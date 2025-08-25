import streamlit as st
import pandas as pd
import os
import importlib
import inspect
import logging
from io import BytesIO
from reporting import generate_summary_text
from utils import validate_api_key
from agents.api_tracker import ApiUsageTracker
import json
import yaml

# --- Page Setup ---
st.set_page_config(layout="wide", page_title="Mx Data Assessment Tool", page_icon="✨🚀")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Custom CSS for Modern Look ---
def load_css():
    """Injects custom CSS for a modern, clean look and feel."""
    st.markdown("""
        <style>
            /* --- General Styling --- */
            .stApp {
                background-color: none;
            }
            .main .block-container {
                padding-top: 2rem;
                padding-bottom: 2rem;
                padding-left: 5rem;
                padding-right: 5rem;
            }
            /* --- Card-like Containers for results --- */
            .st-emotion-cache-1r4qj8v, .st-emotion-cache-1kyxreq {
                border-radius: 0.75rem;
                padding: 1.5rem !important;
                background-color: white;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
                border: 1px solid #e0e0e0;
            }
            /* --- Header Styling --- */
            h1, h2, h3 {
                font-weight: 600;
                color: #1a1a2e;
            }

            /* --- Button-like Tab Styling --- */
            .stTabs {
                border-bottom: none !important; /* Remove the default underline */
            }
            /* Target individual tab buttons */
            button[data-baseweb="tab"] {
                font-size: 1.1rem;
                font-weight: 600;
                color: #4a4a4a;
                background-color: #ffffff !important;
                border: 1px solid #d0d0d0 !important;
                border-radius: 0.5rem !important;
                padding: 10px 20px !important;
                margin-right: 10px !important;
                margin-bottom: 10px;
                transition: all 0.2s ease-in-out;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            }
            /* Style for the active tab */
            button[data-baseweb="tab"][aria-selected="true"] {
                color: #ffffff !important;
                background-color: #667eea !important;
                border-color: #667eea !important;
            }
            /* Hover effect for inactive tabs */
            button[data-baseweb="tab"]:not([aria-selected="true"]):hover {
                color: #1a1a2e !important;
                background-color: #f0f2f6 !important;
                border-color: #667eea !important;
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }


            /* --- Floating Chat Button --- */
            div[data-testid="stPageLink"] {
                position: fixed;
                bottom: 40px;
                right: 40px;
                z-index: 1000;
            }
            div[data-testid="stPageLink"] a {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border-radius: 50%;
                width: 64px;
                height: 64px;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                text-decoration: none !important;
                box-shadow: 0 6px 12px rgba(0,0,0,0.15);
                transition: transform 0.3s ease, box-shadow 0.3s ease;
            }
            div[data-testid="stPageLink"] a:hover {
                transform: translateY(-5px);
                box-shadow: 0 12px 24px rgba(0,0,0,0.2);
            }
            div[data-testid="stPageLink"] p {
                font-size: 36px !important;
                margin: 0 !important;
            }
            
            /* --- Spinning Gear Animation --- */
            @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
            }
            .spinning-gear {
                display: inline-block;
                animation: spin 2s linear infinite;
            }
                
        </style>
    """, unsafe_allow_html=True)


# --- Initialize Session State ---
default_session_state = {
    "api_key": "", "api_key_validated": False, "ai_model": "gpt-4o",
    "website_url": "", "uploaded_file_content": None, "uploaded_file_name": "",
    "taxonomy_df": None, "criteria_content": None, "vertical": "CnG",
    "is_nexla": False, "style_guide": "", "last_vertical": "",
    "assessed_df": None, "summary_df": None, "full_report": None,
    "website_comparison_report": None, "final_summary": None,
    "assessed_csv": None, "sample_30_csv": None, "sample_50_csv": None,
    "assessment_done": False,
    "agent_model": "gpt-5-chat-latest" # New session state variable for agent model
}
for key, val in default_session_state.items():
    if key not in st.session_state:
        st.session_state[key] = val

# --- ADDED: Initialize the API tracker in the session state ---
if 'api_tracker' not in st.session_state:
    st.session_state.api_tracker = ApiUsageTracker()

# --- Caching Functions ---
@st.cache_resource
def discover_agents():
    """Discovers and loads agent modules from the 'agents' directory."""
    agents = []
    agent_folder = 'agents'
    if not os.path.isdir(agent_folder):
        st.error(f"'{agent_folder}' directory not found.")
        return []
    for filename in os.listdir(agent_folder):
        if filename.endswith('_agent.py') and filename != 'base_agent.py':
            try:
                module = importlib.import_module(f"{agent_folder}.{filename[:-3]}")
                agents.append(module.Agent())
            except Exception as e:
                logging.error(f"Error loading agent from {filename}: {e}")
                st.error(f"Error loading {filename}: {e}")
    return agents

