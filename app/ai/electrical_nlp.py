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
        # Skip pure business lines and dealer slogans
        if any(h in lower for h in ("gst", "gstin", "email", "phone", "address", "company", "dear sir", "regards", "thank you", "dealers in", "dealer of", "all kinds of", "stockist of", "authorized dealer", "distributor of")):
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

CHATTER_EXCLUDE_REGEX = re.compile(
    r'\b(acha|wala|hoga|kardo|bhejo|kya|hai|rate|price|batao|kaise|kab tak|bhaiya|ok sir|regret|costly)\b',
    re.IGNORECASE
)
CHAT_PHRASES_LITERAL = (
    "download", "attached", ".xlsx", ".pdf", ".png", ".jpg", "document", "photo", "image",
    "delivery is", "please share", "quotation", "brand preference", "best price"
)

def is_noise_or_chatter(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    if any(p in lower for p in CHAT_PHRASES_LITERAL):
        return True
    if CHATTER_EXCLUDE_REGEX.search(lower):
        return True
    return False

def extract_company_name(text: str) -> Optional[str]:
    if not text:
        return None
    
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # 1. Explicit label has highest priority
    for line_clean in lines:
        lower = line_clean.lower()
        if any(lower.startswith(prefix) for prefix in ("company:", "business:", "firm:", "shop:", "company name:", "firm name:", "m/s:", "m/s ")):
            clean = re.sub(r'^(?:company name|firm name|company|business|firm|shop|m/s)[\s:-]+', '', line_clean, flags=re.IGNORECASE).strip()
            if len(clean) >= 3 and len(clean) <= 60 and not any(p in clean.lower() for p in IGNORE_UI_PHRASES) and not is_noise_or_chatter(clean):
                return clean.title()

    # 2. Visiting card / document header detection (Top 3 lines)
    for l in lines[:3]:
        lower_l = l.lower()
        if any(tag in lower_l for tag in ("dealers in", "dealer of", "all kinds of", "stockist", "distributor", "authorized dealer", "authorised dealer", "manufacturers of")):
            continue
        if any(p in lower_l for p in IGNORE_UI_PHRASES) or is_noise_or_chatter(lower_l):
            continue
        # Check if line contains clear company entity marker
        if any(ind in lower_l for ind in (" co.", " co", " company", "enterprises", "traders", "trading", "industries", "electricals", "electric", "pvt ltd", "ltd", "corporation", "hardware")):
            clean = re.sub(r'^(?:m/s\.?|messrs\.?)\s*', '', l, flags=re.IGNORECASE).strip()
            if len(clean) >= 3 and len(clean) <= 60:
                return clean.title()

    # 3. Strong legal entity pattern
    text_clean = re.sub(r'\bm/s\.?\s*', '', text, flags=re.IGNORECASE)
    legal_m = re.search(
        r'\b([A-Za-z0-9\s&().]{3,50}?\b(?:Private Limited|Pvt Ltd|Pvt\. Ltd\.|Limited|Ltd|Enterprises|Industries|Electricals|Electric|Traders|Corporation))\b',
        text_clean,
        re.IGNORECASE
    )
    if legal_m:
        cand = legal_m.group(1).strip()
        cand_l = cand.lower()
        if not any(tag in cand_l for tag in ("dealers in", "dealer of", "all kinds of", "stockist", "distributor", "authorized dealer", "dealers")) and not any(p in cand_l for p in IGNORE_UI_PHRASES) and not is_noise_or_chatter(cand_l):
            return cand.title()

    # 4. Pattern: from <Company> or at <Company>
    from_m = re.search(
        r'\b(?:from|at)\s+([A-Za-z0-9\s&]{2,40}?(?:trading co|trading company|trading corp|electricals|electric|enterprises|traders|trading|industries|corp|corporation|agency|agencies|hardware|store|solutions|limited|ltd|pvt ltd|llp|co\.?))\b',
        text,
        re.IGNORECASE
    )
    if from_m:
        cand = from_m.group(1).strip()
        cand_l = cand.lower()
        if not any(p in cand_l for p in IGNORE_UI_PHRASES) and not is_noise_or_chatter(cand_l):
            return cand.title()

    # 5. Line scan with strict indicator
    for line_clean in lines:
        lower = line_clean.lower()
        if any(tag in lower for tag in ("dealers in", "dealer of", "all kinds of", "stockist", "distributor", "authorized dealer", "dealers")):
            continue
        if any(p in lower for p in IGNORE_UI_PHRASES) or is_noise_or_chatter(lower):
            continue
        if "?" in line_clean:
            continue
        # Exclude pure wattages or quantities or simple messages
        if re.match(r'^\d+\s*(?:watt|w|pcs|pc|mtr|meter|m|nos|no)\b', lower):
            continue
        if any(ind in lower for ind in ("electricals", "electric", "enterprises", "traders", "industries", "pvt ltd", "ltd", "corporation", "hardware store")) and len(line_clean) < 60:
            clean = re.sub(r'^(?:company|business|firm|shop|org|name)[\s:-]+', '', line_clean, flags=re.IGNORECASE).strip()
            if len(clean) >= 3 and not any(p in clean.lower() for p in IGNORE_UI_PHRASES) and not is_noise_or_chatter(clean.lower()):
                return clean.title()
    return None

# ── 5. COMPLETE ADDRESS EXTRACTION ────────────────────────────────────────────
PIN_CODE_REGEX = re.compile(r'\b[1-9][0-9]{5}\b')
STREET_MARKERS = ("road", "rd", "street", "st", "lane", "gali", "marg", "bazaar", "bazar", "market", "floor", "nagar", "chowk", "complex", "sector", "plot", "park", "industrial area", "industrial areea", "building", "opp", "opposite", "near", "beside")
CITY_MARKERS = (
    "kolkata", "delhi", "mumbai", "chennai", "bangalore", "hyderabad", "pune", "ahmedabad", "jaipur", "patna",
    "bengal", "burrabazar", "patliputra", "pirangut", "baddi", "solan", "gurgaon", "gurugram", "noida",
    "greater noida", "faridabad", "ghaziabad", "surat", "vadodara", "rajkot", "indore", "bhopal", "nagpur",
    "nashik", "ludhiana", "amritsar", "jalandhar", "panipat", "karnal", "chandigarh", "mohali", "panchkula",
    "ranchi", "jamshedpur", "bhubaneswar", "cuttack", "guwahati", "raipur", "bilaspur", "kanpur", "lucknow", "agra"
)
STATE_MARKERS = (
    "himachal pradesh", "himachal", "punjab", "haryana", "uttar pradesh", "uttarakhand", "rajasthan",
    "gujarat", "maharashtra", "madhya pradesh", "west bengal", "bihar", "odisha", "jharkhand", "karnataka",
    "tamil nadu", "kerala", "andhra pradesh", "telangana", "assam", "chhattisgarh", "goa"
)

def extract_address(text: str) -> Optional[str]:
    if not text:
        return None
    matched_address_parts = []
    # Split by newlines first to preserve address lines like 'Shop No. 4, Gali No. 2, Industrial Area, Baddi'
    raw_lines = [s.strip() for s in text.splitlines() if s.strip()]
    lines = []
    for rl in raw_lines:
        # Avoid splitting common address abbreviations: 'No. ', 'Plot No. ', 'Shop No. ', 'Opp. '
        safe_rl = re.sub(r'\b(no|plot|shop|flat|opp|rd|st|dr)\.\s+', r'\1_DOT_ ', rl, flags=re.IGNORECASE)
        if ". " in safe_rl:
            lines.extend([part.replace('_DOT_', '.').strip() for part in safe_rl.split(". ") if part.strip()])
        else:
            lines.append(rl)
    
    # Check for 'from <Company> <Location>' pattern (e.g. 'I am kamal yadav from him Trading co Baddi Himachal Pradesh')
    intro_loc_m = re.search(
        r'\b(?:from|at)\s+(?:[A-Za-z0-9\s&]{2,40}?(?:trading co|trading company|trading corp|electricals|electric|enterprises|traders|trading|industries|corp|corporation|agency|agencies|hardware|store|solutions|limited|ltd|pvt ltd|llp|co\.?))\s+([A-Za-z\s,.-]{3,60})$',
        text,
        re.IGNORECASE
    )
    if intro_loc_m:
        cand_loc = intro_loc_m.group(1).strip()
        cand_l = cand_loc.lower()
        if any(sm in cand_l for sm in STATE_MARKERS) or any(cm in cand_l for cm in CITY_MARKERS):
            return cand_loc.title()

    for line in lines:
        lower = line.lower()
        # Reject questions, chat chatter, and UI noise immediately
        if "?" in line or any(p in lower for p in IGNORE_UI_PHRASES) or is_noise_or_chatter(lower):
            continue

        has_pin = bool(PIN_CODE_REGEX.search(line))
        has_street = any(sm in lower for sm in STREET_MARKERS)
        has_city = any(cm in lower for cm in CITY_MARKERS)
        has_state = any(st in lower for st in STATE_MARKERS)
        is_explicit_label = any(lower.startswith(prefix) for prefix in ("address:", "loc:", "location:", "addr:", "shop address:", "office address:", "delivery address:"))
        
        if is_explicit_label:
            clean = re.sub(r'^(?:address|location|loc|addr|shop address|office address|delivery address)[\s:-]+', '', line, flags=re.IGNORECASE).strip()
            if len(clean) >= 3 and "?" not in clean:
                from app.exports.data_sanitizer import clean_address
                cleaned_addr = clean_address(clean)
                if cleaned_addr:
                    return cleaned_addr

        # Legitimate address line: has pin code OR (has premise/street + city/state) OR (has city + state)
        if has_pin or (has_street and (has_city or has_state) and len(line) >= 8) or (has_city and has_state and len(line) >= 6):
            # Exclude lines that are purely product orders or short chatter
            if not any(pk in lower for pk in ("bulb", "mcb", "wire", "cable", "fan", "switch", "watt", "pcs")):
                clean_line = line.replace('\r', '').strip()
                if clean_line and clean_line not in matched_address_parts:
                    matched_address_parts.append(clean_line)

    if matched_address_parts:
        from app.exports.data_sanitizer import clean_address
        return clean_address(", ".join(matched_address_parts))
    return None

# ── 6. CONTACT PERSON NAME EXTRACTION ─────────────────────────────────────────
def extract_contact_name(text: str, profile_name: Optional[str] = None) -> Optional[str]:
    # 1. Visiting card / document designation pattern: Proprietor / Director / Owner / Partner
    if text:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for i, l in enumerate(lines):
            # Pattern A: "Proprietor: Kamal Yadav" or "Director - Kamal Yadav"
            desig_m = re.match(r'^(?:proprietor|prop\.?|partner|director|owner|manager|founder|authorized signatory)[\s:-]+([A-Za-z\s]{2,30})$', l, re.IGNORECASE)
            if desig_m:
                cand = desig_m.group(1).strip()
                if not is_noise_or_chatter(cand) and not any(p in cand.lower() for p in IGNORE_UI_PHRASES):
                    return cand.title()
            
            # Pattern B: Line itself is "Proprietor" or "Owner", preceding or succeeding line is Name
            if re.match(r'^(?:proprietor|prop\.?|partner|director|owner|manager|founder|authorized signatory)$', l, re.IGNORECASE):
                if i > 0:
                    prev_l = lines[i-1].strip()
                    if re.match(r'^[A-Za-z\s.]{2,30}$', prev_l) and not any(k in prev_l.lower() for k in ('dealers', 'trading', 'company', 'ltd', 'gst', 'email', 'phone', 'address', 'goods', 'cables', 'wires', 'enterprises', 'industries', 'electricals', 'co.')):
                        return prev_l.title()
                if i < len(lines) - 1:
                    next_l = lines[i+1].strip()
                    if re.match(r'^[A-Za-z\s.]{2,30}$', next_l) and not any(k in next_l.lower() for k in ('dealers', 'trading', 'company', 'ltd', 'gst', 'email', 'phone', 'address', 'goods', 'cables', 'wires', 'enterprises', 'industries', 'electricals', 'co.')):
                        return next_l.title()

            # Pattern C: "Mr. Kamal Yadav", "Er. Kamal Yadav", "Shri Kamal Yadav"
            title_m = re.search(r'\b(?:mr\.?|shri|er\.?|dr\.?)\s+([A-Za-z\s]{2,30})\b', l, re.IGNORECASE)
            if title_m:
                cand = title_m.group(1).strip()
                if not is_noise_or_chatter(cand) and not any(p in cand.lower() for p in IGNORE_UI_PHRASES):
                    return cand.title()

        # Explicit pattern: I am <Name> from ... or My name is <Name> or Contact Person: <Name>
        m = re.search(r'\b(?:my name is|i am|this is|contact person|contact person name|contact name)[\s:-]+([A-Za-z\s]{2,30})(?:\s+from|\s*,|\s*$|\s*\n)', text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            cand_l = candidate.lower()
            if cand_l not in ("here", "interested", "need", "we", "hi", "sir") and not any(p in cand_l for p in IGNORE_UI_PHRASES) and not is_noise_or_chatter(cand_l):
                return candidate.title()

    # 2. Check if profile name is provided from WhatsApp profile and is a valid personal name
    if profile_name:
        clean_p = profile_name.strip()
        lower_p = clean_p.lower()
        if not any(p in lower_p for p in IGNORE_UI_PHRASES) and not is_noise_or_chatter(lower_p):
            if len(clean_p) >= 2 and len(clean_p) <= 30 and not clean_p.replace('+', '').replace(' ', '').isdigit():
                return clean_p.title()
        
    return None
