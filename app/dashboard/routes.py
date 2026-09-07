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
from app.exports.excel_exporter import HEADERS, format_ist_timestamp, format_phone_display, _write_to_workbook, _excel_lock
from app.config import settings

router = APIRouter(prefix="", tags=["Dashboard"])

templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)

@router.get("/scan", response_class=HTMLResponse)
async def live_qr_scanner():
    """Live interactive QR code scanner with auto-refresh every 10s."""
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Scan WhatsApp QR Code — 24/7 Cloud Bot</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
    .card { background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 32px; max-width: 440px; width: 100%; text-align: center; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.5); }
    h1 { font-size: 20px; margin-top: 0; margin-bottom: 8px; color: #38bdf8; }
    p { font-size: 14px; color: #94a3b8; margin-bottom: 20px; }
    .qr-box { background: white; padding: 16px; border-radius: 12px; display: inline-block; min-width: 250px; min-height: 250px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2); }
    img { width: 250px; height: 250px; display: block; }
    .status { margin-top: 20px; font-size: 14px; font-weight: 500; padding: 8px 16px; border-radius: 9999px; display: inline-block; background: #334155; color: #cbd5e1; }
    .status.connected { background: #065f46; color: #34d399; font-size: 16px; padding: 12px 24px; }
    .instructions { text-align: left; font-size: 13px; color: #cbd5e1; margin-top: 24px; background: #0f172a; padding: 16px; border-radius: 8px; line-height: 1.6; }
  </style>
</head>
<body>
  <div class="card">
    <h1>📱 Link WhatsApp to Cloud</h1>
    <p>Live QR Code (Auto-refreshes every 10 seconds)</p>
    <div class="qr-box">
      <img id="qr-img" src="" alt="Loading QR code..." />
    </div>
    <div id="status-badge" class="status">Connecting to Evolution API...</div>
    <div class="instructions">
      <strong>How to Scan:</strong><br>
      1. Open <strong>WhatsApp</strong> on your phone (<code>+91 6290 164 699</code>)<br>
      2. Tap <strong>Settings</strong> &rarr; <strong>Linked Devices</strong><br>
      3. Tap <strong>Link a Device</strong> &rarr; Scan this screen!
    </div>
  </div>
  <script>
    const serverUrl = "https://whatsapp-gateway-nsr1.onrender.com";
    const apiKey = "mysecretkey123";
    const instance = "whatsapp-bot";
    let isConnected = false;
    async function checkState() {
      try {
        const res = await fetch(`${serverUrl}/instance/connectionState/${instance}`, { headers: { "apikey": apiKey } });
        const data = await res.json();
        const state = data?.instance?.state;
        if (state === "open") {
          isConnected = true;
          document.getElementById("status-badge").className = "status connected";
          document.getElementById("status-badge").innerHTML = "✅ WhatsApp Connected Successfully!";
          document.querySelector(".qr-box").innerHTML = "<div style='color:#065f46;font-size:48px;padding:80px 0;'>✓</div>";
        }
      } catch (e) {}
    }
    async function refreshQR() {
      if (isConnected) return;
      try {
        const res = await fetch(`${serverUrl}/instance/connect/${instance}`, { headers: { "apikey": apiKey } });
        const data = await res.json();
        if (data.base64) {
          document.getElementById("qr-img").src = data.base64;
          document.getElementById("status-badge").innerText = "Scan QR code with your phone camera";
        }
      } catch (e) {
        document.getElementById("status-badge").innerText = "Retrying connection to cloud...";
      }
    }
    checkState();
    refreshQR();
    setInterval(() => { checkState(); refreshQR(); }, 10000);
    setInterval(checkState, 3000);
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

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
async def export_excel_download(db: Session = Depends(get_db)):
    """Download on-demand the latest 9-column Excel file generated dynamically from the database."""
    excel_path = os.path.join(settings.DATA_DIR, "WhatsApp_Conversations.xlsx")
    customers = db.query(Customer).order_by(Customer.id.asc()).all()
    for cust in customers:
        try:
            with _excel_lock:
                _write_to_workbook(excel_path, cust)
        except Exception:
            pass

    if not os.path.exists(excel_path):
        if os.path.exists(settings.EXCEL_EXPORT_PATH):
            excel_path = settings.EXCEL_EXPORT_PATH
        elif os.path.exists(settings.SHARED_EXCEL_PATH):
            excel_path = settings.SHARED_EXCEL_PATH

    if os.path.exists(excel_path):
        return FileResponse(
            excel_path,
            filename="WhatsApp_Conversations.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    return {"error": "No records found in database yet."}

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

@router.get("/api/clear-customer")
async def clear_customer_from_db(phone: str = Query(...), db: Session = Depends(get_db)):
    """Completely deletes all traces of a customer number from DB so they start 100% fresh."""
    import re
    from app.ai.conversation_agent import reset_phone_guard_record
    phone_digits = re.sub(r"[^0-9]", "", phone)[-10:]
    try:
        reset_phone_guard_record(phone_digits)
        customers = db.query(Customer).filter(Customer.whatsapp_number.like(f"%{phone_digits}%")).all()
        for cust in customers:
            convs = db.query(Conversation).filter(Conversation.customer_id == cust.id).all()
            for c in convs:
                db.query(Message).filter(Message.conversation_id == c.id).delete()
                db.delete(c)
            db.delete(cust)
        db.commit()

        save_dir = os.path.join(settings.DATA_DIR, "customer_files")
        if os.path.exists(save_dir):
            for f in os.listdir(save_dir):
                if f.startswith(f"{phone_digits}_"):
                    try:
                        os.remove(os.path.join(save_dir, f))
                    except Exception:
                        pass

        return {"status": "ok", "phone": phone_digits, "message": f"Customer {phone_digits} completely cleared from database! You can now test from scratch!"}
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

