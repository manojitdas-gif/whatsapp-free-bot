"""
cloud_router.py — FastAPI Webhook Router for WhatsApp-compatible Cloud Gateways.
Receives incoming messages/media 24/7 without requiring Meta verification or local PC uptime.
"""

import os
import re
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, BackgroundTasks, Response, status
from pydantic import BaseModel

from app.config import settings
from app.database.session import SessionLocal
from app.database.models import Customer, Conversation, Message, ResponseLog, utc_now
from app.conversation.state_machine import ConversationStage, ConversationStatus
from app.conversation.decision_engine import evaluate_conversation_completeness
from app.conversation.templates import get_response_template
from app.schemas.extraction import ExtractionResult
from app.ai.extractor import analyze_conversation
from app.exports.excel_exporter import sync_customer_to_excel
from app.exports.google_sheets_sync import sync_customer_to_google_sheet_async
from app.whatsapp import get_whatsapp_provider
from document_analyzer import analyze_file, parse_product_details
from app.ai.conversation_agent import evaluate_customer_with_ai_agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["Cloud Gateway Webhook"])

IST = timezone(timedelta(hours=5, minutes=30))
GREETING_WORDS = {
    "hi", "hello", "hey", "namaste", "namaskar", "start", "info", "help",
    "shuru", "karo", "good morning", "good afternoon", "good evening", "hii", "helo"
}

_completed_phones = set()
_last_sent_response = {}

def _init_completed():
    global _completed_phones
    try:
        db = SessionLocal()
        rows = db.query(Customer.whatsapp_number).join(Conversation).filter(
            (Conversation.status == ConversationStatus.COMPLETED.value) |
            (Conversation.stage == ConversationStage.COMPLETED.value)
        ).all()
        for r in rows:
            digits = re.sub(r'[^0-9]', '', str(r[0]))[-10:]
            if digits:
                _completed_phones.add(digits)
        db.close()
    except Exception as e:
        logger.error("[CLOUD INIT ERROR] %s", e)

_init_completed()

