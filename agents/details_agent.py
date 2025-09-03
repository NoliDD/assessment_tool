from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Details/Description")
        self.issue_column = 'DescriptionIssues?'
        # --- FIX: Define a list of possible column names ---
        self.possible_data_columns = ["DESCRIPTION", "SHORT_DESCRIPTION"]
        self.data_column = None # This will be determined dynamically in the assess method

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the description column for blanks and formatting issues.
        It dynamically finds the correct column to use from a list of possibilities.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        # --- FIX: Dynamically find the first available data column ---
        self.data_column = next((col for col in self.possible_data_columns if col in df.columns), None)

        if self.data_column is None:
            df[self.issue_column] = f'❌ Column not found (checked for: {self.possible_data_columns}).'
            return df
        
        logging.info(f"Found and using data column: '{self.data_column}' for Details assessment.")
        
        # --- 1. Check for Blank or Null Descriptions ---
        desc_series = df[self.data_column].astype(str).str.strip()
        blank_mask = desc_series.isnull() | (desc_series.str.lower().isin(['', 'n/a', 'nan', 'default']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Description. '

        # --- 2. Check for potential formatting issues (HTML tags, high symbol count) ---
        non_blank_mask = ~blank_mask
        
        html_mask = desc_series.str.contains(r'<[^>]+>', regex=True, na=False)
        df.loc[html_mask & non_blank_mask, self.issue_column] += '❌ Contains HTML tags. '

        def check_symbol_ratio(text):
            if not isinstance(text, str) or not text:
                return False
            
            # Count non-alphanumeric characters (symbols, punctuation, etc.)
            symbol_count = len(re.findall(r'[^a-zA-Z0-9\s]', text))
            # Count total alphanumeric characters
            alphanumeric_count = len(re.findall(r'[a-zA-Z0-9]', text))
            
            # Avoid division by zero
            if alphanumeric_count == 0:
                return symbol_count > 0
            
            # Flag if symbol count is more than a third of alphanumeric count
            return symbol_count / alphanumeric_count > 0.33

        # Apply the check to non-blank, non-HTML rows
        symbol_ratio_mask = df[~blank_mask & ~html_mask][self.data_column].apply(check_symbol_ratio)
        df.loc[symbol_ratio_mask[symbol_ratio_mask].index, self.issue_column] += '❌ High symbol ratio, potentially messy text. '
        
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Details attribute.
        """
        summary_name = "short_description"
        
        # This check is important for when the assess method hasn't run or found a column
        if not self.data_column or self.data_column not in df.columns:
            logging.warning(f"Details summary failed: Data column '{self.data_column}' not found.")
            return {"name": summary_name, "issue_count": "N/A", "coverage_count": 0}

        if self.issue_column not in df.columns:
             logging.warning(f"Details summary failed: Issue column '{self.issue_column}' not found.")
             return {"name": summary_name, "issue_count": "N/A", "coverage_count": 0}

        desc_series = df[self.data_column].astype(str).str.strip()
        coverage_mask = ~desc_series.str.lower().isin(['', 'n/a', 'nan', 'default', 'none', 'null'])
        coverage_count = int(coverage_mask.sum())
        
        issue_count = int((df[self.issue_column].astype(str).str.strip() != '').sum())
        
        summary = {
            "name": summary_name,
            "issue_count": issue_count,
            "coverage_count": coverage_count,
        }

        logging.info(f"Details Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary

