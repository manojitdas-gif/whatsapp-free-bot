"""
whatsapp_web_engine.py — 100% Free WhatsApp Web Automation Engine (Zero Meta Account Needed).

Runs on your existing WhatsApp Business number (+91 6290 164 699) for ₹0.00 forever.
Features:
  1. No Meta account, No API tokens, No paid subscriptions needed.
  2. data-pre-plain-text DOM extraction (100% accurate customer & bot message separation).
  3. Real Playwright pointer clicks for unread chats in sidebar.
  4. 1.5–2.0s stop-typing silence debounce before replying.
  5. Multi-message electrical entity extractor (Products, Quantities, Specs, GSTIN, Address, Company, Name).
  6. Exact 3 primary responses (Response 1, Response 2, Response 3) matching Master Prompt.
  7. Exact 9-column Excel sync (in-place row updates, no duplicate rows).
  8. Local SQLite + Live Admin Web Dashboard at http://localhost:8080/admin.
"""

import os
import sys
import re
import time
import asyncio
from datetime import datetime, timezone, timedelta

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

from playwright.async_api import async_playwright

from app.config import settings
from app.ai.extractor import analyze_conversation
from app.conversation.decision_engine import evaluate_conversation_completeness
from app.conversation.templates import RESPONSE_1, RESPONSE_2, RESPONSE_3, get_response_template
from app.conversation.state_machine import ConversationStage, ConversationStatus
from app.exports.excel_exporter import sync_customer_to_excel
from app.database.session import SessionLocal, init_db
from app.database.models import Customer, Conversation, Message, ResponseLog, utc_now
from app.documents.ocr_engine import run_image_ocr

IST = timezone(timedelta(hours=5, minutes=30))
BASE_DIR    = settings.BASE_DIR
SESSION_DIR = os.path.join(settings.DATA_DIR, "whatsapp_web_profile")
FILES_DIR   = os.path.join(settings.DATA_DIR, "customer_files")
QR_IMAGE_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "SCAN_WHATSAPP_QR.png")

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

DEBOUNCE_SILENCE_S = settings.DEBOUNCE_SECONDS  # 1.5s
REPLY_WAIT_S = 1.0

_last_processed_msg: dict = {}
_last_sent_response: dict = {}

BOT_REPLY_PREFIXES = (
    "🙏 *Thank you for sharing all your details!",
    "🙏 Thank you for sharing all your details!",
    "🙏 *Thank you for contacting us!",
    "🙏 Thank you for contacting us!",
    "✅ *Thank you for sharing your requirements!",
    "✅ Thank you for sharing your requirements!",
    "Thank you for sharing all your details",
    "Thank you for contacting us",
    "Thank you for sharing your requirements",
)


def _start_cloud_health_server():
    """Starts background dashboard/health server on port 8080."""
    import threading, uvicorn
    def run_server():
        try:
            uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, log_level="warning")
        except Exception as e:
            print(f"[SERVER ERROR] {e}", flush=True)
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    print(f"[HEALTH/ADMIN] Web Dashboard live on http://localhost:{settings.PORT}/admin", flush=True)

_start_cloud_health_server()
init_db()


def sanitize_phone(raw: str) -> str:
    c = re.sub(r'[^0-9]', '', raw)
    if c.startswith("91") and len(c) == 12:
        return c
    if len(c) == 10:
        return "91" + c
    return c


def _is_bot_reply(text: str) -> bool:
    t = text.strip()
    return any(t.startswith(p[:20]) for p in BOT_REPLY_PREFIXES)


# ──────────────────────────────────────────────────────────────────────────────
# LOGIN HANDLER
# ──────────────────────────────────────────────────────────────────────────────

async def wait_for_login(page) -> bool:
    print("[SESSION] Checking WhatsApp Web session...", flush=True)
    attempt = 0
    qr_saved = False
    while True:
        attempt += 1
        if await page.query_selector('div#pane-side'):
            print("[SESSION] ✅ Logged in to WhatsApp Web!", flush=True)
            if os.path.exists(QR_IMAGE_PATH):
                try: os.remove(QR_IMAGE_PATH)
                except Exception: pass
            return True

        reload_btn = (
            await page.query_selector('span[data-icon="refresh"]')
            or await page.query_selector('div[role="button"]:has(span[data-icon="refresh"])')
        )
        if reload_btn:
            try: await reload_btn.click(); await asyncio.sleep(1)
            except Exception: pass

        qr_el = await page.query_selector('canvas') or await page.query_selector('div[data-ref]')
        if qr_el:
            try:
                await qr_el.screenshot(path=QR_IMAGE_PATH)
                if not qr_saved:
                    print(f"[QR] 📱 Scan QR saved to Desktop: {os.path.basename(QR_IMAGE_PATH)}", flush=True)
                    qr_saved = True
            except Exception:
                pass

        if attempt > 150:
            return False
        await asyncio.sleep(2)


# ──────────────────────────────────────────────────────────────────────────────
# REPLY SENDER
# ──────────────────────────────────────────────────────────────────────────────

async def send_reply(page, text: str) -> bool:
    try:
        input_box = None
        for _ in range(15):
            input_box = (
                await page.query_selector('footer [contenteditable="true"]')
                or await page.query_selector('[contenteditable="true"][data-tab="10"]')
                or await page.query_selector('footer [role="textbox"]')
                or await page.query_selector('[contenteditable="true"][role="textbox"]')
                or await page.query_selector('div[title="Type a message"]')
            )
            if input_box:
                break
            await asyncio.sleep(0.3)

        if not input_box:
            all_editable = await page.query_selector_all('[contenteditable="true"]')
            input_box = all_editable[-1] if all_editable else None

        if not input_box:
            print("[SEND ERROR] WhatsApp input box not found.", flush=True)
            return False

        await input_box.click(force=True, timeout=4000)
        await asyncio.sleep(0.3)

        lines = text.split("\n")
        for idx, line in enumerate(lines):
            await page.keyboard.type(line)
            if idx < len(lines) - 1:
                await page.keyboard.down("Shift")
                await page.keyboard.press("Enter")
                await page.keyboard.up("Shift")

        await asyncio.sleep(0.3)
        await page.keyboard.press("Enter")
        await asyncio.sleep(1.0)
        return True

    except Exception as e:
        print(f"[SEND ERROR] {e}", flush=True)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# MESSAGE EXTRACTOR (Using data-pre-plain-text & DOM)
# ──────────────────────────────────────────────────────────────────────────────

async def extract_chat_messages(page) -> list:
    return await page.evaluate('''() => {
        const results = [];
        const main = document.querySelector('div#main');
        if (!main) return results;

        const textNodes = Array.from(main.querySelectorAll('div.copyable-text[data-pre-plain-text]'));
        for (const el of textNodes) {
            const pre = el.getAttribute('data-pre-plain-text') || '';
            const isOut = pre.includes('] You:') || pre.includes('] you:');
            const spanText = el.querySelector('span.selectable-text') || el;
            const text = spanText ? spanText.innerText.trim() : '';
            if (text) {
                results.push({
                    text: text,
                    isOut: isOut,
                    hasImg: false
                });
            }
        }

        const imgs = Array.from(main.querySelectorAll('img[src*="blob:"]'));
        for (const img of imgs) {
            const closestRow = img.closest('div[role="row"]') || img.parentElement;
            const isOut = closestRow ? (closestRow.innerText.includes('You:') || closestRow.className.includes('out')) : false;
            results.push({
                text: '[Image Attached]',
                isOut: isOut,
                hasImg: true
            });
        }

        return results;
    }''')


# ──────────────────────────────────────────────────────────────────────────────
# PROCESS ACTIVE CHAT PIPELINE
# ──────────────────────────────────────────────────────────────────────────────

