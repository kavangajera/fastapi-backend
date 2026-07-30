"""
services/doc_extractor.py
─────────────────────────
Extracts a structured Drug Dispensed Report from .doc (RTF) and .docx files
that share the same table layout as the PDF report.

Strategy
--------
* RTF (.doc)  – striprtf.rtf_to_text() produces one cell per line.
* DOCX (.docx) – python-docx iterates paragraphs + table cells, also one cell
  per line after normalisation.

Both formats are reduced to the same flat list[str] of non-empty cell values,
then a single sequential state-machine parser rebuilds the records.

Cell order per dispense row (from RTF analysis)
-----------------------------------------------
  pat_name | drug_name | NDC | qty_disp | days | date_filled |
  rxno | ref | pres_name | price | ins_paid |
  pat_addr | pres_addr | phone | ins_code | pres_phone | qty_ord

Totals block tokens (appear as individual lines)
------------------------------------------------
  'TotalRxCount:' | 'Packs:' | packs_val | cost_val | NDC | drug_name |
  rx_count | 'Total For:' | price_val |
  'Total Ins Paid:' | ins_val | 'Total Price:' | 'Total Cost:' | cost_val2

Grand total block
-----------------
  'Grand Total:' | 'TotalRxCount:' | total_price | total_ins_paid |
  'Total Price:' | 'Total Cost:' | rx_count

Output shape  (identical to pdf_extractor.extract_report)
----------------------------------------------------------
{
  "pharmacy": { pharmacy_name, address, phone, fax,
                report_date, report_from_date, report_to_date },
  "medicines": [
    { drug_name, ndc, inventory_bucket, lot_no_exp_date,
      totals: { packs, total_ins_paid, total_price, total_cost, total_rx_count },
      dispenses: [
        { qty_disp, qty_ord, days_supply, date_filled, rx_no, ref,
          pat_name, pat_addr, pat_phone,
          pres_name, pres_addr, pres_phone,
          price, ins_paid, ins_code }
      ]
    }
  ],
  "grand_total": { total_price, total_rx_count, total_cost }
}
"""

from __future__ import annotations

import io
import re
import time
from typing import Any

from loguru import logger

# ──────────────────────────── regex helpers ───────────────────────────────────

_NDC_RE = re.compile(r"^\d{11}$")
_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_MONEY_RE = re.compile(r"^\$\s*[\d,]+\.?\d*$")
_PHONE_RE = re.compile(r"^[\d]{10}$")
_QTY_RE = re.compile(r"^\d{1,4}\.\d{3}$")
_INT_RE = re.compile(r"^\d{1,4}$")
_STATE_ZIP_RE = re.compile(r"\b[A-Z]{2}\s+\d{5,9}\b")

_TOTALS_START = "TotalRxCount:"
_GRAND_TOTAL = "Grand Total:"
_TOTAL_FOR = "Total For:"
_PACKS_LABEL = "Packs:"
_TOTAL_INS = "Total Ins Paid:"
_TOTAL_PRICE = "Total Price:"
_TOTAL_COST = "Total Cost:"

# Known header / skip tokens that appear at the top of every page
_HEADER_TOKENS = {
    "Drug Name",
    "NDC",
    "Lot No/Exp Date",
    "Qty Disp",
    "Days",
    "Date Filled",
    "Pat Name",
    "Price",
    "RxNo",
    "Ref#",
    "Pres Name",
    "Pres Addr",
    "Pres Phone",
    "Pat Addr",
    "Pat Ph#",
    "Ins Paid",
    "Ins Code",
    "Qty Ord",
    "Inventory Bucket",
    "Page#:",
    "Date:",
    "Drug Dispensed Report",
}


# ───────────────────────────── money helpers ──────────────────────────────────


def _strip_money(s: str) -> str | None:
    cleaned = s.lstrip("$").replace(",", "").strip()
    return cleaned if cleaned else None


def _is_address(cell: str) -> bool:
    """Heuristic: cell contains a US state+zip pattern."""
    return bool(_STATE_ZIP_RE.search(cell))


