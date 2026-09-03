"""
electrical_nlp.py — Deterministic electrical domain entity extraction & validation.
Extracts:
  - Product requirements (name, quantity, size/specs)
  - GSTIN (15-character structural validation)
  - Email addresses (RFC-5322 regex)
  - Business / Company names
  - Complete business addresses
  - Contact person names
"""

import re
from typing import List, Optional, Dict, Any
from app.schemas.extraction import ProductItem

# ── 1. INDIAN GST VALIDATION ──────────────────────────────────────────────────
# Format: 2 digits state code + 5 chars PAN + 4 chars PAN digits + 1 char PAN + 1 entity num + 'Z' + 1 checksum
GST_REGEX = re.compile(r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Zz]{1}[A-Z\d]{1}\b')

def extract_gst(text: str) -> Optional[str]:
    if not text:
        return None
    matches = GST_REGEX.findall(text)
    if matches:
        return matches[-1].upper()
    # Check explicit "Not applicable"
    lower = text.lower()
    if any(p in lower for p in ("no gst", "without gst", "gst not applicable", "gst na", "no gstin", "retail customer", "composite")):
        return "Not Applicable"
    return None

# ── 2. EMAIL VALIDATION ───────────────────────────────────────────────────────
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b')

def extract_email(text: str) -> Optional[str]:
    if not text:
        return None
    match = EMAIL_REGEX.search(text)
    return match.group(0).lower() if match else None

# ── 3. ELECTRICAL PRODUCT EXTRACTION ──────────────────────────────────────────
ELECTRICAL_KEYWORDS = [
    "led bulb", "bulb", "batten", "tube light", "tubelight", "downlight", "panel light", "flood light", "street light",
    "fan", "ceiling fan", "exhaust fan", "table fan", "pedestal fan",
    "mcb", "rccb", "mccb", "isolator", "distribution board", "db box", "junction box", "gang box",
    "wire", "cable", "flexible wire", "copper wire", "armoured cable", "submersible cable", "coaxial cable", "lan cable",
    "switch", "socket", "regulator", "modular switch", "plug", "holder", "ceiling rose", "indicator", "bell push",
    "pvc conduit", "casing", "capping", "conduit pipe", "flexible pipe",
    "tape", "insulation tape", "lugs", "gland", "cable tie", "multimeter", "tester",
    "geyser", "immersion rod", "heater", "choke", "starter", "capacitor"
]

UNITS_REGEX = re.compile(
    r'\b(\d+(?:\.\d+)?)\s*(pcs|pc|nos|pieces|box|boxes|pkt|packet|packets|meters|meter|mtr|mtrs|rolls|roll|coils|coil|bundles|bundle|sets|set|doz|dozen|sq\s*mm|sqmm)\b',
    re.IGNORECASE
)

SPECS_REGEX = re.compile(
    r'\b(\d+[\s]*(?:w|watt|watts|v|volt|volts|a|amp|amps|ah|hp|kva|sq\s*mm|sqmm|mm|cm|inch|in|feet|ft|b22|e27|cool\s*white|warm\s*white|natural\s*white|single\s*pole|sp|dp|tp|tpn|4p|1200mm|900mm|600mm|1400mm))\b',
    re.IGNORECASE
)

def extract_electrical_products(text: str) -> List[ProductItem]:
    if not text:
        return []
    
    items: List[ProductItem] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    for line in lines:
        lower = line.lower()
        # Skip pure business lines
        if any(h in lower for h in ("gst", "gstin", "email", "phone", "address", "company", "dear sir", "regards", "thank you")):
            continue
        
        matched_keyword = None
        for kw in ELECTRICAL_KEYWORDS:
            if kw in lower:
                matched_keyword = kw
                break
        
        # If electrical keyword or unit with number is present
        unit_match = UNITS_REGEX.search(line)
        spec_matches = SPECS_REGEX.findall(line)
        
        if matched_keyword or unit_match or ("need" in lower and any(c.isdigit() for c in line)):
            qty_str = unit_match.group(0) if unit_match else None
            # Extract number if no unit
            if not qty_str:
                num_match = re.search(r'\b\d+\b', line)
                if num_match:
                    qty_str = f"{num_match.group(0)} pcs"

            prod_name = matched_keyword.title() if matched_keyword else line[:40].strip()
            specs_str = ", ".join(spec_matches) if spec_matches else None
            
            clean_desc = re.sub(r'^(?:[•\-\*\+]|\d+[\.\)])\s*', '', line).strip()
            
            items.append(ProductItem(
                product_name=prod_name,
                description=clean_desc,
                quantity=qty_str,
                specifications=specs_str
            ))

    return items[:15]

