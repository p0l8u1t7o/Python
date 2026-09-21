"""Comment-preserving YAML helpers."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML(typ="rt")
_yaml.preserve_quotes = True
_yaml_lock = RLock()


def load_yaml(path: Path) -> Any:
    with _yaml_lock, path.open("r", encoding="utf-8") as handle:
        return _yaml.load(handle)


def dump_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _yaml_lock, path.open("w", encoding="utf-8") as handle:
        _yaml.dump(value, handle)
