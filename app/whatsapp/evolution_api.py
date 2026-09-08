"""
evolution_api.py - Evolution API Provider Adapter (Free and Unlimited).
"""
import re
import os
import httpx
import logging
from typing import Optional
from app.whatsapp.base import WhatsAppProvider
from app.config import settings

logger = logging.getLogger(__name__)

class EvolutionAPIProvider(WhatsAppProvider):
    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None, instance_name: Optional[str] = None):
        self.api_url = (api_url or getattr(settings, 'EVOLUTION_API_URL', '') or getattr(settings, 'GATEWAY_API_URL', '') or '').rstrip('/')
        self.api_key = api_key or getattr(settings, 'EVOLUTION_API_KEY', '') or getattr(settings, 'GATEWAY_API_TOKEN', '') or ''
        self.instance_name = instance_name or getattr(settings, 'EVOLUTION_INSTANCE_NAME', 'whatsapp-bot-v2') or 'whatsapp-bot-v2'

    def _format_phone(self, phone: str) -> str:
        digits = re.sub(r'[^0-9]', '', phone)
        if len(digits) == 10:
            digits = '91' + digits
        return digits

    async def _resolve_active_instance(self) -> str:
        """Dynamically finds the currently open WhatsApp instance on Evolution API."""
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get(f'{self.api_url}/instance/fetchInstances', headers={'apikey': self.api_key})
                if res.status_code == 200:
                    instances = res.json()
                    for inst in instances:
                        if inst.get('connectionStatus') == 'open':
                            return inst.get('name')
        except Exception:
            pass
        return self.instance_name or 'whatsapp-bot-v2'

    async def send_text_message(self, to_number: str, text: str) -> bool:
        clean_p = self._format_phone(to_number)
        active_inst = await self._resolve_active_instance()
        endpoint = f'{self.api_url}/message/sendText/{active_inst}'
        headers = {'apikey': self.api_key, 'Content-Type': 'application/json'}
        payload = {'number': clean_p, 'text': text}
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(endpoint, json=payload, headers=headers)
                if res.status_code in (200, 201):
                    logger.info('[EVOLUTION API] Message sent successfully to %s via %s', to_number, active_inst)
                    return True
                else:
                    logger.error('[EVOLUTION API ERROR] Status %d: %s', res.status_code, res.text)
                    return False
        except Exception as e:
            logger.error('[EVOLUTION API SEND FAILED] %s', e)
            return False

    async def download_media(self, media_id_or_url: str, save_path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            if media_id_or_url.startswith("data:") or len(media_id_or_url) > 200 and not media_id_or_url.startswith("http"):
                # Raw base64 string
                import base64
                b64 = media_id_or_url
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                with open(save_path, "wb") as f:
                    f.write(base64.b64decode(b64))
                return True

            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(media_id_or_url)
                if res.status_code == 200:
                    with open(save_path, 'wb') as f:
                        f.write(res.content)
                    return True
        except Exception as e:
            logger.error('[EVOLUTION API DOWNLOAD FAILED] %s', e)
        return False

    async def download_media_from_message(self, message_data: dict, save_path: str) -> bool:
        """Downloads media directly from Evolution API message object using getBase64FromMediaMessage."""
        import base64
        try:
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            active_inst = await self._resolve_active_instance()
            endpoint = f"{self.api_url}/chat/getBase64FromMediaMessage/{active_inst}"
            headers = {"apikey": self.api_key, "Content-Type": "application/json"}
            payload = {"message": message_data, "convertToMp4": False}
            async with httpx.AsyncClient(timeout=35.0) as client:
                res = await client.post(endpoint, json=payload, headers=headers)
                if res.status_code in (200, 201):
                    data = res.json()
                    b64 = data.get("base64", "")
                    if b64:
                        if "," in b64:
                            b64 = b64.split(",", 1)[1]
                        with open(save_path, "wb") as f:
                            f.write(base64.b64decode(b64))
                        logger.info("[EVOLUTION API] Media downloaded and saved to %s", save_path)
                        return True
                logger.warning("[EVOLUTION API] getBase64 returned status %d: %s", res.status_code, res.text[:200])
        except Exception as e:
            logger.error("[EVOLUTION API MEDIA DECODE FAILED] %s", e)
        return False

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        return challenge
