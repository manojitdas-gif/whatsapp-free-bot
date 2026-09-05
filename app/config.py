import os
from typing import Optional
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "WhatsApp Requirement Automation System"
    ENVIRONMENT: str = "production"
    DEBUG: bool = False
    PORT: int = 8080
    HOST: str = "0.0.0.0"

    # Timezone
    TIMEZONE: str = "Asia/Kolkata"

    # Database
    DATABASE_URL: str = "sqlite:///./data/whatsapp_production.db"

    # WhatsApp Provider: "meta_cloud", "local_web", or "mock"
    WHATSAPP_PROVIDER: str = "local_web"

    # Meta Cloud API Config (When using Meta provider)
    WHATSAPP_API_URL: str = "https://graph.facebook.com/v19.0"
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WEBHOOK_VERIFY_TOKEN: str = "whatsapp_verify_token_2026"

    # Burst Debounce (Silence duration before processing message burst in seconds)
    DEBOUNCE_SECONDS: float = 1.5

    # Storage paths
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR: str = os.path.join(BASE_DIR, "data")
    MEDIA_DIR: str = os.path.join(BASE_DIR, "data", "media")
    EXCEL_EXPORT_PATH: str = os.path.join(os.path.expanduser("~"), "Desktop", "WhatsApp_Conversations.xlsx")
    SHARED_EXCEL_PATH: str = os.path.join(os.path.expanduser("~"), "Desktop", "WhatsApp_Leads_SHARED.xlsx")
    CSV_EXPORT_PATH: str = os.path.join(os.path.expanduser("~"), "Desktop", "WhatsApp_Leads_Live.csv")

    # Business Rules
    REQUIRE_GST_MANDATORY: bool = False  # If True, GST is strictly mandatory unless explicitly "Not Applicable"

    # Cloud WhatsApp-Compatible Gateway Settings (Green API / Baileys Gateway)
    GATEWAY_TYPE: str = "green_api"  # "green_api", "evolution", or "local_web"
    GATEWAY_INSTANCE_ID: Optional[str] = os.getenv("GATEWAY_INSTANCE_ID", "710522726064")
    GATEWAY_API_TOKEN: Optional[str] = os.getenv("GATEWAY_API_TOKEN", "52d9555e5c6b4c65b3ebc1119abb5e62bf64e52d8dde4ac7aa")
    GATEWAY_API_URL: str = os.getenv("GATEWAY_API_URL", "https://api.green-api.com")

    # Cloud Google Sheets Sync URL (Google Apps Script Webhook)
    GOOGLE_SHEET_WEBHOOK_URL: Optional[str] = os.getenv(
        "GOOGLE_SHEET_WEBHOOK_URL",
        "https://script.google.com/macros/s/AKfycby-a2A6tpShmCJjeOVZ-dkNf2POJFiozd6Lz5cC6Krtsbv1qUgVUKq2eKir_DRnrf592A/exec"
    )

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")

settings = Settings()

os.makedirs(settings.DATA_DIR, exist_ok=True)
os.makedirs(settings.MEDIA_DIR, exist_ok=True)
