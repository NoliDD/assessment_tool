from .base_agent import BaseAgent
import pandas as pd
import logging
import json

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Product Group")
        self.issue_column = 'ProductGroupIssues?'

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the PRODUCT_GROUP column for blanks and consistency.
        Adds a 'ProductGroupIssues?' column to the DataFrame.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        if 'PRODUCT_GROUP' not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df
        
        # --- 1. Check for Blank or Default Product Groups ---
        blank_mask = df['PRODUCT_GROUP'].isnull() | (df['PRODUCT_GROUP'].astype(str).str.strip().str.lower().isin(['default', 'default_group', 'nan', '']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Product Group. '
        
        # --- 2. Check for inconsistent groupings. ---
        # This is a qualitative check. If an item has a brand, we check if other items of the same brand are in different product groups.
        # This is a good proxy for inconsistent grouping.
        if 'BRAND_NAME' in df.columns:
            df['temp_combined'] = df['BRAND_NAME'].astype(str) + '_' + df['PRODUCT_GROUP'].astype(str)
            group_counts = df['temp_combined'].value_counts()
            inconsistent_mask = df['temp_combined'].isin(group_counts[group_counts > 1].index)
            df.loc[inconsistent_mask & ~blank_mask, self.issue_column] += '❌ Potential inconsistent grouping: Same brand, different group. '
            df.drop(columns=['temp_combined'], inplace=True, errors='ignore')
            
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Product Group attribute.
        """
        if 'PRODUCT_GROUP' not in df.columns or 'ProductGroupIssues?' not in df.columns:
            logging.warning(f"Product Group summary failed: Missing required columns.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "unique_group_count": 0}
            
        total_items = len(df)
        
        # Calculate total issues flagged by the agent
        issue_count = int(df['ProductGroupIssues?'].str.contains('❌').sum())
        
        # Calculate coverage: items with valid, non-blank product groups
        valid_groups = df['PRODUCT_GROUP'].dropna().astype(str).str.strip()
        coverage_count = int(len(valid_groups))

        # Calculate the number of unique product groups
        unique_group_count = int(valid_groups.nunique())
        
        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0
            
        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "unique_group_count": unique_group_count
        }
        
        logging.info(f"Product Group Agent Summary: {json.dumps(summary, indent=2)}")
            
        return summary
