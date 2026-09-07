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
                post_help_sent BOOLEAN DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Ensure post_help_sent and reset_at columns exist in existing databases
        try:
            cur.execute("ALTER TABLE phone_flow_guard ADD COLUMN post_help_sent BOOLEAN DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE phone_flow_guard ADD COLUMN reset_at INTEGER DEFAULT 0")
        except Exception:
            pass
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
        cur.execute("SELECT response_1_sent, response_2_sent, response_3_sent, is_completed, last_response, COALESCE(post_help_sent, 0), COALESCE(reset_at, 0) FROM phone_flow_guard WHERE phone = ?", (phone_digits,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "response_1_sent": bool(row[0]),
                "response_2_sent": bool(row[1]),
                "response_3_sent": bool(row[2]),
                "is_completed": bool(row[3]),
                "last_response": row[4],
                "post_help_sent": bool(row[5]),
                "reset_at": int(row[6])
            }
    except Exception as e:
        logger.warning(f"[AGENT] Error reading phone_flow_guard: {e}")
    return {
        "response_1_sent": False,
        "response_2_sent": False,
        "response_3_sent": False,
        "is_completed": False,
        "last_response": None,
        "post_help_sent": False,
        "reset_at": 0
    }

def reset_phone_guard_record(phone_digits: str, reset_timestamp: int = 0):
    """Resets phone guard and sets reset_at so all past chat history is ignored."""
    try:
        import time as _time
        ts = reset_timestamp or int(_time.time())
        db_path = os.path.join(settings.DATA_DIR, "whatsapp_production.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO phone_flow_guard (phone, response_1_sent, response_2_sent, response_3_sent, is_completed, last_response, post_help_sent, reset_at, updated_at)
            VALUES (?, 0, 0, 0, 0, NULL, 0, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
                response_1_sent = 0,
                response_2_sent = 0,
                response_3_sent = 0,
                is_completed = 0,
                last_response = NULL,
                post_help_sent = 0,
                reset_at = excluded.reset_at,
                updated_at = CURRENT_TIMESTAMP
        ''', (phone_digits, ts))
        conn.commit()
        conn.close()
        logger.info(f"[AGENT] Reset phone guard for {phone_digits} with reset_at={ts}")
    except Exception as e:
        logger.warning(f"[AGENT] Error resetting phone_flow_guard: {e}")

def update_phone_guard_state(phone_digits: str, sent_response: str):
    try:
        db_path = os.path.join(settings.DATA_DIR, "whatsapp_production.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        is_comp = (sent_response == "RESPONSE_1")
        r1 = 1 if sent_response == "RESPONSE_1" else 0
        r2 = 1 if sent_response == "RESPONSE_2" else 0
        r3 = 1 if sent_response == "RESPONSE_3" else 0
        post_help = 1 if sent_response == "RESPONSE_POST_COMPLETION" else 0

        cur.execute('''
            INSERT INTO phone_flow_guard (phone, response_1_sent, response_2_sent, response_3_sent, is_completed, last_response, post_help_sent, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
                response_1_sent = MAX(response_1_sent, excluded.response_1_sent),
                response_2_sent = MAX(response_2_sent, excluded.response_2_sent),
                response_3_sent = MAX(response_3_sent, excluded.response_3_sent),
                is_completed = MAX(is_completed, excluded.is_completed),
                post_help_sent = MAX(post_help_sent, excluded.post_help_sent),
                last_response = excluded.last_response,
                updated_at = CURRENT_TIMESTAMP
        ''', (phone_digits, r1, r2, r3, 1 if is_comp else 0, sent_response, post_help))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[AGENT] Error updating phone_flow_guard: {e}")

def fetch_customer_messages_from_db(phone_digits: str, since_ts: int = 0) -> List[Dict[str, Any]]:
    """Fetches all customer messages directly from persistent SQLite database."""
    results = []
    try:
        db_path = os.path.join(settings.DATA_DIR, "whatsapp_production.db")
        if not os.path.exists(db_path):
            return results
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute('''
            SELECT m.text, m.direction, m.message_type, m.media_reference, strftime('%s', m.timestamp) as ts
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            JOIN customers cust ON c.customer_id = cust.id
            WHERE cust.whatsapp_number LIKE ?
            ORDER BY m.id ASC
        ''', (f"%{phone_digits}%",))
        rows = cur.fetchall()
        conn.close()
        for r in rows:
            m_text, m_dir, m_type, m_media, m_ts = r
            ts_int = int(m_ts) if m_ts else 0
            if since_ts and ts_int and ts_int < since_ts:
                continue
            results.append({
                "text": m_text or "",
                "direction": m_dir or "INBOUND",
                "type": m_type or "text",
                "media": m_media or "",
                "timestamp": ts_int
            })
    except Exception as e:
        logger.warning(f"[AGENT] Error reading DB messages for {phone_digits}: {e}")
    return results

def fetch_chat_history_from_gateway(phone: str, count: int = 25) -> List[Dict[str, Any]]:
    """Fallback to fetch live conversation history from gateway if configured."""
    inst_id = getattr(settings, 'GATEWAY_INSTANCE_ID', None)
    token = getattr(settings, 'GATEWAY_API_TOKEN', None)
    base_url = getattr(settings, 'GATEWAY_API_URL', None)
    if not inst_id or not token or not base_url or "green-api" not in base_url:
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
        self.response_type = response_type  # 'RESPONSE_1' | 'RESPONSE_2' | 'RESPONSE_3' | 'RESPONSE_POST_COMPLETION'
        self.reply_text = reply_text
        self.reason = reason
        self.extraction = extraction

def evaluate_customer_with_ai_agent(
    phone: str,
    incoming_text: str,
    has_media: bool = False,
    media_filename: str = "",
    media_text: str = "",
    profile_name: str = "",
    existing_requirements: str = "",
    existing_company: str = "",
    existing_address: str = "",
    existing_contact: str = "",
    existing_gst: str = ""
) -> AgentDecision:
    """
    Intelligent AI Agent:
    1. Analyzes ALL customer documents, photos, spreadsheets, and files (cumulative).
    2. Analyzes ALL chronological conversation history (past chats + current message).
    3. Evaluates which details (requirements, business details) are ALREADY available.
    4. Guarantees that details/requirements already provided are NEVER requested again.
    5. Dispatches Response 1, Response 2, Response 3, or SILENCE with zero repeated or wrong replies.
    """
    phone_digits = re.sub(r'[^0-9]', '', phone)[-10:]
    guard = get_phone_guard_state(phone_digits)
    reset_ts = guard.get("reset_at", 0) or 0

    lower_text = (incoming_text or "").strip().lower()
    is_greeting = lower_text in ("hi", "hello", "hey", "namaste", "namaskar", "start", "info", "help", "hii", "helo")
    is_followup = is_conversational_followup(incoming_text)

    # 1. Post-Completion Check: If flow was already completed in our persistent DB
    if guard["is_completed"] or guard["response_1_sent"]:
        if not guard.get("post_help_sent"):
            logger.info(f"[AGENT] Customer {phone} flow already completed. Triggering one post-completion help message.")
            update_phone_guard_state(phone_digits, "RESPONSE_POST_COMPLETION")
            return AgentDecision(
                action="REPLY",
                response_type="RESPONSE_POST_COMPLETION",
                reply_text=get_response_template("RESPONSE_POST_COMPLETION"),
                reason="Flow completed. Customer sent message, triggering one post-completion help message."
            )
        else:
            logger.info(f"[AGENT] Customer {phone} post-completion help already sent once. Silencing follow-up.")
            return AgentDecision(action="SILENCE", reason="Post-completion help message already sent once.")

    # 2. Fetch Full Chronological History from SQLite Database
    db_history = fetch_customer_messages_from_db(phone_digits, since_ts=reset_ts)
    all_incoming_texts = [m["text"] for m in db_history if m["direction"] == "INBOUND" and m["text"] and not m["text"].startswith("[")]

    # Append current incoming text if not already the last item
    if incoming_text and (not all_incoming_texts or all_incoming_texts[-1] != incoming_text):
        all_incoming_texts.append(incoming_text)

    # 3. Gather Attachment Texts (Current + All Previous Documents in Storage)
    att_list = []
    if media_text:
        att_list.append(media_text)

    save_dir = os.path.join(settings.DATA_DIR, "customer_files")
    if os.path.exists(save_dir):
        for fname in os.listdir(save_dir):
            if fname.startswith(f"{phone_digits}_"):
                fpath = os.path.join(save_dir, fname)
                try:
                    from document_analyzer import analyze_file
                    _, prev_raw = analyze_file(fpath)
                    if prev_raw and prev_raw not in att_list:
                        att_list.append(prev_raw)
                except Exception:
                    pass

    # 4. Cumulative Extraction across ALL Messages and ALL Documents
    extraction = analyze_conversation(
        all_incoming_texts,
        attachment_texts=att_list if att_list else None,
        profile_name=profile_name
    )

    # 5. Check what details are ALREADY AVAILABLE
    # Requirements Check:
    has_products = bool(
        existing_requirements
        or extraction.product_requirements
        or extraction.raw_requirement_text
        or has_media
        or bool(media_text)
        or bool(att_list)
    )

    # Business Details Check:
    company_cand = (existing_company or extraction.company_business_name or "").strip()
    has_company = bool(company_cand and len(company_cand) >= 2 and company_cand.lower() not in ("none", "null", "not applicable", "customer"))

    address_cand = (existing_address or extraction.complete_address or "").strip()
    has_address = bool(address_cand and len(address_cand) >= 3)

    contact_cand = (existing_contact or extraction.contact_person_name or "").strip()
    has_contact = bool((contact_cand and len(contact_cand) >= 2 and contact_cand.lower() not in ("none", "null", "customer")) or has_company)

    has_business_details = has_company and has_address and has_contact

    past_r1_sent = guard["response_1_sent"]
    past_r2_sent = guard["response_2_sent"]
    past_r3_sent = guard["response_3_sent"]

    logger.info(
        f"[AGENT] Cumulative check for {phone}: products={has_products}, company={has_company}, "
        f"address={has_address}, contact={has_contact} | past sent: r1={past_r1_sent}, r2={past_r2_sent}, r3={past_r3_sent}"
    )

    # 6. STABLE DECISION LOGIC: DO NOT GENERATE REPEAT REQUESTS FOR DETAILS ALREADY AVAILABLE
    
    # SCENARIO 1: Both Requirements AND Business Details are Available
    if has_products and has_business_details:
        if not past_r1_sent:
            update_phone_guard_state(phone_digits, "RESPONSE_1")
            return AgentDecision(
                action="REPLY",
                response_type="RESPONSE_1",
                reply_text=get_response_template("RESPONSE_1"),
                reason="All requirements and business details received. Sending confirmation Response 1.",
                extraction=extraction
            )
        else:
            if not guard.get("post_help_sent"):
                update_phone_guard_state(phone_digits, "RESPONSE_POST_COMPLETION")
                return AgentDecision(
                    action="REPLY",
                    response_type="RESPONSE_POST_COMPLETION",
                    reply_text=get_response_template("RESPONSE_POST_COMPLETION"),
                    reason="Details already submitted. Sending one post-completion help message.",
                    extraction=extraction
                )
            return AgentDecision(action="SILENCE", reason="All details already received and confirmed.", extraction=extraction)

    # SCENARIO 2: Requirements are Available, but Business Details are Missing
    elif has_products and not has_business_details:
        # Requirements are ALREADY available! NEVER send Response 2 (do not ask for requirements again).
        if not past_r3_sent:
            update_phone_guard_state(phone_digits, "RESPONSE_3")
            return AgentDecision(
                action="REPLY",
                response_type="RESPONSE_3",
                reply_text=get_response_template("RESPONSE_3"),
                reason="Requirements are already available. Requesting missing business details (Response 3).",
                extraction=extraction
            )
        else:
            # Response 3 was ALREADY sent once!
            # Do NOT ask again for the same details! Stay SILENT!
            logger.info(f"[AGENT] Response 3 already sent once to {phone}. Staying silent on repeat/followup message.")
            return AgentDecision(
                action="SILENCE",
                reason="Requirements already available and Response 3 was already sent once. Staying silent to avoid repeating requests.",
                extraction=extraction
            )

    # SCENARIO 3: Requirements are NOT yet available (e.g. Greeting or Incomplete Inquiry)
    else:
        if not past_r2_sent:
            update_phone_guard_state(phone_digits, "RESPONSE_2")
            return AgentDecision(
                action="REPLY",
                response_type="RESPONSE_2",
                reply_text=get_response_template("RESPONSE_2"),
                reason="No requirements found. Sending Response 2 to request product requirements.",
                extraction=extraction
            )
        else:
            # Response 2 was ALREADY sent once!
            # Do NOT repeat Response 2!
            logger.info(f"[AGENT] Response 2 already sent once to {phone}. Staying silent.")
            return AgentDecision(
                action="SILENCE",
                reason="Response 2 was already sent once. Waiting for customer requirements without repeating.",
                extraction=extraction
            )
