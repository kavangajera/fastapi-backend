from __future__ import annotations

import os
import sys

from loguru import logger


def setup_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        backtrace=False,
        diagnose=False,
        colorize=True,
    )
