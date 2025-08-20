from .base_agent import BaseAgent
import pandas as pd
import logging

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
        
        # --- THIS IS THE KEY FIX ---
        # The list of default values to check for has been expanded.
        default_values = ['default_brand', 'default_brand_name', 'default']
        
        # Check for blank values or any of the default placeholders (case-insensitive)
        blank_mask = df['BRAND_NAME'].isnull() | (df['BRAND_NAME'].astype(str).str.strip().str.lower().isin(default_values))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Brand. '
        
        # Check for brand name already in item name
        def brand_in_name(row):
            brand = str(row.get('BRAND_NAME', ''))
            name = str(row.get('CONSUMER_FACING_ITEM_NAME', ''))
            # Ensure brand is not empty before checking if it's in the name
            if brand and name and brand.lower() in name.lower():
                return True
            return False
            
        # Apply the check only on rows that are not already flagged for being blank/default
        unflagged_rows = df[~blank_mask]
        brand_in_name_mask = unflagged_rows.apply(brand_in_name, axis=1)
        df.loc[brand_in_name_mask[brand_in_name_mask].index, self.issue_column] += 'ℹ️ Brand name is already in Item Name. '
        
        return df
