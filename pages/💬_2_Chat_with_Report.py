import streamlit as st
import pandas as pd
from openai import OpenAI
import re
import yaml
from utils import validate_api_key
import json, os
import logging
from datetime import date
from ui import add_footer

# --- Page Configuration and State Initialization ---
st.set_page_config(layout="wide", page_title="Chat with Report", page_icon="🧠")
# st.set_page_config(
#     page_title="Data Assessment Tool",   # <- shows in the top navbar
#     page_icon="✨🚀",
#     layout="wide",
#     initial_sidebar_state="expanded",
#     menu_items={        # optional: customize / hide default menu entries
#         "Get Help": None,
#         "Report a bug": None,
#         "About": "Data Assessment Tool v1.0"
#     }
# )


# --- Custom CSS (Optional, for consistency) ---
st.markdown("""
<style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        padding-left: 5rem;
        padding-right: 5rem;
    }
    h1, h2, h3 {
        font-weight: 600;
        color: #1a1a2e;
    }
</style>
""", unsafe_allow_html=True)


# This is a placeholder for the init_session_state function from your utils
# In your actual app, you would import this.
def initialize_chat_session():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    # Ensure all required session state keys from the main page are present
    # to avoid errors, providing default/empty values if necessary.
    keys_to_check = [
        'assessment_done', 'api_key_validated', 'api_key', 'criteria_content',
        'assessed_df', 'style_guide', 'vertical', 'ai_model', 'full_report'
    ]
    for key in keys_to_check:
        if key not in st.session_state:
            st.session_state[key] = None if key != 'assessment_done' else False

initialize_chat_session()

# --- Parse criteria .yaml ---
@st.cache_data
def parse_criteria_yaml(yaml_content):
    """Parses a YAML string and extracts the overview and instructions."""
    if not yaml_content:
        return {}
    try:
        data = yaml.safe_load(yaml_content)
        # Flatten the YAML data into a simpler dictionary for the chatbot
        criteria_dict = {}
        for key, value in data.items():
            if isinstance(value, dict):
                criteria_dict[key.replace('_', ' ').title()] = value.get('overview', '') + '\n\n' + value.get('instructions', '')
        return criteria_dict

    except Exception as e:
        st.error(f"Failed to parse the criteria document. Error: {e}")
        return {}


# --- Main Page UI ---
st.title("💬 Chat with Your Assessment Report")

# --- Pre-chat Checks ---
if not st.session_state.get('assessment_done'):
    st.warning("Please run an assessment on the main page first.")
    st.page_link("streamlit_app.py", label="Go to Main Page", icon="🏠")
    add_footer()
    st.stop()

if not st.session_state.get('api_key_validated'):
    st.error("No valid OpenAI API key found. Please return to the main page and enter a valid key.")
    st.page_link("streamlit_app.py", label="Go to Main Page", icon="🏠")
    add_footer() 
    st.stop()


# --- Load and Display Criteria Status ---
# Pass the YAML string from session state to the parsing function
assessment_criteria_dict = parse_criteria_yaml(st.session_state.get('criteria_content'))


if assessment_criteria_dict:
    st.info("✅ Assessment criteria document is loaded and ready for questions.")
else:
    st.warning("⚠️ Assessment criteria document not uploaded. The chatbot will have limited knowledge of specific rules.")

# --- Chat UI ---
st.success("API key is valid. You can now chat with your report.")

with st.sidebar:
    st.subheader("Chat Configuration")
    st.session_state.ai_model = st.selectbox("Select AI Model for Chat",
        ["gpt-5-chat-latest", "gpt-4o"],
        index=["gpt-5-chat-latest", "gpt-4o"].index(st.session_state.ai_model))

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about your assessment results or the rules..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("Thinking..."):
        try:
            client = OpenAI(api_key=st.session_state.api_key)

            # --- Build Context for the AI ---
            # 1. Create a sample of the main data
            if st.session_state.assessed_df is not None and not st.session_state.assessed_df.empty:
                sample_size = min(500, len(st.session_state.assessed_df))
                context_df_sample = st.session_state.assessed_df.sample(n=sample_size)

                context_cols = [
                    'MSID', 'BRAND_NAME', 'CONSUMER_FACING_ITEM_NAME',
                    'Taxonomy Path', 'Item Name Rule Issues',
                    'AI Item Name Assessment', 'CategoryIssues?'
                ]
                existing_cols = [col for col in context_cols if col in context_df_sample.columns]
                sanitized_df = context_df_sample[existing_cols].copy()

                # Sanitize text to prevent encoding errors
                def sanitize_text(text):
                    if isinstance(text, str):
                        return text.encode('ascii', 'ignore').decode('ascii')
                    return text

                for col in sanitized_df.columns:
                    if sanitized_df[col].dtype == 'object':
                        sanitized_df[col] = sanitized_df[col].apply(sanitize_text)

                data_context = sanitized_df.to_string()
            else:
                data_context = "No assessed data available."
                sample_size = 0

            # 2. Find the best-matching criteria based on the user's prompt
            relevant_criteria = "No specific criteria found for this topic in the document."
            if assessment_criteria_dict:
                best_match_key = None
                max_match_count = 0
                prompt_words = set(prompt.lower().split())

                for key, content in assessment_criteria_dict.items():
                    key_words = set(key.lower().split())
                    match_count = len(prompt_words.intersection(key_words))

                    if match_count > max_match_count:
                        max_match_count = match_count
                        best_match_key = key

                if best_match_key:
                    relevant_criteria = f"--- Relevant Assessment Criteria for '{best_match_key}' ---\n{assessment_criteria_dict[best_match_key]}"

            # 3. Get style guide and vertical info
            style_guide = st.session_state.get("style_guide", "No style guide provided.")
            vertical = st.session_state.get("vertical", "this vertical")

            # 4. Get the full report for detailed analysis
            full_report_context = "No full report available."
            if st.session_state.get('full_report'):
                full_report_context = json.dumps(st.session_state.full_report, indent=2)

            # 5. Construct the full system prompt with all available context
            system_prompt = {
                "role": "system",
                "content": f"""
You are a data analyst assistant. Your task is to answer the user's question based *only* on the provided context.
Use all available information to provide a detailed and comprehensive response.

--- FULL ASSESSMENT REPORT ---
{full_report_context}

--- RELEVANT ASSESSMENT CRITERIA ---
{relevant_criteria}

--- STYLE GUIDE for {vertical} ---
{style_guide}

--- DATA CONTEXT (a random sample of {sample_size} rows) ---
{data_context}
"""
            }

            messages_to_send = [system_prompt] + st.session_state.messages
            
            # New log message to confirm the selected model
            st.info(f"Using AI model: **{st.session_state.get('ai_model', 'gpt-4o')}**")

            # --- Call OpenAI API ---
            response = client.chat.completions.create(
                model=st.session_state.get("ai_model", "gpt-4o"),
                messages=messages_to_send
            )

            bot_response = response.choices[0].message.content

            st.session_state.messages.append({"role": "assistant", "content": bot_response})
            with st.chat_message("assistant"):
                st.markdown(bot_response)

        except Exception as e:
            st.error(f"An error occurred while communicating with the AI: {e}")

# call once near the end of each page:
add_footer()

