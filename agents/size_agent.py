from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Size")

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the SIZE column for blanks, default values, and generic terms.
        It also checks for inconsistent formatting where size and UOM might be
        combined in the SIZE column, but only if there is a separate UOM column.
        Adds a 'SizeIssues?' column to the DataFrame.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        self.issue_column = 'SizeIssues?'
        df[self.issue_column] = ''

        if 'SIZE' not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df
        
        # --- Pre-processing: Strip whitespace to handle dirty data ---
        # Apply this to the entire column to normalize all string values
        df['SIZE'] = df['SIZE'].astype(str).str.strip()

        # --- 1. Check for Blank or Default Sizes ---
        blank_mask = df['SIZE'].isnull() | (df['SIZE'].str.lower().isin(['default_size', '', 'n/a']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Size. '
        
        # --- 2. Check for generic or unhelpful size values ---
        generic_sizes = ['count', 'each', 'one']
        generic_mask = df['SIZE'].str.lower().isin(generic_sizes)
        df.loc[generic_mask, self.issue_column] += '❌ Generic size value found. '
        
        # --- 3. Check for mixed size/UOM in a single column if UOM is also provided separately ---
        if 'UNIT_OF_MEASUREMENT' in df.columns:
            # New and more reliable logic to detect a mixed format string.
            # A "mixed format" is a string that contains both a number and a letter.
            mixed_format_mask = (df['SIZE'].str.contains(r'\d', na=False) &  # Contains a number
                                 df['SIZE'].str.contains(r'[a-zA-Z]', na=False)) # Contains a letter
            
            # This check is only applied to non-blank items to avoid redundant flags.
            mixed_format_mask = mixed_format_mask & ~blank_mask
            df.loc[mixed_format_mask, self.issue_column] += '❌ Mixed format (Size and UOM combined) found when separate UOM column exists. '

        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Size attribute.
        """
        if 'SIZE' not in df.columns or 'SizeIssues?' not in df.columns:
            logging.warning(f"Size summary failed: Missing required columns 'SIZE' or 'SizeIssues?'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "generic_size_count": 0}

        total_items = len(df)
        
        # Calculate total issues flagged by the agent
        issue_count = int(df['SizeIssues?'].str.contains('❌').sum())
        
        # Calculate coverage: items with a non-blank size value, even if invalid.
        coverage_count = int(df['SIZE'].notna().sum())
        
        # Count of generic size issues
        generic_size_count = int(df['SizeIssues?'].str.contains('❌ Generic size value found.').sum())
        
        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0

        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "generic_size_count": generic_size_count
        }

        logging.info(f"Size Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
