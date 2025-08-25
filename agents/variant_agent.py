from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Variant")
        self.issue_column = 'VariantIssues?'

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the VARIANT column for blanks, multiple variant columns, and
        SKUs with more than the allowed number of variants.
        Adds a 'VariantIssues?' column to the DataFrame.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        if 'VARIANT' not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df

        # --- 1. Check for Blank or Default Variants ---
        blank_mask = df['VARIANT'].isnull() | (df['VARIANT'].astype(str).str.strip().str.lower().isin(['default', 'default_variant', 'nan', '']))
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Variant. '

        # --- 2. Check for multiple variants per SKU ---
        # The instruction states we cannot support more than 2 variants per SKU.
        # This check looks for rows where the 'VARIANT' column contains multiple
        # distinct values separated by a common delimiter.
        if 'MSID' in df.columns:
            # We assume variants for a single SKU are in a list-like format.
            # This regex looks for multiple distinct values separated by a comma, pipe, or semicolon.
            multi_variant_mask = df['VARIANT'].astype(str).str.contains(r'[,|;]', regex=True, na=False)
            df.loc[multi_variant_mask, self.issue_column] += '❌ Multiple variants found in a single SKU. '
            
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Variant attribute.
        """
        if 'VARIANT' not in df.columns or 'VariantIssues?' not in df.columns:
            logging.warning(f"Variant summary failed: Missing required columns.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "unique_variant_count": 0}

        total_items = len(df)
        
        # Calculate total issues flagged by the agent
        issue_count = int(df['VariantIssues?'].str.contains('❌').sum())
        
        # Calculate coverage: items with valid, non-blank variants
        valid_variants = df['VARIANT'].dropna().astype(str).str.strip()
        coverage_count = int(len(valid_variants))

        # Calculate the number of unique variants
        unique_variant_count = int(valid_variants.nunique())
        
        # Count the number of SKUs with multiple variants
        multiple_variant_count = int(df['VariantIssues?'].str.contains('❌ Multiple variants found').sum())

        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0
            
        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "unique_variant_count": unique_variant_count,
            "multiple_variant_count": multiple_variant_count
        }
        
        logging.info(f"Variant Agent Summary: {json.dumps(summary, indent=2)}")
            
        return summary
