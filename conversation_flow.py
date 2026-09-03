"""
conversation_flow.py — Strict 3-Step WhatsApp Bot Flow with Validation.

FLOW:
  Step 0 → Customer sends ANY first message
           → Bot waits 2s → sends Step 1 (Ask for requirements + sample photo)

  Step 1 → Customer shares requirements/documents/photos (anything detailed)
           → Bot detects customer has STOPPED typing (2s silence)
           → Validates: did customer share actual requirements?
             ✅ YES → sends Step 2 (Ask business name, GST, contact)
             ❌ NO  → sends polite re-request: "Please share product requirements"

  Step 2 → Customer shares business details (name, GST, address, contact)
           → Bot detects customer has STOPPED typing (2s silence)
           → Validates: did customer share business details?
             ✅ YES → sends Step 3 (Thank you, team will connect soon)
             ❌ NO  → sends polite re-request: "Please share your business details"

  Step 3 → DONE. Bot only logs silently from here. No more automated replies.
           → If customer sends NEW greeting later, restart from Step 0.
"""

import json
import os
import re
import time
from threading import Lock

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "conversation_states.json")
_state_lock = Lock()

# ──────────────────────────────────────────────────────────────────────────────
# MESSAGES
# ──────────────────────────────────────────────────────────────────────────────

STEP_MESSAGES = {
    1: (
        "🙏 *Thank you for contacting us!*\n\n"
        "Please share your *product requirements* with:\n"
        "📦 Product name & description\n"
        "🔢 Quantity required\n"
        "📐 Size / specifications\n\n"
        "📎 You can also share a *sample photo or document* for better understanding."
    ),
    2: (
        "✅ *Thank you for sharing your requirements!*\n\n"
        "To prepare your *quotation*, please share your:\n"
        "🏢 *Business / Company Name*\n"
        "📋 *GST Number* (if applicable)\n"
        "📍 *Complete Business Address*\n"
        "👤 *Contact Person Name*"
    ),
    3: (
        "🙏 *Thank you for sharing all your details!*\n\n"
        "Our team will carefully review your requirements and "
        "*contact you as soon as possible* with the best quotation.\n\n"
        "Have a great day! 😊"
    ),
}

# Validation re-request messages (sent when customer skips relevant info)
RETRY_MESSAGES = {
    1: (
        "📋 *Please share your product requirements!*\n\n"
        "To prepare your quotation, I need:\n"
        "📦 *Product name* and description\n"
        "🔢 *Quantity* required\n"
        "📐 *Size / specifications*\n\n"
        "You can also share a *sample photo or document*. 📎"
    ),
    2: (
        "🏢 *Please share your business details!*\n\n"
        "To complete your quotation, I need:\n"
        "🏢 *Business / Company Name*\n"
        "📋 *GST Number* (if applicable)\n"
        "📍 *Complete Business Address*\n"
        "👤 *Contact Person Name*"
    ),
}


def get_step_message(step: int) -> str:
    return STEP_MESSAGES.get(step, "")


def get_retry_message(step: int) -> str:
    return RETRY_MESSAGES.get(step, "")


# ──────────────────────────────────────────────────────────────────────────────
# VALIDATION — Is the customer's reply relevant to the current step?
# ──────────────────────────────────────────────────────────────────────────────

# Short chatter words that are NOT relevant data
_CHATTER = {
    "hi", "hello", "hey", "hii", "helo", "ok", "okay", "k", "yes", "no",
    "fine", "good", "sure", "thanks", "thank you", "done", "alright",
    "start", "restart", "reset", "namaste", "good morning", "good afternoon",
    "good evening", "haan", "ha", "ji", "ji ha", "noted",
}

def _is_chatter_only(text: str) -> bool:
    """Returns True if the message is just a greeting/filler with no real data."""
    clean = text.strip().lower()
    # Remove punctuation for comparison
    clean_stripped = re.sub(r'[^\w\s]', '', clean).strip()
    words = set(clean_stripped.split())
    if not words:
        return True
    return words.issubset(_CHATTER | {w for s in _CHATTER for w in s.split()})


def validate_step1_reply(message_text: str, has_image: bool = False, has_document: bool = False) -> bool:
    """
    Step 1 validation: Did customer share actual product requirements?
    Accept if:
      - Image or document attached (always accept)
      - Text contains product keywords, numbers, quantities, sizes
      - Message is long enough (≥ 10 chars and not just chatter)
    """
    if has_image or has_document:
        return True

    text = (message_text or "").strip()
    if len(text) < 5:
        return False

    if _is_chatter_only(text):
        return False

    # If message has numbers (quantities/sizes) it's likely a requirement
    if re.search(r'\d', text):
        return True

    # If message has product/requirement keywords
    product_keywords = [
        'box', 'bag', 'carton', 'packet', 'bottle', 'container', 'drum', 'jar',
        'roll', 'sheet', 'piece', 'pcs', 'kg', 'gram', 'liter', 'meter', 'feet',
        'size', 'color', 'colour', 'print', 'design', 'sample', 'spec', 'specification',
        'material', 'product', 'item', 'need', 'want', 'require', 'order',
        'honeywell', 'corrugated', 'duplex', 'kraft', 'plastic', 'paper',
        'foam', 'bubble', 'tape', 'label', 'sticker',
    ]
    text_lower = text.lower()
    if any(kw in text_lower for kw in product_keywords):
        return True

    # If message is reasonably long and not chatter, accept it
    if len(text) >= 15:
        return True

    return False


