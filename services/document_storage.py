"""
services/document_storage.py
─────────────────────────────
Local filesystem storage for uploaded documents.

Abstracted behind a class so it can be swapped for S3/MinIO later
without changing any callers.

Directory layout:
    storage/documents/{doc_key}.pdf
    storage/documents/{doc_key}.csv
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from core.config import settings


class DocumentStorageService:
    """Store and retrieve documents on the local filesystem."""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir or settings.DOCUMENT_STORAGE_DIR)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        file_bytes: bytes,
        doc_key: str,
        extension: str,
    ) -> str:
        """
        Persist file bytes to disk.

        Returns the relative storage path (e.g. "storage/documents/abc123.pdf").
        """
        filename = f"{doc_key}.{extension.lstrip('.')}"
        file_path = self._base_dir / filename
        file_path.write_bytes(file_bytes)

        storage_path = str(file_path)
        logger.info(
            "Document stored: doc_key={doc_key} path={path} size={size}",
            doc_key=doc_key,
            path=storage_path,
            size=len(file_bytes),
        )
        return storage_path

    def retrieve(self, storage_path: str) -> bytes:
        """Read file bytes from storage. Raises FileNotFoundError if missing."""
        path = Path(storage_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found at {storage_path}")
        data = path.read_bytes()
        logger.info(
            "Document retrieved: path={path} size={size}",
            path=storage_path,
            size=len(data),
        )
        return data

    def delete(self, storage_path: str) -> None:
        """Remove a document file from storage."""
        path = Path(storage_path)
        if path.exists():
            path.unlink()
            logger.info("Document deleted: path={path}", path=storage_path)
        else:
            logger.warning(
                "Document not found for deletion: path={path}",
                path=storage_path,
            )

    def exists(self, storage_path: str) -> bool:
        """Check if a document exists in storage."""
        return Path(storage_path).exists()


# ── Module-level singleton ──────────────────────────────────────────────────
document_storage = DocumentStorageService()
