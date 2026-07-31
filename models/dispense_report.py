"""
models/dispense_report.py
─────────────────────────
Domain models for *dispensed* prescription reports — the records of what
medicines a pharmacy actually gave to patients (versus what it bought,
which lives in `models/invoice.py`).

Table names kept intentionally as `drug_reports` / `medicines` /
`dispenses` for backward-compatible queries; only the Python module was
renamed from `pharmacy_purchase_report.py` because that name conflated
purchases (invoices) with dispenses.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import AuditMixin, Base


class DrugReport(AuditMixin, Base):
    __tablename__ = "drug_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    report_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_from_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_to_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pharmacy_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pharmacy_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    pharmacy_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pharmacy_fax: Mapped[str | None] = mapped_column(String(30), nullable=True)

    grand_total_rx_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grand_total_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    grand_total_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    grand_total_ins_paid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Set when the owner force-saves past blocking validation errors. The
    # full blocking-alert list is stashed in `validation_errors` so the
    # audit report can replay exactly what was wrong at save time.
    force_saved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)

    medicines: Mapped[list["Medicine"]] = relationship(
        "Medicine",
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<DrugReport id={self.id} medical_store_id={self.medical_store_id} "
            f"from={self.report_from_date} to={self.report_to_date}>"
        )


class Medicine(AuditMixin, Base):
    __tablename__ = "medicines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("drug_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    drug_name: Mapped[str] = mapped_column(String(300), nullable=False)
    ndc: Mapped[str] = mapped_column(String(11), nullable=False, index=True)
    inventory_bucket: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lot_no_exp_date: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lot_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expiration_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pack_size: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    generic_indicator: Mapped[str | None] = mapped_column(String(50), nullable=True)
    strength: Mapped[str | None] = mapped_column(String(100), nullable=True)
    daw_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    drug_schedule: Mapped[str | None] = mapped_column(String(30), nullable=True)

    total_packs: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    total_quantity_dispensed: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    total_rx_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_ins_paid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Per-row validation errors captured on force-save (the alerts whose
    # `medicine_index` pointed at this medicine). NULL when the row was clean.
    has_errors: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)

    report: Mapped["DrugReport"] = relationship("DrugReport", back_populates="medicines")
    dispenses: Mapped[list["Dispense"]] = relationship(
        "Dispense",
        back_populates="medicine",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Medicine id={self.id} ndc={self.ndc!r} drug={self.drug_name!r}>"


class Dispense(AuditMixin, Base):
    __tablename__ = "dispenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    medicine_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("medicines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    medical_store_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    qty_disp: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    qty_ord: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    days_supply: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_filled: Mapped[str | None] = mapped_column(String(12), nullable=True)

    rx_no: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    ref: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    pat_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pat_addr: Mapped[str | None] = mapped_column(Text, nullable=True)
    pat_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    patient_dob: Mapped[str | None] = mapped_column(String(20), nullable=True)
    patient_gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    patient_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    pres_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pres_addr: Mapped[str | None] = mapped_column(Text, nullable=True)
    pres_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    prescriber_dea: Mapped[str | None] = mapped_column(String(30), nullable=True)
    prescriber_npi: Mapped[str | None] = mapped_column(String(30), nullable=True)

    date_written: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_sold: Mapped[str | None] = mapped_column(String(20), nullable=True)
    will_call_date: Mapped[str | None] = mapped_column(String(20), nullable=True)

    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ins_paid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ins_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    patient_copay: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cash_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extraction_warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("medical_store_id", "rx_no", name="uq_dispenses_store_rx_no"),
    )

    medicine: Mapped["Medicine"] = relationship("Medicine", back_populates="dispenses")

    def __repr__(self) -> str:
        return (
            f"<Dispense id={self.id} rx_no={self.rx_no!r} "
            f"pat={self.pat_name!r} date={self.date_filled!r}>"
        )
