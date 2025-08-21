from .base_agent import BaseAgent
import pandas as pd
import re
from openai import OpenAI
import os
import json
import random
from tqdm import tqdm
import streamlit as st
from io import BytesIO
import docx
import numpy as np
import logging

class Agent(BaseAgent):
    def __init__(self):
        super().__init__("Category")
        self.taxonomy_df = None
        self.vertical = "Grocery"
        self.model = "gpt-4o"

    def assess(self, df: pd.DataFrame, api_key: str = None) -> pd.DataFrame:
        """
        Performs a two-part assessment:
        1. A quick, rule-based and AI quality check on the main DataFrame.
        2. A detailed, separate AI-powered taxonomy mapping against DoorDash standards,
           saving the result to a new file.
        """
        logging.info(f"Running {self.attribute_name} Agent...")
        self.issue_column = 'CategoryIssues?'
        df[self.issue_column] = ''

        # --- Part 1: Initial Assessment (same as before) ---
        df = self.run_initial_assessment(df, api_key)

        # --- Part 2: Detailed Taxonomy Mapping (new logic) ---
        if api_key and self.taxonomy_df is not None:
            logging.info("Running detailed taxonomy mapping assessment...")
            try:
                mapping_df = self.run_detailed_taxonomy_mapping(df, api_key)
                # Save the result to session state for download
                st.session_state.taxonomy_mapping_csv = mapping_df.to_csv(index=False).encode('utf-8')
                logging.info("Detailed taxonomy mapping complete and saved to session state.")
            except Exception as e:
                logging.error(f"Error during detailed taxonomy mapping: {e}", exc_info=True)
                st.session_state.taxonomy_mapping_csv = None
        else:
            st.session_state.taxonomy_mapping_csv = None


        return df

    def run_initial_assessment(self, df: pd.DataFrame, api_key: str) -> pd.DataFrame:
        """Original assessment for quick, high-level feedback."""
        category_cols = [f'L{i}_CATEGORY' for i in range(1, 5) if f'L{i}_CATEGORY' in df.columns]
        if not category_cols:
            df[self.issue_column] = 'No category columns (L1_CATEGORY, etc.) found.'
            return df

        df['Taxonomy Path'] = df[category_cols].astype(str).apply(
            lambda row: ' > '.join([val for val in row if val and pd.notna(val) and str(val).strip().lower() != 'nan']), axis=1
        )

        df.loc[df['L1_CATEGORY'].isnull() | (df['L1_CATEGORY'].astype(str).str.strip() == ''), self.issue_column] += '❌ Blank L1_CATEGORY. '
        if 'L2_CATEGORY' in df.columns:
            df.loc[df['L2_CATEGORY'].isnull() | (df['L2_CATEGORY'].astype(str).str.strip() == ''), self.issue_column] += '❌ Blank L2_CATEGORY. '

        if not api_key:
            df[self.issue_column] += " ℹ️ AI Check Skipped (No API Key)."
            return df

        unique_paths = df[df['Taxonomy Path'] != '']['Taxonomy Path'].dropna().unique()
        sample_paths = random.sample(list(unique_paths), min(10, len(unique_paths)))
        # ... (rest of the initial AI assessment logic can go here if desired) ...
        return df

    def run_detailed_taxonomy_mapping(self, df: pd.DataFrame, api_key: str) -> pd.DataFrame:
        """
        New, intensive AI assessment to map merchant taxonomy to DoorDash standards.
        """
        client = OpenAI(api_key=api_key)
        vertical_taxonomy_rows, l1_col, l2_col = self.get_vertical_taxonomy()

        if vertical_taxonomy_rows.empty:
            logging.error("Could not find taxonomy for the selected vertical. Aborting detailed mapping.")
            return pd.DataFrame({"Error": [f"Could not find taxonomy for the selected vertical: {self.vertical}"]})

        # Sample the catalog data to be assessed
        catalog_df = df.sample(n=min(100, len(df)), random_state=42).reset_index(drop=True)
        catalog_df["Category_Path"] = catalog_df[[f'L{i}_CATEGORY' for i in range(1, 5) if f'L{i}_CATEGORY' in catalog_df.columns]].fillna("").agg(" > ".join, axis=1).str.strip(" >")

        def sample_skus_by_taxonomy(df, samples_per_taxonomy=1):
            return (
                df.groupby("Category_Path", group_keys=False)
                  .apply(lambda x: x.sample(min(len(x), samples_per_taxonomy)))
                  .reset_index(drop=True)
            )

        sampled_catalog_df = sample_skus_by_taxonomy(catalog_df)
        
        # Process in batches
        BATCH_SIZE = 20
        unique_categories = sampled_catalog_df["Category_Path"].unique()
        batches = [unique_categories[i:i + BATCH_SIZE] for i in range(0, len(unique_categories), BATCH_SIZE)]
        final_assessment = []

        for i, batch_categories in enumerate(batches):
            batch_df = sampled_catalog_df[sampled_catalog_df["Category_Path"].isin(batch_categories)]
            sample_rows = batch_df.to_dict('records')
            logging.info(f"Processing batch {i+1}/{len(batches)} for taxonomy mapping...")
            
            assessment_result = self.run_ai_assessment_for_mapping(client, sample_rows, vertical_taxonomy_rows, l1_col, l2_col)
            final_assessment.extend(assessment_result)

        return pd.DataFrame(final_assessment)

    def get_vertical_taxonomy(self):
        """
        Gets the relevant L1/L2 columns from the main taxonomy file.
        This version is case-insensitive to handle variations in CSV column names.
        """
        logging.info(f"Attempting to find taxonomy for vertical: '{self.vertical}'")
        
        # Create a case-insensitive mapping of original column names
        case_insensitive_cols = {col.upper(): col for col in self.taxonomy_df.columns}
        logging.info(f"Taxonomy file columns (case-insensitive): {list(case_insensitive_cols.keys())}")

        mapping = {
            "ALCOHOL": ["ALCOHOL_L1_NAME", "ALCOHOL_L2_NAME"],
            "CNG": ["CNG_L1_NAME", "CNG_L2_NAME"],
            "GROCERY": ["CNG_L1_NAME", "CNG_L2_NAME"],
            "HOME IMPROVEMENT": ["HOME_IMPROVEMENT_L1_NAME", "HOME_IMPROVEMENT_L2_NAME"],
            "BEAUTY": ["BEAUTY_L1_NAME", "BEAUTY_L2_NAME"],
            "PRODUCE": ["PRODUCE_L1_NAME", "PRODUCE_L2_NAME"],
            "OTHER": ["OTHER_L1_NAME", "OTHER_L2_NAME"],
            "SPORTS": ["SPORTS_L1_NAME", "SPORTS_L2_NAME"],
            "ELECTRONICS": ["ELECTRONICS_L1_NAME", "ELECTRONICS_L2_NAME"],
            "PETS": ["PET_L1_NAME", "PET_L2_NAME"],
            "PARTY": ["PARTY_L1_NAME", "PARTY_L2_NAME"],
            "PAINT": ["PAINT_L1_NAME", "PAINT_L2_NAME"],
            "SHOES": ["SHOES_L1_NAME", "SHOES_L2_NAME"],
            "OFFICE": ["OFFICE_L1_NAME", "OFFICE_L2_NAME"]
        }
        
        # Look for the vertical's columns in the case-insensitive map
        l1_col_upper, l2_col_upper = mapping.get(self.vertical.upper(), [None, None])
        
        if not l1_col_upper:
            logging.error(f"No taxonomy mapping defined for vertical: {self.vertical}")
            return pd.DataFrame(), None, None

        logging.info(f"Looking for columns: '{l1_col_upper}' and '{l2_col_upper}'")

        # Get the original column names using the case-insensitive map
        l1_col_original = case_insensitive_cols.get(l1_col_upper)
        l2_col_original = case_insensitive_cols.get(l2_col_upper)

        if not l1_col_original or not l2_col_original:
            logging.error(f"Could not find required columns '{l1_col_upper}' or '{l2_col_upper}' in the taxonomy file.")
            return pd.DataFrame(), None, None
            
        logging.info(f"Found original columns: '{l1_col_original}' and '{l2_col_original}'")
        
        # Filter the dataframe using the original column names
        return self.taxonomy_df[self.taxonomy_df[l1_col_original].notna()], l1_col_original, l2_col_original


    def run_ai_assessment_for_mapping(self, client, sample_rows, vertical_taxonomy_rows, l1_col, l2_col):
        """Constructs the prompt and calls the AI for taxonomy mapping."""
        allowed_pairs_json = json.dumps(
            [{'L1_L2': row[l1_col] + ' > ' + row[l2_col]} for _, row in vertical_taxonomy_rows.drop_duplicates([l1_col, l2_col]).iterrows()],
            indent=2
        )

        system_prompt = (
            f"You are assessing a merchant's taxonomy against DoorDash's standard for the '{self.vertical}' vertical.\n\n"
            "Your Goals:\n"
            "1. Identify categories that are too broad or mismatched.\n"
            "2. Recommend the most precise L1 > L2 taxonomy from the allowed list below.\n"
            "3. Use both item name and image URL to confirm your recommendations.\n\n"
            "Restrictions:\n"
            f"- Only suggest L1 > L2 pairs from the allowed list.\n"
            f"- Allowed DoorDash L1 > L2 taxonomy pairs:\n{allowed_pairs_json}\n\n"
            "Merchant Sample Data:\n"
            f"{json.dumps(sample_rows, indent=2)}\n\n"
            "You MUST respond with only a single, valid JSON object that adheres to the following schema. Do not include any other text, explanations, or markdown formatting.\n"
            "Response Schema:\n"
            "{\n"
            "  \"assessment\": [\n"
            "    {\n"
            "      \"Mx_Category\": \"...\",\n"
            "      \"Issue\": \"Specific but could be matched to a more appropriate category\",\n"
            "      \"Recommended_Taxonomy\": \"<L1_NAME> > <L2_NAME>\",\n"
            "      \"Example_SKUs\": [\"...\"],\n"
            "      \"Considered_Info\": \"Explain how name/image guided your suggestion\"\n"
            "    }\n"
            "  ]\n"
            "}\n"
        )
        
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
            max_tokens=4000,
            response_format={"type": "json_object"} # Force JSON output
        )
        
        content = response.choices[0].message.content
        try:
            # First attempt: direct parsing (most common case)
            return json.loads(content)["assessment"]
        except (json.JSONDecodeError, KeyError):
            # Fallback: use regex to find JSON within the response text
            logging.warning("Direct JSON parsing failed. Attempting regex fallback.")
            try:
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    logging.info("Regex found a JSON-like object. Attempting to parse.")
                    return json.loads(json_match.group())["assessment"]
                else:
                    logging.error("Regex could not find a JSON object in the response.")
                    logging.error(f"Problematic AI response content: {content}")
                    return []
            except (json.JSONDecodeError, KeyError) as e:
                logging.error(f"Fallback JSON parsing also failed. Error: {e}")
                logging.error(f"Problematic AI response content: {content}")
                return []
