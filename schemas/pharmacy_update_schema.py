from pydantic import BaseModel
from typing import Optional
from schemas.address_schema import AddressUpdateInput


class PharmacyUpdateSchema(BaseModel):
    pharmacy_title: Optional[str] = None
    pharmacy_code: Optional[str] = None
    address: Optional[AddressUpdateInput] = None
