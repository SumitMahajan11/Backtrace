"""Structured Logging Subsystem (Layer 11 Infrastructure).

Provides structured, JSON-formatted logging correlated across all 11 layers by a contextual run_id.
"""

import json
import logging
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Context variable holding the active pipeline run_id
current_run_id: ContextVar[str] = ContextVar("current_run_id", default="")


def set_run_id(run_id: str) -> None:
    """Sets the active run_id in the current context."""
    current_run_id.set(run_id)


def get_run_id() -> str:
    """Retrieves the active run_id from context, or empty string."""
    return current_run_id.get()


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects with correlated run_id."""

    def format(self, record: logging.LogRecord) -> str:
        run_id = getattr(record, "run_id", None) or get_run_id() or "none"
        layer = getattr(record, "layer", "system")
        details = getattr(record, "details", {})

        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": run_id,
            "layer": layer,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if details:
            log_data["details"] = details
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def get_logger(name: str, layer: str = "orchestration") -> logging.Logger:
    """Creates or returns a logger configured with structured output and layer metadata."""
    logger = logging.getLogger(f"reverse.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger

