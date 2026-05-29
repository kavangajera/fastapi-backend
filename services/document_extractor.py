"""
services/document_extractor.py
───────────────────────────────
Unified entry-point for all supported report file formats.

Supported extensions
--------------------
  .pdf   → services.pdf_extractor.extract_report()
  .docx  → services.doc_extractor.extract_report_from_docx()
  .doc   → services.doc_extractor.extract_report_from_doc()
  .xlsx  → services.excel_extractor.extract_report_from_excel()
  .xls   → services.excel_extractor.extract_report_from_excel()

Returns the same structured dict regardless of input format:
  { "pharmacy": {...}, "medicines": [...], "grand_total": {...} }
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from services import pdf_extractor, doc_extractor, excel_extractor

SUPPORTED_EXTENSIONS = {"pdf", "docx", "doc", "xlsx", "xls"}


def extract_report_from_file(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """
    Detect file type from *filename* extension and dispatch to the correct
    extractor.  Returns the standard report dict.

    Raises
    ------
    ValueError
        If the file extension is not in SUPPORTED_EXTENSIONS.
    """
    if not filename:
        raise ValueError("Filename must be provided to determine file type.")

    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    logger.info(
        "Dispatching extraction for '{filename}' (detected type: .{ext})",
        filename=filename,
        ext=ext,
    )

    if ext == "pdf":
        return pdf_extractor.extract_report(file_bytes)
    elif ext == "docx":
        return doc_extractor.extract_report_from_docx(file_bytes)
    elif ext == "doc":
        return doc_extractor.extract_report_from_doc(file_bytes)
    elif ext in ("xlsx", "xls"):
        return excel_extractor.extract_report_from_excel(file_bytes, filename)
    else:
        raise ValueError(
            f"Unsupported file type '.{ext}'. "
            f"Accepted formats: {', '.join(f'.{e}' for e in sorted(SUPPORTED_EXTENSIONS))}."
        )
