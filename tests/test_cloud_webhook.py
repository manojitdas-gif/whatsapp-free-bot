"""
test_cloud_webhook.py — Automated test suite for Cloud Webhook Router & Google Sheets Sync.
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.database.session import SessionLocal, init_db
from app.database.models import Customer, Conversation
from app.conversation.state_machine import ConversationStage, ConversationStatus
from app.exports.google_sheets_sync import format_in_phone

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()

def test_health_check_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "gateway_type" in data

def test_cloud_webhook_handshake():
    res = client.get("/webhook/cloud")
    assert res.status_code == 200
    assert res.json()["status"] == "online"

def test_cloud_webhook_greeting_triggers_response_2():
    payload = {
        "typeWebhook": "incomingMessageReceived",
        "senderData": {
            "sender": "919988776655@c.us",
            "senderName": "Ramesh Gupta"
        },
        "messageData": {
            "typeMessage": "textMessage",
            "textMessageData": {
                "textMessage": "Hi"
            }
        }
    }
    res = client.post("/webhook/cloud", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "accepted"
    assert res.json()["phone"] == "919988776655"

    db = SessionLocal()
    cust = db.query(Customer).filter(Customer.whatsapp_number.like("%9988776655%")).first()
    assert cust is not None
    assert cust.contact_person_name == "Ramesh Gupta"
    db.close()

def test_cloud_webhook_document_triggers_response_3():
    payload = {
        "typeWebhook": "incomingMessageReceived",
        "senderData": {
            "sender": "919988776655@c.us",
            "senderName": "Ramesh Gupta"
        },
        "messageData": {
            "typeMessage": "documentMessage",
            "fileMessageData": {
                "fileName": "electrical_materials.pdf",
                "caption": "Please send quotation for attached items"
            }
        }
    }
    res = client.post("/webhook/cloud", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "accepted"

def test_cloud_webhook_business_details_triggers_response_1_and_completes():
    payload = {
        "typeWebhook": "incomingMessageReceived",
        "senderData": {
            "sender": "919988776655@c.us",
            "senderName": "Ramesh Gupta"
        },
        "messageData": {
            "typeMessage": "textMessage",
            "textMessageData": {
                "textMessage": "M/s Gupta Electricals, GST: 19ABCDE1234F1Z5, 12 Park Street, Kolkata 700016, email: gupta@gmail.com"
            }
        }
    }
    res = client.post("/webhook/cloud", json=payload)
    assert res.status_code == 200

    db = SessionLocal()
    cust = db.query(Customer).filter(Customer.whatsapp_number.like("%9988776655%")).first()
    assert cust is not None
    assert cust.company_name == "Gupta Electricals"
    assert cust.gst_number == "19ABCDE1234F1Z5"
    db.close()

def test_cloud_webhook_ignores_chatter():
    payload = {
        "typeWebhook": "incomingMessageReceived",
        "senderData": {
            "sender": "919988776655@c.us",
            "senderName": "Ramesh Gupta"
        },
        "messageData": {
            "typeMessage": "textMessage",
            "textMessageData": {
                "textMessage": "plz send your best possible price"
            }
        }
    }
    res = client.post("/webhook/cloud", json=payload)
    assert res.status_code == 200

    db = SessionLocal()
    cust = db.query(Customer).filter(Customer.whatsapp_number.like("%9988776655%")).first()
    # Ensure conversational noise was NOT appended as requirements
    if cust.requirements_summary:
        assert "plz send your best possible price" not in cust.requirements_summary.lower()
    db.close()

def test_google_sheets_phone_formatter():
    assert format_in_phone("916290164699") == "+91 62901 64699"
    assert format_in_phone("9876543210") == "+91 98765 43210"
    assert format_in_phone("+91 87651 97073") == "+91 87651 97073"
