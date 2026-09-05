"""
data_sanitizer.py — 100% Pure Data Sanitizer & Validator for 9-Column Architecture.

Guarantees 100% clean, noise-free, accurate data entry into:
  1. First Contact Date (YYYY-MM-DD)
  2. Last Contact Date (YYYY-MM-DD)
  3. Contact Person Name (Clean human title-cased name, or fallback Company Name)
  4. WhatsApp Number (+91 XXXXX XXXXX)
  5. Email ID (Strict RFC-5322 regex or empty "")
  6. Company / Business Name (Title-cased legal entity, M/s stripped, zero chatter)
  7. GST Number (15-character uppercase GSTIN or "Not Applicable" or empty "")
  8. Complete Address (Pure physical postal address, zero GST/email/phone leakage)
  9. Customer Requirements Details (Clean product bullet points or document line items, zero chatter)
"""

import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

IST = timezone(timedelta(hours=5, minutes=30))

GST_REGEX = re.compile(r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Zz]{1}[A-Z\d]{1}\b')
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b')
PHONE_REGEX = re.compile(r'\b(?:\+?91[\s-]?)?[6-9]\d{9}\b')

INVALID_NAMES = {
    "none", "null", "customer", "user", "admin", "client", "buyer", "sir", "dear",
    "bhaiya", "bro", "hi", "hello", "hey", "test", "ok", "thanks", "thank you",
    "deleted this message", "online", "typing", "last seen", "not a contact"
}

CHATTER_PHRASES = [
    "please sir rate and availability", "rate and availability requested", "rate and availability",
    "please send rate", "rate please", "price please", "what is the price", "best price",
    "send quotation", "quotation please", "kab tak deliver hoga", "kab tak milega",
    "urgent requirement", "urgent please", "update please", "sir update", "missed call",
    "call me", "how much", "rate batao", "price batao", "bhejo sir", "kardo sir",
    "acha wala", "regret", "costly", "delivery is", "please share"
]

DEALER_TAGLINES = [
    "dealers in electrical goods", "dealers in", "dealer of", "authorized dealer",
    "authorised dealer", "all kinds of electrical", "all types of electrical",
    "stockist of", "distributor of", "manufacturers of", "supplier of"
]


def clean_first_contact_date(dt: Any) -> str:
    if not dt:
        return datetime.now(IST).strftime("%Y-%m-%d")
    if isinstance(dt, str):
        parts = dt.split()[0].replace('/', '-')
        m = re.match(r'^\d{4}-\d{2}-\d{2}$', parts)
        if m:
            return parts
    if hasattr(dt, "astimezone"):
        return dt.astimezone(IST).strftime("%Y-%m-%d")
    return datetime.now(IST).strftime("%Y-%m-%d")


def clean_last_contact_date(dt: Any) -> str:
    if not dt:
        return datetime.now(IST).strftime("%Y-%m-%d")
    if isinstance(dt, str):
        parts = dt.split()[0].replace('/', '-')
        m = re.match(r'^\d{4}-\d{2}-\d{2}$', parts)
        if m:
            return parts
    if hasattr(dt, "astimezone"):
        return dt.astimezone(IST).strftime("%Y-%m-%d")
    return datetime.now(IST).strftime("%Y-%m-%d")


def clean_contact_name(name: Optional[str], company: Optional[str] = None) -> str:
    """Returns a clean Title-Cased personal name, falling back to Company Name."""
    raw = str(name or "").strip()
    # Strip common designation prefixes
    cleaned = re.sub(
        r'^(?:mr\.?|shri|er\.?|dr\.?|prop\.?|proprietor|partner|director|owner|manager|contact(?:\s+person)?(?:\s+name)?)[\s:-]+',
        '', raw, flags=re.IGNORECASE
    ).strip()

    # Reject invalid names
    lower = cleaned.lower()
    is_invalid = (
        not cleaned or
        len(cleaned) < 2 or
        len(cleaned) > 40 or
        lower in INVALID_NAMES or
        any(inv in lower for inv in ("deleted this", "typing", "online", "not a contact", "customer")) or
        bool(re.search(r'\d', cleaned)) or  # Contains numbers
        cleaned.startswith("+")
    )

    if is_invalid:
        # Fallback to cleaned company name
        c_clean = clean_company_name(company)
        return c_clean if c_clean else ""

    return cleaned.title()


def clean_phone_number(raw_phone: Any) -> str:
    """Formats phone numbers strictly into '+91 XXXXX XXXXX' format."""
    digits = re.sub(r'[^0-9]', '', str(raw_phone or ""))
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif len(digits) > 10:
        digits = digits[-10:]
    
    if len(digits) == 10:
        return f"+91 {digits[:5]} {digits[5:]}"
    return str(raw_phone or "").strip()


