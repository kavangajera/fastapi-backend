"""
Pharmacy Purchase Report Extractor
====================================
Supports .xlsx and .xls files.

Column layout (0-indexed, inferred from report structure):
  Data row  (row A):
    col[0]  = drug_name
    col[1]  = ndc
    col[2]  = qty_ord          (Qty Ordered)
    col[3]  = pat_name
    col[4]  = days_supply
    col[5]  = date_filled      (datetime)
    col[6]  = ins_paid
    col[7]  = price
    col[8]  = pres_name
    col[9]  = rx_no
    col[10] = ref#

  Address row (row A+1):
    col[0]  = lot_no/exp_date  (if not just '\n')
    col[1]  = qty_disp         (Qty Dispensed)
    col[2]  = pat_addr
    col[3]  = pat_phone
    col[4]  = ins_code
    col[6]  = pres_addr
    col[7]  = pres_phone

  Blank row  (row A+2): all NaN — separator

  Total For row:
    col[0]  = 'Total For:'
    col[1]  = drug_name
    col[2]  = ndc
    col[3]  = qty_disp total
    col[5]  = total_packs
    col[7]  = total_ins_paid
    col[9]  = total_rx_count
    col[11] = qty_ord total
    col[13] = total_price
    col[14] = 'Total Cost:'   (value absent in sample — column right of it)

  Grand Total row:
    col[0]  = 'Grand Total:'
    col[2]  = grand_total_price
    col[4]  = grand_total_rx_count
    col[6]  = grand_total_cost

Usage:
    uv run extract_pharmacy_report.py sample_01_xls.xlsx
    uv run extract_pharmacy_report.py report.xls
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# Data classes (mirror SQLAlchemy models)
# ---------------------------------------------------------------------------

@dataclass
class DispenseRow:
    qty_disp: float | None = None
    qty_ord: float | None = None
    days_supply: int | None = None
    date_filled: str | None = None
    rx_no: str | None = None
    ref: str | None = None
    pat_name: str | None = None
    pat_addr: str | None = None
    pat_phone: str | None = None
    pres_name: str | None = None
    pres_addr: str | None = None
    pres_phone: str | None = None
    price: float | None = None
    ins_paid: float | None = None
    ins_code: str | None = None


@dataclass
class MedicineRow:
    drug_name: str = ""
    ndc: str = ""
    inventory_bucket: str | None = None
    lot_no_exp_date: str | None = None
    # Totals from "Total For:" block
    total_packs: float | None = None
    total_rx_count: int | None = None
    total_ins_paid: float | None = None
    total_price: float | None = None
    total_cost: float | None = None
    dispenses: list[DispenseRow] = field(default_factory=list)


@dataclass
class DrugReportRow:
    grand_total_rx_count: int | None = None
    grand_total_price: float | None = None
    grand_total_cost: float | None = None
    medicines: list[MedicineRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s if s else None


def _float(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _int(v: Any) -> int | None:
    f = _float(v)
    return int(f) if f is not None else None


def _date(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if hasattr(v, "strftime"):
        return v.strftime("%m/%d/%Y")
    return _str(v)


def _lot_no(raw: Any) -> str | None:
    """Parse lot_no field: may be '\\n', 'LOT\\n', 'LOT\\nEXP_DATE', or NaN."""
    s = _str(raw)
    if not s or s == "\n":
        return None
    return s.replace("\n", " / ").strip(" /")


def _is_blank_row(row: pd.Series) -> bool:
    return all(
        v is None or (isinstance(v, float) and pd.isna(v))
        for v in row
    )


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_report(path: str | Path) -> DrugReportRow:
    path = Path(path)
    engine = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"

    df = pd.read_excel(path, sheet_name=0, header=None, engine=engine)
    rows = df.values.tolist()
    n = len(rows)

    report = DrugReportRow()
    current_medicine: MedicineRow | None = None

    i = 1  # skip header row[0]
    while i < n:
        row = rows[i]
        col0 = _str(row[0])

        # ── Grand Total ──────────────────────────────────────────────────────
        if col0 == "Grand Total:":
            report.grand_total_price = _float(row[2])
            report.grand_total_rx_count = _int(row[4])
            report.grand_total_cost = _float(row[6])
            i += 1
            continue

        # ── Total For ────────────────────────────────────────────────────────
        if col0 == "Total For:":
            if current_medicine is not None:
                current_medicine.total_packs = _float(row[5])
                current_medicine.total_ins_paid = _float(row[7])
                current_medicine.total_rx_count = _int(row[9])
                current_medicine.total_price = _float(row[13])
                # total_cost value lives one column past col[14]; not always present
                # col[14] = 'Total Cost:' label; value would be col[15] if it exists
                if len(row) > 15:
                    current_medicine.total_cost = _float(row[15])
                report.medicines.append(current_medicine)
                current_medicine = None
            i += 1
            continue

        # ── Blank row ────────────────────────────────────────────────────────
        if _is_blank_row(row):
            i += 1
            continue

        # ── Data row (drug name / dispense header) ───────────────────────────
        # Identified by: col[0] = drug_name string (not 'Total For:' / 'Grand Total:')
        # col[1] = NDC (numeric string), col[3] = patient name, col[5] = date
        ndc_candidate = _str(row[1])
        pat_name = _str(row[3])
        date_val = _date(row[5])

        if (
            col0
            and col0 not in ("Total For:", "Grand Total:")
            and ndc_candidate
            and pat_name
        ):
            drug_name = col0
            ndc = ndc_candidate

            # If first dispense for this medicine, create the medicine record
            if current_medicine is None or current_medicine.ndc != ndc:
                # If there was an open medicine without a Total For (shouldn't happen
                # in well-formed data, but guard anyway)
                if current_medicine is not None and current_medicine.ndc != ndc:
                    report.medicines.append(current_medicine)
                current_medicine = MedicineRow(drug_name=drug_name, ndc=ndc)

            dispense = DispenseRow(
                qty_ord=_float(row[2]),
                pat_name=pat_name,
                days_supply=_int(row[4]),
                date_filled=date_val,
                ins_paid=_float(row[6]),
                price=_float(row[7]),
                pres_name=_str(row[8]),
                rx_no=_str(row[9]),
                ref=_str(row[10]),
            )

            # ── Address row immediately follows ──────────────────────────────
            if i + 1 < n:
                addr_row = rows[i + 1]
                lot_raw = addr_row[0]
                dispense.qty_disp = _float(addr_row[1])
                dispense.pat_addr = _str(addr_row[2])
                dispense.pat_phone = _str(addr_row[3])
                dispense.ins_code = _str(addr_row[4])
                dispense.pres_addr = _str(addr_row[6])
                dispense.pres_phone = _str(addr_row[7])

                lot = _lot_no(lot_raw)
                if lot and current_medicine.lot_no_exp_date is None:
                    current_medicine.lot_no_exp_date = lot

                i += 2  # consume data row + address row
            else:
                i += 1

            current_medicine.dispenses.append(dispense)
            continue

        # ── Anything else (unexpected row) ───────────────────────────────────
        i += 1

    # Flush last medicine if Total For was missing
    if current_medicine is not None:
        report.medicines.append(current_medicine)

    return report


# ---------------------------------------------------------------------------
# Public API — accepts raw bytes, returns the standard report dict
# ---------------------------------------------------------------------------

def _str_val(v: Any) -> str | None:
    """Convert a value to a string suitable for the standard dict, coercing None."""
    if v is None:
        return None
    return str(v)


def extract_report_from_excel(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """
    Entry-point called by ``document_extractor``.

    Accepts raw file bytes and the original filename (used to pick the pandas
    engine via the extension).  Returns the same dict shape as
    ``pdf_extractor.extract_report()``::

        {
          "pharmacy": { ... },
          "medicines": [ { ..., "totals": {...}, "dispenses": [...] } ],
          "grand_total": { ... }
        }
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "xlsx"
    suffix = f".{ext}"

    logger.info(
        "Excel extraction started: {filename} ({size} bytes)",
        filename=filename,
        size=len(file_bytes),
    )

    # Write to a temp file so pandas can read it (it needs a seekable file).
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, file_bytes)
        os.close(fd)

        report = parse_report(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # ── Convert DrugReportRow → standard dict ────────────────────────────
    medicines: list[dict[str, Any]] = []
    for med in report.medicines:
        dispenses: list[dict[str, Any]] = []
        for d in med.dispenses:
            dispenses.append({
                "qty_disp": _str_val(d.qty_disp),
                "qty_ord": _str_val(d.qty_ord),
                "days_supply": _str_val(d.days_supply),
                "date_filled": d.date_filled,
                "rx_no": d.rx_no,
                "ref": d.ref,
                "pat_name": d.pat_name,
                "pat_addr": d.pat_addr,
                "pat_phone": d.pat_phone,
                "pres_name": d.pres_name,
                "pres_addr": d.pres_addr,
                "pres_phone": d.pres_phone,
                "price": _str_val(d.price),
                "ins_paid": _str_val(d.ins_paid),
                "ins_code": d.ins_code,
            })

        medicines.append({
            "drug_name": med.drug_name,
            "ndc": med.ndc,
            "inventory_bucket": None,         # not available in Excel layout
            "lot_no_exp_date": med.lot_no_exp_date,
            "totals": {
                "packs": _str_val(med.total_packs),
                "total_ins_paid": _str_val(med.total_ins_paid),
                "total_price": _str_val(med.total_price),
                "total_cost": _str_val(med.total_cost),
                "total_rx_count": _str_val(med.total_rx_count),
            },
            "dispenses": dispenses,
        })

    total_dispenses = sum(len(m["dispenses"]) for m in medicines)
    logger.info(
        "Excel extraction finished (medicines={med_count}, dispenses={disp_count})",
        med_count=len(medicines),
        disp_count=total_dispenses,
    )

    return {
        "pharmacy": {
            "pharmacy_name": None,
            "address": None,
            "phone": None,
            "fax": None,
            "report_date": None,
            "report_from_date": None,
            "report_to_date": None,
        },
        "medicines": medicines,
        "grand_total": {
            "total_price": _str_val(report.grand_total_price),
            "total_rx_count": _str_val(report.grand_total_rx_count),
            "total_cost": _str_val(report.grand_total_cost),
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_pharmacy_report.py <report.xlsx|report.xls>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    report = parse_report(path)

    print(f"\n{'='*60}")
    print(f"Grand Total Price    : {report.grand_total_price}")
    print(f"Grand Total Rx Count : {report.grand_total_rx_count}")
    print(f"Grand Total Cost     : {report.grand_total_cost}")
    print(f"Total medicines      : {len(report.medicines)}")
    total_dispenses = sum(len(m.dispenses) for m in report.medicines)
    print(f"Total dispenses      : {total_dispenses}")
    print(f"{'='*60}\n")

    for m in report.medicines:
        print(f"  Drug : {m.drug_name}")
        print(f"  NDC  : {m.ndc}")
        if m.lot_no_exp_date:
            print(f"  Lot  : {m.lot_no_exp_date}")
        print(f"  Totals → packs={m.total_packs}, rx={m.total_rx_count}, "
              f"ins_paid={m.total_ins_paid}, price={m.total_price}, cost={m.total_cost}")
        for d in m.dispenses:
            print(f"    Rx#{d.rx_no} ref={d.ref} | {d.pat_name} | "
                  f"qty_disp={d.qty_disp} qty_ord={d.qty_ord} days={d.days_supply} "
                  f"filled={d.date_filled} | ins={d.ins_code} ins_paid={d.ins_paid} "
                  f"price={d.price} | {d.pres_name}")
        print()

    # Also dump full JSON
    out_json = path.with_suffix(".json")
    with open(out_json, "w") as f:
        json.dump(asdict(report), f, indent=2, default=str)
    print(f"Full JSON written to: {out_json}")


if __name__ == "__main__":
    main()