from .base_agent import BaseAgent
import pandas as pd
import logging
import json

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("SNAP Eligibility")
        self.issue_column = 'SNAPEligibilityIssues?'
        self.vertical = None  # This will be set by the main app
        self.snap_eligible_col = 'SNAP_ELIGIBLE' # The actual column name in the data

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the SNAP_ELIGIBLE attribute, flagging alcohol items incorrectly
        marked as SNAP eligible. This check is only for the CnG vertical.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        if self.vertical and self.vertical.lower() != 'cng':
            logging.info("Skipping SNAP check: not a CnG vertical.")
            df[self.issue_column] = 'N/A: Not a CnG vertical.'
            return df
        
        # New code to find the correct SNAP eligible column name
        snap_col = next((col for col in df.columns if 'SNAP_ELIGIBLE' in col.upper()), None)
        if snap_col is None or 'Taxonomy Path' not in df.columns:
            df[self.issue_column] = '❌ Missing required columns.'
            return df
        
        # --- 1. Check for Alcohol items incorrectly marked as SNAP eligible ---
        alcohol_mask = df['Taxonomy Path'].astype(str).str.contains('Alcohol', case=False, na=False)
        snap_true_mask = df[snap_col] == True
        invalid_snap_mask = alcohol_mask & snap_true_mask
        df.loc[invalid_snap_mask, self.issue_column] += '❌ Alcohol item incorrectly marked as SNAP eligible. '
        
        # --- 2. Check for SNAP eligible items that are not marked as such ---
        snap_eligible_keywords = [
            'fruits', 'vegetables', 'meat', 'poultry', 'fish', 'dairy',
            'breads', 'cereals', 'snack', 'non-alcoholic beverages', 'seeds', 'plants'
        ]
        
        snap_eligible_mask = df['Taxonomy Path'].astype(str).str.contains('|'.join(snap_eligible_keywords), case=False, na=False)
        not_snap_marked_mask = (df[snap_col] != True)
        
        unmarked_snap_mask = snap_eligible_mask & not_snap_marked_mask & ~alcohol_mask
        df.loc[unmarked_snap_mask, self.issue_column] += '❌ Item is SNAP eligible but not marked. '
        
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the SNAP Eligibility attribute.
        """
        snap_col = next((col for col in df.columns if 'SNAP_ELIGIBLE' in col.upper()), None)
        if snap_col is None or 'SNAPEligibilityIssues?' not in df.columns:
            logging.warning("SNAP Eligibility summary failed: Missing required columns.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "snap_eligible_count": 0, "alcohol_in_snap_count": 0, "unmarked_snap_eligible_items": 0}

        total_items = len(df)
        
        # Total number of items marked as SNAP eligible by the merchant
        snap_eligible_count = int(df[snap_col].sum())
        
        # Total number of alcohol items incorrectly marked as SNAP eligible
        alcohol_in_snap_count = int(df['SNAPEligibilityIssues?'].str.contains('❌ Alcohol item incorrectly marked as SNAP eligible.').sum())
        
        # Count of items that should be SNAP eligible but aren't marked
        unmarked_snap_eligible_items = int(df['SNAPEligibilityIssues?'].str.contains('❌ Item is SNAP eligible but not marked.').sum())
        
        # Total issues flagged by the agent
        issue_count = alcohol_in_snap_count + unmarked_snap_eligible_items
        
        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0

        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "snap_eligible_count": snap_eligible_count,
            "alcohol_in_snap_count": alcohol_in_snap_count,
            "unmarked_snap_eligible_items": unmarked_snap_eligible_items
        }

        logging.info(f"SNAP Eligibility Agent Summary: {json.dumps(summary, indent=2)}")

        return summary
