from typing import Optional, List
import datetime
from pydantic import BaseModel

class CustomerResponse(BaseModel):
    id: int
    whatsapp_number: str
    contact_person_name: Optional[str]
    email: Optional[str]
    company_name: Optional[str]
    gst_number: Optional[str]
    complete_address: Optional[str]
    requirements_summary: Optional[str]
    first_contact_at: datetime.datetime
    last_contact_at: datetime.datetime

    class Config:
        from_attributes = True

class DashboardStats(BaseModel):
    total_customers: int
    new_customers: int
    completed_enquiries: int
    waiting_for_requirements: int
    waiting_for_details: int