async def process_active_chat(page) -> None:
    global _last_processed_msg, _last_sent_response

    header_el = await page.query_selector('div#main header')
    if not header_el:
        return

    contact_title = (await header_el.inner_text()).strip()
    phone_m = re.search(r'\+?\d[\d\s\-]{8,15}\d', contact_title)
    if phone_m:
        phone = sanitize_phone(phone_m.group(0))
        name  = "Customer"
    else:
        name  = contact_title.split("\n")[0].strip()
        phone = sanitize_phone(contact_title) if re.search(r'\d{10}', contact_title) else ""

    if not phone:
        phone = "91" + re.sub(r'[^0-9]', '', str(abs(hash(contact_title))))[:10]

    messages = await extract_chat_messages(page)
    if not messages:
        return

    # Inbound customer messages only
    incoming = [m for m in messages if not m['isOut']]
    if not incoming:
        return

    latest_msg = incoming[-1]['text']

    if _is_bot_reply(latest_msg):
        return

    # Check if we already processed this exact latest message
    if _last_processed_msg.get(phone) == latest_msg:
        return

    now_str = datetime.now(IST).strftime("%H:%M:%S")
    print(f"\n[{now_str}] 📩 New customer interaction from {name} ({phone}): '{latest_msg[:60]}'", flush=True)

    # ── DEBOUNCE: Wait for 1.5–2.0s of silence after customer stops typing ─────
    print(f"         ⏳ Waiting {DEBOUNCE_SILENCE_S}s silence for customer burst to finish...", flush=True)
    silence_start = time.time()
    while True:
        await asyncio.sleep(0.4)
        msgs_now = await extract_chat_messages(page)
        incoming_now = [m for m in msgs_now if not m['isOut'] and not _is_bot_reply(m['text'])]

        if incoming_now and incoming_now[-1]['text'] != latest_msg:
            latest_msg = incoming_now[-1]['text']
            silence_start = time.time()
            print(f"         📝 Customer still sending... resetting silence timer.", flush=True)
            continue

        if (time.time() - silence_start) >= DEBOUNCE_SILENCE_S:
            break

    print(f"         ✓ Customer stopped typing. Analyzing complete conversation...", flush=True)
    _last_processed_msg[phone] = latest_msg

    # ── COLLECT ALL CHAT TEXT & OCR FROM IMAGES ───────────────────────────────
    all_msgs_final = await extract_chat_messages(page)
    all_incoming_texts = [m['text'] for m in all_msgs_final if not m['isOut'] and not _is_bot_reply(m['text'])]
    has_media = any(m.get('hasImg') for m in all_msgs_final if not m['isOut'])

    ocr_text = ""
    if has_media:
        try:
            img_els = await page.query_selector_all('div#main img[src*="blob:"]')
            for i, img_el in enumerate(img_els[-2:]):
                ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
                save_path = os.path.join(FILES_DIR, f"{phone}_{ts}_{i}.png")
                await img_el.screenshot(path=save_path, timeout=3000)
                extracted_ocr = run_image_ocr(save_path)
                if extracted_ocr:
                    ocr_text += f"\n{extracted_ocr}"
                    print(f"         📷 OCR extracted {len(extracted_ocr)} chars", flush=True)
        except Exception:
            pass

    # ── AI/NLP EXTRACTION ACROSS COMPLETE CONVERSATION ─────────────────────────
    attachment_texts = [ocr_text] if ocr_text else None
    extraction = analyze_conversation(
        messages_history=all_incoming_texts,
        attachment_texts=attachment_texts,
        profile_name=name if name != "Customer" else None
    )

    # ── DECISION ENGINE: EVALUATE COMPLETENESS & SELECT RESPONSE ───────────────
    response_type, audit_meta = evaluate_conversation_completeness(extraction, has_media=has_media)
    reply_text = get_response_template(response_type)

    # Avoid duplicate identical response if state has not changed
    if _last_sent_response.get(phone) == response_type:
        print(f"         [SILENT] State {response_type} already sent. Waiting for new details.", flush=True)
        return

    # ── SEND EXACT PRIMARY RESPONSE ───────────────────────────────────────────
    await asyncio.sleep(REPLY_WAIT_S)
    success = await send_reply(page, reply_text)
    if success:
        _last_sent_response[phone] = response_type
        print(f"         ✅ Sent {response_type} to {phone}!", flush=True)

    # ── DATABASE & 9-COLUMN EXCEL SYNCHRONIZATION ───────────────────────────────
    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.whatsapp_number == phone).first()
        if not customer:
            customer = Customer(
                whatsapp_number=phone,
                contact_person_name=extraction.contact_person_name or name,
                first_contact_at=utc_now(),
                last_contact_at=utc_now()
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)

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

        # Update Conversation Stage
        conv = (
            db.query(Conversation)
            .filter(Conversation.customer_id == customer.id, Conversation.status == ConversationStatus.ACTIVE.value)
            .order_by(Conversation.id.desc())
            .first()
        )
        if not conv:
            conv = Conversation(customer_id=customer.id, status=ConversationStatus.ACTIVE.value, stage=ConversationStage.NEW.value)
            db.add(conv)
            db.commit()
            db.refresh(conv)

        if response_type == "RESPONSE_1":
            conv.stage = ConversationStage.COMPLETED.value
            conv.status = ConversationStatus.COMPLETED.value
            conv.completed_at = utc_now()
        elif response_type == "RESPONSE_2":
            conv.stage = ConversationStage.WAITING_FOR_PRODUCT_REQUIREMENTS.value
        elif response_type == "RESPONSE_3":
            conv.stage = ConversationStage.WAITING_FOR_CUSTOMER_DETAILS.value

        db.commit()

        # Save to 9-column Excel & Live CSV (in-place row updates)
        sync_customer_to_excel(customer)
        print(f"         📊 Synced {phone} to 9-column Excel & Database!", flush=True)

    except Exception as e:
        print(f"[DB/EXCEL SYNC ERROR] {e}", flush=True)
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60, flush=True)
    print("  🤖 WhatsApp Automation System — 100% FREE (NO META ACCOUNT)", flush=True)
    print("=" * 60, flush=True)
    print("  📱 Phone    : +91 6290 164 699 (Existing WhatsApp Business)", flush=True)
    print("  💸 Cost     : ₹0.00 Forever (No Meta, No Paid APIs)", flush=True)
    print("  ⚡ Debounce : 1.5s silence before replying to message bursts", flush=True)
    print("  📋 Flow     : Exact 3 Master Responses (Response 1, 2, 3)", flush=True)
    print("  📊 Excel    : 9 Columns In-Place Row Sync", flush=True)
    print("  🌐 Dashboard: http://localhost:8080/admin", flush=True)
    print("=" * 60, flush=True)

    async with async_playwright() as p:
        headless = os.environ.get("HEADLESS", "true").lower() == "true"
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

        if not await wait_for_login(page):
            print("[ERROR] Login timeout. Please restart.", flush=True)
            return

        print("\n🟢 Engine ONLINE — Listening 24/7 for customer messages...\n", flush=True)

        while True:
            try:
                # ── Dismiss popups or lightbox modals ──────────────────────────
                close_btn = await page.query_selector(
                    'span[data-icon="x-alt"], span[data-icon="x"], button[aria-label="Close"]'
                )
                if close_btn:
                    try:
                        await close_btn.click(timeout=1000)
                        await asyncio.sleep(0.3)
                    except Exception:
                        pass

                # ── Scan sidebar for unread badges and click with Playwright ───
                badge = await page.query_selector(
                    'div#pane-side span[aria-label*="unread"], div#pane-side span[aria-label*="Unread"]'
                )
                if badge:
                    label = await badge.get_attribute("aria-label") or "unread message"
                    print(f"\n[UNREAD] Opening unread chat ({label})...", flush=True)
                    try:
                        await badge.click(force=True, timeout=4000)
                        await asyncio.sleep(1.5)
                        await process_active_chat(page)
                    except Exception as ce:
                        print(f"[CLICK ERROR] {ce}", flush=True)

                # ── Also process whatever chat is currently open in main ───────
                if await page.query_selector('div#main header'):
                    await process_active_chat(page)

                await asyncio.sleep(1.0)

            except Exception as e:
                print(f"[LOOP ERROR] {e}", flush=True)
                await asyncio.sleep(2.0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
