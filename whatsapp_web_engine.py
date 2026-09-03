"""
whatsapp_web_engine.py — 100% Free 24/7 WhatsApp Bot Engine.

FULL FLOW:
  1. Customer sends first message (any text, photo, file, document)
     → Bot waits 2s → sends Step 1 reply (ask requirements + photo)

  2. Customer shares requirements (text/photos/documents/PDFs/Excel/Word/anything)
     → Bot waits until customer STOPS for 2s (stop-typing detection)
     → VALIDATES: did customer share product requirements?
       ✓ YES → waits 2s → sends Step 2 reply (ask business details)
       ✗ NO  → sends polite retry: "please share your requirements"

  3. Customer shares business details (name, GST, address, contact — any format)
     → Bot waits until customer STOPS for 2s
     → VALIDATES: did customer share business info?
       ✓ YES → sends Step 3 reply (thank you, team will connect)
       ✗ NO  → sends polite retry: "please share your business details"

  4. DONE — bot logs silently, no more automated replies.

MEDIA HANDLING:
  - All customer images, photos, screenshots → OCR text extraction
  - PDF, Word, Excel, CSV files → text extraction
  - Multiple files supported per message (all collected)

EXCEL LOGGING (8 columns only):
  First Contact Date | Last Contact Date | Contact Name | WhatsApp Number
  | Email ID | Company/Business Name | GST Number | Complete Address

DEDUPLICATION:
  - Each phone's last processed message is tracked in memory
  - Bot never replies twice to the same message
  - Bot NEVER processes its own sent messages
"""

import os
import sys
import re
import time
import asyncio
import tempfile
from datetime import datetime, timezone, timedelta

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

from playwright.async_api import async_playwright

from conversation_flow import (
    register_customer_incoming_message,
    record_customer_message_time,
    mark_bot_reply_sent,
    get_step_message,
    get_retry_message,
    validate_step1_reply,
    validate_step2_reply,
)
from excel_logger import log_customer_lead, flush_pending_excel_queue
from document_analyzer import analyze_file, run_image_ocr

IST = timezone(timedelta(hours=5, minutes=30))
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(BASE_DIR, "data", "whatsapp_web_profile")
FILES_DIR   = os.path.join(BASE_DIR, "data", "customer_files")
QR_IMAGE_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "SCAN_WHATSAPP_QR.png")

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

# ── TIMING CONFIG ──────────────────────────────────────────────────────────────
STEP1_DELAY_S      = 2.0   # Wait 2s after first message → send Step 1
TYPING_SILENCE_S   = 2.0   # Silence duration = "customer stopped typing"
REPLY_DELAY_S      = 2.0   # After silence detected → wait 2s → send reply

# ── DEDUPLICATION — last seen message per phone ────────────────────────────────
# { phone: {"text": str, "arrived_at": float} }
_last_seen: dict = {}

# ── BOT OWN REPLY PREFIXES — filter these out from incoming detection ──────────
BOT_REPLY_PREFIXES = (
    "🙏 *Thank you for contacting us!",
    "✅ *Thank you for sharing your requirements!",
    "🙏 *Thanks for sharing all the details!",
    "🙏 *Thank you for sharing all your details!",
    "📋 *Please share your product requirements!",
    "🏢 *Please share your business details!",
    "⚠️ *Please share your product requirements",
    "⚠️ *Please share your business details",
    "Thank you for contacting us",
    "Thank you for sharing your requirements",
    "Thanks for sharing all the details",
    "Please share your product requirements",
    "Please share your business details",
)


