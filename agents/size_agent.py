import pandas as pd
import numpy as np
import logging
import json

from .base_agent import BaseAgent

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Size")
        self.data_column = "SIZE"
        self.issue_column = "SizeIssues?"
        self.vertical = None

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assesses the SIZE column for completeness, default values, and generic terms.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        if self.data_column not in df.columns:
            df[self.issue_column] = '❌ Column not found.'
            return df
        
        size_series = df[self.data_column].astype(str).str.strip().str.lower()
        
        blank_values = ['', 'nan', 'n/a', 'none', 'null', 'default_size', 'default']
        blank_mask = size_series.isnull() | size_series.isin(blank_values)
        
        df.loc[blank_mask, self.issue_column] += '❌ Blank or Default Size. '

        non_blank_mask = ~blank_mask
        
        generic_sizes = ['each', 'one', 'count']
        generic_size_mask = non_blank_mask & size_series.isin(generic_sizes)
        df.loc[generic_size_mask, self.issue_column] += '❌ Generic or unusable size found. '

        uom_col = 'UNIT_OF_MEASUREMENT'
        if uom_col in df.columns:
            # --- FIX: Use a robust regex to correctly identify numeric values (including floats) ---
            # This regex checks if a string is a valid integer or decimal number.
            # It will correctly identify "7.3" as a number and "12 oz" as not a number.
            is_valid_number_regex = r'^-?\d*\.?\d+$'
            
            # The mask is True for rows that are NOT valid numbers and have a UOM.
            mixed_format_mask = non_blank_mask & \
                                (~size_series.str.match(is_valid_number_regex, na=False)) & \
                                df[uom_col].notna() & \
                                (df[uom_col].astype(str).str.strip() != '')

            df.loc[mixed_format_mask, self.issue_column] += '❌ Mixed format (Size and UOM combined) found when separate UOM column exists. '

        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Size attribute.
        """
        summary_name = "size" 
        
        if self.data_column not in df.columns:
            logging.warning("Size Agent summary failed: Missing required 'SIZE' column.")
            return {"name": summary_name, "issue_count": "N/A", "coverage_count": 0}

        size_series = df[self.data_column].astype(str).str.strip().str.lower()
        blank_values = ['', 'nan', 'n/a', 'none', 'null', 'default_size', 'default']
        blank_mask = size_series.isnull() | size_series.isin(blank_values)
        
        coverage_count = int((~blank_mask).sum())

        issue_count = int(df[self.issue_column].astype(str).str.strip().ne('').sum())
                    
        summary = {
            "name": summary_name,
            "issue_count": issue_count,
            "coverage_count": coverage_count,
        }
        
        logging.info(f"Size Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary

