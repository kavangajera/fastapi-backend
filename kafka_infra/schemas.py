"""
kafka_infra/schemas.py
──────────────────────
Pydantic models for Kafka message payloads.

Messages are intentionally tiny — only metadata, never file content.
"""

from datetime import datetime

from pydantic import BaseModel


class DocumentJobMessage(BaseModel):
    """Payload published to the document processing Kafka topic."""

    doc_key: str
    document_type: str
    timestamp: str  # ISO 8601

    @classmethod
    def create(cls, doc_key: str, document_type: str) -> "DocumentJobMessage":
        return cls(
            doc_key=doc_key,
            document_type=document_type,
            timestamp=datetime.utcnow().isoformat(),
        )
