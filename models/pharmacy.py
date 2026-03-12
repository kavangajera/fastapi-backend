from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Pharmacy(Base):

    __tablename__="pharmacy"

    pharmacy_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "user.user_id",
            ondelete="CASCADE",
            onupdate="CASCADE"
        ),
        nullable=False
    )

    name:Mapped[str]=mapped_column(String(255),nullable=False)

    address:Mapped[str]=mapped_column(String(255),nullable=False)

    owner = relationship(
        "User",
        back_populates="pharmacies"
    )

