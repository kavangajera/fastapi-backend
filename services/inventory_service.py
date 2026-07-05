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
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Dispense,
    Invoice,
    InvoiceLineItem,
    Medicine,
    MedicineInventory,
    MedicineNdcCache,
)
from services.ndc_utils import digits_only, ndc10_to_ndc11_from_package_ndc

# ── stock-status thresholds ───────────────────────────────────────────────────
# Derived label for the mobile app. Tweak the threshold here — nothing else
# depends on the exact numbers.
LOW_STOCK_THRESHOLD = Decimal("10")
STATUS_OUT_OF_STOCK = "Out of stock"
STATUS_LOW_STOCK = "Low stock"
STATUS_IN_STOCK = "In stock"


def derive_stock_status(quantity) -> str:
    """0 → Out of stock, 1..LOW_STOCK_THRESHOLD → Low stock, else → In stock."""
    qty = quantity if isinstance(quantity, Decimal) else (_to_decimal(quantity) or Decimal("0"))
    if qty <= 0:
        return STATUS_OUT_OF_STOCK
    if qty <= LOW_STOCK_THRESHOLD:
        return STATUS_LOW_STOCK
    return STATUS_IN_STOCK

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
    exp_date: str | None = None,
) -> Decimal:
    """
    `INSERT ... ON DUPLICATE KEY UPDATE` against medicine_inventory.

    Returns the new quantity after the upsert. `exp_date` is only ever set
    from a scanned barcode/QR; a NULL passed here leaves any existing value
    untouched (so a later non-scanned invoice doesn't wipe a known expiry).
    """
    stmt = mysql_insert(MedicineInventory).values(
        medical_store_id=medical_store_id,
        code=code,
        product_name=product_name,
        quantity=delta,
        last_invoice_id=last_invoice_id,
        exp_date=exp_date,
    )
    stmt = stmt.on_duplicate_key_update(
        quantity=MedicineInventory.quantity + stmt.inserted.quantity,
        # Keep an existing product_name if we now have None; otherwise prefer the new one.
        product_name=stmt.inserted.product_name,
        last_invoice_id=stmt.inserted.last_invoice_id,
        # Refresh expiry only when this line actually carried a scanned value.
        exp_date=func.coalesce(stmt.inserted.exp_date, MedicineInventory.exp_date),
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
            # Only present when this line was enriched from a barcode/QR scan.
            exp_date=item.dm_expiration_date,
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


async def search_inventory(
    session: AsyncSession,
    *,
    medical_store_id: int,
    q: str | None = None,
    only_negative: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[MedicineInventory], int]:
    """
    Filtered, paginated inventory. `q` matches code OR product_name.
    Returns (rows, total_count).
    """
    filters = [MedicineInventory.medical_store_id == medical_store_id]
    if q:
        like = f"%{q}%"
        filters.append(
            MedicineInventory.code.ilike(like) | MedicineInventory.product_name.ilike(like)
        )
    if only_negative:
        filters.append(MedicineInventory.quantity < 0)

    total = (
        await session.execute(select(func.count(MedicineInventory.id)).where(*filters))
    ).scalar() or 0

    rows = await session.execute(
        select(MedicineInventory)
        .where(*filters)
        .order_by(MedicineInventory.code.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(rows.scalars().all()), total


async def adjust_inventory(
    session: AsyncSession,
    *,
    medical_store_id: int,
    code: str,
    product_name: str | None = None,
    quantity: Decimal | None = None,
    exp_date: str | None = None,
    location: str | None = None,
) -> tuple[MedicineInventory | None, dict]:
    """
    Direct manual edit of an existing inventory row (no invoice/dispense).

    Only fields that are not None are changed. `quantity` is SET (absolute
    correction), not added. Returns (row, before/after diff). Returns
    (None, {}) if the row does not exist.
    """
    res = await session.execute(
        select(MedicineInventory).where(
            MedicineInventory.medical_store_id == medical_store_id,
            MedicineInventory.code == code,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        return None, {}

    diff: dict = {}
    if product_name is not None and product_name != row.product_name:
        diff["product_name"] = {"before": row.product_name, "after": product_name}
        row.product_name = product_name
    if quantity is not None and quantity != row.quantity:
        diff["quantity"] = {"before": str(row.quantity), "after": str(quantity)}
        row.quantity = quantity
    if exp_date is not None and exp_date != row.exp_date:
        diff["exp_date"] = {"before": row.exp_date, "after": exp_date}
        row.exp_date = exp_date
    if location is not None and location != row.location:
        diff["location"] = {"before": row.location, "after": location}
        row.location = location

    await session.flush()
    return row, diff


async def get_inventory_detail(
    session: AsyncSession, *, medical_store_id: int, code: str
) -> dict | None:
    """Single inventory row enriched for the mobile detail view.

    Returns a dict with the row plus joined fields, or None if no such row:
      - manufacturer  ← medicine_ndc_cache.brand_name (NDC-keyed)
      - dosage_form   ← medicine_ndc_cache.dosage_form  (Dose Form/Type)
      - lot_number    ← latest InvoiceLineItem for this store + NDC
    """
    res = await session.execute(
        select(MedicineInventory).where(
            MedicineInventory.medical_store_id == medical_store_id,
            MedicineInventory.code == code,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        return None

    # NDC cache is keyed by ndc11; a UPC-coded row simply won't match.
    cache = await session.get(MedicineNdcCache, code)

    lot_number = (
        await session.execute(
            select(InvoiceLineItem.lot_number)
            .join(Invoice, InvoiceLineItem.invoice_id == Invoice.id)
            .where(
                Invoice.medical_store_id == medical_store_id,
                InvoiceLineItem.ndc11 == code,
                InvoiceLineItem.lot_number.isnot(None),
            )
            .order_by(InvoiceLineItem.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return {
        "row": row,
        "manufacturer": cache.brand_name if cache else None,
        "dosage_form": cache.dosage_form if cache else None,
        "lot_number": lot_number,
    }


# Exported for the save routes that need to look up an existing invoice
# before recording inventory.
async def get_invoice_or_none(session: AsyncSession, *, invoice_id: int) -> Invoice | None:
    res = await session.execute(select(Invoice).where(Invoice.id == invoice_id))
    return res.scalar_one_or_none()
