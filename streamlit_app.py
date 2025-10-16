import streamlit as st
import pandas as pd
import os
import importlib
import inspect
import logging
from io import BytesIO
from utils import validate_api_key
from agents.api_tracker import ApiUsageTracker
import json
import yaml
import numpy as np
import re
import nest_asyncio
from ui import add_footer

# --- FIX: Apply nest_asyncio patch to prevent "Event loop is closed" error ---
nest_asyncio.apply()

# --- Page Setup ---
# st.set_page_config(layout="wide", page_title="Mx Data Assessment Tool", page_icon="✨🚀")
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
    "api_key": "", "api_key_validated": False, "ai_model": "gpt-5-chat-latest",
    "website_url": "", "uploaded_file_content": None, "uploaded_file_name": "",
    "taxonomy_df": None, "criteria_content": None, "vertical": "CnG",
    "is_nexla": False, "style_guide": "", "last_vertical": "",
    "assessed_df": None, "summary_df": None, "full_report": None,
    "website_comparison_report": None, "final_summary": None,
    "assessed_csv": None, "sample_30_csv": None, "sample_50_csv": None,
    "assessment_done": False,
    "agent_model": "gpt-5-chat-latest"
}
for key, val in default_session_state.items():
    if key not in st.session_state:
        st.session_state[key] = val

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
def load_and_standardize_dataframe(file_content, file_name):
    """
    Loads a dataframe from file content and standardizes column names
    to ensure consistency for all downstream agents. This function is cached
    and contains no Streamlit UI elements.
    """
    try:
        dtype_spec = {'BUSINESS_ID': str, 'MSID': str, 'UPC': str}
        
        if file_name.lower().endswith('.csv'):
            df = pd.read_csv(BytesIO(file_content), low_memory=False, dtype=dtype_spec)
        elif file_name.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(BytesIO(file_content), dtype=dtype_spec)
        else:
            logging.error("Unsupported file type provided.")
            return None

        # --- Column Standardization Logic ---
        column_mapping = {
            'merchant supplied id (msid)': 'MSID', 
            'item name': 'CONSUMER_FACING_ITEM_NAME',
            'brand': 'BRAND_NAME', 
            'photo url': 'IMAGE_URL', 
            'size': 'SIZE',
            'unit of measure': 'UNIT_OF_MEASUREMENT', 
            'uom': 'UNIT_OF_MEASUREMENT',
            'l1 category': 'L1_CATEGORY', 'l2 category': 'L2_CATEGORY',
            'l3 category': 'L3_CATEGORY', 'l4 category': 'L4_CATEGORY',
            'product group': 'PRODUCT_GROUP', 
            'variant': 'VARIANT', 
            'details': 'DESCRIPTION',
            'short_description': 'DESCRIPTION', 
            'weighted item': 'IS_WEIGHTED_ITEM',
            'average weight': 'AVERAGE_WEIGHT_PER_EACH', 
            'snap': 'SNAP_ELIGIBLE', 
            'plu': 'PLU'
        }
        canonical_map = {k: v for k, v in column_mapping.items()}
        for target_name in column_mapping.values():
            canonical_map[target_name.lower()] = target_name
        
        df.rename(columns=lambda c: canonical_map.get(c.strip().lower(), c), inplace=True)
        logging.info(f"Standardized columns. New columns: {df.columns.tolist()}")
        return df
        
    except Exception as e:
        logging.error(f"Error reading and standardizing file: {e}")
        return None

# --- Helper Functions ---
def configure_agent(agent, session):
    mapping = {
        'taxonomy_df': 'taxonomy_df', 'vertical': 'vertical',
        'is_nexla_mx': 'is_nexla', 'style_guide': 'style_guide',
    }
    for agent_attr, session_key in mapping.items():
        if hasattr(agent, agent_attr):
            setattr(agent, agent_attr, session.get(session_key))
    if hasattr(agent, 'model'):
        setattr(agent, 'model', session.get('agent_model'))

