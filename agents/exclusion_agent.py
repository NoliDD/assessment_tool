# agents/exclusion_agent.py
import logging
import json
import re
from typing import Dict, List, Optional

import pandas as pd
import yaml

from .base_agent import BaseAgent


class Agent(BaseAgent):
    """
    Exclusion Agent (hybrid rules + AI)
    -----------------------------------
    Responsibilities:
      1) Fast manual pass:
         - Absolute prohibitions => Auto Exclude
         - Restricted-but-allowed (Alcohol, CBD/THC, Nicotine/NRT, OTC meds) =>
             * "Restricted (Compliant)" if merchant flag present
             * "Review" if keyword suggests restricted but flag missing/false
      2) AI pass (optional; default on):
         - Only for ambiguous/Review/empty decisions
         - Returns {allow|review|exclude} + reason + confidence
         - Apply if confidence >= threshold (else keep Review)

    Notes:
      - Uses word-boundary regex matching to avoid substring false positives
        (e.g., "gin" should not match in "original").
      - Honors common flag columns (case-insensitive): IS_ALCOHOL, IS_CBD,
        IS_NICOTINE, IS_OTC_MED (auto-detects if present).
      - Keeps an audit trail in self.issue_column.
    """

    def __init__(self):
        super().__init__("Exclusion")
        self.model = "gpt-5-chat-latest"

        # Output columns
        self.issue_column = "ExclusionIssues?"
        self.decision_column = "ExclusionDecision"

        # Controls for AI hand-off
        self.use_ai_for_ambiguous = True
        self.ai_confidence_threshold = 0.70
        self.ai_batch_size = 50
        self.max_ai_items = 1500

        # Merchant flag canonical names (we auto-detect case-insensitive)
        self.flag_columns: Dict[str, str] = {
            "alcohol": "IS_ALCOHOL",
            "cbd_thc": "IS_CBD",
            "nicotine": "IS_NICOTINE",     # nicotine / NRT
            "otc_med": "IS_OTC_MED",       # cough/cold/pain OTC gating if you use it
        }

        # Load guidelines/keywords from YAML and heuristics
        self.guidelines = self._load_guidelines()
        self.absolute_keywords: List[str] = self._build_absolute_keywords(self.guidelines)
        self.flagged_groups = self._build_flagged_groups(self.guidelines)

        # Small safety defaults if YAML is very sparse
        if not self.flagged_groups["alcohol"]["keywords"]:
            self.flagged_groups["alcohol"]["keywords"] = {
                "beer", "wine", "vodka", "gin", "whiskey", "whisky",
                "tequila", "bourbon", "rum", "brandy", "cider",
                "seltzer", "liqueur", "mezcal", "sauvignon", "merlot",
                "cabernet", "pinot", "ipa", "stout", "lager", "pilsner",
            }

        # Cache AI decisions: key -> {decision, reason, confidence}
        self.cache: Dict[str, Dict[str, object]] = {}

    # ---------------------------------------------------------------------
    # Public entrypoint
    # ---------------------------------------------------------------------
    def assess(self, df: pd.DataFrame, api_key: str = None) -> pd.DataFrame:
        logging.info(f"Running {self.attribute_name} Agent...")

        # Ensure columns exist
        if self.issue_column not in df.columns:
            df[self.issue_column] = ""
        if self.decision_column not in df.columns:
            df[self.decision_column] = ""

        # Manual fast pass
        df = self._manual_exclusion_pass(df)

        # AI pass (optional)
        if self.use_ai_for_ambiguous and api_key:
            amb_mask = self._ambiguous_mask(df)
            if amb_mask.any():
                logging.info("Running AI review for ambiguous/review rows...")
                # Build items for AI (capped)
                items = self._gather_ai_items(df[amb_mask])
                if self.max_ai_items:
                    items = items[: self.max_ai_items]

                # Batch to reduce token spikes
                results = {}
                for i in range(0, len(items), self.ai_batch_size):
                    batch = items[i : i + self.ai_batch_size]
                    batch_res = self._ai_review(batch, api_key=api_key)
                    for rkey, rval in batch_res.items():
                        results[rkey] = rval

                # Apply AI decisions to DataFrame
                self._apply_ai_decisions(df, amb_mask, results)

        # Final logging
        n_auto = int((df[self.decision_column] == "Auto Exclude").sum())
        n_comp = int((df[self.decision_column] == "Restricted (Compliant)").sum())
        n_rev  = int((df[self.decision_column] == "Review").sum())
        n_allow = int((df[self.decision_column] == "Allow").sum())
        logging.info(f"Exclusion summary: Auto Exclude={n_auto}, Restricted (Compliant)={n_comp}, Review={n_rev}, Allow={n_allow}")

        return df

    # ---------------------------------------------------------------------
    # Manual pass (deterministic)
    # ---------------------------------------------------------------------
    def _manual_exclusion_pass(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        - Absolute prohibitions -> Auto Exclude
        - Restricted-but-allowed groups -> Respect merchant flags or mark Review
        """
        issue_col = self.issue_column
        decision_col = self.decision_column

        # Helpers
        def set_if_empty(mask: pd.Series, value: str):
            empty = df[decision_col].astype(str).str.strip().eq("")
            df.loc[mask & empty, decision_col] = value

        # Lowercased series for matching (aligned indexes)
        l1 = df.get("L1_CATEGORY", pd.Series("", index=df.index)).astype(str).str.lower()
        l2 = df.get("L2_CATEGORY", pd.Series("", index=df.index)).astype(str).str.lower()
        names = df.get("CONSUMER_FACING_ITEM_NAME", pd.Series("", index=df.index)).astype(str).str.lower()

        # 1) Absolute prohibitions => Auto Exclude
        abs_mask = pd.Series(False, index=df.index)
        for kw in self.absolute_keywords:
            abs_mask |= (self._kw_mask(l1, kw) | self._kw_mask(l2, kw) | self._kw_mask(names, kw))

        df.loc[abs_mask, issue_col] += "⚠️ Auto Exclude (Manual): Absolute prohibition keyword matched. "
        set_if_empty(abs_mask, "Auto Exclude")

        # 2) Restricted-but-allowed: honor merchant flags
        def handle_group(group_key: str):
            kws: set = self.flagged_groups[group_key]["keywords"]
            if not kws:
                return

            mask_kw = pd.Series(False, index=df.index)
            for w in kws:
                mask_kw |= (self._kw_mask(l1, w) | self._kw_mask(l2, w) | self._kw_mask(names, w))

            # Find the merchant flag column (case-insensitive) for the group
            desired = self.flag_columns.get(group_key)  # canonical desired name
            col_present = self._find_flag_col(df, desired) if desired else None

            if col_present:
                flags = df[col_present].apply(self._bool_from_cell)
                compliant_mask = mask_kw & flags
                review_mask = mask_kw & (~flags)

                df.loc[compliant_mask, issue_col] += f"ℹ️ Restricted (Compliant): {group_key.replace('_','/').title()} (merchant flag present). "
                set_if_empty(compliant_mask, "Restricted (Compliant)")

                df.loc[review_mask, issue_col] += f"⚠️ Review: {group_key.replace('_','/').title()} suspected but missing merchant flag '{desired}'. "
                set_if_empty(review_mask, "Review")
            else:
                # No flag column at all → review if keywords match
                df.loc[mask_kw, issue_col] += f"⚠️ Review: {group_key.replace('_','/').title()} suspected but flag column '{desired}' not found. "
                set_if_empty(mask_kw, "Review")

        handle_group("alcohol")
        handle_group("cbd_thc")
        handle_group("nicotine")
        handle_group("otc_med")

        return df

    # ---------------------------------------------------------------------
    # AI hand-off (only for ambiguous)
    # ---------------------------------------------------------------------
    def _ambiguous_mask(self, df: pd.DataFrame) -> pd.Series:
        dec = df[self.decision_column].astype(str).str.strip().str.lower()
        return dec.eq("") | dec.eq("review")

    def _item_key(self, row: pd.Series) -> str:
        # stable cache key across runs
        return "|".join([
            str(row.get("CONSUMER_FACING_ITEM_NAME", "")).strip().lower(),
            str(row.get("L1_CATEGORY", "")).strip().lower(),
            str(row.get("L2_CATEGORY", "")).strip().lower(),
            str(row.get("IS_ALCOHOL", "")),
            str(row.get("IS_CBD", "")),
            str(row.get("IS_NICOTINE", "")),
            str(row.get("IS_OTC_MED", "")),
        ])

    def _gather_ai_items(self, df_part: pd.DataFrame) -> List[dict]:
        cols = [
            "CONSUMER_FACING_ITEM_NAME", "L1_CATEGORY", "L2_CATEGORY",
            "IS_ALCOHOL", "IS_CBD", "IS_NICOTINE", "IS_OTC_MED"
        ]
        present = [c for c in cols if c in df_part.columns]
        items = []
        for _, row in df_part[present].iterrows():
            key = self._item_key(row)
            if key in self.cache:
                continue
            items.append({
                "item_name": row.get("CONSUMER_FACING_ITEM_NAME", ""),
                "l1_category": row.get("L1_CATEGORY", ""),
                "l2_category": row.get("L2_CATEGORY", ""),
                "is_alcohol_flag": row.get("IS_ALCOHOL", None),
                "is_cbd_flag": row.get("IS_CBD", None),
                "is_nicotine_flag": row.get("IS_NICOTINE", None),
                "is_otc_med_flag": row.get("IS_OTC_MED", None),
            })
        return items

    def _build_ai_prompt(self, items_for_ai: List[dict]) -> str:
        guidance = """
You are a DoorDash compliance checker. Classify each item as one of:
- "exclude": absolutely prohibited (e.g., weapons, illegal drugs, non-pilot gift cards).
- "review": potentially restricted but unclear; needs human review OR requires a missing merchant flag.
- "allow": allowed for sale (including restricted-but-compliant when the correct merchant flag is present).

Rules:
1) Do NOT classify alcohol, CBD/THC, nicotine/NRT, or typical OTC meds as "exclude" by default. They are allowed when the correct merchant flag is present.
2) If the item appears to be alcohol but is_alcohol_flag is false or null → "review" with reason "Alcohol suspected but missing flag".
3) Same logic for CBD/THC (is_cbd_flag), nicotine/NRT (is_nicotine_flag), and OTC cough/cold/pain meds (is_otc_med_flag).
4) Avoid substring mistakes (do not infer alcohol from letters inside unrelated words: "gin" in "original", "ale" in "wholesale", etc.). Match whole words and use category context.
5) If L1/L2 are clearly non-restricted (e.g., Snacks > Chips), that should overrule stray name fragments.

