"""
models/document.py
──────────────────
SQLAlchemy model for documents uploaded via `/documents/process`.

Every document is bound to a medical store. Processing is
**extraction-only** — the handler's structured output is captured in
`result_data` (JSON-encoded). Domain rows in `invoices` / `drug_reports`
are only created later via `POST /invoices` / `POST /dispenses`.

`progress` is reused by the barcode handler when the upload contained
two images — it stashes the second image's storage path so a single
Document represents both files.

Status lifecycle:
    QUEUED → PROCESSING → COMPLETED
                       → FAILED → RETRYING → ...
                       → FAILED_PERMANENTLY
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True
    )

    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    process_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="dispense", index=True
    )
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUEUED", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # MEDIUMTEXT (16 MB) — dispense reports can serialize to >65 KB.
    result_data: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)

    # Used by the barcode handler when the request shipped 2 images:
    # {"second_image_path": "storage/documents/<doc_key>-2.jpg",
    #  "second_original_filename": "..."}.
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<Document(doc_key={self.doc_key!r}, "
            f"medical_store_id={self.medical_store_id}, "
            f"status={self.status!r}, "
            f"type={self.document_type!r})>"
        )
