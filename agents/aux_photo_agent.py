from .base_agent import BaseAgent
import pandas as pd
import logging
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
from tqdm import tqdm
import re
import ast
from typing import List

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
                    return ast.literal_eval(url_string)
                return []
            except (ValueError, SyntaxError):
                return []

        # Apply the parser to the entire column
        df['parsed_aux_urls'] = df['ADDITIONAL_IMAGE_URLS'].apply(parse_url_list)
        
        # --- NEW: Create a new column with the formatted URLs ---
        df['All_Aux_Photos_URLs'] = df['parsed_aux_urls'].apply(lambda x: '\n'.join(x) if x else '')

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

        # --- 4. Perform Live URL Checks on a Sample ---
        # Get a flat list of all unique, non-flagged auxiliary URLs for the live check
        all_aux_urls = df['parsed_aux_urls'].explode().dropna()
        live_check_urls = all_aux_urls.drop_duplicates().tolist()
        
        # Only proceed if we have URLs to check
        if live_check_urls:
            sample_size = min(500, len(live_check_urls))
            sample_urls = random.sample(live_check_urls, sample_size)
            logging.info(f"Performing live check on a sample of {len(sample_urls)} auxiliary images...")

            def validate_single_url(url):
                try:
                    # Use HEAD request for efficiency
                    response = requests.head(url, timeout=5)
                    if response.status_code != 200:
                        return url, f"❌ URL dead (Code: {response.status_code}). "
                except requests.RequestException:
                    return url, "❌ URL request failed. "
                return url, ""

            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(validate_single_url, url) for url in sample_urls]
                for future in tqdm(as_completed(futures), total=len(sample_urls), desc="Live Aux Image Check"):
                    url, error_msg = future.result()
                    if error_msg:
                        # Find all rows that contain this URL and add the error message
                        for index, row in df.iterrows():
                            if url in row['parsed_aux_urls']:
                                if error_msg not in df.loc[index, self.issue_column]:
                                    df.loc[index, self.issue_column] += error_msg

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
        issue_count = int((df['AuxPhotoIssues?'].str.strip() != '').sum())
        
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
