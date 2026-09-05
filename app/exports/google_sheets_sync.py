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
    """Asynchronously syncs customer record to Google Sheets via webhook with 100% pure data."""
    webhook_url = settings.GOOGLE_SHEET_WEBHOOK_URL
    if not webhook_url:
        logger.debug("[GOOGLE SHEETS] GOOGLE_SHEET_WEBHOOK_URL not configured. Skipping cloud sheet sync.")
        return False

    from app.exports.data_sanitizer import sanitize_customer_model
    clean = sanitize_customer_model(customer)

    phone_clean = clean["whatsapp_number"]
    phone_payload = ("'" + phone_clean) if (phone_clean and not phone_clean.startswith("'")) else phone_clean

    payload = {
        "first_contact_date": clean["first_contact_date"],
        "last_contact_date": clean["last_contact_date"],
        "contact_person_name": clean["contact_person_name"],
        "whatsapp_number": phone_payload,
        "email_id": clean["email_id"],
        "company_name": clean["company_name"],
        "gst_number": clean["gst_number"],
        "complete_address": clean["complete_address"],
        "requirements_summary": clean["requirements_summary"],
        "requirements": clean["requirements_summary"]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            res = await client.post(webhook_url, json=payload)
            if res.status_code == 200:
                logger.info("[GOOGLE SHEETS] Successfully synced customer %s to cloud sheet!", clean["whatsapp_number"])
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

    from app.exports.data_sanitizer import sanitize_customer_model
    clean = sanitize_customer_model(customer)

    phone_clean = clean["whatsapp_number"]
    phone_payload = ("'" + phone_clean) if (phone_clean and not phone_clean.startswith("'")) else phone_clean

    payload = {
        "first_contact_date": clean["first_contact_date"],
        "last_contact_date": clean["last_contact_date"],
        "contact_person_name": clean["contact_person_name"],
        "whatsapp_number": phone_payload,
        "email_id": clean["email_id"],
        "company_name": clean["company_name"],
        "gst_number": clean["gst_number"],
        "complete_address": clean["complete_address"],
        "requirements_summary": clean["requirements_summary"],
        "requirements": clean["requirements_summary"]
    }

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            res = client.post(webhook_url, json=payload)
            if res.status_code == 200:
                logger.info("[GOOGLE SHEETS] Synced %s to Google Sheet", clean["whatsapp_number"])
                return True
    except Exception as e:
        logger.error("[GOOGLE SHEETS SYNC ERROR] %s", e)

    return False