def _start_cloud_health_server():
    import http.server, socketserver, threading
    port = int(os.environ.get("PORT", 8080))
    class H(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"WhatsApp 24/7 Engine ONLINE!")
        def log_message(self, *a): pass
    try:
        srv = socketserver.TCPServer(("", port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"[HEALTH] Listening on port {port}", flush=True)
    except Exception as e:
        print(f"[HEALTH] {e}", flush=True)

_start_cloud_health_server()


# ──────────────────────────────────────────────────────────────────────────────
# UTILITY
# ──────────────────────────────────────────────────────────────────────────────

def sanitize_phone(raw: str) -> str:
    c = re.sub(r'[^0-9]', '', raw)
    if c.startswith("91") and len(c) == 12:
        return c
    if len(c) == 10:
        return "91" + c
    return c


def _is_bot_reply(text: str) -> bool:
    """Returns True if text looks like one of the bot's own replies."""
    t = text.strip()
    return any(t.startswith(p[:25]) for p in BOT_REPLY_PREFIXES)


# ──────────────────────────────────────────────────────────────────────────────
# LOGIN HANDLER
# ──────────────────────────────────────────────────────────────────────────────

async def wait_for_login(page) -> bool:
    print("[SESSION] Checking WhatsApp Web login...", flush=True)
    attempt = 0
    qr_saved = False
    while True:
        attempt += 1
        if await page.query_selector('div[id="pane-side"]'):
            print("[SESSION] ✅ Logged in!", flush=True)
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
                try:
                    from PIL import Image, ImageOps
                    with Image.open(QR_IMAGE_PATH) as im:
                        ImageOps.expand(im, border=45, fill="white").save(QR_IMAGE_PATH)
                except Exception:
                    pass
                if not qr_saved:
                    print(f"[QR] 📱 Please scan QR → saved to Desktop: {os.path.basename(QR_IMAGE_PATH)}", flush=True)
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
        for _ in range(20):
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
            print("[SEND ERROR] Input box not found.", flush=True)
            return False

        await input_box.click(force=True)
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
# MESSAGE EXTRACTOR
# ──────────────────────────────────────────────────────────────────────────────

async def extract_chat_messages(page) -> list:
    """
    Returns list of {text, isOut} for all visible messages in div#main.
    De-duplicates consecutive identical messages.
    """
    return await page.evaluate('''() => {
        const rows = Array.from(document.querySelectorAll(
            'div#main div[role="row"], div#main .message-in, div#main .message-out'
        ));
        const results = [];
        const seen = new Set();
        for (const r of rows) {
            const textEl = r.querySelector('span.selectable-text') || r.querySelector('.copyable-text');
            const text = textEl ? textEl.innerText.trim() : '';
            if (!text) continue;
            const key = text.slice(0, 80);
            if (seen.has(key)) continue;
            seen.add(key);
            const isOut = (
                r.classList.contains('message-out') ||
                !!r.closest('.message-out') ||
                (r.dataset && r.dataset.id && r.dataset.id.startsWith('true_'))
            );
            results.push({ text, isOut });
        }
        return results;
    }''')


# ──────────────────────────────────────────────────────────────────────────────
# MEDIA COLLECTOR — download and analyze ALL customer images/files in the chat
# ──────────────────────────────────────────────────────────────────────────────

async def collect_all_media_text(page, phone: str) -> tuple:
    """
    Finds ALL customer images and documents currently visible in div#main.
    Downloads them, runs OCR/extraction on each, and returns combined text.

    Returns:
        (combined_ocr_text: str, has_any_media: bool)
    """
    all_text_parts = []
    has_media = False

    # ── Images (photos, screenshots) ──────────────────────────────────────────
    img_els = await page.query_selector_all('div#main .message-in img[src*="blob:"]')
    for i, img_el in enumerate(img_els):
        try:
            ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
            save_path = os.path.join(FILES_DIR, f"{phone}_{ts}_{i}.png")
            await img_el.screenshot(path=save_path)
            ocr_text = run_image_ocr(save_path)
            if ocr_text.strip():
                all_text_parts.append(ocr_text)
                print(f"[MEDIA] Image {i+1} OCR extracted {len(ocr_text)} chars", flush=True)
            has_media = True
        except Exception as e:
            print(f"[OCR] Image {i+1} error: {e}", flush=True)

    # ── Documents (PDF, Word, Excel, etc.) ────────────────────────────────────
    # WhatsApp shows document name in span[title] or div[title] inside .message-in
    doc_els = await page.query_selector_all('div#main .message-in span[title], div#main .message-in div[title]')
    for doc_el in doc_els:
        doc_name = (await doc_el.get_attribute("title") or "").strip()
        if not doc_name:
            continue
        ext = os.path.splitext(doc_name)[1].lower()
        if ext not in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt", ".png", ".jpg", ".jpeg"):
            continue

        # Try to find a download button near this doc element
        try:
            download_btn = await doc_el.evaluate_handle(
                'el => el.closest("div[role=\'button\']") || '
                'el.closest("[data-icon=\'download\']") || '
                'el.parentElement.querySelector("[data-icon=\'download\']")'
            )
            btn_el = download_btn.as_element()
            if btn_el:
                async with page.expect_download() as dl_info:
                    await btn_el.click()
                dl = await dl_info.value
                save_path = os.path.join(FILES_DIR, f"{phone}_{doc_name}")
                await dl.save_as(save_path)
                _, raw_text = analyze_file(save_path, ext)
                if raw_text.strip():
                    all_text_parts.append(raw_text)
                    print(f"[MEDIA] Document '{doc_name}' extracted {len(raw_text)} chars", flush=True)
                has_media = True
        except Exception as e:
            print(f"[MEDIA] Doc '{doc_name}' download/extract: {e}", flush=True)
            # Fall back: at least note the document name
            all_text_parts.append(f"Document: {doc_name}")
            has_media = True

    return "\n\n".join(all_text_parts), has_media


# ──────────────────────────────────────────────────────────────────────────────
# PROCESS ACTIVE CHAT
# ──────────────────────────────────────────────────────────────────────────────

async def process_active_chat(page) -> None:
    """
    Main processing logic for the chat open in div#main.
    - Detects new customer messages (text + any media)
    - Waits for 2s stop-typing silence
    - Validates content per step
    - Sends appropriate reply
    - Logs extracted data to 8-column Excel
    """
    global _last_seen

    # ── Get contact info ───────────────────────────────────────────────────────
    header_el = (
        await page.query_selector('header span[title]')
        or await page.query_selector('header div[role="button"] span')
    )
    if not header_el:
        return

    contact_title = (await header_el.inner_text()).strip()
    phone_m = re.search(r'\+?\d[\d\s\-]{8,15}\d', contact_title)
    if phone_m:
        phone = sanitize_phone(phone_m.group(0))
        name  = "Customer"
    else:
        name  = contact_title
        phone = sanitize_phone(contact_title) if re.search(r'\d{10}', contact_title) else ""

    if not phone:
        phone = "91" + re.sub(r'[^0-9]', '', str(abs(hash(contact_title))))[:10]

    # ── Extract all visible messages ───────────────────────────────────────────
    messages = await extract_chat_messages(page)
    if not messages:
        return

    # Get all incoming messages (customer's)
    incoming = [m for m in messages if not m['isOut']]
    if not incoming:
        return

    latest_msg = incoming[-1]['text']

    # ── Filter out bot's own reply being misclassified ─────────────────────────
    if _is_bot_reply(latest_msg):
        return

    # ── Deduplication ──────────────────────────────────────────────────────────
    prev = _last_seen.get(phone, {})
    if prev.get("text") == latest_msg:
        return  # Same message — nothing new

    # ── New message detected! ──────────────────────────────────────────────────
    _last_seen[phone] = {"text": latest_msg, "arrived_at": time.time()}
    record_customer_message_time(phone)

    now_str = datetime.now(IST).strftime("%H:%M:%S")
    print(f"\n[{now_str}] 📩 New msg from {name} ({phone}): '{latest_msg[:60]}'", flush=True)

    # ── State machine ──────────────────────────────────────────────────────────
    current_step, can_advance = register_customer_incoming_message(phone, latest_msg)

    if not can_advance:
        print(f"         [WAIT] Step {current_step} — waiting for customer's next reply.", flush=True)
        return

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 0: First message from customer → send Step 1 after 2s
    # ══════════════════════════════════════════════════════════════════════════
    if current_step == 0:
        print(f"         ⏳ First message → sending Step 1 in {STEP1_DELAY_S}s...", flush=True)
        await asyncio.sleep(STEP1_DELAY_S)

        success = await send_reply(page, get_step_message(1))
        if success:
            mark_bot_reply_sent(phone, 1, triggered_by_text=latest_msg)
            # Log first contact — name from WhatsApp profile, no requirements yet
            log_customer_lead(
                sender_phone=phone,
                sender_name=name,
                message_text=latest_msg,
                ocr_text="",
                requirements="",
            )
            print(f"         ✅ Step 1 sent to {phone}!", flush=True)
        return

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1 or STEP 2: Wait for stop-typing (2s silence), then validate & reply
    # ══════════════════════════════════════════════════════════════════════════
    if current_step in (1, 2):
        print(f"         ⏳ Step {current_step}: waiting for customer to stop sending ({TYPING_SILENCE_S}s silence)...", flush=True)

        # ── Poll until customer has been silent for TYPING_SILENCE_S seconds ──
        # If customer keeps sending (texts, photos, files) — keep waiting.
        # If customer stops replying entirely — bot also stops (no auto reply).
        silence_start = time.time()
        while True:
            await asyncio.sleep(0.5)

            msgs_now = await extract_chat_messages(page)
            incoming_now = [m for m in msgs_now if not m['isOut'] and not _is_bot_reply(m['text'])]

            if incoming_now and incoming_now[-1]['text'] != latest_msg:
                # Customer sent more — reset silence timer, keep waiting
                latest_msg = incoming_now[-1]['text']
                _last_seen[phone]["text"] = latest_msg
                record_customer_message_time(phone)
                silence_start = time.time()
                print(f"         📝 Customer still sending... waiting for silence.", flush=True)
                continue

            if (time.time() - silence_start) >= TYPING_SILENCE_S:
                break  # Customer stopped for 2s — now process

        print(f"         ✓ Customer stopped. Collecting all messages and media...", flush=True)

        # ── Collect ALL customer text messages (up to last 10) ────────────────
        all_msgs_final = await extract_chat_messages(page)
        all_incoming   = [m['text'] for m in all_msgs_final if not m['isOut'] and not _is_bot_reply(m['text'])]
        combined_customer_text = "\n".join(all_incoming[-10:])

        # ── Collect ALL customer media (images, docs, screenshots, PDFs, etc.) ─
        ocr_text, has_media = await collect_all_media_text(page, phone)

        # Pause before sending reply
        await asyncio.sleep(REPLY_DELAY_S)

        # ══════════════════════════════════════════════════════════════════════
        # STEP 1: Customer should share product requirements
        # ══════════════════════════════════════════════════════════════════════
        if current_step == 1:
            valid = validate_step1_reply(combined_customer_text, has_image=has_media, has_document=has_media)

            if valid:
                # Parse product requirements from all customer text + OCR text
                from document_analyzer import parse_product_details
                all_text_for_req = "\n".join(filter(None, [combined_customer_text, ocr_text]))
                parsed_req = parse_product_details(all_text_for_req)
                # If parser didn't extract structured items, use raw customer text (cleaned)
                if not parsed_req:
                    parsed_req = combined_customer_text[:1000]

                # Save to Excel: requirements + any entity data found in text
                log_customer_lead(
                    sender_phone=phone,
                    sender_name=name,
                    message_text=combined_customer_text,
                    ocr_text=ocr_text,
                    requirements=parsed_req,
                )

                # Send Step 2
                success = await send_reply(page, get_step_message(2))
                if success:
                    mark_bot_reply_sent(phone, 2, triggered_by_text=latest_msg)
                    print(f"         ✅ Step 2 sent to {phone}!", flush=True)
            else:
                # Customer sent irrelevant data — send specific error message
                error_msg = (
                    "⚠️ *Please share your product requirements correctly!*\n\n"
                    "We need the following details to prepare your quotation:\n"
                    "📦 *Product name* and description\n"
                    "🔢 *Quantity* required\n"
                    "📐 *Size / Specifications*\n\n"
                    "📎 You can also share a *photo, catalogue, PDF or any document*."
                )
                await send_reply(page, error_msg)
                mark_bot_reply_sent(phone, 1, triggered_by_text=latest_msg)
                print(f"         ⚠ Requirements error message sent to {phone}.", flush=True)

        # ══════════════════════════════════════════════════════════════════════
        # STEP 2: Customer should share business details
        # ══════════════════════════════════════════════════════════════════════
        elif current_step == 2:
            valid = validate_step2_reply(combined_customer_text, has_image=has_media, has_document=has_media)

            if valid:
                # Save business details to Excel (same row, fills empty cells only)
                log_customer_lead(
                    sender_phone=phone,
                    sender_name=name,
                    message_text=combined_customer_text,
                    ocr_text=ocr_text,
                    requirements="",  # Don't overwrite requirements at this step
                )

                # Send Step 3
                success = await send_reply(page, get_step_message(3))
                if success:
                    mark_bot_reply_sent(phone, 3, triggered_by_text=latest_msg)
                    print(f"         ✅ Step 3 sent to {phone}! Flow complete.", flush=True)
            else:
                # Customer didn't share business details — specific error message
                error_msg = (
                    "⚠️ *Please share your business details correctly!*\n\n"
                    "We need the following to process your quotation:\n"
                    "🏢 *Company / Business Name*\n"
                    "📋 *GST Number* (if applicable)\n"
                    "📍 *Complete Business Address* (with pin code)\n"
                    "👤 *Contact Person Name*\n\n"
                    "📎 You can also share a *visiting card or letterhead photo*."
                )
                await send_reply(page, error_msg)
                mark_bot_reply_sent(phone, 2, triggered_by_text=latest_msg)
                print(f"         ⚠ Business details error message sent to {phone}.", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# OPEN UNREAD CHAT FROM SIDEBAR
# ──────────────────────────────────────────────────────────────────────────────

async def open_unread_chat(page, span_el) -> bool:
    try:
        row = await span_el.evaluate_handle(
            'el => el.closest("div[role=\'listitem\']") || el.closest("div[tabindex]") || el.parentElement'
        )
        row_el = row.as_element() or span_el
        await row_el.click(force=True)
        await asyncio.sleep(2.0)
        return True
    except Exception as e:
        print(f"[OPEN CHAT ERROR] {e}", flush=True)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60, flush=True)
    print("  🤖  WhatsApp Free Bot — 100% Automatic 24/7", flush=True)
    print("=" * 60, flush=True)
    print("  📱  Mode    : Local WhatsApp Web (Playwright)", flush=True)
    print("  💸  Cost    : ₹0.00 Forever", flush=True)
    print("  ✅  Flow    : Step 1 → Step 2 → Step 3 (with validation)", flush=True)
    print("  📊  Excel   : 9 columns — with Requirements Details", flush=True)
    print("  📎  Media   : Photos, PDFs, Word, Excel, Screenshots supported", flush=True)
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
            print("[ERROR] Login timeout. Restart and scan QR code.", flush=True)
            return

        print("\n🟢 Engine ACTIVE — Listening 24/7 for customer messages...\n", flush=True)

        while True:
            try:
                # ── Dismiss popups ─────────────────────────────────────────────
                for _ in range(2):
                    close_btn = await page.query_selector(
                        'span[data-icon="x-alt"], span[data-icon="x"], button[aria-label="Close"]'
                    )
                    if close_btn:
                        try: await close_btn.click(); await asyncio.sleep(0.3)
                        except Exception: pass

                # ── Scan sidebar for ALL unread chats ──────────────────────────
                unread_chats = await page.evaluate('''() => {
                    const spans = Array.from(document.querySelectorAll('div#pane-side span[title]'));
                    return spans.map(s => {
                        const title = s.getAttribute('title');
                        const row = s.closest('div[role="listitem"]') || s.closest('div[tabindex]') || s.parentElement;
                        const badge = row ? (
                            row.querySelector('span[aria-label*="unread"]') ||
                            row.querySelector('span[aria-label*="Unread"]')
                        ) : null;
                        return badge ? { title, label: badge.getAttribute('aria-label') } : null;
                    }).filter(Boolean);
                }''')

                for uchat in unread_chats:
                    title = uchat['title']
                    print(f"\n[UNREAD] Found: '{title}' ({uchat['label']})", flush=True)
                    span_el = await page.query_selector(f'div#pane-side span[title="{title}"]')
                    if span_el:
                        opened = await open_unread_chat(page, span_el)
                        if opened:
                            await process_active_chat(page)

                # ── Also check the currently visible open chat ──────────────────
                if await page.query_selector('div#main header'):
                    await process_active_chat(page)

                # ── Flush pending Excel queue ───────────────────────────────────
                flush_pending_excel_queue()

                await asyncio.sleep(1.0)

            except Exception as e:
                print(f"[LOOP ERROR] {e}", flush=True)
                await asyncio.sleep(3.0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
