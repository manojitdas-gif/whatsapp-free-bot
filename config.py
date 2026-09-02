"""
config.py — Configuration for WhatsApp Bot.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Green API credentials
ID_INSTANCE        = os.getenv("ID_INSTANCE", "710522726064")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE", "52d9555e5c6b4c65b3ebc1119abb5e62bf64e52d8dde4ac7aa")

# Custom API host
API_HOST   = os.getenv("API_HOST", "https://7105.api.greenapi.com")
MEDIA_HOST = os.getenv("MEDIA_HOST", "https://7105.media.greenapi.com")

BASE_URL = f"{API_HOST}/waInstance{ID_INSTANCE}"

# Desktop primary Excel path
DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
DESKTOP_EXCEL_PATH = os.path.join(DESKTOP_DIR, "WhatsApp_Conversations.xlsx")

# Desktop shared copy path
SHARED_EXCEL_PATH = os.path.join(DESKTOP_DIR, "WhatsApp_Leads_SHARED.xlsx")

# Local project backup Excel path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_EXCEL_PATH = os.path.join(PROJECT_DIR, "data", "messages.xlsx")

# Primary path used by logger
EXCEL_FILE_PATH = os.getenv("EXCEL_FILE_PATH", DESKTOP_EXCEL_PATH)
