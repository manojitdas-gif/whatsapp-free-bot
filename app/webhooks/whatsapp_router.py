"""
whatsapp_router.py — Ingestion Webhook Endpoint with Idempotency, Meta verification, and Media downloads.
"""

import os
from fastapi import APIRouter, Request, Response, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from app.config import settings
from app.database.session import get_db
from app.database.models import Customer, Conversation, Message, utc_now
from app.whatsapp import get_whatsapp_provider
from app.documents.parser import parse_attachment
from app.workers.debounce_queue import enqueue_customer_message

router = APIRouter(prefix="/webhook", tags=["Webhook"])

@router.get("")
async def verify_webhook(request: Request):
    """
    Standard Meta Webhook handshake verification.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    provider = get_whatsapp_provider()
    res = provider.verify_webhook(mode, token, challenge)
    if res:
        return Response(content=res, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)

@router.post("")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Receives WhatsApp webhook events (Meta Cloud API or standard JSON payloads).
    Enforces idempotency by checking message_id, stores messages, and enqueues to debounce worker.
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "invalid_json"}

    provider = get_whatsapp_provider()

    # Meta Cloud API Webhook format
    entries = body.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            contacts = value.get("contacts", [])
            messages = value.get("messages", [])

            # Extract profile name
            profile_name = None
            if contacts:
                profile_name = contacts[0].get("profile", {}).get("name")

            for msg in messages:
                msg_id = msg.get("id")
                from_num = msg.get("from")
                msg_type = msg.get("type", "text")
                text_content = ""
                media_path = None

                # ── IDEMPOTENCY CHECK ──────────────────────────────────────────
                if msg_id:
                    existing = db.query(Message).filter(Message.whatsapp_message_id == msg_id).first()
                    if existing:
                        # Duplicate delivery! Ignore idempotently
                        continue

                # Parse Text
                if msg_type == "text":
                    text_content = msg.get("text", {}).get("body", "")
                
                # Parse Media (image, document)
                elif msg_type in ("image", "document"):
                    media_obj = msg.get(msg_type, {})
                    media_id = media_obj.get("id")
                    caption = media_obj.get("caption", "")
                    filename = media_obj.get("filename", f"{msg_id}.dat")
                    
                    if media_id:
                        save_path = os.path.join(settings.MEDIA_DIR, f"{from_num}_{filename}")
                        downloaded = await provider.download_media(media_id, save_path)
                        if downloaded:
                            media_path = save_path
                            # Run OCR/Parser
                            extracted_text, _ = parse_attachment(save_path)
                            text_content = f"{caption}\n{extracted_text}".strip()
                        else:
                            text_content = caption or "[Media Attached]"
                    else:
                        text_content = caption or "[Media Attached]"

                # ── Look up or create Customer ─────────────────────────────────
                customer = db.query(Customer).filter(Customer.whatsapp_number == from_num).first()
                if not customer:
                    customer = Customer(
                        whatsapp_number=from_num,
                        contact_person_name=profile_name,
                        first_contact_at=utc_now(),
                        last_contact_at=utc_now()
                    )
                    db.add(customer)
                    db.commit()
                    db.refresh(customer)
                else:
                    if profile_name and not customer.contact_person_name:
                        customer.contact_person_name = profile_name
                    customer.last_contact_at = utc_now()
                    db.commit()

                # ── Look up or create Active Conversation ──────────────────────
                conversation = (
                    db.query(Conversation)
                    .filter(Conversation.customer_id == customer.id, Conversation.status == "ACTIVE")
                    .order_by(Conversation.id.desc())
                    .first()
                )
                if not conversation:
                    conversation = Conversation(
                        customer_id=customer.id,
                        status="ACTIVE",
                        stage="NEW"
                    )
                    db.add(conversation)
                    db.commit()
                    db.refresh(conversation)

                # ── Store Inbound Message (Idempotent) ─────────────────────────
                db_msg = Message(
                    conversation_id=conversation.id,
                    whatsapp_message_id=msg_id,
                    direction="INBOUND",
                    message_type=msg_type,
                    text=text_content,
                    media_reference=media_path,
                    processing_status="PENDING"
                )
                db.add(db_msg)
                db.commit()

                # ── Enqueue to Burst Debounce Queue ────────────────────────────
                background_tasks.add_task(
                    enqueue_customer_message,
                    whatsapp_number=from_num,
                    message_data={"text": text_content, "type": msg_type}
                )

    return {"status": "ok"}
