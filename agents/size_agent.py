from .base_agent import BaseAgent
import pandas as pd

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Size")

    def assess(self, df):
        print(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''
        if 'SIZE' not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df
        blank_mask = df['SIZE'].isnull() | (df['SIZE'].astype(str).str.lower() == 'default_size')
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Size. '
        return df