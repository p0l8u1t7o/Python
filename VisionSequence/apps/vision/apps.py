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
        from apps.vision.tools import accel

        accel.configure(str(settings.VISION.get("ACCEL", "auto")), int(settings.VISION.get("ACCEL_MIN_PIXELS", accel.DEFAULT_MIN_PIXELS)))

        from apps.vision.tools import register_builtins

        register_builtins()
        for module in settings.VISION.get("TOOL_PLUGINS", []):
            try:
                importlib.import_module(module)
                log.info("已載入工具外掛 %s", module)
            except Exception:  # noqa: BLE001
                log.exception("工具外掛 %s 載入失敗", module)

        # 深度學習教導：內建 trainer 與裝置設定（外掛 trainer 由資料夾外掛掛載）。
        from apps.vision.dl import base as dl_base, devices

        dl_base.register_builtins()
        devices.load_settings()

        # 資料夾外掛：plugins/ 下的 .py 自動偵測（工具／影像來源／整合連線／trainer）。
        from apps.core.plugins import load_folder_plugins

        load_folder_plugins()
