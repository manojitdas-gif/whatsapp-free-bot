from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class ProductItem(BaseModel):
    product_name: str
    description: Optional[str] = None
    quantity: Optional[str] = None
    size: Optional[str] = None
    specifications: Optional[str] = None

class ExtractionResult(BaseModel):
    contact_person_name: Optional[str] = None
    email_id: Optional[str] = None
    company_business_name: Optional[str] = None
    gst_number: Optional[str] = None
    complete_address: Optional[str] = None
    product_requirements: List[ProductItem] = Field(default_factory=list)
    raw_requirement_text: Optional[str] = None
    confidence: Dict[str, float] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)

    def format_requirements_summary(self) -> str:
        """Formats products into the concise structured format required by specifications."""
        if not self.product_requirements and self.raw_requirement_text:
            return self.raw_requirement_text.strip()
        
        if not self.product_requirements:
            return ""

        if len(self.product_requirements) == 1:
            item = self.product_requirements[0]
            lines = [f"Product: {item.product_name}"]
            if item.description:
                lines.append(f"Description: {item.description}")
            if item.quantity:
                lines.append(f"Quantity: {item.quantity}")
            specs = filter(None, [item.size, item.specifications])
            spec_str = ", ".join(specs)
            if spec_str:
                lines.append(f"Size/Specifications: {spec_str}")
            return "\n".join(lines)

        result_lines = []
        for i, item in enumerate(self.product_requirements, start=1):
            result_lines.append(f"Product {i}:")
            result_lines.append(item.product_name)
            if item.quantity:
                result_lines.append(f"Quantity: {item.quantity}")
            specs = filter(None, [item.size, item.specifications])
            spec_str = ", ".join(specs)
            if spec_str:
                result_lines.append(f"Specification: {spec_str}")
        return "\n".join(result_lines)
