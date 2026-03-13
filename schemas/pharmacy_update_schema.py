from pydantic import BaseModel
from typing import Optional

class PharmacyUpdateSchema(BaseModel):
    name:Optional[str]=None
    address:Optional[str]=None
