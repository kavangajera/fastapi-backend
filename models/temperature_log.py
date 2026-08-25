"""
models/temperature_log.py
─────────────────────────
SQLAlchemy model for temperature readings pushed by a registered
temperature-monitoring device.

One row per reading. Readings arrive in batches over
``POST /temperature-logs`` authenticated by a *device session token*, so every
new row can be attributed to the device, the logging session it belongs to,
and the pharmacy that owns it — which is what makes the reads pharmacy-scoped.

``raw_payload`` keeps the reading object exactly as the device sent it
(including any keys we do not model), so nothing is lost to our schema and the
original can always be replayed or inspected.

``temp_device_id`` is the *external* hardware id reported by the device. It is
distinct from ``TemperatureDevice.temperature_device_id`` (our registry key)
and from ``Device.device_id`` (the app/client sync id); it falls back to the
registry id when the device does not report one.

The three link columns are nullable so rows written before the device registry
existed still load.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String
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

    # ── Attribution (set by the authenticated push path) ─────────────
    temperature_device_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "temperature_device.temperature_device_id", ondelete="SET NULL", onupdate="CASCADE"
        ),
        nullable=True,
        index=True,
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "temperature_device_session.session_id", ondelete="SET NULL", onupdate="CASCADE"
        ),
        nullable=True,
        index=True,
    )
    medical_store_id: Mapped[int | None] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
        index=True,
    )

    # The reading object exactly as the device sent it.
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TemperatureLog(id={self.id}, "
            f"temp_device_id={self.temp_device_id!r}, "
            f"temperature={self.temperature})>"
        )
