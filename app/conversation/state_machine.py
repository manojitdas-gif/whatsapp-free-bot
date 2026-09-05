"""
state_machine.py — Explicit Conversation State Machine.
"""

from enum import Enum
from typing import Optional
import datetime

class ConversationStage(str, Enum):
    NEW = "NEW"
    WAITING_FOR_PRODUCT_REQUIREMENTS = "WAITING_FOR_PRODUCT_REQUIREMENTS"
    WAITING_FOR_CUSTOMER_DETAILS = "WAITING_FOR_CUSTOMER_DETAILS"
    COMPLETED = "COMPLETED"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"

class ConversationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"

def transition_state(current_stage: str, next_action: str) -> str:
    """
    Computes valid deterministic state transition.
    """
    if next_action in ("RESPONSE_1", "RESPONSE_POST_COMPLETION"):
        return ConversationStage.COMPLETED.value
    elif next_action == "RESPONSE_2":
        return ConversationStage.WAITING_FOR_PRODUCT_REQUIREMENTS.value
    elif next_action == "RESPONSE_3":
        return ConversationStage.WAITING_FOR_CUSTOMER_DETAILS.value
    return current_stage
