from .base_agent import BaseAgent
import pandas as pd
import json
import logging
import numpy as np

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Master Reporting")
        self.model = "gpt-5-chat-latest"

    def assess(self, df: pd.DataFrame, vertical: str = "Unknown", api_key: str = None) -> dict:
        """
        Analyzes the fully assessed DataFrame to generate a structured report
        for each attribute, incorporating detailed qualitative checks.
        """
        logging.info("Running Master Reporting Agent...")
        if not api_key:
            logging.warning("OpenAI API key not provided. Skipping report generation.")
            return {"error": "API Key not provided."}

        full_report = {}
        total_skus = len(df)
        logging.info(f"Total SKUs calculated: {total_skus}")

        # **FIX**: Use the provided vertical directly, with a fallback
        if vertical == "Unknown":
            logging.warning("Vertical not provided to reporting_agent; defaulting to 'Unknown'. The final summary may not apply specific rules.")
        else:
            logging.info(f"Using user-provided vertical for this report: {vertical}")
        full_report['vertical'] = vertical


        # **FIX**: Updated 'l1_category' to 'Taxonomy Path'
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

            coverage_count = 0
            if data_col in df.columns:
                coverage_count = df[data_col].replace(r'^\s*$', np.nan, regex=True).notna().sum()

            duplicate_count = 0
            if attr['name'] not in ['brand', 'photo_url']:
                # **FIX**: Logic now correctly references 'Taxonomy Path'
                subset_col = 'Taxonomy Path' if attr['name'] == 'Taxonomy Path' and 'Taxonomy Path' in df.columns else data_col
                if subset_col in df.columns:
                    duplicate_count = df[df.duplicated(subset=[subset_col], keep='first')].shape[0]

            unique_category_count = df['Taxonomy Path'].nunique() if attr['name'] == 'Taxonomy Path' and 'Taxonomy Path' in df.columns else "N/A"

            issues_sample = []
            if issue_col and issue_col in df.columns:
                issue_rows = df[df[issue_col].astype(str).str.strip().ne('')]
                issues_sample = issue_rows[issue_col].head(5).tolist()

            prompt = f"""
            You are a data quality analyst. Your task is to fill out an assessment report for the '{attr['name']}' attribute based on the provided data summary and a sample of the full data.

            **Data Summary:**
            - Total rows in file: {total_skus}
            - Number of rows with this attribute provided: {coverage_count}
            - Number of rows with duplicate values: {duplicate_count}
            - A sample of issues flagged by other systems: {json.dumps(issues_sample, indent=2)}

            **Full Data Sample (first 10 rows):**
            {df.head(10).to_string()}

            **Your Task:**
            Based on all the information, provide a JSON object with the following keys:
            1. "assessment_score": A string. Choose one: "Perfect", "Has Some Issues/Nuances to Accommodate", or "Missing or Unusable".
            2. "commentary": A string. A brief, one-sentence commentary on the overall state of this attribute's data.
            3. "improvements_needed": A string. A brief, one-sentence recommendation for what the merchant needs to improve.
            4. "bad_data_examples": A string. A brief description of the types of issues found, based on the sample.
            5. "corrected_data_examples": A string. A brief description of what the corrected data should look like.

            **Specific Instructions for '{attr['name']}':**
            - For **brand**: Check if any item names in the sample (e.g., 'Tostitos Chips') have a brand but the 'BRAND_NAME' column is empty for that row.
            - For **consumer_facing_item_name**: Check if any item names seem to be "modifier" items that require customer choices, like 'Build Your Own Pizza'.
            - For **size/unit_of_measure**: Check if any sizes or UOMs are generic or not customer-friendly (e.g., 'EACH', 'ONE', 'SF' instead of 'sq ft').
            - For **restricted_item_check**: Scan the item names in the data sample for products that DoorDash cannot sell, such as tobacco, vapes, or knives, and score the assessment based on their presence.
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
            # **FIX**: Logic now correctly references 'Taxonomy Path'
            if attr['name'] == 'Taxonomy Path':
                report_for_attr['unique_categories'] = unique_category_count

            full_report[attr['name']] = report_for_attr

            # **NEW**: Log the complete report before returning it
        logging.info("Master Reporting Agent finished. Final report structure:")
        logging.info(json.dumps(full_report, indent=2))
        

        return full_report
