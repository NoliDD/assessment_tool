from .base_agent import BaseAgent
import pandas as pd

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("MSID")

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        print(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''
        if 'MSID' not in df.columns: return df
        blank_mask = df['MSID'].isnull() | (df['MSID'].astype(str).str.lower() == 'default_value')
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default MSID. '
        dup_mask = df['MSID'].duplicated(keep=False) & ~blank_mask
        df.loc[dup_mask, self.issue_column] += '❌ Duplicate MSID. '
        return df