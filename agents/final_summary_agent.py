from .base_agent import BaseAgent
import pandas as pd
import json
import logging
import re
from typing import Dict, List, Optional, Any
import numpy as np

# --- Set up logging configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Agent(BaseAgent):
    """
    The final agent that orchestrates the analysis, evaluates against dynamic rules,
    and uses an LLM to generate a structured, human-readable final report.
    This version includes detailed logging for debugging purposes.
    """
    
    _UNIVERSAL_VERTICALS = {"all", "all verticals", "any", "general", "*"}

    def __init__(self):
        super().__init__("Final Summary")
        self.model = "gpt-5-chat-latest" 

    # ---- Private Helper Methods for Rule Processing and Data Analysis ----

    def _normalize(self, s: Optional[str]) -> str:
        """Strips and collapses whitespace in a string for consistent matching."""
        if not isinstance(s, str):
            return ""
        return re.sub(r"\s+", " ", s).strip()

    def _parse_coverage(self, val: Any) -> Optional[float]:
        """Normalize coverage values (e.g., '80%', 0.8) to a float between 0 and 1."""
        if pd.isna(val):
            return None
        try:
            s = str(val).strip().replace(",", "")
            if s.endswith("%"):
                s = s[:-1].strip()
            num = float(s)
            if 1 < num <= 100:
                return num / 100.0
            if 0 <= num <= 1:
                return num
        except (ValueError, TypeError):
            return None
        return None

    def _standardize_requirement(self, val: Any) -> Optional[str]:
        """Standardizes requirement text to 'Required', 'Nice to Have', or 'Not Applicable'."""
        if pd.isna(val):
            return None
        s = str(val).strip().lower()
        if s in {"required", "req", "must", "mandatory"}:
            return "Required"
        if s in {"nice", "nice to have", "optional", "good to have"}:
            return "Nice to Have"
        if s in {"not applicable", "n/a", "not required"}:
            return "Not Applicable"
        return str(val).strip().title()

    def _load_coverage_rules(self, json_path: str) -> pd.DataFrame:
        """Loads and normalizes the SKU coverage rules from the specified JSON file."""
        logging.info(f"Attempting to load coverage rules from: {json_path}")
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
                rules_list = data.get("rules", [])
                df = pd.DataFrame(rules_list)
                logging.info(f"Successfully loaded {len(df)} rules from JSON.")
        except FileNotFoundError:
            logging.error(f"Rules file not found at: {json_path}")
            return pd.DataFrame()
        except Exception as e:
            logging.error(f"Error loading or parsing JSON rules from {json_path}: {e}")
            return pd.DataFrame()

        if df.empty:
            logging.warning("Rules DataFrame is empty after loading.")
            return df

        df.columns = df.columns.str.lower()
        required_cols = ["attribute", "vertical", "requirement", "coverage_rule_text"]
        for col in required_cols:
            if col not in df.columns:
                df[col] = None

        df["attribute"] = df["attribute"].astype(str).apply(self._normalize)
        df["vertical"] = df["vertical"].astype(str).apply(self._normalize)
        df["requirement"] = df["requirement"].apply(self._standardize_requirement)
        
        df.dropna(subset=["attribute", "requirement"], inplace=True)
        logging.debug(f"Normalized rules DataFrame head:\n{df.head().to_string()}")
        return df[df["attribute"] != ""].reset_index(drop=True)[required_cols]

    def _rules_for_vertical(self, rules: pd.DataFrame, vertical: Optional[str]) -> pd.DataFrame:
        """Selects rules for a given vertical, allowing specific rules to override universal ones."""
        v = self._normalize(vertical).lower() if vertical else ""
        logging.info(f"Filtering rules for vertical: '{v}'")
        
        is_universal_mask = rules["vertical"].apply(lambda x: self._normalize(x).lower() in self._UNIVERSAL_VERTICALS)
        is_specific_mask = rules["vertical"].str.lower() == v
        
        subset = rules[is_universal_mask | is_specific_mask].copy()
        
        subset["__priority__"] = np.where(is_specific_mask.loc[subset.index], 1, 0)
        subset.sort_values(["attribute", "__priority__"], ascending=[True, False], inplace=True)
        subset.drop_duplicates(subset=["attribute"], keep="first", inplace=True)
        
        logging.info(f"Found {len(subset)} applicable rules for this vertical.")
        logging.debug(f"Applicable rules head:\n{subset.head().to_string()}")
        return subset.drop(columns=["__priority__"])

    def _infer_vertical(self, full_report: dict) -> Optional[str]:
        """Infers the primary vertical from various keys in the full report."""
        vertical_keys = ["vertical", "detected_vertical", "primary_vertical", "merchant_vertical"]
        for key in vertical_keys:
            if (candidate := full_report.get(key)) and isinstance(candidate, str):
                logging.info(f"Inferred vertical '{candidate}' from key '{key}'.")
                return candidate
        logging.warning("Could not infer vertical from the report.")
        return None

    def _collect_metrics_from_report(self, full_report: dict) -> Dict[str, Dict[str, Any]]:
        """
        **FIXED**: Collects metrics directly from the detailed full_report dictionary.
        """
        logging.info("Collecting attribute metrics directly from the full_report.")
        metrics_map = {}
        for attr, data in full_report.items():
            if isinstance(data, dict): # Ensure we only process attribute dictionaries
                try:
                    # Parse coverage string like "100 / 101 (99.01%)"
                    coverage_str = data.get("coverage", "0 / 0")
                    coverage_count = int(coverage_str.split('/')[0].strip())
                    
                    metrics_map[self._normalize(attr).lower()] = {
                        "coverage_count": coverage_count,
                        "commentary": data.get("commentary"),
                        "assessment": data.get("assessment")
                    }
                except (ValueError, IndexError) as e:
                    logging.warning(f"Could not parse coverage for attribute '{attr}': {e}")
                    metrics_map[self._normalize(attr).lower()] = { "coverage_count": None }

        logging.debug(f"Collected metrics from full_report: {json.dumps(metrics_map, indent=2)}")
        return metrics_map

    # ---- Core Evaluation Logic ----

    def _evaluate_against_rules(
        self,
        attr_metrics: Dict[str, Dict[str, Any]],
        rules: pd.DataFrame,
        total_skus: int,
        full_report: dict
    ) -> List[Dict[str, Any]]:
        """Compares attribute metrics against rules and returns a detailed assessment for each attribute."""
        logging.info("Starting evaluation of attribute metrics against rules.")
        assessments = []

        for _, rule in rules.iterrows():
            attr = str(rule["attribute"])
            req = rule["requirement"]
            rule_text = rule.get("coverage_rule_text", "")

            if req == "Not Applicable":
                continue

            metrics = attr_metrics.get(self._normalize(attr).lower(), {})
            coverage_count = metrics.get("coverage_count")
            commentary = metrics.get("commentary")

            record = {
                "attribute": attr, "requirement": req, "status": "Unknown",
                "coverage_percentage_str": "N/A", "details": "Coverage data not found.",
                "commentary": commentary if commentary else None
            }

            if total_skus <= 0:
                record["details"] = "Cannot assess coverage as total SKU count is zero."
                assessments.append(record)
                continue

            coverage_rate = (coverage_count / total_skus) if coverage_count is not None else None
            if coverage_rate is not None:
                record["coverage_percentage_str"] = f"{coverage_rate:.1%}"
            
            reasons = []
            has_issue = False
            
            if req == "Required":
                coverage_threshold = self._parse_coverage(rule_text)
                
                if coverage_threshold is not None:
                    if coverage_rate is None:
                        reasons.append("Missing coverage data.")
                        has_issue = True
                    elif coverage_rate < coverage_threshold:
                        reasons.append(f"Coverage of {record['coverage_percentage_str']} is below the {coverage_threshold:.1%} threshold.")
                        has_issue = True
                
                elif "Fails if" in rule_text and metrics.get("assessment") == "Has Some Issues/Nuances to Accommodate":
                    reasons.append(f"Qualitative issue detected: {rule_text}")
                    has_issue = True
                
                if metrics.get("assessment") == "Missing or Unusable":
                    reasons.append("AI assessment marked as 'Missing or Unusable'.")
                    has_issue = True

                if has_issue:
                    record["status"] = "Fail"
                    if commentary:
                        reasons.append(f"AI Commentary: '{commentary}'")
                    record["details"] = " | ".join(reasons)
                else:
                    record["status"] = "Pass"
                    record["details"] = f"Coverage of {record['coverage_percentage_str']} meets all requirements."

            elif req == "Nice to Have":
                coverage_threshold = self._parse_coverage(rule_text)
                if coverage_threshold and coverage_rate is not None and coverage_rate < coverage_threshold:
                    record["status"] = "Issue"
                    record["details"] = f"Coverage {record['coverage_percentage_str']} is below the recommended {coverage_threshold:.1%}."
                else:
                    record["status"] = "OK"
                    record["details"] = f"Sufficient coverage at {record['coverage_percentage_str']}."
            
            logging.debug(f"Assessment for '{attr}': {record['status']} - {record['details']}")
            assessments.append(record)
        logging.info("Finished evaluation.")
        return assessments

    # ---- Main Assess Method ----

    def assess(self, full_report: dict, api_key: str = None) -> dict:
        """
        Orchestrates the final assessment process.
        **FIXED**: Takes full_report as the primary input.
        """
        logging.info("--- Starting Final Summary Agent Assessment ---")
        json_path = "sku_coverage_rules.json"
        try:
            rules_df = self._load_coverage_rules(json_path)
            if rules_df.empty:
                return {"eligibility_score": "Error", "reasons": ["Loaded an empty or invalid rules file."]}
        except Exception as e:
            logging.exception(f"Critical error loading rules: {e}")
            return {"eligibility_score": "Error", "reasons": [f"Critical error loading rules: {e}"]}
        
        total_skus = full_report.get("total_skus", 0)
        logging.info(f"Total SKUs for assessment: {total_skus}")
        
        vertical = self._infer_vertical(full_report) or "Unknown"
        applicable_rules = self._rules_for_vertical(rules_df, vertical)
        attr_metrics = self._collect_metrics_from_report(full_report)

        all_assessments = self._evaluate_against_rules(attr_metrics, applicable_rules, total_skus, full_report)

        failed_required = any(a["requirement"] == "Required" and a["status"] in ["Fail", "Unknown"] for a in all_assessments)
        eligibility = "Not Eligible for GP" if failed_required else "Eligible for GP"
        logging.info(f"Programmatic eligibility determined as: {eligibility}")

        llm_context = {
            "vertical": vertical,
            "total_skus": total_skus,
            "determined_eligibility": eligibility,
            "attribute_assessments": all_assessments
        }
        logging.info("Context prepared for LLM. Calling AI for narrative summary.")
        logging.debug(f"LLM Context: {json.dumps(llm_context, indent=2)}")

        prompt = f"""
You are a data quality consultant writing a final report. Your task is to provide a clear, narrative-style summary of the merchant's data quality issues.

Your output MUST be a valid JSON object with this exact structure:
- `eligibility_score`: (string) "Eligible for GP" or "Not Eligible for GP".
- `narrative_summary`: (string) A brief, prose-style summary formatted with Markdown.

**Analysis Context:**
```json
{json.dumps(llm_context, indent=2, ensure_ascii=False)}
```

**Instructions for `narrative_summary`:**
1.  **Create a Brief List of Issues:** Use a Markdown bulleted list. For each major failed attribute:
    * Create a bolded title (e.g., "**MSID Issues:**"). Explain the problem clearly. Use the `commentary` and `details` from the context to provide specific examples. Also include the coverage if less than the requirement.
2.  **End with a Conclusive Summary Paragraph:** Write a final paragraph that summarizes the primary blockers for eligibility. Start with a checkmark emoji (✅ **Summary:**).
"""

        ai_response = self.call_ai(prompt, api_key, self.model)

        if isinstance(ai_response, dict) and "eligibility_score" in ai_response and "narrative_summary" in ai_response:
            logging.info("Successfully received and parsed a valid response from LLM.")
            summary = [ai_response.get("narrative_summary")]
            return {
                "eligibility_score": ai_response.get("eligibility_score"),
                "reasons": summary,
                "final_summary": {
                    "recommendations": summary,
                    "assessment_details": all_assessments
                },
                "vertical": vertical,
                "rule_source": json_path
            }
        else:
            logging.warning("LLM response was invalid. Using deterministic fallback.")
            failures = [f"{a['attribute']}: {a['details']}" for a in all_assessments if a["status"] == "Fail"]
            summary = [f"Eligibility is {eligibility}."] + failures
            
            return {
                "eligibility_score": eligibility,
                "reasons": summary,
                "final_summary": {
                    "recommendations": summary,
                    "assessment_details": all_assessments
                },
                "notes": "LLM summary unavailable; returned deterministic result.",
                "vertical": vertical,
                "rule_source": json_path,
            }
