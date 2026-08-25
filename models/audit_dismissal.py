"""
models/audit_dismissal.py
─────────────────────────
Rows the owner has cleared from the audit report.

The audit report has no table of its own — it is derived on every request
from failed `documents` and force-saved `drug_reports`
(routes/audit_report.py). So "clearing" an entry cannot delete anything
without destroying the underlying compliance record; instead we remember
the dismissal here and filter the derived rows against it.

`ref` identifies what was dismissed within its `kind`:
    kind="parsing"     → the Document's `doc_key`
    kind="validation"  → the DrugReport id, as a string

A dismissal is itself soft-deletable (AuditMixin), which is how "restore"
works: the dismissal row is flagged and the audit entry reappears.
"""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import AuditMixin, Base


class AuditDismissal(AuditMixin, Base):
    __tablename__ = "audit_dismissals"

    __table_args__ = (
        UniqueConstraint(
            "medical_store_id", "kind", "ref", name="uq_audit_dismissal_store_kind_ref"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "parsing" | "validation" — kept as a plain string so a new audit section
    # doesn't need a schema migration to become dismissible.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    dismissed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<AuditDismissal medical_store_id={self.medical_store_id} "
            f"kind={self.kind!r} ref={self.ref!r}>"
        )
