"""
whatsapp_web_engine.py — 100% Free 24/7 WhatsApp Bot Engine.

FULL FLOW:
  1. Customer sends first message (anything)
     → Bot waits 2 seconds → sends Step 1 reply (ask requirements + photo)

  2. Customer shares requirements/photos/documents
     → Bot waits until customer STOPS typing (2s silence)
     → VALIDATES: did customer actually share product requirements?
       ✓ YES → waits 2s → sends Step 2 reply (ask business details)
       ✗ NO  → waits 2s → sends polite retry: "please share your requirements"

  3. Customer shares business details (name, GST, address, contact)
     → Bot waits until customer STOPS typing (2s silence)
     → VALIDATES: did customer share business details?
       ✓ YES → waits 2s → sends Step 3 reply (thank you, team will connect)
       ✗ NO  → waits 2s → sends polite retry: "please share business details"

  4. DONE — bot logs silently, no more automated replies.

DEDUPLICATION:
  - Each phone number's last processed message is tracked.
  - The bot never replies twice to the same message.
  - Excel is written ONCE per real new message, not on every loop tick.
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

from conversation_flow import (
    register_customer_incoming_message,
    record_customer_message_time,
    has_customer_stopped_typing,
    mark_bot_reply_sent,
    get_step_message,
    get_retry_message,
    validate_step1_reply,
    validate_step2_reply,
)
from excel_logger import log_customer_lead, flush_pending_excel_queue
from document_analyzer import parse_product_details, analyze_file

IST = timezone(timedelta(hours=5, minutes=30))
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(BASE_DIR, "data", "whatsapp_web_profile")
FILES_DIR   = os.path.join(BASE_DIR, "data", "customer_files")
QR_IMAGE_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "SCAN_WHATSAPP_QR.png")

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

# ── TIMING CONFIG ──────────────────────────────────────────────────────────────
STEP1_DELAY_S  = 2.0   # Wait 2s after first message → send Step 1
TYPING_WAIT_S  = 2.0   # Wait 2s of silence → treat as "stopped typing"
STEP_REPLY_DELAY_S = 2.0  # After stop-typing detected → wait 2s → send reply

# ── DEDUPLICATION — track last processed message per phone ────────────────────
# { phone: {"text": str, "timestamp": float, "pending_reply": bool} }
_last_seen: dict = {}


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
            print("[SESSION] ✅ Logged in and ready!", flush=True)
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
                    print(f"[QR] 📱 Please scan the QR code! Saved to Desktop: {os.path.basename(QR_IMAGE_PATH)}", flush=True)
                    qr_saved = True
            except Exception:
                pass

        if attempt > 150:  # 5 minute timeout
            return False
        await asyncio.sleep(2)


# ──────────────────────────────────────────────────────────────────────────────
# REPLY SENDER
# ──────────────────────────────────────────────────────────────────────────────

async def send_reply(page, text: str) -> bool:
    """Types and sends a WhatsApp message in the currently open chat."""
    try:
        # Find the message input composer
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

        # Type multi-line message (Shift+Enter for new lines)
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
    Uses JavaScript for reliable DOM traversal.
    """
    return await page.evaluate('''() => {
        const rows = Array.from(document.querySelectorAll(
            'div#main div[role="row"], div#main .message-in, div#main .message-out'
        ));
        const seen = new Set();
        return rows.map(r => {
            const textEl = r.querySelector('span.selectable-text') || r.querySelector('.copyable-text');
            const text = textEl ? textEl.innerText.trim() : '';
            if (!text || seen.has(text)) return null;
            seen.add(text);
            const isOut = (
                r.classList.contains('message-out') ||
                r.closest('.message-out') !== null ||
                (r.dataset.id && r.dataset.id.startsWith('true_'))
            );
            return { text, isOut };
        }).filter(Boolean);
    }''')


# ──────────────────────────────────────────────────────────────────────────────
# IMAGE / DOCUMENT ANALYZER
# ──────────────────────────────────────────────────────────────────────────────

async def extract_media(page, phone: str) -> tuple:
    """
    Checks for images or documents in div#main.
    Returns (analyzed_text: str, has_image: bool, has_doc: bool)
    """
    analyzed = ""
    has_image = False
    has_doc = False

    img_el = await page.query_selector('div#main .message-in img[src*="blob:"]')
    if img_el:
        has_image = True
        ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(FILES_DIR, f"{phone}_{ts}.png")
        try:
            await img_el.screenshot(path=save_path)
            print(f"[MEDIA] Image saved → {os.path.basename(save_path)}, running OCR...", flush=True)
            summary, _ = analyze_file(save_path, ".png")
            analyzed = summary
        except Exception as e:
            print(f"[OCR ERROR] {e}", flush=True)

    if not has_image:
        doc_el = await page.query_selector('div#main .message-in span[title*="."], div#main .message-in div[title*="."]')
        if doc_el:
            has_doc = True
            doc_name = await doc_el.get_attribute("title") or "document"
            analyzed = f"[Document: {doc_name}]"

    return analyzed, has_image, has_doc


