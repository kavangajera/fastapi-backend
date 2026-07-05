"""
services/record_id_service.py
─────────────────────────────
Server-side generation of ``record_Identifier`` / ``update_record_Identifier``.

The server is the sole authority for these sync keys (clients supply only a
``device_id`` in the request body). Two entry points are used at every
create / update site:

  - ``stamp_on_create(db, obj, device_id)`` — sets ``record_Identifier`` once.
  - ``stamp_on_update(db, obj, device_id)`` — (re)writes ``update_record_Identifier``.

Both draw the next value from a monotonic per-(device, table) counter, run in
the **same transaction** as the row being written, so a rollback reclaims the
value (no gaps from failed writes).

Device lifecycle (``resolve_device`` / ``generate_unique_device_id``) is used
by login and signup to register the calling device and pin its
``source_prefix`` (e.g. ``AN001``).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.record_ids import (
    DEFAULT_SOURCE_PREFIX,
    WEB_DEVICE_ID,
    build_record_identifier,
    is_valid_device_id,
    new_device_id,
)
from models.device import Device

_MAX_DEVICE_ID_ATTEMPTS = 12


async def _next_count(db: AsyncSession, device_id: str, table_name: str) -> int:
    """Atomically bump and return the next counter for (device, table).

    MySQL ``LAST_INSERT_ID(expr)`` idiom: the INSERT branch seeds the counter
    at 1 and stashes it in the session's ``LAST_INSERT_ID``; the ON DUPLICATE
    branch increments and re-stashes. Both statements run on the same
    connection inside the caller's open transaction, so the read-back is exact.
    """
    await db.execute(
        text(
            "INSERT INTO record_counter (device_id, table_name, last_count) "
            "VALUES (:d, :t, LAST_INSERT_ID(1)) "
            "ON DUPLICATE KEY UPDATE last_count = LAST_INSERT_ID(last_count + 1)"
        ),
        {"d": device_id, "t": table_name},
    )
    result = await db.execute(text("SELECT LAST_INSERT_ID()"))
    return int(result.scalar_one())


async def _source_prefix(db: AsyncSession, device_id: str) -> str:
    device = await db.get(Device, device_id)
    if device is not None and device.source_prefix:
        return device.source_prefix
    return DEFAULT_SOURCE_PREFIX


def _normalize_device_id(device_id: str | None) -> str:
    """Fall back to the web/server sentinel for missing or malformed ids."""
    return device_id if is_valid_device_id(device_id) else WEB_DEVICE_ID


async def _generate(db: AsyncSession, table_name: str, device_id: str) -> str:
    source = await _source_prefix(db, device_id)
    count = await _next_count(db, device_id, table_name)
    return build_record_identifier(source, device_id, table_name, count)


async def stamp_on_create(db: AsyncSession, obj, device_id: str | None) -> None:
    """Generate and set ``record_Identifier`` on a freshly-built ORM row."""
    device_id = _normalize_device_id(device_id)
    obj.record_Identifier = await _generate(db, obj.__tablename__, device_id)


async def stamp_on_update(db: AsyncSession, obj, device_id: str | None) -> None:
    """Generate and set ``update_record_Identifier`` for an edited ORM row.

    ``record_Identifier`` (the create-time id) is left untouched.
    """
    device_id = _normalize_device_id(device_id)
    obj.update_record_Identifier = await _generate(db, obj.__tablename__, device_id)


async def generate_unique_device_id(db: AsyncSession) -> str:
    """A random 6-char device id not already present in the device table."""
    for _ in range(_MAX_DEVICE_ID_ATTEMPTS):
        candidate = new_device_id()
        if await db.get(Device, candidate) is None:
            return candidate
    raise RuntimeError("Could not allocate a unique device id")


async def resolve_device(
    db: AsyncSession,
    *,
    device_id: str | None,
    source_prefix: str | None = None,
    platform: str | None = None,
    user_id: int | None = None,
) -> Device:
    """Register or refresh the calling device and return the canonical row.

    - A valid client-supplied ``device_id`` is honored (created if new).
    - A missing / malformed one is replaced with a freshly generated id.
    Callers should return ``device.device_id`` to the client so it adopts the
    server's canonical value.
    """
    if not is_valid_device_id(device_id):
        device_id = await generate_unique_device_id(db)

    device = await db.get(Device, device_id)
    if device is None:
        device = Device(
            device_id=device_id,
            source_prefix=source_prefix or DEFAULT_SOURCE_PREFIX,
            source_platform=platform,
            user_id=user_id,
        )
        db.add(device)
    else:
        if source_prefix:
            device.source_prefix = source_prefix
        if platform:
            device.source_platform = platform
        if user_id is not None:
            device.user_id = user_id

    await db.flush()
    return device