@st.cache_data
def load_dataframe(file_content, file_name):
    """Loads a dataframe from file content, caching the result."""
    try:
        # --- FIX: Specify dtype for MSID to preserve leading zeros ---
        dtype_spec = {'MSID': str, 'UPC': str} # Also good practice for UPC
        
        if file_name.lower().endswith('.csv'):
            return pd.read_csv(BytesIO(file_content), low_memory=False, dtype=dtype_spec)
        elif file_name.lower().endswith(('.xls', '.xlsx')):
            return pd.read_excel(BytesIO(file_content), dtype=dtype_spec)
        else:
            st.error("Unsupported file type. Please upload a CSV or XLSX file.")
            return None
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return None

# --- Helper Functions (from original script) ---
def configure_agent(agent, session):
    mapping = {
        'taxonomy_df': 'taxonomy_df', 'vertical': 'vertical',
        'is_nexla_mx': 'is_nexla', 'style_guide': 'style_guide',
    }
    for agent_attr, session_key in mapping.items():
        if hasattr(agent, agent_attr):
            setattr(agent, agent_attr, session.get(session_key))
    # New logic to set a dedicated model for AI agents
    if hasattr(agent, 'model'):
        setattr(agent, 'model', session.get('agent_model'))

def run_assessment_pipeline(agents, df, session, progress_bar, progress_text):
    # This function remains the same as the original script's logic
    reporting_agent = next((a for a in agents if a.attribute_name == "Master Reporting"), None)
    website_agent = next((a for a in agents if a.attribute_name == "Website Comparison"), None)
    final_summary_agent = next((a for a in agents if a.attribute_name == "Final Summary"), None)
    concat_agent = next((a for a in agents if a.attribute_name == "Nexla Concatenation"), None)
    assessment_agents = [a for a in agents if a.attribute_name not in
                         ["Master Reporting", "Website Comparison", "Final Summary", "Nexla Concatenation"]]
    total_steps = len(assessment_agents) + 5
    step = 0
    if session.is_nexla and concat_agent:
        step += 1
        progress_text.info(f"Step {step}/{total_steps}: Running Nexla Concatenation...")
        progress_bar.progress(step / total_steps)
        df = concat_agent.assess(df)
    for agent in assessment_agents:
        step += 1
        progress_text.info(f"Step {step}/{total_steps}: Running {agent.attribute_name} Agent...")
        progress_bar.progress(step / total_steps)
        configure_agent(agent, session)
        if 'api_key' in inspect.signature(agent.assess).parameters:
            df = agent.assess(df, api_key=session.api_key)
        else:
            df = agent.assess(df)
    step += 1
    progress_text.info(f"Step {step}/{total_steps}: Reordering columns...")
    progress_bar.progress(step / total_steps)
    df = reorder_columns_for_readability(df, session.is_nexla)
    st.session_state.assessed_df = df
    if reporting_agent and session.api_key_validated:
        step += 1
        progress_text.info(f"Step {step}/{total_steps}: Generating Attribute-by-Attribute Report...")
        progress_bar.progress(step / total_steps)
        st.session_state.full_report = reporting_agent.assess(df, api_key=session.api_key)
    if website_agent and session.api_key_validated:
        step += 1
        progress_text.info(f"Step {step}/{total_steps}: Generating Website Comparison Report...")
        progress_bar.progress(step / total_steps)
        st.session_state.website_comparison_report = website_agent.assess(
            df, api_key=session.api_key, website_url=session.website_url)
    step += 1
    progress_text.info(f"Step {step}/{total_steps}: Generating final summaries...")
    progress_bar.progress(step / total_steps)
    
    # Updated logic to use the detailed summary output
    summary_data = [agent.get_summary(df) for agent in assessment_agents]
    summary_df = pd.DataFrame(summary_data)
    total_skus = len(df)
    summary_df['Issue Rate'] = summary_df.apply(
        lambda row: f"{(row['issue_count'] / total_skus * 100):.2f}%" if total_skus > 0 else "0.00%", axis=1)
    
    # Clean up column names for display
    summary_df.rename(columns={'name': 'Attribute', 'issue_count': 'Issues Found'}, inplace=True)
    st.session_state.summary_df = summary_df[['Attribute', 'Issues Found', 'Issue Rate']]
    
    if final_summary_agent and session.api_key_validated:
        st.session_state.final_summary = final_summary_agent.assess(
            summary_df, st.session_state.full_report, api_key=session.api_key)
            
    st.session_state.assessed_csv = df.to_csv(index=False).encode('utf-8')
    st.session_state.sample_30_csv = generate_sample_csv(df, ["UPC", "IMAGE_URL", "CONSUMER_FACING_ITEM_NAME", "SIZE", "UNIT_OF_MEASUREMENT"], 30)
    st.session_state.sample_50_csv = generate_sample_csv(df, ["MSID", "IMAGE_URL"], 50)
    st.session_state.assessment_done = True
    progress_text.success("✅ Assessment complete!")
    st.balloons()

