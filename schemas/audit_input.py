"""
schemas/audit_input.py
──────────────────────
Client-supplied sync input on create/update requests.

Record identifiers are now **server-generated** (see
``services/record_id_service.py``), so the client no longer sends
``record_Identifier`` / ``update_record_Identifier``. It sends only its
``device_id`` — the 6-char alphanumeric device key — which the server folds
into the generated identifier.

``device_id`` is **optional** at the schema level so existing web/dashboard
callers keep working: when it is absent (or malformed) the server stamps the
row under the ``WEB000`` sentinel device instead of rejecting the request.
Mobile clients send it on every write per the app spec. To *require* it,
change the default below to ``...``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.record_ids import DEVICE_ID_LENGTH


class AuditInputFields(BaseModel):
    device_id: str | None = Field(
        None,
        min_length=DEVICE_ID_LENGTH,
        max_length=DEVICE_ID_LENGTH,
        pattern=r"^[A-Za-z0-9]+$",
        description=(
            "6-char alphanumeric device id (client-generated at login). Folded "
            "into the server-generated record identifier. Omit for web/server "
            "writes (stamped under the WEB000 sentinel device)."
        ),
        examples=["a1B2c3"],
    )