# ──────────────────────────── pharmacy header ─────────────────────────────────

_PHONE_FAX_RE = re.compile(
    r"Phone#\s*(\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}).*?Fax#\s*(\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4})",
    re.IGNORECASE,
)
_DATE_RANGE_RE = re.compile(r"Drug Dispensed Report\s+([\d/]+)\s+To\s+([\d/]+)", re.IGNORECASE)


def _parse_pharmacy_header(cells: list[str]) -> dict[str, str]:
    hdr: dict[str, str] = {
        "pharmacy_name": "",
        "address": "",
        "phone": "",
        "fax": "",
        "report_date": "",
        "report_from_date": "",
        "report_to_date": "",
    }

    full = " ".join(cells[:30])  # header lives in the first ~30 cells

    if "Good Health Pharmacy" in full:
        hdr["pharmacy_name"] = "Good Health Pharmacy"

    addr_m = re.search(
        r"1379[\u2010\-]83 Nostrand Ave,?\s*Brooklyn,?\s*NY\s*11226", full, re.IGNORECASE
    )
    if addr_m:
        hdr["address"] = addr_m.group(0).strip()

    ph_m = _PHONE_FAX_RE.search(full)
    if ph_m:
        hdr["phone"] = ph_m.group(1).strip()
        hdr["fax"] = ph_m.group(2).strip()

    # Report date: first date-looking cell before "Page#:"
    for _i, c in enumerate(cells[:30]):
        if re.match(r"\d{1,2}/\d{1,2}/\d{4}", c):
            hdr["report_date"] = c.strip()
            break

    rng_m = _DATE_RANGE_RE.search(full)
    if rng_m:
        hdr["report_from_date"] = rng_m.group(1)
        hdr["report_to_date"] = rng_m.group(2)

    return hdr


# ──────────────────────── sequential dispense parser ─────────────────────────


class _DispenseRecord:
    """Mutable accumulator for one dispense row."""

    __slots__ = (
        "pat_name",
        "drug_name",
        "ndc",
        "qty_disp",
        "days_supply",
        "date_filled",
        "rx_no",
        "ref",
        "pres_name",
        "price",
        "ins_paid",
        "pat_addr",
        "pres_addr",
        "pat_phone",
        "pres_phone",
        "ins_code",
        "qty_ord",
        "_addr_count",
        "_phone_count",
    )

    def __init__(self) -> None:
        for s in self.__slots__:
            setattr(self, s, None)
        self._addr_count = 0
        self._phone_count = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "qty_disp": self.qty_disp,
            "qty_ord": self.qty_ord,
            "days_supply": int(self.days_supply) if self.days_supply is not None else None,
            "date_filled": self.date_filled,
            "rx_no": self.rx_no,
            "ref": self.ref,
            "pat_name": self.pat_name,
            "pat_addr": self.pat_addr,
            "pat_phone": self.pat_phone,
            "pres_name": self.pres_name,
            "pres_addr": self.pres_addr,
            "pres_phone": self.pres_phone,
            "price": _strip_money(self.price) if self.price else None,
            "ins_paid": _strip_money(self.ins_paid) if self.ins_paid else None,
            "ins_code": self.ins_code,
            "inventory_bucket": None,
            "lot_no_exp_date": None,
        }


# ──────────────────────── RTF cell-sequence state machine ────────────────────

# Dispense field slots filled in order after NDC is seen
_AFTER_NDC_SLOTS = ("qty_disp", "days_supply", "date_filled", "rx_no", "ref")

# Fields after ref: pres_name, price, ins_paid
# Then addresses and phones in lookahead


