from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


# ---------------------------------------------------------------------------
# drug_reports
# ---------------------------------------------------------------------------
class DrugReport(Base):
    """
    One row per PDF upload.
    Stores pharmacy header info, the report date range, and the grand total.
    """

    __tablename__ = "drug_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    # ── Pharmacy header ──────────────────────────────────────────────────────
    pharmacy_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    pharmacy_address: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    pharmacy_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    pharmacy_fax: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # ── Report meta ──────────────────────────────────────────────────────────
    report_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)        # e.g. "2/1/2026"
    report_from_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # e.g. "1/30/2026"
    report_to_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)     # e.g. "2/1/2026"

    # ── Grand total (bottom of report) ───────────────────────────────────────
    grand_total_rx_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    grand_total_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    grand_total_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    # ── Relationships ────────────────────────────────────────────────────────
    medicines: Mapped[List["Medicine"]] = relationship(
        "Medicine", back_populates="report", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<DrugReport id={self.id} pharmacy={self.pharmacy_name!r} "
            f"from={self.report_from_date} to={self.report_to_date}>"
        )


# ---------------------------------------------------------------------------
# medicines
# ---------------------------------------------------------------------------
class Medicine(Base):
    """
    One row per unique NDC within a report.
    Stores drug-level totals (packs, total ins paid, total price, etc.).
    """

    __tablename__ = "medicines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drug_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Drug identity ─────────────────────────────────────────────────────────
    drug_name: Mapped[str] = mapped_column(String(300), nullable=False)
    ndc: Mapped[str] = mapped_column(String(11), nullable=False, index=True)          # 11-digit NDC
    inventory_bucket: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    lot_no_exp_date: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # ── Drug-level totals (from "Total For:" block in PDF) ────────────────────
    total_packs: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    total_rx_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_ins_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    total_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    total_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    report: Mapped["DrugReport"] = relationship("DrugReport", back_populates="medicines")
    dispenses: Mapped[List["Dispense"]] = relationship(
        "Dispense", back_populates="medicine", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Medicine id={self.id} ndc={self.ndc!r} drug={self.drug_name!r}>"


# ---------------------------------------------------------------------------
# dispenses
# ---------------------------------------------------------------------------
class Dispense(Base):
    """
    One row per prescription fill line in the report.
    Maps to the columns:
      Qty Disp | Qty Ord | Pat Name | Pat Addr/Ph | Days | Date Filled |
      Price | Pres Name | Pres Addr/Phone | Ins Paid | Ins Code | RxNo | Ref#
    """

    __tablename__ = "dispenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    medicine_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Quantities ────────────────────────────────────────────────────────────
    qty_disp: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)     # Qty Dispensed
    qty_ord: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)      # Qty Ordered
    days_supply: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    date_filled: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)      # MM/DD/YYYY string

    # ── Prescription identifiers ──────────────────────────────────────────────
    rx_no: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    ref: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)              # Refill number

    # ── Patient info ──────────────────────────────────────────────────────────
    pat_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    pat_addr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)               # Street address
    pat_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # ── Prescriber info ───────────────────────────────────────────────────────
    pres_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    pres_addr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pres_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # ── Financial ─────────────────────────────────────────────────────────────
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)        # Total price
    ins_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)     # Insurance paid amount
    ins_code: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)         # Insurance plan code

    # ── Relationships ─────────────────────────────────────────────────────────
    medicine: Mapped["Medicine"] = relationship("Medicine", back_populates="dispenses")

    def __repr__(self) -> str:
        return (
            f"<Dispense id={self.id} rx_no={self.rx_no!r} "
            f"pat={self.pat_name!r} date={self.date_filled!r}>"
        )