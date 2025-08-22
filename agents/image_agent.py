from .base_agent import BaseAgent
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
from tqdm import tqdm
import logging
import json

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Image")

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Performs a comprehensive assessment of the IMAGE_URL column, including
        format checks and live URL validation on a sample.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        self.issue_column = 'ImageIssues?'
        df[self.issue_column] = ''
        
        if 'IMAGE_URL' not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df

        # Use a temporary column to accumulate errors
        df['temp_image_errors'] = ''
        ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'tiff', 'bmp'}
        
        def check_url_format(url):
            if not isinstance(url, str) or not url.strip(): return "❌ Not a string or blank. "
            url_lower = url.lower()
            
            if not url_lower.startswith(('http://', 'https://')): return "❌ Invalid URL protocol. "
            if url_lower.endswith('.avif'): return "❌ Invalid file type (.avif). "
            
            # Check for placeholder keywords in the URL
            if any(keyword in url_lower for keyword in ['placeholder', 'coming-soon', 'no-image', 'default-image']):
                return "❌ Placeholder image detected in URL. "

            path = url_lower.split('?', 1)[0]
            ext = path.rsplit('.', 1)[-1] if '.' in path else ''
            if ext not in ALLOWED_EXT: return f"❌ Unexpected extension (.{ext}). "
            return ""

        df['temp_image_errors'] += df['IMAGE_URL'].apply(check_url_format)
        
        valid_format_df = df[df['temp_image_errors'] == '']
        if not valid_format_df.empty:
            sample_size = min(500, len(valid_format_df))
            sample_indices = random.sample(list(valid_format_df.index), sample_size)
            logging.info(f"Performing live check on a sample of {len(sample_indices)} images...")
            
            def validate_single_image(idx):
                url = df.loc[idx, 'IMAGE_URL']
                try:
                    response = requests.head(url, timeout=5)
                    if response.status_code != 200:
                        return idx, f"❌ URL dead (Code: {response.status_code}). "
                except requests.RequestException:
                    return idx, "❌ URL request failed. "
                return idx, ""

            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(validate_single_image, idx) for idx in sample_indices]
                for future in tqdm(futures, total=len(sample_indices), desc="Live Image Check"):
                    idx, error_msg = future.result()
                    if error_msg:
                        df.loc[idx, 'temp_image_errors'] += error_msg

        # Finalize the 'Image Issues?' column based on accumulated errors
        df[self.issue_column] = df['temp_image_errors'].apply(lambda x: x.strip() if x else '✅ OK')
        df.drop(columns=['temp_image_errors'], inplace=True)
        return df

    def get_summary(self, df: pd.DataFrame) -> dict:
        """
        Generates a summary dictionary with detailed metrics for the Image attribute.
        """
        if 'IMAGE_URL' not in df.columns or 'ImageIssues?' not in df.columns:
            logging.warning(f"Image summary failed: Missing required columns 'IMAGE_URL' or 'ImageIssues?'.")
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0, "coverage_count": 0}
        
        total_items = len(df)
        
        # Total issues flagged by the agent
        issue_count = int(df['ImageIssues?'].str.contains('❌').sum())
        
        # Coverage is defined as items with a URL that is not a blank, null, or a placeholder/default
        # and has not been flagged with an error.
        coverage_count = int(df['ImageIssues?'].str.contains('✅ OK').sum())

        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0
            
        summary = {
            "name": self.attribute_name,
            "issue_count": issue_count,
            "issue_percent": issue_percent,
            "coverage_count": coverage_count,
        }
        
        logging.info(f"Image Agent Summary: {json.dumps(summary, indent=2)}")
        
        return summary
