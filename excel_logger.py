"""
excel_logger.py — Real-time Customer Lead Logger for WhatsApp (10 Columns).

EXACT 10 COLUMNS:
  1. S.No.
  2. First Contact Date (IST)
  3. Last Contact Date (IST)
  4. Contact Person Name (Who is messaging me)
  5. WhatsApp Number
  6. Email ID (Dedicated email column)
  7. Company / Business Name
  8. GST Number
  9. Complete Address (Full address only, without truncation)
  10. Customer Requirements Details (Pure product details only)

FEATURES:
  - Real-time instant logging: Extracts pure product details, email, full address, company name, GST.
  - Keeps both Desktop Excel files (WhatsApp_Conversations.xlsx & WhatsApp_Leads_SHARED.xlsx) and live CSV synced.
  - Zero bot/owner messages. Customer details only.
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

# Styling: Deep Emerald Header & Segoe UI
HEADER_FILL = PatternFill("solid", fgColor="0B5345")
HEADER_FONT = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
DATA_FONT = Font(name="Segoe UI", size=10)
BOLD_FONT = Font(name="Segoe UI", size=10, bold=True)

THIN_BORDER = Border(
    left=Side(style="thin", color="E0E0E0"),
    right=Side(style="thin", color="E0E0E0"),
    top=Side(style="thin", color="E0E0E0"),
    bottom=Side(style="thin", color="E0E0E0"),
)

HEADERS = [
    "S.No.",
    "First Contact Date (IST)",
    "Last Contact Date (IST)",
    "Contact Person Name",
    "WhatsApp Number",
    "Email ID",
    "Company / Business Name",
    "GST Number",
    "Complete Address",
    "Customer Requirements Details",
]
WIDTHS = [8, 22, 22, 24, 20, 28, 30, 22, 45, 65]


def format_phone_display(raw_phone: str) -> str:
    p = str(raw_phone or "").replace("+", "").replace(" ", "").strip()
    if p.startswith("91") and len(p) == 12:
        return f"+91 {p[2:7]} {p[7:]}"
    elif p:
        return f"+{p}"
    return "Unknown"


def extract_lead_entities(text: str, profile_name: str = "", is_business_step: bool = False) -> dict:
    """
    Extract Email ID, Complete Address, Company Name, GST, and Contact Name from customer message.
    """
    clean_text = str(text or "").strip()

    # 1. Email ID
    email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b')
    email_match = email_pattern.search(clean_text)
    email = email_match.group(0).lower() if email_match else ""

    # 2. GST Number
    gst_pattern = re.compile(r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}\b', re.IGNORECASE)
    gst_match = gst_pattern.search(clean_text)
    gst = gst_match.group(0).upper() if gst_match else ""

    # 3. Contact Person Name
    contact_name = ""
    name_match = re.search(r'(?:contact\s*person|person|contact|name)[\s:.-]+([a-zA-Z\s]{3,30})', clean_text, re.IGNORECASE)
    if name_match:
        val = name_match.group(1).strip()
        if not any(kw in val.lower() for kw in ['company', 'enterprise', 'trader', 'gst', 'box', 'size', 'need', 'want', 'please', 'lugs', 'road']):
            contact_name = val.title()

    if not contact_name and profile_name:
        contact_name = profile_name.strip().title()

    # 4. Company / Business Name
    company = ""
    comp_match = re.search(r'(?:company|business|firm|shop|org|enterprise|firm\s*name)[\s:.-]+([^\n,]+)', clean_text, re.IGNORECASE)
    if comp_match:
        company = comp_match.group(1).strip()
    elif re.search(r'\b(enterprise[s]?|group\s+of\s+companies|traders|trading|pvt\s*ltd|ltd|industries|packaging|boxes|store|mart|agency|agencies|corporation|solutions|works|manufacturing)\b', clean_text, re.IGNORECASE):
        for part in re.split(r'[,;\n]', clean_text):
            if re.search(r'\b(enterprise[s]?|group\s+of\s+companies|traders|trading|pvt\s*ltd|ltd|industries|packaging|boxes|store|mart|agency|agencies|corporation|solutions|works|manufacturing)\b', part, re.IGNORECASE):
                if not re.search(r'\b(need|want|send|quote|price|rate|requirement)\b', part, re.IGNORECASE):
                    company = part.strip()
                    break

    # 5. Complete Address (Gathers all road, street, building, area, city, pin code lines)
    addr_lines = []
    lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
    addr_keywords = [
        'road', 'rd', 'street', 'st', 'lane', 'gali', 'bazar', 'bazaar', 'nagar', 'colony',
        'block', 'sector', 'floor', 'plot', 'shop', 'near', 'opp', 'opposite', 'behind',
        'dist', 'district', 'pin', 'kolkata', 'mumbai', 'delhi', 'chennai', 'bangalore',
        'hyderabad', 'pune', 'ahmedabad', 'surat', 'jaipur', 'lucknow', 'howrah', 'west bengal',
        'maharashtra', 'gujarat', 'up', 'bihar'
    ]

    for line in lines:
        line_l = line.lower()
        if gst and gst in line.upper():
            continue
        if email and email in line_l:
            continue
        if company and line.strip().lower() == company.lower():
            continue
        if any(kw in line_l for kw in addr_keywords) or re.search(r'\b\d{6}\b', line):
            cleaned = re.sub(r'^(?:address|location|addr|office)[\s:.-]+', '', line, flags=re.IGNORECASE).strip()
            if cleaned and cleaned not in addr_lines:
                addr_lines.append(cleaned)

    complete_address = ", ".join(addr_lines) if addr_lines else ""

    # Fallback for business step: if company still missing, check first non-metadata, non-chatter line
    chatter_words = {
        'ok', 'okay', 'thanks', 'thank you', 'call me', 'hi', 'hello', 'hey', 'yes', 'no',
        'fine', 'good', 'sure', 'send', 'please', 'ok thanks', 'k', 'alright', 'done'
    }
    if is_business_step and not company:
        for line in lines:
            line_clean = line.strip().lower()
            if gst_pattern.search(line) or (email and email in line_clean):
                continue
            if line_clean in chatter_words:
                continue
            if not any(kw in line_clean for kw in ['pin', 'kolkata', 'delhi', 'mumbai', 'phone', 'contact', 'gst', 'www', 'http', 'road', 'street', 'bazar', 'call', 'reply', 'send']):
                if 2 <= len(line.strip()) < 60 and len(line.split()) >= 1:
                    company = line.strip()
                    break

    return {
        "email": email,
        "company": company,
        "gst": gst,
        "address": complete_address,
        "contact": contact_name,
    }


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
    ws.views.sheetView[0].showGridLines = True

    for col_idx, (header, width) in enumerate(zip(HEADERS, WIDTHS), start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"
    return wb


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


def _apply_lead_to_workbook(file_path: str, lead_data: dict) -> bool:
    wb = _get_or_create_workbook(file_path)
    ws = wb["Customer Leads"] if "Customer Leads" in wb.sheetnames else wb.active

    phone = lead_data.get("phone", "")
    timestamp = lead_data.get("timestamp", "")
    contact_name = lead_data.get("contact_name", "")
    email = lead_data.get("email", "")
    company = lead_data.get("company", "")
    gst = lead_data.get("gst", "")
    address = lead_data.get("address", "")
    requirements = lead_data.get("requirements", "")

    match_row = None
    first_empty_row = None
    existing_leads_count = 0

    for r in range(2, ws.max_row + 1):
        existing_phone = ws.cell(row=r, column=5).value
        if existing_phone:
            existing_leads_count += 1
            if existing_phone == phone:
                match_row = r
                break
        elif first_empty_row is None:
            first_empty_row = r

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    if match_row:
        # Col 3: Last Contact Date
        ws.cell(row=match_row, column=3, value=timestamp)

        if contact_name and contact_name != "Unknown Customer":
            ws.cell(row=match_row, column=4, value=contact_name)
        if email:
            ws.cell(row=match_row, column=6, value=email)
        if company:
            ws.cell(row=match_row, column=7, value=company)
        if gst:
            ws.cell(row=match_row, column=8, value=gst)
        if address:
            ws.cell(row=match_row, column=9, value=address)
        if requirements:
            prev_req = str(ws.cell(row=match_row, column=10).value or "").strip()
            if prev_req and prev_req != "—":
                new_lines = [l.strip() for l in requirements.splitlines() if l.strip()]
                prev_lower = prev_req.lower()
                to_add = [l for l in new_lines if l.lower() not in prev_lower]
                if to_add:
                    combined_req = f"{prev_req}\n" + "\n".join(to_add)
                else:
                    combined_req = prev_req
            else:
                combined_req = requirements
            ws.cell(row=match_row, column=10, value=combined_req)
    else:
        new_row = first_empty_row if first_empty_row is not None else (ws.max_row + 1)
        s_no = existing_leads_count + 1
        row_values = [
            s_no,
            timestamp,              # Col 2: First Contact Date (IST)
            timestamp,              # Col 3: Last Contact Date (IST)
            contact_name or "Unknown Customer", # Col 4: Contact Person Name
            phone,                  # Col 5: WhatsApp Number
            email or "—",           # Col 6: Email ID
            company or "—",         # Col 7: Company / Business Name
            gst or "—",             # Col 8: GST Number
            address or "—",         # Col 9: Complete Address
            requirements or "—",    # Col 10: Customer Requirements Details
        ]

        for col_idx, val in enumerate(row_values, start=1):
            cell = ws.cell(row=new_row, column=col_idx, value=val)
            cell.font = DATA_FONT
            cell.border = THIN_BORDER
            cell.alignment = align_center if col_idx in (1, 2, 3, 5, 8) else align_left

        ws.row_dimensions[new_row].height = 28

    wb.save(file_path)
    return True


def _update_live_csv(lead_data: dict) -> None:
    """Always maintains a live lock-free CSV copy on Desktop with 10 columns."""
    try:
        rows = []
        if os.path.exists(CSV_PATH):
            with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)

        if not rows:
            rows = [HEADERS]

        phone = lead_data.get("phone", "")
        match_idx = None
        for i in range(1, len(rows)):
            if len(rows[i]) > 4 and rows[i][4] == phone:
                match_idx = i
                break

        if match_idx is not None:
            while len(rows[match_idx]) < 10:
                rows[match_idx].append("—")
            rows[match_idx][2] = lead_data.get("timestamp", "")
            if lead_data.get("contact_name"):
                rows[match_idx][3] = lead_data.get("contact_name")
            if lead_data.get("email"):
                rows[match_idx][5] = lead_data.get("email")
            if lead_data.get("company"):
                rows[match_idx][6] = lead_data.get("company")
            if lead_data.get("gst"):
                rows[match_idx][7] = lead_data.get("gst")
            if lead_data.get("address"):
                rows[match_idx][8] = lead_data.get("address")
            if lead_data.get("requirements"):
                prev = rows[match_idx][9]
                rows[match_idx][9] = f"{prev} | {lead_data.get('requirements')}" if prev and prev != "—" else lead_data.get("requirements")
        else:
            s_no = len(rows)
            rows.append([
                s_no,
                lead_data.get("timestamp", ""),
                lead_data.get("timestamp", ""),
                lead_data.get("contact_name") or "Unknown Customer",
                phone,
                lead_data.get("email") or "—",
                lead_data.get("company") or "—",
                lead_data.get("gst") or "—",
                lead_data.get("address") or "—",
                lead_data.get("requirements") or "—",
            ])

        with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
    except Exception as e:
        print(f"[CSV ERROR] {e}")


def flush_pending_excel_queue():
    with _excel_lock:
        queue = _load_queue()
        if not queue:
            return

        unflushed = []
        for item in queue:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                dest, lead = item
            else:
                dest, lead = EXCEL_FILE_PATH, item

            try:
                _apply_lead_to_workbook(dest, lead)
            except PermissionError:
                unflushed.append((dest, lead))
            except Exception as e:
                print(f"[EXCEL QUEUE ERROR] {e}")

        if len(unflushed) < len(queue):
            flushed_count = len(queue) - len(unflushed)
            print(f"[EXCEL SYNC] Flushed {flushed_count} queued customer leads to Desktop files!")

        _save_queue(unflushed)


def log_customer_lead(
    sender_phone: str,
    sender_name: str,
    message_text: str = "",
    analyzed_products: str = "",
    is_requirement_step: bool = False,
    is_business_step: bool = False,
) -> None:
    """
    Primary function to record customer lead details.
    Extracts Contact Name, Phone, Email, Company, GST, Complete Address, and Pure Requirements.
    Saves to Desktop live file, Desktop shared file, live CSV, and project backup.
    """
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    formatted_phone = format_phone_display(sender_phone)

    # 1. Extract entities from text
    extracted = extract_lead_entities(message_text, sender_name, is_business_step=is_business_step)

    # 2. Determine requirements details (Pure products only, reject chatter)
    requirements = ""
    if analyzed_products and not analyzed_products.startswith("No text"):
        requirements = analyzed_products
    elif message_text and not message_text.startswith("["):
        requirements = parse_product_details(message_text)

    lead_data = {
        "timestamp": now_ist,
        "contact_name": extracted["contact"],
        "phone": formatted_phone,
        "email": extracted["email"],
        "company": extracted["company"],
        "gst": extracted["gst"],
        "address": extracted["address"],
        "requirements": requirements,
    }

    # Asynchronously push lead to cloud Google Sheets if webhook configured
    try:
        from cloud_sync import push_lead_to_cloud
        push_lead_to_cloud({
            "first_contact": now_ist,
            "last_contact": now_ist,
            "name": extracted["contact"],
            "phone": formatted_phone,
            "email": extracted["email"],
            "company": extracted["company"],
            "gst": extracted["gst"],
            "address": extracted["address"],
            "requirements": requirements,
        })
    except Exception:
        pass

    with _excel_lock:
        _update_live_csv(lead_data)

        try:
            _apply_lead_to_workbook(BACKUP_EXCEL_PATH, lead_data)
        except Exception as e:
            print(f"[EXCEL BACKUP ERROR] {e}")

        for dest in [EXCEL_FILE_PATH, SHARED_EXCEL_PATH]:
            try:
                _apply_lead_to_workbook(dest, lead_data)
                print(f"[EXCEL] ✅ Saved to {os.path.basename(dest)}: {lead_data['contact_name']} ({formatted_phone})")
            except PermissionError:
                queue = _load_queue()
                queue.append((dest, lead_data))
                _save_queue(queue)
                print(f"[EXCEL INFO] {os.path.basename(dest)} is currently open. Queued safely for auto-sync.")
            except Exception as e:
                queue = _load_queue()
                queue.append((dest, lead_data))
                _save_queue(queue)
                print(f"[EXCEL QUEUE] Queued: {e}")
