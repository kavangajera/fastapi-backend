"""
services/refill_service.py
──────────────────────────
Derive the refill-due list from dispense history.

There is no "authorized refills" field in the source data, so "remaining" is
modeled as a **refill-due date**: for each patient + drug we take the latest
fill and compute `next_due = date_filled + days_supply`. The owner sees who is
overdue, due soon, or fine — i.e. who to call back.

Patients are keyed by the hashed, de-identified `patient_key`
(`services/validation/patient_key.py`) so we never group on raw PHI. Pairs the
owner has dismissed (`refill_dismissals`) are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Dispense, DrugReport, Medicine, RefillDismissal
from services.validation.patient_key import derive_patient_key

# date_filled / report dates arrive as free-form strings; try the common ones.
_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%d-%b-%Y", "%m/%d/%Y %H:%M")

_DUE_SOON_DAYS = 7


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class RefillEntry:
    patient_key: str
    customer_name: str | None
    phone: str | None
    drug_name: str
    ndc: str
    last_qty: str | None
    days_supply: int | None
    last_fill_date: str | None
    next_due: date | None
    days_remaining: int | None
    status: str  # OVERDUE | DUE_SOON | OK | UNKNOWN


def _status(next_due: date | None, today: date) -> tuple[str, int | None]:
    if next_due is None:
        return "UNKNOWN", None
    remaining = (next_due - today).days
    if remaining < 0:
        return "OVERDUE", remaining
    if remaining <= _DUE_SOON_DAYS:
        return "DUE_SOON", remaining
    return "OK", remaining


async def build_refill_list(
    db: AsyncSession,
    *,
    medical_store_id: int,
    today: date | None = None,
) -> list[RefillEntry]:
    """
    Latest fill per (patient_key, ndc) → refill-due entry, excluding dismissed
    patient/drug pairs. Sorted by urgency (most overdue first).
    """
    today = today or date.today()

    # Dismissals: "" drug_ndc means the whole patient is dismissed.
    dism_rows = (
        await db.execute(
            select(RefillDismissal.patient_key, RefillDismissal.drug_ndc).where(
                RefillDismissal.medical_store_id == medical_store_id
            )
        )
    ).all()
    dismissed_all: set[str] = set()
    dismissed_pairs: set[tuple[str, str]] = set()
    for pk, ndc in dism_rows:
        if ndc == "" or ndc is None:
            dismissed_all.add(pk)
        else:
            dismissed_pairs.add((pk, ndc))

    rows = (
        await db.execute(
            select(
                Dispense.pat_name,
                Dispense.pat_phone,
                Dispense.pat_addr,
                Dispense.qty_disp,
                Dispense.days_supply,
                Dispense.date_filled,
                Medicine.drug_name,
                Medicine.ndc,
            )
            .join(Medicine, Dispense.medicine_id == Medicine.id)
            .join(DrugReport, Medicine.report_id == DrugReport.id)
            .where(DrugReport.medical_store_id == medical_store_id)
        )
    ).all()

    # Keep the most recent fill per (patient_key, ndc).
    latest: dict[tuple[str, str], dict] = {}
    for pat_name, pat_phone, pat_addr, qty, days, date_filled, drug_name, ndc in rows:
        pk = derive_patient_key(pat_name, pat_phone, pat_addr)
        if pk in dismissed_all or (pk, ndc) in dismissed_pairs:
            continue
        key = (pk, ndc)
        filled = _parse_date(date_filled)
        existing = latest.get(key)
        # Prefer the row with the newest parseable fill date; fall back to any.
        if existing is not None:
            ex_filled = existing["_filled"]
            if ex_filled is not None and (filled is None or filled <= ex_filled):
                continue
        latest[key] = {
            "_filled": filled,
            "pat_name": pat_name,
            "pat_phone": pat_phone,
            "qty": qty,
            "days": days,
            "date_filled": date_filled,
            "drug_name": drug_name,
            "ndc": ndc,
            "patient_key": pk,
        }

    entries: list[RefillEntry] = []
    for data in latest.values():
        filled = data["_filled"]
        days = data["days"]
        next_due = None
        if filled is not None and days:
            next_due = filled + timedelta(days=int(days))
        status, remaining = _status(next_due, today)
        entries.append(
            RefillEntry(
                patient_key=data["patient_key"],
                customer_name=data["pat_name"],
                phone=data["pat_phone"],
                drug_name=data["drug_name"],
                ndc=data["ndc"],
                last_qty=str(data["qty"]) if data["qty"] is not None else None,
                days_supply=int(days) if days is not None else None,
                last_fill_date=data["date_filled"],
                next_due=next_due,
                days_remaining=remaining,
                status=status,
            )
        )

    # Most urgent first: smaller days_remaining first; UNKNOWN (None) last.
    entries.sort(key=lambda e: (e.days_remaining is None, e.days_remaining if e.days_remaining is not None else 0))
    return entries
