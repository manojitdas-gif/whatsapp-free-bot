"""
excel_logger.py — Clean 10-Column Customer Lead Logger.

COLUMNS (raw data only — no decorative dashes, no bot messages):
  1.  S.No.
  2.  First Contact Date (IST)
  3.  Last Contact Date (IST)
  4.  Contact Person Name
  5.  WhatsApp Number
  6.  Email ID
  7.  Company / Business Name
  8.  GST Number
  9.  Complete Address
  10. Requirements Details

RULES:
  - A customer row is created once (on first message).
  - Each subsequent message ONLY fills in NEW data to empty cells.
  - Empty cell = blank (no dashes, no placeholders).
  - Requirements are accumulated across messages (appended, not overwritten).
  - Saves to Desktop: WhatsApp_Conversations.xlsx & WhatsApp_Leads_SHARED.xlsx
  - Also saves live CSV: WhatsApp_Leads_Live.csv
"""

import os
import sys
import re
import csv
import json
import time
from datetime import datetime, timezone, timedelta
from threading import Lock

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from config import EXCEL_FILE_PATH, BACKUP_EXCEL_PATH, SHARED_EXCEL_PATH
from document_analyzer import parse_product_details

IST = timezone(timedelta(hours=5, minutes=30))
_excel_lock = Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(BASE_DIR, "data", "pending_lead_queue.json")
CSV_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "WhatsApp_Leads_Live.csv")

# Header style: Deep green
HEADER_FILL = PatternFill("solid", fgColor="1B5E20")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
DATA_FONT   = Font(name="Calibri", size=10)

THIN_BORDER = Border(
    left  =Side(style="thin", color="CCCCCC"),
    right =Side(style="thin", color="CCCCCC"),
    top   =Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)

HEADERS = [
    "S.No.",
    "First Contact (IST)",
    "Last Contact (IST)",
    "Contact Name",
    "WhatsApp Number",
    "Email ID",
    "Company / Business Name",
    "GST Number",
    "Complete Address",
    "Requirements Details",
]
# Column widths in characters
WIDTHS = [7, 20, 20, 22, 18, 28, 30, 22, 40, 60]


# ──────────────────────────────────────────────────────────────────────────────
# HELPER: Phone display format
# ──────────────────────────────────────────────────────────────────────────────

def format_phone_display(raw_phone: str) -> str:
    p = re.sub(r'[^\d]', '', str(raw_phone or ""))
    if p.startswith("91") and len(p) == 12:
        return f"+91 {p[2:7]} {p[7:]}"
    if len(p) == 10:
        return f"+91 {p[:5]} {p[5:]}"
    return f"+{p}" if p else "Unknown"


# ──────────────────────────────────────────────────────────────────────────────
# ENTITY EXTRACTION — Email, GST, Address, Company, Contact Name
# ──────────────────────────────────────────────────────────────────────────────

