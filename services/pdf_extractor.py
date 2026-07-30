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

import time
from typing import Any

from loguru import logger

from services.dispense_llm_extractor import process_pdf


def extract_report(pdf_bytes: bytes) -> dict[str, Any]:
    """
    Main entry point. Accepts raw PDF bytes, returns structured report dict using LLM extraction.
    """
    start_time = time.perf_counter()
    logger.info("PDF extraction started (LLM mode)")
    
    result = process_pdf(pdf_bytes)
    
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"PDF extraction finished in {elapsed_ms:.1f} ms")
    return result
