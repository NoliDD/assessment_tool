from .base_agent import BaseAgent
import pandas as pd

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("PLU")

    def assess(self, df):
        print(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''
        if 'PLU' in df.columns and 'CATEGORY' in df.columns:
            produce_mask = df['CATEGORY'].str.contains('Produce', case=False, na=False)
            missing_plu_mask = produce_mask & (df['PLU'].isnull() | ~df['PLU'].astype(str).str.match(r'^\d{4,5}$'))
            df.loc[missing_plu_mask, self.issue_column] += '❌ Missing or invalid 4-5 digit PLU for Produce item. '
        return df