# ── 4. COMPANY / BUSINESS NAME EXTRACTION ─────────────────────────────────────
COMPANY_INDICATORS = [
    "electricals", "electric", "enterprises", "traders", "trading", "industries", "corp", "corporation",
    "agency", "agencies", "co", "company", "hardware", "store", "shop", "solutions", "limited", "ltd", "pvt ltd", "llp"
]

IGNORE_UI_PHRASES = (
    "not a contact", "no common groups", "common groups", "click here",
    "online", "typing", "last seen", "message yourself", "messages and calls",
    "end-to-end", "encrypted", "disappearing", "mute notifications", "business account",
    "account", "customer"
)

CHAT_CHATTER_PHRASES = (
    "download", "attached", ".xlsx", ".pdf", ".png", ".jpg", "document", "photo", "image",
    "needed", "costly", "delivery is", "acha", "wala", "hoga", "kardo", "bhejo", "kya", "hai",
    "please share", "quotation", "rate", "price", "batao", "kaise", "kab tak", "brand preference",
    "regret", "delivery", "sir", "bhaiya", "ok sir"
)

def extract_company_name(text: str) -> Optional[str]:
    if not text:
        return None
    
    # 1. Explicit label has highest priority
    for line in text.splitlines():
        line_clean = line.strip()
        lower = line_clean.lower()
        if any(lower.startswith(prefix) for prefix in ("company:", "business:", "firm:", "shop:", "company name:", "firm name:", "m/s:", "m/s ")):
            clean = re.sub(r'^(?:company name|firm name|company|business|firm|shop|m/s)[\s:-]+', '', line_clean, flags=re.IGNORECASE).strip()
            if len(clean) >= 3 and len(clean) <= 60 and not any(p in clean.lower() for p in IGNORE_UI_PHRASES) and not any(p in clean.lower() for p in CHAT_CHATTER_PHRASES):
                return clean.title()

    # 2. Pattern: from <Company> or at <Company>
    from_m = re.search(
        r'\b(?:from|at)\s+([A-Za-z0-9\s&]{3,40}?(?:electricals|electric|enterprises|traders|trading|industries|corp|corporation|agency|agencies|hardware|store|solutions|limited|ltd|pvt ltd|llp))\b',
        text,
        re.IGNORECASE
    )
    if from_m:
        cand = from_m.group(1).strip()
        cand_l = cand.lower()
        if not any(p in cand_l for p in IGNORE_UI_PHRASES) and not any(p in cand_l for p in CHAT_CHATTER_PHRASES):
            return cand.title()

    # 3. Line scan with strict indicator
    for line in text.splitlines():
        line_clean = line.strip()
        lower = line_clean.lower()
        if any(p in lower for p in IGNORE_UI_PHRASES) or any(p in lower for p in CHAT_CHATTER_PHRASES):
            continue
        if "?" in line_clean:
            continue
        # Exclude pure wattages or quantities or simple messages
        if re.match(r'^\d+\s*(?:watt|w|pcs|pc|mtr|meter|m|nos|no)\b', lower):
            continue
        if any(ind in lower for ind in ("electricals", "electric", "enterprises", "traders", "industries", "pvt ltd", "ltd", "corporation", "hardware store")) and len(line_clean) < 60:
            clean = re.sub(r'^(?:company|business|firm|shop|org|name)[\s:-]+', '', line_clean, flags=re.IGNORECASE).strip()
            if len(clean) >= 3 and not any(p in clean.lower() for p in IGNORE_UI_PHRASES) and not any(p in clean.lower() for p in CHAT_CHATTER_PHRASES):
                return clean.title()
    return None

