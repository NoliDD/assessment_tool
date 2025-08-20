from .base_agent import BaseAgent
import pandas as pd

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("UPC")

    def assess(self, df):
        print(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''
        if 'UPC' not in df.columns: return df
        blank_mask = df['UPC'].isnull() | (df['UPC'].astype(str).str.lower() == 'default_value')
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default UPC. '
        format_mask = ~df['UPC'].astype(str).str.match(r'^\d+$') & ~blank_mask
        df.loc[format_mask, self.issue_column] += '❌ Invalid Format (non-numeric). '
        dup_mask = df['UPC'].duplicated(keep=False) & ~blank_mask
        df.loc[dup_mask, self.issue_column] += '❌ Duplicate UPC. '
        return df