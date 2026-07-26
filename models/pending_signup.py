"""
models/pending_signup.py
────────────────────────
A registration that has been *started* but not yet email-verified.

Signup is two steps: the submitted credentials land here and a one-time
code is mailed; only when that code comes back is a real `user` row
created. Nothing in this table can authenticate — it is not the `user`
table — so an unverified address never holds an account, and an abandoned
attempt expires instead of squatting the email address forever.

Both secrets are stored the way a password is (Argon2id PHC strings): a
dump of this table yields neither the chosen password nor the code that
would activate the account.

One live row per email. A repeat request overwrites it, so only the most
recently mailed code is ever valid.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import AuditMixin, Base


class PendingSignup(AuditMixin, Base):
    __tablename__ = "pending_signup"

    pending_signup_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_number: Mapped[str] = mapped_column(String(10), nullable=False)

    # Argon2id, hashed on arrival — neither value is ever held in the clear.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Resend budget: how many codes this attempt has already burned, and when
    # the last one went out. Together they cap how much mail one address can
    # be made to receive.
    send_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Carried from step 1 so the account, when it is finally created, is
    # stamped against the device that actually started the signup.
    device_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
