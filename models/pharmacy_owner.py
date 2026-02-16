from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base
class Pharmacy_Owner(Base):
    __tablename__="pharmacy_owner"

    owner_id :Mapped[int]= mapped_column(Integer,primary_key=True,index=True, unique=True,autoincrement=True)
    username : Mapped[str] = mapped_column(String(100))

    #If Unique Email Needed
    email : Mapped[str] = mapped_column(String(255) , unique=True , index=True)
    
    # NEEDS TO UPDATE AS PER USA
    contact_number : Mapped[str] = mapped_column(String(10))
    password_hash : Mapped[str] = mapped_column(String(255))