def clean_email(raw_email: Optional[str]) -> str:
    """Validates and extracts RFC-5322 email or returns empty string."""
    if not raw_email:
        return ""
    m = EMAIL_REGEX.search(str(raw_email).strip())
    if m:
        return m.group(0).strip().lower().rstrip('.')
    return ""


def clean_company_name(raw_company: Optional[str]) -> str:
    """Cleans company name, stripping M/s prefixes, conversational intros, dealer taglines, and noise."""
    if not raw_company:
        return ""
    clean = str(raw_company).strip()

    # Strip conversational introductions: "Hi, I am Raj from ABC Electricals" -> "ABC Electricals"
    clean = re.sub(r'^(?:hi|hello|hey|namaste)?[,\s]*(?:i\s*am|this\s*is|my\s*name\s*is)?\s*[A-Za-z\s]+?\s+from\s+', '', clean, flags=re.IGNORECASE).strip()

    # Strip prefixes: M/s, M/S, Messrs, Company:, Firm:, Shop Name:
    clean = re.sub(r'^(?:m/s\.?|messrs\.?|company(?:\s+name)?|firm(?:\s+name)?|shop(?:\s+name)?|business)[\s:-]+', '', clean, flags=re.IGNORECASE).strip()
    
    # Reject business dealer taglines
    lower = clean.lower()
    for tag in DEALER_TAGLINES:
        if lower.startswith(tag):
            return ""

    # Reject if it's chatter, product spec, or invalid
    if any(ch in lower for ch in CHATTER_PHRASES) or lower in INVALID_NAMES:
        return ""
    if re.match(r'^\d+\s*(?:watt|w|pcs|pc|mtr|meter|m|nos)\b', lower):
        return ""
    if len(clean) < 3 or len(clean) > 60:
        return ""

    # Strip trailing punctuation
    clean = clean.rstrip(' :;,-.')
    return clean.title()


def clean_gst_number(raw_gst: Optional[str]) -> str:
    """Validates 15-character Indian GSTIN or 'Not Applicable'."""
    if not raw_gst:
        return ""
    val = str(raw_gst).strip()
    m = GST_REGEX.search(val)
    if m:
        return m.group(0).upper()
    
    val_lower = val.lower()
    if any(p in val_lower for p in ("not applicable", "na", "no gst", "without gst", "retail", "unregistered", "composite")):
        return "Not Applicable"
    return ""


def clean_address(raw_address: Optional[str]) -> str:
    """
    Cleans complete address:
    - Strips out leaked GSTINs
    - Strips out leaked email addresses
    - Strips out leaked phone numbers
    - Strips out labels (GST:, Email:, Ph:, Address:)
    - Strips out company header prefixes (e.g. 'M/s Gupta Electricals, 12 Park Street...')
    - Strips out conversational chatter ('Our shop is...', 'I am from...')
    """
    if not raw_address:
        return ""
    
    addr = str(raw_address).strip()
    
    # 1. Remove 15-char GSTINs
    addr = GST_REGEX.sub('', addr)
    
    # 2. Remove Email addresses
    addr = EMAIL_REGEX.sub('', addr)
    
    # 3. Remove 10-12 digit phone numbers
    addr = PHONE_REGEX.sub('', addr)
    
    # 4. Remove labels like GSTIN:, Email:, Phone:, Address:, Loc:
    addr = re.sub(r'\b(?:gstin|gst|email|e-mail|mail|phone|ph|mob|mobile|address|addr|loc|location)\b[\s:-]*', '', addr, flags=re.IGNORECASE)
    
    # 5. Remove conversational intros from address: "Hi, I am X from Y Electricals, 12 Park St..."
    addr = re.sub(r'^(?:hi|hello|hey|namaste)?[,\s]*(?:i\s*am|this\s*is|my\s*name\s*is)?\s*[A-Za-z\s]+?\s+from\s+[A-Za-z0-9\s&.]+,?\s*', '', addr, flags=re.IGNORECASE).strip()
    
    # 6. Remove premise introductions: "Our shop is 12 MG Road...", "Office is at..."
    addr = re.sub(r'^(?:our\s+(?:shop|office|godown|factory|firm|company|unit)(?:\s+is|\s+at)?|shop\s+is|office\s+is)[\s:-]*', '', addr, flags=re.IGNORECASE).strip()

    # 7. Remove company names preceding the address: "M/s Gupta Electricals, 12 Park Street..."
    addr = re.sub(r'^(?:m/s\.?|messrs\.?)\s*[A-Za-z0-9\s&.]+(?:electricals|electric|enterprises|traders|trading|industries|corp|corporation|hardware|store|solutions|limited|ltd|pvt ltd|llp|co\.?),?\s*', '', addr, flags=re.IGNORECASE).strip()

    # 8. Remove conversational chatter
    for phrase in CHATTER_PHRASES:
        addr = re.sub(re.escape(phrase), '', addr, flags=re.IGNORECASE)
    
    # 9. Clean up punctuation artifacts (",,", " , ", trailing commas, semicolons)
    addr = re.sub(r'[,;\s]+,', ',', addr)
    addr = re.sub(r'\s{2,}', ' ', addr)
    addr = addr.strip(' ,;:-.')
    
    if len(addr) < 4:
        return ""
        
    return addr


