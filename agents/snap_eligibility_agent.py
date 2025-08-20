from .base_agent import BaseAgent
import pandas as pd

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("SNAP Eligibility")

    def assess(self, df):
        print(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''
        if 'SNAP_ELIGIBLE' in df.columns and 'CATEGORY' in df.columns:
            alcohol_mask = df['CATEGORY'].str.contains('Alcohol', case=False, na=False)
            snap_true_mask = df['SNAP_ELIGIBLE'] == True
            invalid_snap_mask = alcohol_mask & snap_true_mask
            df.loc[invalid_snap_mask, self.issue_column] += '❌ Alcohol item incorrectly marked as SNAP eligible. '
        return df