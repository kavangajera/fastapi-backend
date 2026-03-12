from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base
from core.enums import UserRole
class User(Base):
    __tablename__="user"

    user_id :Mapped[int]= mapped_column(Integer,primary_key=True,index=True, unique=True,autoincrement=True)
    username : Mapped[str] = mapped_column(String(100))

    #If Unique Email Needed
    email : Mapped[str] = mapped_column(String(255) , unique=True , index=True)
    
    # NEEDS TO UPDATE AS PER USA
    contact_number : Mapped[str] = mapped_column(String(10))
    password_hash : Mapped[str] = mapped_column(String(255))
    role:Mapped[UserRole] = mapped_column(default=UserRole.PHARMACY_OWNER)

    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    pharmacies=relationship("Pharmacy" , back_populates="owner", cascade="all, delete-orphan")