from .base_agent import BaseAgent
import pandas as pd
import logging
import json

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("MSID")

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the MSID column for blanks, default values, and duplicates.
        Adds an 'MSIDIssues?' column to the DataFrame. This version handles
        multiple businesses by creating a combined 'BIZID_MSID' column for
        the duplicate check.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        # The instructions specify handling multiple business IDs, so we create a
        # combined column for a more accurate duplicate check.
        if 'BIZID_MSID' not in df.columns and 'BUSINESS_ID' in df.columns and 'MSID' in df.columns:
            df['BIZID_MSID'] = df['BUSINESS_ID'].astype(str) + '_' + df['MSID'].astype(str)
        
        # Determine which column to use for the check
        check_column = 'BIZID_MSID' if 'BIZID_MSID' in df.columns else 'MSID'
        
        if check_column not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df

        # --- 1. Check for Blank or Default MSIDs ---
        blank_mask = df[check_column].isnull() | (df[check_column].astype(str).str.lower().isin(['default_value', '']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default MSID. '
        
        # --- 2. Check for Duplicates ---
        # Find duplicates on the non-blank subset to avoid flagging every blank row as a dupe.
        non_blank_df = df[~blank_mask]
        dup_mask = non_blank_df.index.isin(non_blank_df[non_blank_df.duplicated(subset=[check_column], keep='first')].index)
        
        df.loc[dup_mask, self.issue_column] += '❌ Duplicate MSID. '
        
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary from the assessment, including specific counts
        for coverage and duplicates as per the assessment instructions.
        """
        check_column = 'BIZID_MSID' if 'BIZID_MSID' in df.columns else 'MSID'
        
        if check_column not in df.columns or 'MSIDIssues?' not in df.columns:
            logging.warning(f"MSID summary failed: Missing required columns '{check_column}' or 'MSIDIssues?'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "duplicate_count": 0}
            
        total_items = len(df)
        
        # Total issues flagged by the agent
        issue_count = int(df['MSIDIssues?'].str.contains('❌').sum())
        
        # Calculate coverage: items with valid, non-blank MSIDs
        valid_msids = df[df[check_column].notna() & (df[check_column] != '')][check_column]
        coverage_count = int(len(valid_msids))

        # Calculate duplicates on the valid subset
        duplicate_count = int(len(valid_msids[valid_msids.duplicated(keep='first')].unique()))

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
        
        logging.info(f"MSID Agent Summary: {json.dumps(summary, indent=2)}")
            
        return summary
