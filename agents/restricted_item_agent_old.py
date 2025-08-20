from .base_agent import BaseAgent
import pandas as pd
import numpy as np
import json
from openai import OpenAI
import logging

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Restricted Item")
        self.model = "gpt-4o"

    def assess(self, df: pd.DataFrame, api_key: str = None) -> pd.DataFrame:
        """
        Assesses restricted items using both rule-based checks and an AI-powered
        review of item names against DoorDash guidelines.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        self.issue_column = 'RestrictedItemIssues?'
        if self.issue_column not in df.columns:
            df[self.issue_column] = ''

        # --- 1. Rule-Based Checks ---
        # Check for invalid values in existing restricted columns.
        restricted_cols = ['IS_ALCOHOL', 'IS_CBD'] # Removed 'IS_AGE_RESTRICTED'
        for col in restricted_cols:
            if col in df.columns:
                invalid_mask = ~df[col].isin([True, False, None, np.nan, '', ' '])
                df.loc[invalid_mask, self.issue_column] += f'❌ Invalid value in {col}. '
        
        # --- 2. AI-Powered Assessment ---
        if not api_key:
            logging.warning("No OpenAI API key provided. Skipping AI check for restricted items.")
            return df

        logging.info("Performing AI check for potentially restricted items...")
        try:
            items_to_check_df = df.copy()

            # Exclude items already marked as alcohol, if the column exists
            if 'IS_ALCOHOL' in df.columns:
                logging.info("Excluding items already flagged as 'IS_ALCOHOL'.")
                items_to_check_df = items_to_check_df[items_to_check_df['IS_ALCOHOL'] != True]

            # If there are no items left to check, exit.
            if items_to_check_df.empty:
                logging.info("No items to check for restricted status after filtering.")
                return df

            # Take a sample to keep the process fast and cost-effective.
            sample_size = min(500, len(items_to_check_df))
            sample_df = items_to_check_df.sample(n=sample_size, random_state=42)

            # Create a list of item names for the AI.
            items_for_ai = sample_df[['CONSUMER_FACING_ITEM_NAME']].to_dict('records')
            
            prompt = self.create_ai_prompt(items_for_ai)
            
            ai_response_str = self.call_ai(prompt, api_key, self.model)
            
            if isinstance(ai_response_str, str):
                ai_results = json.loads(ai_response_str)
            else:
                ai_results = ai_response_str

            # Map AI findings back to the main DataFrame
            if ai_results and 'restricted_items' in ai_results:
                flagged_items = {item['item_name']: item['reason'] for item in ai_results['restricted_items']}
                
                def get_ai_issue(row):
                    item_name = row['CONSUMER_FACING_ITEM_NAME']
                    if item_name in flagged_items:
                        return f"🤖 AI Suggestion: This may be a restricted item. Reason: {flagged_items[item_name]}. "
                    return ''

                # Apply the AI feedback to the original sample indices
                df.loc[sample_df.index, self.issue_column] += sample_df.apply(get_ai_issue, axis=1)

        except Exception as e:
            logging.error(f"An error occurred during AI restricted item check: {e}", exc_info=True)
            df.loc[:, self.issue_column] += '⚠️ AI check failed. '
            
        return df

    def create_ai_prompt(self, items_for_ai: list) -> str:
        """Creates the detailed prompt for the AI assessment."""
        return f"""
        You are a data compliance analyst for DoorDash. Your task is to review a list of product names and identify any that should be flagged as age-restricted according to DoorDash guidelines.

        **DoorDash Age-Restricted Product Guidelines:**
        You must flag any item that falls into these categories:
        - Alcoholic beverages with => 0% ABV (this includes non-alcoholic beer, wine, spirits & Bitters).
        - CBD Items.
        - THC Items.
        - Over-the-counter products containing dextromethorphan, pseudoephedrine, or any other age-restricted ingredients.
        - Nicotine Replacement Therapy (NRT) products (e.g., nicotine gum, patches).
        - Dietary supplements for weight loss or muscle building.

        **Input Data:**
        A JSON list of products to review:
        {json.dumps(items_for_ai, indent=2)}

        **Your Task:**
        Review each "CONSUMER_FACING_ITEM_NAME" in the list. Respond with a single JSON object containing a key "restricted_items".
        The value of "restricted_items" should be an array of objects, one for each item you identify as restricted.
        If no items are restricted, return an empty array.

        - For each restricted item, include the original "item_name" and a brief "reason" explaining why it's restricted based on the guidelines.

        **Example Response Format:**
        {{
          "restricted_items": [
            {{
              "item_name": "Premium Non-Alcoholic Beer 6pk",
              "reason": "Contains non-alcoholic beer, which is age-restricted."
            }},
            {{
              "item_name": "Weight Loss Tea",
              "reason": "Dietary supplement for weight loss."
            }}
          ]
        }}

        Provide only the JSON object in your response.
        """
