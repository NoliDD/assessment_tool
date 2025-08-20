import streamlit as st
from openai import OpenAI
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@st.cache_data(show_spinner=False)
def validate_api_key(api_key: str) -> tuple[bool, str]:
    """
    Makes a lightweight call to OpenAI to check if the API key is valid.
    """
    if not api_key:
        return False, "API key has not been entered."
    try:
        client = OpenAI(api_key=api_key)
        client.models.list()
        logging.info("API key validation successful.")
        return True, "✅ API key is valid."
    except Exception as e:
        logging.error(f"API key validation failed: {e}")
        return False, f"❌ API key is invalid or expired. Please check the key and try again."

def init_session_state():
    """
    Initializes all required session state variables if they don't exist.
    This is the single source of truth for the app's state.
    """
    defaults = {
        "assessment_done": False,
        "assessed_df": None,
        "summary_df": None,
        "assessed_csv": None,
        "full_report": None,
        "website_comparison_report": None,
        "uploaded_file_content": None,
        "uploaded_file_name": "",
        "taxonomy_df": None,
        "criteria_content": None,
        "vertical": "Grocery",
        "is_nexla": False,
        "api_key": "",
        "api_key_validated": False,
        "ai_model": "gpt-4o",
        "style_guide": "",
        "website_url": "",
        "sample_30_csv": None,
        "sample_50_csv": None,
        "final_summary": None,
        "messages": [] # For the chat page
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
