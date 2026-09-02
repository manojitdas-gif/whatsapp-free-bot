"""
whatsapp_web_engine.py — 100% Free Local WhatsApp Engine for PC.

FEATURES:
  - 100% Free Forever: Zero third-party API fees, zero subscriptions, zero quotas.
  - Unlimited Customers: Chat and capture leads with unlimited numbers.
  - Persistent Session: Saved in data/whatsapp_web_profile. Scan QR code once.
  - Real-Time Integration:
      * Pure product extraction via document_analyzer.py
      * Strict 10-column Excel logging via excel_logger.py
      * Strict turn-based state machine via conversation_flow.py (1s for Step 1, 3s for Steps 2/3).
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
    mark_bot_reply_sent,
    get_step_message,
)
from excel_logger import log_customer_lead, flush_pending_excel_queue
from document_analyzer import parse_product_details, analyze_file

IST = timezone(timedelta(hours=5, minutes=30))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(BASE_DIR, "data", "whatsapp_web_profile")
FILES_DIR = os.path.join(BASE_DIR, "data", "customer_files")
QR_IMAGE_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "SCAN_WHATSAPP_QR.png")

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

# Step delay seconds: 1s for step 1, 3s for step 2 & 3
STEP_DELAYS = {1: 1.0, 2: 3.0, 3: 3.0}

def _start_cloud_health_server():
    """Lightweight HTTP server so Render / Koyeb free web service stays 100% active."""
    import http.server
    import socketserver
    import threading

    port = int(os.environ.get("PORT", 8080))
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"WhatsApp 24/7 Engine is ONLINE!")
        def log_message(self, format, *args):
            pass

    try:
        httpd = socketserver.TCPServer(("", port), HealthHandler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        print(f"[HEALTH] Cloud health endpoint listening on port {port}", flush=True)
    except Exception as e:
        print(f"[HEALTH WARNING] {e}", flush=True)

_start_cloud_health_server()

# Keep track of handled incoming messages to avoid duplicates
processed_messages = set()


def sanitize_phone(raw: str) -> str:
    cleaned = re.sub(r'[^0-9]', '', raw)
    if cleaned.startswith("91") and len(cleaned) == 12:
        return cleaned
    if len(cleaned) == 10:
        return "91" + cleaned
    return cleaned


async def wait_for_login(page) -> bool:
    """
    Checks if WhatsApp Web is logged in or if QR code is shown.
    Saves QR code image to Desktop if scanning is needed.
    """
    print("[SESSION] Checking WhatsApp Web login status...", flush=True)

    attempt = 0
    qr_printed = False
    while True:
        attempt += 1
        # Check if chat list is visible (already logged in)
        chat_pane = await page.query_selector('div[id="pane-side"]')
        if chat_pane:
            print("[SESSION] ✅ WhatsApp Web is LOGGED IN and READY!", flush=True)
            if os.path.exists(QR_IMAGE_PATH):
                try:
                    os.remove(QR_IMAGE_PATH)
                except Exception:
                    pass
            return True

        # Check if QR reload button appeared and click it to keep QR fresh
        reload_btn = await page.query_selector('span[data-icon="refresh"]') or await page.query_selector('div[role="button"]:has(span[data-icon="refresh"])')
        if reload_btn:
            try:
                await reload_btn.click()
                await asyncio.sleep(1)
            except Exception:
                pass

        # Check if QR code is visible
        qr_canvas = await page.query_selector('canvas') or await page.query_selector('div[data-ref]')
        if qr_canvas:
            await qr_canvas.screenshot(path=QR_IMAGE_PATH)
            try:
                from PIL import Image, ImageOps
                with Image.open(QR_IMAGE_PATH) as im:
                    im_padded = ImageOps.expand(im, border=45, fill="white")
                    im_padded.save(QR_IMAGE_PATH)
            except Exception:
                pass

            if not qr_printed:
                print(f"[ACTION REQUIRED] 📱 Please scan QR code with your WhatsApp! (Saved to Desktop: {os.path.basename(QR_IMAGE_PATH)})", flush=True)
                qr_printed = True

        await asyncio.sleep(2)


async def send_reply(page, text: str) -> bool:
    """Sends a text message through WhatsApp Web active chat."""
    try:
        # Selector for message input box in WhatsApp Web
        input_box = (
            await page.query_selector('footer div[contenteditable="true"]')
            or await page.query_selector('div[data-tab="10"][contenteditable="true"]')
            or await page.query_selector('div[role="textbox"][contenteditable="true"]')
        )
        if not input_box:
            print("[SEND ERROR] Message input box not found in active chat.", flush=True)
            return False

        await input_box.click(force=True)
        await asyncio.sleep(0.2)

        # Type message multiline if needed
        lines = text.split("\n")
        for idx, line in enumerate(lines):
            await page.keyboard.type(line)
            if idx < len(lines) - 1:
                await page.keyboard.down("Shift")
                await page.keyboard.press("Enter")
                await page.keyboard.up("Shift")

        await asyncio.sleep(0.2)
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.5)
        return True
    except Exception as e:
        print(f"[SEND ERROR] Failed to send reply: {e}", flush=True)
        return False


async def process_chat(page, chat_item) -> None:
    """Reads unread messages from a chat, logs to Excel, and replies."""
    try:
        # Dismiss any popup or dialog that might block clicks
        modal = await page.query_selector('div[role="dialog"]')
        if modal:
            close_btn = (
                await modal.query_selector('button[aria-label="Close"]')
                or await modal.query_selector('div[role="button"]:has-text("Close")')
                or await modal.query_selector('button:has-text("Not now")')
            )
            if close_btn:
                await close_btn.click(force=True)
            else:
                await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)

        await chat_item.click(force=True)
        await asyncio.sleep(0.8)

        # 1. Extract contact name / phone from chat header
        header_title_el = await page.query_selector('header span[title]') or await page.query_selector('header div[role="button"] span')
        contact_title = await header_title_el.inner_text() if header_title_el else "Customer"
        contact_title = contact_title.strip()

        # Determine phone number
        phone_match = re.search(r'\+?\d[\d\s-]{8,15}\d', contact_title)
        if phone_match:
            phone = sanitize_phone(phone_match.group(0))
            name = "Customer"
        else:
            name = contact_title
            # Fallback: check profile info or clean title
            phone = sanitize_phone(contact_title) if re.search(r'\d{10}', contact_title) else sanitize_phone(contact_title)

        if not phone:
            # If name has no digits, use hash/name for session
            phone = "91" + re.sub(r'[^0-9]', '', str(abs(hash(contact_title))))[:10]

        # 2. Extract latest incoming messages (div.message-in or false_ prefix)
        incoming_elements = await page.query_selector_all('div.message-in, div[data-id*="false_"]')
        if not incoming_elements:
            return

        latest_el = incoming_elements[-1]
        msg_text = ""

        # Check for text
        text_el = await latest_el.query_selector('span.selectable-text') or await latest_el.query_selector('.copyable-text')
        if text_el:
            msg_text = (await text_el.inner_text()).strip()

        # Check for image
        img_el = await latest_el.query_selector('img[src*="blob:"]')
        analyzed_products = ""
        if img_el:
            img_time = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
            saved_img_path = os.path.join(FILES_DIR, f"{phone}_{img_time}.png")
            try:
                await img_el.screenshot(path=saved_img_path)
                print(f"[MEDIA] Incoming image saved to {os.path.basename(saved_img_path)}. Analyzing with OCR...", flush=True)
                summary, _ = analyze_file(saved_img_path, ".png")
                analyzed_products = summary
                if not msg_text:
                    msg_text = f"[PHOTO: {os.path.basename(saved_img_path)}]"
            except Exception as e:
                print(f"[OCR ERROR] {e}")

        # Check for document
        doc_el = await latest_el.query_selector('span[title*="."]') or await latest_el.query_selector('div[title*="."]')
        if doc_el:
            doc_title = await doc_el.get_attribute("title") or "document.pdf"
            if not msg_text:
                msg_text = f"[DOCUMENT: {doc_title}]"

        # Unique key for deduplication
        msg_key = f"{phone}:{msg_text}:{len(incoming_elements)}"
        if msg_key in processed_messages:
            return
        processed_messages.add(msg_key)

        now_str = datetime.now(IST).strftime("%H:%M:%S")
        print(f"\n[{now_str}] 📩 Incoming WhatsApp Web Chat: {name} ({phone})", flush=True)
        print(f"         Content: {msg_text[:70]}", flush=True)

        # 3. State Transition
        current_step, can_advance = register_customer_incoming_message(phone, msg_text)

        # 4. Instant Logging to 10-Column Excel
        is_req = (current_step in (0, 1))
        is_biz = (current_step == 2)
        log_customer_lead(
            sender_phone=phone,
            sender_name=name,
            message_text=msg_text,
            analyzed_products=analyzed_products,
            is_requirement_step=is_req,
            is_business_step=is_biz,
        )

        # 5. Send automated reply if eligible
        if can_advance and current_step in (0, 1, 2):
            target_step = current_step + 1
            delay = STEP_DELAYS.get(target_step, 2.0)
            reply_text = get_step_message(target_step)

            if reply_text:
                print(f"         ⏳ Pausing {delay}s before Step {target_step} reply...", flush=True)
                await asyncio.sleep(delay)

                print(f"         🚀 Sending Step {target_step} reply...", flush=True)
                success = await send_reply(page, reply_text)
                if success:
                    mark_bot_reply_sent(phone, target_step)
                    print(f"         ✅ Step {target_step} delivered successfully!", flush=True)

    except Exception as e:
        print(f"[PROCESS ERROR] Error processing chat: {e}", flush=True)


async def main():
    print("=" * 60)
    print("  🤖  WhatsApp Web Free Automation Engine (100% Free Forever)")
    print("=" * 60)
    print("  📱  Engine Mode     : Local WhatsApp Web (Playwright)")
    print("  💸  API Cost        : ₹0.00 (Zero Subscriptions / Zero Limits)")
    print("  👥  Customers       : UNLIMITED (No Quota Limits)")
    print(f"  📊  Desktop Excel   : WhatsApp_Conversations.xlsx & SHARED.xlsx")
    print("=" * 60, flush=True)

    async with async_playwright() as p:
        # Launch persistent browser so login stays saved forever
        context = await p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=True,
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

        is_logged_in = await wait_for_login(page)
        if not is_logged_in:
            print("[ERROR] Login timeout. Please restart and scan the QR code.", flush=True)
            return

        print("🟢 Engine is ACTIVE! Listening 24/7 for unread customer chats...", flush=True)

        while True:
            try:
                # 1. Look for unread chats in left pane using robust evaluator
                unread_item_handle = await page.evaluate_handle('''() => {
                    const listItems = document.querySelectorAll('div#pane-side div[role="listitem"]');
                    for (const item of listItems) {
                        // Check for aria-label containing unread
                        if (item.querySelector('span[aria-label*="unread"]')) return item;
                        
                        // Check for badge with number of unread messages
                        const spans = item.querySelectorAll('span');
                        for (const s of spans) {
                            const txt = (s.innerText || '').trim();
                            if (/^\\d+$/.test(txt) && parseInt(txt) > 0 && parseInt(txt) < 100) {
                                const parentAria = s.parentElement ? (s.parentElement.getAttribute('aria-label') || '') : '';
                                if (parentAria.includes('unread') || s.classList.length > 0) {
                                    return item;
                                }
                            }
                        }
                    }
                    return null;
                }''')

                unread_chat = unread_item_handle.as_element()
                if unread_chat:
                    await process_chat(page, unread_chat)
                else:
                    # 2. Also check if currently active chat has an unhandled incoming message
                    active_header = await page.query_selector('div#main header')
                    if active_header:
                        latest_in = await page.query_selector('div#main div.message-in:last-child')
                        if latest_in:
                            text_el = await latest_in.query_selector('span.selectable-text') or await latest_in.query_selector('.copyable-text')
                            if text_el:
                                cur_text = (await text_el.inner_text()).strip()
                                # Check if already processed
                                title_el = await active_header.query_selector('span[title]')
                                cur_title = (await title_el.inner_text()).strip() if title_el else "Customer"
                                phone_match = re.search(r'\\+?\\d[\\d\\s-]{8,15}\\d', cur_title)
                                cur_phone = sanitize_phone(phone_match.group(0)) if phone_match else sanitize_phone(cur_title)
                                active_key = f"{cur_phone}:{cur_text}:active"
                                if active_key not in processed_messages:
                                    # Process currently open chat
                                    active_item = await page.evaluate_handle('() => document.querySelector("div#pane-side div[role=\'listitem\'][aria-selected=\'true\']") || document.querySelector("div#pane-side div[role=\'listitem\']")')
                                    if active_item and active_item.as_element():
                                        await process_chat(page, active_item.as_element())
                                        processed_messages.add(active_key)

                flush_pending_excel_queue()
                await asyncio.sleep(1.0)

            except Exception as e:
                print(f"[LOOP WARNING] {e}", flush=True)
                await asyncio.sleep(2.0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