def reorder_columns_for_readability(df, is_nexla):
    # This function remains the same as the original script's logic
    item_group = ['CONSUMER_FACING_ITEM_NAME']
    if is_nexla:
        item_group.extend(['SUGGESTED_CONCATENATED_NAME', 'Item Name Rule Issues', 'Item Name Assessment'])
    else:
        item_group.extend(['Item Name Rule Issues', 'Item Name Assessment'])
    groups = [
        ['BUSINESS_ID','VERTICAL', 'businessName', 'BIZID_MSID'], ['MSID', 'MSIDIssues?'], ['UPC', 'UPCIssues?'],
        ['BRAND_NAME', 'BrandIssues?'], item_group, ['IMAGE_URL', 'ImageIssues?'],
        ['SIZE', 'SizeIssues?'], ['UNIT_OF_MEASUREMENT', 'UNIT_OF_MEASUREMENTIssues?'],
        ['L1_CATEGORY', 'L2_CATEGORY', 'L3_CATEGORY', 'L4_CATEGORY', 'Taxonomy Path', 'CategoryIssues?'],
        ['IS_WEIGHTED_ITEM', 'WeightedItemIssues?'], ['PLU', 'PLUIssues?'],
        ['IS_ALCOHOL', 'IS_CBD', 'RestrictedItemIssues?', 'ExclusionIssues?'],
        ['SNAP_ELIGIBLE', 'SNAPEligibilityIssues?'],
        ['PRODUCT_GROUP', 'ProductGroupIssues?']
    ]
    reordered, seen = [], set()
    for group in groups:
        for col in group:
            if col in df.columns and col not in seen:
                reordered.append(col)
                seen.add(col)
    return df[reordered + [col for col in df.columns if col not in seen]]

def generate_sample_csv(df, columns, n):
    # This function remains the same as the original script's logic
    selected_cols = [col for col in columns if col in df.columns]
    sample_df = df.sample(n=min(n, len(df)))[selected_cols]
    return sample_df.to_csv(index=False).encode('utf-8')

# --- Call CSS function ---
load_css()

