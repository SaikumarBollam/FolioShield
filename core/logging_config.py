"""
Structured Logging, Correlation Filtering, and PII/Secret Masking for FolioShield.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Regex patterns for sensitive data redaction
_PAN_REGEX = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
_BEARER_REGEX = re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.~+/]+=*")
_PASSWORD_REGEX = re.compile(r"(?i)(password|secret|api_key|token)[\"']?\s*[:=]\s*[\"']?([^\"'\s,]+)")


class SensitiveDataFilter(logging.Filter):
    """
    Log filter that redacts payment card numbers, authorization tokens,
    and passwords/secrets before log records are emitted.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            # Redact payment card PANs
            msg = _PAN_REGEX.sub("[REDACTED_PAN]", msg)
            # Redact Bearer tokens
            msg = _BEARER_REGEX.sub("Bearer [REDACTED_TOKEN]", msg)
            # Redact secrets in JSON/key-value logs
            msg = _PASSWORD_REGEX.sub(r'\1: "[REDACTED_SECRET]"', msg)
            record.msg = msg
        return True


class JSONLogFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects with ISO8601 timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Request correlation ID
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id

        # Exception information
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


def configure_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None,
) -> None:
    """Configures application-wide logging with sensitivity filtering."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    formatter: logging.Formatter
    if json_format:
        formatter = JSONLogFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(console_handler)

    # File Handler
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(file_handler)
