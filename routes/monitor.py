"""
routes/monitor.py
─────────────────
Backend API endpoints for the pipeline monitoring dashboard.

All endpoints return JSON data consumed by the dashboard frontend.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import DocumentStatus
from database import get_db
from models.document import Document

router = APIRouter(prefix="/api/monitor", tags=["Monitoring"])


# ── GET /api/monitor/overview ───────────────────────────────────────────────


@router.get("/overview", summary="System overview and health")
def get_overview(db: Session = Depends(get_db)):
    """Aggregate stats for the dashboard header cards."""
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    last_1h = now - timedelta(hours=1)

    total = db.query(func.count(Document.id)).scalar() or 0

    status_counts = dict(
        db.query(Document.status, func.count(Document.id))
        .group_by(Document.status)
        .all()
    )

    queued = status_counts.get(DocumentStatus.QUEUED.value, 0)
    processing = status_counts.get(DocumentStatus.PROCESSING.value, 0)
    completed = status_counts.get(DocumentStatus.COMPLETED.value, 0)
    failed = status_counts.get(DocumentStatus.FAILED.value, 0)
    failed_perm = status_counts.get(DocumentStatus.FAILED_PERMANENTLY.value, 0)
    retrying = status_counts.get(DocumentStatus.RETRYING.value, 0)

    # Throughput: completed in last 24h
    completed_24h = (
        db.query(func.count(Document.id))
        .filter(
            Document.status == DocumentStatus.COMPLETED.value,
            Document.updated_at >= last_24h,
        )
        .scalar()
        or 0
    )

    # Throughput: completed in last 1h
    completed_1h = (
        db.query(func.count(Document.id))
        .filter(
            Document.status == DocumentStatus.COMPLETED.value,
            Document.updated_at >= last_1h,
        )
        .scalar()
        or 0
    )

    # Failed in last 24h
    failed_24h = (
        db.query(func.count(Document.id))
        .filter(
            Document.status.in_([
                DocumentStatus.FAILED.value,
                DocumentStatus.FAILED_PERMANENTLY.value,
            ]),
            Document.updated_at >= last_24h,
        )
        .scalar()
        or 0
    )

    # Success rate
    total_finished_24h = completed_24h + failed_24h
    success_rate = (
        round((completed_24h / total_finished_24h) * 100, 1)
        if total_finished_24h > 0
        else 100.0
    )

    # Average processing time (crude: updated_at - created_at for completed)
    avg_time_result = (
        db.query(
            func.avg(
                func.timestampdiff(
                    func.text("SECOND"),
                    Document.created_at,
                    Document.updated_at,
                )
            )
        )
        .filter(Document.status == DocumentStatus.COMPLETED.value)
        .scalar()
    )
    avg_processing_seconds = round(float(avg_time_result), 1) if avg_time_result else 0

    return {
        "total_documents": total,
        "queued": queued,
        "processing": processing,
        "completed": completed,
        "failed": failed + failed_perm,
        "retrying": retrying,
        "completed_24h": completed_24h,
        "completed_1h": completed_1h,
        "failed_24h": failed_24h,
        "success_rate": success_rate,
        "avg_processing_seconds": avg_processing_seconds,
        "timestamp": now.isoformat(),
    }


# ── GET /api/monitor/documents/recent ───────────────────────────────────────


@router.get("/documents/recent", summary="Recent documents")
def get_recent_documents(
    limit: int = 30,
    db: Session = Depends(get_db),
):
    """Most recent documents for the activity feed."""
    docs = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "doc_key": d.doc_key,
            "document_type": d.document_type,
            "original_filename": d.original_filename,
            "file_size": d.file_size,
            "status": d.status,
            "retry_count": d.retry_count,
            "error_message": d.error_message,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in docs
    ]


# ── GET /api/monitor/documents/by-status ────────────────────────────────────


@router.get("/documents/by-status", summary="Document count by status")
def get_documents_by_status(db: Session = Depends(get_db)):
    """Status distribution for the chart."""
    rows = (
        db.query(Document.status, func.count(Document.id))
        .group_by(Document.status)
        .all()
    )
    return {status: count for status, count in rows}


# ── GET /api/monitor/documents/by-type ──────────────────────────────────────


@router.get("/documents/by-type", summary="Document count by type")
def get_documents_by_type(db: Session = Depends(get_db)):
    """Type distribution for the chart."""
    rows = (
        db.query(Document.document_type, func.count(Document.id))
        .group_by(Document.document_type)
        .all()
    )
    return {dtype: count for dtype, count in rows}


# ── GET /api/monitor/documents/timeline ─────────────────────────────────────


@router.get("/documents/timeline", summary="Hourly throughput timeline")
def get_documents_timeline(
    hours: int = 24,
    db: Session = Depends(get_db),
):
    """Hourly document counts for the last N hours."""
    now = datetime.utcnow()
    timeline = []

    for i in range(hours, 0, -1):
        start = now - timedelta(hours=i)
        end = now - timedelta(hours=i - 1)

        completed = (
            db.query(func.count(Document.id))
            .filter(
                Document.status == DocumentStatus.COMPLETED.value,
                Document.updated_at >= start,
                Document.updated_at < end,
            )
            .scalar()
            or 0
        )
        failed = (
            db.query(func.count(Document.id))
            .filter(
                Document.status.in_([
                    DocumentStatus.FAILED.value,
                    DocumentStatus.FAILED_PERMANENTLY.value,
                ]),
                Document.updated_at >= start,
                Document.updated_at < end,
            )
            .scalar()
            or 0
        )
        queued = (
            db.query(func.count(Document.id))
            .filter(
                Document.created_at >= start,
                Document.created_at < end,
            )
            .scalar()
            or 0
        )

        timeline.append({
            "hour": start.strftime("%H:%M"),
            "completed": completed,
            "failed": failed,
            "queued": queued,
        })

    return timeline


# ── GET /api/monitor/services ───────────────────────────────────────────────


@router.get("/services", summary="Service health status")
def get_services_health(db: Session = Depends(get_db)):
    """
    Health status of each service in the architecture.
    Checks actual connectivity where possible.
    """
    services = []

    # 1. API Server — always alive if this endpoint responds
    services.append({
        "name": "API Server",
        "type": "api",
        "status": "healthy",
        "icon": "server",
        "details": f"FastAPI on port 5001",
        "uptime": True,
    })

    # 2. Database — check with a simple query
    try:
        db.execute(func.text("SELECT 1"))
        db_status = "healthy"
        db_detail = "MySQL connected"
    except Exception as e:
        db_status = "down"
        db_detail = str(e)

    services.append({
        "name": "Database",
        "type": "database",
        "status": db_status,
        "icon": "database",
        "details": db_detail,
        "uptime": db_status == "healthy",
    })

    # 3. Kafka Producer — check if the singleton is connected
    try:
        from kafka_infra.producer import kafka_producer
        kafka_status = "healthy" if kafka_producer._producer else "down"
        kafka_detail = (
            f"Connected to {settings.KAFKA_BOOTSTRAP_SERVERS}"
            if kafka_producer._producer
            else "Producer not connected"
        )
    except Exception:
        kafka_status = "down"
        kafka_detail = "Producer unavailable"

    services.append({
        "name": "Kafka Broker",
        "type": "kafka",
        "status": kafka_status,
        "icon": "message-square",
        "details": kafka_detail,
        "uptime": kafka_status == "healthy",
    })

    # 4. Document Storage — check if directory exists and is writable
    import os
    storage_dir = settings.DOCUMENT_STORAGE_DIR
    storage_exists = os.path.isdir(storage_dir)
    services.append({
        "name": "Document Storage",
        "type": "storage",
        "status": "healthy" if storage_exists else "warning",
        "icon": "hard-drive",
        "details": f"Local: {storage_dir}" if storage_exists else "Directory missing",
        "uptime": storage_exists,
    })

    # 5. Worker status — infer from recent processing activity
    now = datetime.utcnow()
    recent_processing = (
        db.query(func.count(Document.id))
        .filter(
            Document.status == DocumentStatus.PROCESSING.value,
        )
        .scalar()
        or 0
    )
    recent_completed = (
        db.query(func.count(Document.id))
        .filter(
            Document.status == DocumentStatus.COMPLETED.value,
            Document.updated_at >= now - timedelta(minutes=5),
        )
        .scalar()
        or 0
    )

    if recent_processing > 0 or recent_completed > 0:
        worker_status = "healthy"
        worker_detail = f"{recent_processing} processing, {recent_completed} completed (5m)"
    else:
        # Check if there are queued items waiting
        queued_count = (
            db.query(func.count(Document.id))
            .filter(Document.status == DocumentStatus.QUEUED.value)
            .scalar()
            or 0
        )
        if queued_count > 0:
            worker_status = "warning"
            worker_detail = f"{queued_count} queued, no recent activity"
        else:
            worker_status = "idle"
            worker_detail = "No pending work"

    services.append({
        "name": "Document Workers",
        "type": "worker",
        "status": worker_status,
        "icon": "cpu",
        "details": worker_detail,
        "uptime": worker_status in ("healthy", "idle"),
    })

    return services


# ── GET /api/monitor/config ─────────────────────────────────────────────────


@router.get("/config", summary="Pipeline configuration")
def get_config():
    """Current pipeline configuration (non-sensitive)."""
    return {
        "kafka_bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "kafka_topic": settings.KAFKA_DOCUMENT_TOPIC,
        "kafka_consumer_group": settings.KAFKA_CONSUMER_GROUP,
        "kafka_dlq_topic": settings.KAFKA_DLQ_TOPIC,
        "storage_dir": settings.DOCUMENT_STORAGE_DIR,
        "max_file_size_mb": settings.DOCUMENT_MAX_FILE_SIZE_MB,
        "max_retries": settings.DOCUMENT_MAX_RETRIES,
    }
