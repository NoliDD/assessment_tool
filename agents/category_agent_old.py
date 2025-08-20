from .base_agent import BaseAgent
import pandas as pd
import re
from openai import OpenAI
import os
import json
import random
from tqdm import tqdm

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Category")
        # These attributes will be set by the main Streamlit script before 'assess' is called
        self.taxonomy_df = None
        self.vertical = "Grocery"
        self.model = "gpt-4o"

    def assess(self, df: pd.DataFrame, api_key: str = None) -> pd.DataFrame:
        """
        Assesses merchant categories by creating a unified path, checking for blanks,
        and using AI to determine the quality, granularity, and mappability of the taxonomy.
        """
        print(f"Running {self.attribute_name} Agent...")
        self.issue_column = 'CategoryIssues?'
        df[self.issue_column] = ''

        # --- 1. Create a Unified Taxonomy Path (as per instructions) ---
        category_cols = [f'L{i}_CATEGORY' for i in range(1, 5) if f'L{i}_CATEGORY' in df.columns]
        if not category_cols:
            df[self.issue_column] = 'No category columns (L1_CATEGORY, etc.) found.'
            return df
            
        df['Taxonomy Path'] = df[category_cols].astype(str).apply(
            lambda row: ' > '.join([val for val in row if val and pd.notna(val) and str(val).strip().lower() != 'nan']), axis=1
        )

        # --- 2. Basic Rule-Based Checks (Only for critical missing data) ---
        # We only flag if the foundational L1 or L2 categories are missing.
        df.loc[df['L1_CATEGORY'].isnull() | (df['L1_CATEGORY'].astype(str).str.strip() == ''), self.issue_column] += '❌ Blank L1_CATEGORY. '
        if 'L2_CATEGORY' in df.columns:
            df.loc[df['L2_CATEGORY'].isnull() | (df['L2_CATEGORY'].astype(str).str.strip() == ''), self.issue_column] += '❌ Blank L2_CATEGORY. '
        
        # --- 3. AI-Powered Qualitative Assessment (The Core Logic) ---
        if not api_key:
            print("️ OpenAI API key not provided. Skipping AI analysis for Categories.")
            df[self.issue_column] += " ℹ️ AI Check Skipped (No API Key)."
            return df

        print(f"Performing AI-powered category assessment for '{self.vertical}' vertical...")
        try:
            
            # --- Prepare Context for the AI ---
            # Get a unique sample of merchant taxonomy paths to analyze (as per instructions)
            # We filter out paths that are already blank to focus the AI's work.
            unique_paths = df[df['Taxonomy Path'] != '']['Taxonomy Path'].dropna().unique()
            sample_paths = random.sample(list(unique_paths), min(10, len(unique_paths)))

            # For each sample path, get a few example item names to provide context to the AI
            sample_context = {}
            for path in sample_paths:
                # Ensure CONSUMER_FACING_ITEM_NAME exists before trying to access it
                if 'CONSUMER_FACING_ITEM_NAME' in df.columns:
                    sample_items = df[df['Taxonomy Path'] == path]['CONSUMER_FACING_ITEM_NAME'].head(3).tolist()
                    sample_context[path] = sample_items
                else:
                    sample_context[path] = ["Item name column not found."]


            # This detailed prompt is based directly on the new criteria you provided
            prompt = f"""
            You are a data analyst reviewing a merchant's product categories. Your goal is to determine if their categories are high-quality and can be mapped to DoorDash's taxonomy.

            **Assessment Criteria:**
            - **Goal:** Categories must be distinct and granular. Avoid "blanket categories" like 'Gifts' or 'Best Sellers'.
            - **Red Flag:** A category is "too broad" if it contains many different types of items that should be in separate sub-categories (e.g., a main category of "Beer" is too broad because it contains IPAs, Stouts, etc., which are sub-categories on DoorDash).
            - **Scoring:**
              - **Perfect:** High-quality, granular categories with 100% coverage.
              - **Has Some Issues:** Good coverage, but some categories are too broad or have other nuances.
              - **Missing or Unusable:** Many missing categories, or most categories are too broad and generic to be useful.

            **Your Task:**
            For each of the merchant's unique taxonomy paths provided below (along with sample items in that path), provide a JSON object with these keys:
            - "assessment_score": string. Your final score for this specific category path, choosing from "Perfect", "Has Some Issues", or "Missing or Unusable".
            - "notes": string. Detailed notes explaining your reasoning. Specifically mention if the category is too broad, if the items are relevant, and provide examples.

            Return a single JSON object where the keys are the merchant's original taxonomy paths.

            **Merchant Taxonomy Paths and Sample Items to Assess:**
            {json.dumps(sample_context, indent=2)}
            """
            
            ai_results = self.call_ai(prompt, api_key, self.model)

            # Map the AI results back to the original DataFrame
            def apply_ai_feedback(path):
                feedback = ai_results.get(path)
                if not feedback:
                    return ""
                
                score = feedback.get("assessment_score", "N/A")
                notes = feedback.get("notes", "No notes provided.")
                
                # Format the feedback for the 'Issues?' column
                if score != "Perfect":
                    return f"AI Assessment: {score} - {notes}"
                return "" # No issue to report if the AI deems it perfect

            # Create a mapping from path to feedback
            path_to_feedback = {path: apply_ai_feedback(path) for path in sample_paths}
            
            # Apply the feedback to the 'CategoryIssues?' column
            df[self.issue_column] += df['Taxonomy Path'].map(path_to_feedback).fillna("")

        except Exception as e:
            df[self.issue_column] += f'⚠️ An unexpected error occurred during AI taxonomy validation: {e}'

        return df
