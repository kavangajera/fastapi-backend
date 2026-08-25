"""
services/audit_dismissal_service.py
───────────────────────────────────
Read/write helpers for audit-report dismissals (models/audit_dismissal).

The audit report is derived from `documents` and `drug_reports` on every
request, so "clear this row" cannot delete anything — the underlying
document or force-saved report IS the compliance record. Instead the
dismissal is recorded and the derived rows are filtered against it.

Restoring flips the same row back (`IsDeleted = False`) rather than
inserting a second one, so a dismiss → restore → dismiss cycle never
accumulates duplicates behind the unique key.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditDismissal

DISMISS_PARSING = "parsing"
DISMISS_VALIDATION = "validation"
VALID_KINDS = (DISMISS_PARSING, DISMISS_VALIDATION)


async def fetch_dismissed(db: AsyncSession, medical_store_id: int) -> dict[str, set[str]]:
    """`{kind: {ref, ...}}` for one pharmacy's live dismissals."""
    rows = (
        await db.execute(
            select(AuditDismissal.kind, AuditDismissal.ref).where(
                AuditDismissal.medical_store_id == medical_store_id
            )
        )
    ).all()
    out: dict[str, set[str]] = {}
    for kind, ref in rows:
        out.setdefault(kind, set()).add(ref)
    return out


async def dismiss(
    db: AsyncSession,
    *,
    medical_store_id: int,
    kind: str,
    refs: list[str],
    user_id: int | None,
) -> int:
    """Clear `refs` from the audit report. Idempotent — re-dismissing an
    already-cleared entry is a no-op, not a duplicate-key error."""
    if not refs:
        return 0

    # `include_deleted` so a previously restored dismissal is reused: the
    # unique key (store, kind, ref) still holds it, and a plain INSERT would
    # collide with a row the default read filter cannot see.
    existing = {
        row.ref: row
        for row in (
            await db.execute(
                select(AuditDismissal)
                .where(
                    AuditDismissal.medical_store_id == medical_store_id,
                    AuditDismissal.kind == kind,
                    AuditDismissal.ref.in_(refs),
                )
                .execution_options(include_deleted=True)
            )
        ).scalars()
    }

    changed = 0
    for ref in dict.fromkeys(refs):  # de-dupe, keep order
        row = existing.get(ref)
        if row is None:
            db.add(
                AuditDismissal(
                    medical_store_id=medical_store_id,
                    kind=kind,
                    ref=ref,
                    dismissed_by_user_id=user_id,
                )
            )
            changed += 1
        elif row.IsDeleted:
            row.IsDeleted = False  # the before_flush hook clears delete_date_at
            row.dismissed_by_user_id = user_id
            changed += 1
    return changed


async def restore(
    db: AsyncSession, *, medical_store_id: int, kind: str, refs: list[str]
) -> int:
    """Bring `refs` back into the audit report by soft-deleting the dismissal."""
    if not refs:
        return 0
    rows = (
        await db.execute(
            select(AuditDismissal).where(
                AuditDismissal.medical_store_id == medical_store_id,
                AuditDismissal.kind == kind,
                AuditDismissal.ref.in_(refs),
            )
        )
    ).scalars().all()
    for row in rows:
        row.IsDeleted = True
    return len(rows)
