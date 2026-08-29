from __future__ import annotations

import importlib
import logging

from django.apps import AppConfig
from django.conf import settings

log = logging.getLogger(__name__)


class VisionConfig(AppConfig):
    name = "apps.vision"
    label = "vision"

    def ready(self) -> None:
        import cv2

        threads = settings.VISION.get("CV_THREADS", 0)
        if threads:
            cv2.setNumThreads(int(threads))

        from apps.vision.tools import register_builtins

        register_builtins()
        for module in settings.VISION.get("TOOL_PLUGINS", []):
            try:
                importlib.import_module(module)
                log.info("已載入工具外掛 %s", module)
            except Exception:  # noqa: BLE001
                log.exception("工具外掛 %s 載入失敗", module)
