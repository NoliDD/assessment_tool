import streamlit as st

# --- Page Setup ---
st.set_page_config(
    page_title="Data Assessment Tool",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

pg = st.navigation([
    st.Page("streamlit_app.py", title="Home", icon="🏠"),
    st.Page("pages/💬_2_Chat_with_Report.py", title="Chat with Report", icon="💬"),
    # add more pages here...
])

pg.run()