# --- Sidebar UI ---
with st.sidebar:
    st.header("⚙️ Configuration")
    # st.subheader("AI Model Configuration")
    # This is the updated, more secure API key input
    # It uses st.password to hide the key and stores it in session_state
    api_key_input = st.text_input("OpenAI API Key", value=st.session_state.get("api_key", ""), type="password")
    if api_key_input:
        st.session_state.api_key = api_key_input
        is_valid, message = validate_api_key(st.session_state.api_key)
        st.session_state.api_key_validated = is_valid
        if is_valid: st.success(message)
        else: st.error(message)
    else:
        st.session_state.api_key = ""
        st.session_state.api_key_validated = False
    
    st.session_state.agent_model = st.selectbox("Select AI Model for Agents",
        ["gpt-5","gpt-5-chat-latest", "gpt-5-mini", "gpt-5-nano","gpt5-thinking", "gpt-4o"],
        index=["gpt-5","gpt-5-chat-latest", "gpt-5-mini", "gpt-5-nano","gpt5-thinking", "gpt-4o"].index(st.session_state.agent_model))
        
    # st.session_state.ai_model = st.selectbox("Select AI Model for Chat",
    #     ["gpt-5","gpt-5-chat-latest", "gpt-5-mini", "gpt-5-nano","gpt5-thinking", "gpt-4o"],
    #     index=["gpt-5","gpt-5-chat-latest", "gpt-5-mini", "gpt-5-nano","gpt5-thinking", "gpt-4o"].index(st.session_state.ai_model))
    

    st.session_state.website_url = st.text_input("Merchant Website URL", value=st.session_state.website_url)
    uploaded_file = st.file_uploader("1. Upload Merchant Data File", type=["csv", "xlsx"])
    # The taxonomy file is now loaded locally, so no uploader is needed.
    if uploaded_file:
        st.session_state.uploaded_file_content = uploaded_file.read()
        st.session_state.uploaded_file_name = uploaded_file.name
    
    # Load local taxonomy file
    try:
        if os.path.exists('taxonomy.json'):
            with open('taxonomy.json', 'r') as f:
                taxonomy_data = json.load(f)
                st.session_state.taxonomy_df = pd.DataFrame(taxonomy_data['taxonomy'])
            st.success("Taxonomy Loaded")
        else:
            st.warning("No local 'taxonomy.json' found. Taxonomy-based agents will be limited.")
    except Exception as e:
        st.error(f"Error loading local taxonomy file: {e}")
        st.session_state.taxonomy_df = None
        
    # Load local criteria file
    try:
        with open('assessment_instructions.yaml', 'r') as f:
            st.session_state.criteria_content = f.read()
        st.success("Assessment Criteria Loaded")
    except FileNotFoundError:
        st.warning("No local 'assessment_instructions.yaml' found. The chatbot will have limited knowledge of specific rules.")
        st.session_state.criteria_content = None

    if st.session_state.uploaded_file_content:
        st.success(f"File in memory: **{st.session_state.uploaded_file_name}**")
        
    st.divider()
    verticals = ['CnG', 'Alcohol', 'Office', 'Home Improvement', 'Beauty', 'Sports', 'Electronics', 'Pets', 'Party', 'Paint', 'Shoes']
    st.session_state.vertical = st.selectbox("Select Business Vertical", options=verticals,
                                             index=verticals.index(st.session_state.vertical))
    st.session_state.is_nexla = st.toggle("Nexla Enabled Merchant?", value=st.session_state.is_nexla)
    
    
    default_guides = {
        "CnG": "[Brand] [Dietary Tag] [Variation] [Item Name] [Container] [Size & UOM]",
        "Alcohol": "[Brand] [Dietary Tag] [Flavor] [Variation] [Size] [Color] [Age] [Item Name] [Container] [Appellation Location] [Vintage Year] [Size & UOM]",
        "Home Improvement": "[Brand] [Material/Fabric] [Power] [Variation] [Size] [Color] [Scent] [Item Name] [with Accessories]",
        "Beauty": "[Brand] [Item Name] [Product Type] [Variation] [Size] [Scent] [Color][Size & UOM]",
        "Produce": "[Brand] [Variety] [Item Name] [Container] [Size & UOM]",
        "Other": "[Brand] [Item Name] [Size & UOM]"
    }
    if st.session_state.style_guide == "" or st.session_state.last_vertical != st.session_state.vertical:
        st.session_state.style_guide = default_guides.get(st.session_state.vertical, "")
    st.session_state.last_vertical = st.session_state.vertical
    st.session_state.style_guide = st.text_area("Style Guide", value=st.session_state.style_guide, height=150)
    run_button = st.button("🚀 Run Assessment", type="primary",
                           disabled=(st.session_state.uploaded_file_content is None))

# --- Main UI ---
st.title("✨🚀 Merchant Data Assessment Tool")

# --- Empty State / Welcome Message ---
if not st.session_state.assessment_done and not run_button:
    st.info("👋 Welcome! Upload your data and configure the settings in the sidebar to begin.")
    st.markdown("ℹ️ Note: The assessment rules and taxonomy are now embedded in the app.")

# Create a placeholder for the status message
status_placeholder = st.empty()

if run_button:
    # --- ADDED: Reset the tracker on each new run ---
    st.session_state.api_tracker = ApiUsageTracker()
    if st.session_state.uploaded_file_content:
        # Place the spinning gear message in the placeholder
        status_placeholder.markdown('<h3><span class="spinning-gear">⚙️</span> Running Assessment...</h3>', unsafe_allow_html=True)
        try:
            df = load_dataframe(st.session_state.uploaded_file_content, st.session_state.uploaded_file_name)
            if df is not None:
                with st.spinner('Loading assessment agents...'):
                    agents = discover_agents()
                
                st.divider()
                progress_bar = st.progress(0)
                progress_text = st.empty()
                run_assessment_pipeline(agents, df, st.session_state, progress_bar, progress_text)
                status_placeholder.empty()
                
        except Exception as e:
            status_placeholder.empty() # Clear the placeholder on failure
            st.error(f"❌ Assessment failed: {e}")
            logging.error("Assessment error", exc_info=True)
            st.exception(e)

