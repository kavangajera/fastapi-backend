from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Pharmacy(Base):

    __tablename__="pharmacy"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True
    )

    owner_id: Mapped[int] = mapped_column(
        ForeignKey(
            "pharmacy_owner.owner_id",
            ondelete="CASCADE",
            onupdate="CASCADE"
        ),
        nullable=False
    )

    name:Mapped[str]=mapped_column(String(255),nullable=False)

    address:Mapped[str]=mapped_column(String(255),nullable=False)

    pharmacy_owner = relationship(
        "Pharmacy_Owner",
        back_populates="pharmacies"
    )

