"""
models/temperature_device.py
────────────────────────────
The registry behind the temperature-logging flow.

``TemperatureDevice``
    One row per physical logger registered against a pharmacy. A store may
    register as many as it likes. The device authenticates with a **secret**
    that is never stored in the clear:

    * ``secret_lookup`` — SHA-256 hex of the secret. Deterministic, uniquely
      indexed, and the only way to *find* a device from a presented secret
      (an Argon2 hash is salted, so it cannot be looked up).
    * ``secret_hash``   — Argon2id PHC string, verified after the lookup hit.
      Belt-and-braces for caller-supplied secrets, which may be low entropy.
    * ``secret_hint``   — last few characters, so the UI can tell two devices
      apart without ever holding the secret.

``TemperatureDeviceSession``
    One row per *logging session* — the window between "start logging" and
    "stop logging". A session outlives individual tokens: when a token
    expires the device presents its secret again and we mint a new one
    against the same session, rotating ``current_jti``.

    ``current_jti`` is the revocation switch. A token is only honoured while
    its ``jti`` still equals the session's ``current_jti``, so issuing a new
    token instantly kills the previous one, and stopping the session (which
    NULLs the column) kills the current one.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import AuditMixin, Base
from core.enums import TemperatureSessionStatus


class TemperatureDevice(AuditMixin, Base):
    __tablename__ = "temperature_device"

    temperature_device_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    # Human label shown in the UI ("Fridge A", "Vaccine freezer"). Deliberately
    # not unique per store — two identical fridges are a normal thing to own.
    nickname: Mapped[str] = mapped_column(String(120), nullable=False)

    secret_lookup: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    secret_hint: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Owner-controlled kill switch. An inactive device cannot start a session
    # and its live token stops being accepted.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    registered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True
    )

    # Touched on every successful authentication and every accepted push, so
    # the dashboard can show "last heard from" without scanning the readings.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_readings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sessions = relationship(
        "TemperatureDeviceSession",
        back_populates="device",
        foreign_keys="TemperatureDeviceSession.temperature_device_id",
    )

    def __repr__(self) -> str:
        return (
            f"<TemperatureDevice(id={self.temperature_device_id}, "
            f"store={self.medical_store_id}, nickname={self.nickname!r})>"
        )


class TemperatureDeviceSession(AuditMixin, Base):
    __tablename__ = "temperature_device_session"

    session_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )

    temperature_device_id: Mapped[int] = mapped_column(
        ForeignKey(
            "temperature_device.temperature_device_id", ondelete="CASCADE", onupdate="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    # Denormalized from the device so pharmacy-scoped reads never need a join.
    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )

    # core.enums.TemperatureSessionStatus, stored as its string *value* —
    # matching the convention used by Subscription.status / Document.status.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TemperatureSessionStatus.ACTIVE.value, index=True
    )

    # The single token this session currently honours. NULL once stopped.
    current_jti: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    token_issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tokens_issued: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Free-text why: "device_stop", "pharmacy_stop", "device_deleted", …
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    readings_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device = relationship(
        "TemperatureDevice",
        back_populates="sessions",
        foreign_keys=[temperature_device_id],
    )

    def __repr__(self) -> str:
        return (
            f"<TemperatureDeviceSession(id={self.session_id}, "
            f"device={self.temperature_device_id}, status={self.status!r})>"
        )
