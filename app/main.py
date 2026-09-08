"""
main.py — FastAPI Application Entrypoint.
Initializes Database, WhatsApp Webhook Router, and Admin Dashboard.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database.session import init_db
from app.webhooks.whatsapp_router import router as webhook_router
from app.webhooks.cloud_router import router as cloud_router
from app.dashboard.routes import router as dashboard_router

import asyncio
import httpx

async def _keep_alive_loop():
    """Keeps Render bot and WhatsApp Gateway awake 24/7 so connections never disconnect."""
    await asyncio.sleep(60)
    while True:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                await client.get("https://whatsapp-free-bot-1.onrender.com/health")
                await client.get(
                    "https://whatsapp-gateway-nsr1.onrender.com/instance/connectionState/whatsapp-bot-v2",
                    headers={"apikey": "mysecretkey123"}
                )
        except Exception:
            pass
        await asyncio.sleep(480)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database tables
    print(f"[{settings.APP_NAME}] Initializing database tables...")
    init_db()
    print(f"[{settings.APP_NAME}] Database ready. Running in {settings.ENVIRONMENT} mode.")
    ka_task = asyncio.create_task(_keep_alive_loop())
    yield
    ka_task.cancel()
    # Shutdown
    print(f"[{settings.APP_NAME}] Shutting down safely.")

app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="24x7 Production WhatsApp Customer Requirement Automation System for Electrical Dealership",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Webhooks and Dashboard
app.include_router(webhook_router)
app.include_router(cloud_router)
app.include_router(dashboard_router)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "provider": settings.WHATSAPP_PROVIDER,
        "gateway_type": settings.GATEWAY_TYPE,
        "gateway_instance_id": settings.GATEWAY_INSTANCE_ID,
        "gateway_api_url": settings.GATEWAY_API_URL,
        "google_sheets_sync": bool(settings.GOOGLE_SHEET_WEBHOOK_URL),
        "timezone": settings.TIMEZONE,
        "debounce_seconds": settings.DEBOUNCE_SECONDS
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