# ──────────────────────────────────────────────────────────────────────────────
# PROCESS A SINGLE CHAT (opened in div#main)
# ──────────────────────────────────────────────────────────────────────────────

async def process_active_chat(page) -> None:
    """
    Main processing logic for the chat currently open in div#main.
    Implements 2-second stop-typing detection and per-step validation.
    """
    global _last_seen

    # Get contact info from header
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
        name = "Customer"
    else:
        name = contact_title
        phone = sanitize_phone(contact_title) if re.search(r'\d{10}', contact_title) else ""

    if not phone:
        phone = "91" + re.sub(r'[^0-9]', '', str(abs(hash(contact_title))))[:10]

    # Extract all visible messages
    messages = await extract_chat_messages(page)
    if not messages:
        return

    # Find the latest incoming (customer) message
    incoming = [m for m in messages if not m['isOut']]
    if not incoming:
        return

    latest_msg = incoming[-1]['text']

    # ── FILTER: reject if this is actually one of the bot's own reply messages ──
    # (Sometimes WhatsApp Web mis-classifies the bot's own sent message as incoming
    #  for a split second before the DOM updates the 'message-out' class.)
    BOT_REPLY_PREFIXES = (
        "🙏 *Thank you for contacting us!",
        "✅ *Thank you for sharing your requirements!",
        "🙏 *Thanks for sharing all the details!",
        "🙏 *Thank you for sharing all your details!",
        "📋 *Please share your product requirements!",
        "🏢 *Please share your business details!",
    )
    if any(latest_msg.startswith(p[:30]) for p in BOT_REPLY_PREFIXES):
        return  # This is the bot's own message — skip

    # ── DEDUPLICATION: skip if this is the same message we already processed ──
    prev = _last_seen.get(phone, {})
    if prev.get("text") == latest_msg:
        # Message unchanged — nothing new from the customer
        return

    # New incoming message detected!
    _last_seen[phone] = {"text": latest_msg, "recorded": False, "pending_reply": True, "arrived_at": time.time()}
    record_customer_message_time(phone)
    _last_seen[phone]["recorded"] = True

    now_str = datetime.now(IST).strftime("%H:%M:%S")
    print(f"\n[{now_str}] 📩 New msg from {name} ({phone}): '{latest_msg[:60]}'", flush=True)

    # ── Get current state ─────────────────────────────────────────────────────
    current_step, can_advance = register_customer_incoming_message(phone, latest_msg)

    if not can_advance:
        print(f"         [WAIT] Step {current_step} — bot replied, waiting for customer's next message.", flush=True)
        return

    # ── STEP 0 → Reply immediately after 2s (Step 1 message) ─────────────────
    if current_step == 0:
        print(f"         ⏳ Step 0: waiting {STEP1_DELAY_S}s then sending Step 1...", flush=True)
        await asyncio.sleep(STEP1_DELAY_S)
        reply = get_step_message(1)
        success = await send_reply(page, reply)
        if success:
            # Pass the customer's triggering message so state machine knows what was replied to
            mark_bot_reply_sent(phone, 1, triggered_by_text=latest_msg)
            # Keep _last_seen text as latest_msg (do NOT reset to "") —
            # so next loop tick the same "Hi" is not re-processed as a new message.
            _last_seen[phone]["pending_reply"] = False

            # Log to Excel (first contact)
            log_customer_lead(
                sender_phone=phone,
                sender_name=name,
                message_text=latest_msg,
                is_requirement_step=False,
                is_business_step=False,
            )
            print(f"         ✅ Step 1 sent to {phone}!", flush=True)
        return

    # ── STEP 1 or 2: wait until customer stops typing (2s silence) ───────────
    if current_step in (1, 2):
        print(f"         ⏳ Step {current_step}: waiting for customer to stop typing ({TYPING_WAIT_S}s silence)...", flush=True)

        # Poll for silence — check if more messages arrive
        silence_start = time.time()
        while True:
            await asyncio.sleep(0.5)

            # Re-check messages — has customer sent another one?
            messages_now = await extract_chat_messages(page)
            incoming_now = [m for m in messages_now if not m['isOut']]
            if incoming_now and incoming_now[-1]['text'] != latest_msg:
                # Customer sent another message — update and restart silence wait
                latest_msg = incoming_now[-1]['text']
                _last_seen[phone]["text"] = latest_msg
                record_customer_message_time(phone)
                silence_start = time.time()
                print(f"         [TYPING] Customer still sending messages...", flush=True)
                continue

            # Check if we've had TYPING_WAIT_S seconds of silence
            if (time.time() - silence_start) >= TYPING_WAIT_S:
                break

        print(f"         ✓ Customer stopped typing. Analyzing...", flush=True)
        await asyncio.sleep(STEP_REPLY_DELAY_S)

        # Extract media
        analyzed, has_image, has_doc = await extract_media(page, phone)

        # Build final message text (collect ALL incoming messages since last bot reply)
        messages_final = await extract_chat_messages(page)
        incoming_final = [m['text'] for m in messages_final if not m['isOut']]
        combined_text = "\n".join(incoming_final[-5:])  # Last 5 customer messages

        if current_step == 1:
            # Validate: did customer share requirements?
            valid = validate_step1_reply(combined_text, has_image, has_doc)
            if valid:
                # Log requirements to Excel
                req_text = analyzed if analyzed else parse_product_details(combined_text)
                log_customer_lead(
                    sender_phone=phone,
                    sender_name=name,
                    message_text=combined_text,
                    analyzed_products=req_text,
                    is_requirement_step=True,
                    is_business_step=False,
                )
                # Send Step 2
                reply = get_step_message(2)
                success = await send_reply(page, reply)
                if success:
                    # Store the customer message that triggered this reply — so state machine
                    # won't fire again until a genuinely NEW customer message arrives.
                    mark_bot_reply_sent(phone, 2, triggered_by_text=latest_msg)
                    _last_seen[phone]["pending_reply"] = False
                    # Do NOT reset text to "" — keep latest_msg so deduplication works correctly
                    print(f"         ✅ Step 2 sent to {phone}!", flush=True)
            else:
                # Validation failed — send retry, but do NOT advance step.
                # Record combined_text as last_replied_text so the SAME message
                # won't re-trigger this retry forever — customer must send something new.
                print(f"         ⚠ Step 1 validation — asking customer to share requirements.", flush=True)
                retry = get_retry_message(1)
                await send_reply(page, retry)
                mark_bot_reply_sent(phone, 1, triggered_by_text=latest_msg)  # Stay at step 1 but lock
                _last_seen[phone]["pending_reply"] = False
                print(f"         🔁 Requirements request sent to {phone}.", flush=True)

        elif current_step == 2:
            # Validate: did customer share business details?
            valid = validate_step2_reply(combined_text, has_image, has_doc)
            if valid:
                # Log business details to Excel
                log_customer_lead(
                    sender_phone=phone,
                    sender_name=name,
                    message_text=combined_text,
                    analyzed_products="",
                    is_requirement_step=False,
                    is_business_step=True,
                )
                # Send Step 3
                reply = get_step_message(3)
                success = await send_reply(page, reply)
                if success:
                    mark_bot_reply_sent(phone, 3, triggered_by_text=latest_msg)
                    _last_seen[phone]["pending_reply"] = False
                    print(f"         ✅ Step 3 sent to {phone}! Flow complete.", flush=True)
            else:
                print(f"         ⚠ Step 2 validation — asking customer to share business details.", flush=True)
                retry = get_retry_message(2)
                await send_reply(page, retry)
                mark_bot_reply_sent(phone, 2, triggered_by_text=latest_msg)  # Stay at step 2 but lock
                _last_seen[phone]["pending_reply"] = False
                print(f"         🔁 Business details request sent to {phone}.", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# OPEN UNREAD CHAT FROM SIDEBAR
# ──────────────────────────────────────────────────────────────────────────────

async def open_unread_chat(page, span_el) -> bool:
    """Click a chat in pane-side to open it. Returns True if successful."""
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
    print("  📱  Mode     : Local WhatsApp Web (Playwright)", flush=True)
    print("  💸  Cost     : ₹0.00 Forever", flush=True)
    print("  ✅  Flow     : Step 1 → Step 2 → Step 3 (with validation)", flush=True)
    print("  📊  Excel    : Raw data only, 10 columns, Desktop files", flush=True)
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
                # ── Dismiss popups ──────────────────────────────────────────
                for _ in range(2):
                    close_btn = await page.query_selector(
                        'span[data-icon="x-alt"], span[data-icon="x"], button[aria-label="Close"]'
                    )
                    if close_btn:
                        try: await close_btn.click(); await asyncio.sleep(0.3)
                        except Exception: pass

                # ── Scan sidebar for ALL unread chats ──────────────────────
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

                # ── Also check the currently visible open chat ──────────────
                if await page.query_selector('div#main header'):
                    await process_active_chat(page)

                # ── Flush any pending Excel writes ──────────────────────────
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
