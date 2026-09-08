"""工具套件。register_builtins() 在 AppConfig.ready() 呼叫，重複呼叫安全。"""

from __future__ import annotations

import importlib
import logging

from apps.vision.tools import base

log = logging.getLogger(__name__)

#: 內建工具模組；每個模組定義 TOOLS = [ToolInstance, ...]。
BUILTIN_MODULES = [
    "apps.vision.tools.builtin.source",
    "apps.vision.tools.builtin.fixed_image",
    "apps.vision.tools.builtin.preprocess",
    "apps.vision.tools.builtin.polar",
    "apps.vision.tools.builtin.photometric",
    "apps.vision.tools.builtin.locate",
    "apps.vision.tools.builtin.shape",
    "apps.vision.tools.builtin.region",
    "apps.vision.tools.builtin.measure",
    "apps.vision.tools.builtin.contours",
    "apps.vision.tools.builtin.gdt",
    "apps.vision.tools.builtin.circular",
    "apps.vision.tools.builtin.edge_defect",
    "apps.vision.tools.builtin.detect",
    "apps.vision.tools.builtin.barcode_grade",
    "apps.vision.tools.builtin.ocr_tools",
    "apps.vision.tools.builtin.stat",
    "apps.vision.tools.builtin.dl",
    "apps.vision.tools.builtin.anomaly_tool",
    "apps.vision.tools.builtin.yolo",
    "apps.vision.tools.builtin.logic",
    "apps.vision.tools.builtin.script",
    "apps.vision.tools.builtin.output",
    "apps.vision.tools.builtin.modbus",
]

_registered = False


def register_builtins() -> None:
    global _registered
    if _registered:
        return
    for name in BUILTIN_MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                log.warning("內建工具模組 %s 不存在，略過", name)
                continue
            raise
        for tool in getattr(module, "TOOLS", []):
            if not base.has(tool.key):
                base.register(tool)
    _registered = True


__all__ = ["base", "register_builtins"]
