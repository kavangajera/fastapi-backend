"""
schemas/temperature_device.py
─────────────────────────────
Request / response schemas for the temperature-device registry and the
logging-session lifecycle.

Follows the id-prefix convention used across the codebase: responses expose
domain-prefixed ids (``temperature_device_id``, ``pharmacy_id``) while requests
keep the internal ``medical_store_id`` name, mapped via ``validation_alias``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from schemas.audit_fields import AuditFields

# ─────────────────────────────────────────────────────────────────────
# Registration / management (called by an authenticated pharmacy user)
# ─────────────────────────────────────────────────────────────────────


class TemperatureDeviceRegisterInput(BaseModel):
    """Register one logger against a pharmacy.

    ``device_secret`` is optional: supply the secret already burned into the
    hardware, or leave it out and the server generates a strong one and returns
    it **once** in the registration response.
    """

    medical_store_id: int = Field(
        ..., description="Pharmacy this device belongs to.", examples=[1]
    )
    nickname: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Human label for the device, e.g. 'Vaccine Fridge A'.",
        examples=["Vaccine Fridge A"],
    )
    device_secret: str | None = Field(
        None,
        description=(
            "Secret the device will authenticate with. Omit to have one "
            "generated — it is shown only in this response and never again."
        ),
        examples=["fridge-a-4f9c1d2e8b70"],
    )
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "medical_store_id": 1,
                "nickname": "Vaccine Fridge A",
                "device_secret": None,
            }
        }
    )


class TemperatureDeviceUpdateInput(BaseModel):
    """Rename a device or flip its kill switch. Omitted fields are untouched."""

    nickname: str | None = Field(None, min_length=1, max_length=120)
    is_active: bool | None = Field(
        None,
        description=(
            "Set false to disable the device: it can no longer start a session "
            "and its live token stops being accepted immediately."
        ),
    )


class TemperatureSessionOutput(AuditFields, BaseModel):
    """A logging session — the window between start-logging and stop-logging."""

    session_id: int = Field(..., description="Unique id of the logging session.")
    temperature_device_id: int = Field(..., description="Device the session belongs to.")
    pharmacy_id: int = Field(
        ..., validation_alias="medical_store_id", description="Owning pharmacy."
    )
    status: str = Field(..., description="ACTIVE | STOPPED.", examples=["ACTIVE"])
    started_at: datetime = Field(..., description="When logging started.")
    ended_at: datetime | None = Field(None, description="When logging was stopped.")
    end_reason: str | None = Field(None, description="Why the session ended.")
    token_issued_at: datetime | None = Field(
        None, description="When the session's current token was minted."
    )
    token_expires_at: datetime | None = Field(
        None, description="When the session's current token stops being accepted."
    )
    tokens_issued: int = Field(0, description="How many tokens this session has burned.")
    readings_count: int = Field(0, description="Readings pushed within this session.")
    last_reading_at: datetime | None = Field(None, description="Newest reading in the session.")


class TemperatureDeviceOutput(AuditFields, BaseModel):
    """A registered device. The secret is never echoed back — only its hint."""

    temperature_device_id: int = Field(..., description="Unique id of the device.")
    pharmacy_id: int = Field(
        ..., validation_alias="medical_store_id", description="Owning pharmacy."
    )
    nickname: str = Field(..., description="Human label for the device.")
    secret_hint: str | None = Field(
        None, description="Last few characters of the secret, for identification only."
    )
    is_active: bool = Field(True, description="False disables the device entirely.")
    registered_by_user_id: int | None = Field(None, description="Who registered it.")
    last_seen_at: datetime | None = Field(None, description="Last successful contact.")
    last_reading_at: datetime | None = Field(None, description="Newest reading received.")
    total_readings: int = Field(0, description="Lifetime readings stored for this device.")

    # Filled in by the service layer, not columns on the row.
    is_logging: bool = Field(
        False, description="True while the device has an ACTIVE logging session."
    )
    active_session: TemperatureSessionOutput | None = Field(
        None, description="The open logging session, if any."
    )
    latest_temperature: float | None = Field(None, description="Newest reading value (°C).")
    latest_status: str | None = Field(None, description="Status of the newest reading.")


class TemperatureDeviceRegisteredOutput(BaseModel):
    """Registration result — the only place a device secret is ever returned."""

    device: TemperatureDeviceOutput
    device_secret: str | None = Field(
        None,
        description=(
            "The device's secret. Returned ONLY here and only when the server "
            "generated it — store it on the device now, it cannot be retrieved later."
        ),
    )
    secret_generated: bool = Field(
        False, description="True when the server generated the secret."
    )


# ─────────────────────────────────────────────────────────────────────
# Session lifecycle (called by the device itself, with its secret)
# ─────────────────────────────────────────────────────────────────────


class DeviceSecretInput(BaseModel):
    """The device presenting its secret — start logging, renew, or stop."""

    device_secret: str = Field(
        ..., min_length=1, description="The secret supplied at registration."
    )

    model_config = ConfigDict(
        json_schema_extra={"example": {"device_secret": "tdev_9sK3n...f2Qa"}}
    )


class DeviceTokenOutput(BaseModel):
    """A freshly minted session token.

    Send it as ``Authorization: Bearer <access_token>`` on
    ``POST /temperature-logs``. When it expires, present the secret again —
    the logging session keeps running and only the token is replaced.
    """

    access_token: str = Field(..., description="The device session JWT.")
    token_type: str = Field("bearer", description="Always 'bearer'.")
    expires_at: datetime = Field(..., description="UTC instant the token stops working.")
    expires_in: int = Field(..., description="Seconds until expiry.", examples=[43200])
    session_id: int = Field(..., description="Logging session this token belongs to.")
    temperature_device_id: int = Field(..., description="Device the token authenticates.")
    pharmacy_id: int = Field(..., description="Owning pharmacy.")
    nickname: str = Field(..., description="Device label, echoed for convenience.")
    session_started_at: datetime = Field(..., description="When the session opened.")
    resumed: bool = Field(
        False,
        description=(
            "True when this token continues an already-open session (a renewal) "
            "rather than opening a new one."
        ),
    )


class StopLoggingOutput(BaseModel):
    """Result of stopping a logging session."""

    stopped: bool = Field(..., description="True if an open session was closed by this call.")
    already_stopped: bool = Field(
        False, description="True when there was no open session — the call is a no-op."
    )
    session: TemperatureSessionOutput | None = Field(None, description="The closed session.")
