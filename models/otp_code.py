from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import OtpPurpose
from database import Base


class OtpCode(Base):
    __tablename__ = "otp_code"

    otp_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[OtpPurpose] = mapped_column(
        Enum(OtpPurpose, name="otppurpose"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    pharmacy_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pharmacy.pharmacy_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    transfer_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(
            "pharmacy_ownership_transfer.transfer_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    new_owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )

    user = relationship("User", foreign_keys=[user_id])
