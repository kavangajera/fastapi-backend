"""
models/temperature_log.py
─────────────────────────
SQLAlchemy model for temperature readings pushed by an external
temperature-monitoring device.

Intentionally **basic** for now: it is a connectivity surface to confirm a
device can reach the backend and store readings. It is deliberately NOT yet
scoped to a pharmacy / medical store — that wiring comes later.

``temp_device_id`` is the *external* hardware id reported by the device and is
distinct from our internal ``Device.device_id`` (the app/client sync id).

One row per reading. Standard record-metadata (``created_at`` / ``updated_at`` /
``IsDeleted`` / …) is inherited from ``AuditMixin``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import AuditMixin, Base


class TemperatureLog(AuditMixin, Base):
    __tablename__ = "temperature_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # External device hardware id — NOT our internal Device.device_id.
    temp_device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    temperature: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    # Device-reported time the reading was taken (optional; falls back to created_at).
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    probe: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TemperatureLog(id={self.id}, "
            f"temp_device_id={self.temp_device_id!r}, "
            f"temperature={self.temperature})>"
        )
