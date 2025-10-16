import logging
import json
import pandas as pd
import yaml
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional
from .base_agent import BaseAgent


class Agent(BaseAgent):
    """
    Exclusion / Restricted-Items Agent

    - "Absolute" prohibitions => Auto Exclude (e.g., weapons, fireworks, lottery, subscriptions, gift cards).
    - "Restricted but allowed with flags" => Alcohol, CBD/THC, Nicotine/Vape, OTC meds.
      * If merchant flag is True => "Restricted (Compliant)" (no exclusion).
      * If keywords suggest restricted but flag missing/False => "Review (Missing Flag)".

    AI step:
      * Receives merchant flags and category context.
      * Returns structured JSON with recommended_action: auto_exclude | review | ignore.
      * We write to ExclusionDecision and explanatory text, but do not hard-block allowed items solely from AI.
    """

    def __init__(self):
        super().__init__("Exclusion")
        self.model = "gpt-5-chat-latest"
        self.issue_column = "ExclusionIssues?"
        self.decision_column = "ExclusionDecision"
        self.batch_size = 40
        self.cache: Dict[str, Dict[str, Any]] = {}

        # Load guidelines & structured rules
        self.guidelines_text, self.rules = self._load_restriction_rules()

        # Fallback keyword sets (used if YAML is missing or incomplete)
        self.absolute_keywords = {"weapon", "fireworks", "lottery", "subscription", "gift card", "giftcard"}
        self.flagged_groups = {
            "alcohol": {"keywords": {"alcohol", "beer", "wine", "whiskey", "vodka", "tequila", "rum"}},
            "cbd_thc": {"keywords": {"cbd", "thc", "hemp", "cannabis"}},
            "nicotine": {"keywords": {"nicotine", "vape", "e-cigarette", "ecig", "e cig", "tobacco"}},
            "otc_med": {"keywords": {"cough", "dextromethorphan", "pseudoephedrine", "guaifenesin", "cold medicine", "antihistamine"}}
        }
        self.flag_columns = {
            "alcohol": "IS_ALCOHOL",
            "cbd_thc": "IS_CBD",
            "nicotine": "IS_NICOTINE",
            "otc_med": "IS_OTC_MED"
        }

    # -------------------- Public API --------------------

    def assess(self, df: pd.DataFrame, api_key: str = None) -> pd.DataFrame:
        logging.info(f"Running {self.attribute_name} Agent...")

        # Ensure required columns exist
        if self.issue_column not in df.columns:
            df[self.issue_column] = ""
        if self.decision_column not in df.columns:
            df[self.decision_column] = ""

        # 1) Manual pass (fast)
        df = self._manual_exclusion_pass(df)

        # 2) AI pass on remaining (optional)
        if not api_key:
            logging.warning("No OpenAI API key provided. Skipping AI exclusion check.")
            return df

        # Unflagged rows only
        unflagged_mask = df[self.issue_column].astype(str).str.strip().eq("")
        if unflagged_mask.sum() == 0:
            logging.info("All rows already flagged or no candidates for AI check.")
            return df

        sample_df = df[unflagged_mask].sample(n=min(1500, unflagged_mask.sum()), random_state=42)
        items_for_prompt, key_to_index = self._make_prompt_items(sample_df)

        new_items = [it for it in items_for_prompt if it["cache_key"] not in self.cache]
        if not new_items:
            logging.info("No new items to send to AI (cache hit).")
            return df

        batches = [new_items[i:i + self.batch_size] for i in range(0, len(new_items), self.batch_size)]
        logging.info(f"Submitting {len(new_items)} un-cached items to AI in {len(batches)} batch(es).")

        with ThreadPoolExecutor() as ex:
            futures = [ex.submit(self._process_batch, batch, api_key) for batch in batches]
            for fut in as_completed(futures):
                results = fut.result() or []
                for rec in results:
                    # rec: { item_name, reason, recommended_action, confidence, cache_key }
                    cache_key = rec.get("cache_key")
                    reason = rec.get("reason", "")
                    action = rec.get("recommended_action", "review")
                    idx = key_to_index.get(cache_key)
                    if idx is None:
                        continue

                    if action == "auto_exclude":
                        df.loc[idx, self.issue_column] += f"⚠️ Auto Exclude (AI): {reason} "
                        df.loc[idx, self.decision_column] = "Auto Exclude"
                    elif action == "review":
                        df.loc[idx, self.issue_column] += f"🤖 AI Suggestion: Review for exclusion. Reason: {reason} "
                        # Don't overwrite a more severe decision if one exists
                        if df.loc[idx, self.decision_column].astype(str).str.strip().eq("").any():
                            df.loc[idx, self.decision_column] = "Review"
                    else:
                        # ignore
                        if df.loc[idx, self.decision_column].astype(str).str.strip().eq("").any():
                            df.loc[idx, self.decision_column] = "Ignore"

                    self.cache[cache_key] = {
                        "reason": reason,
                        "action": action,
                        "confidence": rec.get("confidence", None),
                    }

        # 3) Summarize & return
        manual_flags = int(df[self.issue_column].str.contains("⚠️").sum())
        ai_flags = int(df[self.issue_column].str.contains("🤖").sum())
        logging.info(f"Exclusion assessment complete. Manual flags: {manual_flags}, AI flags: {ai_flags}")
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Returns summary metrics for dashboard cards.
        """
        if self.issue_column not in df.columns:
            logging.warning("Exclusion summary failed: missing issue column.")
            return {"name": self.attribute_name, "issue_count": "N/A"}

        total = len(df)
        auto_exclude = int((df.get(self.decision_column, "") == "Auto Exclude").sum()) if total else 0
        review = int((df.get(self.decision_column, "") == "Review").sum()) if total else 0
        compliant = int((df.get(self.decision_column, "") == "Restricted (Compliant)").sum()) if total else 0
        ignore = int((df.get(self.decision_column, "") == "Ignore").sum()) if total else 0

        # simple category scan
        excluded_categories = []
        if "L1_CATEGORY" in df.columns:
            l1 = df["L1_CATEGORY"].astype(str).str.lower()
            keys = set()
            for w in list(self.absolute_keywords) + ["alcohol", "cbd", "thc", "vape", "nicotine", "lottery", "gift card", "fireworks", "subscription"]:
                mask = l1.str.contains(w, na=False)
                keys.update(df.loc[mask, "L1_CATEGORY"].dropna().unique().tolist())
            excluded_categories = sorted(keys)

        out = {
            "name": self.attribute_name,
            "total_items": total,
            "auto_exclude_count": auto_exclude,
            "review_count": review,
            "restricted_compliant_count": compliant,
            "ignore_count": ignore,
            "issue_percent": (auto_exclude + review) / total * 100 if total else 0.0,
            "excluded_categories_list": excluded_categories,
        }
        logging.info("Exclusion Agent Summary: " + json.dumps(out, indent=2))
        return out

    # -------------------- Internals --------------------

    def _load_restriction_rules(self):
        """
        Loads `restricted_items.yaml` if present.
        Expected shape:
        restrictions:
          - name: Alcohol
            keywords: ["beer","wine","whiskey"]
            flag_column: IS_ALCOHOL
            absolute: false
          - name: Fireworks
            keywords: ["fireworks"]
            absolute: true
        """
        try:
            with open("restricted_items.yaml", "r") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logging.warning(f"Failed to load restricted_items.yaml: {e}")
            data = {}

        rules = data.get("restrictions", [])
        # Make a flattened, human-readable list for the AI guidelines
        flat_lines = []
        for r in rules:
            name = str(r.get("name", "Unknown"))
            abs_ = bool(r.get("absolute", False))
            kw = r.get("keywords", []) or []
            flag_col = r.get("flag_column")
            line = f"{name}: keywords={kw}"
            if abs_:
                line += " (ABSOLUTE prohibition)"
            if flag_col:
                line += f" — requires flag '{flag_col}' if allowed"
            flat_lines.append(line)

            # Mirror into our fallback sets so YAML governs behavior when present
            if abs_:
                for k in kw:
                    self.absolute_keywords.add(k.lower())
            elif flag_col:
                key = None
                lc_flag = str(flag_col).upper()
                if "ALCOHOL" in lc_flag:
                    key = "alcohol"
                elif "CBD" in lc_flag or "THC" in lc_flag:
                    key = "cbd_thc"
                elif "NICOTINE" in lc_flag or "TOBACCO" in lc_flag:
                    key = "nicotine"
                elif "OTC" in lc_flag or "MED" in lc_flag:
                    key = "otc_med"
                if key:
                    self.flag_columns[key] = flag_col.upper()
                    # merge keywords
                    if kw:
                        self.flagged_groups[key]["keywords"].update({w.lower() for w in kw})

        return flat_lines, rules

    def _col_exists(self, df: pd.DataFrame, target_upper: str) -> Optional[str]:
        for c in df.columns:
            if c.upper() == target_upper:
                return c
        return None

    def _bool_from_cell(self, val: Any) -> bool:
        if pd.isna(val):
            return False
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        return s in {"1", "true", "t", "yes", "y"}

    def _manual_exclusion_pass(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Manual first-pass:
          - Auto Exclude if absolute keyword matches (L1/L2/Name).
          - For Alcohol / CBD/THC / Nicotine / OTC meds:
              * If flag True -> Restricted (Compliant)
              * If keyword match and flag False/missing -> Review (Missing Flag)
        """
        # Precompute convenient lowercase strings
        l1 = df.get("L1_CATEGORY", pd.Series("", index=df.index)).astype(str).str.lower()
        l2 = df.get("L2_CATEGORY", pd.Series("", index=df.index)).astype(str).str.lower()
        names = df.get("CONSUMER_FACING_ITEM_NAME", pd.Series("", index=df.index)).astype(str).str.lower()

        # --- 1) Absolute prohibitions => Auto Exclude
        abs_mask = pd.Series(False, index=df.index)
        for kw in self.absolute_keywords:
            if not kw:
                continue
            k = kw.lower()
            abs_mask |= l1.str.contains(k, na=False) | l2.str.contains(k, na=False) | names.str.contains(k, na=False)

        df.loc[abs_mask, self.issue_column] += "⚠️ Auto Exclude (Manual): Absolute prohibition keyword matched. "
        df.loc[abs_mask, self.decision_column] = df.loc[abs_mask, self.decision_column].mask(
            df[self.decision_column].astype(str).str.strip().eq(""), "Auto Exclude"
        )

        # --- 2) Restricted-but-allowed groups
        def handle_group(key: str, df: pd.DataFrame, kws: set, flag_col_name: str):
            if not kws:
                return
            # detect mentions
            mask_kw = pd.Series(False, index=df.index)
            for w in kws:
                w = w.lower()
                mask_kw |= l1.str.contains(w, na=False) | l2.str.contains(w, na=False) | names.str.contains(w, na=False)

            # find the actual column present (case-insensitive)
            col_present = self._col_exists(df, flag_col_name.upper()) if flag_col_name else None

            if col_present:
                flags = df[col_present].apply(self._bool_from_cell)
                # compliant where keyword suggests restricted and flag is True
                compliant_mask = mask_kw & flags
                df.loc[compliant_mask, self.issue_column] += f"ℹ️ Restricted (Compliant): {key.replace('_','/').title()} (merchant flag present). "
                df.loc[compliant_mask, self.decision_column] = df.loc[compliant_mask, self.decision_column].mask(
                    df[self.decision_column].astype(str).str.strip().eq(""), "Restricted (Compliant)"
                )
                # missing flag => review
                review_mask = mask_kw & (~flags)
                df.loc[review_mask, self.issue_column] += f"⚠️ Review: {key.replace('_','/').title()} suspected but missing merchant flag '{flag_col_name}'. "
                df.loc[review_mask, self.decision_column] = df.loc[review_mask, self.decision_column].mask(
                    df[self.decision_column].astype(str).str.strip().eq(""), "Review"
                )
            else:
                # column not present; if keywords match => review
                df.loc[mask_kw, self.issue_column] += f"⚠️ Review: {key.replace('_','/').title()} suspected but flag column '{flag_col_name}' not found. "
                df.loc[mask_kw, self.decision_column] = df.loc[mask_kw, self.decision_column].mask(
                    df[self.decision_column].astype(str).str.strip().eq(""), "Review"
                )

        # alcohol, cbd/thc, nicotine, otc meds
        handle_group("alcohol", df, self.flagged_groups["alcohol"]["keywords"], self.flag_columns.get("alcohol"))
        handle_group("cbd_thc", df, self.flagged_groups["cbd_thc"]["keywords"], self.flag_columns.get("cbd_thc"))
        handle_group("nicotine", df, self.flagged_groups["nicotine"]["keywords"], self.flag_columns.get("nicotine"))
        handle_group("otc_med", df, self.flagged_groups["otc_med"]["keywords"], self.flag_columns.get("otc_med"))

        return df

    def _make_prompt_items(self, sample_df: pd.DataFrame):
        """
        Build the records we send to AI, including merchant flags, and a composite cache key.
        """
        items: List[Dict[str, Any]] = []
        key_to_index: Dict[str, pd.Index] = {}

        # Identify MSID column if present (case-insensitive)
        msid_col = None
        for c in sample_df.columns:
            if c.upper() == "MSID":
                msid_col = c
                break

        for idx, r in sample_df.iterrows():
            name = r.get("CONSUMER_FACING_ITEM_NAME", "")
            msid = str(r.get(msid_col, "")) if msid_col else ""
            cache_key = f"{msid}|{name}".strip("|")

            # Compose AI item object
            item = {
                "cache_key": cache_key,
                "item_name": name,
                "l1": r.get("L1_CATEGORY", ""),
                "l2": r.get("L2_CATEGORY", ""),
                # merchant flags (robust)
                "is_alcohol": self._bool_from_cell(r.get(self._col_exists(sample_df, "IS_ALCOHOL") or "", False)),
                "is_cbd": self._bool_from_cell(r.get(self._col_exists(sample_df, "IS_CBD") or "", False)),
                "is_nicotine": self._bool_from_cell(r.get(self._col_exists(sample_df, "IS_NICOTINE") or "", False)),
                "is_otc_med": self._bool_from_cell(r.get(self._col_exists(sample_df, "IS_OTC_MED") or "", False)),
            }
            items.append(item)
            key_to_index[cache_key] = idx

        return items, key_to_index

    def _process_batch(self, batch_items: List[Dict[str, Any]], api_key: str) -> List[Dict[str, Any]]:
        """
        Call AI for a batch; return normalized records:
        [{ item_name, reason, recommended_action, confidence, cache_key }, ...]
        """
        try:
            prompt = self._create_ai_prompt(batch_items)
            resp = self.call_ai(prompt, api_key, self.model)
            data = self._parse_ai_response(resp)
            out = []
            for it in data.get("excluded_items", []):
                # carry through cache_key from our input
                name = it.get("item_name", "")
                # Find the original cache_key by matching name (best-effort)
                ck = None
                for bi in batch_items:
                    if bi.get("item_name") == name:
                        ck = bi.get("cache_key")
                        break
                out.append({
                    "cache_key": ck or name,
                    "item_name": name,
                    "reason": it.get("reason", ""),
                    "recommended_action": it.get("recommended_action", "review"),
                    "confidence": it.get("confidence", None),
                })
            return out
        except Exception as e:
            logging.error(f"Batch processing failed: {e}", exc_info=True)
            return []

    def _parse_ai_response(self, response: Any) -> Dict[str, Any]:
        if isinstance(response, dict):
            return response
        try:
            return json.loads(response)
        except Exception:
            logging.error("Failed to parse AI response as JSON.", exc_info=True)
            return {"excluded_items": []}

    def _create_ai_prompt(self, items_for_ai: list) -> str:
        # Render guidelines (flattened) for the model
        guidelines_str = "\n- " + "\n- ".join(self.guidelines_text) if self.guidelines_text else "\n- Follow DoorDash marketplace policies and local laws."

        # Explain the decision logic
        return f"""
You are a DoorDash compliance analyst. Decide exclusion for each product using the rules below.

**Policies Overview:**
{guidelines_str}

**Decision Policy:**
1) If an item is an ABSOLUTE prohibition (e.g., weapons, fireworks, lottery, subscriptions, gift cards), return "auto_exclude".
2) For regulated categories allowed on DoorDash with proper controls:
   - Alcohol, CBD/THC, Nicotine/Vape, OTC Medications
   - If corresponding merchant flag is TRUE (e.g., is_alcohol==true), consider it "ignore" (already flagged as restricted/compliant in tooling) unless other policies are violated.
   - If keywords imply a restricted category but the merchant flag is FALSE or missing, return "review".
3) If not prohibited or restricted, return "ignore".

**Return ONLY valid JSON** with this schema:
{{
  "excluded_items": [
    {{
      "item_name": "exact item name from input",
      "reason": "short reason grounded in policy/keywords/flags",
      "recommended_action": "auto_exclude" | "review" | "ignore",
      "confidence": 0.0
    }}
  ]
}}

Here is the input array (include all fields when deciding):
{json.dumps(items_for_ai, indent=2, ensure_ascii=False)}
"""