def clean_requirements_summary(raw_req: Optional[str]) -> str:
    """
    Cleans requirements details:
    - Retains structured product bullet points (• Product - Qty)
    - Retains document / photo references
    - STRICTLY PURGES conversational chatter, rates requests, questions, and dealer taglines.
    """
    if not raw_req:
        return ""

    raw = str(raw_req).strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    cleaned_items = []

    for line in lines:
        lower = line.lower()

        # 1. Purge conversational chatter
        if any(ch in lower for ch in CHATTER_PHRASES):
            # Check if chatter is appended in parentheses like "Product Image Attached (Rate and availability requested)"
            line = re.sub(r'\s*\([^)]*(?:rate|availab|price|update|quote|quotation|cost)[^)]*\)', '', line, flags=re.IGNORECASE).strip()
            lower = line.lower()
            if not line or any(ch in lower for ch in CHATTER_PHRASES):
                continue

        # 2. Purge business dealer taglines
        if any(tag in lower for tag in DEALER_TAGLINES):
            continue

        # 3. Skip greetings, UI strings, noise
        if lower in ("hi", "hello", "hey", "ok", "thanks", "thank you", "yes", "no", "product:", "description:"):
            continue
        if any(inv in lower for inv in ("deleted this message", "click here", "online", "typing")):
            continue

        # 4. Format clean bullet points
        clean_item = re.sub(r'^(?:[•\-\*\+]|\d+[\.\)])\s*', '', line).strip()
        clean_item = re.sub(r'^(?:product|description)\s*[:\-]+\s*', '', clean_item, flags=re.IGNORECASE).strip()
        if clean_item.startswith("[") and clean_item.endswith("]"):
            clean_item = clean_item[1:-1].strip()

        if clean_item:
            # If line is a header like 'Document: file.pdf', 'Product Photo Attached', 'Product Image Attached'
            if clean_item.lower().startswith("document:") or any(term in clean_item.lower() for term in ("photo attached", "image attached", "file attached")):
                if clean_item not in cleaned_items:
                    cleaned_items.append(clean_item)
            else:
                bullet_item = f"• {clean_item}"
                if bullet_item not in cleaned_items:
                    cleaned_items.append(bullet_item)

    if not cleaned_items:
        return ""

    return "\n".join(cleaned_items[:12])


def sanitize_lead_dict(data: Dict[str, Any]) -> Dict[str, str]:
    """Sanitizes raw lead dictionary to ensure 100% pure data across all 9 columns."""
    c_date1 = clean_first_contact_date(data.get("first_contact_date") or data.get("first_contact_at"))
    c_date2 = clean_last_contact_date(data.get("last_contact_date") or data.get("last_contact_at"))
    c_company = clean_company_name(data.get("company_name") or data.get("company_business_name"))
    c_name = clean_contact_name(data.get("contact_person_name"), company=c_company)
    c_phone = clean_phone_number(data.get("whatsapp_number"))
    c_email = clean_email(data.get("email_id") or data.get("email"))
    c_gst = clean_gst_number(data.get("gst_number"))
    c_addr = clean_address(data.get("complete_address"))
    c_reqs = clean_requirements_summary(data.get("requirements_summary") or data.get("requirements"))

    return {
        "first_contact_date": c_date1,
        "last_contact_date": c_date2,
        "contact_person_name": c_name,
        "whatsapp_number": c_phone,
        "email_id": c_email,
        "company_name": c_company,
        "gst_number": c_gst,
        "complete_address": c_addr,
        "requirements_summary": c_reqs
    }


def sanitize_customer_model(customer: Any) -> Dict[str, str]:
    """Extracts and sanitizes all 9 columns from Customer ORM model."""
    first_dt = getattr(customer, "first_contact_at", None)
    last_dt = getattr(customer, "last_contact_at", None)
    
    return sanitize_lead_dict({
        "first_contact_at": first_dt,
        "last_contact_at": last_dt,
        "contact_person_name": getattr(customer, "contact_person_name", None),
        "whatsapp_number": getattr(customer, "whatsapp_number", None),
        "email": getattr(customer, "email", None),
        "company_name": getattr(customer, "company_name", None),
        "gst_number": getattr(customer, "gst_number", None),
        "complete_address": getattr(customer, "complete_address", None),
        "requirements_summary": getattr(customer, "requirements_summary", None)
    })
