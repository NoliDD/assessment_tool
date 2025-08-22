from .base_agent import BaseAgent
import pandas as pd
import json
import logging
import os
import re
from typing import Dict, List, Tuple, Optional, Any
import numpy as np

# ---- Helpers for coverage rules ------------------------------------------------

_UNIVERSAL_VERTICALS = {"all", "all verticals", "any", "general", "*"}

def _normalize(s: Optional[str]) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()

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
    if s in {"not applicable", "n/a", "not required"}:
        return "Not Applicable"
    # fallback: title case whatever we got
    return str(val).strip().title()

def load_coverage_rules(json_path: str) -> pd.DataFrame:
    """Load and normalize the SKU coverage rules JSON file."""
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
            rules_list = data.get("rules", [])
            df = pd.DataFrame(rules_list)
    except FileNotFoundError:
        logging.error(f"Rules file not found at: {json_path}")
        return pd.DataFrame()
    except Exception as e:
        logging.error(f"Error loading JSON rules file: {e}")
        return pd.DataFrame()

    df.columns = df.columns.str.lower()
    
    # Ensure required columns exist
    required_cols = ["attribute", "vertical", "requirement", "coverage_rule_text"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    # Clean and normalize data
    df["attribute"] = df["attribute"].astype(str).map(_normalize)
    df["vertical"] = df["vertical"].astype(str).map(_normalize)
    df["requirement"] = df["requirement"].map(_standardize_requirement)
    
    # Drop empty rows
    df = df[ df["attribute"].astype(bool) ]
    return df[["attribute", "vertical", "requirement", "coverage_rule_text"]].reset_index(drop=True)

def _is_universal(v: str) -> bool:
    return _normalize(v).lower() in _UNIVERSAL_VERTICALS

def rules_for_vertical(rules: pd.DataFrame, vertical: Optional[str]) -> pd.DataFrame:
    """
    Select rules for a given vertical with override semantics:
    - "All Verticals" (or synonyms) act as a baseline.
    - If a vertical-specific rule exists for the same attribute, it OVERRIDES the universal baseline.
    """
    if not vertical:
        vertical = ""
    v = _normalize(vertical).lower()
    
    # Build masks on the original frame
    is_universal_mask = rules["vertical"].map(lambda x: _is_universal(x))
    is_specific_mask = rules["vertical"].str.lower() == v
    
    subset = rules[is_universal_mask | is_specific_mask].copy()

    # Priority: specific (1) overrides universal (0)
    subset["__priority__"] = np.where(is_specific_mask.loc[subset.index], 1, 0)

    # Sort so specific rows come first per attribute, then drop dup attributes
    subset = subset.sort_values(["attribute", "__priority__"], ascending=[True, False])
    subset = subset.drop_duplicates(subset=["attribute"], keep="first")
    subset = subset.drop(columns=["__priority__"])

    return subset

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

def collect_attribute_coverage(summary_df: Optional[pd.DataFrame]) -> Dict[str, Tuple[int, int, int]]:
    """
    Collect per-attribute coverage, issue counts, and duplicate counts.
    Returns a dict with key: (issue_count, coverage_count, duplicate_count).
    """
    out = {}
    if summary_df is not None:
        for _, row in summary_df.iterrows():
            attr = str(row['Attribute']).strip()
            # Extract new metrics, defaulting to 0 or None if not present
            issue_count = row.get('Issues Found', 0)
            coverage_count = row.get('coverage_count')
            duplicate_count = row.get('duplicate_count')
            
            out[_normalize(attr).lower()] = (issue_count, coverage_count, duplicate_count)
            
    return out

def evaluate_against_rules(attr_metrics: Dict[str, Tuple[int, int, int]], rules: pd.DataFrame, total_skus: int) -> Dict[str, Any]:
    """
    Compare provided attribute metrics against the vertical rules.
    Returns a dict with pass/fail lists and counts.
    """
    required_fails: List[Dict[str, Any]] = []
    required_passes: List[Dict[str, Any]] = []
    required_unknown: List[Dict[str, Any]] = []
    nice_to_have_issues: List[Dict[str, Any]] = []

    for _, r in rules.iterrows():
        attr = str(r["attribute"]).strip()
        req = r["requirement"]
        cov_text = r.get("coverage_rule_text", None)
        
        # Get metrics for this attribute
        issue_count, coverage_count, duplicate_count = attr_metrics.get(_normalize(attr).lower(), (0, None, None))
        
        record = {
            "attribute": attr, 
            "issue_count": issue_count, 
            "coverage": coverage_count, 
            "duplicates": duplicate_count,
            "rule_text": cov_text,
            "requirement": req
        }

        # Handle 'Not Applicable' case first
        if req == "Not Applicable":
            continue

        # Check for numeric coverage threshold
        if total_skus > 0:
            coverage_rate = (coverage_count / total_skus) if coverage_count is not None else None
            coverage_threshold = _parse_coverage(cov_text)
            
            if req == "Required":
                if coverage_threshold is not None:
                    if coverage_rate is None or coverage_rate < coverage_threshold:
                        record["coverage_rate"] = coverage_rate
                        record["coverage_threshold"] = coverage_threshold
                        required_fails.append(record)
                    else:
                        required_passes.append(record)
                elif "Fails if" in str(cov_text):
                    # For non-numeric rules, check for issues flagged by the agent
                    if issue_count > 0:
                        required_fails.append(record)
                    else:
                        required_passes.append(record)
                else: # Required without a specific rule text
                    if coverage_count is None or coverage_count == 0:
                        required_unknown.append(record)
                    else:
                        required_passes.append(record)
            elif req == "Nice to Have":
                if coverage_threshold is not None and coverage_rate is not None and coverage_rate < coverage_threshold:
                    nice_to_have_issues.append(record)

        else: # total_skus is 0
            if req == "Required":
                required_unknown.append(record)

    all_required_ok = (len(required_fails) == 0) and (len(required_unknown) == 0)
    return {
        "required_passes": required_passes,
        "required_fails": required_fails,
        "required_unknown": required_unknown,
        "nice_to_have_issues": nice_to_have_issues,
        "all_required_ok": all_required_ok,
    }


class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Final Summary")
        self.model = "gpt-5-chat-latest"

    def assess(self, summary_df: pd.DataFrame, full_report: dict, api_key: str = None) -> dict:
        logging.info("Running Final Summary Agent with JSON-driven rules...")

        json_path = "sku_coverage_rules.json"
        try:
            rules_df = load_coverage_rules(json_path)
            if rules_df.empty:
                return {"eligibility_score": "Error", "reasons": ["Loaded an empty rules file or failed to load."]}
        except Exception as e:
            logging.exception(f"Failed to load coverage rules from {json_path}")
            return {"eligibility_score": "Error", "reasons": [f"Failed to load coverage rules: {e}"]}
            
        total_skus = len(summary_df)

        vertical = infer_vertical(full_report, summary_df) or "Unknown"
        applicable_rules = rules_for_vertical(rules_df, vertical)

        attr_metrics = collect_attribute_coverage(summary_df)

        eval_out = evaluate_against_rules(attr_metrics, applicable_rules, total_skus)

        if eval_out["all_required_ok"]:
            eligibility = "Eligible for GP"
        else:
            eligibility = "Not Eligible for GP"

        llm_context = {
            "vertical": vertical,
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
        
        prompt = f"""
You are a senior data quality reviewer for GP ingestion.
Given the JSON-driven gating rules and measured coverage, write a brief final assessment.
Be decisive and specific about which REQUIRED attributes failed their thresholds.

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

        if isinstance(ai_response, dict) and "eligibility_score" in ai_response:
            return {
                "eligibility_score": ai_response.get("eligibility_score", eligibility),
                "reasons": ai_response.get("reasons", []),
                "notes": ai_response.get("notes", ""),
                "vertical": vertical,
                "rule_source": json_path,
            }

        reasons: List[str] = []
        if eval_out["required_fails"]:
            reasons.append(f"{len(eval_out['required_fails'])} required attributes below threshold.")
        if eval_out["required_unknown"]:
            reasons.append(f"{len(eval_out['required_unknown'])} required attributes missing coverage data.")
        if eval_out["nice_to_have_issues"]:
            reasons.append(f"{len(eval_out['nice_to_have_issues'])} nice-to-have attributes below threshold.")
        if not reasons:
            reasons = ["All required attributes meet or exceed thresholds."]

        return {
            "eligibility_score": eligibility,
            "reasons": reasons,
            "notes": "LLM summary unavailable; returned deterministic result.",
            "vertical": vertical,
            "rule_source": json_path,
        }
