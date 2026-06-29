from sqlalchemy import ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import AuditMixin, Base
from core.enums import UserRole


class User(AuditMixin, Base):
    __tablename__ = "user"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    username: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    contact_number: Mapped[str] = mapped_column(String(10))
    password_hash: Mapped[str] = mapped_column(String(255))

    role: Mapped[UserRole] = mapped_column(default=UserRole.PHARMACY_OWNER)

    # User-only state flags (integer, as requested):
    #   IsActive  — 1 = active account, 0 = deactivated   (default 1)
    #   IsLogout  — 1 = currently logged out, 0 = logged in (default 0)
    IsActive: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    IsLogout: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )

    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )

    pharmacies_owns = relationship(
        "Pharmacy",
        back_populates="owner",
        foreign_keys="Pharmacy.user_id",
        cascade="all, delete-orphan",
    )

    pharmacies_works = relationship(
        "Pharmacy", back_populates="technician", foreign_keys=[medical_store_id]
    )
