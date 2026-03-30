from pydantic import BaseModel
from typing import Optional

class PharmacyUpdateSchema(BaseModel):
    pharmacy_title:Optional[str]=None
    pharmacy_location:Optional[str]=None
