"""
services/pdf_extractor.py
─────────────────────────
Extracts a structured Drug Dispensed Report from a text-based PDF.

Strategy
--------
* Uses PyMuPDF (fitz) in "blocks" mode – each text block becomes one line.
  In this PDF the renderer places BOTH patient and prescriber addresses in
  a single block when they fit on the same visual row, so _split_addr_line()
  handles that case.
* Totals blocks use the pattern "N Total For:" (count precedes the label).
* Returns a plain dict ready for DB insertion.

Output shape
------------
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

import re
import time
from typing import Any

import fitz  # PyMuPDF
from loguru import logger

# ────────────────────────────── regex constants ───────────────────────────────

_NDC_RE = re.compile(r"\b(\d{11})\b")
_DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")
_MONEY_RE = re.compile(r"\$\s*[\d,]+\.?\d*")
_PHONE_RE = re.compile(r"\(?\d{3}\)?[ \-]?\d{3}[ \-]?\d{4}")
_PAT_NAME_RE = re.compile(r"([A-Z][A-Za-z'\-]+,\s*[A-Za-z'\-]+)")
_STATE_ZIP_RE = re.compile(r"\b([A-Z]{2})\s+(\d{5}(?:\-\d{4})?)\b")
_ADDR_KW_RE = re.compile(
    r"\b(AVE|BLVD|ST|RD|LN|DR|APT|FL|FLOOR|WAY|COURT|CT|PLACE|PL)\b", re.IGNORECASE
)

# "right-of-NDC" portion: qty  days  MM/DD/YYYY  rxno  ref  ...rest
_RIGHT_RE = re.compile(
    r"^\s*(?P<qty>\d{1,4}\.\d{3})\s+"
    r"(?:(?P<pat_name>[A-Z][A-Za-z'\-]+,\s*[A-Za-z'\-]+)\s+)?"
    r"(?P<days>\d{1,3})\s+"
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<rxno>\d{5,6})\s+"
    r"(?P<ref>\d{1,2})\s+"
    r"(?P<rest>.+?)\s*$"
)

_INS_CODE_RE = re.compile(
    r"\b(MCD|AD[12]|ADV|ANTHE\w*|MMS\d+|ES3|AC1|AE1|EXP\d+|EMPIRE\w*|PAI|AETMCR|C)\b",
    re.IGNORECASE,
)

_SKIP_PREFIXES = (
    "----- Page",
    "Drug Dispensed Report",
    "Drug Name NDC",
    "Pres Addr",
    "Ins Code",
    "TotalRxCount:",
    "Grand Total",
    "Total For:",
    "Total Ins Paid",
    "Total Price",
    "Total Cost",
)


# ─────────────────────────────── helpers ──────────────────────────────────────


def _parse_money(s: str | None) -> str | None:
    if not s:
        return None
    cleaned = s.strip().lstrip("$").replace(",", "").strip()
    return cleaned if cleaned else None


def _safe_int(s: Any) -> int | None:
    if s is None:
        return None
    try:
        return int(str(s).strip())
    except (ValueError, TypeError):
        return None


def _is_detail_row(ln: str) -> bool:
    return bool(_NDC_RE.search(ln)) and bool(_DATE_RE.search(ln)) and bool(_MONEY_RE.search(ln))


def _is_totals_boundary(ln: str) -> bool:
    return any(ln.startswith(p) for p in ("TotalRxCount:", "Total For:", "Grand Total"))


def _split_addr_line(ln: str) -> tuple[str, str]:
    """
    Split a combined pat+pres address line at the end of the first state+zip.
    Returns (pat_addr, pres_addr). If only one address, pres_addr is "".
    """
    matches = list(_STATE_ZIP_RE.finditer(ln))
    if len(matches) >= 2:
        split_pos = matches[0].end()
        return ln[:split_pos].strip(), ln[split_pos:].strip()
    return ln.strip(), ""


def _is_header_line(ln: str) -> bool:
    """True if line is part of the recurring page header or table header."""
    header_patterns = [
        r"Good Health Pharmacy",
        r"1379-83 Nostrand Ave",
        r"Brooklyn, NY 11226",
        r"Phone# \(718\)618-7425",
        r"Fax# \(718\)618-7428",
        r"Drug Dispensed Report",
        r"Page#:",
        r"Date:",
        r"Drug Name\s+NDC",
        r"Inventory Bucket\s+Lot No/Exp Date",
    ]
    return any(re.search(p, ln, re.IGNORECASE) for p in header_patterns)


# ──────────────────────────── PDF text extraction ────────────────────────────


def _extract_lines(pdf_bytes: bytes) -> list[str]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    lines: list[str] = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        for block in page.get_text("blocks"):  # type: ignore[arg-type]
            if block[6] == 0:
                raw = block[4].replace("\n", " ").strip()
                if raw:
                    lines.append(raw)
    doc.close()
    return lines


# ──────────────────────────── pharmacy header ─────────────────────────────────


def _parse_pharmacy_header(full_text: str) -> dict[str, str]:
    hdr: dict[str, str] = {
        "pharmacy_name": "",
        "address": "",
        "phone": "",
        "fax": "",
        "report_date": "",
        "report_from_date": "",
        "report_to_date": "",
    }

    if "Good Health Pharmacy" in full_text:
        hdr["pharmacy_name"] = "Good Health Pharmacy"

    addr_m = re.search(
        r"1379-83 Nostrand Ave,?\s*Brooklyn,?\s*NY\s*11226", full_text, re.IGNORECASE
    )
    if addr_m:
        hdr["address"] = addr_m.group(0).strip()

    ph_fax_m = re.search(
        r"Phone#\s*(\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}).*?Fax#\s*(\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4})",
        full_text,
        re.IGNORECASE,
    )
    if ph_fax_m:
        hdr["phone"] = ph_fax_m.group(1).strip()
        hdr["fax"] = ph_fax_m.group(2).strip()

    # Blocks mode: "2/1/2026 1 Page#: Date: Good Health Pharmacy …"
    date_m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+\d+\s+Page#:", full_text)
    if date_m:
        hdr["report_date"] = date_m.group(1)

    range_m = re.search(
        r"Drug Dispensed Report\s+([\d/]+)\s+To\s+([\d/]+)", full_text, re.IGNORECASE
    )
    if range_m:
        hdr["report_from_date"] = range_m.group(1)
        hdr["report_to_date"] = range_m.group(2)

    return hdr


# ──────────────────────────── detail row parser ───────────────────────────────


def _parse_detail_row(ln: str) -> dict[str, Any]:
    disp: dict[str, Any] = {
        "qty_disp": None,
        "qty_ord": None,
        "days_supply": None,
        "date_filled": None,
        "rx_no": None,
        "ref": None,
        "pat_name": None,
        "pat_addr": None,
        "pat_phone": None,
        "pres_name": None,
        "pres_addr": None,
        "pres_phone": None,
        "price": None,
        "ins_paid": None,
        "ins_code": None,
        "inventory_bucket": None,
        "lot_no_exp_date": None,
    }

    ndc_m = _NDC_RE.search(ln)
    if not ndc_m:
        return disp

    left = ln[: ndc_m.start()].strip()
    right = ln[ndc_m.end() :].strip()

    pats = list(_PAT_NAME_RE.finditer(left))
    if pats:
        disp["pat_name"] = re.sub(r"\s{2,}", " ", pats[-1].group(1)).strip()

    rr = _RIGHT_RE.match(right)
    if rr:
        disp["qty_disp"] = rr.group("qty")
        disp["days_supply"] = _safe_int(rr.group("days"))
        disp["date_filled"] = rr.group("date")
        disp["rx_no"] = rr.group("rxno")
        disp["ref"] = rr.group("ref")
        if rr.group("pat_name"):
            disp["pat_name"] = re.sub(r"\s{2,}", " ", rr.group("pat_name")).strip()
        rest = rr.group("rest")
    else:
        rest = right

    monies = _MONEY_RE.findall(rest)
    if monies:
        disp["price"] = _parse_money(monies[0])
        disp["ins_paid"] = _parse_money(monies[-1])
        pres_raw = rest.split(monies[0])[0].strip()
        disp["pres_name"] = re.sub(r"\s{2,}", " ", pres_raw).strip() or None

    return disp


# ──────────────────────────── look-ahead enrichment ──────────────────────────


def _enrich_lookahead(lines: list[str], start_idx: int, disp: dict[str, Any]) -> None:
    """Fill pat_addr, pres_addr, phones, ins_code, qty_ord from lines after detail row."""
    addr_parts: list[str] = []
    pat_phone = pres_phone = ins_code = qty_ord = ""
    inventory_bucket = ""
    lot_no_exp_date = ""

    for j in range(start_idx + 1, min(start_idx + 20, len(lines))):
        l2 = lines[j]

        if _is_detail_row(l2) or _is_totals_boundary(l2):
            break

        phones = _PHONE_RE.findall(l2)
        code_m = _INS_CODE_RE.search(l2)
        qtys = re.findall(r"\b\d{1,4}\.\d{3}\b", l2)

        if phones or code_m or qtys:
            if phones:
                pat_phone = phones[0]
                if len(phones) > 1:
                    pres_phone = phones[1]
            if code_m:
                ins_code = code_m.group(1).upper()
            if qtys:
                qty_ord = qtys[-1]
                qty_pos = l2.rfind(qty_ord)
                if qty_pos != -1:
                    post_qty = l2[qty_pos + len(qty_ord) :].strip()
                    post_tokens = post_qty.split() if post_qty else []
                    bucket_token = ""
                    for token in reversed(post_tokens):
                        if re.fullmatch(r"[A-Za-z][A-Za-z-]*", token):
                            bucket_token = token
                            break
                    if bucket_token and bucket_token.lower() == "general":
                        inventory_bucket = bucket_token
                        bucket_idx = post_tokens.index(bucket_token)
                        lot_tokens = [
                            t
                            for t in post_tokens[:bucket_idx]
                            if re.search(r"[\d/\-]", t) or (len(t) >= 3 and not t.isalpha())
                        ]
                        if lot_tokens:
                            lot_no_exp_date = " ".join(lot_tokens)
                    else:
                        lot_tokens = [
                            t
                            for t in post_tokens
                            if re.search(r"[\d/\-]", t) or (len(t) >= 3 and not t.isalpha())
                        ]
                        if lot_tokens:
                            lot_no_exp_date = " ".join(lot_tokens)
            if not inventory_bucket:
                tokens = l2.strip().split()
                for token in reversed(tokens):
                    if re.fullmatch(r"[A-Za-z][A-Za-z-]*", token) and token.lower() == "general":
                        inventory_bucket = token
                        break
            if qtys or inventory_bucket or lot_no_exp_date:
                break

        # Address line — may contain one or two addresses
        sz_count = len(list(_STATE_ZIP_RE.finditer(l2)))
        if sz_count >= 2:
            pat_a, pres_a = _split_addr_line(l2)
            addr_parts.extend([pat_a, pres_a])
        else:
            addr_parts.append(l2.strip())

    if len(addr_parts) >= 1:
        disp["pat_addr"] = addr_parts[0]
    if len(addr_parts) >= 2:
        disp["pres_addr"] = addr_parts[1]
    if pat_phone:
        disp["pat_phone"] = pat_phone
    if pres_phone:
        disp["pres_phone"] = pres_phone
    if ins_code:
        disp["ins_code"] = ins_code
    if qty_ord:
        disp["qty_ord"] = qty_ord
    if inventory_bucket and not disp.get("inventory_bucket"):
        disp["inventory_bucket"] = inventory_bucket
    if lot_no_exp_date and not disp.get("lot_no_exp_date"):
        disp["lot_no_exp_date"] = lot_no_exp_date


# ──────────────────────────── totals block parser ─────────────────────────────


def _parse_totals_blocks(lines: list[str]) -> dict[str, dict[str, str | None]]:
    """
    Blocks mode totals structure:
      "TotalRxCount: Packs: 1.000 75.000 76204020025 DRUG NAME"
      "1 Total For:"        ← rx_count BEFORE the label
      "$14.59"              ← stand-alone money = total price
      "Total Ins Paid: $14.59"
      "Total Price:"        ← empty; value already captured
      "Total Cost:  75.000"
    """
    totals: dict[str, dict[str, str | None]] = {}

    for idx, ln in enumerate(lines):
        if "TotalRxCount:" not in ln or "Packs:" not in ln:
            continue
        ndc_m = _NDC_RE.search(ln)
        if not ndc_m:
            continue
        ndc = ndc_m.group(1)
        if ndc in totals:
            continue

        rec: dict[str, str | None] = {
            "packs": None,
            "total_ins_paid": None,
            "total_price": None,
            "total_cost": None,
            "total_rx_count": None,
        }

        packs_m = re.search(r"Packs:\s*([\d.]+)", ln)
        if packs_m:
            rec["packs"] = packs_m.group(1)
        if "Total For:" in ln:
            rx_inline = re.search(r"\b(\d+)\s+Total\s+For:", ln)
            if rx_inline:
                rec["total_rx_count"] = rx_inline.group(1)

        prev_standalone_money = ""

        for k in range(idx + 1, min(idx + 15, len(lines))):
            l2 = lines[k]

            if "TotalRxCount:" in l2 and "Packs:" in l2 and l2 is not ln:
                break

            if "Total For:" in l2:
                # "N Total For:"  (blocks mode puts count before label)
                rx_before = re.search(r"\b(\d+)\s+Total\s+For:", l2)
                if rx_before:
                    rec["total_rx_count"] = rx_before.group(1)
                else:
                    rx_after = re.search(r"Total\s+For:\s*(\d+)", l2)
                    if rx_after:
                        rec["total_rx_count"] = rx_after.group(1)
                m_here = _MONEY_RE.findall(l2)
                if m_here and rec["total_price"] is None:
                    rec["total_price"] = _parse_money(m_here[0])

            elif "Total Ins Paid" in l2:
                m2 = re.search(r"Total\s+Ins\s+Paid:\s*(\$\s*[\d,]+\.?\d*)", l2, re.IGNORECASE)
                if m2:
                    rec["total_ins_paid"] = _parse_money(m2.group(1))

            elif "Total Price" in l2:
                m2 = re.search(r"Total\s+Price:\s*(\$\s*[\d,]+\.?\d*)", l2, re.IGNORECASE)
                if m2:
                    rec["total_price"] = _parse_money(m2.group(1))
                elif prev_standalone_money and rec["total_price"] is None:
                    rec["total_price"] = _parse_money(prev_standalone_money)

            elif "Total Cost" in l2:
                m2 = re.search(r"Total\s+Cost:\s*(\$?[\d,\.]+)", l2, re.IGNORECASE)
                if m2:
                    rec["total_cost"] = _parse_money(m2.group(1))

            else:
                stripped = l2.strip()
                if re.match(r"^\$\s*[\d,]+\.?\d*$", stripped):
                    prev_standalone_money = stripped

        totals[ndc] = rec

    return totals


# ──────────────────────────── grand total ────────────────────────────────────


def _parse_grand_total(lines: list[str]) -> dict[str, str | None]:
    gt: dict[str, str | None] = {
        "total_price": None,
        "total_rx_count": None,
        "total_cost": None,
    }

    gt_start: int | None = None
    for i, ln in enumerate(lines):
        if ln.startswith("Grand Total"):
            gt_start = i
            break
    if gt_start is None:
        return gt

    tail_lines = lines[gt_start : gt_start + 15]
    tail = " ".join(tail_lines)

    rx_m = re.search(r"TotalRxCount:\s*(\d+)", tail)
    if rx_m:
        gt["total_rx_count"] = rx_m.group(1)
    else:
        nums = re.findall(r"\b(\d{2,4})\b", tail)
        if nums:
            gt["total_rx_count"] = nums[-1]

    money_lines: list[tuple[str, str]] = []
    for l2 in tail_lines:
        m2 = _MONEY_RE.search(l2)
        if m2:
            money_lines.append((l2, m2.group(0)))

    for l2, m2 in money_lines:
        if "Total Price" in l2:
            gt["total_price"] = _parse_money(m2)
            break

    if gt["total_price"] is None and money_lines:
        gt["total_price"] = _parse_money(money_lines[-1][1])

    for l2, m2 in money_lines:
        parsed = _parse_money(m2)
        if parsed != gt["total_price"]:
            gt["total_cost"] = parsed
            break

    return gt


# ──────────────────────────── public API ─────────────────────────────────────


def extract_report(pdf_bytes: bytes) -> dict[str, Any]:
    """
    Main entry point.  Accepts raw PDF bytes, returns structured report dict.
    """
    start_time = time.perf_counter()
    logger.info("PDF extraction started")
    lines = _extract_lines(pdf_bytes)
    full_text = "\n".join(lines)
    pharmacy = _parse_pharmacy_header(full_text)

    # Filter out header noise to handle page breaks cleanly
    lines = [ln for ln in lines if not _is_header_line(ln)]

    # Collect detail rows
    detail_rows: list[tuple[int, str, str, str | None, str | None]] = []
    for i, ln in enumerate(lines):
        if any(ln.startswith(p) for p in _SKIP_PREFIXES):
            continue
        # We already filtered headers, but double check pharmacy/page lines just in case
        if "Good Health Pharmacy" in ln and "Page#:" in ln:
            continue
        if not _is_detail_row(ln):
            continue
        ndc_m = _NDC_RE.search(ln)
        if not ndc_m:
            continue
        ndc = ndc_m.group(1)

        # Initial drug name from this line
        left = ln[: ndc_m.start()].strip()
        pats = list(_PAT_NAME_RE.finditer(left))
        drug_part = left[pats[-1].end() :].strip() if pats else left
        drug_name = re.sub(r"\s{2,}", " ", drug_part).strip()

        # Some PDFs put "Pat Name + Drug Name" on the previous line
        pat_name_override: str | None = None
        bucket_override: str | None = None
        prev_line = lines[i - 1] if i > 0 else ""
        prev_pat = _PAT_NAME_RE.search(prev_line)
        if prev_pat:
            pat_name_override = re.sub(r"\s{2,}", " ", prev_pat.group(1)).strip()
            if not drug_name:
                prev_drug = prev_line[prev_pat.end() :].strip()
                if prev_drug:
                    drug_name = re.sub(r"\s{2,}", " ", prev_drug).strip()

        # Inventory bucket is typically on a short line below the drug name
        for j in range(i + 1, min(i + 6, len(lines))):
            l2 = lines[j]
            if _is_detail_row(l2) or _is_totals_boundary(l2):
                break
            if (
                _DATE_RE.search(l2)
                or _MONEY_RE.search(l2)
                or _NDC_RE.search(l2)
                or _PHONE_RE.search(l2)
                or _INS_CODE_RE.search(l2)
                or "," in l2
            ):
                continue
            if re.fullmatch(r"[A-Za-z][A-Za-z -]{0,40}", l2.strip()):
                candidate = l2.strip()
                if candidate.lower() == "general":
                    bucket_override = candidate
                break

        # Look ahead for multi-line drug name continuation
        for j in range(i + 1, min(i + 5, len(lines))):
            l2 = lines[j]
            if _is_detail_row(l2) or _is_totals_boundary(l2):
                break
            # If it has specific data like date, money, NDC or phone, it's not a name continuation
            if (
                _DATE_RE.search(l2)
                or _MONEY_RE.search(l2)
                or _NDC_RE.search(l2)
                or _PHONE_RE.search(l2)
            ):
                break
            # Do not append lines that contain address markers
            if _STATE_ZIP_RE.search(l2) or _ADDR_KW_RE.search(l2):
                break
            drug_name += " " + l2.strip()

        drug_name = re.sub(r"\s{2,}", " ", drug_name).strip()
        detail_rows.append((i, drug_name, ndc, pat_name_override, bucket_override))

    # Build dispenses
    dispenses_by_key: dict[tuple[str, str], list[dict]] = {}
    for line_idx, drug_name, ndc, pat_name_override, bucket_override in detail_rows:
        disp = _parse_detail_row(lines[line_idx])
        if not disp.get("pat_name") and pat_name_override:
            disp["pat_name"] = pat_name_override
        if bucket_override and not disp.get("inventory_bucket"):
            disp["inventory_bucket"] = bucket_override
        _enrich_lookahead(lines, line_idx, disp)
        dispenses_by_key.setdefault((drug_name, ndc), []).append(disp)

    totals_by_ndc = _parse_totals_blocks(lines)

    # Assemble medicines in order of first appearance
    seen: dict[tuple[str, str], bool] = {}
    ordered_keys: list[tuple[str, str]] = []
    for _, dn, ndc, _, _ in detail_rows:
        if (dn, ndc) not in seen:
            seen[(dn, ndc)] = True
            ordered_keys.append((dn, ndc))

    medicines: list[dict[str, Any]] = []
    for drug_name, ndc in ordered_keys:
        t = totals_by_ndc.get(ndc, {})
        dispenses = dispenses_by_key.get((drug_name, ndc), [])
        inv_bucket = next(
            (d.get("inventory_bucket") for d in dispenses if d.get("inventory_bucket")),
            None,
        )
        lot_no_exp = next(
            (d.get("lot_no_exp_date") for d in dispenses if d.get("lot_no_exp_date")),
            None,
        )
        medicines.append(
            {
                "drug_name": drug_name,
                "ndc": ndc,
                "inventory_bucket": inv_bucket,
                "lot_no_exp_date": lot_no_exp,
                "totals": {
                    "packs": t.get("packs"),
                    "total_ins_paid": t.get("total_ins_paid"),
                    "total_price": t.get("total_price"),
                    "total_cost": t.get("total_cost"),
                    "total_rx_count": t.get("total_rx_count"),
                },
                "dispenses": dispenses,
            }
        )

    total_dispenses = sum(len(m.get("dispenses", [])) for m in medicines)
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "PDF extraction finished in {elapsed_ms:.1f} ms (lines={line_count}, medicines={med_count}, dispenses={disp_count})",
        elapsed_ms=elapsed_ms,
        line_count=len(lines),
        med_count=len(medicines),
        disp_count=total_dispenses,
    )

    return {
        "pharmacy": pharmacy,
        "medicines": medicines,
        "grand_total": _parse_grand_total(lines),
    }
