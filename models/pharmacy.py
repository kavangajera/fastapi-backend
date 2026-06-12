from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import Base


class Pharmacy(Base):
    # NB: the Python identifier stays `Pharmacy` because every existing
    # caller, schema, and route uses that name. Only the *table* is
    # renamed to `medical_store` to reflect the real-world entity
    # (an independent medical store / retail pharmacy outlet).
    __tablename__ = "medical_store"

    medical_store_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "user.user_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
            use_alter=True,
            name="fk_pharmacy_user_id",
        ),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)

    # lazy="selectin": every PharmacyOutput.owner read on an AsyncSession
    # would otherwise emit a lazy load mid-validation and crash with
    # MissingGreenlet. We always need the owner row when serializing, so
    # fetch it alongside the parent.
    owner = relationship(
        "User",
        back_populates="pharmacies_owns",
        foreign_keys=[user_id],
        lazy="selectin",
    )

    technician = relationship(
        "User",
        back_populates="pharmacies_works",
        foreign_keys="User.medical_store_id",
        lazy="selectin",
    )
