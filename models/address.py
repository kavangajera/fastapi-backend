from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Address(Base):

    __tablename__ = "address"

    address_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True
    )

    address_line_1: Mapped[str] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=True)
    state: Mapped[str] = mapped_column(String(100), nullable=True)
    zip_code: Mapped[str] = mapped_column(String(20), nullable=True)

    pharmacy = relationship(
        "Pharmacy",
        back_populates="address_rel",
        uselist=False
    )
