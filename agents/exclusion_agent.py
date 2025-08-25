import logging
import json
import pandas as pd
import yaml
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from .base_agent import BaseAgent


class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Exclusion")
        self.model = "gpt-5-chat-latest"
        self.issue_column = 'ExclusionIssues?'
        self.batch_size = 50
        self.guidelines = self.load_guidelines()
        self.cache = {}

    def assess(self, df: pd.DataFrame, api_key: str = None) -> pd.DataFrame:
        logging.info(f"Running {self.attribute_name} Agent...")

        if self.issue_column not in df.columns:
            df[self.issue_column] = ''

        # --- 1. Manual Exclusion Checks (Fast and Efficient) ---
        # Manual exclusion based on IS_ALCOHOL flag
        if "IS_ALCOHOL" in df.columns:
            alcohol_mask = df["IS_ALCOHOL"] == True
            df.loc[alcohol_mask, self.issue_column] += "⚠️ Excluded: Marked as an Alcohol item. "

        # Manual exclusion based on restricted keywords in categories
        restricted_keywords = ["magazine", "subscription", "gift card", "lottery", "fireworks", "weapon", "tobacco", "vape", "nicotine", "kratom", "cbd", "thc", "pseudoephedrine", "dextromethorphan", "weight loss", "muscle building"]
        def check_restricted_category(row):
            l1 = str(row.get("L1_CATEGORY", "")).lower()
            l2 = str(row.get("L2_CATEGORY", "")).lower()
            item_name = str(row.get("CONSUMER_FACING_ITEM_NAME", "")).lower()
            for keyword in restricted_keywords:
                if keyword in l1 or keyword in l2 or keyword in item_name:
                    return f"⚠️ Excluded: Restricted keyword match for '{keyword}'. "
            return ''
        df[self.issue_column] += df.apply(check_restricted_category, axis=1)

        if not api_key:
            logging.warning("No OpenAI API key provided. Skipping AI exclusion check.")
            return df

        # --- 2. AI-Powered Assessment (On remaining items) ---
        # Sample only from items that have not yet been flagged
        unflagged_mask = df[self.issue_column].str.strip() == ''
        sample_df = df[unflagged_mask].sample(n=min(1500, unflagged_mask.sum()), random_state=42)

        # Prepare items for AI, including context
        items_to_process = sample_df[["CONSUMER_FACING_ITEM_NAME", "L1_CATEGORY", "L2_CATEGORY"]].to_dict('records')
        new_items = [item for item in items_to_process if item["CONSUMER_FACING_ITEM_NAME"] not in self.cache]

        batches = [new_items[i:i + self.batch_size] for i in range(0, len(new_items), self.batch_size)]
        logging.info(f"Submitting {len(new_items)} un-cached items to AI in {len(batches)} batch(es).")

        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(self.process_batch, batch, api_key) for batch in batches]
            for future in as_completed(futures):
                flagged_items = future.result()
                if flagged_items:
                    # Update cache and DataFrame as each batch completes
                    self.cache.update(flagged_items)
                    for item_name, reason in flagged_items.items():
                        # Find original index in the main df to apply the issue
                        target_indices = sample_df[sample_df["CONSUMER_FACING_ITEM_NAME"] == item_name].index
                        df.loc[target_indices, self.issue_column] += f"🤖 AI Suggestion: Exclude. Reason: {reason} "

        # --- 3. Final Logging ---
        manual_flags = df[self.issue_column].str.contains("⚠️").sum()
        ai_flags = df[self.issue_column].str.contains("🤖").sum()
        logging.info(f"Exclusion assessment complete. Manual flags: {manual_flags}, AI flags: {ai_flags}")

        return df

    def process_batch(self, batch_items, api_key):
        """Calls AI on a batch and returns a dictionary of flagged items."""
        try:
            prompt = self.create_ai_prompt(batch_items)
            ai_response_str = self.call_ai(prompt, api_key, self.model)
            ai_results = self.parse_ai_response(ai_response_str)

            return {
                item['item_name']: item['reason']
                for item in ai_results.get('excluded_items', [])
            } if ai_results else {}
        except Exception as e:
            logging.error(f"Batch processing failed: {e}", exc_info=True)
            return {}

    def parse_ai_response(self, response):
        """Parses AI response string into a dictionary."""
        if isinstance(response, dict): # If call_ai already parsed it
            return response
        try:
            return json.loads(response)
        except (json.JSONDecodeError, TypeError):
            logging.error("Failed to parse AI response JSON.", exc_info=True)
            return None

    def create_ai_prompt(self, items_for_ai: list) -> str:
        guidelines_str = "\n- " + "\n- ".join(self.guidelines)

        return f"""
You are a data compliance analyst for DoorDash. Your task is to review a list of products and identify any that are absolutely restricted.

**DoorDash Absolute Restriction Guidelines:**{guidelines_str}

**Input Data:**
Each product has a name, L1, and L2 category. Use all three fields for context. Pay special attention to items where the L1 or L2 category contains restricted terms like 'Magazines', 'Guns', 'Vape', 'Subscriptions', 'Rentals', etc.

**Your Task:**
Analyze the items for restrictions. Respond ONLY with a valid JSON object adhering to this schema:
{{
  "excluded_items": [
    {{
      "item_name": "The name of the excluded item",
      "reason": "A brief explanation based on the guidelines."
    }}
  ]
}}
If no items are restricted, return an empty "excluded_items" list.

Here is the data:
{json.dumps(items_for_ai, indent=2)}
"""

    def _flatten_guidelines(self, guidelines_data):
        flat_list = []
        for item in guidelines_data:
            if isinstance(item, str):
                flat_list.append(item)
            elif isinstance(item, dict):
                for key, value in item.items():
                    flat_list.append(f"{key}: {value}")
            elif isinstance(item, list):
                flat_list.extend(self._flatten_guidelines(item))
        return flat_list

    def load_guidelines(self):
        try:
            with open('restricted_items.yaml', 'r') as f:
                data = yaml.safe_load(f)
                restrictions = data.get('restrictions', [])
                return self._flatten_guidelines(restrictions)
        except Exception as e:
            logging.warning(f"Failed to load restricted_items.yaml: {e}")
            return []

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Exclusion attribute.
        """
        if 'ExclusionIssues?' not in df.columns:
            logging.warning("Exclusion summary failed: Missing required column 'ExclusionIssues?'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "manual_flags": 0, "ai_flags": 0}

        total_items = len(df)
        
        # New metrics
        marked_age_restricted_count = 0
        if 'IS_ALCOHOL' in df.columns:
            marked_age_restricted_count += int(df['IS_ALCOHOL'].sum())
        if 'IS_CBD' in df.columns:
            marked_age_restricted_count += int(df['IS_CBD'].sum())

        manual_flags = int(df['ExclusionIssues?'].str.contains('⚠️').sum())
        ai_flags = int(df['ExclusionIssues?'].str.contains('🤖').sum())
        
        # This count now represents the total number of flagged age-restricted items
        total_age_restricted_items = manual_flags + ai_flags

        # Find unique L1 categories of flagged items
        excluded_categories = []
        if 'L1_CATEGORY' in df.columns:
            restricted_category_keywords = ["magazine", "subscription", "gift card", "lottery", "fireworks", "weapon", "tobacco", "vape", "nicotine", "kratom", "cbd", "thc", "pseudoephedrine", "dextromethorphan", "weight loss", "muscle building"]
            
            # Create a mask for rows where L1_CATEGORY contains any of the keywords
            l1_mask = df['L1_CATEGORY'].astype(str).str.lower().str.contains('|'.join(restricted_category_keywords), na=False)
            
            # Get the unique L1 categories from these rows
            excluded_categories = df.loc[l1_mask, 'L1_CATEGORY'].dropna().unique().tolist()
        
        if total_items > 0:
            issue_percent = (total_age_restricted_items / total_items) * 100
        else:
            issue_percent = 0
        
        summary = {
            "name": self.attribute_name,
            "total_age_restricted_items": total_age_restricted_items,
            "issue_percent": issue_percent,
            "marked_by_merchant_columns": marked_age_restricted_count,
            "manual_flags": manual_flags,
            "ai_flags": ai_flags,
            "excluded_categories_list": excluded_categories
        }
        
        logging.info(f"Exclusion Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
