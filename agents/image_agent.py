from .base_agent import BaseAgent
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor
import random
from tqdm import tqdm
import logging

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
        
        if 'IMAGE_URL' not in df.columns:
            df[self.issue_column] = 'Column not found.'
            return df

        # Use a temporary column to accumulate errors
        df['temp_image_errors'] = ''
        ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'tiff', 'bmp'}

        def check_url_format(url):
            if not isinstance(url, str) or not url.strip(): return "❌ Not a string or blank. "
            if not url.lower().startswith(('http://', 'https://')): return "❌ Invalid URL protocol. "
            if url.lower().endswith('.avif'): return "❌ Invalid file type (.avif). "
            path = url.lower().split('?', 1)[0]
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