def extract_lead_entities(text: str, profile_name: str = "", is_business_step: bool = False) -> dict:
    """
    Extract structured entities from customer message text.
    Returns only fields that are actually found — no placeholder values.
    """
    text = str(text or "").strip()

    # Email
    email_m = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b', text)
    email = email_m.group(0).lower() if email_m else ""

    # GST Number (Indian format: 15 chars)
    gst_m = re.search(r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}\b', text, re.IGNORECASE)
    gst = gst_m.group(0).upper() if gst_m else ""

    # Contact Person Name — explicit keyword patterns first
    contact_name = ""
    name_m = re.search(
        r'(?:contact\s*person|contact|person|name)\s*[:\-–]?\s*([A-Za-z](?:[A-Za-z\s]{1,28}[A-Za-z]))',
        text, re.IGNORECASE
    )
    if name_m:
        candidate = name_m.group(1).strip()
        # Reject if it looks like a business phrase
        if not re.search(r'\b(company|enterprise|pvt|ltd|gst|road|street|require|need|want)\b', candidate, re.IGNORECASE):
            contact_name = candidate.title()
    if not contact_name and profile_name and profile_name.lower() not in ("customer", "unknown"):
        contact_name = profile_name.strip().title()

    # Company / Business Name
    company = ""
    comp_m = re.search(
        r'(?:company|business|firm|shop|org|enterprise)\s*(?:name)?\s*[:\-–]?\s*([^\n,]{3,50})',
        text, re.IGNORECASE
    )
    if comp_m:
        company = comp_m.group(1).strip()
    else:
        # Heuristic: line that contains a business-type keyword
        biz_rx = re.compile(
            r'\b(enterprise[s]?|traders?|trading|pvt\.?\s*ltd|ltd|industries|packaging|'
            r'corporation|solutions|works|manufacturing|group|agency|agencies)\b',
            re.IGNORECASE
        )
        for line in text.splitlines():
            line = line.strip()
            if biz_rx.search(line) and not re.search(r'\b(need|want|send|quote|price|rate|req)\b', line, re.IGNORECASE):
                if 3 <= len(line) <= 60:
                    company = line
                    break

    # Address — collect lines that look like address fragments
    addr_lines = []
    ADDR_KW = re.compile(
        r'\b(road|rd|street|st\b|lane|gali|bazar|bazaar|nagar|colony|block|sector|'
        r'floor|plot|near|opp|opposite|behind|dist|district|pin|'
        r'kolkata|mumbai|delhi|chennai|bangalore|hyderabad|pune|ahmedabad|'
        r'surat|jaipur|lucknow|howrah|bengal|maharashtra|gujarat|pradesh)\b',
        re.IGNORECASE
    )
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if gst and gst.lower() in line.lower():
            continue
        if email and email in line.lower():
            continue
        if company and line.lower() == company.lower():
            continue
        if ADDR_KW.search(line) or re.search(r'\b\d{6}\b', line):
            cleaned = re.sub(r'^(?:address|location|addr|office)\s*[:\-–]?\s*', '', line, flags=re.IGNORECASE).strip()
            if cleaned and cleaned not in addr_lines:
                addr_lines.append(cleaned)
    address = ", ".join(addr_lines)

    # For business step: if company still empty, try first substantive non-chatter line
    if is_business_step and not company:
        CHATTER = {"ok","okay","thanks","thank you","hi","hello","hey","yes","no",
                   "fine","good","sure","k","alright","done","noted"}
        for line in text.splitlines():
            line_clean = line.strip()
            if not line_clean or line_clean.lower() in CHATTER:
                continue
            if gst_m and gst in line_clean:
                continue
            if email and email in line_clean.lower():
                continue
            if re.search(r'\b(pin|road|street|gst|www|http|call|reply|send)\b', line_clean, re.IGNORECASE):
                continue
            if 3 <= len(line_clean) <= 60:
                company = line_clean
                break

    return {
        "email":   email,
        "company": company,
        "gst":     gst,
        "address": address,
        "contact": contact_name,
    }


