from .base_agent import BaseAgent
import pandas as pd
import os
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
from tqdm import tqdm
import re
import logging
import json

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Item Name Rules", issue_column_name="Item Name Rule Issues")
        self.vertical = "CnG"
        self.is_nexla_mx = False
        self.model = "gpt-5-chat-latest" 
        self.style_guide = ""

    def assess(self, df: pd.DataFrame, api_key: str = None) -> pd.DataFrame:
        logging.info(f"Running {self.attribute_name} Agent...")
        
        if self.is_nexla_mx and 'SUGGESTED_CONCATENATED_NAME' in df.columns:
            item_name_col = 'SUGGESTED_CONCATENATED_NAME'
            logging.info("Nexla enabled. Assessing 'SUGGESTED_CONCATENATED_NAME'.")
        else:
            item_name_col = 'CONSUMER_FACING_ITEM_NAME'
            logging.info("Nexla not enabled. Assessing 'CONSUMER_FACING_ITEM_NAME'.")

        self.issue_column = 'Item Name Rule Issues'
        ai_issue_col = 'Item Name Assessment'
        df[self.issue_column] = ''
        df[ai_issue_col] = ''

        if item_name_col not in df.columns:
            df[self.issue_column] = f"Column '{item_name_col}' not found."
            return df
        
        # Pre-process: Strip whitespace to handle dirty data
        df[item_name_col] = df[item_name_col].astype(str).str.strip()
        df['MSID'] = df['MSID'].astype(str)

        # --- 1. Rule-Based Checks ---
        blank_mask = df[item_name_col].isnull() | (df[item_name_col].str.lower().isin(['default', 'default_name', 'nan', '']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Name. '
        
        non_blank_mask = ~blank_mask
        
        # Check for duplicates, flagging every instance except the first
        dup_mask = df.loc[non_blank_mask, item_name_col].duplicated(keep='first')
        df.loc[dup_mask[dup_mask].index, self.issue_column] += '❌ Duplicate Name. '

        # Check for formatting issues like an item name ending with a comma
        formatting_mask = df[item_name_col].str.endswith(',', na=False)
        df.loc[formatting_mask, self.issue_column] += '❌ Formatting issue: Item name ends with a comma. '

        # --- 2. AI-Powered Checks ---
        if not api_key:
            logging.info("OpenAI API key not provided. Skipping AI analysis for Item Names.")
            df[ai_issue_col] = "ℹ️ AI Check Skipped (No API Key)."
            return df
        
        scenario_instructions = (
            "This merchant is a 'Nexla' type, meaning Brand, Size, and Variant may be in separate columns. Your main goal is to assess if the provided item names, in combination with other (unseen) columns, have enough information to be programmatically concatenated into our ideal style guide format."
            if self.is_nexla_mx
            else "This merchant provides the full item name in a single column. Your main goal is to assess the quality and consistency of these pre-built names against our ideal style guide."
        )

        prompt_template = f"""
        You are a data quality analyst. Your goal is to assess item names based on three criteria: consistency, completeness, and mappability.
        
        INSTRUCTIONS:
        1.  **Scenario Context**: {scenario_instructions}
        2.  **Ideal Style Guide**: Our target format for the '{self.vertical}' vertical is: {self.style_guide}
        3.  **Your Task**: For each item below, analyze it and return a JSON object with the following keys:
            - "is_consistent": boolean. Is this item's format consistent with the merchant's overall naming pattern?
            - "is_complete": boolean. Does the name seem to be missing critical attributes (e.g., flavor, color)?
            - "can_be_mapped": boolean. Does the name contain enough information to be programmatically transformed into our style guide?
            - "suggestion": string. Provide the corrected item name according to our ideal style guide.
            - "reason": string. Provide a brief explanation for your findings.
        Return a single JSON object where keys are the item MSIDs.

        Here are the items to check:
        {{batch_json}}
        """

        # Sample from the entire DataFrame to ensure the AI always runs
        sample_size = min(500, len(df))
        sample_df = df.sample(n=sample_size)

        def get_ai_suggestions(batch_df):
            try:
                batch_prompt = prompt_template.format(batch_json=batch_df.to_json(orient='records'))
                ai_response = self.call_ai(batch_prompt, api_key, self.model)
                if 'error' in ai_response:
                    return {"error": ai_response['error'], "msids": batch_df['MSID'].tolist()}
                return ai_response
            except Exception as e:
                logging.error(f"Error in AI batch processing: {e}", exc_info=True)
                return {"error": str(e), "msids": batch_df['MSID'].tolist()}

        batch_size = 10
        results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            required_ai_cols = ['MSID', item_name_col, 'BRAND_NAME', 'SIZE', 'UNIT_OF_MEASUREMENT']
            cols_to_send = [col for col in required_ai_cols if col in sample_df.columns]
            
            futures = [executor.submit(get_ai_suggestions, sample_df.iloc[i:i+batch_size][cols_to_send]) for i in range(0, len(sample_df), batch_size)]
            for future in tqdm(futures, total=len(futures), desc="AI Item Name Check"):
                res = future.result()
                if res and isinstance(res, dict):
                    if "error" in res:
                        # Handle the error and flag all items in the batch
                        for msid in res["msids"]:
                            idx = df[df['MSID'].astype(str) == str(msid)].index
                            if not idx.empty:
                                df.loc[idx, ai_issue_col] = f"❌ AI Check Failed: {res['error']}"
                    else:
                        results.update(res)

        for msid_str, analysis in results.items():
            try:
                msid = msid_str
                issue_msg = ""
                # Add a comprehensive check for any of the AI's boolean flags
                if not analysis.get('is_consistent') or not analysis.get('is_complete') or not analysis.get('can_be_mapped'):
                    issue_msg += "AI detected issues. "
                    # Append the AI's reason for more detail
                    reason = analysis.get('reason', 'No specific reason provided.')
                    issue_msg += f"Reason: '{reason}'"
                
                if issue_msg:
                    suggestion = analysis.get('suggestion', 'N/A')
                    issue_msg += f"Suggestion: '{suggestion}'"
                    idx = df[df['MSID'].astype(str) == msid].index
                    if not idx.empty:
                        df.loc[idx, ai_issue_col] = f"{issue_msg}"
            except (ValueError, TypeError) as e:
                logging.error(f"Could not process AI result for MSID: {msid_str}. Error: {e}")

        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Item Name attribute.
        """
        item_name_col = 'SUGGESTED_CONCATENATED_NAME' if self.is_nexla_mx and 'SUGGESTED_CONCATENATED_NAME' in df.columns else 'CONSUMER_FACING_ITEM_NAME'

        if item_name_col not in df.columns or self.issue_column not in df.columns:
            logging.warning(f"Item Name summary failed: Missing required columns '{item_name_col}' or '{self.issue_column}'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "duplicate_count": 0, "formatting_issues": 0}

        total_items = len(df)
        
        # Calculate total issues flagged by the agent
        issue_count = int(df[self.issue_column].str.contains('❌').sum())
        
        # Calculate coverage: items with a non-blank name
        coverage_count = int(df[item_name_col].notna().sum())
        
        # Calculate duplicates, flagging every instance except the first
        duplicate_rows = df[item_name_col][df[item_name_col].duplicated(keep='first')]
        duplicate_count = int(len(duplicate_rows))
        
        # Count of formatting issues
        formatting_issues = int(df[self.issue_column].str.contains('❌ Inconsistent capitalization|❌ Formatting issue').sum())

        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0

        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "duplicate_count": duplicate_count,
            "formatting_issues": formatting_issues,
        }

        logging.info(f"Item Name Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
