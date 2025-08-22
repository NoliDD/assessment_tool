from .base_agent import BaseAgent
import pandas as pd
import logging
import json # Make sure to import json
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Brand")

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the BRAND_NAME column for blank values, common default placeholders,
        and redundancy within the item name.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        self.issue_column = 'BrandIssues?'
        df[self.issue_column] = ''
        
        if 'BRAND_NAME' not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df
        
        # --- 1. Check for Blank or Default Brands ---
        default_values = ['default_brand', 'default_brand_name', 'default']
        
        # Check for blank values or any of the default placeholders (case-insensitive)
        blank_mask = df['BRAND_NAME'].isnull() | (df['BRAND_NAME'].astype(str).str.strip().str.lower().isin(default_values))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Brand. '
        
        # --- 2. Check for brand name already in item name ---
        def brand_in_name(row):
            brand = str(row.get('BRAND_NAME', '')).strip()
            name = str(row.get('CONSUMER_FACING_ITEM_NAME', '')).strip()
            
            # Skip rows where brand is blank or the item name is not a string
            if not brand or not name:
                return False
            
            # Ensure brand name is a separate word to avoid false positives (e.g., 'brand' in 'unbranded')
            pattern = r'\b' + re.escape(brand) + r'\b'
            return bool(re.search(pattern, name, re.IGNORECASE))
        
        # Apply the check only on rows that are not already flagged for being blank/default
        unflagged_rows = df[~blank_mask]
        if not unflagged_rows.empty:
            brand_in_name_mask = unflagged_rows.apply(brand_in_name, axis=1)
            df.loc[brand_in_name_mask[brand_in_name_mask].index, self.issue_column] += 'ℹ️ Brand name is already in Item Name. '
        
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Brand attribute.
        This now includes coverage and brand-in-name counts.
        """
        if 'BRAND_NAME' not in df.columns or 'BrandIssues?' not in df.columns:
            logging.warning(f"Brand summary failed: Missing required columns 'BRAND_NAME' or 'BrandIssues?'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "brand_in_name_count": 0}
            
        total_items = len(df)
        
        # Calculate total issues flagged by the agent
        issue_count = int(df['BrandIssues?'].str.contains('❌').sum())
        
        # Calculate coverage: items with valid, non-blank brand names
        valid_brands = df[df['BRAND_NAME'].notna() & (df['BRAND_NAME'] != '')]['BRAND_NAME']
        coverage_count = int(len(valid_brands))
        
        # Calculate how many brands are redundantly in the item name
        brand_in_name_count = int(df['BrandIssues?'].str.contains('ℹ️ Brand name is already in Item Name.').sum())
        
        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0
            
        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "brand_in_name_count": brand_in_name_count
        }
        
        logging.info(f"Brand Agent Summary: {json.dumps(summary, indent=2)}")
            
        return summary
