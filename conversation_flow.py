"""
conversation_flow.py — Strict Turn-Based 3-Step WhatsApp Flow.

CORE PRINCIPLE:
  The bot NEVER sends a follow-up response without the customer explicitly replying first!
  - Step 1: Customer messages first → Bot replies Step 1 (Requirements & sample picture request)
            → Bot WAITS strictly for customer reply.
  - Step 2: Customer replies with requirements (can send multiple texts/photos)
            → 5s pause after customer stops typing → Bot replies Step 2 (Business & GST request)
            → Bot WAITS strictly for customer reply.
  - Step 3: Customer replies with business/GST details
            → 5s pause after customer stops typing → Bot replies Step 3 (Final confirmation: connect soon)
            → Completed!
  - After Step 3: Bot NEVER sends any more automated replies. Only logs customer chats to Excel.
"""

import json
import os
import time
from threading import Lock

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "conversation_states.json")
_state_lock = Lock()

SESSION_TIMEOUT_SECONDS = 86400  # 24 hours

STEP_MESSAGES = {
    1: (
        "🙏 *Thank you for contacting us!*\n\n"
        "Please share your *requirements* with quantity & details.\n\n"
        "📎 If possible, please also share a *sample picture* so we can understand better."
    ),
    2: (
        "✅ *Thank you for sharing your requirements!*\n\n"
        "To prepare your *quotation*, please share your:\n"
        "🏢 *Business Name & Address*\n"
        "📋 *GST Number* (if applicable)\n"
        "📞 *Contact Person Name*"
    ),
    3: (
        "🙏 *Thanks for sharing all the details!*\n\n"
        "Our team will review your requirements and *connect with you as soon as possible.*\n\n"
        "Have a great day! 😊"
    ),
}


def get_step_message(step: int) -> str:
    """Returns the pre-defined template message for the specified step."""
    return STEP_MESSAGES.get(step, "")


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
    """Return customer state dict: {'step': int, 'waiting_for_customer': bool, 'updated_at': int}"""
    with _state_lock:
        states = _load_states()
        now = int(time.time())
        state = states.get(sender_phone, {
            "step": 0,
            "waiting_for_customer": False,
            "updated_at": now,
        })

        # Auto-reset after 24 hours of inactivity
        if state.get("step", 0) >= 3 and (now - state.get("updated_at", now)) > SESSION_TIMEOUT_SECONDS:
            state = {"step": 0, "waiting_for_customer": False, "updated_at": now}
            states[sender_phone] = state
            _save_states(states)

        return state


def register_customer_incoming_message(sender_phone: str, message_text: str = "") -> tuple[int, bool]:
    """
    Called whenever a customer sends a message.
    Unlocks waiting_for_customer flag because customer has actively replied!
    If customer says 'Hi', 'Hello', or sends a greeting after completion,
    automatically restarts the 3-step intake.

    Returns:
        (current_step, can_advance_to_next_step)
    """
    clean = (message_text or "").strip().lower()
    is_greeting = clean in (
        "hi", "hello", "hey", "hii", "helo", "start", "restart", "reset",
        "good morning", "good afternoon", "good evening", "namaste"
    )

    with _state_lock:
        states = _load_states()
        now = int(time.time())
        state = states.get(sender_phone, {
            "step": 0,
            "waiting_for_customer": False,
            "updated_at": now,
        })

        step = state.get("step", 0)

        # If customer already completed all 3 steps:
        if step >= 3:
            # If they say "Hi" or send a greeting, restart the flow!
            if is_greeting:
                print(f"[FLOW] Customer {sender_phone} said '{clean}' after completion. Restarting flow!")
                state = {"step": 0, "waiting_for_customer": False, "updated_at": now}
                states[sender_phone] = state
                _save_states(states)
                return (0, True)

            # If more than 1 hour passed since completion, restart for new inquiry!
            if (now - state.get("updated_at", now)) > 3600:
                print(f"[FLOW] Customer {sender_phone} sent new message after 1 hour. Restarting flow!")
                state = {"step": 0, "waiting_for_customer": False, "updated_at": now}
                states[sender_phone] = state
                _save_states(states)
                return (0, True)

            # Otherwise, quietly log further comments to Excel without repeating bot replies
            state["updated_at"] = now
            states[sender_phone] = state
            _save_states(states)
            return (step, False)

        # Customer has actively messaged: clear waiting flag
        state["waiting_for_customer"] = False
        state["updated_at"] = now
        states[sender_phone] = state
        _save_states(states)

        return (step, True)


def mark_bot_reply_sent(sender_phone: str, step_sent: int) -> None:
    """
    Called after bot successfully sends a step reply to customer.
    Advances step and sets waiting_for_customer=True so bot NEVER replies
    again until the customer sends a new message!
    """
    with _state_lock:
        states = _load_states()
        now = int(time.time())
        states[sender_phone] = {
            "step": step_sent,
            "waiting_for_customer": (step_sent < 3),  # Step 3 is final, so not waiting
            "updated_at": now,
        }
        _save_states(states)
        print(f"[FLOW] Customer {sender_phone} advanced to Step {step_sent}. Waiting for customer: {step_sent < 3}")


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
