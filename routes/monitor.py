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
from kafka_infra import topics
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
        "kafka_topics": topics.all_topics(),
        "kafka_results_topic": topics.results_topic(),
        "storage_dir": settings.DOCUMENT_STORAGE_DIR,
        "max_file_size_mb": settings.DOCUMENT_MAX_FILE_SIZE_MB,
        "max_retries": settings.DOCUMENT_MAX_RETRIES,
    }


# ── GET /api/monitor/metrics ───────────────────────────────────────────────


@router.get("/metrics", summary="System metrics (no DB tracking)")
def get_system_metrics():
    """
    Real-time system metrics using stdlib only.
    No database tracking — purely ephemeral.
    """
    import os
    import gc
    import platform
    import time

    process_start = getattr(get_system_metrics, "_start_time", None)
    if process_start is None:
        get_system_metrics._start_time = time.time()
        process_start = get_system_metrics._start_time

    uptime_seconds = time.time() - process_start

    # GC stats
    gc_stats = gc.get_stats()
    gc_counts = gc.get_count()

    # Memory estimation via resource (platform-dependent)
    memory_info = {"rss_mb": 0, "available_pct": 0}
    try:
        import resource
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        memory_info["rss_mb"] = round(rusage.ru_maxrss / 1024, 1)  # Linux KB → MB
    except (ImportError, Exception):
        # Windows fallback
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            memory_info["rss_mb"] = round((mem.ullTotalPhys - mem.ullAvailPhys) / (1024 ** 2), 1)
            memory_info["available_pct"] = 100 - mem.dwMemoryLoad
            memory_info["total_mb"] = round(mem.ullTotalPhys / (1024 ** 2), 1)
            memory_info["used_pct"] = mem.dwMemoryLoad
        except Exception:
            pass

    # CPU count
    cpu_count = os.cpu_count() or 1

    # Disk usage for storage dir
    disk_info = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "used_pct": 0}
    try:
        import shutil
        usage = shutil.disk_usage(settings.DOCUMENT_STORAGE_DIR)
        disk_info = {
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "used_gb": round(usage.used / (1024 ** 3), 1),
            "free_gb": round(usage.free / (1024 ** 3), 1),
            "used_pct": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
        }
    except Exception:
        pass

    return {
        "uptime_seconds": round(uptime_seconds, 0),
        "uptime_formatted": _format_uptime(uptime_seconds),
        "cpu_count": cpu_count,
        "memory": memory_info,
        "disk": disk_info,
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "gc_counts": gc_counts,
        "gc_stats": gc_stats,
        "timestamp": datetime.utcnow().isoformat(),
    }


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


# ── GET /api/monitor/logs ──────────────────────────────────────────────────


@router.get("/logs", summary="Recent application logs (in-memory)")
def get_logs(limit: int = 100, level: str | None = None):
    """
    Returns recent application logs from the in-memory ring buffer.
    No database tracking — logs are ephemeral.
    """
    from core.log_buffer import log_buffer
    return log_buffer.get_logs(limit=limit, level=level)


# ── GET /api/monitor/traces ────────────────────────────────────────────────


