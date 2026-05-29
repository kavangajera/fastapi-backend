from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class DispenseReconciliation(Base):
    __tablename__ = "dispense_reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drug_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ndc11: Mapped[str] = mapped_column(String(11), nullable=False, index=True)

    invoice_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    dispensed_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    remaining_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)

    report = relationship("DrugReport")