def run_assessment_pipeline(agents, df, session, progress_bar, progress_text):
    reporting_agent = next((a for a in agents if a.attribute_name == "Master Reporting"), None)
    website_agent = next((a for a in agents if a.attribute_name == "Website Comparison"), None)
    final_summary_agent = next((a for a in agents if a.attribute_name == "Final Summary"), None)
    concat_agent = next((a for a in agents if a.attribute_name == "Nexla Concatenation"), None)

    EXCLUDE = {"Master Reporting", "Website Comparison", "Final Summary", "Nexla Concatenation"}
    assessment_agents = [a for a in agents if getattr(a, "attribute_name", "").strip() not in EXCLUDE]
    assessment_agents.sort(key=lambda a: 0 if getattr(a, "attribute_name", "").strip().lower().startswith("category") else 1)

    total_steps = len(assessment_agents)
    if session.is_nexla and concat_agent:
        total_steps += 1
    if reporting_agent and session.api_key_validated:
        total_steps += 1
    if website_agent and session.api_key_validated:
        total_steps += 1
    total_steps += 3 

    step = 0
    
    # --- Centralized Data Cleaning Step for Calculations ---
    step += 1
    progress_text.info(f"Step {step}/{total_steps}: Standardizing data types for calculation...")
    progress_bar.progress(min(1.0, step / total_steps))
    
    boolean_flags = ['IS_WEIGHTED_ITEM', 'IS_ALCOHOL', 'IS_CBD', 'SNAP_ELIGIBLE']
    for flag_col in boolean_flags:
        if flag_col in df.columns:
            df[flag_col] = pd.to_numeric(df[flag_col], errors='coerce')
    
    logging.info("Data types standardized for all agents.")
    
    if session.is_nexla and concat_agent:
        step += 1
        progress_text.info(f"Step {step}/{total_steps}: Running Nexla Concatenation...")
        progress_bar.progress(min(1.0, step / total_steps))
        df = concat_agent.assess(df)

    for agent in assessment_agents:
        step += 1
        progress_text.info(f"Step {step}/{total_steps}: Running {agent.attribute_name} Agent...")
        progress_bar.progress(min(1.0, step / total_steps))
        configure_agent(agent, session)
        
        agent_params = inspect.signature(agent.assess).parameters
        if 'api_key' in agent_params:
            df = agent.assess(df, api_key=session.api_key)
        else:
            df = agent.assess(df)

    step += 1
    progress_text.info(f"Step {step}/{total_steps}: Generating summaries...")
    progress_bar.progress(min(1.0, step / total_steps))
    
    summary_data = [agent.get_summary(df) for agent in assessment_agents]
    summary_df = pd.DataFrame(summary_data)
    total_skus = len(df)
    
    summary_df['issue_count'] = pd.to_numeric(summary_df['issue_count'], errors='coerce').fillna(0)
    summary_df['Issue Rate'] = summary_df.apply(
        lambda row: f"{(row['issue_count'] / total_skus * 100):.2f}%" if total_skus > 0 else "0.00%", axis=1)
    
    summary_df.rename(columns={'name': 'Attribute', 'issue_count': 'Issues Found'}, inplace=True)
    
    display_cols = ['Attribute', 'Issues Found', 'Issue Rate']
    for col in ['coverage_count', 'duplicate_count']:
        if col in summary_df.columns:
            display_cols.append(col)
            
    st.session_state.summary_df = summary_df[display_cols]

    if reporting_agent and session.api_key_validated:
        step += 1
        progress_text.info(f"Step {step}/{total_steps}: Generating Attribute-by-Attribute Report...")
        progress_bar.progress(min(1.0, step / total_steps))
        st.session_state.full_report = reporting_agent.assess(df, vertical=session.vertical, api_key=session.api_key)

    if website_agent and session.api_key_validated:
        step += 1
        progress_text.info(f"Step {step}/{total_steps}: Generating Website Comparison Report...")
        progress_bar.progress(min(1.0, step / total_steps))
        st.session_state.website_comparison_report = website_agent.assess(df, api_key=session.api_key, website_url=session.website_url)
            
    if final_summary_agent and session.api_key_validated:
        st.session_state.final_summary = final_summary_agent.assess(st.session_state.full_report, api_key=session.api_key)
            
        step += 1
        progress_text.info(f"Step {step}/{total_steps}: Preparing final report for display...")
        progress_bar.progress(min(1.0, step / total_steps))
    
    # --- **FIX**: New, more robust final cleanup function for display ---
    logging.info("Performing final cleanup of the assessed DataFrame for display.")
    display_df = df.copy()

    # Convert boolean columns to clean True/False strings for display
    for flag_col in boolean_flags:
        if flag_col in display_df.columns:
            # Map 1.0 to 'True', 0.0 to 'False', and everything else (NaN) to an empty string
            display_df[flag_col] = display_df[flag_col].apply(lambda x: 'True' if x == 1.0 else ('False' if x == 0.0 else ''))

    # Convert all other columns to string type to prevent mixed-type errors
    for col in display_df.columns:
        if col not in boolean_flags:
             # Fill NaNs before converting to string, and remove trailing '.0' from numbers
             display_df[col] = display_df[col].fillna('').astype(str).replace(r'\.0$', '', regex=True)

    # --- FIX: Use a more robust, column-specific method for case-insensitive 'nan' replacement ---
    for col in display_df.select_dtypes(include=['object']).columns:
        # Use str.replace with case=False, which is the correct method for Series objects
        display_df[col] = display_df[col].str.replace('nan', '', case=False, regex=True)
        
    display_df = reorder_columns_for_readability(display_df, session.is_nexla)
    st.session_state.assessed_df = display_df
    # --- End of New Cleanup Step ---
            
    st.session_state.assessed_csv = display_df.to_csv(index=False).encode('utf-8')
    st.session_state.sample_30_csv = generate_sample_csv(display_df, ["UPC", "IMAGE_URL", "CONSUMER_FACING_ITEM_NAME", "SIZE", "UNIT_OF_MEASUREMENT"], 30)
    st.session_state.sample_50_csv = generate_sample_csv(display_df, ["MSID", "IMAGE_URL"], 50)
    st.session_state.assessment_done = True
    progress_text.success("✅ Assessment complete!")
    st.balloons()


