"""
models/document.py
──────────────────
SQLAlchemy model for documents processed via the Kafka pipeline.

Status lifecycle:
    UPLOADED → QUEUED → PROCESSING → COMPLETED
                                   → FAILED → RETRYING → ...
                                   → FAILED_PERMANENTLY
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    doc_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    original_filename: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    storage_path: Mapped[str] = mapped_column(
        String(500), nullable=False
    )
    file_size: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="QUEUED", index=True
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    result_data: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<Document(doc_key={self.doc_key!r}, "
            f"status={self.status!r}, "
            f"type={self.document_type!r})>"
        )
