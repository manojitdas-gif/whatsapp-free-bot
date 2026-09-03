"""
meta_cloud.py — Official Meta WhatsApp Cloud API Provider Adapter.
"""

import httpx
from typing import Optional
from app.whatsapp.base import WhatsAppProvider
from app.config import settings

class MetaCloudWhatsAppProvider(WhatsAppProvider):

    def __init__(self):
        self.api_url = settings.WHATSAPP_API_URL
        self.access_token = settings.WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.verify_token = settings.WEBHOOK_VERIFY_TOKEN

    async def send_text_message(self, to_number: str, text: str) -> bool:
        if not self.access_token or not self.phone_number_id:
            print(f"[META CLOUD API] Missing ACCESS_TOKEN or PHONE_NUMBER_ID. Simulating send to {to_number}.")
            return True

        clean_number = "".join(filter(str.isdigit, to_number))
        url = f"{self.api_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_number,
            "type": "text",
            "text": {"preview_url": False, "body": text}
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code in (200, 201):
                    return True
                print(f"[META API ERROR] Status {res.status_code}: {res.text}")
                return False
        except Exception as e:
            print(f"[META API EXCEPTION] {e}")
            return False

    async def download_media(self, media_id_or_url: str, save_path: str) -> bool:
        if not self.access_token:
            return False
        try:
            # 1. Get media URL
            url = f"{self.api_url}/{media_id_or_url}"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code != 200:
                    return False
                direct_url = res.json().get("url")
                if not direct_url:
                    return False
                # 2. Download binary
                dl_res = await client.get(direct_url, headers=headers)
                if dl_res.status_code == 200:
                    with open(save_path, "wb") as f:
                        f.write(dl_res.content)
                    return True
            return False
        except Exception as e:
            print(f"[META DOWNLOAD ERROR] {e}")
            return False

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        if mode == "subscribe" and token == self.verify_token:
            return challenge
        return None
