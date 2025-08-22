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
        return dffrom .base_agent import BaseAgent
import pandas as pd

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("MSID")

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the MSID column for blanks, default values, and duplicates.
        Adds an 'MSIDIssues?' column to the DataFrame.
        """
        print(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''
        
        if 'MSID' not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df
        
        # Identify blank or default MSIDs
        blank_mask = df['MSID'].isnull() | (df['MSID'].astype(str).str.lower().isin(['default_value', '']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default MSID. '
        
        # Identify duplicate MSIDs, excluding the blank/default ones
        # We find duplicates on the non-blank subset to avoid flagging every blank row as a dupe.
        non_blank_df = df[~blank_mask]
        dup_mask = non_blank_df.index.isin(non_blank_df[non_blank_df.duplicated(subset=['MSID'], keep=False)].index)
        
        df.loc[dup_mask, self.issue_column] += '❌ Duplicate MSID. '
        
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary from the assessment, including specific counts
        for coverage and duplicates as per the assessment instructions.
        """
        if 'MSID' not in df.columns or 'MSIDIssues?' not in df.columns:
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0}
            
        total_items = len(df)
        
        # Calculate issues based on the issue column
        issue_count = df['MSIDIssues?'].str.contains('❌').sum()
        
        # More specific calculations for the summary report
        valid_msids = df['MSID'].replace('', pd.NA).dropna()
        coverage_count = len(valid_msids)
        duplicate_msids = valid_msids[valid_msids.duplicated(keep=False)]
        duplicate_count = len(duplicate_msids.unique())

        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0
            
        return {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "duplicate_count": duplicate_count
        }
