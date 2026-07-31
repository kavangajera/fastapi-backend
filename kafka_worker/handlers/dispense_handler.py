"""Extraction-only dispense handler with POST and PATCH queue modes."""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kafka_worker.errors import PermanentDocumentError
from models.dispense_report import Dispense
from models.document import Document
from services.document_extractor import extract_report_from_file
from services.document_storage import document_storage
from services.validation import validate_tier1


async def handle_dispense(
    session: AsyncSession,
    doc: Document,
    *,
    medical_store_id: int,
) -> dict:
    file_bytes = document_storage.retrieve(doc.storage_path)
    filename = doc.original_filename or doc.doc_key
    report_data = await asyncio.to_thread(extract_report_from_file, file_bytes, filename)
    report_data["medical_store_id"] = medical_store_id
    report_data["document_id"] = doc.id

    incoming_rx_nos = [
        row.get("rx_no")
        for medicine in report_data.get("medicines", [])
        for row in medicine.get("dispenses", [])
        if row.get("rx_no")
    ]
    patch_mode = bool(doc.progress and doc.progress.get("request_mode") == "patch")
    if patch_mode:
        await _filter_patch_rows(session, report_data, medical_store_id, incoming_rx_nos)
    elif incoming_rx_nos:
        existing = await session.execute(
            select(Dispense.rx_no).where(
                Dispense.medical_store_id == medical_store_id,
                Dispense.rx_no.in_(incoming_rx_nos),
                Dispense.IsDeleted.is_(False),
            )
        )
        duplicates = [row[0] for row in existing.all()]
        if duplicates:
            raise ValueError(
                f"Duplicate document: {len(duplicates)} rx_no(s) already exist "
                f"for this pharmacy. Duplicate rx_no: {duplicates}"
            )

    tier1 = validate_tier1(report_data)
    report_data["validation"] = tier1.model_dump(mode="json")
    logger.info(
        "Dispense Tier-1: store={store} doc_key={key} patch={patch} errors={errors}",
        store=medical_store_id,
        key=doc.doc_key,
        patch=patch_mode,
        errors=tier1.summary.errors,
    )
    return report_data


async def _filter_patch_rows(
    session: AsyncSession,
    report_data: dict,
    medical_store_id: int,
    incoming_rx_nos: list[str],
) -> None:
    if not incoming_rx_nos:
        raise PermanentDocumentError(400, "No rx_no values found in the document.")
    existing = await session.execute(
        select(Dispense.rx_no).where(
            Dispense.medical_store_id == medical_store_id,
            Dispense.rx_no.in_(incoming_rx_nos),
            Dispense.IsDeleted.is_(False),
        )
    )
    existing_rx_nos = {row[0] for row in existing.all()}
    if not existing_rx_nos:
        raise PermanentDocumentError(404, "No document rx_no values exist for this pharmacy.")

    kept_medicines = []
    for medicine in report_data.get("medicines", []):
        rows = [row for row in medicine.get("dispenses", []) if row.get("rx_no") in existing_rx_nos]
        if rows:
            medicine["dispenses"] = rows
            kept_medicines.append(medicine)
    report_data["medicines"] = kept_medicines
