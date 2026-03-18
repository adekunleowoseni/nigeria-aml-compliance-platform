from __future__ import annotations

import logging
import sys
from typing import Any

try:
    import structlog
except Exception:  # pragma: no cover
    structlog = None  # type: ignore


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    if structlog:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )


def get_logger(**kwargs: Any):
    if structlog:
        return structlog.get_logger().bind(**kwargs)
    base = logging.getLogger("aml")
    return logging.LoggerAdapter(base, extra=kwargs)

