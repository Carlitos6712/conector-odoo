"""Structured JSON logging with redaction of sensitive values."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import IO, Any

REDACTED = "***"
_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "authorization",
    "signature",
    "token",
)
_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys() | {"message", "asctime"}
)


def _is_sensitive(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(marker in normalized for marker in _SENSITIVE_MARKERS)


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with sensitive mapping entries masked, recursively."""
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive(key) else redact(item) for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    return value


class RedactionFilter(logging.Filter):
    """Masks sensitive values in the ``extra`` fields attached to a log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in list(record.__dict__.items()):
            if key in _STANDARD_ATTRS:
                continue
            record.__dict__[key] = REDACTED if _is_sensitive(key) else redact(value)
        return True


class JsonFormatter(logging.Formatter):
    """Formats records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", stream: IO[str] | None = None) -> None:
    """Install a single JSON handler with redaction on the root logger."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
