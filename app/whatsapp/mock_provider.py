"""
mock_provider.py — Mock WhatsApp Provider for automated testing and CI.
"""

from typing import List, Dict, Optional
from app.whatsapp.base import WhatsAppProvider

class MockWhatsAppProvider(WhatsAppProvider):

    def __init__(self):
        self.sent_messages: List[Dict[str, str]] = []

    async def send_text_message(self, to_number: str, text: str) -> bool:
        self.sent_messages.append({"to": to_number, "text": text})
        return True

    async def download_media(self, media_id_or_url: str, save_path: str) -> bool:
        return True

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        return challenge

    def clear(self):
        self.sent_messages.clear()
