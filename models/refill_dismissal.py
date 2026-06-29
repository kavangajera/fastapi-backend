"""
models/refill_dismissal.py
──────────────────────────
Owner opt-out for the refill-due list.

`GET /pharmacy/{id}/refills` derives "who is due for a refill" from the
latest dispense per patient+drug. When the owner no longer wants to track a
customer, we record a dismissal here instead of deleting dispense history —
so the audit trail and inventory math stay intact while the customer drops
off the refill list.

`patient_key` is the hashed, de-identified key from
`services/validation/patient_key.py` (never raw PHI). `drug_ndc` uses the
empty string `""` as the "all drugs" sentinel (so the UNIQUE constraint
treats it as a real value — MySQL allows duplicate NULLs in a unique key);
a real NDC dismisses only that medicine for that customer.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import AuditMixin, Base


class RefillDismissal(AuditMixin, Base):
    __tablename__ = "refill_dismissals"

    __table_args__ = (
        UniqueConstraint(
            "medical_store_id", "patient_key", "drug_ndc", name="uq_refill_dismissal"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # "" = dismiss the customer for every drug; otherwise scope to one NDC.
    drug_ndc: Mapped[str] = mapped_column(
        String(11), nullable=False, default="", server_default=""
    )

    dismissed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<RefillDismissal ms_id={self.medical_store_id} "
            f"patient_key={self.patient_key!r} ndc={self.drug_ndc!r}>"
        )
