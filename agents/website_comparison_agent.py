from .base_agent import BaseAgent
import pandas as pd
import json
import logging

class Agent(BaseAgent):
    def __init__(self):
        # This agent doesn't modify the DataFrame, so it has a unique name
        super().__init__("Website Comparison")
        self.model = "gpt-5-chat-latest"

    def assess(self, df: pd.DataFrame, api_key: str = None, website_url: str = None) -> dict:
        """
        Uses AI to compare the quality of the provided merchant data against what would
        be expected on their public-facing website.
        """
        logging.info("Running Website Comparison Agent...")
        if not api_key:
            logging.warning("OpenAI API key not provided. Skipping website comparison.")
            return {"error": "API Key not provided."}
        if not website_url:
            logging.warning("Website URL not provided. Skipping website comparison.")
            return {"assessment": "N/A", "reasoning": "No website URL was provided for comparison."}

        # Take a representative sample of the data to show the AI
        sample_df = df.sample(n=min(20, len(df)))
        
        # Select key columns for the AI to analyze
        cols_to_show = ['BRAND_NAME', 'CONSUMER_FACING_ITEM_NAME', 'IMAGE_URL', 'L1_CATEGORY', 'L2_CATEGORY']
        existing_cols = [col for col in cols_to_show if col in sample_df.columns]
        data_sample_json = sample_df[existing_cols].to_json(orient='records', indent=2)

        prompt = f"""
        You are a data quality analyst. Your task is to compare a merchant's provided data feed with the likely quality of their public website.

        **Merchant Website URL:** {website_url}
        **Sample of Data Provided by Merchant:**
        {data_sample_json}

        **Instructions:**
        Based on the provided data sample, and using your general knowledge of what a typical high-quality e-commerce website looks like for this type of merchant, perform the following:
        1.  **Choose a score:** Select one of the three following scores: "Mx Data is Better", "Mx Data is Comparable", or "Mx Data is Worse".
        2.  **Provide reasoning:** Write a detailed, one-paragraph explanation for your choice.
            - If "Better", explain what the provided data has that a website might not (e.g., clean taxonomy, specific flags).
            - If "Comparable", explain the similarities in quality (e.g., both have good photos and names).
            - If "Worse", explain what is likely better on the website (e.g., higher resolution photos, more descriptive item names) and provide specific examples from the data sample to illustrate the shortcomings.

        Return a single JSON object with two keys: "assessment_score" and "reasoning".
        """

        ai_response = self.call_ai(prompt, api_key, self.model)

        if "error" in ai_response:
            return {"assessment": "Error", "reasoning": ai_response["error"]}

        return {
            "assessment": ai_response.get("assessment_score", "N/A"),
            "reasoning": ai_response.get("reasoning", "No reasoning provided by AI.")
        }
