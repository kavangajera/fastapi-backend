import time
from typing import Any

import requests
from fastapi import HTTPException, status
from loguru import logger

from core.config import settings
from services.dispense_gemini_extractor import process_pdf
from services.legacy_doc_extractor import (
    extract_report_from_doc as extract_legacy_doc,
)
from services.legacy_doc_extractor import (
    extract_report_from_docx as extract_legacy_docx,
)
from services.legacy_layout import validated_legacy_extract


def convert_to_pdf_via_gotenberg(file_bytes: bytes, filename: str) -> bytes:
    """
    Sends a document to the local Gotenberg LibreOffice container
    to convert it to a PDF, preserving table structures perfectly.
    """
    url = f"{settings.GOTENBERG_URL}/forms/libreoffice/convert"
    try:
        response = requests.post(url, files={"files": (filename, file_bytes)}, timeout=60.0)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"Gotenberg conversion failed for {filename}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to convert document to PDF for extraction.",
        ) from e


def extract_report_from_doc(file_bytes: bytes) -> dict[str, Any]:
    """
    Converts .doc via Gotenberg to PDF, then uses Vision LLM to parse it.
    """
    start_time = time.perf_counter()
    logger.info("DOC extraction started (Gotenberg -> PDF -> Vision LLM)")

    result = validated_legacy_extract(extract_legacy_doc, file_bytes)
    if result is None:
        pdf_bytes = convert_to_pdf_via_gotenberg(file_bytes, "document.doc")
        result = process_pdf(pdf_bytes)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"DOC extraction finished in {elapsed_ms:.1f} ms")
    return result


def extract_report_from_docx(file_bytes: bytes) -> dict[str, Any]:
    """
    Converts .docx via Gotenberg to PDF, then uses Vision LLM to parse it.
    """
    start_time = time.perf_counter()
    logger.info("DOCX extraction started (Gotenberg -> PDF -> Vision LLM)")

    result = validated_legacy_extract(extract_legacy_docx, file_bytes)
    if result is None:
        pdf_bytes = convert_to_pdf_via_gotenberg(file_bytes, "document.docx")
        result = process_pdf(pdf_bytes)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"DOCX extraction finished in {elapsed_ms:.1f} ms")
    return result
