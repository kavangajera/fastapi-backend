"""
kafka_worker/handlers/barcode_handler.py
────────────────────────────────────────
Barcode + datamatrix extraction.

The Document points to the *first* image at `storage_path`. If the
upload included a second image, the route stashed its storage path in
`doc.progress["second_image_path"]`. This handler reads both, hands
them to `services.barcode_pairing.pair_images` (which scans + pairs
them), and returns the merged dict.

No DB writes beyond the worker's own status / result_data updates.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from models.document import Document
from services.barcode_pairing import pair_images
from services.document_storage import document_storage


async def handle_barcode(
    session: AsyncSession,
    doc: Document,
    *,
    medical_store_id: int,
) -> dict:
    images: list[tuple[bytes, str]] = []

    first_bytes = document_storage.retrieve(doc.storage_path)
    images.append((first_bytes, doc.original_filename or doc.doc_key))

    progress = doc.progress or {}
    second_path = progress.get("second_image_path")
    if second_path:
        second_bytes = document_storage.retrieve(second_path)
        images.append(
            (second_bytes, progress.get("second_original_filename") or f"{doc.doc_key}-2")
        )

    logger.info(
        "Barcode extract: doc_key={dk} images={n}",
        dk=doc.doc_key,
        n=len(images),
    )

    result = await asyncio.to_thread(pair_images, images)
    result["medical_store_id"] = medical_store_id
    result["document_id"] = doc.id
    return result
