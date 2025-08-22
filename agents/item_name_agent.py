from .base_agent import BaseAgent
import pandas as pd
import os
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor
import random
import json
from tqdm import tqdm
import re

class Agent(BaseAgent):
    def __init__(self):
        # The primary issue column will now be for the rule-based checks.
        super().__init__("Item Name Rules", issue_column_name="Item Name Rule Issues")
        # These attributes will be set dynamically from the Streamlit UI
        self.vertical = "CnG"
        self.is_nexla_mx = False
        self.model = "gpt-5-chat-latest" 
        self.style_guide = ""

    def assess(self, df: pd.DataFrame, api_key: str = None) -> pd.DataFrame:
        """
        Performs a detailed assessment of the item name, choosing the correct column
        based on whether Nexla is enabled.
        """
        print(f"Running {self.attribute_name} Agent...")
        
        # --- THIS IS THE KEY FIX ---
        # 1. Determine which column to use for the assessment based on the Nexla toggle.
        if self.is_nexla_mx and 'SUGGESTED_CONCATENATED_NAME' in df.columns:
            item_name_col = 'SUGGESTED_CONCATENATED_NAME'
            print("Nexla enabled. Assessing 'SUGGESTED_CONCATENATED_NAME'.")
        else:
            item_name_col = 'CONSUMER_FACING_ITEM_NAME'
            print("Nexla not enabled. Assessing 'CONSUMER_FACING_ITEM_NAME'.")

        # Define the two separate columns for the output.
        self.issue_column = 'Item Name Rule Issues' # For blank, duplicate, etc.
        ai_issue_col = 'Item Name Assessment'   # For AI feedback
        df[self.issue_column] = ''
        df[ai_issue_col] = ''

        if item_name_col not in df.columns:
            df[self.issue_column] = f"Column '{item_name_col}' not found."
            return df

        # 2. Populate the rule-based issue column using the selected item name column.
        blank_mask = df[item_name_col].isnull() | (df[item_name_col].astype(str).str.lower().isin(['default', 'default_name']))
        dup_mask = df[item_name_col].duplicated(keep=False) & ~blank_mask
        
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Name. '
        df.loc[dup_mask, self.issue_column] += '❌ Duplicate Name. '

        common_uoms = 'oz|ct|gal|lb|ml|g|kg'
        no_space_mask = df[item_name_col].str.contains(fr'\d({common_uoms})\b', case=False, na=False)
        df.loc[no_space_mask, self.issue_column] += ' formatting: No space between size and UOM. '

        # 3. The AI-powered checks will also use the selected item name column.
        if not api_key:
            print("️ OpenAI API key not provided. Skipping AI analysis for Item Names.")
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
        Return a single JSON object where keys are the item MSIDs.

        Here are the items to check:
        {{batch_json}}
        """

        unflagged_df = df[df[self.issue_column] == '']
        if unflagged_df.empty:
            return df

        sample_size = min(500, len(unflagged_df))
        sample_df = unflagged_df.sample(n=sample_size)

        def get_ai_suggestions(batch):
            batch_prompt = prompt_template.format(batch_json=batch.to_json(orient='records'))
            return self.call_ai(batch_prompt, api_key, self.model)

        batch_size = 10
        results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Send the selected item name column to the AI
            required_ai_cols = ['MSID', item_name_col, 'BRAND_NAME', 'SIZE', 'UNIT_OF_MEASUREMENT']
            cols_to_send = [col for col in required_ai_cols if col in sample_df.columns]
            
            futures = [executor.submit(get_ai_suggestions, sample_df.iloc[i:i+batch_size][cols_to_send]) for i in range(0, len(sample_df), batch_size)]
            for future in tqdm(futures, total=len(futures), desc="AI Item Name Check"):
                res = future.result()
                if 'error' not in res:
                    results.update(res)

        for msid_str, analysis in results.items():
            try:
                msid = int(msid_str) if str(msid_str).isdigit() else msid_str
                issue_msg = ""
                if not analysis.get('is_consistent'): issue_msg += "Inconsistent w/ Mx pattern. "
                if not analysis.get('is_complete'): issue_msg += "Missing attributes. "
                if not analysis.get('can_be_mapped'): issue_msg += "Cannot be mapped. "
                
                if issue_msg:
                    issue_msg += f"Suggestion: '{analysis.get('suggestion', 'N/A')}'"
                    idx = df[df['MSID'] == msid].index
                    if not idx.empty:
                        # Populate the dedicated AI column
                        df.loc[idx, ai_issue_col] = f"{issue_msg}"
            except (ValueError, TypeError) as e:
                print(f"Could not process AI result for MSID: {msid_str}. Error: {e}")

        return df
