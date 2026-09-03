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
    path = settings.SHARED_EXCEL_PATH if os.path.exists(settings.SHARED_EXCEL_PATH) else settings.EXCEL_EXPORT_PATH
    if os.path.exists(path):
        return FileResponse(
            path,
            filename="WhatsApp_Electrical_Leads.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    return {"error": "Excel file not generated yet."}