def reorder_columns_for_readability(df, is_nexla):
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
        ['IS_WEIGHTED_ITEM', 'WeightedItemIssues?', 'AVERAGE_WEIGHT_PER_EACH', 'AverageWeightIssues?', 'AVERAGE_WEIGHT_UOM'], ['PLU', 'PLUIssues?'],
        ['IS_ALCOHOL', 'IS_CBD', 'RestrictedItemIssues?', 'ExclusionIssues?'],
        ['SNAP_ELIGIBLE', 'SNAPEligibilityIssues?'],
        ['PRODUCT_GROUP', 'ProductGroupIssues?'],
        ['VARIANT', 'VariantIssues?'],
        ['ADDITIONAL_IMAGE_URLS','AuxPhotoIssues?', 'All_Aux_Photos_URLs'],
        ['SHORT_DESCRIPTION', 'DESCRIPTION', 'DETAILS', 'DescriptionIssues?']
    ]
    reordered, seen = [], set()
    for group in groups:
        for col in group:
            if col in df.columns and col not in seen:
                reordered.append(col)
                seen.add(col)
    return df[reordered + [col for col in df.columns if col not in seen]]

def generate_sample_csv(df, columns, n):
    selected_cols = [col for col in columns if col in df.columns]
    sample_df = df.sample(n=min(n, len(df)))[selected_cols]
    return sample_df.to_csv(index=False).encode('utf-8')

# --- Call CSS function ---
load_css()

