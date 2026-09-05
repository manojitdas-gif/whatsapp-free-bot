"""
green_api.py — WhatsApp-compatible cloud gateway provider (No Meta account required).
Supports Green API, Evolution API, and Baileys-based self-hosted gateways.
"""

import os
import re
import httpx
import logging
from typing import Optional, Dict, Any
from app.whatsapp.base import WhatsAppProvider
from app.config import settings

logger = logging.getLogger(__name__)

class GreenAPIProvider(WhatsAppProvider):
    def __init__(
        self,
        instance_id: Optional[str] = None,
        api_token: Optional[str] = None,
        api_url: Optional[str] = None
    ):
        self.instance_id = instance_id or settings.GATEWAY_INSTANCE_ID or ""
        self.api_token = api_token or settings.GATEWAY_API_TOKEN or ""
        self.api_url = (api_url or settings.GATEWAY_API_URL or "https://api.green-api.com").rstrip("/")

    def _format_chat_id(self, phone: str) -> str:
        digits = re.sub(r'[^0-9]', '', phone)
        if len(digits) == 10:
            digits = "91" + digits
        return digits + "@c.us"

    async def send_text_message(self, to_number: str, text: str) -> bool:
        if not self.instance_id or not self.api_token:
            logger.warning("[GATEWAY] Instance ID or API Token not configured. Simulated dispatch: %s -> %s", to_number, text[:40])
            return True

        chat_id = self._format_chat_id(to_number)
        endpoint = f"{self.api_url}/waInstance{self.instance_id}/sendMessage/{self.api_token}"
        payload = {
            "chatId": chat_id,
            "message": text
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(endpoint, json=payload)
                if res.status_code == 200:
                    logger.info("[GATEWAY] Message sent successfully to %s", to_number)
                    return True
                else:
                    logger.error("[GATEWAY ERROR] Status %d: %s", res.status_code, res.text)
                    return False
        except Exception as e:
            logger.error("[GATEWAY SEND FAILED] %s", e)
            return False

    async def download_media(self, media_id_or_url: str, save_path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(media_id_or_url)
                if res.status_code == 200:
                    with open(save_path, "wb") as f:
                        f.write(res.content)
                    return True
        except Exception as e:
            logger.error("[GATEWAY DOWNLOAD FAILED] %s", e)
        return False

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        return challenge