Return ONLY valid JSON with this exact schema:
{
  "results": [
    {
      "item_name": "...",
      "decision": "allow|review|exclude",
      "reason": "short reason referencing the rules/flags",
      "confidence": 0.0
    }
  ]
}
"""
        return f"{guidance}\n\nINPUT:\n{json.dumps(items_for_ai, ensure_ascii=False, indent=2)}"

    def _ai_review(self, items: List[dict], api_key: str) -> Dict[str, dict]:
        if not items:
            return {}
        prompt = self._build_ai_prompt(items)
        raw = self.call_ai(prompt, api_key, self.model)

        if isinstance(raw, dict):
            data = raw
        else:
            try:
                data = json.loads(raw)
            except Exception:
                logging.error("AI response not valid JSON for exclusion review.")
                return {}

        out = {}
        for r in data.get("results", []):
            nm = str(r.get("item_name", "")).strip().lower()
            out[nm] = {
                "decision": str(r.get("decision", "review")).lower(),
                "reason": r.get("reason", ""),
                "confidence": float(r.get("confidence", 0.0)),
            }
            self.cache[nm] = out[nm]
        return out

    def _apply_ai_decisions(self, df: pd.DataFrame, mask: pd.Series, results: Dict[str, dict]):
        issue_col = self.issue_column
        decision_col = self.decision_column
        thr = self.ai_confidence_threshold

        def norm(s): return str(s).strip().lower()

        for idx in df[mask].index:
            nm = norm(df.at[idx, "CONSUMER_FACING_ITEM_NAME"])
            r = results.get(nm)
            if not r:
                continue
            dec, reason, conf = r["decision"], r["reason"], r["confidence"]

            # Preserve earlier manual/absolute decisions; append AI note
            if str(df.at[idx, decision_col]).strip():
                df.at[idx, issue_col] += f" 🤖 AI note: {reason} (conf {conf:.2f})."
                continue

            if conf >= thr:
                if dec == "exclude":
                    df.at[idx, decision_col] = "Auto Exclude"
                    df.at[idx, issue_col] += f" 🤖 Exclude: {reason} (conf {conf:.2f})."
                elif dec == "allow":
                    df.at[idx, decision_col] = "Allow"
                    df.at[idx, issue_col] += f" 🤖 Allow: {reason} (conf {conf:.2f})."
                else:
                    df.at[idx, decision_col] = "Review"
                    df.at[idx, issue_col] += f" 🤖 Review: {reason} (conf {conf:.2f})."
            else:
                df.at[idx, decision_col] = "Review"
                df.at[idx, issue_col] += f" 🤖 Low confidence: {reason} (conf {conf:.2f})."

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------
    def _kw_mask(self, s: pd.Series, kw: str) -> pd.Series:
        """Whole-word/phrase matching to avoid false positives."""
        kw = str(kw).strip().lower()
        if not kw:
            return pd.Series(False, index=s.index)
        pattern = r"\b" + re.escape(kw) + r"\b"
        try:
            return s.str.contains(pattern, regex=True, case=False, na=False)
        except re.error:
            return s.str.contains(kw, case=False, na=False)

    def _bool_from_cell(self, v) -> bool:
        """Parse truthy/falsey variants robustly."""
        if pd.isna(v):
            return False
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        return s in {"1", "true", "t", "yes", "y"}

    def _find_flag_col(self, df: pd.DataFrame, desired_upper: Optional[str]) -> Optional[str]:
        """Find a flag column by case-insensitive exact name or common synonyms."""
        if not desired_upper:
            return None
        desired_upper = desired_upper.upper()

        # 1) Case-insensitive exact match
        for c in df.columns:
            if c.upper() == desired_upper:
                return c

        # 2) Common synonyms per group
        synonyms = {
            "IS_ALCOHOL": {"ALCOHOL", "IS-ALCOHOL", "AGE_RESTRICTED", "IS_AGE_RESTRICTED"},
            "IS_CBD": {"CBD", "IS-CBD", "IS_HEMP", "HEMP", "THC", "IS_THC"},
            "IS_NICOTINE": {"NICOTINE", "IS-NICOTINE", "NRT", "TOBACCO", "IS_TOBACCO"},
            "IS_OTC_MED": {"OTC", "OTC_MED", "OTC-MED", "IS_OTC", "COUGH_COLD", "COUGH/COLD"},
        }
        for c in df.columns:
            cu = c.upper()
            for want, syns in synonyms.items():
                if desired_upper == want and (cu == want or cu in syns):
                    return c
        return None

    # ---------------------------------------------------------------------
    # Guidelines / YAML parsing
    # ---------------------------------------------------------------------
    def _load_guidelines(self) -> List[str]:
        """
        Loads `restricted_items.yaml` if present. The provided sample is a simple list:
           restrictions:
             - Tobacco/Vape products, E-cigarettes, Nicotine Pouches (unless merchant has addendum)
             - Products containing HHC or Kratom
             - Gift Cards (unless part of pilot)
             ...
        We keep the raw strings; later we heuristically map them to groups/keywords.
        """
        try:
            with open("restricted_items.yaml", "r") as f:
                data = yaml.safe_load(f) or {}
                lst = data.get("restrictions", [])
                out = []
                for item in lst:
                    if isinstance(item, str):
                        out.append(item)
                    elif isinstance(item, dict):
                        for k, v in item.items():
                            out.append(f"{k}: {v}")
                    elif isinstance(item, list):
                        out.extend([str(x) for x in item])
                return out
        except Exception as e:
            logging.warning(f"Failed to load restricted_items.yaml: {e}")
            return []

    def _build_absolute_keywords(self, raw: List[str]) -> List[str]:
        """Heuristics: extract absolute prohibitions keywords from freeform strings."""
        absolute = set()
        text = " | ".join(x.lower() for x in raw)
        # Obvious absolutes (non-pilot gift cards, weapons, live animals (non-food), fireworks, etc.)
        if "gift card" in text:
            absolute |= {"gift card", "gift cards", "itunes card", "prepaid card"}
        for kw in ["weapon", "weapons", "ammo", "ammunition", "firearm", "gun", "taser", "pepper spray",
                   "fireworks", "explosive", "grenade", "live animals", "lottery", "donation", "tips", "dry ice",
                   "deposit items", "rental items", "water refills", "mlm", "propane tank refills"]:
            if kw in text:
                absolute.add(kw)
        # Kratom/HHC (if you want absolute)
        if "kratom" in text:
            absolute.add("kratom")
        if "hhc" in text:
            absolute.add("hhc")
        # Phones / prepaid phones sometimes absolute
        if "prepaid phone" in text:
            absolute |= {"prepaid phone", "prepaid phones"}
        # Magazines/Newspapers commonly restricted -> treat as absolute if your policy requires
        if "magazine" in text or "newspaper" in text:
            absolute |= {"magazine", "magazines", "newspaper", "newspapers"}

        # De-duplicate and return
        return sorted(absolute)

    def _build_flagged_groups(self, raw: List[str]) -> Dict[str, Dict[str, set]]:
        """
        Build keyword sets for restricted-but-allowed groups from freeform lines.
        """
        text = " | ".join(x.lower() for x in raw)

        alcohol_kws = set()  # defaults are added in __init__ if empty
        cbd_kws = set()
        if "hemp" in text or "cannabis" in text or "thc" in text or "delta-8" in text or "delta-10" in text:
            cbd_kws |= {"hemp", "cannabis", "thc", "delta-8", "delta-10", "delta 8", "delta 10", "cbd"}

        nicotine_kws = set()
        if "tobacco" in text or "vape" in text or "nicotine" in text or "e-cigarette" in text:
            nicotine_kws |= {"tobacco", "vape", "nicotine", "e-cigarette", "ecigarette", "e cigarette", "e-cigs", "nicotine pouch", "nrt"}

        otc_kws = set()
        if "pseudoephedrine" in text or "pse" in text or "cough" in text or "dex" in text or "dextromethorphan" in text:
            otc_kws |= {"pseudoephedrine", "pse", "cough", "cold", "cough syrup", "dextromethorphan", "dxm", "paracetamol", "acetaminophen", "ibuprofen", "naproxen"}

        return {
            "alcohol":  {"keywords": alcohol_kws},
            "cbd_thc":  {"keywords": cbd_kws},
            "nicotine": {"keywords": nicotine_kws},
            "otc_med":  {"keywords": otc_kws},
        }

    # ---------------------------------------------------------------------
    # Summary (optional UI)
    # ---------------------------------------------------------------------
    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Returns a summary useful for dashboards.
        """
        if self.issue_column not in df.columns or self.decision_column not in df.columns:
            logging.warning("Exclusion summary failed: required columns missing.")
            return {
                "name": self.attribute_name,
                "issue_count": "N/A", "issue_percent": 0,
                "auto_exclude": 0, "restricted_compliant": 0, "review": 0, "allow": 0,
            }

        total = len(df) or 1
        auto_exclude = int((df[self.decision_column] == "Auto Exclude").sum())
        restricted_compliant = int((df[self.decision_column] == "Restricted (Compliant)").sum())
        review = int((df[self.decision_column] == "Review").sum())
        allow = int((df[self.decision_column] == "Allow").sum())

        # Manual vs AI signals for quick telemetry
        manual_flags = int(df[self.issue_column].str.contains("⚠️", na=False).sum())
        ai_flags = int(df[self.issue_column].str.contains("🤖", na=False).sum())

        return {
            "name": self.attribute_name,
            "issue_count": manual_flags + ai_flags,
            "issue_percent": ((manual_flags + ai_flags) / total) * 100.0,
            "auto_exclude": auto_exclude,
            "restricted_compliant": restricted_compliant,
            "review": review,
            "allow": allow,
            "manual_flags": manual_flags,
            "ai_flags": ai_flags,
        }