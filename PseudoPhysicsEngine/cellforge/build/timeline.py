"""Load a project's sequence.py through the restricted sequence API."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from cellforge.schema.models import Process

from . import seq


def expand_sequence(path: Path, process: Process) -> dict:
    spec = importlib.util.spec_from_file_location("cellforge_project_sequence", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"無法載入動畫腳本：{path}")
    module = importlib.util.module_from_spec(spec)
    builder = seq.SequenceBuilder(process)
    token = seq._active.set(builder)
    try:
        spec.loader.exec_module(module)
        entrypoint = getattr(module, "build", None)
        if not callable(entrypoint):
            raise ValueError("animation/sequence.py 必須提供 build()")
        entrypoint()
    finally:
        seq._active.reset(token)
    return builder.timeline()