# --- Sidebar UI ---
with st.sidebar:
    st.header("⚙️ Configuration")
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
        ["gpt-5-chat-latest", "gpt-4o"],
        index=["gpt-5-chat-latest", "gpt-4o"].index(st.session_state.agent_model))
        
    st.session_state.website_url = st.text_input("Merchant Website URL", value=st.session_state.website_url)
    uploaded_file = st.file_uploader("1. Upload Merchant Data File", type=["csv", "xlsx"])
    if uploaded_file:
        st.session_state.uploaded_file_content = uploaded_file.read()
        st.session_state.uploaded_file_name = uploaded_file.name
    
    try:
        if os.path.exists('taxonomy.json'):
            with open('taxonomy.json', 'r') as f:
                taxonomy_data = json.load(f)
                st.session_state.taxonomy_df = pd.DataFrame(taxonomy_data['taxonomy'])
            # st.success("Taxonomy Loaded")
                logging.info(f"Taxonomy Loaded")
        else:
            st.warning("No local 'taxonomy.json' found. Taxonomy-based agents will be limited.")
    except Exception as e:
        st.error(f"Error loading local taxonomy file: {e}")
        st.session_state.taxonomy_df = None
        
    try:
        with open('assessment_instructions.yaml', 'r') as f:
            st.session_state.criteria_content = f.read()
        # st.success("Assessment Criteria Loaded")
            logging.info(f'Assessment Criteria Loaded')
            
    except FileNotFoundError:
        st.warning("No local 'assessment_instructions.yaml' found. The chatbot will have limited knowledge of specific rules.")
        st.session_state.criteria_content = None

    if st.session_state.uploaded_file_content:
        st.success(f"File in memory: **{st.session_state.uploaded_file_name}**")
        
    st.divider()
    
    verticals = ['CnG', 'Alcohol', 'Office', 'Home Improvement', 'Beauty', 'Sports', 'Electronics', 'Pets', 'Party', 'Halloween', 'Home', 'Outdoor']
    st.session_state.vertical = st.selectbox("Select Business Vertical", options=verticals,
                                             index=verticals.index(st.session_state.vertical))
    st.session_state.is_nexla = st.toggle("Nexla Enabled Merchant?", value=st.session_state.is_nexla)
    
    default_guides = {
        "CnG": "[Brand] [Dietary Tag] [Variation] [Item Name] [Container] [Size & UOM]",
        "Alcohol": "[Brand] [Dietary Tag] [Flavor] [Variation] [Size] [Color] [Age] [Item Name] [Container] [Appellation Location] [Vintage Year] [Size & UOM]",
        "Office": "[Brand] [Variation] [Size] [Color] [Item Name] [Product Key]",
        "Home Improvement": "[Brand] [Material/Fabric] [Power] [Variation] [Size] [Color] [Scent] [Item Name] [with Accessories]",
        "Beauty": "[Brand] [Item Name] [Product Type] [Variation] [Size] [Scent] [Color][Size & UOM]",
        "Sports": "[Brand] [Age (specific to infant clothing)] [Gender] [Collection/Sub Brand] [Quantity if more than 1, e.g., '2 Pack' or '2 Piece'] [Style] [Color] [Fabric] [Item Name]",
        "Electronics": "[Brand] [Variant 1] [Variant 2] [Size] [Color] [Item Name] [with Additional Detail] ['(Open Box)']",
        "Pets": "[Brand] [Item Name] [Variation] [Dietary Tag] [Flavor] [Size] [Color] [Pet/Animal Type] [Container]",
        "Party": "[Brand/exclude if parent brand] [Variation] [Size] [Color] [Item Name]",
        "Halloween": "[Brand] [Item Name] [Size] [Quantity]",
        "Home": "[Brand] [Material/Fabric] [Variation] [Size] [Color] [Scent] [Room] [Item Name]",
        "Produce": "[Brand] [Variety] [Item Name] [Container] [Size & UOM]",
        "Outdoor": "[Brand] [Gender/Age] [Variation] [Color] [Size] [Sport/Activity] [Item Name] [Clothing Size]"
    }
    if st.session_state.style_guide == "" or st.session_state.last_vertical != st.session_state.vertical:
        st.session_state.style_guide = default_guides.get(st.session_state.vertical, "")
    st.session_state.last_vertical = st.session_state.vertical
    st.session_state.style_guide = st.text_area("Style Guide", value=st.session_state.style_guide, height=150)
    run_button = st.button("🚀 Run Assessment", type="primary",
                           disabled=(st.session_state.uploaded_file_content is None))
    
    add_footer()

# --- Main UI ---
st.title("✨🚀 Merchant Data Assessment Tool")

if not st.session_state.assessment_done and not run_button:
    st.info("👋 Welcome! Upload your data and configure the settings in the sidebar to begin.")
    # st.markdown("ℹ️ Note: The assessment rules and taxonomy are now embedded in the app.")

status_placeholder = st.empty()

if run_button:
    st.session_state.api_tracker = ApiUsageTracker()
    if st.session_state.uploaded_file_content:
        status_placeholder.markdown('<h3><span class="spinning-gear">⚙️</span> Running Assessment...</h3>', unsafe_allow_html=True)
        try:
            df = load_and_standardize_dataframe(st.session_state.uploaded_file_content, st.session_state.uploaded_file_name)
            
            if df is not None:
                st.toast("DataFrame loaded and columns standardized.", icon="✅")
                with st.spinner('Loading assessment agents...'):
                    agents = discover_agents()
                
                st.divider()
                progress_bar = st.progress(0)
                progress_text = st.empty()
                run_assessment_pipeline(agents, df, st.session_state, progress_bar, progress_text)
                status_placeholder.empty()
            else:
                status_placeholder.empty()
                st.error("❌ Failed to load or process the data file. Please check the file format and content.")

        except Exception as e:
            status_placeholder.empty()
            st.error(f"❌ Assessment failed with an unexpected error: {e}")
            logging.error("Assessment error", exc_info=True)
            st.exception(e)