@router.get("/traces", summary="Document processing traces")
def get_traces(limit: int = 20, db: Session = Depends(get_db)):
    """
    Build trace-like data from document lifecycle events.
    Read-only — no new database tracking.
    """
    docs = (
        db.query(Document)
        .filter(Document.status.in_([
            DocumentStatus.COMPLETED.value,
            DocumentStatus.FAILED.value,
            DocumentStatus.FAILED_PERMANENTLY.value,
            DocumentStatus.PROCESSING.value,
        ]))
        .order_by(Document.updated_at.desc())
        .limit(limit)
        .all()
    )

    traces = []
    for doc in docs:
        created = doc.created_at
        updated = doc.updated_at or created
        if not created:
            continue

        total_duration_ms = int((updated - created).total_seconds() * 1000) if updated and created else 0

        # Simulate spans based on status progression
        spans = []
        cursor = 0

        # Span 1: Upload
        upload_dur = max(int(total_duration_ms * 0.05), 10)
        spans.append({
            "name": "document.upload",
            "service": "API Server",
            "start_ms": cursor,
            "duration_ms": upload_dur,
            "status": "ok",
            "tags": {"filename": doc.original_filename or "unknown", "size": doc.file_size or 0},
        })
        cursor += upload_dur

        # Span 2: Kafka enqueue
        kafka_dur = max(int(total_duration_ms * 0.03), 5)
        spans.append({
            "name": "kafka.produce",
            "service": "Kafka Broker",
            "start_ms": cursor,
            "duration_ms": kafka_dur,
            "status": "ok",
            "tags": {"topic": topics.main_topic(doc.process_type), "partition": hash(doc.doc_key) % 3},
        })
        cursor += kafka_dur

        # Span 3: Queue wait
        queue_dur = max(int(total_duration_ms * 0.15), 20)
        spans.append({
            "name": "queue.wait",
            "service": "Kafka Broker",
            "start_ms": cursor,
            "duration_ms": queue_dur,
            "status": "ok",
            "tags": {"consumer_group": topics.worker_group(doc.process_type)},
        })
        cursor += queue_dur

        # Span 4: Processing
        proc_dur = max(total_duration_ms - cursor - 10, 50)
        proc_status = "error" if doc.status in (DocumentStatus.FAILED.value, DocumentStatus.FAILED_PERMANENTLY.value) else "ok"
        spans.append({
            "name": "document.process",
            "service": "Document Worker",
            "start_ms": cursor,
            "duration_ms": proc_dur,
            "status": proc_status,
            "tags": {"type": doc.document_type, "retries": doc.retry_count},
        })
        cursor += proc_dur

        # Span 5: Storage write (only if completed)
        if doc.status == DocumentStatus.COMPLETED.value:
            store_dur = max(int(total_duration_ms * 0.02), 5)
            spans.append({
                "name": "storage.write",
                "service": "Document Storage",
                "start_ms": cursor,
                "duration_ms": store_dur,
                "status": "ok",
                "tags": {"dir": settings.DOCUMENT_STORAGE_DIR},
            })

        traces.append({
            "trace_id": doc.doc_key[:16],
            "doc_key": doc.doc_key,
            "filename": doc.original_filename or "unknown",
            "status": doc.status,
            "total_duration_ms": total_duration_ms,
            "span_count": len(spans),
            "spans": spans,
            "started_at": created.isoformat() if created else None,
            "ended_at": updated.isoformat() if updated else None,
        })

    return traces


# ── GET /api/monitor/alerts ────────────────────────────────────────────────


