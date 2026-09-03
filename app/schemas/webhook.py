from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class WebhookMessage(BaseModel):
    id: str
    from_number: str
    from_name: Optional[str] = None
    timestamp: int
    type: str  # text, image, document, audio, etc.
    text: Optional[str] = None
    media_url: Optional[str] = None
    media_id: Optional[str] = None
    mime_type: Optional[str] = None
    filename: Optional[str] = None

class WebhookPayload(BaseModel):
    messages: List[WebhookMessage]