# ── 5. COMPLETE ADDRESS EXTRACTION ────────────────────────────────────────────
PIN_CODE_REGEX = re.compile(r'\b[1-9][0-9]{5}\b')
STREET_MARKERS = ("road", "rd", "street", "st", "lane", "gali", "marg", "bazaar", "bazar", "market", "floor", "nagar", "chowk", "complex", "sector", "plot", "park", "industrial area", "industrial areea", "building", "opp", "opposite", "near", "beside")
CITY_MARKERS = ("kolkata", "delhi", "mumbai", "chennai", "bangalore", "hyderabad", "pune", "ahmedabad", "jaipur", "patna", "bengal", "burrabazar", "patliputra", "pirangut")

def extract_address(text: str) -> Optional[str]:
    if not text:
        return None
    matched_address_parts = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    for line in lines:
        lower = line.lower()
        # Reject questions, chat chatter, and UI noise immediately
        if "?" in line or any(p in lower for p in IGNORE_UI_PHRASES) or any(p in lower for p in CHAT_CHATTER_PHRASES):
            continue

        has_pin = bool(PIN_CODE_REGEX.search(line))
        has_street = any(sm in lower for sm in STREET_MARKERS)
        has_city = any(cm in lower for cm in CITY_MARKERS)
        is_explicit_label = any(lower.startswith(prefix) for prefix in ("address:", "loc:", "location:", "addr:", "shop address:", "office address:", "delivery address:"))
        
        if is_explicit_label:
            clean = re.sub(r'^(?:address|location|loc|addr|shop address|office address|delivery address)[\s:-]+', '', line, flags=re.IGNORECASE).strip()
            if len(clean) >= 5 and "?" not in clean:
                return clean

        # Legitimate address line: has pin code OR has premise marker + city marker
        if has_pin or (has_street and has_city and len(line) >= 12):
            # Exclude lines that are purely product orders or short chatter
            if not any(pk in lower for pk in ("bulb", "mcb", "wire", "cable", "fan", "switch", "watt", "pcs")):
                clean_line = line.replace('\r', '').strip()
                # If line is an intro like 'Hi, I am Debashis from Bengal Electricals, 12 Park St, Kolkata', isolate address
                snippet_m = re.search(r'(\d+[\s\w,.-]+(?:st|street|road|rd|lane|nagar|park|bazar|market)[\s\w,.-]*(?:kolkata|delhi|mumbai|chennai|bangalore|pune|patna|bengal|pirangut)\b)', clean_line, re.IGNORECASE)
                if snippet_m:
                    clean_line = snippet_m.group(1).strip()
                elif has_street and "," in clean_line:
                    parts = [p.strip() for p in clean_line.split(",") if any(sm in p.lower() for sm in STREET_MARKERS) or any(cm in p.lower() for cm in CITY_MARKERS) or PIN_CODE_REGEX.search(p)]
                    if parts:
                        clean_line = ", ".join(parts)

                if clean_line and clean_line not in matched_address_parts:
                    matched_address_parts.append(clean_line)

    if matched_address_parts:
        # Return clean address without duplicate commas
        return ", ".join(matched_address_parts)
    return None

# ── 6. CONTACT PERSON NAME EXTRACTION ─────────────────────────────────────────
def extract_contact_name(text: str, profile_name: Optional[str] = None) -> Optional[str]:
    # Check if profile name is provided from WhatsApp profile and is a valid personal name
    if profile_name:
        clean_p = profile_name.strip()
        lower_p = clean_p.lower()
        if not any(p in lower_p for p in IGNORE_UI_PHRASES) and not any(p in lower_p for p in CHAT_CHATTER_PHRASES):
            if len(clean_p) >= 2 and len(clean_p) <= 30 and not clean_p.replace('+', '').replace(' ', '').isdigit():
                return clean_p.title()

    if not text:
        return None
    
    # Explicit pattern: I am <Name> from ... or My name is <Name> or Contact Person: <Name>
    m = re.search(r'\b(?:my name is|i am|this is|contact person|contact person name|contact name)[\s:-]+([A-Za-z\s]{2,30})(?:\s+from|\s*,|\s*$|\s*\n)', text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        cand_l = candidate.lower()
        if cand_l not in ("here", "interested", "need", "we", "hi", "sir") and not any(p in cand_l for p in IGNORE_UI_PHRASES) and not any(p in cand_l for p in CHAT_CHATTER_PHRASES):
            return candidate.title()
        
    return None
