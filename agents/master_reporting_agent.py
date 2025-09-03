from .base_agent import BaseAgent
import pandas as pd
import json
import logging
import numpy as np
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Master Reporting")
        self.model = "gpt-5-chat-latest"

    # ---------- Unicode + JSON cleanup helpers ----------
    def _unescape_unicode(self, s: str) -> str:
        """Turn \\uXXXX sequences into real characters."""
        if not isinstance(s, str):
            return s
        return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)

    def _normalize_text(self, s: str, prefer_ascii: bool = True) -> str:
        """Unescape + normalize a few symbols; keep ✅ as emoji (no \\u2705)."""
        if not isinstance(s, str):
            return s
        s = self._unescape_unicode(s)
        if prefer_ascii:
            s = (s
                 .replace("→", "->")
                 .replace("–", "-")
                 .replace("—", "-"))
        return s

    def _clean_field(self, x):
        """Recursively clean dict/list/str."""
        if isinstance(x, str):
            return self._normalize_text(x, prefer_ascii=True)
        if isinstance(x, list):
            return [self._clean_field(v) for v in x]
        if isinstance(x, dict):
            return {k: self._clean_field(v) for k, v in x.items()}
        return x

    def _coerce_examples_to_text(self, value) -> str:
        """
        Accepts:
          - a plain string,
          - a JSON-encoded string (e.g., "[\"\\u2705 foo\", \"bar\"]"),
          - a Python list of strings.
        Returns a clean bullet-list string with real characters (no \\uXXXX).
        """
        # If it's a string that *looks* like a JSON array, try to parse it
        if isinstance(value, str):
            txt = value.strip()
            # First unescape any \uXXXX so parse attempts aren't double-escaped garbage
            txt_unescaped = self._unescape_unicode(txt)

            if txt_unescaped.startswith('[') and txt_unescaped.endswith(']'):
                try:
                    parsed = json.loads(txt_unescaped)
                    if isinstance(parsed, list):
                        items = [self._normalize_text(str(it), prefer_ascii=True) for it in parsed]
                        return "\n".join(f"- {it}" for it in items)
                except Exception:
                    # fall through to treat it as plain text
                    pass
            # Plain string: normalize and return
            return self._normalize_text(txt_unescaped, prefer_ascii=True)

        # If it is already a list, join nicely
        if isinstance(value, list):
            items = [self._normalize_text(str(it), prefer_ascii=True) for it in value]
            return "\n".join(f"- {it}" for it in items)

        # Fallback
        return self._normalize_text(str(value), prefer_ascii=True)
    # ----------------------------------------------------

    def _get_attribute_specific_instructions(self, attr_name: str, vertical: str) -> str:
        instructions = {
            "brand": "Focus on consistency and accuracy. Is the brand name correctly populated, or is it mixed into the item name? A 'Perfect' score requires high coverage and consistent brand names. Downgrade if brands are missing where implied by the item name (e.g., 'Tostitos Chips' with an empty BRAND_NAME field).",
            "consumer_facing_item_name": "Assess for customer readability and completeness. Are names clear, or full of internal codes or repeated information (like brand/size)? 'Modifier' items needing customer choices (e.g., 'Build Your Own Pizza') are critical issues. 'Perfect' means names are clean, descriptive, and unique.",
            "size": "Evaluate standardization. Are sizes consistent (e.g., '12 fl oz' vs. '12oz')? Look for text like 'varies' which indicates a problem. High coverage of standardized values is 'Perfect'.",
            "unit_of_measure": "Check for customer-friendly and standard units. 'EA' or 'PCE' is less clear than 'each' or 'piece'. Generic units for items that need specific ones (e.g., 'each' for a beverage) are issues. 'Perfect' requires high coverage of appropriate, clear UoMs.",
            "Taxonomy Path": "Assess for completeness and logical structure. Are all levels populated? Is the hierarchy consistent across similar products? A 'Perfect' score requires high coverage and a consistent, logical taxonomy.",
            "photo_url": "Verify based on the sample if URLs seem valid and are not duplicated. While you can't access the URLs, look for patterns suggesting placeholders or errors. High coverage of seemingly valid, unique URLs is 'Perfect'.",
            "upc": "Check for valid formatting (e.g., correct number of digits) and signs of placeholder data (e.g., '00000', '12345'). High coverage of valid-looking, unique UPCs is 'Perfect'.",
            "msid": "This is a critical identifier. Check for uniqueness and presence. Any duplicates or missing values are significant issues. 'Perfect' requires 100% coverage with unique values.",
            "product_group": f"For the '{vertical}' vertical, this attribute is crucial for creating product variants. Assess if the groupings are logical and consistent. For example, all 'lipstick' products should share a group. 'Perfect' requires high coverage of consistent group names.",
            "variant": f"For the '{vertical}' vertical, variants like color, flavor, or scent are essential. Assess if the provided variants are specific and relevant (e.g., 'Red' for lipstick, not 'Assorted'). 'Perfect' requires high coverage of clear, specific variant names.",
            "short_description": "Assess for quality and value. Is the description unique and informative, or generic and unhelpful? Good descriptions enhance customer experience. 'Perfect' means high coverage of unique, well-written descriptions.",
            "restricted_item_check": "This is a critical compliance check. Scan item names in the sample for products that cannot be sold (e.g., tobacco, CBD, lottery tickets, weapons). The presence of even ONE such item should result in a 'Missing or Unusable' score for this check.",
        }
        return instructions.get(attr_name, "Assess this attribute for overall completeness, consistency, and accuracy based on the provided data sample.")

    def assess(self, df: pd.DataFrame, vertical: str = "Unknown", api_key: str = None) -> dict:
        logging.info("Running Master Reporting Agent with optimized prompt...")
        if not api_key:
            logging.warning("OpenAI API key not provided. Skipping report generation.")
            return {"error": "API Key not provided."}

        full_report = {}
        total_skus = len(df)
        full_report['vertical'] = vertical

        attributes_to_assess = [
            {"name": "msid", "data_col": "MSID", "issue_col": "MSIDIssues?"},
            {"name": "upc", "data_col": "UPC", "issue_col": "UPCIssues?"},
            {"name": "brand", "data_col": "BRAND_NAME", "issue_col": "BrandIssues?"},
            {"name": "consumer_facing_item_name", "data_col": "CONSUMER_FACING_ITEM_NAME", "issue_col": "Item Name Rule Issues"},
            {"name": "photo_url", "data_col": "IMAGE_URL", "issue_col": "ImageIssues?"},
            {"name": "size", "data_col": "SIZE", "issue_col": "SizeIssues?"},
            {"name": "unit_of_measure", "data_col": "UNIT_OF_MEASUREMENT", "issue_col": "UNIT_OF_MEASUREMENTIssues?"},
            {"name": "Taxonomy Path", "data_col": "Taxonomy Path", "issue_col": "CategoryIssues?"},
            {"name": "product_group", "data_col": "PRODUCT_GROUP", "issue_col": "ProductGroupIssues?"},
            {"name": "variant", "data_col": "VARIANT", "issue_col": "VariantIssues?"},
            {"name": "short_description", "data_col": "DESCRIPTION", "issue_col": "DescriptionIssues?"},
            {"name": "restricted_item_check", "data_col": "CONSUMER_FACING_ITEM_NAME", "issue_col": None},
        ]

        for attr in attributes_to_assess:
            data_col = attr['data_col']
            issue_col = attr['issue_col']

            # Coverage
            coverage_count = 0
            if data_col in df.columns:
                s = df[data_col].copy().astype(str).str.strip()
                s_lower = s.str.lower()
                s[s_lower.isin(['nan', 'none', 'null', 'undefined'])] = np.nan
                coverage_count = s.notna().sum()

            # Duplicates
            duplicate_count = 0
            if data_col in df.columns and attr['name'] not in ['brand', 'photo_url']:
                subset_col = 'Taxonomy Path' if attr['name'] == 'Taxonomy Path' else data_col
                if subset_col in df.columns:
                    duplicate_count = df[df.duplicated(subset=[subset_col], keep='first')].shape[0]

            unique_category_count = (
                df['Taxonomy Path'].nunique()
                if attr['name'] == 'Taxonomy Path' and 'Taxonomy Path' in df.columns
                else "N/A"
            )

            # Issue sample
            issues_sample = []
            if issue_col and issue_col in df.columns:
                issue_rows = df[df[issue_col].astype(str).str.strip().ne('')]
                raw_sample = issue_rows[issue_col].head(5).tolist()
                issues_sample = [self._clean_field(s) for s in raw_sample]
            issues_sample_json = json.dumps(issues_sample, indent=2, ensure_ascii=False)

            # Data sample
            sample_n = min(30, len(df))
            data_sample_str = df.sample(n=sample_n).to_string() if sample_n > 0 else "No data to sample."
            data_sample_str = self._clean_field(data_sample_str)

            specific_instructions = self._get_attribute_specific_instructions(attr['name'], vertical)

            prompt = f"""
            You are an expert data quality consultant with a deep understanding of e-commerce standards. Provide a precise and actionable assessment for the '{attr['name']}' attribute.

            **Assessment Score Rubric**
            - "Perfect": 100% coverage, few/no duplicates, consistent/standardized values.
            - "Has Some Issues/Nuances to Accommodate": Mostly populated but with fixable issues (e.g., 80–98% coverage, inconsistent formatting).
            - "Missing or Unusable": Low coverage (<80%), mostly empty, or fundamentally incorrect/placeholder values.

            ---
            **1) Quantitative Metrics**
            - Total SKUs: {total_skus}
            - Coverage: {coverage_count} / {total_skus}
            - Duplicates: {duplicate_count}
            - Pre-flagged Issues Sample:
            {issues_sample_json}

            **2) Qualitative Sample ({sample_n} random rows)**
            {data_sample_str}

            **3) Attribute-Specific Guidance**
            - {specific_instructions}

            ---
            **Return ONLY this JSON object:**
            {{
            "assessment_score": "...",
            "commentary": "...",
            "improvements_needed": "...",
            "bad_data_examples": "...",        // may be a list OR a stringified JSON list
            "corrected_data_examples": "..."
            }}
            """

            ai_response = self.call_ai(prompt, api_key, self.model)
            if "error" in ai_response:
                full_report[attr['name']] = {"error": ai_response["error"]}
                continue

            # Clean/normalize all AI fields
            cleaned = {k: self._clean_field(v) for k, v in ai_response.items()}

            # Special handling: examples may be list OR stringified JSON
            bad_ex = self._coerce_examples_to_text(cleaned.get("bad_data_examples", ""))
            corr_ex = self._coerce_examples_to_text(cleaned.get("corrected_data_examples", ""))

            coverage_pct = (coverage_count / total_skus * 100) if total_skus > 0 else 0.0
            report_for_attr = {
                "coverage": f"{coverage_count} / {total_skus} ({coverage_pct:.2f}%)",
                "duplicates": duplicate_count,
                "assessment": cleaned.get("assessment_score", "N/A"),
                "commentary": cleaned.get("commentary", "N/A"),
                "improvements": cleaned.get("improvements_needed", "N/A"),
                "bad_examples": bad_ex,
                "corrected_examples": corr_ex,
            }
            if attr['name'] == 'Taxonomy Path':
                report_for_attr['unique_categories'] = unique_category_count

            full_report[attr['name']] = report_for_attr

        logging.info("Master Reporting Agent finished. Final report structure:")
        logging.info(json.dumps(full_report, indent=2, ensure_ascii=False))
        return full_report
