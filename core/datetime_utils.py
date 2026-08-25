"""
core/datetime_utils.py
──────────────────────
One job: keep timezone-aware datetimes out of the naive-UTC columns.

Every ``DateTime`` column in this codebase is naive and holds UTC (see the
``AuditMixin`` docstring in ``core/async_db.py``). Inbound values do not respect
that: a browser's ``new Date().toISOString()`` produces ``…Z``, and firmware
commonly reports a local offset like ``+05:30``. Handing either straight to the
driver goes wrong two ways —

* the driver renders ``'2026-08-25 10:00:00+00:00'``, which MySQL rejects in
  strict mode and silently truncates otherwise; and
* mixing an aware value with a naive one (``datetime.utcnow()``) in the same
  comparison raises ``TypeError: can't compare offset-naive and offset-aware``.

``to_naive_utc`` converts to UTC and drops the tzinfo, so an offset is *honoured*
rather than discarded: ``16:10+05:30`` is stored as ``10:40``, the same instant.
Naive input is assumed to already be UTC and passes through untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone


def to_naive_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to naive UTC. ``None`` passes through."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
