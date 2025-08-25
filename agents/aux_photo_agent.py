from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
from tqdm import tqdm
import re

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Auxiliary Photos")
        self.issue_column = 'AuxPhotoIssues?'
        self.model = "gpt-5-chat-latest"
        
    def assess(self, df: pd.DataFrame, api_key: str = None) -> pd.DataFrame:
        """
        Assesses the auxiliary photo URLs for blanks, format issues, and usage.
        Adds an 'AuxPhotoIssues?' column to the DataFrame to flag issues.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        df[self.issue_column] = ''

        if 'ADDITIONAL_IMAGE_URLS' not in df.columns or 'IMAGE_URL' not in df.columns:
            df[self.issue_column] = '❌ Missing one or both of the required columns (ADDITIONAL_IMAGE_URLS, IMAGE_URL).'
            return df

        # Helper function to safely parse the stringified list of URLs
        def parse_url_list(url_string):
            try:
                # Use literal_eval to safely parse the string as a Python list
                if isinstance(url_string, str) and url_string.startswith('['):
                    import ast
                    return ast.literal_eval(url_string)
                return []
            except (ValueError, SyntaxError):
                return []

        # Apply the parser to the entire column
        df['parsed_aux_urls'] = df['ADDITIONAL_IMAGE_URLS'].apply(parse_url_list)
        
        def check_issues(row):
            issues = []
            main_url = str(row['IMAGE_URL']).strip() if pd.notna(row['IMAGE_URL']) else ''
            aux_urls = row['parsed_aux_urls']
            
            # --- 1. Check if Aux photo exists without a main photo ---
            if aux_urls and not main_url:
                issues.append('❌ Aux Photo provided without a main photo. ')
            
            for url in aux_urls:
                url_lower = str(url).strip().lower()
                
                # --- 2. Check for blanks, defaults, or invalid URLs ---
                if not url_lower or url_lower in ['n/a', 'default']:
                    issues.append('❌ Blank or Default Aux Photo URL. ')
                    continue
                
                if url_lower.endswith('.avif'):
                    issues.append('❌ Invalid file type (.avif). ')

                # --- 3. Check for duplicates between main and aux photos ---
                if url_lower == main_url.lower():
                    issues.append('❌ Auxiliary photo is identical to the main photo. ')
            
            return "".join(list(set(issues))) # Use a set to get unique issues

        # Apply the check_issues function to the DataFrame
        df[self.issue_column] = df.apply(check_issues, axis=1)

        # Clean up the temporary column
        df.drop(columns=['parsed_aux_urls'], inplace=True, errors='ignore')

        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Aux Photo attribute.
        """
        if 'ADDITIONAL_IMAGE_URLS' not in df.columns or 'AuxPhotoIssues?' not in df.columns:
            logging.warning("Aux Photo summary failed: Missing required columns.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0, "no_main_photo_count": 0}

        total_items = len(df)
        
        # Calculate coverage: items with a non-blank aux photo URL.
        coverage_count = int(df['ADDITIONAL_IMAGE_URLS'].notna().sum())
        
        # Calculate total issues flagged by the agent
        # The fix is here: ensures issue_count is a number before division
        issue_count = df['AuxPhotoIssues?'].str.contains('❌').sum()
        if not isinstance(issue_count, (int, float)):
            issue_count = 0
        
        # Count of Aux photos without a main photo
        no_main_photo_count = int(df['AuxPhotoIssues?'].str.contains('❌ Aux Photo provided without a main photo.').sum())
        
        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0

        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
            "no_main_photo_count": no_main_photo_count
        }

        logging.info(f"Aux Photo Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