# --- Results Display (UPDATED WITH MODERN UI) ---
if st.session_state.assessment_done:
    st.page_link("pages/💬_2_Chat_with_Report.py", label="🧠", use_container_width=False)

    st.header("📊 Assessment Results")
    
    # --- Top-level summary cards ---
    col1, col2 = st.columns(2)
    with col1:
        if st.session_state.final_summary:
            with st.container(border=True):
                st.subheader("📌 Final Verdict")
                score = st.session_state.final_summary.get("eligibility_score", "N/A")
                if "Not Eligible" in score:
                    st.error(f"**Verdict:** {score}")
                else:
                    st.success(f"**Verdict:** {score}")
                st.markdown("**Key Reasons:**")
                for reason in st.session_state.final_summary.get("reasons", []):
                    st.markdown(f"- {reason}")
    with col2:
        if st.session_state.website_comparison_report:
            with st.container(border=True):
                st.subheader("🌐 Website Comparison")
                site = st.session_state.website_comparison_report
                st.metric("Assessment", site.get("assessment", "N/A"))
                st.markdown(f"**Reasoning:** {site.get('reasoning', 'N/A')}")
    
    st.divider()

    # --- Tabs for organized results ---
    tab1, tab2, tab3, tab4 = st.tabs(["📈 Summary & Chart", "📋 Detailed Report", "💾 Downloads", "🧾 Full Data"])

    with tab1:
        if st.session_state.summary_df is not None:
            st.subheader("🔍 Issues Summary by Attribute")
            st.dataframe(st.session_state.summary_df, use_container_width=True)
            
            st.divider()

            st.subheader("📊 Visualized Issue Counts")
            chart_df = st.session_state.summary_df.set_index('Attribute')
            st.bar_chart(chart_df['Issues Found'])


    with tab2:
        if st.session_state.full_report:
            st.subheader("📋 Attribute-by-Attribute AI Commentary")
            rows = []
            for attr, data in st.session_state.full_report.items():
                if "error" in data:
                    rows.append({"Attribute": attr, "Assessment": "Error", "Commentary": data["error"]})
                else:
                    rows.append({
                        "Attribute": attr, "Coverage": data.get("coverage", "N/A"),
                        "Duplicates": data.get("duplicates", "N/A"), "Unique Paths": str(data.get("unique_categories", "")),
                        "Assessment": data.get("assessment", "N/A"), "Commentary": data.get("commentary", "N/A"),
                        "Improvements Needed": data.get("improvements", "N/A"), "Bad Examples": data.get("bad_examples", "N/A"),
                        "Corrected Examples": data.get("corrected_examples", "N/A")
                    })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

    with tab3:
        st.subheader("⬇️ Download Center")
        st.info("Download the full report or sample files for further analysis.")
        d_col1, d_col2, d_col3, d_col4 = st.columns(4)
        with d_col1:
            st.download_button("⬇️ Full Detailed Report (.csv)", st.session_state.assessed_csv, "assessment_results.csv", "text/csv", use_container_width=True, type='primary')
        with d_col2:
            st.download_button("⬇️ Name Check Sample (30 SKUs)", st.session_state.sample_30_csv, "sample_30_skus.csv", "text/csv", use_container_width=True, type='primary')
        with d_col3:
            st.download_button("⬇️ Image Check Sample (50 SKUs)", st.session_state.sample_50_csv, "sample_50_skus.csv", "text/csv", use_container_width=True, type='primary')
        
        # st.divider()

        # --- ADDED: New download button for the taxonomy mapping ---
        if st.session_state.get("taxonomy_mapping_csv"):
            with d_col4:
                st.download_button(
                label="⬇️ Download Taxonomy Mapping Assessment (.csv)",
                data=st.session_state.taxonomy_mapping_csv,
                file_name="Taxonomy_Mapping_Assessment.csv",
                mime="text/csv",
                use_container_width=True,
                type="primary" # Make it stand out
            )

    with tab4:
        st.subheader("🧾 Full Assessed Dataset")
        st.info("This table contains the original data with added assessment columns.")
        st.dataframe(st.session_state.assessed_df)

     # --- ADDED: Display the API Usage Report ---
    st.divider()
    st.subheader("💰 API Usage & Cost Report")
    st.info("This table provides an estimate of the tokens used and the cost for this assessment session.")
    usage_df = st.session_state.api_tracker.summary()
    st.dataframe(usage_df, use_container_width=True)

    st.info("Use the Chat tab to ask AI questions about this report.")
