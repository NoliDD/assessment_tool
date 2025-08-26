from .base_agent import BaseAgent
import pandas as pd
import logging
import json

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Weighted Item")
        self.issue_column = 'WeightedItemIssues?'
        self.required_cols = ['IS_WEIGHTED_ITEM', 'AVERAGE_WEIGHT_PER_EACH']

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the IS_WEIGHTED_ITEM and AVERAGE_WEIGHT_PER_EACH columns for consistency.
        Adds a 'WeightedItemIssues?' column to the DataFrame to flag issues.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        for col in self.required_cols:
            if col not in df.columns:
                df[self.issue_column] = f'❌ Column not found: {col}.'
                return df

        # --- 1. Check for missing AVERAGE_WEIGHT_PER_EACH on items marked as weighted ---
        weighted_mask = df['IS_WEIGHTED_ITEM'] == True
        missing_weight_mask = weighted_mask & df['AVERAGE_WEIGHT_PER_EACH'].isnull()
        df.loc[missing_weight_mask, self.issue_column] += '❌ Weighted item is missing AVERAGE_WEIGHT_PER_EACH. '
        
        # --- 2. Check for unmarked weighted items ---
        # A weighted item is unmarked if it has an average weight but IS_WEIGHTED_ITEM is not True
        unmarked_weighted_mask = df['AVERAGE_WEIGHT_PER_EACH'].notna() & (df['IS_WEIGHTED_ITEM'] != True)
        df.loc[unmarked_weighted_mask, self.issue_column] += '❌ Item with average weight is not marked as weighted. '
        
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Weighted Item attribute.
        """
        if 'WeightedItemIssues?' not in df.columns:
            logging.warning(f"Weighted Item summary failed: Missing required column 'WeightedItemIssues?'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "marked_weighted_count": 0, "unmarked_weighted_items": 0}

        total_items = len(df)
        
        # Total issues flagged by the agent
        issue_count = int((df[self.issue_column].str.strip() != '').sum())
        
        # Total number of items marked by the merchant as weighted (IS_WEIGHTED_ITEM = True)
        marked_weighted_count = int(df['IS_WEIGHTED_ITEM'].sum())

        # Total number of weighted items found by the agent (marked or unmarked)
        unmarked_weighted_items = int(df['WeightedItemIssues?'].str.contains('❌ Item with average weight is not marked as weighted.').sum())
        
        # The total number of items that are or should be weighted is the sum of those marked by the merchant and those flagged by the agent
        total_weighted_items = marked_weighted_count + unmarked_weighted_items

        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0
            
        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "marked_weighted_count": marked_weighted_count,
            "total_weighted_items": total_weighted_items
        }

        logging.info(f"Weighted Item Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
