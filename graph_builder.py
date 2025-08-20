import pandas as pd
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import Checkpoint
import logging
from langchain_core.messages import AIMessage, BaseMessage

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 1. Define the State of the Graph ---
# This is the shared memory that all agents will have access to.
class AgentState(TypedDict):
    dataframe: pd.DataFrame
    agents: list
    config: dict
    findings: List[str]
    # Adding chat history for more advanced interactions
    messages: List[BaseMessage]

# --- 2. Define the Nodes of the Graph ---
# Each node is a function that performs a specific step in the assessment.

def run_initial_checks_node(state: AgentState) -> AgentState:
    """Runs the fast, rule-based agents first."""
    logging.info("--- Running Initial Checks Node ---")
    df = state['dataframe']
    agents_to_run = [
        "MSID", "UPC", "Brand", "Size", "UOM", "Image",
        "Restricted Item", "Weighted Item", "PLU", "SNAP Eligibility"
    ]
    
    for agent in state['agents']:
        if agent.attribute_name in agents_to_run:
            df = agent.assess(df)
            
    state['dataframe'] = df
    state['findings'].append("Initial rule-based checks completed.")
    return state

def human_approval_node(state: AgentState) -> AgentState:
    """
    This node is a placeholder for the human-in-the-loop step.
    In a real app, this would update the UI and wait for a user's click.
    For now, it just logs that it's ready for approval.
    """
    logging.info("--- Human Approval Node ---")
    state['findings'].append("Initial checks complete. Ready for human approval to proceed with AI analysis.")
    # In a real app, we would use 'interrupt' here to pause the graph.
    # For this script, we will just pass through.
    return state


def run_ai_checks_node(state: AgentState) -> AgentState:
    """Runs the slower, more expensive AI-powered agents."""
    logging.info("--- Running AI Checks Node ---")
    df = state['dataframe']
    config = state['config']
    
    for agent in state['agents']:
        # Check if the agent's assess method can accept an 'api_key' argument
        import inspect
        assess_params = inspect.signature(agent.assess).parameters
        if 'api_key' in assess_params:
            # Configure the agent with settings from the config
            if hasattr(agent, 'vertical'): agent.vertical = config['vertical']
            if hasattr(agent, 'is_nexla_mx'): agent.is_nexla_mx = config['is_nexla']
            if hasattr(agent, 'style_guide'): agent.style_guide = config['style_guide']
            if hasattr(agent, 'model'): agent.model = config['ai_model']
            
            df = agent.assess(df, api_key=config['api_key'])

    state['dataframe'] = df
    state['findings'].append("AI-powered checks completed.")
    return state

# --- 3. Define the Conditional Logic (Edges) ---

def should_run_ai_checks(state: AgentState) -> str:
    """
    This is the decision-making router. It checks the results of the initial
    checks to decide if it's worth running the expensive AI agents.
    """
    logging.info("--- Making decision: Should run AI? ---")
    df = state['dataframe']
    
    # Example Rule: If more than 50% of MSIDs are blank, the data is too poor to continue.
    if 'MSIDIssues?' in df.columns:
        blank_msid_rate = df['MSIDIssues?'].str.contains("Blank or Default").sum() / len(df)
        if blank_msid_rate > 0.5:
            logging.warning("Over 50% of MSIDs are blank. Skipping expensive AI checks.")
            state['findings'].append("High rate of blank MSIDs detected. Skipped AI analysis.")
            return "end" # Go directly to the end of the graph
            
    logging.info("Data quality is sufficient. Proceeding to human approval.")
    return "continue_to_approval" # Continue to the next step

# --- 4. Assemble the Graph ---

def build_graph():
    """Builds and returns the LangGraph workflow."""
    workflow = StateGraph(AgentState)

    # Add the nodes
    workflow.add_node("initial_checks", run_initial_checks_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("ai_checks", run_ai_checks_node)

    # Define the entry point
    workflow.set_entry_point("initial_checks")

    # Add the conditional edge
    workflow.add_conditional_edges(
        "initial_checks",
        should_run_ai_checks,
        {
            "continue_to_approval": "human_approval",
            "end": END
        }
    )
    
    # Add the edge from approval to the AI step
    workflow.add_edge("human_approval", "ai_checks")
    
    # The AI checks node always goes to the end
    workflow.add_edge("ai_checks", END)

    # Compile the graph into a runnable app
    return workflow.compile()
