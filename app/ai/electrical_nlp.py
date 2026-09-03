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

def extract_company_name(text: str) -> Optional[str]:
    if not text:
        return None
    
    # 1. Explicit label has highest priority
    for line in text.splitlines():
        line_clean = line.strip()
        lower = line_clean.lower()
        if any(lower.startswith(prefix) for prefix in ("company:", "business:", "firm:", "shop:", "company name:", "firm name:")):
            clean = re.sub(r'^(?:company name|firm name|company|business|firm|shop)[\s:-]+', '', line_clean, flags=re.IGNORECASE).strip()
            if len(clean) >= 2:
                return clean.title()

    # 2. Pattern: from <Company> or at <Company>
    from_m = re.search(
        r'\b(?:from|at)\s+([A-Za-z0-9\s&]+?(?:electricals|electric|enterprises|traders|trading|industries|corp|corporation|agency|agencies|co|company|hardware|store|shop|solutions|limited|ltd|pvt ltd|llp))\b',
        text,
        re.IGNORECASE
    )
    if from_m:
        return from_m.group(1).strip().title()

    # 3. Line scan with indicator
    for line in text.splitlines():
        line_clean = line.strip()
        lower = line_clean.lower()
        if any(ind in lower for ind in COMPANY_INDICATORS) and len(line_clean) < 80:
            # Exclude lines that are clearly product orders
            if any(p in lower for p in ("bulb", "mcb", "wire", "cable", "quotation for", "invoice")):
                continue
            clean = re.sub(r'^(?:company|business|firm|shop|org|name)[\s:-]+', '', line_clean, flags=re.IGNORECASE).strip()
            if len(clean) >= 3:
                return clean.title()
    return None

# ── 5. COMPLETE ADDRESS EXTRACTION ────────────────────────────────────────────
PIN_CODE_REGEX = re.compile(r'\b[1-9][0-9]{5}\b')
ADDRESS_KEYWORDS = ["road", "street", "lane", "bazaar", "bazar", "market", "floor", "near", "opposite", "opp", "beside", "dist", "district", "city", "state", "pin", "kolkata", "delhi", "mumbai", "chennai", "bangalore", "hyderabad", "pune", "ahmedabad", "jaipur", "patna", "bengal", "up", "bihar", "odisha"]

def extract_address(text: str) -> Optional[str]:
    if not text:
        return None
    matched_address_parts = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    for line in lines:
        lower = line.lower()
        has_pin = bool(PIN_CODE_REGEX.search(line))
        has_addr_word = any(kw in lower for kw in ADDRESS_KEYWORDS)
        is_explicit_label = any(lower.startswith(prefix) for prefix in ("address:", "loc:", "location:", "addr:", "shop address:"))
        
        if is_explicit_label:
            clean = re.sub(r'^(?:address|location|loc|addr|shop address)[\s:-]+', '', line, flags=re.IGNORECASE).strip()
            return clean

        if has_pin or (has_addr_word and len(line) > 8):
            # Exclude lines that are clearly product lines
            if not any(pk in lower for pk in ("bulb", "mcb", "wire", "cable", "fan", "switch")):
                matched_address_parts.append(line)

    if matched_address_parts:
        return ", ".join(matched_address_parts)
    return None

# ── 6. CONTACT PERSON NAME EXTRACTION ─────────────────────────────────────────
def extract_contact_name(text: str, profile_name: Optional[str] = None) -> Optional[str]:
    if not text:
        return profile_name or None
    
    # 1. Pattern: I am <Name> from ... or My name is <Name>
    m = re.search(r'\b(?:my name is|i am|this is|contact person|contact|name is)[\s:-]+([A-Za-z]{2,20})(?:\s+from|\s*,|\s*$|\s*\n)', text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() not in ("here", "interested", "need", "we", "hi"):
            return candidate.title()

    m2 = re.search(r'\b(?:my name is|i am|this is|contact person|contact|name is)[\s:-]+([A-Za-z\s]{2,25})\b', text, re.IGNORECASE)
    if m2:
        candidate = m2.group(1).strip()
        if candidate.lower() not in ("here", "interested", "need"):
            return candidate.title()
        
    return profile_name or None
