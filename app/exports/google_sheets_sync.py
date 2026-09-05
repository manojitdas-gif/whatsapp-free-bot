"""
google_sheets_sync.py — Real-time synchronization of customer records to Google Sheets.
Sends clean 9-column payloads to the Google Apps Script Webhook.
"""

import re
import httpx
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

def format_in_phone(raw: str) -> str:
    """Standardizes phone numbers to +91 XXXXX XXXXX format."""
    digits = re.sub(r'[^0-9]', '', str(raw or ""))
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif len(digits) > 10:
        digits = digits[-10:]
    if len(digits) == 10:
        return f"+91 {digits[:5]} {digits[5:]}"
    return str(raw or "").strip()

async def sync_customer_to_google_sheet_async(customer) -> bool:
    """Asynchronously syncs customer record to Google Sheets via webhook."""
    webhook_url = settings.GOOGLE_SHEET_WEBHOOK_URL
    if not webhook_url:
        logger.debug("[GOOGLE SHEETS] GOOGLE_SHEET_WEBHOOK_URL not configured. Skipping cloud sheet sync.")
        return False

    first_dt = customer.first_contact_at
    if first_dt and hasattr(first_dt, "astimezone"):
        first_str = first_dt.astimezone(IST).strftime("%Y-%m-%d")
    else:
        first_str = datetime.now(IST).strftime("%Y-%m-%d")

    last_dt = customer.last_contact_at
    if last_dt and hasattr(last_dt, "astimezone"):
        last_str = last_dt.astimezone(IST).strftime("%Y-%m-%d")
    else:
        last_str = datetime.now(IST).strftime("%Y-%m-%d")

    contact_name = customer.contact_person_name or customer.company_name or ""
    if contact_name.lower() in ("customer", "none"):
        contact_name = customer.company_name or ""

    payload = {
        "first_contact_date": first_str,
        "last_contact_date": last_str,
        "contact_person_name": contact_name,
        "whatsapp_number": format_in_phone(customer.whatsapp_number),
        "email_id": customer.email or "",
        "company_name": customer.company_name or "",
        "gst_number": customer.gst_number or "",
        "complete_address": customer.complete_address or "",
        "requirements_summary": customer.requirements_summary or ""
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            res = await client.post(webhook_url, json=payload)
            if res.status_code == 200:
                logger.info("[GOOGLE SHEETS] Successfully synced customer %s to cloud sheet!", customer.whatsapp_number)
                return True
            else:
                logger.warning("[GOOGLE SHEETS] Status %d: %s", res.status_code, res.text)
    except Exception as e:
        logger.error("[GOOGLE SHEETS SYNC ERROR] %s", e)

    return False

def sync_customer_to_google_sheet(customer) -> bool:
    """Synchronous wrapper for sync_customer_to_google_sheet_async."""
    webhook_url = settings.GOOGLE_SHEET_WEBHOOK_URL
    if not webhook_url:
        return False

    first_dt = customer.first_contact_at
    if first_dt and hasattr(first_dt, "astimezone"):
        first_str = first_dt.astimezone(IST).strftime("%Y-%m-%d")
    else:
        first_str = datetime.now(IST).strftime("%Y-%m-%d")

    last_dt = customer.last_contact_at
    if last_dt and hasattr(last_dt, "astimezone"):
        last_str = last_dt.astimezone(IST).strftime("%Y-%m-%d")
    else:
        last_str = datetime.now(IST).strftime("%Y-%m-%d")

    contact_name = customer.contact_person_name or customer.company_name or ""
    if contact_name.lower() in ("customer", "none"):
        contact_name = customer.company_name or ""

    payload = {
        "first_contact_date": first_str,
        "last_contact_date": last_str,
        "contact_person_name": contact_name,
        "whatsapp_number": format_in_phone(customer.whatsapp_number),
        "email_id": customer.email or "",
        "company_name": customer.company_name or "",
        "gst_number": customer.gst_number or "",
        "complete_address": customer.complete_address or "",
        "requirements_summary": customer.requirements_summary or ""
    }

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            res = client.post(webhook_url, json=payload)
            if res.status_code == 200:
                logger.info("[GOOGLE SHEETS] Synced %s to Google Sheet", customer.whatsapp_number)
                return True
    except Exception as e:
        logger.error("[GOOGLE SHEETS SYNC ERROR] %s", e)

    return False
