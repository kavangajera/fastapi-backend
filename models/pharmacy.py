from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Pharmacy(Base):

    __tablename__ = "pharmacy"

    pharmacy_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=True)

    address_id: Mapped[int] = mapped_column(
        ForeignKey("address.address_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False
    )

    owner = relationship(
        "User",
        back_populates="pharmacies_owns",
        foreign_keys=[user_id]
    )

    technician = relationship(
        "User",
        back_populates="pharmacies_works",
        foreign_keys="User.pharmacy_id"
    )

    address_rel = relationship(
        "Address",
        back_populates="pharmacy",
        uselist=False,
        lazy="joined"
    )