def _parse_cells(cells: list[str]) -> dict[str, Any]:
    """
    Core sequential parser.  Processes the flat cell list and returns the
    full report dict (pharmacy / medicines / grand_total).
    """
    pharmacy = _parse_pharmacy_header(cells)

    medicines_map: dict[tuple[str, str], dict[str, Any]] = {}  # (drug_name, NDC) → medicine dict
    medicines_order: list[tuple[str, str]] = []  # ordered keys

    grand_total: dict[str, str | None] = {
        "total_price": None,
        "total_rx_count": None,
        "total_cost": None,
    }

    i = 0
    n = len(cells)

    while i < n:
        cell = cells[i]

        # ── Grand Total block ────────────────────────────────────────────────
        if cell == _GRAND_TOTAL:
            # Expected: Grand Total: | TotalRxCount: | price | ins | Total Price: | Total Cost: | count
            j = i + 1
            if j < n and cells[j] == _TOTALS_START:
                j += 1
            # Collect money and integer tokens
            prices: list[str] = []
            rx_count: str | None = None
            while j < n and cells[j] not in (_TOTALS_START,):
                c2 = cells[j]
                if _MONEY_RE.match(c2):
                    prices.append(c2)
                elif c2 == _TOTAL_PRICE:
                    pass
                elif c2 == _TOTAL_COST:
                    pass
                elif _INT_RE.match(c2):
                    rx_count = c2
                j += 1
            if len(prices) == 1:
                grand_total["total_price"] = _strip_money(prices[0])
            elif len(prices) >= 2:
                # The first money value is total_cost, the second is total_price
                grand_total["total_cost"] = _strip_money(prices[0])
                grand_total["total_price"] = _strip_money(prices[1])
            if rx_count:
                grand_total["total_rx_count"] = rx_count
            i = j
            continue

        # ── Totals block ─────────────────────────────────────────────────────
        if cell == _TOTALS_START:
            # TotalRxCount: | Packs: | packs_val | cost_val | NDC | drug_name |
            # rx_count | Total For: | price_val | Total Ins Paid: | ins_val |
            # Total Price: | Total Cost: | cost_val2
            j = i + 1
            packs: str | None = None
            total_cost: str | None = None
            ndc: str | None = None
            rx_count_t: str | None = None
            total_price_t: str | None = None
            total_ins_t: str | None = None
            total_cost_t: str | None = None

            if j < n and cells[j] == _PACKS_LABEL:
                j += 1
            if j < n and _QTY_RE.match(cells[j]):
                packs = cells[j]
                j += 1
            if j < n and _QTY_RE.match(cells[j]):
                total_cost = cells[j]
                j += 1
            if j < n and _NDC_RE.match(cells[j]):
                ndc = cells[j]
                j += 1
            if (
                j < n
                and not _INT_RE.match(cells[j])
                and cells[j]
                not in (
                    _TOTAL_FOR,
                    _TOTAL_INS,
                    _TOTAL_PRICE,
                    _TOTAL_COST,
                    _TOTALS_START,
                    _GRAND_TOTAL,
                )
            ):
                # drug_name_t = cells[j]
                j += 1
            if j < n and _INT_RE.match(cells[j]):
                rx_count_t = cells[j]
                j += 1
            if j < n and cells[j] == _TOTAL_FOR:
                j += 1
            if j < n and _MONEY_RE.match(cells[j]):
                total_price_t = cells[j]
                j += 1
            if j < n and cells[j] == _TOTAL_INS:
                j += 1
            if j < n and _MONEY_RE.match(cells[j]):
                total_ins_t = cells[j]
                j += 1
            if j < n and cells[j] == _TOTAL_PRICE:
                j += 1
            if j < n and cells[j] == _TOTAL_COST:
                j += 1
            if j < n and (_QTY_RE.match(cells[j]) or _MONEY_RE.match(cells[j])):
                total_cost_t = cells[j]
                j += 1

            if ndc:
                for (_d_name, n_key), med in medicines_map.items():
                    if n_key == ndc:
                        t = med["totals"]
                        if t["total_rx_count"] is None:
                            if packs:
                                t["packs"] = packs
                            if rx_count_t:
                                t["total_rx_count"] = rx_count_t
                            if total_price_t:
                                t["total_price"] = _strip_money(total_price_t)
                            if total_ins_t:
                                t["total_ins_paid"] = _strip_money(total_ins_t)
                            if total_cost_t or total_cost:
                                t["total_cost"] = _strip_money(total_cost_t or total_cost)

            i = j
            continue

        # ── Skip known header tokens and page-break repeats ──────────────────
        if cell in _HEADER_TOKENS or re.match(r"\d{1,2}/\d{1,2}/\d{4}", cell) and i < 15:
            i += 1
            continue

        # ── Detect start of a new dispense record: NAME then DRUG then NDC ──
        # Pattern: next two non-empty cells are a drug name string and then NDC
        # We identify by: current cell is a name (has comma or mixed case),
        # next is drug name text, cell after that is 11-digit NDC.
        if (
            i + 2 < n
            and _NDC_RE.match(cells[i + 2])
            and not _NDC_RE.match(cell)
            and not _QTY_RE.match(cell)
            and not _MONEY_RE.match(cell)
            and not _DATE_RE.match(cell)
            and not _INT_RE.match(cell)
            and cell
            not in (
                _TOTALS_START,
                _GRAND_TOTAL,
                _TOTAL_FOR,
                _PACKS_LABEL,
                _TOTAL_INS,
                _TOTAL_PRICE,
                _TOTAL_COST,
            )
            and cell not in _HEADER_TOKENS
        ):
            rec = _DispenseRecord()
            rec.pat_name = cell
            rec.drug_name = cells[i + 1]
            rec.ndc = cells[i + 2]
            j = i + 3

            # qty_disp, days_supply, date_filled, rx_no, ref
            for slot in _AFTER_NDC_SLOTS:
                if j >= n:
                    break
                setattr(rec, slot, cells[j])
                j += 1

            # pres_name (next non-qty, non-money, non-date, non-int cell)
            if j < n and not _MONEY_RE.match(cells[j]):
                rec.pres_name = cells[j]
                j += 1

            # price
            if j < n and _MONEY_RE.match(cells[j]):
                rec.price = cells[j]
                j += 1

            # ins_paid
            if j < n and _MONEY_RE.match(cells[j]):
                rec.ins_paid = cells[j]
                j += 1

            # pat_addr (first address)
            if j < n and _is_address(cells[j]):
                rec.pat_addr = cells[j]
                j += 1

            # pres_addr (second address)
            if j < n and _is_address(cells[j]):
                rec.pres_addr = cells[j]
                j += 1

            # phone (10 digits = pat_phone)
            if j < n and _PHONE_RE.match(cells[j]):
                rec.pat_phone = cells[j]
                j += 1

            # ins_code — must be a short alphanumeric code (e.g. MCD, AD1, ADV);
            # never a long string or one containing spaces (those are addresses)
            if (
                j < n
                and not _QTY_RE.match(cells[j])
                and not _PHONE_RE.match(cells[j])
                and not _INT_RE.match(cells[j])
                and cells[j] not in (_TOTALS_START, _GRAND_TOTAL)
                and len(cells[j]) <= 15
                and " " not in cells[j]
            ):
                rec.ins_code = cells[j]
                j += 1

            # pres_phone (10 digits)
            if j < n and _PHONE_RE.match(cells[j]):
                rec.pres_phone = cells[j]
                j += 1

            # qty_ord
            if j < n and _QTY_RE.match(cells[j]):
                rec.qty_ord = cells[j]
                j += 1

            med_key = (rec.drug_name, rec.ndc)
            if med_key not in medicines_map:
                medicines_map[med_key] = {
                    "drug_name": rec.drug_name,
                    "ndc": rec.ndc,
                    "inventory_bucket": None,
                    "lot_no_exp_date": None,
                    "totals": {
                        "packs": None,
                        "total_ins_paid": None,
                        "total_price": None,
                        "total_cost": None,
                        "total_rx_count": None,
                    },
                    "dispenses": [],
                }
                medicines_order.append(med_key)

            medicines_map[med_key]["dispenses"].append(rec.to_dict())
            i = j
            continue

        i += 1

    medicines = [medicines_map[key] for key in medicines_order]
    return {
        "pharmacy": pharmacy,
        "medicines": medicines,
        "grand_total": grand_total,
    }


