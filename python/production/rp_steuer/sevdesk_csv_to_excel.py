import pandas as pd
import os
import numpy as np
import glob
import sys
import argparse
from datetime import datetime
from collections import Counter

from importlib.metadata import version



def convert_csv_to_excel(csv_file_path, excel_output_path=None):
    print(f"Reading CSV from: {csv_file_path}")

    try:
        # Read the CSV file with German locale settings
        df = pd.read_csv(
            csv_file_path,
            sep=';',
            decimal=',',
            encoding='utf-8',
            quotechar='"'
        )
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return None

    # Clean up data - drop the empty column at the end if it exists
    df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

    # Convert date columns to datetime format
    date_columns = ['Rechnungs-Datum', 'Fällig am', 'Bezahlt am']
    for col in date_columns:
        if col in df.columns:
            # Convert to datetime and keep it as datetime (not date) for Excel compatibility
            df[col] = pd.to_datetime(df[col], format='%d.%m.%Y', errors='coerce')

    # Determine the most common year and month from Rechnungs-Datum
    if 'Rechnungs-Datum' in df.columns and not df.empty and not df['Rechnungs-Datum'].isna().all():
        # Extract year-month from each date
        year_months = [f"{date.year}-{date.month:02d}" for date in df['Rechnungs-Datum'].dropna()]
        # Find the most common year-month
        if year_months:
            most_common_year_month = Counter(year_months).most_common(1)[0][0]
            # If no output path specified, create one based on the year-month
            if excel_output_path is None:
                base_dir = os.path.dirname(csv_file_path)
                excel_output_path = os.path.join(base_dir, f"{most_common_year_month}-Rechnungen.xlsx")
        else:
            # If no valid dates, use the original file name
            if excel_output_path is None:
                base_name = os.path.splitext(csv_file_path)[0]
                excel_output_path = f"{base_name}.xlsx"
    else:
        # If no date column or all dates are NaN, use the original file name
        if excel_output_path is None:
            base_name = os.path.splitext(csv_file_path)[0]
            excel_output_path = f"{base_name}.xlsx"

    # Check if the Excel file already exists
    if os.path.exists(excel_output_path):
        print(f"Excel file already exists: {excel_output_path}")
        return None

    # Convert monetary columns to numeric
    money_columns = ['Gesamtbetrag-Netto', 'Gesamtbetrag-Brutto', 'offener Betrag']
    for col in money_columns:
        if col not in df.columns:
            continue

        # Check if the column is already numeric
        if pd.api.types.is_numeric_dtype(df[col]):
            continue

        # Convert string with German number format to numeric
        if pd.api.types.is_string_dtype(df[col]):
            df[col] = pd.to_numeric(df[col].str.replace(',', '.'), errors='coerce')
        else:
            # Try direct conversion
            df[col] = pd.to_numeric(df[col], errors='coerce')

    print(f"Creating Excel file: {excel_output_path}")

    try:
        # Create a Excel writer object
        with pd.ExcelWriter(excel_output_path, engine='xlsxwriter') as writer:
            # Get the workbook object
            workbook = writer.book

            # Create formats
            money_format = workbook.add_format({'num_format': '#,##0.00 €'})
            # German date format (TT.MM.JJJJ)
            date_format = workbook.add_format({'num_format': 'dd.mm.yyyy'})

            # Create bold formats for sum row
            bold_format = workbook.add_format({'bold': True})
            bold_money_format = workbook.add_format({'bold': True, 'num_format': '#,##0.00 €'})

            # Sheet 1: All data with sums
            df.to_excel(writer, sheet_name='Alle Rechnungen', index=False)

            # Get the worksheet object
            worksheet = writer.sheets['Alle Rechnungen']

            # Calculate and store column widths
            column_widths = {}
            for idx, col in enumerate(df.columns):
                # Convert dates to strings with specific format for width calculation
                if col in date_columns:
                    # Use a fixed width for date columns
                    column_widths[idx] = 12  # dd.mm.yyyy format takes about 10 chars + buffer
                else:
                    # Find the maximum length in the column
                    max_len = max(
                        # Column name length
                        len(str(col)),
                        # Maximum data length in the column
                        df[col].astype(str).map(len).max() if not df.empty else 0
                    )
                    # Add a buffer for better appearance
                    adjusted_width = max_len + 2
                    # Store the column width (limit to reasonable size)
                    column_widths[idx] = min(adjusted_width, 40)

                # Set the basic column width
                worksheet.set_column(idx, idx, column_widths[idx])

            # Add sum row at the bottom
            row_count = len(df) + 1  # +1 for header
            for col_idx, col_name in enumerate(df.columns):
                if col_name in money_columns:
                    col_letter = chr(65 + col_idx)  # A, B, C, etc.
                    formula = f'=SUM({col_letter}2:{col_letter}{row_count})'
                    # Use bold money format for sum cells
                    worksheet.write_formula(row_count, col_idx, formula, bold_money_format)
                else:
                    # Make all cells in the sum row bold (even if they don't have a sum)
                    worksheet.write(row_count, col_idx, None, bold_format)

            # Add "Summe" label with bold formatting
            worksheet.write(row_count, 0, 'Summe', bold_format)

            # Apply formats to columns and convert cell formats
            for col_idx, col_name in enumerate(df.columns):
                if col_name in money_columns:
                    # Use the width we calculated earlier, but ensure it's at least 18 for money columns
                    width = max(column_widths[col_idx], 18)
                    worksheet.set_column(col_idx, col_idx, width, money_format)
                elif col_name in date_columns:
                    worksheet.set_column(col_idx, col_idx, column_widths[col_idx], date_format)

                    # Manually format each date cell to ensure correct date format
                    for row_idx in range(len(df)):
                        if not pd.isna(df.iloc[row_idx][col_name]):
                            date_val = df.iloc[row_idx][col_name].to_pydatetime()
                            worksheet.write_datetime(row_idx + 1, col_idx, date_val, date_format)  # +1 for header row

            # Sheet 2: Late payments
            # Identify payments made in a different month than invoice date or not paid at all
            def is_late_payment(row):
                # Check if payment date is missing (not paid)
                if pd.isna(row['Bezahlt am']):
                    return True

                # Check if payment date is in a different month or year than invoice date
                invoice_date = row['Rechnungs-Datum']
                payment_date = row['Bezahlt am']

                if invoice_date is None or payment_date is None:
                    return True

                # Extract month and year for comparison
                invoice_month, invoice_year = invoice_date.month, invoice_date.year
                payment_month, payment_year = payment_date.month, payment_date.year

                if (payment_month != invoice_month or payment_year != invoice_year):
                    return True

                return False

            late_payments = df.apply(is_late_payment, axis=1)
            late_df = df[late_payments]

            if not late_df.empty:
                late_df.to_excel(writer, sheet_name='Verspätete Zahlungen', index=False)

                # Format the late payments sheet
                late_worksheet = writer.sheets['Verspätete Zahlungen']

                # Calculate and store column widths for the late payments sheet
                late_column_widths = {}
                for idx, col in enumerate(late_df.columns):
                    if col in date_columns:
                        # Use a fixed width for date columns
                        late_column_widths[idx] = 12  # dd.mm.yyyy format takes about 10 chars + buffer
                    else:
                        # Find the maximum length in the column
                        max_len = max(
                            # Column name length
                            len(str(col)),
                            # Maximum data length in the column
                            late_df[col].astype(str).map(len).max()
                        )
                        # Add a buffer for better appearance
                        adjusted_width = max_len + 2
                        # Store the column width (limit to reasonable size)
                        late_column_widths[idx] = min(adjusted_width, 40)

                    # Set the basic column width
                    late_worksheet.set_column(idx, idx, late_column_widths[idx])

                # Add sum row at the bottom of second sheet
                late_row_count = len(late_df) + 1  # +1 for header
                for col_idx, col_name in enumerate(late_df.columns):
                    if col_name in money_columns:
                        col_letter = chr(65 + col_idx)  # A, B, C, etc.
                        formula = f'=SUM({col_letter}2:{col_letter}{late_row_count})'
                        # Use bold money format for sum cells
                        late_worksheet.write_formula(late_row_count, col_idx, formula, bold_money_format)
                    else:
                        # Make all cells in the sum row bold (even if they don't have a sum)
                        late_worksheet.write(late_row_count, col_idx, None, bold_format)

                # Add "Summe" label with bold formatting
                late_worksheet.write(late_row_count, 0, 'Summe', bold_format)

                # Apply formats to columns and manually format date cells
                for col_idx, col_name in enumerate(late_df.columns):
                    if col_name in money_columns:
                        # Use the width we calculated earlier, but ensure it's at least 18 for money columns
                        width = max(late_column_widths[col_idx], 18)
                        late_worksheet.set_column(col_idx, col_idx, width, money_format)
                    elif col_name in date_columns:
                        late_worksheet.set_column(col_idx, col_idx, late_column_widths[col_idx], date_format)

                        # Manually format each date cell to ensure correct date format
                        for row_idx in range(len(late_df)):
                            if not pd.isna(late_df.iloc[row_idx][col_name]):
                                date_val = late_df.iloc[row_idx][col_name].to_pydatetime()
                                late_worksheet.write_datetime(row_idx + 1, col_idx, date_val, date_format)  # +1 for header row
            else:
                # Create an empty sheet if there are no late payments
                workbook.add_worksheet('Verspätete Zahlungen')
                print("No late payments found, creating empty second sheet.")

        print(f"Excel file created successfully: {excel_output_path}")
        return excel_output_path

    except Exception as e:
        print(f"Error creating Excel file: {e}")
        # If there was an error and a partial file was created, remove it
        if os.path.exists(excel_output_path):
            try:
                os.remove(excel_output_path)
                print(f"Removed incomplete Excel file: {excel_output_path}")
            except:
                print(f"Failed to remove incomplete Excel file: {excel_output_path}")
        return None


