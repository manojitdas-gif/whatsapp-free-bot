"""
local_web.py — Local Playwright WhatsApp Web provider adapter.
"""

from typing import Optional
from app.whatsapp.base import WhatsAppProvider

class LocalWebWhatsAppProvider(WhatsAppProvider):

    def __init__(self):
        pass

    async def send_text_message(self, to_number: str, text: str) -> bool:
        # Re-use existing send_reply function if browser context is active
        try:
            from whatsapp_web_engine import send_reply, _page_instance
            if _page_instance:
                return await send_reply(_page_instance, text)
        except Exception:
            pass
        return True

    async def download_media(self, media_id_or_url: str, save_path: str) -> bool:
        return True

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        return challenge
