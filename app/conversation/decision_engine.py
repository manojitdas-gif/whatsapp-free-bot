"""
decision_engine.py — Decides which primary response template to send based on information completeness.
"""

from typing import Tuple, Dict, Any
from app.schemas.extraction import ExtractionResult
from app.config import settings

def evaluate_conversation_completeness(extraction: ExtractionResult, has_media: bool = False) -> Tuple[str, Dict[str, Any]]:
    """
    Evaluates extracted fields against business categories:
    Category A: Requirement Information (Products, quantities, specifications OR attached media)
    Category B: Business & Customer Details (Company name, complete address, contact person)
    
    Returns:
        (response_type: 'RESPONSE_1' | 'RESPONSE_2' | 'RESPONSE_3', audit_meta: dict)
    """
    has_products = bool(extraction.product_requirements or extraction.raw_requirement_text or has_media)
    
    has_company = bool(extraction.company_business_name and len(extraction.company_business_name.strip()) >= 2)
    has_address = bool(extraction.complete_address and len(extraction.complete_address.strip()) >= 5)
    # Contact person can be from profile/chat, or company name fallback
    has_contact = bool((extraction.contact_person_name and len(extraction.contact_person_name.strip()) >= 2) or has_company)
    
    # GST rule
    gst_val = (extraction.gst_number or "").strip()
    is_gst_valid = bool(gst_val)
    if not settings.REQUIRE_GST_MANDATORY:
        # GST is "if applicable"
        has_gst = True
    else:
        has_gst = is_gst_valid or (gst_val.lower() in ("not applicable", "na", "n/a", "no", "retail"))

    has_business_details = has_company and has_address and has_contact and has_gst

    missing = []
    if not has_products:
        missing.append("product_requirements")
    if not has_company:
        missing.append("company_name")
    if not has_address:
        missing.append("complete_address")
    if not has_contact:
        missing.append("contact_person_name")
    if settings.REQUIRE_GST_MANDATORY and not has_gst:
        missing.append("gst_number")

    # Decision Matrix:
    # 1. If both Requirements AND Business details available:
    if has_products and has_business_details:
        response_type = "RESPONSE_1"
    # 2. If product requirements are missing:
    elif not has_products:
        response_type = "RESPONSE_2"
    # 3. If product requirements are present, but business details are missing:
    else:
        response_type = "RESPONSE_3"

    audit_meta = {
        "has_products": has_products,
        "has_business_details": has_business_details,
        "has_company": has_company,
        "has_address": has_address,
        "has_contact": has_contact,
        "has_gst": has_gst,
        "missing_fields": missing,
        "selected_response": response_type
    }

    return response_type, audit_meta
