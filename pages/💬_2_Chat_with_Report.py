import streamlit as st
import pandas as pd
from openai import OpenAI
import docx
from io import BytesIO
import re
from utils import validate_api_key, init_session_state

# --- Page Configuration and State Initialization ---
st.set_page_config(layout="wide", page_title="Chat with Report", page_icon="🧠")

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
        'assessed_df', 'style_guide', 'vertical', 'ai_model'
    ]
    for key in keys_to_check:
        if key not in st.session_state:
            st.session_state[key] = None if key != 'assessment_done' else False


initialize_chat_session()

# --- Parse criteria .docx ---
@st.cache_data
def parse_criteria_doc(file_content):
    """Parses a .docx file and extracts bolded headers and their subsequent text."""
    if not file_content:
        return {}
    try:
        doc = docx.Document(BytesIO(file_content))
        criteria = {}
        current_header = None
        current_text = []

        for para in doc.paragraphs:
            # Check if the paragraph is bold, indicating a header
            if para.runs and para.runs[0].bold:
                # If we have a pending header and text, save it
                if current_header and current_text:
                    criteria[current_header.strip()] = "\n".join(current_text).strip()
                # Start a new header
                current_header = para.text
                current_text = []
            elif current_header:
                # Append text to the current header's content
                current_text.append(para.text)

        # Save the last collected criteria
        if current_header and current_text:
            criteria[current_header.strip()] = "\n".join(current_text).strip()
        return criteria

    except Exception as e:
        st.error(f"Failed to parse the criteria document. Error: {e}")
        return {}

# --- Main Page UI ---
st.title("💬 Chat with Your Assessment Report")

# --- Pre-chat Checks ---
if not st.session_state.get('assessment_done'):
    st.warning("Please run an assessment on the main page first.")
    st.page_link("streamlit_app.py", label="Go to Main Page", icon="🏠")
    st.stop()

if not st.session_state.get('api_key_validated'):
    st.error("No valid OpenAI API key found. Please return to the main page and enter a valid key.")
    st.page_link("streamlit_app.py", label="Go to Main Page", icon="🏠")
    st.stop()

# --- Load and Display Criteria Status ---
assessment_criteria_dict = parse_criteria_doc(st.session_state.criteria_content)
if assessment_criteria_dict:
    st.info("✅ Assessment criteria document is loaded and ready for questions.")
else:
    st.warning("⚠️ Assessment criteria document not uploaded. The chatbot will have limited knowledge of specific rules.")

# --- Chat UI ---
st.success("API key is valid. You can now chat with your report.")

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
                sample_size = min(100, len(st.session_state.assessed_df))
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

                for key in assessment_criteria_dict:
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

            # 4. Construct the system prompt
            system_prompt = {
                "role": "system",
                "content": f"""
You are a data analyst assistant. Your task is to answer the user's question based *only* on the provided context.
If the user asks about a rule or 'why' something is an issue, refer to the 'Relevant Assessment Criteria'.
If the user asks about data, refer to the 'DATA CONTEXT'.

--- RELEVANT ASSESSMENT CRITERIA ---
{relevant_criteria}

--- STYLE GUIDE for {vertical} ---
{style_guide}

--- DATA CONTEXT (a random sample of {sample_size} rows) ---
{data_context}
"""
            }

            messages_to_send = [system_prompt] + st.session_state.messages

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