# --- Results Display ---
if st.session_state.assessment_done:
    st.page_link("pages/💬_2_Chat_with_Report.py", label="🧠", width='content')

    st.header("📊 Assessment Results")
    
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

    tab1, tab2, tab3, tab4 = st.tabs(["📈 Summary & Chart", "📋 Detailed Report", "💾 Downloads", "🧾 Full Data"])

    with tab1:
        if st.session_state.summary_df is not None:
            st.subheader("🔍 Issues Summary by Attribute")
            st.dataframe(st.session_state.summary_df, width='stretch')
            
            st.divider()

            st.subheader("📊 Visualized Issue Counts")
            chart_df = st.session_state.summary_df.set_index('Attribute')
            st.bar_chart(chart_df['Issues Found'])

    with tab2:
        if st.session_state.full_report:
            st.subheader("📋 Attribute-by-Attribute AI Commentary")
            rows = []
            for attr, data in st.session_state.full_report.items():
                if isinstance(data, dict):
                    bad_examples = data.get("bad_examples", "N/A")
                    if isinstance(bad_examples, (list, dict)):
                        bad_examples = json.dumps(bad_examples, indent=2)
                    
                    corrected_examples = data.get("corrected_examples", "N/A")
                    if isinstance(corrected_examples, (list, dict)):
                        corrected_examples = json.dumps(corrected_examples, indent=2)

                    if "error" in data:
                        rows.append({"Attribute": attr, "Assessment": "Error", "Commentary": data["error"]})
                    else:
                        rows.append({
                            "Attribute": attr, "Coverage": data.get("coverage", "N/A"),
                            "Duplicates": data.get("duplicates", "N/A"), "Unique Paths": str(data.get("unique_categories", "")),
                            "Assessment": data.get("assessment", "N/A"), "Commentary": data.get("commentary", "N/A"),
                            "Improvements Needed": data.get("improvements", "N/A"),
                            "Bad Examples": bad_examples,
                            "Corrected Examples": corrected_examples
                        })
            st.dataframe(pd.DataFrame(rows), width='stretch')

    with tab3:
        st.subheader("⬇️ Download Center")
        st.info("Download the full report or sample files for further analysis.")
        d_col1, d_col2, d_col3, d_col4 = st.columns(4)
        with d_col1:
            st.download_button("⬇️ Full Detailed Report (.csv)", st.session_state.assessed_csv, "assessment_results.csv", "text/csv", width='stretch', type='primary')
        with d_col2:
            st.download_button("⬇️ Name Check Sample (30 SKUs)", st.session_state.sample_30_csv, "name_check_sample_30_skus.csv", "text/csv", width='stretch', type='primary')
        with d_col3:
            st.download_button("⬇️ Image Check Sample (50 SKUs)", st.session_state.sample_50_csv, "image_check_sample_50_skus.csv", "text/csv", width='stretch', type='primary')
        
        if st.session_state.get("taxonomy_mapping_csv"):
            with d_col4:
                st.download_button(
                label="⬇️ Download Taxonomy Mapping Assessment (.csv)",
                data=st.session_state.taxonomy_mapping_csv,
                file_name="Taxonomy_Mapping_Assessment.csv",
                mime="text/csv",
                width='stretch',
                type="primary"
            )

    with tab4:
        st.subheader("🧾 Full Assessed Dataset")
        st.info("This table contains the original data with added assessment columns.")
        st.dataframe(st.session_state.assessed_df)

    st.divider()
    st.subheader("💰 API Usage & Cost Report")
    st.info("This table provides an estimate of the tokens used and the cost for this assessment session.")
    usage_df = st.session_state.api_tracker.summary()
    st.dataframe(usage_df, width='stretch')

    st.info("Use the Chat tab to ask AI questions about this report.")


# call once near the end of each page:
add_footer()