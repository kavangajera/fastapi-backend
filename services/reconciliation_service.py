"""
services/reconciliation_service.py
──────────────────────────────────
Invoice-vs-billed cross-reconciliation (Ultimate feature
``invoice_billed_cross_reconciliation``).

Per NDC, for one medical store, compares:
  - **invoiced** quantity — what the pharmacy *purchased*
    (``invoice_line_items.invoiced_qty`` via ``invoices``), and
  - **dispensed** quantity — what it *billed out*
    (sum of ``dispenses.qty_disp`` via ``medicines`` → ``drug_reports``).

The headline compliance signal is **dispensed > invoiced** — a drug billed out
in greater quantity than was ever purchased. A dispensed NDC with NO invoice
line item at all gets its own ``NEVER_INVOICED`` status (not lumped into
``OVER_BILLED``) so the UI can surface "No Invoice Record Found" distinctly.

NOTE: this is a **quantity-level** comparison, not pack-size normalized. Invoice
quantities may be in packages while dispensed quantities are in units;
pack-size-aware reconciliation is a separate check (Module C /
``pack_size_billed_reconciliation``). Deltas here are directional indicators,
not exact unit ledgers — surfaced for human review.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.dispense_report import Dispense, DrugReport, Medicine
from models.invoice import Invoice, InvoiceLineItem

# Status codes for a per-NDC reconciliation row.
STATUS_MATCHED = "MATCHED"            # dispensed == invoiced
STATUS_OVER_BILLED = "OVER_BILLED"   # dispensed > invoiced (billed more than bought)
STATUS_UNDER_DISPENSED = "UNDER_DISPENSED"  # invoiced > dispensed (bought more than billed)
STATUS_NEVER_INVOICED = "NEVER_INVOICED"  # dispensed but this NDC has no invoice line item at all

_NEVER_INVOICED_MESSAGE = (
    "No Invoice Record Found — upload the invoice that brought this drug in, "
    "or verify the NDC."
)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _status(invoiced: Decimal, dispensed: Decimal, ever_invoiced: bool) -> str:
    if not ever_invoiced:
        return STATUS_NEVER_INVOICED
    if dispensed > invoiced:
        return STATUS_OVER_BILLED
    if invoiced > dispensed:
        return STATUS_UNDER_DISPENSED
    return STATUS_MATCHED


async def invoice_vs_billed(
    db: AsyncSession, medical_store_id: int, only_mismatch: bool = False
) -> tuple[list[dict], dict]:
    """Return (rows, summary). Each row is one NDC with invoiced/dispensed/delta."""
    # ── Dispensed (billed-out) qty per NDC — qty_disp is Numeric, sum in SQL ──
    disp_stmt = (
        select(
            Medicine.ndc,
            func.coalesce(func.sum(Dispense.qty_disp), 0),
            func.min(Medicine.drug_name),
        )
        .join(Dispense, Dispense.medicine_id == Medicine.id)
        .join(DrugReport, DrugReport.id == Medicine.report_id)
        .where(DrugReport.medical_store_id == medical_store_id)
        .group_by(Medicine.ndc)
    )
    dispensed: dict[str, tuple[Decimal, str | None]] = {}
    for ndc, qty, name in (await db.execute(disp_stmt)).all():
        dispensed[ndc] = (Decimal(str(qty or 0)), name)

    # ── Invoiced (purchased) qty per NDC — invoiced_qty is String, sum in Py ──
    inv_stmt = (
        select(
            InvoiceLineItem.ndc11,
            InvoiceLineItem.invoiced_qty,
            InvoiceLineItem.description,
        )
        .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
        .where(
            Invoice.medical_store_id == medical_store_id,
            InvoiceLineItem.ndc11.isnot(None),
        )
    )
    invoiced: dict[str, list] = defaultdict(lambda: [Decimal(0), None])
    for ndc11, qty, desc in (await db.execute(inv_stmt)).all():
        parsed = _to_decimal(qty)
        if parsed is not None:
            invoiced[ndc11][0] += parsed
        if invoiced[ndc11][1] is None and desc:
            invoiced[ndc11][1] = desc

    # ── Merge on the union of NDCs ──
    rows: list[dict] = []
    over = under = matched = never = 0
    for ndc in set(dispensed) | set(invoiced):
        disp_qty, disp_name = dispensed.get(ndc, (Decimal(0), None))
        ever_invoiced = ndc in invoiced
        inv_qty, inv_name = invoiced.get(ndc, [Decimal(0), None])
        status = _status(inv_qty, disp_qty, ever_invoiced)
        if status == STATUS_NEVER_INVOICED:
            never += 1
        elif status == STATUS_OVER_BILLED:
            over += 1
        elif status == STATUS_UNDER_DISPENSED:
            under += 1
        else:
            matched += 1
        if only_mismatch and status == STATUS_MATCHED:
            continue
        rows.append(
            {
                "ndc": ndc,
                "drug_name": disp_name or inv_name,
                "invoiced_qty": str(inv_qty),
                "dispensed_qty": str(disp_qty),
                "delta": str(disp_qty - inv_qty),  # dispensed − invoiced
                "status": status,
                "message": _NEVER_INVOICED_MESSAGE if status == STATUS_NEVER_INVOICED else None,
            }
        )

    # Most concerning first: never-invoiced, then over-billed, then biggest absolute delta.
    _status_rank = {STATUS_NEVER_INVOICED: 0, STATUS_OVER_BILLED: 1}
    rows.sort(
        key=lambda r: (
            _status_rank.get(r["status"], 2),
            -abs(Decimal(r["delta"])),
        )
    )
    summary = {
        "ndc_count": over + under + matched + never,
        "over_billed": over,
        "under_dispensed": under,
        "matched": matched,
        "never_invoiced": never,
    }
    return rows, summary
