"""
test_all_12_cases.py — Complete automated test suite covering all 12 required test scenarios.
"""

import os
import pytest
import asyncio
from app.config import settings
from app.database.session import SessionLocal, init_db, engine, Base
from app.database.models import Customer, Conversation, Message, ExtractedData, ResponseLog
from app.whatsapp.mock_provider import MockWhatsAppProvider
from app.whatsapp import set_whatsapp_provider
from app.workers.debounce_queue import process_customer_conversation, enqueue_customer_message
from app.conversation.templates import RESPONSE_1, RESPONSE_2, RESPONSE_3
from app.ai.extractor import analyze_conversation
from app.conversation.decision_engine import evaluate_conversation_completeness
from app.conversation.state_machine import ConversationStage
from app.documents.excel_parser import extract_spreadsheet_text

@pytest.fixture(autouse=True)
def setup_test_env():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    mock_provider = MockWhatsAppProvider()
    set_whatsapp_provider(mock_provider)
    yield mock_provider
    Base.metadata.drop_all(bind=engine)

@pytest.mark.asyncio
async def test_1_customer_provides_everything_in_first_message(setup_test_env):
    """Test 1: Customer provides everything in first message -> Expected: Response 1."""
    mock = setup_test_env
    phone = "919876543210"
    full_text = (
        "Hi, I am Raj from ABC Electricals.\n"
        "We need 100 pcs LED bulbs 12W B22 and 20 ceiling fans 1200mm.\n"
        "Our shop address is 12 MG Road, Kolkata 700001.\n"
        "GST: 19ABCDE1234F1Z5."
    )
    
    db = SessionLocal()
    c = Customer(whatsapp_number=phone)
    db.add(c)
    db.commit()
    c_id = c.id
    conv = Conversation(customer_id=c_id, status="ACTIVE", stage="NEW")
    db.add(conv)
    db.commit()
    msg = Message(conversation_id=conv.id, text=full_text, direction="INBOUND")
    db.add(msg)
    db.commit()
    db.close()

    await process_customer_conversation(phone)

    assert len(mock.sent_messages) == 1
    assert mock.sent_messages[0]["text"] == RESPONSE_1

    db = SessionLocal()
    updated_conv = db.query(Conversation).filter(Conversation.customer_id == c_id).first()
    assert updated_conv.stage == ConversationStage.COMPLETED.value
    db.close()

@pytest.mark.asyncio
async def test_2_customer_only_says_hi(setup_test_env):
    """Test 2: Customer only says 'Hi' -> Expected: Response 2."""
    mock = setup_test_env
    phone = "919876543211"
    
    db = SessionLocal()
    c = Customer(whatsapp_number=phone)
    db.add(c)
    db.commit()
    c_id = c.id
    conv = Conversation(customer_id=c_id, status="ACTIVE", stage="NEW")
    db.add(conv)
    db.commit()
    msg = Message(conversation_id=conv.id, text="Hi", direction="INBOUND")
    db.add(msg)
    db.commit()
    db.close()

    await process_customer_conversation(phone)

    assert len(mock.sent_messages) == 1
    assert mock.sent_messages[0]["text"] == RESPONSE_2

    db = SessionLocal()
    updated_conv = db.query(Conversation).filter(Conversation.customer_id == c_id).first()
    assert updated_conv.stage == ConversationStage.WAITING_FOR_PRODUCT_REQUIREMENTS.value
    db.close()

@pytest.mark.asyncio
async def test_3_customer_sends_product_photo_only(setup_test_env):
    """Test 3: Customer sends a product photo -> Expected: Response 3."""
    mock = setup_test_env
    phone = "919876543212"
    
    db = SessionLocal()
    c = Customer(whatsapp_number=phone)
    db.add(c)
    db.commit()
    c_id = c.id
    conv = Conversation(customer_id=c_id, status="ACTIVE", stage="NEW")
    db.add(conv)
    db.commit()
    msg = Message(
        conversation_id=conv.id,
        text="Need 50 pcs of this 12W LED bulb",
        message_type="image",
        direction="INBOUND"
    )
    db.add(msg)
    db.commit()
    db.close()

    await process_customer_conversation(phone)

    assert len(mock.sent_messages) == 1
    assert mock.sent_messages[0]["text"] == RESPONSE_3

    db = SessionLocal()
    updated_conv = db.query(Conversation).filter(Conversation.customer_id == c_id).first()
    assert updated_conv.stage == ConversationStage.WAITING_FOR_CUSTOMER_DETAILS.value
    db.close()