# ──────────────────────────── RTF text extraction ────────────────────────────


def _cells_from_rtf(file_bytes: bytes) -> list[str]:
    """
    Decode RTF bytes → flat list of non-empty cell strings.

    Performance note: striprtf processes the file character-by-character in
    Python.  For large reports (~900 KB RTF) this takes ~16s.  The bottleneck
    is the data volume, not the preamble, so pre-slicing does not help much.
    This is acceptable for an async background upload endpoint.
    """
    from striprtf.striprtf import rtf_to_text

    text = rtf_to_text(file_bytes.decode("latin-1", errors="replace"))

    # Normalise typographic characters that RTF commonly uses:
    #   U+2011 NON-BREAKING HYPHEN → regular hyphen
    #   U+00A0 NON-BREAKING SPACE  → regular space
    #   U+2010 HYPHEN              → regular hyphen
    text = text.replace("\u2011", "-").replace("\u2010", "-").replace("\u00a0", " ")

    return [line.strip() for line in text.splitlines() if line.strip()]


# ──────────────────────────── DOCX text extraction ───────────────────────────


def _cells_from_docx(file_bytes: bytes) -> list[str]:
    """Parse DOCX bytes → flat list of non-empty cell strings."""
    import docx2python

    doc_result = docx2python.docx2python(io.BytesIO(file_bytes))
    cells: list[str] = []

    def clean_and_split(text: str) -> list[str]:
        if not text.strip():
            return []
        # Isolate NDC from merged strings
        text = re.sub(r"\b(\d{11})\b", r"\n\1\n", text)
        # Fix merged strings where qty_disp and pat_name are space-separated
        text = re.sub(r"(\d{1,4}\.\d{3})\s+([A-Za-z])", r"\1\n\2", text)
        # Fix merged pat_name and days_supply e.g. "CHEN, JINGQIANG 30"
        text = re.sub(r"([A-Za-z\'\,])\s+(\d{1,3})$", r"\1\n\2", text)
        # Fix "Total For:ALBUTEROL"
        text = re.sub(r"(Total For:)\s*([A-Za-z])", r"\1\n\2", text)
        # Fix merged Packs and qty e.g. "180.000 Packs:"
        text = re.sub(r"(\d{1,4}\.\d{3})\s+(Packs:)", r"\1\n\2", text)

        tokens = []
        for token in re.split(r"\t|\n|\s{2,}", text):
            token = token.strip()
            if token:
                tokens.append(token)
        return tokens

    # docx2python returns a list of tables. Each table is a list of rows.
    # Each row is a list of cells. Each cell is a list of paragraphs.
    # Extract headers first (pharmacy name, dates)
    for table in doc_result.header:
        for row in table:
            for cell in row:
                for para in cell:
                    cells.extend(clean_and_split(para))

    for table in doc_result.body:
        for row in table:
            for cell in row:
                for para in cell:
                    cells.extend(clean_and_split(para))

    return cells


