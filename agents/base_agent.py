import pandas as pd
from openai import OpenAI
import logging
import json 
import re
import streamlit as st

class BaseAgent:
    """A blueprint for all our assessment agents."""
    def __init__(self, attribute_name: str, issue_column_name: str = None):
        self.attribute_name = attribute_name
        self.issue_column = issue_column_name or f'{attribute_name.replace(" ", "")}Issues?'
        self.json_mode_models = ["gpt-5","gpt-5-chat-latest", "gpt-5-mini", "gpt-5-nano","gpt5-thinking", "gpt-4o"]

    def assess(self, df: pd.DataFrame) -> pd.DataFrame:
        """Each agent must have an 'assess' method."""
        raise NotImplementedError

    def get_summary(self, df: pd.DataFrame) -> dict:
        """Generates a summary dictionary from the assessment."""
        if self.issue_column not in df.columns:
            return {"name": self.attribute_name, "issue_count": "N/A", "issue_percent": 0}
        
        total_items = len(df)
        
        # --- IMPROVEMENT: More robust way to count non-empty issue strings ---
        # This handles potential non-string data gracefully.
        issues = df[self.issue_column].dropna().astype(str).str.strip()
        issue_count = issues[issues != ''].count()
        
        # Specific logic for image 'OK' status
        if self.attribute_name == "Image":
            ok_count = (df[self.issue_column] == '✅ OK').sum()
            issue_count = total_items - ok_count

        if total_items > 0:
            issue_percent = (issue_count / total_items) * 100
        else:
            issue_percent = 0
            
        return {"name": self.attribute_name, "issue_count": issue_count, "issue_percent": issue_percent}

    def call_ai(self, prompt: str, api_key: str, model: str) -> dict:
        """Shared helper to call OpenAI API with enhanced logging."""
        try:
            # --- IMPROVEMENT: Enhanced Logging ---
            logging.info(f"Calling AI model '{model}' for '{self.attribute_name}' agent...")
            # Log a snippet of the prompt for debugging, without revealing sensitive data if any.
            logging.debug(f"Prompt snippet: {prompt[:200]}...")

            client = OpenAI(api_key=api_key)
            params = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}]
            }
            if model in self.json_mode_models:
                params["response_format"] = {"type": "json_object"}
            
            response = client.chat.completions.create(**params)

            # --- ADDED: Log the API call usage to the tracker ---
            if 'api_tracker' in st.session_state:
                st.session_state.api_tracker.log_call(
                    endpoint="chat.completions",
                    model=model,
                    response=response
                )

            content = response.choices[0].message.content
            
            logging.info(f"Successfully received AI response for '{self.attribute_name}'.")

            if model not in self.json_mode_models:
                # Manual JSON parsing for older models
                match = re.search(r'```json\n({.*?})\n```', content, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
                else:
                    logging.warning("Could not parse JSON from older model response.")
                    return {"error": "Failed to parse JSON response."}
            
            return json.loads(content)
        except Exception as e:
            logging.error(f"AI call failed for '{self.attribute_name}': {e}", exc_info=True)
            return {"error": str(e)}
