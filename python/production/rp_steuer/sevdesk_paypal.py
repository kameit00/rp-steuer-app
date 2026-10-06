import argparse
import csv
import datetime
import glob
import json
import os
import re
from collections import defaultdict

import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side


def process_csv_files(delete_csv=False, directory=None):
    """
    Process all CSV files in the specified directory, adding an 'Info' column based on rules from a JSON file.
    Output files are Excel files named based on the dates in the Bezahldatum column.
    Includes summary statistics at the bottom of each file.
    
    Args:
        delete_csv (bool): If True, deletes the CSV files after successful processing. Default is False.
        directory (str): Directory to process CSV files from. If None, uses current directory. Default is None.
    """
    # Set the working directory
    if directory is None:
        directory = os.getcwd()
    else:
        # Convert to absolute path and validate
        directory = os.path.abspath(directory)
        if not os.path.exists(directory):
            print(f"Error: Directory '{directory}' does not exist.")
            return
        if not os.path.isdir(directory):
            print(f"Error: '{directory}' is not a directory.")
            return
    
    print(f"Processing CSV files in directory: {directory}")
    
    # Load or create rules
    rules_file = os.path.join(directory, "rules.json")
    if not os.path.exists(rules_file):
        default_rules = [
            {"column": "Beschreibung", "substring": "relax-pillow Kundennr.", "info_column_value": "ZE Kunde"},
            {"column": "Beschreibung", "substring": "Gebühren", "info_column_value": "Gebühr"}
        ]
        with open(rules_file, 'w', encoding='utf-8') as f:
            json.dump(default_rules, f, indent=4, ensure_ascii=False)
        print(f"Created default rules file at {rules_file}")

    # Load rules from JSON file
    with open(rules_file, 'r', encoding='utf-8') as rules_file:
        rules_data = json.load(rules_file)

        # Handle both old format (list) and new format (dict)
        if isinstance(rules_data, list):
            rules = rules_data
            always_show_categories = []
        else:
            rules = rules_data.get("rules", [])
            always_show_categories = rules_data.get("always_show_in_summary", [])

    # Extract all possible "Info" values from rules for later use in summaries
    info_categories = [rule["info_column_value"] for rule in rules]

    # Find all CSV files in the current directory
    csv_files = glob.glob(os.path.join(directory, "*.csv"))
    if not csv_files:
        print("No CSV files found in the current directory.")
        return

    for input_file in csv_files:
        # Skip files that might be our own output files
        if re.match(r"\d{4}-\d{2}-Paypal\.csv", os.path.basename(input_file)):
            print(f"Ignoring {input_file}, could be our own output file.")
            continue

        try:
            # Read the CSV file to determine the actual structure
            with open(input_file, 'r', newline='', encoding='utf-8') as infile:
                # Detect if the file uses semicolons as delimiters
                sample = infile.read(4096)
                infile.seek(0)
                dialect = csv.Sniffer().sniff(sample, delimiters=';,')

                # Read a few lines to analyze structure
                reader = csv.reader(infile, dialect=dialect)
                headers = next(reader)

                # Debug: Print actual headers from CSV
                print(f"DEBUG - Raw headers from CSV: {headers}")

                # Check for empty columns in the headers
                for i, header in enumerate(headers):
                    if not header.strip():
                        print(f"DEBUG - Empty header found at position {i}")

            # Now process the file with the correct headers
            date_rows_map = defaultdict(list)

            with open(input_file, 'r', newline='', encoding='utf-8') as infile:
                # Skip the header row that we already read
                infile.readline()

                # Create a list of headers without any empty ones
                clean_headers = [h for h in headers if h.strip()]
                print(f"DEBUG - Clean headers: {clean_headers}")

                # Add our own column
                clean_headers.append('Info')

                # Process each row manually to ensure correct structure
                reader = csv.reader(infile, dialect=dialect)
                for row in reader:
                    # Create a dictionary with only valid headers
                    row_dict = {}
                    for i, header in enumerate(headers):
                        if i < len(row) and header.strip():  # Only add non-empty headers
                            row_dict[header] = row[i]

                    # Apply rules to determine the 'Info' value
                    info_value = ""
                    for rule in rules:
                        column = rule["column"]
                        substring = rule["substring"]
                        value = rule["info_column_value"]

                        if column in row_dict and substring in row_dict[column]:
                            info_value = value
                            break

                    # Add the 'Info' column to the row
                    row_dict['Info'] = info_value

                    # Extract date and group rows by month
                    if 'Bezahldatum' in row_dict and row_dict['Bezahldatum']:
                        try:
                            # Parse different date formats (DD.MM.YYYY or YYYY-MM-DD)
                            if '.' in row_dict['Bezahldatum']:
                                date = datetime.datetime.strptime(row_dict['Bezahldatum'], '%d.%m.%Y')
                            else:
                                date = datetime.datetime.strptime(row_dict['Bezahldatum'], '%Y-%m-%d')

                            month_key = date.strftime('%Y-%m')
                            date_rows_map[month_key].append(row_dict)
                        except ValueError:
                            print(f"Warning: Could not parse date '{row_dict['Bezahldatum']}' in file {input_file}")
                            date_rows_map['unknown'].append(row_dict)
                    else:
                        date_rows_map['unknown'].append(row_dict)

            # Write rows to separate Excel files based on months
            files_created = []
            for month_key, rows in date_rows_map.items():
                if month_key == 'unknown':
                    output_file = os.path.join(directory, "unknown-date-Paypal.xlsx")
                else:
                    output_file = os.path.join(directory, f"{month_key}-Paypal.xlsx")

                # Create a new workbook or load existing one
                if os.path.exists(output_file):
                    wb = openpyxl.load_workbook(output_file)
                    sheet = wb.active
                    # Clear existing content to avoid duplication
                    for row in sheet.iter_rows(min_row=1):
                        for cell in row:
                            cell.value = None
                    start_row = 1
                else:
                    wb = openpyxl.Workbook()
                    sheet = wb.active
                    sheet.title = "PayPal Transactions"
                    start_row = 1

                # Find the "Betrag" column index
                betrag_col_idx = None
                info_col_idx = None

                # Add header
                for col_idx, header in enumerate(clean_headers, 1):
                    cell = sheet.cell(row=1, column=col_idx, value=header)
                    # Style the header
                    cell.font = Font(bold=True)

                    # Remember the index of the "Betrag" column
                    if header == "Betrag":
                        betrag_col_idx = col_idx
                    elif header == "Info":
                        info_col_idx = col_idx

                # Add data rows
                for row_idx, row_data in enumerate(rows, start=2):
                    for col_idx, field in enumerate(clean_headers, 1):
                        # Check if the field exists in the row data
                        value = row_data.get(field, "")
                        cell = sheet.cell(row=row_idx, column=col_idx, value=value)

                        # Convert Betrag to float if possible (handling different formats)
                        if field == "Betrag" and value:
                            try:
                                # Handle European number format (e.g., "4.000,00" → 4000.00)
                                if isinstance(value, str):
                                    # First, remove any currency symbols and spaces
                                    value = re.sub(r'[^\d.,-]', '', value)

                                    # If the value has both dot and comma, assume European format (4.000,00)
                                    if '.' in value and ',' in value:
                                        # Remove the thousands separator dots
                                        value = value.replace('.', '')
                                        # Then replace comma with dot for decimal
                                        value = value.replace(',', '.')
                                    # If only comma is present, assume it's the decimal separator
                                    elif ',' in value:
                                        value = value.replace(',', '.')

                                    cell.value = float(value)
                                    cell.number_format = '#,##0.00 €'
                            except ValueError:
                                print(f"Warning: Could not convert '{value}' to float in {output_file}")

                # Calculate summary totals
                last_row = len(rows) + 1
                summary_row = last_row + 2  # Leave one row blank before summary

                # Define borders for summary section
                border = Border(
                    top=Side(style='thin'),
                    left=Side(style='thin'),
                    right=Side(style='thin'),
                    bottom=Side(style='thin')
                )

                # Add summary header
                sheet.cell(row=summary_row, column=1, value="Summary").font = Font(bold=True)
                sheet.cell(row=summary_row, column=1).alignment = Alignment(horizontal='left')

                current_summary_row = summary_row + 1
                total_cell_reference = None  # To keep track of the total cell for formula

                # Add total of Betrag
                if betrag_col_idx:
                    sheet.cell(row=current_summary_row, column=1, value="'Betrag' gesamt:").font = Font(bold=True)
                    sheet.cell(row=current_summary_row, column=1).border = border

                    # Calculate total with formula
                    sum_formula = f"=SUM({openpyxl.utils.get_column_letter(betrag_col_idx)}2:{openpyxl.utils.get_column_letter(betrag_col_idx)}{last_row})"
                    total_cell = sheet.cell(row=current_summary_row, column=2, value=sum_formula)
                    total_cell.number_format = '#,##0.00 €'
                    total_cell.font = Font(bold=True)
                    total_cell.border = border

                    # Store the cell reference for later use in the difference formula
                    total_cell_reference = f"{openpyxl.utils.get_column_letter(2)}{current_summary_row}"

                    current_summary_row += 1

                # Get all unique info values that were actually used
                category_cell_references = []  # To keep track of category cells for formula

                if info_col_idx:
                    used_categories = set()
                    has_empty_category = False

                    for row in rows:
                        info_value = row.get('Info', '')
                        if info_value:
                            used_categories.add(info_value)
                        else:
                            has_empty_category = True

                    # Combine used categories with always_show categories
                    all_categories_to_show = used_categories.union(set(always_show_categories))

                    # Add totals for each category that was actually used or should always be shown
                    for category in sorted(all_categories_to_show):
                        sheet.cell(row=current_summary_row, column=1, value=f"Info '{category}':").font = Font(bold=True)
                        sheet.cell(row=current_summary_row, column=1).border = border

                        # Use a SUMIF formula to sum only entries with matching Info value
                        sum_formula = f'=SUMIF({openpyxl.utils.get_column_letter(info_col_idx)}2:{openpyxl.utils.get_column_letter(info_col_idx)}{last_row},"{category}",{openpyxl.utils.get_column_letter(betrag_col_idx)}2:{openpyxl.utils.get_column_letter(betrag_col_idx)}{last_row})'
                        category_cell = sheet.cell(row=current_summary_row, column=2, value=sum_formula)
                        category_cell.number_format = '#,##0.00 €'
                        category_cell.font = Font(bold=True)
                        category_cell.border = border

                        # Store the cell reference for later use in the difference formula
                        category_cell_references.append(f"{openpyxl.utils.get_column_letter(2)}{current_summary_row}")

                        current_summary_row += 1

                    # Add a row for entries without category (empty Info field)
                    if has_empty_category:
                        sheet.cell(row=current_summary_row, column=1, value="Info nicht ausgefüllt:").font = Font(bold=True)
                        sheet.cell(row=current_summary_row, column=1).border = border

                        # Use a SUMIF formula with empty string criteria
                        sum_formula = f'=SUMIF({openpyxl.utils.get_column_letter(info_col_idx)}2:{openpyxl.utils.get_column_letter(info_col_idx)}{last_row},"",{openpyxl.utils.get_column_letter(betrag_col_idx)}2:{openpyxl.utils.get_column_letter(betrag_col_idx)}{last_row})'
                        category_cell = sheet.cell(row=current_summary_row, column=2, value=sum_formula)
                        category_cell.number_format = '#,##0.00 €'
                        category_cell.font = Font(bold=True)
                        category_cell.border = border

                        # Store the cell reference for later use in the difference formula
                        category_cell_references.append(f"{openpyxl.utils.get_column_letter(2)}{current_summary_row}")

                        current_summary_row += 1

                # Add a row for the difference (should be zero if all entries have categories)
                if total_cell_reference and category_cell_references:
                    # Add a blank row for visual separation
                    current_summary_row += 1

                    # Create the "Differenz" row with normal (non-bold) text and no border
                    label_cell = sheet.cell(row=current_summary_row, column=1, value="Gegenprüfung muss immer 0 sein:")
                    label_cell.font = Font(bold=False)
                    # Don't set border to None, just don't apply any border

                    # Create a formula that subtracts all category sums from the total
                    diff_formula = f"={total_cell_reference}-" + "-".join(category_cell_references)
                    diff_cell = sheet.cell(row=current_summary_row, column=2, value=diff_formula)
                    # Only set the number format, but no other formatting
                    diff_cell.number_format = '#,##0.00 €'

                    current_summary_row += 1

                # Remove any formatting from empty cells beyond the last row with data
                max_row_with_data = current_summary_row - 1  # This is the last row we wrote to
                if sheet.max_row > max_row_with_data:
                    for row in range(max_row_with_data + 1, sheet.max_row + 1):
                        for col in range(1, sheet.max_column + 1):
                            cell = sheet.cell(row=row, column=col)
                            if cell.value is None:
                                cell.border = None
                                cell.fill = None
                                cell.font = Font()
                                cell.alignment = Alignment()

                # Auto-adjust column widths
                for column in sheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        if cell.value:
                            cell_length = len(str(cell.value))
                            if cell_length > max_length:
                                max_length = cell_length
                    adjusted_width = (max_length + 2) * 1.2
                    sheet.column_dimensions[column_letter].width = adjusted_width

                wb.save(output_file)

                if output_file not in files_created:
                    files_created.append(output_file)

            print(f"Processed {input_file}. Created/updated Excel files: {', '.join(files_created)}")

            # Delete the CSV file after successful processing
            if delete_csv:
                os.remove(input_file)
                print(f"Deleted {input_file} after successful processing")

        except Exception as e:
            print(f"Error processing {input_file}: {str(e)}")
            import traceback
            print(traceback.format_exc())
            print(f"The file {input_file} was NOT deleted due to processing errors")

    print("Processing complete!")


def main():

    parser = argparse.ArgumentParser(description='Process CSV files and convert to Excel with Info column.')
    parser.add_argument('--delete-csv', action='store_true', 
                       help='Delete CSV files after successful processing (default: False)')
    parser.add_argument('--directory', type=str, default=None,
                       help='Directory to process CSV files from (default: current directory)')
    
    args = parser.parse_args()
    
    process_csv_files(delete_csv=args.delete_csv, directory=args.directory)


# Run the script
if __name__ == "__main__":
    main()