"""
extractor.py — Multi-message conversation analyzer and information merger.
Analyzes the entire conversation history, merges fields deterministically, and produces
a verified ExtractionResult.
"""

from typing import List, Optional
from app.schemas.extraction import ExtractionResult, ProductItem
from app.ai.electrical_nlp import (
    extract_gst,
    extract_email,
    extract_company_name,
    extract_address,
    extract_contact_name,
    extract_electrical_products
)

def analyze_conversation(
    messages_history: List[str],
    attachment_texts: Optional[List[str]] = None,
    profile_name: Optional[str] = None
) -> ExtractionResult:
    """
    Combines all historical conversation messages and attachments,
    extracts only supported fields with zero hallucination, and returns ExtractionResult.
    """
    combined_texts = list(messages_history or [])
    if attachment_texts:
        combined_texts.extend(attachment_texts)

    full_conversation_text = "\n".join(combined_texts)
    
    # Extract entities
    contact_name = extract_contact_name(full_conversation_text, profile_name=profile_name)
    email = extract_email(full_conversation_text)
    company = extract_company_name(full_conversation_text)
    gst = extract_gst(full_conversation_text)
    address = extract_address(full_conversation_text)
    products = extract_electrical_products(full_conversation_text)

    # Raw requirement text fallback if products keyword list didn't match structured items
    raw_req = None
    if not products:
        for msg in combined_texts:
            clean = msg.strip()
            lower = clean.lower()
            if "?" in clean:
                continue
            # Skip introductions, address lines, business details, bot prompts, questions
            if any(k in lower for k in ("gst", "email", "address", "company", "my name is", "i am", "street", "road", "lane", "pin", "kolkata", "bengal", "thank you", "please share", "quotation", "regret", "costly", "delivery is", "chaheye", "kardo")):
                continue
            if any(w in lower for w in ("need", "want", "require", "send", "rate", "price", "order", "item", "bulb", "fan", "wire", "cable", "switch", "mcb", "watt", "pcs", "nos")):
                raw_req = clean
                break

    result = ExtractionResult(
        contact_person_name=contact_name,
        email_id=email,
        company_business_name=company,
        gst_number=gst,
        complete_address=address,
        product_requirements=products,
        raw_requirement_text=raw_req
    )

    return result
