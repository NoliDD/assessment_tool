from .base_agent import BaseAgent
import pandas as pd
import numpy as np
import logging
import json # Make sure to import json

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("UPC")

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the UPC column for blank values, invalid formats, and duplicates.
        Adds a 'UPCIssues?' column to the DataFrame to flag issues.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''
        
        if 'UPC' not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df
        
        # --- 1. Check for Blank or Default UPCs ---
        # Identify blank, null, or 'default_value' UPCs
        blank_mask = df['UPC'].isnull() | (df['UPC'].astype(str).str.lower().isin(['default_value', '']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default UPC. '
        
        # --- 2. Check for Invalid Formats ---
        # Identify non-numeric UPCs from the non-blank values
        non_blank_mask = ~blank_mask
        format_mask = df.loc[non_blank_mask, 'UPC'].astype(str).str.contains(r'[a-zA-Z\s\W_]', regex=True, na=False)
        df.loc[format_mask[format_mask].index, self.issue_column] += '❌ Invalid Format (non-numeric). '
        
        # --- 3. Check for Duplicates ---
        # Find duplicates on the non-blank, valid-format subset, flagging every instance except the first
        valid_upc_mask = non_blank_mask & ~df[self.issue_column].str.contains('Invalid Format')
        # Create a new mask that flags only the duplicates, not the first instance
        dup_mask = df.loc[valid_upc_mask, 'UPC'].duplicated(keep='first')
        
        # Apply the '❌ Duplicate UPC.' message to the rows that are duplicates
        df.loc[dup_mask[dup_mask].index, self.issue_column] += '❌ Duplicate UPC. '

        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary including issue counts, coverage, and duplicates,
        as per the detailed assessment instructions.
        """
        if 'UPC' not in df.columns or 'UPCIssues?' not in df.columns:
            logging.warning(f"UPC summary failed: Missing required columns 'UPC' or 'UPCIssues?'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "duplicate_count": 0}
            
        total_items = len(df)
        
        # Total issues flagged by the agent
        issue_count = int(df['UPCIssues?'].str.contains('❌').sum())
        
        # Calculate coverage: items with valid, non-blank UPCs
        valid_upcs = df[df['UPC'].notna() & (df['UPC'] != '')]['UPC']
        coverage_count = int(len(valid_upcs))

        # Calculate the number of rows that are duplicates (excluding the first occurrence)
        duplicate_rows = valid_upcs[valid_upcs.duplicated(keep='first')]
        duplicate_count = int(len(duplicate_rows))

        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0
        
        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "duplicate_count": duplicate_count
        }
        
        # Log the summary data
        logging.info(f"UPC Agent Summary: {json.dumps(summary, indent=2)}")
            
        return summary