# ──────────────────────────────────────────────────────────────────────────────
# WORKBOOK HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _get_or_create_workbook(file_path: str) -> openpyxl.Workbook:
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    if os.path.exists(file_path):
        try:
            return openpyxl.load_workbook(file_path)
        except Exception:
            pass

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Customer Leads"
    ws.freeze_panes = "A2"

    for col_idx, (header, width) in enumerate(zip(HEADERS, WIDTHS), start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[1].height = 30
    return wb


def _apply_lead_to_workbook(file_path: str, lead: dict) -> bool:
    """Write or update a customer lead row. Only fills columns that have new data."""
    wb = _get_or_create_workbook(file_path)
    ws = wb["Customer Leads"] if "Customer Leads" in wb.sheetnames else wb.active

    phone        = lead.get("phone", "")
    timestamp    = lead.get("timestamp", "")
    contact_name = lead.get("contact_name", "")
    email        = lead.get("email", "")
    company      = lead.get("company", "")
    gst          = lead.get("gst", "")
    address      = lead.get("address", "")
    requirements = lead.get("requirements", "")

    align_c = Alignment(horizontal="center", vertical="center")
    align_l = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # Find existing row for this phone number
    match_row = None
    first_empty = None
    lead_count = 0

    for r in range(2, ws.max_row + 2):
        cell_val = ws.cell(row=r, column=5).value
        if cell_val:
            lead_count += 1
            if str(cell_val).strip() == str(phone).strip():
                match_row = r
                break
        elif first_empty is None:
            first_empty = r

    if match_row:
        # Update existing row: only overwrite blank cells
        ws.cell(row=match_row, column=3, value=timestamp)  # always update last contact

        def _fill(col, new_val):
            if new_val:
                existing = ws.cell(row=match_row, column=col).value
                if not existing or str(existing).strip() in ("", "—", "-"):
                    ws.cell(row=match_row, column=col, value=new_val)

        _fill(4, contact_name)
        _fill(6, email)
        _fill(7, company)
        _fill(8, gst)
        _fill(9, address)

        # Requirements: accumulate (append new content)
        if requirements:
            existing_req = str(ws.cell(row=match_row, column=10).value or "").strip()
            if not existing_req or existing_req in ("—", "-"):
                ws.cell(row=match_row, column=10, value=requirements)
            else:
                # Only append if genuinely new information
                if requirements.lower().strip() not in existing_req.lower():
                    ws.cell(row=match_row, column=10, value=existing_req + "\n" + requirements)

    else:
        # New customer row
        new_row = first_empty if first_empty else (ws.max_row + 1)
        row_values = [
            lead_count + 1,   # S.No.
            timestamp,        # First Contact
            timestamp,        # Last Contact
            contact_name,     # Contact Name (blank if unknown)
            phone,            # WhatsApp Number
            email,            # Email
            company,          # Company
            gst,              # GST
            address,          # Address
            requirements,     # Requirements
        ]
        for col_idx, val in enumerate(row_values, start=1):
            cell = ws.cell(row=new_row, column=col_idx, value=val if val else None)
            cell.font = DATA_FONT
            cell.border = THIN_BORDER
            cell.alignment = align_c if col_idx in (1, 2, 3, 5) else align_l

        ws.row_dimensions[new_row].height = 25

    wb.save(file_path)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# QUEUE (for when Excel file is open/locked)
# ──────────────────────────────────────────────────────────────────────────────

def _load_queue() -> list:
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_queue(queue: list) -> None:
    os.makedirs(os.path.dirname(QUEUE_FILE) or ".", exist_ok=True)
    try:
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def flush_pending_excel_queue():
    """Try to write any previously queued leads (when file was locked)."""
    with _excel_lock:
        queue = _load_queue()
        if not queue:
            return
        unflushed = []
        flushed = 0
        for item in queue:
            dest, lead = (item[0], item[1]) if isinstance(item, (list, tuple)) else (EXCEL_FILE_PATH, item)
            try:
                _apply_lead_to_workbook(dest, lead)
                flushed += 1
            except PermissionError:
                unflushed.append((dest, lead))
            except Exception as e:
                print(f"[EXCEL QUEUE ERROR] {e}")
        if flushed:
            print(f"[EXCEL SYNC] Flushed {flushed} queued lead(s) to Desktop files.")
        _save_queue(unflushed)


# ──────────────────────────────────────────────────────────────────────────────
# CSV SYNC
# ──────────────────────────────────────────────────────────────────────────────

def _update_live_csv(lead: dict) -> None:
    try:
        rows = []
        if os.path.exists(CSV_PATH):
            with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        if not rows:
            rows = [HEADERS]

        phone = lead.get("phone", "")
        match_idx = None
        for i in range(1, len(rows)):
            if len(rows[i]) > 4 and rows[i][4] == phone:
                match_idx = i
                break

        def _safe(rows, idx, col, val):
            while len(rows[idx]) <= col:
                rows[idx].append("")
            if val and not rows[idx][col]:
                rows[idx][col] = val

        if match_idx is not None:
            rows[match_idx][2] = lead.get("timestamp", "")  # Last contact
            _safe(rows, match_idx, 3, lead.get("contact_name"))
            _safe(rows, match_idx, 5, lead.get("email"))
            _safe(rows, match_idx, 6, lead.get("company"))
            _safe(rows, match_idx, 7, lead.get("gst"))
            _safe(rows, match_idx, 8, lead.get("address"))
            if lead.get("requirements"):
                prev = rows[match_idx][9] if len(rows[match_idx]) > 9 else ""
                if not prev:
                    rows[match_idx][9] = lead["requirements"]
                elif lead["requirements"].lower() not in prev.lower():
                    rows[match_idx][9] = prev + " | " + lead["requirements"]
        else:
            rows.append([
                len(rows),
                lead.get("timestamp", ""),
                lead.get("timestamp", ""),
                lead.get("contact_name") or "",
                phone,
                lead.get("email") or "",
                lead.get("company") or "",
                lead.get("gst") or "",
                lead.get("address") or "",
                lead.get("requirements") or "",
            ])

        with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
    except Exception as e:
        print(f"[CSV ERROR] {e}")


# ──────────────────────────────────────────────────────────────────────────────
# PRIMARY PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def log_customer_lead(
    sender_phone: str,
    sender_name: str,
    message_text: str = "",
    analyzed_products: str = "",
    is_requirement_step: bool = False,
    is_business_step: bool = False,
) -> None:
    """
    Log customer lead to all Excel/CSV files.
    Called once per real incoming customer message (not on every loop tick).
    """
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    formatted_phone = format_phone_display(sender_phone)

    extracted = extract_lead_entities(message_text, sender_name, is_business_step=is_business_step)

    # Requirements: use OCR result first, then parse from text
    requirements = ""
    if analyzed_products and "No text" not in analyzed_products:
        requirements = analyzed_products
    elif message_text and not message_text.startswith("["):
        requirements = parse_product_details(message_text)

    # For business step: requirements not relevant (it's about biz details), don't overwrite
    if is_business_step:
        requirements = ""

    lead = {
        "timestamp":    now_ist,
        "contact_name": extracted["contact"],
        "phone":        formatted_phone,
        "email":        extracted["email"],
        "company":      extracted["company"],
        "gst":          extracted["gst"],
        "address":      extracted["address"],
        "requirements": requirements,
    }

    # Cloud sync
    try:
        from cloud_sync import push_lead_to_cloud
        push_lead_to_cloud({
            "first_contact": now_ist, "last_contact": now_ist,
            "name": extracted["contact"], "phone": formatted_phone,
            "email": extracted["email"], "company": extracted["company"],
            "gst": extracted["gst"], "address": extracted["address"],
            "requirements": requirements,
        })
    except Exception:
        pass

    with _excel_lock:
        _update_live_csv(lead)

        # Backup copy
        try:
            _apply_lead_to_workbook(BACKUP_EXCEL_PATH, lead)
        except Exception as e:
            print(f"[EXCEL BACKUP ERROR] {e}")

        # Desktop copies
        for dest in [EXCEL_FILE_PATH, SHARED_EXCEL_PATH]:
            try:
                _apply_lead_to_workbook(dest, lead)
                print(f"[EXCEL] ✅ {os.path.basename(dest)}: {extracted['contact'] or sender_name} ({formatted_phone})")
            except PermissionError:
                queue = _load_queue()
                queue.append((dest, lead))
                _save_queue(queue)
                print(f"[EXCEL] ⚠ {os.path.basename(dest)} is open — queued for next sync.")
            except Exception as e:
                queue = _load_queue()
                queue.append((dest, lead))
                _save_queue(queue)
                print(f"[EXCEL QUEUE] {e}")
