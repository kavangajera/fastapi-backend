from __future__ import annotations

import os
import sys

from loguru import logger


def setup_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_dir = os.getenv("LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        backtrace=False,
        diagnose=False,
        colorize=True,
    )
    logger.add(
        os.path.join(log_dir, "app_{time:YYYYMMDD_HHmmss}.log"),
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        backtrace=False,
        diagnose=False,
        enqueue=True,
    )

    # In-memory ring buffer for the dashboard log stream (no DB tracking)
    from core.log_buffer import log_buffer
    logger.add(
        log_buffer.sink,
        level="DEBUG",
        format="{message}",
        backtrace=False,
        diagnose=False,
    )