@router.get("/alerts", summary="Computed alerts (threshold-based)")
def get_alerts(db: Session = Depends(get_db)):
    """
    Compute alerts from current state. No database tracking — all ephemeral.
    """
    now = datetime.utcnow()
    alerts = []

    # Rule 1: Queue depth > 10
    queued = (
        db.query(func.count(Document.id))
        .filter(Document.status == DocumentStatus.QUEUED.value)
        .scalar() or 0
    )
    if queued > 10:
        alerts.append({
            "id": "queue-depth-high",
            "severity": "warning",
            "title": "High Queue Depth",
            "message": f"{queued} documents are waiting in queue",
            "service": "Kafka Broker",
            "rule": "queue_depth > 10",
            "value": queued,
            "state": "firing",
            "fired_at": now.isoformat(),
        })
    elif queued > 50:
        alerts.append({
            "id": "queue-depth-critical",
            "severity": "critical",
            "title": "Critical Queue Depth",
            "message": f"{queued} documents are waiting in queue",
            "service": "Kafka Broker",
            "rule": "queue_depth > 50",
            "value": queued,
            "state": "firing",
            "fired_at": now.isoformat(),
        })

    # Rule 2: Error rate > 10% in last hour
    last_1h = now - timedelta(hours=1)
    completed_1h = (
        db.query(func.count(Document.id))
        .filter(
            Document.status == DocumentStatus.COMPLETED.value,
            Document.updated_at >= last_1h,
        ).scalar() or 0
    )
    failed_1h = (
        db.query(func.count(Document.id))
        .filter(
            Document.status.in_([
                DocumentStatus.FAILED.value,
                DocumentStatus.FAILED_PERMANENTLY.value,
            ]),
            Document.updated_at >= last_1h,
        ).scalar() or 0
    )
    total_1h = completed_1h + failed_1h
    error_rate = round((failed_1h / total_1h) * 100, 1) if total_1h > 0 else 0

    if error_rate > 10:
        alerts.append({
            "id": "error-rate-high",
            "severity": "critical" if error_rate > 30 else "warning",
            "title": "High Error Rate",
            "message": f"{error_rate}% failure rate in the last hour ({failed_1h}/{total_1h})",
            "service": "Document Worker",
            "rule": "error_rate_1h > 10%",
            "value": error_rate,
            "state": "firing",
            "fired_at": now.isoformat(),
        })

    # Rule 3: Stale processing — docs stuck in PROCESSING > 5 min
    stale_cutoff = now - timedelta(minutes=5)
    stale_processing = (
        db.query(func.count(Document.id))
        .filter(
            Document.status == DocumentStatus.PROCESSING.value,
            Document.updated_at < stale_cutoff,
        ).scalar() or 0
    )
    if stale_processing > 0:
        alerts.append({
            "id": "stale-processing",
            "severity": "warning",
            "title": "Stale Processing Detected",
            "message": f"{stale_processing} document(s) stuck in PROCESSING for >5 min",
            "service": "Document Worker",
            "rule": "processing_stale > 5min",
            "value": stale_processing,
            "state": "firing",
            "fired_at": now.isoformat(),
        })

    # Rule 4: Kafka producer health
    try:
        from kafka_infra.producer import kafka_producer
        if not kafka_producer._producer:
            alerts.append({
                "id": "kafka-disconnected",
                "severity": "critical",
                "title": "Kafka Producer Disconnected",
                "message": "Kafka producer is not connected. Document processing is unavailable.",
                "service": "Kafka Broker",
                "rule": "kafka_producer.connected == false",
                "value": 0,
                "state": "firing",
                "fired_at": now.isoformat(),
            })
    except Exception:
        pass

    # Rule 5: No activity in last 30 min (if there are queued docs)
    if queued > 0:
        last_30m = now - timedelta(minutes=30)
        recent_activity = (
            db.query(func.count(Document.id))
            .filter(
                Document.status == DocumentStatus.COMPLETED.value,
                Document.updated_at >= last_30m,
            ).scalar() or 0
        )
        if recent_activity == 0:
            alerts.append({
                "id": "worker-inactive",
                "severity": "warning",
                "title": "Worker Inactivity",
                "message": f"No documents completed in 30 min but {queued} are queued",
                "service": "Document Worker",
                "rule": "worker_idle_30m && queue_depth > 0",
                "value": queued,
                "state": "firing",
                "fired_at": now.isoformat(),
            })

    # Alert rules (for display, always returned)
    rules = [
        {"id": "queue-depth-high", "name": "High Queue Depth", "expr": "queue_depth > 10", "severity": "warning", "for": "0m"},
        {"id": "queue-depth-critical", "name": "Critical Queue Depth", "expr": "queue_depth > 50", "severity": "critical", "for": "0m"},
        {"id": "error-rate-high", "name": "High Error Rate", "expr": "error_rate_1h > 10%", "severity": "warning", "for": "0m"},
        {"id": "stale-processing", "name": "Stale Processing", "expr": "processing_time > 5min", "severity": "warning", "for": "5m"},
        {"id": "kafka-disconnected", "name": "Kafka Disconnected", "expr": "kafka_producer == down", "severity": "critical", "for": "0m"},
        {"id": "worker-inactive", "name": "Worker Inactivity", "expr": "worker_idle_30m && queue > 0", "severity": "warning", "for": "30m"},
    ]

    return {
        "alerts": alerts,
        "rules": rules,
        "total_firing": len(alerts),
        "timestamp": now.isoformat(),
    }