def _parse_docx_cells(cells: list[str]) -> dict[str, Any]:
    """
    Core sequential parser tailored for .docx floating table token streams.
    The .docx export usually drops addresses and re-orders fields left-to-right.
    """
    pharmacy = _parse_pharmacy_header(cells)
    medicines_map: dict[tuple[str, str], dict[str, Any]] = {}
    medicines_order: list[tuple[str, str]] = []

    grand_total: dict[str, str | None] = {
        "total_price": None,
        "total_rx_count": None,
        "total_cost": None,
    }

    _RX_RE = re.compile(r"^\d{5,8}$")

    i = 0
    n = len(cells)

    while i < n:
        cell = cells[i]

        # ── Grand Total block ────────────────────────────────────────────────
        if cell == _GRAND_TOTAL:
            j = i + 1
            while j < n:
                c2 = cells[j]
                if c2 == _TOTAL_PRICE:
                    if j + 1 < n and _MONEY_RE.match(cells[j + 1]):
                        grand_total["total_price"] = _strip_money(cells[j + 1])
                        j += 1
                elif c2 == _TOTAL_COST:
                    if j + 1 < n and _MONEY_RE.match(cells[j + 1]):
                        grand_total["total_cost"] = _strip_money(cells[j + 1])
                        j += 1
                elif c2.startswith(_TOTALS_START):
                    parts = c2.split()
                    if len(parts) > 1:
                        grand_total["total_rx_count"] = parts[1]
                    elif j + 1 < n and _INT_RE.match(cells[j + 1]):
                        grand_total["total_rx_count"] = cells[j + 1]
                        j += 1
                j += 1
                if (
                    grand_total["total_price"]
                    and grand_total["total_cost"]
                    and grand_total["total_rx_count"]
                ):
                    break
            i = j
            continue

        # ── Totals block ─────────────────────────────────────────────────────
        if cell == _TOTALS_START:
            # We skip detailed totals parsing for .docx for now to avoid false positives,
            # as the dispense parser below is purely regex anchored on NDC.
            # We just advance past the "TotalRxCount:" marker.
            pass

        # ── Detect start of a new dispense record (NDC anchored) ─────────────
        if _NDC_RE.match(cell):
            is_dispense = False
            # Check lookahead for date_filled to confirm it's a dispense and not a totals block
            for k in range(i, min(n, i + 15)):
                c2 = cells[k]
                if (
                    c2 == _TOTALS_START
                    or c2.startswith(_TOTALS_START)
                    or c2 in (_PACKS_LABEL, "Total Price: Total Cost:", _TOTAL_COST)
                ):
                    break
                if _DATE_RE.match(c2):
                    is_dispense = True
                    break

            if is_dispense:
                # Extrapolate backwards for drug name and bucket
                drug_name = (
                    cells[i - 2]
                    if i > 1 and cells[i - 1] in ("General", "Bucket", "C", "S")
                    else cells[i - 1]
                )
                ndc = cell

                j = i + 1
                qty_disp = cells[j] if j < n and _QTY_RE.match(cells[j]) else None
                if qty_disp:
                    j += 1

                pat_name_parts = []
                while (
                    j < n
                    and not _QTY_RE.match(cells[j])
                    and not _INT_RE.match(cells[j])
                    and not _DATE_RE.match(cells[j])
                ):
                    pat_name_parts.append(cells[j])
                    j += 1
                pat_name = " ".join(pat_name_parts).strip(", ")

                qty_ord = cells[j] if j < n and _QTY_RE.match(cells[j]) else None
                if qty_ord:
                    j += 1

                days_supply = cells[j] if j < n and _INT_RE.match(cells[j]) else None
                if days_supply:
                    j += 1

                date_filled = cells[j] if j < n and _DATE_RE.match(cells[j]) else None
                if date_filled:
                    j += 1

                ins_code = (
                    cells[j]
                    if j < n and not _MONEY_RE.match(cells[j]) and not _RX_RE.match(cells[j])
                    else None
                )
                if ins_code:
                    j += 1

                ins_paid = cells[j] if j < n and _MONEY_RE.match(cells[j]) else None
                if ins_paid:
                    j += 1

                rx_no = cells[j] if j < n and _RX_RE.match(cells[j]) else None
                if rx_no:
                    j += 1

                ref = cells[j] if j < n and _INT_RE.match(cells[j]) else None
                if ref:
                    j += 1

                med_key = (drug_name, ndc)
                if med_key not in medicines_map:
                    medicines_map[med_key] = {
                        "drug_name": drug_name,
                        "ndc": ndc,
                        "inventory_bucket": None,
                        "lot_no_exp_date": None,
                        "totals": {
                            "packs": None,
                            "total_ins_paid": None,
                            "total_price": None,
                            "total_cost": None,
                            "total_rx_count": None,
                        },
                        "dispenses": [],
                    }
                    medicines_order.append(med_key)

                medicines_map[med_key]["dispenses"].append(
                    {
                        "qty_disp": qty_disp,
                        "qty_ord": qty_ord,
                        "days_supply": int(days_supply) if days_supply else None,
                        "date_filled": date_filled,
                        "rx_no": rx_no,
                        "ref": ref,
                        "pat_name": pat_name,
                        "pat_addr": None,
                        "pat_phone": None,
                        "pres_name": None,
                        "pres_addr": None,
                        "pres_phone": None,
                        "price": None,
                        "ins_paid": _strip_money(ins_paid) if ins_paid else None,
                        "ins_code": ins_code,
                        "inventory_bucket": None,
                        "lot_no_exp_date": None,
                    }
                )
                i = j - 1
            else:
                # It's a Totals block for the NDC
                ndc_t = cell
                j = i + 1
                packs = None
                total_cost = None
                total_price_t = None
                total_ins_t = None
                rx_count_t = None
                while j < n and j < i + 15:
                    c2 = cells[j]
                    if c2 == "Packs:" and j + 1 < n and _QTY_RE.match(cells[j + 1]):
                        packs = cells[j + 1]
                    elif c2.startswith("TotalRxCount:"):
                        parts = c2.split()
                        if len(parts) > 1:
                            rx_count_t = parts[1]
                        # TotalRxCount is the end of the totals block
                        break
                    elif _MONEY_RE.match(c2):
                        if not total_cost:
                            total_cost = c2
                        elif not total_price_t:
                            total_price_t = c2
                        else:
                            total_ins_t = c2
                    j += 1

                for (_d_name, n_key), med in medicines_map.items():
                    if n_key == ndc_t:
                        t = med["totals"]
                        if t["total_rx_count"] is None:
                            if packs:
                                t["packs"] = packs
                            if rx_count_t:
                                t["total_rx_count"] = rx_count_t
                            if total_price_t:
                                t["total_price"] = _strip_money(total_price_t)
                            if total_ins_t:
                                t["total_ins_paid"] = _strip_money(total_ins_t)
                            if total_cost:
                                t["total_cost"] = _strip_money(total_cost)

                i = j
        i += 1

    medicines = [medicines_map[key] for key in medicines_order]
    return {
        "pharmacy": pharmacy,
        "medicines": medicines,
        "grand_total": grand_total,
    }


