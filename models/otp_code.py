from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import AuditMixin, Base


class OtpCode(AuditMixin, Base):
    """A single-use verification code, stored hashed.

    Codes are never persisted in the clear — `code_hash` is an Argon2id PHC
    string, verified the same way passwords are. A row is dead once
    `is_active` is False, which happens when it is consumed, expires, or the
    attempt budget runs out.

    The nullable `*_id` columns are the *scope*: a code is only accepted for
    the exact (user, purpose, scope) tuple it was issued for, so a code
    mailed for one pharmacy's transfer cannot be replayed against another.
    """

    __tablename__ = "otp_code"

    otp_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )

    # core.enums.OtpPurpose (stored as its string *value*, matching the
    # convention used by Subscription.status / Document.status). Plain string
    # rather than a native DB enum: a new purpose needs no table rebuild.
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── Scope (all optional) ────────────────────────────────────────
    medical_store_id: Mapped[int | None] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "pharmacy_ownership_transfer.transfer_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    new_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )

    user = relationship("User", foreign_keys=[user_id])
