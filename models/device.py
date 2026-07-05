"""
models/device.py
────────────────
Server-side device registry + per-(device, table) record counters that back
the generated ``record_Identifier`` sync keys.

Neither table carries ``AuditMixin`` — they are infrastructure that *powers*
the record-metadata scheme, not business data that participates in it.

``Device``        — one row per client device. Created / refreshed on login
                    and signup. Holds the ``source_prefix`` (e.g. ``AN001``)
                    captured from the login ``source`` so every id generated
                    for that device carries the right platform code.
``RecordCounter`` — monotonic counter per (device_id, table_name). Incremented
                    atomically inside the same transaction as the row being
                    stamped, so a rolled-back write does not burn a value.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import Base
from core.record_ids import DEFAULT_SOURCE_PREFIX


class Device(Base):
    __tablename__ = "device"

    # The 6-char alphanumeric id is the natural key and appears verbatim in
    # every record_Identifier, so it is the primary key.
    device_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    # Last user seen on this device (a shared device may change hands).
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_prefix: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DEFAULT_SOURCE_PREFIX
    )
    source_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=func.now(),
        nullable=False,
    )


class RecordCounter(Base):
    __tablename__ = "record_counter"

    device_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
