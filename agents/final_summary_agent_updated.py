
from .base_agent import BaseAgent
import pandas as pd
import json
import logging
import os
import re
from typing import Dict, List, Tuple, Optional, Any

# ---- Helpers for coverage rules ------------------------------------------------

_UNIVERSAL_VERTICALS = {"all", "all verticals", "any", "general", "*"}

def _normalize(s: Optional[str]) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()

def _normalize_header(h: str) -> str:
    s = _normalize(h).lower().replace("%", "")
    s = re.sub(r"[_\-]+", " ", s)
    return s

def _parse_coverage(val) -> Optional[float]:
    """Normalize coverage to float in [0,1]. Accepts '80%', '0.8', 80, etc."""
    if pd.isna(val):
        return None
    try:
        s = str(val).strip()
        if s.endswith("%"):
            s = s[:-1].strip()
        s = s.replace(",", "")
        num = float(s)
    except Exception:
        return None
    if 1 < num <= 100:
        num = num / 100.0
    if 0 <= num <= 1:
        return num
    return None

def _standardize_requirement(val: Any) -> Optional[str]:
    if pd.isna(val):
        return None
    s = str(val).strip().lower()
    if s in {"required", "req", "must", "mandatory"} or "require" in s or "must" in s or "mandator" in s:
        return "Required"
    if s in {"nice", "nice to have", "optional", "good to have", "nice-to-have"} or "optional" in s or "nice" in s:
        return "Nice to Have"
    # fallback: title case whatever we got
    return str(val).strip().title()

def load_coverage_rules(csv_path: str) -> pd.DataFrame:
    """Load and normalize the SKU coverage rules CSV."""
    df = pd.read_csv(csv_path)
    # Map headers
    colmap: Dict[str, str] = {}
    for orig in df.columns:
        n = _normalize_header(orig)
        if any(k in n for k in ["attribute", "attribue", "attrib", "attr"]) and "coverage" not in n:
            colmap["attribute"] = orig
        if "vertical" in n:
            colmap["vertical"] = orig
        if any(k in n for k in ["required", "nice to have", "nice", "requirement"]):
            colmap["requirement"] = orig
        if "coverage" in n:
            colmap["ideal_coverage"] = orig

    # Ensure required columns exist
    for k in ["attribute", "vertical", "requirement", "ideal_coverage"]:
        if k not in colmap:
            df[k] = None

    # Rename
    df = df.rename(columns={v: k for k, v in colmap.items() if v in df.columns})
    # Clean
    df["attribute"] = df.get("attribute", pd.Series(dtype=str)).astype(str).map(_normalize)
    df["vertical"] = df.get("vertical", pd.Series(dtype=str)).astype(str).map(_normalize)
    df["requirement"] = df.get("requirement", pd.Series(dtype=str)).map(_standardize_requirement)
    df["ideal_coverage"] = df.get("ideal_coverage", pd.Series(dtype=object)).map(_parse_coverage)

    # Drop empty rows
    df = df[ df["attribute"].astype(bool) ]
    return df[["attribute", "vertical", "requirement", "ideal_coverage"]].reset_index(drop=True)

def _is_universal(v: str) -> bool:
    return _normalize(v).lower() in _UNIVERSAL_VERTICALS


def rules_for_vertical(rules: pd.DataFrame, vertical: Optional[str]) -> pd.DataFrame:
    """
    Select rules for a given vertical with override semantics:
    - "All Verticals" (or synonyms) act as a baseline.
    - If a vertical-specific rule exists for the same attribute, it OVERRIDES the universal baseline.
      This allows exemptions: e.g., Beauty requires "Product Group" but CnG overrides it to not required.
    """
    if not vertical:
        vertical = ""
    v = _normalize(vertical).lower()

    # Build masks on the original frame
    is_universal_mask = rules["vertical"].map(lambda x: _is_universal(x))
    is_specific_mask = rules["vertical"].str.lower() == v

    subset = rules[is_universal_mask | is_specific_mask].copy()

    # Priority: specific (1) overrides universal (0)
    import numpy as np
    subset["__priority__"] = np.where(is_specific_mask.loc[subset.index], 1, 0)

    # Sort so specific rows come first per attribute, then drop dup attributes
    subset = subset.sort_values(["attribute", "__priority__"], ascending=[True, False])
    subset = subset.drop_duplicates(subset=["attribute"], keep="first")
    subset = subset.drop(columns=["__priority__"])

    return subset


# ---- Extraction from the app's context ----------------------------------------

