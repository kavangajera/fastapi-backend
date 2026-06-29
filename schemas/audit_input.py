"""
schemas/audit_input.py
──────────────────────
Optional, client-supplied sync keys accepted on create/update requests.

Mixed into request schemas so the mobile app can send its own
``record_Identifier`` (on create) and ``update_record_Identifier`` (on
edit). Both are **optional** — web / legacy callers may omit them and the
column is stored as NULL.

Rules (per the app team's spec):
  - ``record_Identifier``        — set once, on **create**; never changed
                                    afterwards.
  - ``update_record_Identifier`` — (re)written by the client only when the
                                    record is **edited**.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuditInputFields(BaseModel):
    record_Identifier: str | None = Field(
        None,
        description="Client-generated record identifier. Set once on create; omit to leave NULL.",
        examples=["AN001111111PRO000001"],
    )
    update_record_Identifier: str | None = Field(
        None,
        description="Client-generated identifier of the editing device; sent when the record is modified.",
        examples=["AN001111111PRO000001"],
    )


def apply_record_identifier_on_create(obj, data) -> None:
    """Copy client-supplied sync keys onto a freshly-built ORM row (create)."""
    rid = getattr(data, "record_Identifier", None)
    if rid is not None:
        obj.record_Identifier = rid
    urid = getattr(data, "update_record_Identifier", None)
    if urid is not None:
        obj.update_record_Identifier = urid


def apply_record_identifier_on_update(obj, data) -> None:
    """Update only ``update_record_Identifier`` (never the original ``record_Identifier``)."""
    urid = getattr(data, "update_record_Identifier", None)
    if urid is not None:
        obj.update_record_Identifier = urid
