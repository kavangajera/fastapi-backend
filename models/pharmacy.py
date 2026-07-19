from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import AuditMixin, Base


class Pharmacy(AuditMixin, Base):
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

    # Structured address parts requested by the mobile app spec. Nullable so
    # existing rows (and web callers that only send the free-text `address`)
    # keep working.
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    store_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone = Column(String(20), nullable=True)
    stripe_customer_id = Column(String(255), nullable=True, unique=True, comment="Stripe Customer ID")


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
