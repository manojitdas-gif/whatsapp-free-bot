"""
templates.py — Exactly three approved primary customer response templates.
Verbatim text matching Master Prompt specifications.
"""

RESPONSE_1 = (
    "🙏 Thank you for sharing all your details!\n"
    "Our team will carefully review your requirements and contact you as soon as possible with the best quotation.\n"
    "Have a great day! 😊"
)

RESPONSE_2 = (
    "🙏 Thank you for contacting us!\n"
    "Please share your product requirements with:\n"
    "📦 Product name & description\n"
    "🔢 Quantity required\n"
    "📐 Size / specifications\n"
    "📎 You can also share a sample photo or document for better understanding."
)

RESPONSE_3 = (
    "✅ Thank you for sharing your requirements!\n"
    "To prepare your quotation, please share your:\n"
    "🏢 Business / Company Name\n"
    "📋 GST Number (if applicable)\n"
    "📍 Complete Business Address\n"
    "👤 Contact Person Name"
)

RESPONSE_POST_COMPLETION = "Hi! How can we help you? 😊"

def get_response_template(response_type: str) -> str:
    mapping = {
        "RESPONSE_1": RESPONSE_1,
        "RESPONSE_2": RESPONSE_2,
        "RESPONSE_3": RESPONSE_3,
        "RESPONSE_POST_COMPLETION": RESPONSE_POST_COMPLETION,
    }
    return mapping.get(response_type, RESPONSE_2)
