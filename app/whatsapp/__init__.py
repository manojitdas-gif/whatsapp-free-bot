from app.config import settings
from app.whatsapp.base import WhatsAppProvider
from app.whatsapp.meta_cloud import MetaCloudWhatsAppProvider
from app.whatsapp.mock_provider import MockWhatsAppProvider
from app.whatsapp.local_web import LocalWebWhatsAppProvider
from app.whatsapp.green_api import GreenAPIProvider

_provider_instance = None

def get_whatsapp_provider() -> WhatsAppProvider:
    global _provider_instance
    if _provider_instance is None:
        p_type = settings.WHATSAPP_PROVIDER.lower()
        if p_type == "meta_cloud":
            _provider_instance = MetaCloudWhatsAppProvider()
        elif p_type in ("green_api", "cloud_gateway", "gateway"):
            _provider_instance = GreenAPIProvider()
        elif p_type == "mock":
            _provider_instance = MockWhatsAppProvider()
        else:
            _provider_instance = LocalWebWhatsAppProvider()
    return _provider_instance

def set_whatsapp_provider(provider: WhatsAppProvider):
    global _provider_instance
    _provider_instance = provider
