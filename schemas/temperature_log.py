"""
schemas/temperature_log.py
──────────────────────────
Request / response schemas for temperature readings.

The push body is a **bare JSON array** of reading objects — that is what a
logger naturally batches up — and the device's identity comes from its session
token rather than the payload, so a reading can never claim to be from a device
the caller does not hold the secret for.

Field naming is deliberately forgiving on the way in: firmware tends to emit
``time``/``temp``, so those are accepted as aliases for ``recorded_at``/
``temperature``. Unknown keys are kept too (``extra="allow"``) and land in the
row's ``raw_payload`` verbatim.

Responses follow the id-prefix convention used across the codebase: the
prefixed ``temperature_log_id`` maps to the internal ``id`` column via
``validation_alias``, and payloads are dumped with ``by_alias=False``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from core.datetime_utils import to_naive_utc
from schemas.audit_fields import AuditFields


class TemperatureReadingInput(BaseModel):
    """A single temperature reading within a pushed batch."""

    temperature: float = Field(
        ...,
        validation_alias=AliasChoices("temperature", "temp", "value"),
        description="Temperature reading value (°C). Accepts `temp` or `value` too.",
        examples=[4.2],
    )
    recorded_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("recorded_at", "time", "timestamp", "recordedAt"),
        description=(
            "When the reading was taken on the device. Accepts `time` or "
            "`timestamp` too. Falls back to the server receive time if omitted."
        ),
    )
    probe: str | None = Field(
        None,
        validation_alias=AliasChoices("probe", "probe_id", "probeId"),
        max_length=64,
        description="Probe / sensor id within the device.",
        examples=["PRB-001"],
    )
    status: str | None = Field(
        None,
        max_length=32,
        description=(
            "Device-reported status, e.g. Normal / High. Derived from the "
            "configured safe range when the device does not send one."
        ),
        examples=["Normal"],
    )
    temp_device_id: str | None = Field(
        None,
        max_length=64,
        description="Optional hardware id override for this reading.",
    )

    # Verbatim copy of the object as it arrived, captured before validation
    # renames anything. Stored on the row so nothing is lost to our schema.
    raw_payload: dict | None = Field(None, exclude=True)

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, data):
        if isinstance(data, dict):
            raw = {k: v for k, v in data.items() if k != "raw_payload"}
            return {**data, "raw_payload": raw}
        return data

    @field_validator("recorded_at", mode="after")
    @classmethod
    def _normalize_recorded_at(cls, value):
        """Pin the timestamp to naive UTC, the convention every column uses.

        Devices report time in whatever form they like — a browser sends
        ``...Z``, firmware often sends a local offset. Storing that verbatim
        would corrupt a naive DATETIME column, and mixing aware and naive
        values inside one batch raises a TypeError when we look for the newest
        reading. The offset is honoured, not dropped: 16:10+05:30 becomes
        10:40 UTC. The original string is still kept in ``raw_payload``.
        """
        return to_naive_utc(value)


class TemperaturePushOutput(BaseModel):
    """Acknowledgement for one accepted batch."""

    stored: int = Field(..., description="Readings written by this call.", examples=[12])
    temperature_device_id: int = Field(..., description="Device the batch was attributed to.")
    session_id: int = Field(..., description="Logging session the batch landed in.")
    session_readings_count: int = Field(
        ..., description="Total readings in this session so far."
    )
    token_expires_at: datetime = Field(
        ...,
        description=(
            "When the current token stops working. Re-authenticate with the "
            "device secret at or before this instant to keep logging."
        ),
    )


class TemperatureLogOutput(AuditFields, BaseModel):
    """A stored reading returned to callers."""

    temperature_log_id: int = Field(
        ...,
        validation_alias="id",
        description="Unique id of the stored temperature reading.",
        examples=[1],
    )
    temp_device_id: str = Field(..., description="Hardware id reported by the device.")
    temperature: float = Field(..., description="Temperature reading value (°C).")
    recorded_at: datetime | None = Field(
        None, description="Device-reported time the reading was taken."
    )
    probe: str | None = Field(None, description="Probe / sensor id within the device.")
    status: str | None = Field(None, description="Reading status, e.g. Normal / High / Low.")

    temperature_device_id: int | None = Field(
        None, description="Registered device this reading came from."
    )
    session_id: int | None = Field(None, description="Logging session it was pushed in.")
    pharmacy_id: int | None = Field(
        None, validation_alias="medical_store_id", description="Owning pharmacy."
    )
    raw_payload: dict | None = Field(
        None, description="The reading object exactly as the device sent it."
    )
    device_nickname: str | None = Field(
        None, description="Label of the device, joined in for display."
    )


class TemperatureLogListOutput(BaseModel):
    """A page of readings."""

    pharmacy_id: int = Field(..., description="Pharmacy the readings belong to.")
    items: list[TemperatureLogOutput] = Field(default_factory=list)
    total: int = Field(0, description="Total readings matching the filters.")
    skip: int = Field(0)
    limit: int = Field(50)


class TemperatureDeviceSummary(BaseModel):
    """Per-device snapshot powering the dashboard header card."""

    temperature_device_id: int
    nickname: str
    is_active: bool
    is_logging: bool = Field(..., description="True while a logging session is open.")
    session_id: int | None = None
    session_started_at: datetime | None = None
    token_expires_at: datetime | None = None
    last_seen_at: datetime | None = None
    latest_temperature: float | None = Field(None, description="Newest reading value (°C).")
    latest_recorded_at: datetime | None = None
    latest_status: str | None = None
    latest_probe: str | None = None
    total_readings: int = 0
    readings_in_window: int = Field(
        0, description="Readings within the summary window (see `hours`)."
    )
    min_temperature: float | None = Field(None, description="Lowest reading in the window.")
    max_temperature: float | None = Field(None, description="Highest reading in the window.")
    avg_temperature: float | None = Field(None, description="Mean reading in the window.")
    excursions_in_window: int = Field(
        0, description="Readings outside the safe range within the window."
    )


class TemperatureSummaryOutput(BaseModel):
    """Summary across every device in a pharmacy."""

    pharmacy_id: int
    hours: int = Field(..., description="Width of the statistics window, in hours.")
    safe_min_c: float = Field(..., description="Lower bound of the safe range.")
    safe_max_c: float = Field(..., description="Upper bound of the safe range.")
    devices: list[TemperatureDeviceSummary] = Field(default_factory=list)
