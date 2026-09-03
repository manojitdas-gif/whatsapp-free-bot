import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index, Float
from sqlalchemy.orm import relationship
from app.database.session import Base

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    whatsapp_number = Column(String(32), unique=True, index=True, nullable=False)
    contact_person_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)
    gst_number = Column(String(32), nullable=True)
    complete_address = Column(Text, nullable=True)
    requirements_summary = Column(Text, nullable=True)  # Structured requirements summary
    first_contact_at = Column(DateTime, default=utc_now, nullable=False)
    last_contact_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    conversations = relationship("Conversation", back_populates="customer", cascade="all, delete-orphan")

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    status = Column(String(32), default="ACTIVE", index=True, nullable=False)  # ACTIVE, COMPLETED
    stage = Column(String(64), default="NEW", index=True, nullable=False)  # NEW, WAITING_FOR_PRODUCT_REQUIREMENTS, WAITING_FOR_CUSTOMER_DETAILS, COMPLETED, ERROR
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    extracted_records = relationship("ExtractedData", back_populates="conversation", cascade="all, delete-orphan")
    responses = relationship("ResponseLog", back_populates="conversation", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    whatsapp_message_id = Column(String(128), unique=True, index=True, nullable=True)  # For idempotency
    direction = Column(String(16), default="INBOUND", nullable=False)  # INBOUND, OUTBOUND
    message_type = Column(String(32), default="text", nullable=False)  # text, image, document, audio, etc.
    text = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=utc_now, nullable=False)
    media_reference = Column(String(512), nullable=True)
    processing_status = Column(String(32), default="PENDING", nullable=False)  # PENDING, PROCESSED, ERROR

    conversation = relationship("Conversation", back_populates="messages")

class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    field_name = Column(String(64), nullable=False, index=True)
    field_value = Column(Text, nullable=True)
    source_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    confidence = Column(Float, default=1.0, nullable=False)
    extraction_status = Column(String(32), default="CONFIRMED", nullable=False)  # CONFIRMED, AUDIT
    created_at = Column(DateTime, default=utc_now, nullable=False)

    conversation = relationship("Conversation", back_populates="extracted_records")

class ResponseLog(Base):
    __tablename__ = "response_log"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    response_type = Column(String(32), nullable=False)  # RESPONSE_1, RESPONSE_2, RESPONSE_3
    message_text = Column(Text, nullable=False)
    sent_at = Column(DateTime, default=utc_now, nullable=False)
    whatsapp_message_id = Column(String(128), nullable=True)
    status = Column(String(32), default="SENT", nullable=False)  # SENT, FAILED

    conversation = relationship("Conversation", back_populates="responses")
