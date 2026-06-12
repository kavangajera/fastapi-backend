"""
services/inventory_service.py
─────────────────────────────
Running stock per (medical_store_id, code). +qty on every saved invoice
line item; −qty on every dispensed medicine. Uses MySQL's
`INSERT ... ON DUPLICATE KEY UPDATE` for the upsert so concurrent writes
don't race on the composite unique key (medical_store_id, code).

`code` is the matching key:
    - prefer 11-digit NDC,
    - fall back to UPC.

`services/ndc_utils.py::ndc10_to_ndc11_from_package_ndc` is used to
normalize hyphenated 10-digit NDCs that the dispense extractor sometimes
emits.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import Dispense, Invoice, InvoiceLineItem, Medicine, MedicineInventory
from services.ndc_utils import digits_only, ndc10_to_ndc11_from_package_ndc

# ── code resolution ─────────────────────────────────────────────────────────


def _pick_code(ndc11: str | None, upc: str | None) -> str | None:
    """Return the inventory key for an invoice line item."""
    if ndc11 and digits_only(ndc11) and len(digits_only(ndc11)) == 11:
        return digits_only(ndc11)
    if upc and digits_only(upc):
        return digits_only(upc)
    return None


def _normalize_ndc(ndc: str | None) -> str | None:
    """Best-effort 11-digit NDC from a dispense medicine row."""
    if not ndc:
        return None
    cleaned = digits_only(ndc)
    if len(cleaned) == 11:
        return cleaned
    if len(cleaned) == 10 and "-" in ndc:
        normalized = ndc10_to_ndc11_from_package_ndc(ndc)
        if normalized:
            return normalized
    return cleaned or None


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


# ── upsert helper ───────────────────────────────────────────────────────────


async def _upsert_delta(
    session: AsyncSession,
    *,
    medical_store_id: int,
    code: str,
    delta: Decimal,
    product_name: str | None,
    last_invoice_id: int | None,
) -> Decimal:
    """
    `INSERT ... ON DUPLICATE KEY UPDATE` against medicine_inventory.

    Returns the new quantity after the upsert.
    """
    stmt = mysql_insert(MedicineInventory).values(
        medical_store_id=medical_store_id,
        code=code,
        product_name=product_name,
        quantity=delta,
        last_invoice_id=last_invoice_id,
    )
    stmt = stmt.on_duplicate_key_update(
        quantity=MedicineInventory.quantity + stmt.inserted.quantity,
        # Keep an existing product_name if we now have None; otherwise prefer the new one.
        product_name=stmt.inserted.product_name,
        last_invoice_id=stmt.inserted.last_invoice_id,
    )
    await session.execute(stmt)

    # Read back the resulting quantity so the response can echo it.
    qty = await session.execute(
        select(MedicineInventory.quantity).where(
            MedicineInventory.medical_store_id == medical_store_id,
            MedicineInventory.code == code,
        )
    )
    return qty.scalar_one()


# ── public API ──────────────────────────────────────────────────────────────


async def add_invoice_quantities(
    session: AsyncSession,
    *,
    medical_store_id: int,
    invoice_id: int,
) -> list[dict]:
    """
    For every line item on `invoice_id`, +invoiced_qty into inventory.

    Returns one dict per inventory mutation:
        {code, delta, new_quantity}
    """
    rows = await session.execute(
        select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
    )
    line_items = list(rows.scalars().all())

    updates: list[dict] = []
    for item in line_items:
        code = _pick_code(item.ndc11, item.upc)
        if not code:
            continue
        qty = _to_decimal(item.invoiced_qty) or _to_decimal(item.order_qty)
        if qty is None or qty == 0:
            continue
        new_qty = await _upsert_delta(
            session,
            medical_store_id=medical_store_id,
            code=code,
            delta=qty,
            product_name=item.description,
            last_invoice_id=invoice_id,
        )
        updates.append({"code": code, "delta": str(qty), "new_quantity": str(new_qty)})

    await session.flush()
    logger.info(
        "Inventory +invoice: ms_id={ph} invoice_id={iid} touched={n}",
        ph=medical_store_id,
        iid=invoice_id,
        n=len(updates),
    )
    return updates


async def subtract_dispense_quantities(
    session: AsyncSession,
    *,
    medical_store_id: int,
    drug_report_id: int,
) -> list[dict]:
    """
    For every medicine on `drug_report_id`, −sum(qty_disp) from inventory.
    Creates a negative-balance row if no matching inventory exists.
    """
    med_rows = await session.execute(select(Medicine).where(Medicine.report_id == drug_report_id))
    medicines = list(med_rows.scalars().all())

    updates: list[dict] = []
    for med in medicines:
        code = _normalize_ndc(med.ndc)
        if not code:
            continue

        disp_rows = await session.execute(
            select(Dispense.qty_disp).where(Dispense.medicine_id == med.id)
        )
        total = Decimal("0")
        any_qty = False
        for (qty,) in disp_rows.all():
            if qty is None:
                continue
            total += Decimal(qty)
            any_qty = True
        if not any_qty or total == 0:
            continue

        new_qty = await _upsert_delta(
            session,
            medical_store_id=medical_store_id,
            code=code,
            delta=-total,
            product_name=med.drug_name,
            last_invoice_id=None,
        )
        updates.append({"code": code, "delta": str(-total), "new_quantity": str(new_qty)})

    await session.flush()
    logger.info(
        "Inventory -dispense: ms_id={ph} drug_report_id={r} touched={n}",
        ph=medical_store_id,
        r=drug_report_id,
        n=len(updates),
    )
    return updates


async def get_inventory(session: AsyncSession, *, medical_store_id: int) -> list[MedicineInventory]:
    rows = await session.execute(
        select(MedicineInventory)
        .where(MedicineInventory.medical_store_id == medical_store_id)
        .order_by(MedicineInventory.code.asc())
    )
    return list(rows.scalars().all())


# Exported for the save routes that need to look up an existing invoice
# before recording inventory.
async def get_invoice_or_none(session: AsyncSession, *, invoice_id: int) -> Invoice | None:
    res = await session.execute(select(Invoice).where(Invoice.id == invoice_id))
    return res.scalar_one_or_none()