def _deep_find_first_key(data: Any, targets: List[str]) -> Optional[Any]:
    """Recursively search dict/list for the first matching key in `targets`."""
    seen = set()
    def _walk(node):
        if id(node) in seen:
            return None
        seen.add(id(node))
        if isinstance(node, dict):
            # primary keys
            for t in targets:
                for k in node.keys():
                    if str(k).lower() == t.lower():
                        return node[k]
            # nested
            for v in node.values():
                out = _walk(v)
                if out is not None:
                    return out
        elif isinstance(node, list):
            for it in node:
                out = _walk(it)
                if out is not None:
                    return out
        return None
    return _walk(data)

def infer_vertical(full_report: dict, summary_df: Optional[pd.DataFrame]) -> Optional[str]:
    # Try different likely keys
    candidates = _deep_find_first_key(full_report, [
        "vertical", "detected_vertical", "primary_vertical", "merchant_vertical", "category_vertical"
    ])
    if isinstance(candidates, str):
        return candidates
    # Try DataFrame
    if summary_df is not None:
        for col in summary_df.columns:
            if str(col).lower() in {"vertical", "detected_vertical", "merchant_vertical"}:
                vals = summary_df[col].dropna().unique().tolist()
                if len(vals) == 1:
                    return str(vals[0])
    return None

def collect_attribute_coverage(summary_df: Optional[pd.DataFrame], full_report: dict) -> Dict[str, float]:
    """
    Heuristics to collect per-attribute coverage (0..1).
    Looks for:
      - full_report["attribute_coverage"] = { attribute: float }
      - full_report["coverage"]["attributes"] = { attribute: float }
      - summary_df having columns ['Attribute','Coverage'] or similar.
    """
    # 1) Direct map in full_report
    for path in [
        ["attribute_coverage"],
        ["coverage", "attributes"],
        ["attributes", "coverage"],
    ]:
        node = full_report
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and isinstance(node, dict):
            # normalize keys
            out = {}
            for k,v in node.items():
                try:
                    out[_normalize(k).lower()] = float(v)
                except Exception:
                    continue
            if out:
                return out

    # 2) Try DataFrame
    if summary_df is not None:
        cols = {c.lower(): c for c in summary_df.columns}
        attr_col = None
        cov_col = None
        for c in summary_df.columns:
            n = c.lower()
            if "attribute" in n and "coverage" not in n:
                attr_col = c
            if "coverage" in n:
                cov_col = c
        if attr_col and cov_col:
            out = {}
            for _, row in summary_df[[attr_col, cov_col]].dropna().iterrows():
                try:
                    out[_normalize(row[attr_col]).lower()] = float(row[cov_col])
                except Exception:
                    continue
            if out:
                return out

    return {}

def evaluate_against_rules(attr_cov: Dict[str, float], rules: pd.DataFrame) -> Dict[str, Any]:
    """
    Compare provided attribute coverage against the vertical rules.
    Returns a dict with pass/fail lists and counts.
    """
    required_fails: List[Dict[str, Any]] = []
    required_passes: List[Dict[str, Any]] = []
    nice_to_have_issues: List[Dict[str, Any]] = []
    unknown_required: List[Dict[str, Any]] = []

    for _, r in rules.iterrows():
        attr = str(r["attribute"]).strip()
        req = r["requirement"]
        thr = r["ideal_coverage"]
        key = _normalize(attr).lower()
        cov = attr_cov.get(key, None)

        record = {"attribute": attr, "coverage": cov, "threshold": thr, "requirement": req}

        if req == "Required":
            if cov is None:
                unknown_required.append(record)
            elif thr is not None and cov < thr:
                required_fails.append(record)
            else:
                required_passes.append(record)
        else:  # Nice to Have / other
            if cov is not None and thr is not None and cov < thr:
                nice_to_have_issues.append(record)

    all_required_ok = (len(required_fails) == 0) and (len(unknown_required) == 0)
    return {
        "required_passes": required_passes,
        "required_fails": required_fails,
        "required_unknown": unknown_required,
        "nice_to_have_issues": nice_to_have_issues,
        "all_required_ok": all_required_ok,
    }

