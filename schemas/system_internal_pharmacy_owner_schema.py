from pydantic import BaseModel

class System_Internal_Pharmacy_Owner_Schema(BaseModel):
    owner_id :int
    username :str
    # email :str
    # contact_number :str
    role :str