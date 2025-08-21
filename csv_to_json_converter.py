import pandas as pd
import json

def convert_csv_to_json(csv_file_path, json_file_path):
    """
    Reads a CSV file, converts it to a JSON format, and saves it.

    Args:
        csv_file_path (str): The path to the input CSV file.
        json_file_path (str): The path to the output JSON file.
    """
    try:
        # Read the CSV file into a pandas DataFrame
        df = pd.read_csv(csv_file_path)

        # Convert the DataFrame to a list of dictionaries (records format)
        records = df.to_dict(orient='records')
        
        # Structure the data under a single 'taxonomy' key
        json_data = {"taxonomy": records}

        # Write the data to a JSON file
        with open(json_file_path, 'w') as f:
            json.dump(json_data, f, indent=2)

        print(f"Successfully converted '{csv_file_path}' to '{json_file_path}'.")
    except FileNotFoundError:
        print(f"Error: The file at '{csv_file_path}' was not found.")
    except Exception as e:
        print(f"An error occurred during conversion: {e}")

# --- Main execution ---
if __name__ == "__main__":
    csv_file = 'taxonomy.csv'  # Your original CSV file
    json_file = 'taxonomy.json' # The new JSON file to be created

    # Run the conversion script
    convert_csv_to_json(csv_file, json_file)