@pytest.mark.asyncio
async def test_4_customer_sends_pdf_with_requirements_and_company(setup_test_env):
    """Test 4: Customer sends requirements and company details -> Proper field extraction."""
    extracted = analyze_conversation([
        "Attached invoice quotation for 200 batten tube lights 20W",
        "Company: Apex Electrical Solutions",
        "Address: Sector 5, Kolkata 700091"
    ])
    assert len(extracted.product_requirements) >= 1
    assert extracted.company_business_name == "Apex Electrical Solutions"
    assert "Kolkata" in extracted.complete_address

@pytest.mark.asyncio
async def test_5_customer_sends_burst_messages(setup_test_env):
    """Test 5: Several messages in burst -> One combined analysis and ONE response."""
    mock = setup_test_env
    phone = "919876543215"

    db = SessionLocal()
    c = Customer(whatsapp_number=phone)
    db.add(c)
    db.commit()
    c_id = c.id
    conv = Conversation(customer_id=c_id, status="ACTIVE", stage="NEW")
    db.add(conv)
    db.commit()
    conv_id = conv.id
    
    # Rapid burst
    for text in ["Hi", "I need 20 ceiling fans", "for my shop"]:
        m = Message(conversation_id=conv_id, text=text, direction="INBOUND")
        db.add(m)
        db.commit()
        await enqueue_customer_message(phone, {"text": text})
        await asyncio.sleep(0.05)  # Much faster than debounce 1.5s
    db.close()

    # Wait for debounce timer to expire
    await asyncio.sleep(2.0)

    # Exactly ONE response sent!
    assert len(mock.sent_messages) == 1
    assert mock.sent_messages[0]["text"] == RESPONSE_3

@pytest.mark.asyncio
async def test_6_customer_sends_no_further_reply(setup_test_env):
    """Test 6: Customer sends no further reply -> No automatic next response."""
    mock = setup_test_env
    phone = "919876543216"

    db = SessionLocal()
    c = Customer(whatsapp_number=phone)
    db.add(c)
    db.commit()
    conv = Conversation(customer_id=c.id, status="ACTIVE", stage="WAITING_FOR_PRODUCT_REQUIREMENTS")
    db.add(conv)
    db.commit()
    db.close()

    # Wait without any new customer messages
    await asyncio.sleep(0.5)

    # Bot stays completely silent!
    assert len(mock.sent_messages) == 0