# ---- Agent implementation ------------------------------------------------------

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Final Summary")
        self.model = "gpt-5-chat-latest"  # Use the most capable model for the final decision

    def assess(self, summary_df: pd.DataFrame, full_report: dict, api_key: str = None) -> dict:
        """
        Use sku_coverage.csv rules to determine GP eligibility and generate a concise summary.
        This method will:
          1) Load rules from CSV (env SKU_COVERAGE_CSV, full_report['config']['sku_coverage_path'], or default '/mnt/data/sku_coverage.csv').
          2) Infer vertical from full_report/summary_df (falls back to universal rules).
          3) Gather attribute coverage values from previous agents.
          4) Evaluate pass/fail against required thresholds.
          5) Call the model to produce a crisp human-readable summary (plus a structured fallback).
        """
        logging.info("Running Final Summary Agent with CSV-driven rules...")

        # 1) Load rules
        csv_path = (
            full_report.get("config", {}).get("sku_coverage_path")
            or os.environ.get("SKU_COVERAGE_CSV")
            or "/mnt/data/sku_coverage.csv"
        )
        try:
            rules_df = load_coverage_rules(csv_path)
        except Exception as e:
            logging.exception("Failed to load coverage rules from %s", csv_path)
            # Fallback: preserve previous behavior if we can't load rules
            return {"eligibility_score": "Error", "reasons": [f"Failed to load coverage rules: {e}"]}

        # 2) Vertical
        vertical = infer_vertical(full_report, summary_df)
        applicable_rules = rules_for_vertical(rules_df, vertical)

        # 3) Attribute coverage values
        attr_cov = collect_attribute_coverage(summary_df, full_report)

        # 4) Evaluate
        eval_out = evaluate_against_rules(attr_cov, applicable_rules)

        # Deterministic eligibility decision
        if eval_out["all_required_ok"]:
            eligibility = "Eligible for GP"
        else:
            eligibility = "Not Eligible for GP"

        # Build a compact, structured context for the LLM to turn into nice prose
        llm_context = {
            "vertical": vertical or "Unknown",
            "eligibility_by_rules": eligibility,
            "counts": {
                "required_pass": len(eval_out["required_passes"]),
                "required_fail": len(eval_out["required_fails"]),
                "required_unknown": len(eval_out["required_unknown"]),
                "nice_to_have_issues": len(eval_out["nice_to_have_issues"]),
                "total_rules": int(len(applicable_rules)),
            },
            "failed_required": eval_out["required_fails"],
            "unknown_required": eval_out["required_unknown"],
            "nice_to_have_issues": eval_out["nice_to_have_issues"],
        }

        # 5) Prompt the model for a concise final message (but we still return deterministic eligibility)
        prompt = f"""
You are a senior data quality reviewer for grocery product (GP) ingestion.
Given the CSV-driven gating rules and measured coverage, write a brief final assessment.
Be decisive and specific about which REQUIRED attributes failed thresholds.

Return a JSON object with exactly these fields:
- "eligibility_score": one of ["Eligible for GP", "Not Eligible for GP"]
- "reasons": array of 2-6 short bullet strings focused on the most important gaps
- "notes": short string with any caveats (e.g., unknown required attributes)

Here is the evaluation context (JSON):
```json
{json.dumps(llm_context, ensure_ascii=False)}
```

Guidance:
- If any REQUIRED attribute failed its threshold OR is unknown, set "eligibility_score" to "Not Eligible for GP".
- Group nice-to-have shortfalls under a single bullet unless they are few and critical.
- Keep language factual and actionable (e.g., "Brand coverage 0.62 < 0.80 threshold").
"""

        ai_response = self.call_ai(prompt, api_key, self.model)

        # Robustness: if model fails, fall back to the deterministic decision
        if isinstance(ai_response, dict) and "eligibility_score" in ai_response:
            return {
                "eligibility_score": ai_response.get("eligibility_score", eligibility),
                "reasons": ai_response.get("reasons", []),
                "notes": ai_response.get("notes", ""),
                "vertical": vertical or "Unknown",
                "rule_source_csv": csv_path,
            }

        # Model failed or returned text -> graceful fallback
        reasons: List[str] = []
        if eval_out["required_fails"]:
            reasons.append(
                f"{len(eval_out['required_fails'])} required attribute(s) below threshold."
            )
        if eval_out["required_unknown"]:
            reasons.append(
                f"{len(eval_out['required_unknown'])} required attribute(s) missing coverage data."
            )
        if eval_out["nice_to_have_issues"]:
            reasons.append(
                f"{len(eval_out['nice_to_have_issues'])} nice-to-have attribute(s) below threshold."
            )
        if not reasons:
            reasons = ["All required attributes meet or exceed thresholds."]

        return {
            "eligibility_score": eligibility,
            "reasons": reasons,
            "notes": "LLM summary unavailable; returned deterministic result.",
            "vertical": vertical or "Unknown",
            "rule_source_csv": csv_path,
        }
