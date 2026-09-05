"""
routes.py — Admin Dashboard endpoints for customer inspection, search, stats, and Excel download.
"""

import os
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.database.models import Customer, Conversation, Message
from app.exports.excel_exporter import HEADERS, format_ist_timestamp, format_phone_display
from app.config import settings

router = APIRouter(prefix="", tags=["Dashboard"])

templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    total_customers = db.query(Customer).count()
    completed_enquiries = db.query(Conversation).filter(Conversation.stage == "COMPLETED").count()
    waiting_reqs = db.query(Conversation).filter(Conversation.stage == "WAITING_FOR_PRODUCT_REQUIREMENTS").count()
    waiting_details = db.query(Conversation).filter(Conversation.stage == "WAITING_FOR_CUSTOMER_DETAILS").count()

    customers = db.query(Customer).order_by(Customer.last_contact_at.desc()).limit(100).all()

    content = templates.env.get_template("index.html").render({
        "request": request,
        "total_customers": total_customers,
        "completed_enquiries": completed_enquiries,
        "waiting_reqs": waiting_reqs,
        "waiting_details": waiting_details,
        "customers": customers,
        "format_phone": format_phone_display,
        "format_ts": format_ist_timestamp,
    })
    return HTMLResponse(content=content)

@router.get("/api/customer/{customer_id}/messages")
async def get_customer_messages(customer_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.customer_id == customer_id).order_by(Conversation.id.desc()).first()
    if not conv:
        return []
    msgs = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.id.asc()).all()
    return [{
        "id": m.id,
        "direction": m.direction,
        "type": m.message_type,
        "text": m.text,
        "timestamp": format_ist_timestamp(m.timestamp)
    } for m in msgs]

@router.get("/export/excel")
async def export_excel_download():
    """Download on-demand the latest 9-column Excel file."""
    path = settings.EXCEL_EXPORT_PATH if os.path.exists(settings.EXCEL_EXPORT_PATH) else settings.SHARED_EXCEL_PATH
    if os.path.exists(path):
        return FileResponse(
            path,
            filename="WhatsApp_Conversations.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    return {"error": "Excel file not generated yet."}

@router.get("/api/reset-phone")
async def reset_phone_guard(phone: str = Query(...)):
    """
    Emergency: Clear phone_flow_guard so the bot starts completely fresh from Step 1.
    Usage: /api/reset-phone?phone=8765197073
    """
    import re
    from app.ai.conversation_agent import reset_phone_guard_record
    phone_digits = re.sub(r"[^0-9]", "", phone)[-10:]
    try:
        reset_phone_guard_record(phone_digits)
        return {"status": "ok", "phone": phone_digits, "message": f"Phone {phone_digits} reset fresh. Next message starts from Step 1 (Response 2)!"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@router.get("/api/db-status")
async def db_status(phone: str = Query(None)):
    """Check phone_flow_guard state on Render's cloud DB."""
    import sqlite3
    try:
        db_path = os.path.join(settings.DATA_DIR, "whatsapp_production.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        if phone:
            cur.execute("SELECT phone, response_1_sent, response_2_sent, response_3_sent, is_completed, COALESCE(post_help_sent,0), last_response, COALESCE(reset_at,0) FROM phone_flow_guard WHERE phone = ?", (phone,))
            rows = cur.fetchall()
        else:
            cur.execute("SELECT phone, response_1_sent, response_2_sent, response_3_sent, is_completed, COALESCE(post_help_sent,0), last_response, COALESCE(reset_at,0) FROM phone_flow_guard ORDER BY rowid DESC LIMIT 20")
            rows = cur.fetchall()
        conn.close()
        return {"records": [{"phone": r[0], "r1": r[1], "r2": r[2], "r3": r[3], "completed": r[4], "post_help_sent": r[5], "last_response": r[6], "reset_at": r[7]} for r in rows]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@router.get("/api/full-reset")
async def full_reset_phone(phone: str = Query(...), db: Session = Depends(get_db)):
    """
    Full wipe of ALL data for a phone number across ALL tables.
    Clears: customers, conversations, messages, phone_flow_guard.
    Use this to test the complete bot flow fresh from a phone number.
    Usage: /api/full-reset?phone=8765197073
    """
    import re
    from app.ai.conversation_agent import reset_phone_guard_record
    phone_digits = re.sub(r"[^0-9]", "", phone)[-10:]
    results = {}

    try:
        # 1. Find and delete customer + related records via SQLAlchemy
        from app.database.models import Customer, Conversation, Message, ResponseLog, ExtractedData
        all_customers = db.query(Customer).all()
        matched_customers = [c for c in all_customers if re.sub(r"[^0-9]", "", str(c.whatsapp_number or ""))[-10:] == phone_digits]

        deleted_customers = 0
        deleted_convs = 0
        deleted_msgs = 0

        for cust in matched_customers:
            convs = db.query(Conversation).filter(Conversation.customer_id == cust.id).all()
            for conv in convs:
                db.query(Message).filter(Message.conversation_id == conv.id).delete()
                deleted_msgs += 1
                db.delete(conv)
                deleted_convs += 1
            try:
                db.query(ExtractedData).filter(ExtractedData.customer_id == cust.id).delete()
            except Exception:
                pass
            try:
                db.query(ResponseLog).filter(ResponseLog.customer_id == cust.id).delete()
            except Exception:
                pass
            db.delete(cust)
            deleted_customers += 1
        db.commit()
        results["customers_deleted"] = deleted_customers
        results["conversations_deleted"] = deleted_convs
        results["messages_deleted"] = deleted_msgs

        # 2. Reset phone_flow_guard with current timestamp so all old chat history is ignored
        reset_phone_guard_record(phone_digits)
        results["guard_reset"] = True

        results["status"] = "ok"
        results["phone"] = phone_digits
        results["message"] = f"Phone {phone_digits} fully wiped & reset fresh. Ready for complete bot flow test!"
        return results
    except Exception as e:
        db.rollback()
        return {"status": "error", "detail": str(e)}

