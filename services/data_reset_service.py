"""
services/data_reset_service.py
───────────────────────────────
"RESET DATA" — soft-deletes every pharmacy-scoped row for one
`medical_store_id`. Every touched model already carries `AuditMixin`
(`core/async_db.py`), which supplies `IsDeleted`/`delete_date_at` and an
automatic soft-delete read filter — so this needs no schema changes.

`MedicineNdcCache` is deliberately NOT touched: it has no `medical_store_id`
(it's a global, shared FDA lookup cache), not pharmacy data.

Uses bulk `update()` statements rather than ORM object mutation for
efficiency on potentially large tables. Bulk `update()` bypasses the
`before_flush` hook that normally auto-stamps `delete_date_at`
(`core/async_db.py:143-159`), so each statement sets it explicitly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.dispense_report import Dispense, DrugReport, Medicine
from models.document import Document
from models.invoice import Invoice, InvoiceLineItem, InvoiceSummary
from models.medicine_inventory import MedicineInventory


async def reset_pharmacy_data(db: AsyncSession, ph_id: int) -> dict[str, int]:
    """Soft-delete every row belonging to `ph_id`. Returns per-table counts."""
    now = datetime.utcnow()
    counts: dict[str, int] = {}

    async def _soft_delete(model, where_clause, key: str) -> None:
        stmt = (
            update(model)
            .where(where_clause, model.IsDeleted.is_(False))
            .values(IsDeleted=True, delete_date_at=now)
        )
        result = await db.execute(stmt)
        counts[key] = result.rowcount or 0

    report_ids_subq = select(DrugReport.id).where(DrugReport.medical_store_id == ph_id)
    invoice_ids_subq = select(Invoice.id).where(Invoice.medical_store_id == ph_id)

    await _soft_delete(Dispense, Dispense.medical_store_id == ph_id, "dispenses_deleted")
    await _soft_delete(Medicine, Medicine.report_id.in_(report_ids_subq), "medicines_deleted")
    await _soft_delete(DrugReport, DrugReport.medical_store_id == ph_id, "drug_reports_deleted")
    await _soft_delete(
        InvoiceLineItem,
        InvoiceLineItem.invoice_id.in_(invoice_ids_subq),
        "invoice_line_items_deleted",
    )
    await _soft_delete(
        InvoiceSummary,
        InvoiceSummary.invoice_id.in_(invoice_ids_subq),
        "invoice_summaries_deleted",
    )
    await _soft_delete(Invoice, Invoice.medical_store_id == ph_id, "invoices_deleted")
    await _soft_delete(
        MedicineInventory, MedicineInventory.medical_store_id == ph_id, "inventory_rows_deleted"
    )
    await _soft_delete(Document, Document.medical_store_id == ph_id, "documents_deleted")

    return counts
