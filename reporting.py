import gspread

def generate_summary_text(df, agents):
    """
    Generates a text summary of the assessment from the agents' findings.
    """
    print("Generating summary report text...")
    report_lines = ["--- Mx Data Assessment Summary ---"]
    total_items = len(df)
    report_lines.append(f"Total Items Assessed: {total_items}\n")

    for agent in agents:
        summary = agent.get_summary(df)
        report_lines.append(f"'{summary['name']}' issues found in: {summary['issue_count']} items ({summary['issue_percent']:.2f}%)")

    return "\n".join(report_lines)


def update_google_sheet(gsheet_client, config, summary_data):
    """
    Updates the Google Sheet with summary data, providing detailed logs.
    """
    gs_config = config['google_sheets']
    if not gs_config.get("enabled"):
        print("Google Sheets integration is disabled in config.")
        return

    try:
        sheet_id = gs_config.get("sheet_id")
        tab_name = gs_config.get("tab_name")
        attr_col_letter = gs_config.get("attribute_column_letter", "A")
        target_col_letter = gs_config.get("target_column_letter", "N")

        print(f"Connecting to Google Sheet (ID: {sheet_id})...")
        spreadsheet = gsheet_client.open_by_key(sheet_id)
        print(f"Accessing tab: '{tab_name}'...")
        worksheet = spreadsheet.worksheet(tab_name)
        print("✅ Successfully connected to worksheet.")

        # This map defines what text to find in your sheet vs. what key to use from the summary data
        update_map = {
            "Insert the total number of age-restricted items found on the catalog and are indicated with the merchants age-restricted column": "age_restricted_count",
            "Please put in the total number of weighted items the merchant has marked as weighted": "total_weighted_items"
            # Add other mappings here based on the text in your Google Sheet's 'Instructions' column
        }

        for find_text, data_key in update_map.items():
            try:
                print(f"Searching for row with text: '{find_text}'...")
                cell = worksheet.find(find_text)
                
                # Check if the key exists in your summary_data dictionary
                if data_key in summary_data:
                    target_value = summary_data[data_key]
                    print(f"Found at row {cell.row}. Attempting to update column {target_col_letter} with value: '{target_value}'")
                    
                    target_col_index = gspread.utils.a1_to_rowcol(f"{target_col_letter}1")[1]
                    worksheet.update_cell(cell.row, target_col_index, str(target_value)) # Convert value to string
                    print(f"✅ Successfully updated cell.")
                else:
                    print(f"⚠️ Warning: Data key '{data_key}' not found in summary data. Skipping update.")

            except gspread.exceptions.CellNotFound:
                print(f"⚠️ Could not find cell with text: '{find_text}' in the sheet.")
            except Exception as e:
                print(f"❌ Failed to update row for '{find_text}'. Reason: {e}")

    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ ERROR: Spreadsheet not found. Double-check the Sheet ID and sharing permissions.")
    except gspread.exceptions.WorksheetNotFound:
        print(f"❌ ERROR: Worksheet '{tab_name}' not found. Check that the Tab Name is correct.")
    except Exception as e:
        import traceback
        print(f"❌ An unexpected error occurred with Google Sheets.")
        traceback.print_exc()