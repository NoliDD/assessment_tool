from .base_agent import BaseAgent
import pandas as pd
import numpy as np
import logging

# Configure logging for this agent
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Nexla Concatenation", issue_column_name="SUGGESTED_CONCATENATED_NAME")

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Builds a new item name by concatenating several columns using vectorized operations.
        This version includes corrected logic for brand duplication and improved error handling.
        """
        logging.info("Running Nexla Concatenation Agent...")
        
        required_cols = ['BRAND_NAME', 'CONSUMER_FACING_ITEM_NAME', 'SIZE', 'UNIT_OF_MEASUREMENT']
        if not all(col in df.columns for col in required_cols):
            logging.warning(f"Skipping concatenation: One or more required columns are missing. Expected: {required_cols}")
            return df

        try:
            # Prepare series, ensuring they are string type and stripped of whitespace
            brand = df['BRAND_NAME'].fillna('').astype(str).str.strip()
            name = df['CONSUMER_FACING_ITEM_NAME'].fillna('').astype(str).str.strip()
            size = df['SIZE'].fillna('').astype(str).str.strip()
            uom = df['UNIT_OF_MEASUREMENT'].fillna('').astype(str).str.strip()

            # Vectorized logic to build the name
            contains_brand_mask = [b.lower() in n.lower() for b, n in zip(brand, name)]
            full_name = np.where(contains_brand_mask, name, brand + " " + name)
            size_part = np.where((size != "") & (uom != ""), " (" + size + " " + uom + ")", "")

            # --- THIS IS THE KEY FIX ---
            # Convert the numpy array result back to a pandas Series before using the .str accessor
            df[self.issue_column] = pd.Series(full_name + size_part).str.strip()
            
            logging.info("Successfully generated suggested concatenated names.")

        except Exception as e:
            logging.error(f"An error occurred during concatenation: {e}", exc_info=True)
            # In case of an error, return the original dataframe to not halt the entire process
            return df
        
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """This agent doesn't produce a typical issue summary."""
        return {"name": self.attribute_name, "issue_count": 0, "issue_percent": 0}
