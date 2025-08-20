import argparse
import pandas as pd
from agents.exclusion_agent import Agent
from dotenv import load_dotenv
import os

# Load API key from .env
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

def main():
    parser = argparse.ArgumentParser(description="Run Exclusion Agent for testing.")
    parser.add_argument("--input", "-i", required=True, help="Path to input CSV")
    parser.add_argument("--output", "-o", required=True, help="Path to save results")
    args = parser.parse_args()

    df = pd.read_csv(args.input)

    agent = Agent()
    result_df = agent.assess(df, api_key=api_key)

    # 🔽 Only export relevant columns
    columns_to_save = ["BIZID_MSID", "CONSUMER_FACING_ITEM_NAME", "ExclusionIssues?"]
    missing = [col for col in columns_to_save if col not in result_df.columns]
    if missing:
        print(f"❌ ERROR: Missing required columns in input: {missing}")
        return

    result_df[columns_to_save].to_csv(args.output, index=False)
    print(f"✅ Done! Results written to {args.output}")

if __name__ == "__main__":
    if not api_key:
        print("❌ ERROR: OPENAI_API_KEY not found in .env. Please add it.")
    else:
        main()
