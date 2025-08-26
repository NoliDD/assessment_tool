from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("PLU")
        self.issue_column = 'PLUIssues?'
        self.data_column = 'PLU'
        self.vertical = None  # This will be set by the main app

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the PLU column, but only for Produce items in the CnG vertical.
        Adds a 'PLUIssues?' column to the DataFrame to flag issues.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        if self.vertical and self.vertical.lower() != 'cng':
            logging.info("Skipping PLU check: not a CnG vertical.")
            df[self.issue_column] = 'N/A: Not a CnG vertical.'
            return df
            
        if self.data_column not in df.columns or 'Taxonomy Path' not in df.columns:
            df[self.issue_column] = '❌ Missing required columns.'
            return df

        # Fix: Now checks for multiple keywords to cover more produce categories
        produce_keywords = ['Produce', 'Fruits', 'Vegetables']
        produce_mask = df['Taxonomy Path'].astype(str).str.contains('|'.join(produce_keywords), case=False, na=False)
        produce_items = df[produce_mask]

        if produce_items.empty:
            logging.info("No 'Produce' items found to assess for PLU.")
            return df
        
        # Check for blank or invalid PLUs on Produce items
        blank_or_invalid_mask = produce_items[self.data_column].isnull() | ~produce_items[self.data_column].astype(str).str.match(r'^\d{4,5}$')
        df.loc[blank_or_invalid_mask[blank_or_invalid_mask].index, self.issue_column] += '❌ Missing or invalid 4-5 digit PLU for Produce item. '

        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the PLU attribute.
        """
        if self.issue_column not in df.columns or 'Taxonomy Path' not in df.columns:
            logging.warning("PLU summary failed: Missing required columns.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "produce_item_count": 0, "coverage_count": 0}
            
        total_items = len(df)
        
        # Total number of items in the 'Produce' category
        produce_keywords = ['Produce', 'Fruits', 'Vegetables']
        produce_item_count = int(df['Taxonomy Path'].astype(str).str.contains('|'.join(produce_keywords), case=False, na=False).sum())
        
        # Calculate issues and coverage only on Produce items
        produce_items_df = df[df['Taxonomy Path'].astype(str).str.contains('|'.join(produce_keywords), case=False, na=False)].copy()
        
        # Calculate total issues flagged by the agent
        issue_count = int((produce_items_df[self.issue_column].str.strip() != '').sum())
        
        # Calculate coverage: items with a valid PLU
        valid_plu_mask = produce_items_df[self.data_column].astype(str).str.match(r'^\d{4,5}$')
        coverage_count = int(valid_plu_mask.sum())
        
        if produce_item_count > 0:
            issue_percent = (issue_count / produce_item_count) * 100
        else:
            issue_percent = 0

        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "produce_item_count": produce_item_count,
            "coverage_count": coverage_count,
        }

        logging.info(f"PLU Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
