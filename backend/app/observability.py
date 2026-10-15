"""Structured logging helpers for production observability."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line with stable event fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("event", "request_id", "candidate_id", "package_id", "ticket_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(*, debug: bool = False) -> None:
    """Configure root logging once at process start.

    Args:
        debug: When True, use human-readable text logs; otherwise JSON lines.
    """
    root = logging.getLogger()
    if getattr(root, "_assess_pulse_configured", False):
        return
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    if debug:
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root._assess_pulse_configured = True  # type: ignore[attr-defined]
