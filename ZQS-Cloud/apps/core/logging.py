"""Structured logging helpers.

The MQTT ingestor and the queue workers are long-running processes whose logs
usually end up in a log aggregator, so JSON output is a first-class option.
"""

from __future__ import annotations

import datetime as dt
import logging
import traceback

import orjson

_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    """Renders one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": dt.datetime.fromtimestamp(
                record.created, tz=dt.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            ).strip()
        return orjson.dumps(payload, default=str).decode()


def get_logger(name: str) -> logging.Logger:
    """All project loggers hang off the ``zqs`` root for level control."""
    return logging.getLogger(name if name.startswith("zqs") else f"zqs.{name}")
