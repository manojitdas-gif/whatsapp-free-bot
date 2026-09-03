"""
base.py — Abstract WhatsApp Provider Interface.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

class WhatsAppProvider(ABC):

    @abstractmethod
    async def send_text_message(self, to_number: str, text: str) -> bool:
        """Sends a plain text WhatsApp message."""
        pass

    @abstractmethod
    async def download_media(self, media_id_or_url: str, save_path: str) -> bool:
        """Downloads an attachment from WhatsApp servers."""
        pass

    @abstractmethod
    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Verifies webhook subscription handshake."""
        pass
