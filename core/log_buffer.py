"""
core/log_buffer.py
──────────────────
In-memory ring buffer that captures loguru log entries for the dashboard.
No database writes — purely ephemeral.
"""

from __future__ import annotations

import threading
from collections import deque


class LogBuffer:
    """Thread-safe ring buffer for log entries."""

    def __init__(self, max_size: int = 500):
        self._buffer: deque[dict] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._counter = 0

    def sink(self, message) -> None:
        """Loguru sink function — add to `logger.add(log_buffer.sink)`."""
        record = message.record
        entry = {
            "id": self._counter,
            "timestamp": record["time"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "level": record["level"].name,
            "message": str(record["message"]),
            "module": record.get("module", ""),
            "function": record.get("function", ""),
            "line": record.get("line", 0),
        }
        with self._lock:
            self._counter += 1
            entry["id"] = self._counter
            self._buffer.append(entry)

    def get_logs(self, limit: int = 100, level: str | None = None) -> list[dict]:
        """Return recent logs, optionally filtered by level."""
        with self._lock:
            logs = list(self._buffer)

        if level:
            level_upper = level.upper()
            logs = [l for l in logs if l["level"] == level_upper]

        return logs[-limit:]


# Global singleton
log_buffer = LogBuffer()
