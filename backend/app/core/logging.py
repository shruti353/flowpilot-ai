"""Structured console logging setup.

Every log record supports an optional `request_id` extra so log lines can be
correlated to a single agent run. Records without one fall back to "-".
"""

import logging
import sys

_CONFIGURED = False


class _RequestContextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return super().format(record)


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger exactly once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _RequestContextFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | request_id=%(request_id)s | %(message)s"
        )
    )

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers = [handler]

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
