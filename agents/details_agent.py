from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Details")
        self.issue_column = 'DetailsIssues?'
        self.data_column = "SHORT_DESCRIPTION"

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the SHORT_DESCRIPTION column for blanks and formatting issues
        like HTML or special characters.
        Adds a 'DetailsIssues?' column to the DataFrame to flag issues.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        if self.data_column not in df.columns:
            df[self.issue_column] = '❌ Column not found.'
            return df
        
        # --- 1. Check for Blank or Null Descriptions ---
        blank_mask = df[self.data_column].isnull() | (df[self.data_column].astype(str).str.strip().str.lower().isin(['', 'n/a', 'nan', 'default']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Description. '

        # --- 2. Check for potential formatting issues (HTML tags, high symbol count) ---
        non_blank_mask = ~blank_mask
        
        # Regex to detect common HTML tags
        html_mask = df[self.data_column].astype(str).str.contains(r'<[^>]+>', regex=True, na=False)
        df.loc[html_mask & non_blank_mask, self.issue_column] += '❌ Contains HTML tags. '

        # Check for a high ratio of non-alphanumeric characters
        def check_symbol_ratio(text):
            if not isinstance(text, str) or not text:
                return False
            
            # Count alphanumeric characters (letters and numbers)
            alphanum_count = sum(c.isalnum() for c in text)
            # Count other characters (symbols, spaces, etc.)
            other_count = len(text) - alphanum_count
            
            # A high ratio of non-alphanumeric characters suggests poor formatting.
            if len(text) > 20 and other_count / len(text) > 0.4:
                return True
            return False

        symbol_mask = df[self.data_column].apply(check_symbol_ratio)
        df.loc[symbol_mask & non_blank_mask, self.issue_column] += '❌ High ratio of symbols/special characters. '

        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Details attribute.
        """
        if self.data_column not in df.columns or self.issue_column not in df.columns:
            logging.warning(f"Details summary failed: Missing required columns.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "formatting_issues_count": 0}

        total_items = len(df)
        
        # Calculate coverage: items with a non-blank description
        coverage_count = int(df[self.data_column].notna().sum())
        
        # Calculate total issues flagged by the agent
        issue_count = int((df[self.issue_column].str.strip() != '').sum())

        # Count formatting issues (HTML tags or high symbol ratio)
        formatting_issues_count = int(df[self.issue_column].str.contains('❌ Contains HTML tags|❌ High ratio of symbols').sum())
        
        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0

        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "formatting_issues_count": formatting_issues_count
        }

        logging.info(f"Details Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
