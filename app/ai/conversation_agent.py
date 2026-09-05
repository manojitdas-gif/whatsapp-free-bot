"""
conversation_agent.py — Intelligent AI Decision & History Agent.
Analyzes full chronological WhatsApp conversation history before taking any decision.
Enforces strictly ONE bot flow per phone number in a lifetime.
"""

import os
import re
import sqlite3
import logging
from typing import List, Dict, Any, Optional
import requests

from app.config import settings
from app.ai.extractor import analyze_conversation
from app.schemas.extraction import ExtractionResult
from app.conversation.templates import RESPONSE_1, RESPONSE_2, RESPONSE_3, get_response_template

logger = logging.getLogger(__name__)

def init_flow_guard_db():
    try:
        os.makedirs(settings.DATA_DIR, exist_ok=True)
        db_path = os.path.join(settings.DATA_DIR, "whatsapp_production.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS phone_flow_guard (
                phone VARCHAR(32) PRIMARY KEY,
                response_1_sent BOOLEAN DEFAULT 0,
                response_2_sent BOOLEAN DEFAULT 0,
                response_3_sent BOOLEAN DEFAULT 0,
                is_completed BOOLEAN DEFAULT 0,
                last_response VARCHAR(32),
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[AGENT] Could not init phone_flow_guard: {e}")

init_flow_guard_db()

FOLLOWUP_KEYWORDS = (
    "rate", "price", "availability", "rate and availability", "plz send rate", "please send rate",
    "best price", "update", "status", "kya hua", "kab milega", "bhejo", "batao", "calling",
    "missed voice call", "missed call", "urgent", "please check", "sir please"
)

def is_conversational_followup(text: str) -> bool:
    if not text:
        return False
    lower = text.lower().strip()
    if any(fk in lower for fk in FOLLOWUP_KEYWORDS):
        has_real_product = any(pw in lower for pw in (
            "bulb", "wire", "cable", "switch", "socket", "mcb", "pipe", "fan", "conduit", "meter"
        ))
        has_real_unit = bool(re.search(r'\b\d+\s*(?:pcs|pc|nos|no|meter|mtr|watt|w)\b', lower))
        if not (has_real_product or has_real_unit):
            return True
    return False

def get_phone_guard_state(phone_digits: str) -> Dict[str, Any]:
    try:
        db_path = os.path.join(settings.DATA_DIR, "whatsapp_production.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT response_1_sent, response_2_sent, response_3_sent, is_completed, last_response FROM phone_flow_guard WHERE phone = ?", (phone_digits,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "response_1_sent": bool(row[0]),
                "response_2_sent": bool(row[1]),
                "response_3_sent": bool(row[2]),
                "is_completed": bool(row[3]),
                "last_response": row[4]
            }
    except Exception as e:
        logger.warning(f"[AGENT] Error reading phone_flow_guard: {e}")
    return {
        "response_1_sent": False,
        "response_2_sent": False,
        "response_3_sent": False,
        "is_completed": False,
        "last_response": None
    }

def update_phone_guard_state(phone_digits: str, sent_response: str):
    try:
        db_path = os.path.join(settings.DATA_DIR, "whatsapp_production.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        is_comp = (sent_response == "RESPONSE_1")
        r1 = 1 if sent_response == "RESPONSE_1" else 0
        r2 = 1 if sent_response == "RESPONSE_2" else 0
        r3 = 1 if sent_response == "RESPONSE_3" else 0

        cur.execute('''
            INSERT INTO phone_flow_guard (phone, response_1_sent, response_2_sent, response_3_sent, is_completed, last_response, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
                response_1_sent = MAX(response_1_sent, excluded.response_1_sent),
                response_2_sent = MAX(response_2_sent, excluded.response_2_sent),
                response_3_sent = MAX(response_3_sent, excluded.response_3_sent),
                is_completed = MAX(is_completed, excluded.is_completed),
                last_response = excluded.last_response,
                updated_at = CURRENT_TIMESTAMP
        ''', (phone_digits, r1, r2, r3, 1 if is_comp else 0, sent_response))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[AGENT] Error updating phone_flow_guard: {e}")

def fetch_chat_history_from_gateway(phone: str, count: int = 25) -> List[Dict[str, Any]]:
    """Fetches live conversation history from Green API."""
    inst_id = settings.GATEWAY_INSTANCE_ID
    token = settings.GATEWAY_API_TOKEN
    base_url = settings.GATEWAY_API_URL
    if not inst_id or not token:
        return []

    clean_p = re.sub(r'[^0-9]', '', phone)
    chat_id = f"{clean_p}@c.us"
    url = f"{base_url}/waInstance{inst_id}/getChatHistory/{token}"
    try:
        resp = requests.post(url, json={"chatId": chat_id, "count": count}, timeout=3)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"[AGENT] Error fetching chat history for {phone}: {e}")
    return []

class AgentDecision:
    def __init__(self, action: str, response_type: Optional[str] = None, reply_text: Optional[str] = None, reason: str = "", extraction: Optional[ExtractionResult] = None):
        self.action = action  # 'REPLY' | 'SILENCE'
        self.response_type = response_type  # 'RESPONSE_1' | 'RESPONSE_2' | 'RESPONSE_3'
        self.reply_text = reply_text
        self.reason = reason
        self.extraction = extraction

def evaluate_customer_with_ai_agent(
    phone: str,
    incoming_text: str,
    has_media: bool = False,
    media_filename: str = "",
    media_text: str = "",
    profile_name: str = ""
) -> AgentDecision:
    """
    AI Agent that reads full chronological conversation history,
    verifies past bot responses, extracts cumulative entities,
    and guarantees strict one-time execution per number.
    """
    phone_digits = re.sub(r'[^0-9]', '', phone)[-10:]
    guard = get_phone_guard_state(phone_digits)

    lower_text = (incoming_text or "").strip().lower()
    is_greeting = lower_text in ("hi", "hello", "hey", "namaste", "namaskar", "start", "info", "help", "hii", "helo")
    is_followup = is_conversational_followup(incoming_text)

    # If customer sends an explicit greeting, ALWAYS reply with Welcome / Response 2
    if is_greeting:
        logger.info(f"[AGENT] Customer {phone} sent greeting ('{incoming_text}'). Replying with Response 2.")
        update_phone_guard_state(phone_digits, "RESPONSE_2")
        return AgentDecision(
            action="REPLY",
            response_type="RESPONSE_2",
            reply_text=get_response_template("RESPONSE_2"),
            reason=f"Customer greeting '{incoming_text}' received. Providing welcome and requirements prompt."
        )

    # 1. Check Persistent Guard State for Follow-up inquiries
    if (guard["is_completed"] or guard["response_1_sent"]) and is_followup:
        logger.info(f"[AGENT] Customer {phone} inquiry already COMPLETED. Follow-up inquiry ('{incoming_text}') silenced.")
        return AgentDecision(action="SILENCE", reason="Conversation already completed with Response 1. Follow-up silenced.")

    # 2. Fetch Live Chat History from WhatsApp Gateway
    raw_history = fetch_chat_history_from_gateway(phone, count=25)
    history_messages = list(reversed(raw_history)) if raw_history else []

    past_r1_sent = guard["response_1_sent"]
    past_r2_sent = guard["response_2_sent"]
    past_r3_sent = guard["response_3_sent"]

    all_incoming_texts = []
    has_any_media_in_history = has_media or bool(media_text)

    for m in history_messages:
        m_type = m.get("type", "")
        text = m.get("textMessage", "") or m.get("caption", "") or ""
        
        # Check outgoing
        if m_type == "outgoing":
            if "Thank you for sharing your requirements" in text or "formal quotation" in text:
                past_r1_sent = True
            elif "Business / Company Name" in text or "To prepare your quotation" in text:
                past_r3_sent = True
            elif "Welcome to our Electrical Dealership" in text or "Please share your requirement details" in text:
                past_r2_sent = True
        elif m_type == "incoming":
            msg_t = m.get("typeMessage", "")
            if msg_t in ("imageMessage", "documentMessage", "fileMessage"):
                has_any_media_in_history = True
            if text:
                all_incoming_texts.append(text)

    # Append current incoming message if not in history yet
    if incoming_text and (not all_incoming_texts or all_incoming_texts[-1] != incoming_text):
        all_incoming_texts.append(incoming_text)

    # Check if Response 1 was found in WhatsApp history and incoming is follow-up or chatter
    if past_r1_sent and is_followup:
        update_phone_guard_state(phone_digits, "RESPONSE_1")
        logger.info(f"[AGENT] Response 1 found in live WhatsApp chat history for {phone}. Follow-up silenced.")
        return AgentDecision(action="SILENCE", reason="Response 1 found in chat history. Follow-up silenced.")

    # 3. Check for Conversational Follow-up chatter
    is_followup = is_conversational_followup(incoming_text)
    if is_followup and past_r3_sent:
        logger.info(f"[AGENT] Customer {phone} sent follow-up query after Response 3. Staying silent.")
        return AgentDecision(action="SILENCE", reason="Follow-up message after Response 3. No repeated prompt.")

    # 4. Extract Cumulative Entities across ALL customer messages in history + documents/photos
    att_list = [media_text] if media_text else None
    extraction = analyze_conversation(all_incoming_texts, attachment_texts=att_list, profile_name=profile_name)

    # Check Requirements
    has_products = bool(extraction.product_requirements or extraction.raw_requirement_text or has_any_media_in_history)

    # Check Business Details
    has_company = bool(extraction.company_business_name and len(extraction.company_business_name.strip()) >= 2)
    has_address = bool(extraction.complete_address and len(extraction.complete_address.strip()) >= 3)
    has_contact = bool((extraction.contact_person_name and len(extraction.contact_person_name.strip()) >= 2) or has_company)

    has_business_details = has_company and has_address and has_contact

    logger.info(
        f"[AGENT] Evaluation for {phone}: products={has_products}, company={has_company}, "
        f"address={has_address}, contact={has_contact} | past: r1={past_r1_sent}, r2={past_r2_sent}, r3={past_r3_sent}"
    )

    # 5. Determine Decision
    # Scenario A: Requirements AND Business Details are available
    if has_products and has_business_details:
        if not past_r1_sent:
            update_phone_guard_state(phone_digits, "RESPONSE_1")
            return AgentDecision(
                action="REPLY",
                response_type="RESPONSE_1",
                reply_text=get_response_template("RESPONSE_1"),
                reason="All requirements and business details received. Sending Response 1.",
                extraction=extraction
            )
        else:
            return AgentDecision(action="SILENCE", reason="Response 1 already sent.", extraction=extraction)

    # Scenario B: Requirements are present, but Business Details are missing
    elif has_products and not has_business_details:
        if not past_r3_sent:
            update_phone_guard_state(phone_digits, "RESPONSE_3")
            return AgentDecision(
                action="REPLY",
                response_type="RESPONSE_3",
                reply_text=get_response_template("RESPONSE_3"),
                reason="Requirements present, asking for business details (Response 3).",
                extraction=extraction
            )
        else:
            logger.info(f"[AGENT] Response 3 already sent once to {phone}. Staying silent on incomplete details.")
            return AgentDecision(action="SILENCE", reason="Response 3 already sent once. Staying silent.", extraction=extraction)

    # Scenario C: Requirements are missing
    else:
        if not past_r2_sent:
            update_phone_guard_state(phone_digits, "RESPONSE_2")
            return AgentDecision(
                action="REPLY",
                response_type="RESPONSE_2",
                reply_text=get_response_template("RESPONSE_2"),
                reason="Customer greeting / inquiry without requirements. Sending Response 2.",
                extraction=extraction
            )
        else:
            logger.info(f"[AGENT] Response 2 already sent once to {phone}. Staying silent.")
            return AgentDecision(action="SILENCE", reason="Response 2 already sent once. Staying silent.", extraction=extraction)
