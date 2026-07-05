"""
schemas/audit_fields.py
───────────────────────
Pydantic mirror of the ORM ``AuditMixin`` (``core/async_db.py``).

Every entity response schema inherits ``AuditFields`` so the frontend and
application developers receive the same record-metadata on each record:
a stable opaque identifier, a soft-delete flag, and UTC timestamps.

``from_attributes=True`` lets schemas that validate ORM rows directly
pick these up automatically; the fields are Optional so hand-built
payloads that don't set them never fail validation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditFields(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    record_Identifier: str | None = None
    update_record_Identifier: str | None = None
    IsDeleted: bool = False
    delete_date_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    global_time_at: datetime | None = None
