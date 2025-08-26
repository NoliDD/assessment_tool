from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Average Weight")
        self.issue_column = 'AverageWeightIssues?'
        self.data_column = "AVERAGE_WEIGHT_PER_EACH"

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the AVERAGE_WEIGHT_PER_EACH column for blanks, non-numeric values,
        incorrect UOM, and inconsistencies with the IS_WEIGHTED_ITEM flag.
        Adds an 'AverageWeightIssues?' column to the DataFrame to flag issues.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        if self.data_column not in df.columns:
            df[self.issue_column] = '❌ Column not found.'
            return df
        
        # --- 1. Check for blank or default average weights ---
        blank_mask = df[self.data_column].isnull() | (df[self.data_column].astype(str).str.lower().isin(['', 'n/a', 'default', 'nan']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Average Weight. '

        # --- 2. Check for non-numeric values in the AVERAGE_WEIGHT_PER_EACH column ---
        non_blank_mask = ~blank_mask
        non_numeric_mask = df[self.data_column].astype(str).str.contains(r'[^0-9.]', regex=True, na=False) & non_blank_mask
        df.loc[non_numeric_mask, self.issue_column] += '❌ Non-numeric value found in Average Weight column. '
        
        # --- 3. Check for incorrect UOM ---
        if 'AVERAGE_WEIGHT_UOM' in df.columns:
            valid_uoms = ['LB', 'KG']
            invalid_uom_mask = ~df['AVERAGE_WEIGHT_UOM'].astype(str).str.upper().isin(valid_uoms)
            df.loc[invalid_uom_mask, self.issue_column] += '❌ Incorrect UOM (must be LB or KG). '
            
        # --- 4. Check for consistency with IS_WEIGHTED_ITEM flag ---
        if 'IS_WEIGHTED_ITEM' in df.columns:
            # Check for items with a weight but not marked as weighted
            unmarked_with_weight_mask = df[self.data_column].notna() & (df['IS_WEIGHTED_ITEM'] != True)
            df.loc[unmarked_with_weight_mask, self.issue_column] += '❌ Has average weight but is not marked as weighted. '
            
            # Check for items marked as weighted but with no weight provided
            marked_without_weight_mask = (df['IS_WEIGHTED_ITEM'] == True) & df[self.data_column].isnull()
            df.loc[marked_without_weight_mask, self.issue_column] += '❌ Marked as weighted but has no average weight. '
        
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Average Weight attribute.
        """
        if 'AverageWeightIssues?' not in df.columns:
            logging.warning("Average Weight summary failed: Missing required column 'AverageWeightIssues?'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0}

        total_items = len(df)
        
        # Calculate coverage: items with a non-blank weight value.
        coverage_count = int(df[self.data_column].notna().sum())
        
        # Calculate total issues flagged by the agent
        issue_count = int((df[self.issue_column].str.strip() != '').sum())
        
        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0

        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
        }

        logging.info(f"Average Weight Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
