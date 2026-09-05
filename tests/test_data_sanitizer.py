"""
test_data_sanitizer.py — Comprehensive tests for 100% pure 9-column data formatting.
"""

from app.exports.data_sanitizer import (
    clean_first_contact_date,
    clean_last_contact_date,
    clean_contact_name,
    clean_company_name,
    clean_phone_number,
    clean_email,
    clean_gst_number,
    clean_address,
    clean_requirements_summary,
    sanitize_lead_dict
)

def test_clean_contact_name():
    assert clean_contact_name("Kamal Yadav") == "Kamal Yadav"
    assert clean_contact_name("Mr. Sunil Sharma") == "Sunil Sharma"
    assert clean_contact_name("Proprietor: Ramesh Gupta") == "Ramesh Gupta"
    # Fallback to company when name is generic
    assert clean_contact_name("Customer", company="Him Trading Co") == "Him Trading Co"
    assert clean_contact_name("None", company="Sharma Electricals") == "Sharma Electricals"
    assert clean_contact_name("+91 9988776655", company="Apex Traders") == "Apex Traders"

def test_clean_company_name():
    assert clean_company_name("M/s. Him Trading Co.") == "Him Trading Co"
    assert clean_company_name("M/S Gupta Electricals") == "Gupta Electricals"
    assert clean_company_name("Company: Apex Industries") == "Apex Industries"
    # Disallow taglines
    assert clean_company_name("Dealers in Electrical Goods, Cables & Wires") == ""
    assert clean_company_name("Authorized Dealer of Polycab") == ""

def test_clean_gst_number():
    assert clean_gst_number("02ABCDE1234F1Z5") == "02ABCDE1234F1Z5"
    assert clean_gst_number("GSTIN: 19ABCDE1234F1Z5") == "19ABCDE1234F1Z5"
    assert clean_gst_number("no gst") == "Not Applicable"
    assert clean_gst_number("retail customer") == "Not Applicable"
    assert clean_gst_number("invalid-gst-123") == ""

def test_clean_address():
    # Removes leaked GSTIN, email, and labels
    raw = "19ABCDE1234F1Z5, 12 Park Street, Kolkata 700016, email: gupta@gmail.com"
    assert clean_address(raw) == "12 Park Street, Kolkata 700016"

    raw2 = "GSTIN: 02ABCDE1234F1Z5, Plot No. 14, Phase 1, Industrial Area, Baddi, Himachal Pradesh - 173205"
    assert clean_address(raw2) == "Plot No. 14, Phase 1, Industrial Area, Baddi, Himachal Pradesh - 173205"

    raw3 = "19AABCS1429B1Z8, Burrabazar Kolkata"
    assert clean_address(raw3) == "Burrabazar Kolkata"

def test_clean_requirements_summary():
    # Purges chatter and rate requests
    raw1 = "Product Image Attached (Rate and availability requested)"
    assert clean_requirements_summary(raw1) == "Product Image Attached"

    raw2 = "• 9W LED Bulb - 100 pcs\nPlease sir rate and availability"
    assert clean_requirements_summary(raw2) == "• 9W LED Bulb - 100 pcs"

    # Purges dealer taglines
    raw3 = "Product: Wire\nDescription: Dealers in Electrical Goods, Cables & Wires"
    assert clean_requirements_summary(raw3) == "• Wire"

def test_sanitize_lead_dict_complete():
    lead = {
        "first_contact_date": "2026-09-05 10:00:00",
        "last_contact_date": "2026-09-05 14:00:00",
        "contact_person_name": "Mr. Kamal Yadav",
        "whatsapp_number": "917973904816",
        "email_id": "himtradingbaddi@gmail.com.",
        "company_name": "M/s. Him Trading Co.",
        "gst_number": "02ABCDE1234F1Z5",
        "complete_address": "GST: 02ABCDE1234F1Z5, Plot No. 14, Phase 1, Industrial Area, Baddi, Himachal Pradesh - 173205",
        "requirements_summary": "• 9W LED Bulb - 100 pcs\nRate and availability requested"
    }
    clean = sanitize_lead_dict(lead)
    assert clean["first_contact_date"] == "2026-09-05"
    assert clean["last_contact_date"] == "2026-09-05"
    assert clean["contact_person_name"] == "Kamal Yadav"
    assert clean["whatsapp_number"] == "+91 79739 04816"
    assert clean["email_id"] == "himtradingbaddi@gmail.com"
    assert clean["company_name"] == "Him Trading Co"
    assert clean["gst_number"] == "02ABCDE1234F1Z5"
    assert clean["complete_address"] == "Plot No. 14, Phase 1, Industrial Area, Baddi, Himachal Pradesh - 173205"
    assert clean["requirements_summary"] == "• 9W LED Bulb - 100 pcs"
