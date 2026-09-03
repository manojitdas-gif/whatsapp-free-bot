"""
debounce_queue.py — Burst Message Debounce Worker.
Aggregates multiple customer messages received within DEBOUNCE_SECONDS (1.5s - 2.0s)
into a single customer burst, analyzes the complete burst + conversation history,
and sends exactly ONE unified response.
"""

import asyncio
import time
from typing import Dict, List, Any
from app.config import settings
from app.database.session import SessionLocal
from app.database.models import Customer, Conversation, Message, ExtractedData, ResponseLog, utc_now
from app.ai.extractor import analyze_conversation
from app.conversation.decision_engine import evaluate_conversation_completeness
from app.conversation.templates import get_response_template
from app.conversation.state_machine import ConversationStage, ConversationStatus
from app.whatsapp import get_whatsapp_provider
from app.exports.excel_exporter import sync_customer_to_excel

# Dict holding active debounce timers: { phone: {"timer_task": Task, "burst_count": int, "latest_msg_time": float} }
_debounce_registry: Dict[str, Dict[str, Any]] = {}
_registry_lock = asyncio.Lock()

async def enqueue_customer_message(whatsapp_number: str, message_data: Dict[str, Any]):
    """
    Enqueues incoming message from a customer.
    Resets the debounce silence timer for this customer.
    """
    async with _registry_lock:
        now = time.time()
        entry = _debounce_registry.get(whatsapp_number)
        
        if entry and entry.get("task"):
            # Cancel existing pending timer task (resetting debounce period)
            entry["task"].cancel()

        # Schedule new burst processing after DEBOUNCE_SECONDS
        task = asyncio.create_task(_debounce_worker(whatsapp_number, settings.DEBOUNCE_SECONDS))
        _debounce_registry[whatsapp_number] = {
            "task": task,
            "latest_msg_time": now
        }

async def _debounce_worker(whatsapp_number: str, delay: float):
    current_task = asyncio.current_task()
    try:
        await asyncio.sleep(delay)
        # Silence window passed! Process the unified interaction burst
        await process_customer_conversation(whatsapp_number)
    except asyncio.CancelledError:
        # Debounce timer was reset by another incoming message in the burst
        pass
    finally:
        async with _registry_lock:
            entry = _debounce_registry.get(whatsapp_number)
            if entry and entry.get("task") == current_task:
                del _debounce_registry[whatsapp_number]

async def process_customer_conversation(whatsapp_number: str):
    """
    Core Pipeline:
    1. Look up Customer & Active Conversation in DB.
    2. Read complete historical conversation + attachments.
    3. Run AI/NLP Extraction & Merge.
    4. Save extracted data to database.
    5. Evaluate completeness against Category A & B.
    6. Select Response 1, 2, or 3.
    7. Send via WhatsApp Provider.
    8. Log Response & update Conversation Stage/Status.
    9. Sync 9-column Excel & CSV.
    """
    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.whatsapp_number == whatsapp_number).first()
        if not customer:
            return

        conversation = (
            db.query(Conversation)
            .filter(Conversation.customer_id == customer.id, Conversation.status == ConversationStatus.ACTIVE.value)
            .order_by(Conversation.id.desc())
            .first()
        )

        if not conversation:
            # Create new active conversation
            conversation = Conversation(
                customer_id=customer.id,
                status=ConversationStatus.ACTIVE.value,
                stage=ConversationStage.NEW.value
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

        # Gather all inbound messages in this conversation
        messages = (
            db.query(Message)
            .filter(Message.conversation_id == conversation.id, Message.direction == "INBOUND")
            .order_by(Message.id.asc())
            .all()
        )

        if not messages:
            return

        messages_text = [m.text for m in messages if m.text]
        has_media = any(m.message_type in ("image", "document") for m in messages)

        # ── 1. AI/NLP Extraction over COMPLETE conversation ────────────────────
        extraction = analyze_conversation(
            messages_history=messages_text,
            profile_name=customer.contact_person_name
        )

        # ── 2. Update Customer Record ──────────────────────────────────────────
        if extraction.contact_person_name:
            customer.contact_person_name = extraction.contact_person_name
        if extraction.email_id:
            customer.email = extraction.email_id
        if extraction.company_business_name:
            customer.company_name = extraction.company_business_name
        if extraction.gst_number:
            customer.gst_number = extraction.gst_number
        if extraction.complete_address:
            customer.complete_address = extraction.complete_address

        req_summary = extraction.format_requirements_summary()
        if req_summary:
            customer.requirements_summary = req_summary

        customer.last_contact_at = utc_now()
        db.commit()

        # ── 3. Decision Engine: Missing Field Calculation & Response Selection ─
        response_type, audit_meta = evaluate_conversation_completeness(extraction, has_media=has_media)
        reply_text = get_response_template(response_type)

        # ── 4. Send WhatsApp Response ──────────────────────────────────────────
        provider = get_whatsapp_provider()
        sent_ok = await provider.send_text_message(whatsapp_number, reply_text)

        # ── 5. Update Conversation Stage & Log Response ────────────────────────
        resp_log = ResponseLog(
            conversation_id=conversation.id,
            response_type=response_type,
            message_text=reply_text,
            status="SENT" if sent_ok else "FAILED"
        )
        db.add(resp_log)

        if response_type == "RESPONSE_1":
            conversation.stage = ConversationStage.COMPLETED.value
            conversation.status = ConversationStatus.COMPLETED.value
            conversation.completed_at = utc_now()
        elif response_type == "RESPONSE_2":
            conversation.stage = ConversationStage.WAITING_FOR_PRODUCT_REQUIREMENTS.value
        elif response_type == "RESPONSE_3":
            conversation.stage = ConversationStage.WAITING_FOR_CUSTOMER_DETAILS.value

        db.commit()

        # ── 6. Sync to Excel (9 columns, in-place update) ───────────────────────
        sync_customer_to_excel(customer)

    except Exception as e:
        print(f"[PROCESS CONVERSATION ERROR] {e}")
        db.rollback()
    finally:
        db.close()
