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

def unwrap_evolution_message(msg_obj: dict) -> tuple[dict, str]:
    if not isinstance(msg_obj, dict):
        return {}, "text"
    if "ephemeralMessage" in msg_obj:
        msg_obj = msg_obj["ephemeralMessage"].get("message", {}) or {}
    if "viewOnceMessage" in msg_obj:
        msg_obj = msg_obj["viewOnceMessage"].get("message", {}) or {}
    if "viewOnceMessageV2" in msg_obj:
        msg_obj = msg_obj["viewOnceMessageV2"].get("message", {}) or {}
    if "documentWithCaptionMessage" in msg_obj:
        msg_obj = msg_obj["documentWithCaptionMessage"].get("message", {}) or {}

    if "imageMessage" in msg_obj:
        return msg_obj["imageMessage"], "imageMessage"
    elif "documentMessage" in msg_obj:
        return msg_obj["documentMessage"], "documentMessage"
    elif "videoMessage" in msg_obj:
        return msg_obj["videoMessage"], "videoMessage"
    elif "audioMessage" in msg_obj:
        return msg_obj["audioMessage"], "audioMessage"
    elif "extendedTextMessage" in msg_obj:
        return msg_obj["extendedTextMessage"], "extendedTextMessage"
    return msg_obj, "text"

    # 2. Evolution API / Baileys generic format
    event = payload.get("event", "")
    data = payload.get("data", {}) or payload
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
    if isinstance(data, dict) and (event == "messages.upsert" or "key" in data):
        key = data.get("key", {})
        if key.get("fromMe"):
            return None
        remote_jid = key.get("remoteJid", "")
        # Ignore status broadcasts, group chats, newsletters
        if not remote_jid or "broadcast" in remote_jid or remote_jid.endswith("@g.us") or remote_jid.endswith("@newsletter"):
            return None
        clean_phone = re.sub(r'[^0-9]', '', remote_jid)
        if not clean_phone:
            return None

        raw_msg = data.get("message", {}) or {}
        inner_msg, msg_type = unwrap_evolution_message(raw_msg)

        text = ""
        file_name = ""
        media_url = ""
        base64_data = data.get("base64") or (inner_msg.get("base64") if isinstance(inner_msg, dict) else "") or ""
        key_id = key.get("id", "msg")

        if msg_type == "imageMessage":
            text = inner_msg.get("caption", "") or "[Product Photo Attached]"
            file_name = f"image_{key_id}.jpg"
            media_url = inner_msg.get("url", "")
        elif msg_type == "documentMessage":
            fn = inner_msg.get("fileName") or inner_msg.get("title") or f"doc_{key_id}.pdf"
            file_name = fn
            text = inner_msg.get("caption", "") or f"[Document: {fn}]"
            media_url = inner_msg.get("url", "")
        elif msg_type == "extendedTextMessage":
            text = inner_msg.get("text", "")
        else:
            text = (
                raw_msg.get("conversation") or
                inner_msg.get("text") or
                inner_msg.get("caption") or ""
            )

        return {
            "phone": clean_phone,
            "name": data.get("pushName", ""),
            "text": text.strip(),
            "media_url": media_url,
            "file_name": file_name,
            "type": msg_type,
            "raw_data": data,
            "base64_data": base64_data
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

        # Ensure active conversation exists
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

        # Track completed phones in-memory for quick reference
        comp_conv = db.query(Conversation).filter(
            Conversation.customer_id == customer.id,
            (Conversation.status == ConversationStatus.COMPLETED.value) |
            (Conversation.stage == ConversationStage.COMPLETED.value)
        ).first()
        if comp_conv:
            _completed_phones.add(phone_digits)
        else:
            _completed_phones.discard(phone_digits)

        # ── DOWNLOAD & ANALYZE ATTACHED MEDIA/DOCUMENTS ───────────────────────
        ocr_text = ""
        extracted_doc_summary = ""
        raw_doc_text = ""
        is_media_message = bool(file_name or media_url or info.get("type") in ("imageMessage", "documentMessage", "image", "document") or info.get("base64_data"))
        local_file = ""

        if is_media_message:
            save_dir = os.path.join(settings.DATA_DIR, "customer_files")
            os.makedirs(save_dir, exist_ok=True)
            safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', file_name or "attachment.pdf")
            local_file = os.path.join(save_dir, f"{phone_digits}_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}_{safe_name}")

            provider = get_whatsapp_provider()
            downloaded = False

            # 1. Try base64 directly if present
            if info.get("base64_data"):
                downloaded = await provider.download_media(info["base64_data"], local_file)

            # 2. Try Evolution API getBase64FromMediaMessage if raw_data is available
            if not downloaded and info.get("raw_data") and hasattr(provider, "download_media_from_message"):
                downloaded = await provider.download_media_from_message(info["raw_data"], local_file)

            # 3. Try standard media_url if available
            if not downloaded and media_url:
                downloaded = await provider.download_media(media_url, local_file)

            if downloaded and os.path.exists(local_file):
                logger.info("[CLOUD BOT] Successfully saved customer document: %s (%d bytes)", local_file, os.path.getsize(local_file))
                doc_sum, doc_raw = analyze_file(local_file)
                if doc_raw:
                    ocr_text = doc_raw
                    raw_doc_text = doc_raw
                if doc_sum:
                    extracted_doc_summary = doc_sum

        # Save incoming customer message with document details if present
        saved_text = text
        if extracted_doc_summary:
            saved_text = f"{text}\n{extracted_doc_summary}" if text and text != extracted_doc_summary else extracted_doc_summary
        elif is_media_message and not text:
            saved_text = f"[Document: {file_name}]" if file_name else "[Media Attachment]"

        inbound_msg = Message(
            conversation_id=conv.id,
            direction="INBOUND",
            message_type=info.get("type", "text"),
            text=saved_text,
            media_reference=local_file if (local_file and os.path.exists(local_file)) else (file_name or media_url or None),
            processing_status="PROCESSED",
            timestamp=utc_now()
        )
        db.add(inbound_msg)
        db.commit()

        # ── CUMULATIVE MULTI-TURN DOCUMENT & CHAT EXTRACTION ────────────────
        past_inbound_texts = []
        past_attachment_texts = []

        if raw_doc_text:
            past_attachment_texts.append(raw_doc_text)

        all_convs = db.query(Conversation).filter(Conversation.customer_id == customer.id).all()
        for c in all_convs:
            msgs = db.query(Message).filter(Message.conversation_id == c.id).order_by(Message.id.asc()).all()
            for m in msgs:
                if m.direction == "INBOUND" and m.text and not m.text.startswith("["):
                    past_inbound_texts.append(m.text)

        # Retrieve all previous documents from data/customer_files for this customer
        save_dir = os.path.join(settings.DATA_DIR, "customer_files")
        if os.path.exists(save_dir):
            for fname in os.listdir(save_dir):
                if fname.startswith(f"{phone_digits}_"):
                    fpath = os.path.join(save_dir, fname)
                    try:
                        _, prev_raw = analyze_file(fpath)
                        if prev_raw and prev_raw not in past_attachment_texts:
                            past_attachment_texts.append(prev_raw)
                    except Exception:
                        pass

        if text and text not in past_inbound_texts:
            past_inbound_texts.append(text)

        extraction = analyze_conversation(
            messages_history=past_inbound_texts,
            attachment_texts=past_attachment_texts if past_attachment_texts else None,
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
            has_media=bool(is_media_message or customer.requirements_summary or extracted_doc_summary),
            media_filename=file_name,
            media_text=ocr_text,
            profile_name=name,
            existing_requirements=customer.requirements_summary or "",
            existing_company=customer.company_name or "",
            existing_address=customer.complete_address or "",
            existing_contact=customer.contact_person_name or "",
            existing_gst=customer.gst_number or ""
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

        from app.exports.data_sanitizer import (
            clean_contact_name,
            clean_company_name,
            clean_address,
            clean_gst_number,
            clean_email,
            clean_requirements_summary,
            clean_phone_number
        )

        customer.company_name = clean_company_name(customer.company_name)
        customer.contact_person_name = clean_contact_name(customer.contact_person_name, company=customer.company_name)
        customer.complete_address = clean_address(customer.complete_address)
        customer.gst_number = clean_gst_number(customer.gst_number)
        customer.email = clean_email(customer.email)
        customer.requirements_summary = clean_requirements_summary(customer.requirements_summary)
        customer.whatsapp_number = clean_phone_number(customer.whatsapp_number)

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
            # ── SAVE OUTGOING BOT REPLY IN BACKEND DATABASE ──────────────────
            outbound_msg = Message(
                conversation_id=conv.id,
                direction="OUTBOUND",
                message_type="text",
                text=reply_text,
                processing_status="PROCESSED",
                timestamp=utc_now()
            )
            db.add(outbound_msg)

            resp_log = ResponseLog(
                conversation_id=conv.id,
                response_type=response_type,
                message_text=reply_text,
                status="SENT",
                sent_at=utc_now()
            )
            db.add(resp_log)
            db.commit()
            logger.info("[CLOUD BOT] Sent %s to %s and recorded in backend DB. Reason: %s", response_type, phone, agent_decision.reason)

        # Stage Transition
        if response_type in ("RESPONSE_1", "RESPONSE_POST_COMPLETION"):
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
