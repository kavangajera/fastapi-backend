from pydantic import BaseModel


class PharmacyUpdateSchema(BaseModel):
    pharmacy_title: str | None = None
    pharmacy_location: str | None = None
