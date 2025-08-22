from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("UOM")
        # Define the specific column name it operates on and the issue column it creates
        self.data_column = "UNIT_OF_MEASUREMENT"
        self.issue_column = "UNIT_OF_MEASUREMENTIssues?"

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the UNIT_OF_MEASUREMENT column for blanks, inconsistencies, and generic terms.
        Adds a 'UNIT_OF_MEASUREMENTIssues?' column to the DataFrame.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        if self.data_column not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df
        
        # --- 1. Check for Blank or Default UOMs ---
        blank_mask = df[self.data_column].isnull() | (df[self.data_column].astype(str).str.lower().isin(['', 'n/a', 'default']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default UOM. '
        
        # --- 2. Check for generic or unhelpful UOM values (e.g., 'SF' for 'sq ft') ---
        generic_uoms = ['sf', 'sq ft']
        generic_mask = df[self.data_column].astype(str).str.lower().isin(generic_uoms)
        df.loc[generic_mask, self.issue_column] += '❌ Generic or unclear UOM value found. '
        
        # --- 3. Check for inconsistent UOMs ---
        # Updated to flag long-form versions if the short-form is also present,
        # which is a more useful check for data consistency.
        inconsistent_uoms = {
            'oz': ['ounce', 'ounces'],
            'ml': ['milliliter', 'mili'],
            'lb': ['pound', 'lbs'],
        }
        
        def check_inconsistency(uom_value):
            if not isinstance(uom_value, str):
                return ''
            uom_lower = uom_value.lower()
            for correct_form, variants in inconsistent_uoms.items():
                if uom_lower in variants:
                    return f"❌ Inconsistent UOM: '{uom_value}' could be a variant of '{correct_form}'. "
            return ''

        df.loc[~blank_mask, self.issue_column] += df.loc[~blank_mask, self.data_column].apply(check_inconsistency).fillna('')
        
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the UoM attribute.
        """
        if self.data_column not in df.columns or self.issue_column not in df.columns:
            logging.warning(f"UoM summary failed: Missing required columns '{self.data_column}' or '{self.issue_column}'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "generic_uom_count": 0}

        total_items = len(df)
        
        # Calculate total issues flagged by the agent
        issue_count = int(df[self.issue_column].str.contains('❌').sum())
        
        # Calculate coverage: items with a non-blank UOM value.
        coverage_count = int(df[self.data_column].notna().sum())
        
        # Count of generic UOM issues
        generic_uom_count = int(df[self.issue_column].str.contains('❌ Generic or unclear UOM value found.').sum())
        
        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0

        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "generic_uom_count": generic_uom_count
        }

        logging.info(f"UoM Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
