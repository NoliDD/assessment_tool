from .base_agent import BaseAgent
import pandas as pd

class Agent(BaseAgent):
    def __init__(self):
        # The agent's display name is still "UOM" for brevity in the summary table
        super().__init__("UOM")
        # Define the specific column name it operates on and the issue column it creates
        self.data_column = "UNIT_OF_MEASUREMENT"
        self.issue_column = "UNIT_OF_MEASUREMENTIssues?"

    def assess(self, df):
        print(f"Running {self.attribute_name} Agent (on {self.data_column})...")
        df[self.issue_column] = ''
        if self.data_column not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df
        
        # Check for blank (null) values in the target column
        blank_mask = df[self.data_column].isnull()
        df.loc[blank_mask, self.issue_column] += f'❌ Blank {self.data_column}. '
        return df
