"""
Structured JSON logging configuration.
All log output is JSON-formatted for ingestion by Loki/CloudWatch/Datadog.
"""
import logging
import sys
import json
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra"):
            log_obj.update(record.extra)
        return json.dumps(log_obj, default=str)


def configure_logging(level: str = "INFO") -> None:
    """
    Configure root logger with JSON formatter on stdout.
    Call once at process startup.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ["httpx", "httpcore", "asyncio", "urllib3", "praw"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)
