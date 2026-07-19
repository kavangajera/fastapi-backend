"""
schemas/temperature_log.py
──────────────────────────
Request / response schemas for the basic temperature-logs API.

Follows the id-prefix convention used across the codebase (see
``schemas/pharmacy_output.py``): the response exposes a domain-prefixed
``temperature_log_id`` mapped to the internal ``id`` column via
``validation_alias``, and is dumped with ``by_alias=False`` so the prefixed
key is emitted.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from schemas.audit_fields import AuditFields


class TemperatureReadingInput(BaseModel):
    """A single temperature reading within a submission."""

    temperature: float = Field(
        ..., description="Temperature reading value (°C).", examples=[4.2]
    )
    recorded_at: datetime | None = Field(
        None, description="When the reading was taken on the device."
    )
    probe: str | None = Field(
        None, description="Probe / sensor id within the device.", examples=["PRB-001"]
    )
    status: str | None = Field(
        None, description="Device-reported status, e.g. Normal / High.", examples=["Normal"]
    )


class TemperatureLogCreateInput(BaseModel):
    """Payload for storing a batch of readings from one device."""

    temp_device_id: str = Field(
        ...,
        description="External temperature device id (distinct from our internal device id).",
        examples=["TEMP-DEV-01"],
    )
    logs: list[TemperatureReadingInput] = Field(
        ...,
        min_length=1,
        description="Array of temperature readings reported by the device.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "temp_device_id": "TEMP-DEV-01",
                "logs": [
                    {
                        "temperature": 4.2,
                        "recorded_at": "2026-07-19T10:00:00",
                        "probe": "PRB-001",
                        "status": "Normal",
                    },
                    {
                        "temperature": 8.6,
                        "recorded_at": "2026-07-19T10:05:00",
                        "probe": "PRB-001",
                        "status": "High",
                    },
                ],
            }
        }
    }


class TemperatureLogOutput(AuditFields, BaseModel):
    """A stored reading returned to callers."""

    temperature_log_id: int = Field(
        ...,
        validation_alias="id",
        description="Unique id of the stored temperature reading.",
        examples=[1],
    )
    temp_device_id: str = Field(..., description="External temperature device id.")
    temperature: float = Field(..., description="Temperature reading value (°C).")
    recorded_at: datetime | None = Field(
        None, description="Device-reported time the reading was taken."
    )
    probe: str | None = Field(None, description="Probe / sensor id within the device.")
    status: str | None = Field(None, description="Device-reported status.")