# ──────────────────────────── public API ─────────────────────────────────────


def extract_report_from_doc(file_bytes: bytes) -> dict[str, Any]:
    """
    Extract a Drug Dispensed Report from a .doc file.
    Supports genuine RTF-based .doc files (the most common export format
    from pharmacy management systems).
    """
    start = time.perf_counter()
    logger.info("DOC (RTF) extraction started")

    cells = _cells_from_rtf(file_bytes)
    result = _parse_cells(cells)

    elapsed_ms = (time.perf_counter() - start) * 1000
    total_dispenses = sum(len(m["dispenses"]) for m in result["medicines"])
    logger.info(
        "DOC extraction finished in {elapsed_ms:.1f} ms "
        "(cells={cell_count}, medicines={med_count}, dispenses={disp_count})",
        elapsed_ms=elapsed_ms,
        cell_count=len(cells),
        med_count=len(result["medicines"]),
        disp_count=total_dispenses,
    )
    return result


def extract_report_from_docx(file_bytes: bytes) -> dict[str, Any]:
    """
    Extract a Drug Dispensed Report from a .docx file.
    """
    start = time.perf_counter()
    logger.info("DOCX extraction started")

    cells = _cells_from_docx(file_bytes)
    result = _parse_docx_cells(cells)

    elapsed_ms = (time.perf_counter() - start) * 1000
    total_dispenses = sum(len(m["dispenses"]) for m in result["medicines"])
    logger.info(
        "DOCX extraction finished in {elapsed_ms:.1f} ms "
        "(cells={cell_count}, medicines={med_count}, dispenses={disp_count})",
        elapsed_ms=elapsed_ms,
        cell_count=len(cells),
        med_count=len(result["medicines"]),
        disp_count=total_dispenses,
    )
    return result