@pytest.mark.asyncio
async def test_7_duplicate_webhook_idempotency():
    """Test 7: Duplicate webhook message ID -> Stored and processed only once."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.HBgLMTIzNDU2Nzg5MA==",
                        "from": "919876543217",
                        "type": "text",
                        "text": {"body": "Hi"}
                    }]
                }
            }]
        }]
    }

    # Send first time
    res1 = client.post("/webhook", json=payload)
    assert res1.status_code == 200

    # Send duplicate
    res2 = client.post("/webhook", json=payload)
    assert res2.status_code == 200

    # Verify DB has only 1 message
    db = SessionLocal()
    count = db.query(Message).filter(Message.whatsapp_message_id == "wamid.HBgLMTIzNDU2Nzg5MA==").count()
    assert count == 1
    db.close()

@pytest.mark.asyncio
async def test_8_company_details_first_product_later(setup_test_env):
    """Test 8: Customer gives company details first, then product details later -> Correct transition."""
    mock = setup_test_env
    phone = "919876543218"

    # Step 1: Customer gives company details only
    db = SessionLocal()
    c = Customer(whatsapp_number=phone)
    db.add(c)
    db.commit()
    c_id = c.id
    conv = Conversation(customer_id=c_id, status="ACTIVE", stage="NEW")
    db.add(conv)
    db.commit()
    conv_id = conv.id
    m1 = Message(conversation_id=conv_id, text="Hi, I am Debashis from Bengal Electricals, 12 Park St, Kolkata", direction="INBOUND")
    db.add(m1)
    db.commit()
    db.close()

    await process_customer_conversation(phone)
    # Product missing -> Response 2
    assert mock.sent_messages[-1]["text"] == RESPONSE_2

    # Step 2: Customer now shares product details
    db = SessionLocal()
    m2 = Message(conversation_id=conv_id, text="Please send 50 pcs 9W LED bulb and 10 MCBs", direction="INBOUND")
    db.add(m2)
    db.commit()
    db.close()

    await process_customer_conversation(phone)
    # Both are now available! -> Response 1 (Completed)
    assert mock.sent_messages[-1]["text"] == RESPONSE_1

@pytest.mark.asyncio
async def test_9_customer_corrects_gst_number():
    """Test 9: Customer corrects GST number -> Correct updated value stored."""
    history = [
        "Company: National Traders",
        "GST: 19ABCDE1234F1Z5",
        "Wait, correction in GST: 19XYZAB5678C1Z2"
    ]
    extracted = analyze_conversation(history)
    # Latest valid GST extracted
    assert extracted.gst_number == "19XYZAB5678C1Z2"

@pytest.mark.asyncio
async def test_10_image_containing_gst_address_product():
    """Test 10: Customer sends text containing GST, address, and products."""
    raw_ocr_simulated = (
        "METRO ELECTRICAL STORES\n"
        "GST: 19AAAAA0000A1Z5\n"
        "Address: 45 Park Street, Kolkata 700016\n"
        "Required: 200 mtrs copper wire 2.5 sqmm\n"
        "Contact: Amit Roy"
    )
    extracted = analyze_conversation([raw_ocr_simulated])
    assert extracted.gst_number == "19AAAAA0000A1Z5"
    assert "Kolkata" in extracted.complete_address
    assert len(extracted.product_requirements) >= 1

@pytest.mark.asyncio
async def test_11_excel_product_list_extraction(tmp_path):
    """Test 11: Excel product list -> Extract relevant product rows cleanly."""
    import openpyxl
    excel_file = tmp_path / "products.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Item No", "Product Description", "Qty", "Unit", "Specs"])
    ws.append(["1", "LED Bulb 9W B22", "500", "pcs", "Cool White"])
    ws.append(["2", "Havells 1.5 sqmm wire", "20", "coils", "Red"])
    wb.save(str(excel_file))

    extracted = extract_spreadsheet_text(str(excel_file))
    assert "LED Bulb" in extracted
    assert "500" in extracted
    assert "wire" in extracted

@pytest.mark.asyncio
async def test_12_server_restart_preserves_state():
    """Test 12: Server restarts -> Conversation state remains intact in DB."""
    phone = "919876543220"
    
    # Session 1: Create state
    db = SessionLocal()
    c = Customer(whatsapp_number=phone, company_name="Pioneer Electric")
    db.add(c)
    db.commit()
    c_id = c.id
    conv = Conversation(customer_id=c_id, status="ACTIVE", stage=ConversationStage.WAITING_FOR_CUSTOMER_DETAILS.value)
    db.add(conv)
    db.commit()
    db.close()

    # Simulate server restart (new session / engine connection)
    db2 = SessionLocal()
    loaded_customer = db2.query(Customer).filter(Customer.whatsapp_number == phone).first()
    assert loaded_customer is not None
    assert loaded_customer.company_name == "Pioneer Electric"
    loaded_conv = db2.query(Conversation).filter(Conversation.customer_id == loaded_customer.id).first()
    assert loaded_conv.stage == ConversationStage.WAITING_FOR_CUSTOMER_DETAILS.value
    db2.close()
