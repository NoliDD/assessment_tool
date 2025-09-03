from .base_agent import BaseAgent
import pandas as pd
import json
import logging
import numpy as np

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Master Reporting")
        self.model = "gpt-5-chat-latest"

    def _get_attribute_specific_instructions(self, attr_name: str, vertical: str) -> str:
        """
        Provides detailed, attribute-specific instructions for the AI to improve assessment accuracy.
        This acts as a dynamic rulebook for the LLM.
        """
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
        # Default instruction if no specific rule is found
        default_instruction = "Assess this attribute for overall completeness, consistency, and accuracy based on the provided data sample."
        return instructions.get(attr_name, default_instruction)


    def assess(self, df: pd.DataFrame, vertical: str = "Unknown", api_key: str = None) -> dict:
        """
        Analyzes the fully assessed DataFrame to generate a structured report
        for each attribute, using an optimized prompt for more accurate AI assessments.
        """
        logging.info("Running Master Reporting Agent with optimized prompt...")
        if not api_key:
            logging.warning("OpenAI API key not provided. Skipping report generation.")
            return {"error": "API Key not provided."}

        full_report = {}
        total_skus = len(df)
        logging.info(f"Total SKUs calculated: {total_skus}")

        if vertical == "Unknown":
            logging.warning("Vertical not provided to reporting_agent; defaulting to 'Unknown'.")
        else:
            logging.info(f"Using user-provided vertical for this report: {vertical}")
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
            logging.info(f"Generating report for attribute: {attr['name']}...")

            data_col = attr['data_col']
            issue_col = attr['issue_col']

            # --- Robust Coverage Calculation ---
            coverage_count = 0
            if data_col in df.columns:
                s = df[data_col].copy()
                s = s.astype(str).str.strip()
                s_lower = s.str.lower()
                s[s_lower.isin(['nan', 'none', 'null', 'undefined'])] = np.nan
                coverage_count = s.notna().sum()
            
            duplicate_count = 0
            if data_col in df.columns and attr['name'] not in ['brand', 'photo_url']:
                subset_col = 'Taxonomy Path' if attr['name'] == 'Taxonomy Path' else data_col
                if subset_col in df.columns:
                    duplicate_count = df[df.duplicated(subset=[subset_col], keep='first')].shape[0]

            unique_category_count = df['Taxonomy Path'].nunique() if attr['name'] == 'Taxonomy Path' and 'Taxonomy Path' in df.columns else "N/A"

            issues_sample = []
            if issue_col and issue_col in df.columns:
                issue_rows = df[df[issue_col].astype(str).str.strip().ne('')]
                issues_sample = issue_rows[issue_col].head(5).tolist()

            sample_size = 30
            actual_sample_size = min(sample_size, len(df))
            data_sample_str = df.sample(n=actual_sample_size).to_string() if actual_sample_size > 0 else "No data to sample."
            
            specific_instructions = self._get_attribute_specific_instructions(attr['name'], vertical)

            prompt = f"""
            You are an expert data quality consultant with a deep understanding of e-commerce standards. Your task is to provide a precise and actionable assessment for the '{attr['name']}' attribute.

            **Your Goal:** Evaluate the data based on the provided metrics and data sample to determine its quality and readiness for an e-commerce platform.

            **Step-by-Step Analysis Guide (Think through these steps before giving your JSON response):**
            1.  **Quantitative Review:** Look at the `coverage` and `duplicates` count. Is the coverage high? This sets the baseline. Low coverage is a major red flag.
            2.  **Qualitative Review:** Examine the `Qualitative Data Sample`. Does the data *look* correct and consistent? Compare this with the `Pre-flagged Issues Sample`.
            3.  **Apply Specific Instructions:** Use the rules below to guide your judgment for this specific attribute.
            4.  **Synthesize and Score:** Combine your findings to assign an `assessment_score` based on the rubric below.
            5.  **Summarize:** Write your `commentary` and `improvements_needed` based on your analysis. Be specific and actionable.

            **Assessment Score Rubric:**
            - **"Perfect"**: Coverage is very high (>98%), duplicates are minimal, and the data sample shows consistent, high-quality, standardized values.
            - **"Has Some Issues/Nuances to Accommodate"**: The attribute is mostly populated but has correctable problems like inconsistent formatting, moderate coverage (80-98%), or some inaccuracies. The data is usable but requires cleanup.
            - **"Missing or Unusable"**: Coverage is low (<80%), the attribute is mostly empty, or the data shows critical errors, placeholder text, or is fundamentally incorrect. The data requires significant intervention.

            ---
            **Data for '{attr['name']}' Attribute:**

            **1. Quantitative Metrics:**
            - Total SKUs: {total_skus}
            - Coverage: {coverage_count} / {total_skus}
            - Duplicates: {duplicate_count}
            - Pre-flagged Issues Sample: {json.dumps(issues_sample, indent=2)}

            **2. Qualitative Data Sample ({actual_sample_size} random rows):**
            ```
            {data_sample_str}
            ```

            **3. Specific Instructions for this Attribute:**
            - {specific_instructions}

            ---
            **Your Task:**
            Based on your step-by-step analysis, provide a JSON object with ONLY the following keys. Be concise and direct.

            {{
                "assessment_score": "...",
                "commentary": "...",
                "improvements_needed": "...",
                "bad_data_examples": "...",
                "corrected_data_examples": "..."
            }}
            """

            ai_response = self.call_ai(prompt, api_key, self.model)

            if "error" in ai_response:
                full_report[attr['name']] = {"error": ai_response["error"]}
                continue

            coverage_percentage = (coverage_count / total_skus * 100) if total_skus > 0 else 0
            report_for_attr = {
                "coverage": f"{coverage_count} / {total_skus} ({coverage_percentage:.2f}%)",
                "duplicates": duplicate_count,
                "assessment": ai_response.get("assessment_score", "N/A"),
                "commentary": ai_response.get("commentary", "N/A"),
                "improvements": ai_response.get("improvements_needed", "N/A"),
                "bad_examples": ai_response.get("bad_data_examples", "N/A"),
                "corrected_examples": ai_response.get("corrected_data_examples", "N/A"),
            }
            if attr['name'] == 'Taxonomy Path':
                report_for_attr['unique_categories'] = unique_category_count

            full_report[attr['name']] = report_for_attr

        logging.info("Master Reporting Agent finished. Final report structure:")
        logging.info(json.dumps(full_report, indent=2))
        
        return full_report
