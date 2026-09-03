"""
excel_parser.py — Intelligently inspects spreadsheet cells and extracts electrical product requirements and business info.
"""

import os
import re
import csv


def extract_spreadsheet_text(file_path: str) -> str:
    if not os.path.exists(file_path):
        return ""

    ext = os.path.splitext(file_path)[1].lower()
    extracted_lines = []

    # Handle CSV
    if ext == ".csv":
        try:
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.reader(f)
                for row in reader:
                    line = " | ".join(c.strip() for c in row if c.strip())
                    if line:
                        extracted_lines.append(line)
            return "\n".join(extracted_lines[:50])
        except Exception as e:
            print(f"[CSV PARSER ERROR] {e}")
            return ""

    # Handle XLSX / XLS
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb.active

        # Scan for header row
        header_row = []
        for row in ws.iter_rows(values_only=True):
            if not any(row):
                continue
            cells = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
            if not cells:
                continue

            # Check if this row looks like electrical products or metadata
            row_text = " | ".join(cells)
            if any(term in row_text.lower() for term in ("item", "product", "qty", "quantity", "desc", "spec", "rate", "watt", "mm", "volt")):
                extracted_lines.append(row_text)
            elif any(c.isdigit() for c in row_text):
                extracted_lines.append(row_text)

        wb.close()
        return "\n".join(extracted_lines[:40])
    except Exception as e:
        print(f"[EXCEL PARSER ERROR] {e}")
        return ""
