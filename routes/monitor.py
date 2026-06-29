"""
routes/monitor.py
─────────────────
Backend API endpoints for the pipeline monitoring dashboard. Async.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.config import settings
from core.enums import DocumentStatus
from kafka_infra import topics
from middlewares.auth import require_admin
from models.document import Document

# System-wide monitoring data (spans every pharmacy: documents, logs,
# pipeline config, host metrics). Gated to authenticated ADMIN users via a
# router-level dependency so every current and future endpoint is covered.
router = APIRouter(
    prefix="/api/monitor",
    tags=["Monitoring"],
    dependencies=[Depends(require_admin)],
)


async def _count(db: AsyncSession, stmt) -> int:
    """Run `select count(...)` and return int."""
    return (await db.execute(stmt)).scalar() or 0


# ── GET /api/monitor/overview ───────────────────────────────────────────────


@router.get("/overview", summary="System overview and health")
async def get_overview(db: AsyncSession = Depends(get_async_db)):
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    last_1h = now - timedelta(hours=1)

    total = await _count(db, select(func.count(Document.id)))

    status_rows = await db.execute(
        select(Document.status, func.count(Document.id)).group_by(Document.status)
    )
    status_counts = dict(status_rows.all())

    queued = status_counts.get(DocumentStatus.QUEUED.value, 0)
    processing = status_counts.get(DocumentStatus.PROCESSING.value, 0)
    completed = status_counts.get(DocumentStatus.COMPLETED.value, 0)
    failed = status_counts.get(DocumentStatus.FAILED.value, 0)
    failed_perm = status_counts.get(DocumentStatus.FAILED_PERMANENTLY.value, 0)
    retrying = status_counts.get(DocumentStatus.RETRYING.value, 0)

    completed_24h = await _count(
        db,
        select(func.count(Document.id)).where(
            Document.status == DocumentStatus.COMPLETED.value,
            Document.updated_at >= last_24h,
        ),
    )
    completed_1h = await _count(
        db,
        select(func.count(Document.id)).where(
            Document.status == DocumentStatus.COMPLETED.value,
            Document.updated_at >= last_1h,
        ),
    )
    failed_24h = await _count(
        db,
        select(func.count(Document.id)).where(
            Document.status.in_(
                [
                    DocumentStatus.FAILED.value,
                    DocumentStatus.FAILED_PERMANENTLY.value,
                ]
            ),
            Document.updated_at >= last_24h,
        ),
    )

    total_finished_24h = completed_24h + failed_24h
    success_rate = (
        round((completed_24h / total_finished_24h) * 100, 1) if total_finished_24h > 0 else 100.0
    )

    # MySQL TIMESTAMPDIFF(SECOND, ...) — MySQL-specific (we run on MySQL).
    avg_result = await db.execute(
        select(
            func.avg(func.timestampdiff(text("SECOND"), Document.created_at, Document.updated_at))
        ).where(Document.status == DocumentStatus.COMPLETED.value)
    )
    avg_value = avg_result.scalar()
    avg_processing_seconds = round(float(avg_value), 1) if avg_value else 0

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
async def get_recent_documents(limit: int = 30, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Document).order_by(Document.created_at.desc()).limit(limit))
    docs = result.scalars().all()
    return [
        {
            "doc_key": d.doc_key,
            "document_type": d.document_type,
            "original_filename": d.original_filename,
            "file_size": d.file_size,
            "status": d.status,
            "retry_count": d.retry_count,
            "error_message": d.error_message,
            "medical_store_id": d.medical_store_id,
            "batch_id": d.batch_id,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in docs
    ]


# ── GET /api/monitor/documents/by-status ────────────────────────────────────


@router.get("/documents/by-status", summary="Document count by status")
async def get_documents_by_status(db: AsyncSession = Depends(get_async_db)):
    rows = await db.execute(
        select(Document.status, func.count(Document.id)).group_by(Document.status)
    )
    return {s: c for s, c in rows.all()}


@router.get("/documents/by-type", summary="Document count by type")
async def get_documents_by_type(db: AsyncSession = Depends(get_async_db)):
    rows = await db.execute(
        select(Document.document_type, func.count(Document.id)).group_by(Document.document_type)
    )
    return {t: c for t, c in rows.all()}


# ── GET /api/monitor/documents/timeline ─────────────────────────────────────


@router.get("/documents/timeline", summary="Hourly throughput timeline")
async def get_documents_timeline(hours: int = 24, db: AsyncSession = Depends(get_async_db)):
    now = datetime.utcnow()
    timeline = []

    for i in range(hours, 0, -1):
        start = now - timedelta(hours=i)
        end = now - timedelta(hours=i - 1)

        completed = await _count(
            db,
            select(func.count(Document.id)).where(
                Document.status == DocumentStatus.COMPLETED.value,
                Document.updated_at >= start,
                Document.updated_at < end,
            ),
        )
        failed = await _count(
            db,
            select(func.count(Document.id)).where(
                Document.status.in_(
                    [
                        DocumentStatus.FAILED.value,
                        DocumentStatus.FAILED_PERMANENTLY.value,
                    ]
                ),
                Document.updated_at >= start,
                Document.updated_at < end,
            ),
        )
        queued = await _count(
            db,
            select(func.count(Document.id)).where(
                Document.created_at >= start, Document.created_at < end
            ),
        )

        timeline.append(
            {
                "hour": start.strftime("%H:%M"),
                "completed": completed,
                "failed": failed,
                "queued": queued,
            }
        )

    return timeline


# ── GET /api/monitor/services ───────────────────────────────────────────────


@router.get("/services", summary="Service health status")
async def get_services_health(db: AsyncSession = Depends(get_async_db)):
    services = [
        {
            "name": "API Server",
            "type": "api",
            "status": "healthy",
            "icon": "server",
            "details": "FastAPI on port 5001",
            "uptime": True,
        }
    ]

    try:
        await db.execute(text("SELECT 1"))
        db_status, db_detail = "healthy", "MySQL connected"
    except Exception as exc:
        db_status, db_detail = "down", str(exc)
    services.append(
        {
            "name": "Database",
            "type": "database",
            "status": db_status,
            "icon": "database",
            "details": db_detail,
            "uptime": db_status == "healthy",
        }
    )

    try:
        from kafka_infra.producer import kafka_producer

        kafka_connected = bool(kafka_producer._producer)
    except Exception:
        kafka_connected = False
    services.append(
        {
            "name": "Kafka Broker",
            "type": "kafka",
            "status": "healthy" if kafka_connected else "down",
            "icon": "message-square",
            "details": (
                f"Connected to {settings.KAFKA_BOOTSTRAP_SERVERS}"
                if kafka_connected
                else "Producer not connected"
            ),
            "uptime": kafka_connected,
        }
    )

    import asyncio

    storage_dir = settings.DOCUMENT_STORAGE_DIR
    storage_exists = await asyncio.to_thread(os.path.isdir, storage_dir)
    services.append(
        {
            "name": "Document Storage",
            "type": "storage",
            "status": "healthy" if storage_exists else "warning",
            "icon": "hard-drive",
            "details": (f"Local: {storage_dir}" if storage_exists else "Directory missing"),
            "uptime": storage_exists,
        }
    )

    now = datetime.utcnow()
    recent_processing = await _count(
        db,
        select(func.count(Document.id)).where(Document.status == DocumentStatus.PROCESSING.value),
    )
    recent_completed = await _count(
        db,
        select(func.count(Document.id)).where(
            Document.status == DocumentStatus.COMPLETED.value,
            Document.updated_at >= now - timedelta(minutes=5),
        ),
    )

    if recent_processing > 0 or recent_completed > 0:
        worker_status = "healthy"
        worker_detail = f"{recent_processing} processing, {recent_completed} completed (5m)"
    else:
        queued_count = await _count(
            db,
            select(func.count(Document.id)).where(Document.status == DocumentStatus.QUEUED.value),
        )
        if queued_count > 0:
            worker_status = "warning"
            worker_detail = f"{queued_count} queued, no recent activity"
        else:
            worker_status = "idle"
            worker_detail = "No pending work"

    services.append(
        {
            "name": "Document Workers",
            "type": "worker",
            "status": worker_status,
            "icon": "cpu",
            "details": worker_detail,
            "uptime": worker_status in ("healthy", "idle"),
        }
    )

    return services


# ── GET /api/monitor/config ─────────────────────────────────────────────────


@router.get("/config", summary="Pipeline configuration")
def get_config():
    return {
        "kafka_bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "kafka_topics": topics.all_topics(),
        "kafka_results_topic": topics.results_topic(),
        "storage_dir": settings.DOCUMENT_STORAGE_DIR,
        "max_file_size_mb": settings.DOCUMENT_MAX_FILE_SIZE_MB,
        "max_retries": settings.DOCUMENT_MAX_RETRIES,
    }


# ── GET /api/monitor/metrics ────────────────────────────────────────────────


def _format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


@router.get("/metrics", summary="System metrics (no DB tracking)")
def get_system_metrics():
    import gc
    import platform
    import time

    process_start = getattr(get_system_metrics, "_start_time", None)
    if process_start is None:
        get_system_metrics._start_time = time.time()
        process_start = get_system_metrics._start_time

    uptime_seconds = time.time() - process_start

    memory_info = {"rss_mb": 0, "available_pct": 0}
    try:
        import resource

        rusage = resource.getrusage(resource.RUSAGE_SELF)
        memory_info["rss_mb"] = round(rusage.ru_maxrss / 1024, 1)
    except Exception:
        pass

    disk_info = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "used_pct": 0}
    try:
        usage = shutil.disk_usage(settings.DOCUMENT_STORAGE_DIR)
        disk_info = {
            "total_gb": round(usage.total / (1024**3), 1),
            "used_gb": round(usage.used / (1024**3), 1),
            "free_gb": round(usage.free / (1024**3), 1),
            "used_pct": (round((usage.used / usage.total) * 100, 1) if usage.total else 0),
        }
    except Exception:
        pass

    return {
        "uptime_seconds": round(uptime_seconds, 0),
        "uptime_formatted": _format_uptime(uptime_seconds),
        "cpu_count": os.cpu_count() or 1,
        "memory": memory_info,
        "disk": disk_info,
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "gc_counts": gc.get_count(),
        "gc_stats": gc.get_stats(),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── GET /api/monitor/logs ───────────────────────────────────────────────────


@router.get("/logs", summary="Recent application logs (in-memory)")
def get_logs(limit: int = 100, level: str | None = None):
    from core.log_buffer import log_buffer

    return log_buffer.get_logs(limit=limit, level=level)


# ── GET /api/monitor/alerts ─────────────────────────────────────────────────


@router.get("/alerts", summary="Computed alerts (threshold-based)")
async def get_alerts(db: AsyncSession = Depends(get_async_db)):
    now = datetime.utcnow()
    alerts: list[dict] = []

    queued = await _count(
        db,
        select(func.count(Document.id)).where(Document.status == DocumentStatus.QUEUED.value),
    )
    if queued > 50:
        alerts.append(
            {
                "id": "queue-depth-critical",
                "severity": "critical",
                "title": "Critical Queue Depth",
                "message": f"{queued} documents are waiting in queue",
                "service": "Kafka Broker",
                "rule": "queue_depth > 50",
                "value": queued,
                "state": "firing",
                "fired_at": now.isoformat(),
            }
        )
    elif queued > 10:
        alerts.append(
            {
                "id": "queue-depth-high",
                "severity": "warning",
                "title": "High Queue Depth",
                "message": f"{queued} documents are waiting in queue",
                "service": "Kafka Broker",
                "rule": "queue_depth > 10",
                "value": queued,
                "state": "firing",
                "fired_at": now.isoformat(),
            }
        )

    last_1h = now - timedelta(hours=1)
    completed_1h = await _count(
        db,
        select(func.count(Document.id)).where(
            Document.status == DocumentStatus.COMPLETED.value,
            Document.updated_at >= last_1h,
        ),
    )
    failed_1h = await _count(
        db,
        select(func.count(Document.id)).where(
            Document.status.in_(
                [
                    DocumentStatus.FAILED.value,
                    DocumentStatus.FAILED_PERMANENTLY.value,
                ]
            ),
            Document.updated_at >= last_1h,
        ),
    )
    total_1h = completed_1h + failed_1h
    error_rate = round((failed_1h / total_1h) * 100, 1) if total_1h > 0 else 0
    if error_rate > 10:
        alerts.append(
            {
                "id": "error-rate-high",
                "severity": "critical" if error_rate > 30 else "warning",
                "title": "High Error Rate",
                "message": (
                    f"{error_rate}% failure rate in the last hour ({failed_1h}/{total_1h})"
                ),
                "service": "Document Worker",
                "rule": "error_rate_1h > 10%",
                "value": error_rate,
                "state": "firing",
                "fired_at": now.isoformat(),
            }
        )

    stale_cutoff = now - timedelta(minutes=5)
    stale_processing = await _count(
        db,
        select(func.count(Document.id)).where(
            Document.status == DocumentStatus.PROCESSING.value,
            Document.updated_at < stale_cutoff,
        ),
    )
    if stale_processing > 0:
        alerts.append(
            {
                "id": "stale-processing",
                "severity": "warning",
                "title": "Stale Processing Detected",
                "message": (f"{stale_processing} document(s) stuck in PROCESSING for >5 min"),
                "service": "Document Worker",
                "rule": "processing_stale > 5min",
                "value": stale_processing,
                "state": "firing",
                "fired_at": now.isoformat(),
            }
        )

    try:
        from kafka_infra.producer import kafka_producer

        if not kafka_producer._producer:
            alerts.append(
                {
                    "id": "kafka-disconnected",
                    "severity": "critical",
                    "title": "Kafka Producer Disconnected",
                    "message": (
                        "Kafka producer is not connected. Document processing is unavailable."
                    ),
                    "service": "Kafka Broker",
                    "rule": "kafka_producer.connected == false",
                    "value": 0,
                    "state": "firing",
                    "fired_at": now.isoformat(),
                }
            )
    except Exception:
        pass

    rules = [
        {
            "id": "queue-depth-high",
            "name": "High Queue Depth",
            "expr": "queue_depth > 10",
            "severity": "warning",
            "for": "0m",
        },
        {
            "id": "queue-depth-critical",
            "name": "Critical Queue Depth",
            "expr": "queue_depth > 50",
            "severity": "critical",
            "for": "0m",
        },
        {
            "id": "error-rate-high",
            "name": "High Error Rate",
            "expr": "error_rate_1h > 10%",
            "severity": "warning",
            "for": "0m",
        },
        {
            "id": "stale-processing",
            "name": "Stale Processing",
            "expr": "processing_time > 5min",
            "severity": "warning",
            "for": "5m",
        },
        {
            "id": "kafka-disconnected",
            "name": "Kafka Disconnected",
            "expr": "kafka_producer == down",
            "severity": "critical",
            "for": "0m",
        },
    ]

    return {
        "alerts": alerts,
        "rules": rules,
        "total_firing": len(alerts),
        "timestamp": now.isoformat(),
    }