def validate_step2_reply(message_text: str, has_image: bool = False, has_document: bool = False) -> bool:
    """
    Step 2 validation: Did customer share business details?
    Accept if text contains business name indicators, GST, address, or contact info.
    """
    if has_image or has_document:
        return True

    text = (message_text or "").strip()
    if len(text) < 5:
        return False

    if _is_chatter_only(text):
        return False

    text_lower = text.lower()

    # GST pattern
    if re.search(r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}\b', text, re.IGNORECASE):
        return True

    # Phone number
    if re.search(r'\b[6-9]\d{9}\b', text):
        return True

    # Email
    if re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b', text):
        return True

    # Business/address keywords
    business_keywords = [
        'enterprise', 'pvt', 'ltd', 'industries', 'trading', 'traders', 'company',
        'co.', 'corp', 'firm', 'agency', 'agencies', 'shop', 'store', 'mart',
        'road', 'street', 'lane', 'nagar', 'colony', 'sector', 'block', 'district',
        'kolkata', 'mumbai', 'delhi', 'bangalore', 'chennai', 'pune', 'hyderabad',
        'howrah', 'west bengal', 'maharashtra', 'gujarat', 'gst', 'name',
    ]
    if any(kw in text_lower for kw in business_keywords):
        return True

    # Pin code
    if re.search(r'\b\d{6}\b', text):
        return True

    # Long enough message with mixed content is likely business details
    if len(text) >= 20:
        return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# STATE MACHINE
# ──────────────────────────────────────────────────────────────────────────────

def _load_states() -> dict:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                normalized = {}
                for k, v in raw.items():
                    if isinstance(v, dict):
                        normalized[k] = v
                    else:
                        normalized[k] = {
                            "step": int(v),
                            "waiting_for_customer": False,
                            "last_customer_msg_time": 0,
                            "updated_at": int(time.time()),
                        }
                return normalized
        except Exception:
            return {}
    return {}


def _save_states(states: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(states, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_customer_state(sender_phone: str) -> dict:
    """Return full customer state dict."""
    with _state_lock:
        states = _load_states()
        now = int(time.time())
        return states.get(sender_phone, {
            "step": 0,
            "waiting_for_customer": False,
            "last_customer_msg_time": 0,
            "updated_at": now,
        })


def record_customer_message_time(sender_phone: str) -> None:
    """
    Called every time a new customer message arrives.
    Updates last_customer_msg_time so we can detect when they stop typing.
    """
    with _state_lock:
        states = _load_states()
        now = int(time.time())
        state = states.get(sender_phone, {
            "step": 0,
            "waiting_for_customer": False,
            "last_customer_msg_time": 0,
            "updated_at": now,
        })
        state["last_customer_msg_time"] = now
        state["waiting_for_customer"] = False
        state["updated_at"] = now
        states[sender_phone] = state
        _save_states(states)


def has_customer_stopped_typing(sender_phone: str, silence_seconds: float = 2.0) -> bool:
    """
    Returns True if the customer has been silent for at least `silence_seconds`
    since their last message (i.e., they have stopped typing / sending).
    """
    with _state_lock:
        states = _load_states()
        state = states.get(sender_phone, {})
        last_msg_time = state.get("last_customer_msg_time", 0)
        if last_msg_time == 0:
            return False
        return (time.time() - last_msg_time) >= silence_seconds


def register_customer_incoming_message(sender_phone: str, message_text: str = "") -> tuple:
    """
    Called whenever a customer sends a message.

    Returns:
        (current_step, can_advance_now)
        - current_step: the step the customer is currently at
        - can_advance_now: True if a bot reply should be sent for this step
    """
    clean = (message_text or "").strip().lower()
    is_greeting = clean in (
        "hi", "hello", "hey", "hii", "helo", "start", "restart", "reset",
        "good morning", "good afternoon", "good evening", "namaste",
        "haan", "ha", "ji", "ji ha",
    )

    with _state_lock:
        states = _load_states()
        now = int(time.time())
        state = states.get(sender_phone, {
            "step": 0,
            "waiting_for_customer": False,
            "last_customer_msg_time": 0,
            "updated_at": now,
        })

        step = state.get("step", 0)

        # Reset completed customers on new greeting or after 3+ hours
        if step >= 3:
            if is_greeting or (now - state.get("updated_at", now)) > 10800:
                print(f"[FLOW] Customer {sender_phone} restarted flow.")
                state = {"step": 0, "waiting_for_customer": False,
                         "last_customer_msg_time": now, "updated_at": now}
                states[sender_phone] = state
                _save_states(states)
                return (0, True)
            # Just log silently
            state["updated_at"] = now
            states[sender_phone] = state
            _save_states(states)
            return (step, False)

        # Update last message time (for stop-typing detection)
        state["last_customer_msg_time"] = now
        state["waiting_for_customer"] = False
        state["updated_at"] = now
        states[sender_phone] = state
        _save_states(states)

        return (step, True)


def mark_bot_reply_sent(sender_phone: str, step_sent: int) -> None:
    """
    Called after bot successfully sends a step reply.
    Advances step and sets waiting_for_customer=True.
    """
    with _state_lock:
        states = _load_states()
        now = int(time.time())
        states[sender_phone] = {
            "step": step_sent,
            "waiting_for_customer": (step_sent < 3),
            "last_customer_msg_time": 0,  # Reset: wait for next customer message
            "updated_at": now,
        }
        _save_states(states)
        print(f"[FLOW] Customer {sender_phone} → Step {step_sent} delivered. "
              f"Waiting for customer reply: {step_sent < 3}")


def reset_customer(sender_phone: str) -> None:
    with _state_lock:
        states = _load_states()
        if sender_phone in states:
            del states[sender_phone]
        _save_states(states)
    print(f"[FLOW] Reset customer {sender_phone}")


def reset_all_states() -> None:
    with _state_lock:
        _save_states({})
    print("[FLOW] All conversation states reset.")