def find_csv_files(directory):
    """Find all CSV files in the given directory."""
    # Expand the directory path if it contains ~
    directory = os.path.expanduser(directory)

    # Check if directory exists
    if not os.path.exists(directory):
        print(f"Directory {directory} does not exist.")
        return []

    # Find all CSV files
    pattern = os.path.join(directory, "*.csv")
    csv_files = glob.glob(pattern)

    return csv_files


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Convert CSV files to Excel format.')
    # Use current working directory as default
    parser.add_argument('--directory', default=os.getcwd(),
                        help='Directory to search for CSV files (default: current directory)')
    return parser.parse_args()


if __name__ == "__main__":
    print(f"rp-steuer version: {version('rp-steuer')}")

    # Parse command line arguments
    args = parse_args()
    directory = args.directory

    print(f"Processing CSV files in directory: {directory}")

    # Find all CSV files
    csv_files = find_csv_files(directory)

    if not csv_files:
        print(f"No CSV files found in {directory} directory.")
        sys.exit(0)

    print(f"Found {len(csv_files)} CSV files.")

    # Process each file
    for csv_file in csv_files:
        print(f"Processing file: {csv_file}")

        # Convert the file (the function now determines the Excel file name)
        output_file = convert_csv_to_excel(csv_file)

        if output_file:
            # print(f"Successfully created Excel file: {output_file}")
            # Delete the CSV file after successful conversion
            try:
                os.remove(csv_file)
                print(f"Deleted original CSV file: {csv_file}")
            except Exception as e:
                print(f"Failed to delete CSV file {csv_file}: {e}")
        else:
            print(f"Failed to create Excel file for: {csv_file}")

    print("Script execution completed.")

    # If running as executable, wait for user input before closing
    # if getattr(sys, 'frozen', False):
    #     input("\nPress Enter to exit...")