def extract_message_info(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extracts standardized message details from Green API or generic gateway payload."""
    type_webhook = payload.get("typeWebhook", "")
    
    # 1. Green API format
    if type_webhook in ("incomingMessageReceived", "incomingCall"):
        sender_data = payload.get("senderData", {})
        sender_raw = sender_data.get("sender", "") or sender_data.get("chatId", "")
        sender_name = sender_data.get("senderName", "")
        msg_data = payload.get("messageData", {})
        type_msg = msg_data.get("typeMessage", "")

        text = ""
        media_url = ""
        file_name = ""

        if type_msg == "textMessage":
            text = msg_data.get("textMessageData", {}).get("textMessage", "")
        elif type_msg == "extendedTextMessage":
            text = msg_data.get("extendedTextMessageData", {}).get("text", "")
        elif type_msg in ("imageMessage", "documentMessage", "fileMessage"):
            file_data = msg_data.get("fileMessageData", {})
            media_url = file_data.get("downloadUrl", "")
            file_name = file_data.get("fileName", "")
            text = file_data.get("caption", "") or f"[Document: {file_name}]"

        clean_phone = re.sub(r'[^0-9]', '', sender_raw)
        if clean_phone.endswith("@c.us"):
            clean_phone = clean_phone[:-5]

        if clean_phone:
            return {
                "phone": clean_phone,
                "name": sender_name,
                "text": text.strip(),
                "media_url": media_url,
                "file_name": file_name,
                "type": type_msg
            }

    # 2. Evolution API / Baileys generic format
    event = payload.get("event", "")
    data = payload.get("data", {}) or payload
    if event == "messages.upsert" or "key" in data:
        key = data.get("key", {})
        if key.get("fromMe"):
            return None
        remote_jid = key.get("remoteJid", "")
        clean_phone = re.sub(r'[^0-9]', '', remote_jid)
        msg_obj = data.get("message", {})
        text = (
            msg_obj.get("conversation") or
            msg_obj.get("extendedTextMessage", {}).get("text") or
            msg_obj.get("imageMessage", {}).get("caption") or
            msg_obj.get("documentMessage", {}).get("caption") or ""
        )
        return {
            "phone": clean_phone,
            "name": data.get("pushName", ""),
            "text": text.strip(),
            "media_url": "",
            "file_name": "",
            "type": "text"
        }

    # 3. Direct JSON test payload: {"phone": "...", "text": "...", "name": "..."}
    if "phone" in payload and "text" in payload:
        return {
            "phone": re.sub(r'[^0-9]', '', str(payload["phone"])),
            "name": payload.get("name", ""),
            "text": str(payload.get("text", "")).strip(),
            "media_url": payload.get("media_url", ""),
            "file_name": payload.get("file_name", ""),
            "type": "direct"
        }

    return None

async def process_incoming_cloud_message(info: Dict[str, Any]):
    phone = info["phone"]
    phone_digits = phone[-10:]
    name = info.get("name", "")
    text = info.get("text", "")
    media_url = info.get("media_url", "")
    file_name = info.get("file_name", "")

    db = SessionLocal()
    try:
        customer = None
        for cand in db.query(Customer).all():
            c_digits = re.sub(r'[^0-9]', '', str(cand.whatsapp_number))[-10:]
            if c_digits == phone_digits:
                customer = cand
                break

        if not customer:
            customer = Customer(
                whatsapp_number=f"+91 {phone_digits[:5]} {phone_digits[5:]}",
                contact_person_name=name or "",
                first_contact_at=utc_now(),
                last_contact_at=utc_now()
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
        else:
            customer.last_contact_at = utc_now()
            if name and (not customer.contact_person_name or customer.contact_person_name.lower() in ("customer", "none")):
                customer.contact_person_name = name

        # Strict silence check: If conversation already completed, do not reply further
        is_completed = False
        comp_conv = db.query(Conversation).filter(
            Conversation.customer_id == customer.id,
            (Conversation.status == ConversationStatus.COMPLETED.value) |
            (Conversation.stage == ConversationStage.COMPLETED.value)
        ).first()
        if comp_conv:
            is_completed = True
            _completed_phones.add(phone_digits)
        else:
            _completed_phones.discard(phone_digits)

        # Handle Document / Photo download if URL provided
        ocr_text = ""
        extracted_doc_summary = ""
        if media_url:
            save_dir = os.path.join(settings.DATA_DIR, "customer_files")
            os.makedirs(save_dir, exist_ok=True)
            ext = os.path.splitext(file_name)[1] if file_name else ".pdf"
            local_file = os.path.join(save_dir, f"{phone}_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}_{file_name or 'file' + ext}")
            provider = get_whatsapp_provider()
            downloaded = await provider.download_media(media_url, local_file)
            if downloaded:
                doc_sum, doc_raw = analyze_file(local_file)
                if doc_raw:
                    ocr_text = doc_raw
                if doc_sum:
                    extracted_doc_summary = doc_sum

        # Extract details using electrical NLP
        att_texts = [ocr_text] if ocr_text else None
        extraction = analyze_conversation(
            messages_history=[text] if text else [],
            attachment_texts=att_texts,
            profile_name=name
        )

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

        # Requirement details assignment (Strict filter on chatter)
        new_req = extraction.format_requirements_summary()
        if not new_req and extracted_doc_summary:
            new_req = extracted_doc_summary

        if not new_req and text:
            lower_t = text.lower()
            if "?" not in text and not any(noise in lower_t for noise in (
                "deleted this message", "price", "rate", "costly", "batao", "bhejo",
                "plz send", "please send", "acha", "wala", "hoga", "kardo", "kaise",
                "hi", "hello", "hey", "namaste", "ok", "yes", "no", "thanks", "thank you"
            )):
                has_product = any(pw in lower_t for pw in (
                    "bulb", "lamp", "light", "led", "fan", "wire", "cable", "switch",
                    "socket", "mcb", "mccb", "rccb", "db", "conduit", "pipe", "heater",
                    "geyser", "starter", "motor", "contactor", "relay", "meter"
                ))
                has_unit = bool(re.search(r'\b\d+\s*(?:pcs|pc|nos|no|meter|mtr|m|watt|w|inch|mm)\b', lower_t))
                if has_product or has_unit:
                    new_req = text.strip()

        if not new_req and file_name:
            new_req = f"Document: {file_name} (Attached in WhatsApp)"

        if new_req:
            if not customer.requirements_summary or customer.requirements_summary in ("[Product Photo Attached]", "[Product Photo / Document Attached]"):
                customer.requirements_summary = new_req
            elif new_req.lower() not in customer.requirements_summary.lower():
                customer.requirements_summary = f"{customer.requirements_summary}\n{new_req}"

        if not customer.contact_person_name or customer.contact_person_name.lower() in ("customer", "none"):
            if customer.company_name:
                customer.contact_person_name = customer.company_name

        db.commit()

        # Synchronize to Desktop Excel and Cloud Google Sheet
        try:
            sync_customer_to_excel(customer)
        except Exception:
            pass
        await sync_customer_to_google_sheet_async(customer)

        # ── AI AGENT CONVERSATION ANALYSIS & DECISION ──────────────────────────
        agent_decision = evaluate_customer_with_ai_agent(
            phone=phone,
            incoming_text=text,
            has_media=bool(media_url or file_name or customer.requirements_summary),
            media_filename=file_name,
            media_text=ocr_text,
            profile_name=name
        )

        # Merge any newly extracted entities from full history into customer
        if agent_decision.extraction:
            ext = agent_decision.extraction
            if ext.company_business_name and (not customer.company_name or len(ext.company_business_name) > len(customer.company_name)):
                customer.company_name = ext.company_business_name
            if ext.contact_person_name and (not customer.contact_person_name or customer.contact_person_name.lower() in ("customer", "none")):
                customer.contact_person_name = ext.contact_person_name
            if ext.complete_address and (not customer.complete_address or len(ext.complete_address) > len(customer.complete_address)):
                customer.complete_address = ext.complete_address
            if ext.gst_number and not customer.gst_number:
                customer.gst_number = ext.gst_number
            if ext.email_id and not customer.email:
                customer.email = ext.email_id
            
            ext_summary = ext.format_requirements_summary()
            if ext_summary:
                if not customer.requirements_summary or customer.requirements_summary in ("[Product Photo Attached]", "[Product Photo / Document Attached]"):
                    customer.requirements_summary = ext_summary
                elif ext_summary.lower() not in customer.requirements_summary.lower():
                    customer.requirements_summary = f"{customer.requirements_summary}\n{ext_summary}"

        if not customer.contact_person_name or customer.contact_person_name.lower() in ("customer", "none"):
            if customer.company_name:
                customer.contact_person_name = customer.company_name

        db.commit()

        # Synchronize updated details to Google Sheets and Excel
        await sync_customer_to_google_sheet_async(customer)
        try:
            sync_customer_to_excel(customer)
        except Exception:
            pass

        # ── ENFORCE AGENT DECISION ───────────────────────────────────────────
        if agent_decision.action == "SILENCE":
            logger.info("[CLOUD BOT] AI Agent Decision for %s: SILENCE. Reason: %s", phone, agent_decision.reason)
            return

        response_type = agent_decision.response_type
        reply_text = agent_decision.reply_text

        # Fetch latest conversation to check/update stage
        conv = db.query(Conversation).filter(Conversation.customer_id == customer.id).order_by(Conversation.id.desc()).first()
        if not conv:
            conv = Conversation(
                customer_id=customer.id,
                stage=ConversationStage.NEW.value,
                status=ConversationStatus.ACTIVE.value
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)

        # Send Reply via Gateway
        provider = get_whatsapp_provider()
        sent = await provider.send_text_message(phone, reply_text)
        if sent:
            _last_sent_response[phone_digits] = response_type
            logger.info("[CLOUD BOT] Sent %s to %s. Reason: %s", response_type, phone, agent_decision.reason)

        # Stage Transition
        if response_type == "RESPONSE_1":
            conv.stage = ConversationStage.COMPLETED.value
            conv.status = ConversationStatus.COMPLETED.value
            _completed_phones.add(phone_digits)
        elif response_type == "RESPONSE_3":
            conv.stage = ConversationStage.WAITING_FOR_CUSTOMER_DETAILS.value
        elif response_type == "RESPONSE_2":
            conv.stage = ConversationStage.WAITING_FOR_PRODUCT_REQUIREMENTS.value

        db.commit()

    except Exception as e:
        logger.error("[CLOUD BOT PROCESSING ERROR] %s", e)
    finally:
        db.close()

@router.post("/cloud")
async def receive_cloud_webhook(request: Request, background_tasks: BackgroundTasks):
    """Entrypoint for Green API, Evolution API, and Baileys cloud webhooks."""
    try:
        payload = await request.json()
    except Exception:
        return Response(content='{"status": "invalid json"}', status_code=status.HTTP_400_BAD_REQUEST)

    info = extract_message_info(payload)
    if not info or not info.get("phone"):
        return {"status": "ignored", "reason": "non-message event or missing sender"}

    # Process in background task
    background_tasks.add_task(process_incoming_cloud_message, info)
    return {"status": "accepted", "phone": info["phone"]}

@router.get("/cloud")
async def verify_cloud_webhook(request: Request):
    """Handshake verification endpoint."""
    return {"status": "online", "service": "WhatsApp Cloud Webhook Router"}
