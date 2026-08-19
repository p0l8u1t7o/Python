"""Tiny environment helper.

Deliberately dependency-light: reads a ``.env`` file once at import time and
exposes typed getters. Keeping this local avoids coupling the settings module
to any particular config library.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env", override=False)

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}


class ImproperlyConfigured(RuntimeError):
    pass


_UNSET = object()


def get(name: str, default=_UNSET) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        if default is _UNSET:
            raise ImproperlyConfigured(f"Missing required environment variable: {name}")
        return default
    return value


def get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean, got {raw!r}")


def get_int(name: str, default: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ImproperlyConfigured(f"Missing required environment variable: {name}")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {raw!r}") from exc


def get_float(name: str, default: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ImproperlyConfigured(f"Missing required environment variable: {name}")
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a float, got {raw!r}") from exc


def get_list(name: str, default: list[str] | None = None, sep: str = ",") -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return list(default or [])
    return [item.strip() for item in raw.split(sep) if item.strip()]
