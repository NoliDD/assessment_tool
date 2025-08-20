from .base_agent import BaseAgent
import pandas as pd
import json
import logging

class Agent(BaseAgent):
    def __init__(self):
        # This agent doesn't modify the DataFrame, so it has a unique name
        super().__init__("Final Summary")
        self.model = "gpt-5-chat-latest" # Use the most capable model for the final decision

    def assess(self, summary_df: pd.DataFrame, full_report: dict, api_key: str = None) -> dict:
        """
        Analyzes all prior assessment reports to generate a final eligibility score and summary.
        """
        logging.info("Running Final Summary Agent...")
        if not api_key:
            logging.warning("OpenAI API key not provided. Skipping final summary.")
            return {"error": "API Key not provided."}

        # Convert the summary dataframes to JSON strings to include in the prompt
        summary_json = summary_df.to_json(orient='records', indent=2)
        full_report_json = json.dumps(full_report, indent=2)

        prompt = f"""
        You are a senior data quality analyst. Your task is to provide a final, conclusive assessment of a merchant's data to determine if it is eligible for Green Pipe (GP) onboarding.

        The following attributes are **required for GP eligibility**:
        - MSID
        - UPC
        - Photo URL
        - Brand
        - Item Name
        - Size
        - Unit Of Measure
        - Mx Taxonomy
        - Age-Restricted Item Identification
        - Data Excludes Items that DoorDash Can't Sell

        You have two sources of information about the merchant's data:
        1.  **High-Level Summary:** A table showing the issue rate for each attribute.
        2.  **Attribute-by-Attribute Assessment:** A detailed report with qualitative commentary for each attribute.

        **High-Level Summary:**
        {summary_json}

        **Attribute-by-Attribute Assessment:**
        {full_report_json}

        **Your Task:**
        Based on a holistic review of all the provided information, focusing on the required GP attributes, provide a JSON object with two keys:
        1.  "eligibility_score": string. Your final verdict. Choose one: "Eligible for GP" or "Not Eligible for GP".
        2.  "reasons": list of strings. A bulleted list of the top 3-5 most critical reasons that justify your score. Be specific and reference the data (e.g., "Low MSID coverage (75%)", "Item names are inconsistent and require manual cleanup", "Critical 'Excluded Items' like tobacco were found.").

        Make a decisive judgment. If there are significant issues (e.g., low coverage, "Missing or Unusable" scores) in any of the required GP attributes, the data is likely "Not Eligible for GP".
        """

        ai_response = self.call_ai(prompt, api_key, self.model)

        if "error" in ai_response:
            return {"eligibility_score": "Error", "reasons": [ai_response["error"]]}

        return {
            "eligibility_score": ai_response.get("eligibility_score", "N/A"),
            "reasons": ai_response.get("reasons", ["No reasons provided by AI."])
        }
