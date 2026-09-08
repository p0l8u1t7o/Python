"""單一行程同時提供 HTTP API（uvicorn）、TCP 自動化介面與擷取端連入埠，引擎狀態共享。

    manage.py serve --host 0.0.0.0 --port 8000 --tcp-port 9000 --capture-port 9100 [--pid-file data/run/serve.pid]

正式環境建議用這個而不是 runserver：uvicorn 以執行緒池處理同步 view，
SSE 串流不會占住整個伺服器。服務管理員（NSSM）送 Ctrl-C 時 uvicorn 走正常關閉，最多等 10 秒讓 SSE 長連線收尾。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


def _log_config() -> dict:
    """uvicorn 的預設日誌設定＋access log 遮罩（token／api_key 不進 service.log）。"""
    import uvicorn.config

    cfg = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    cfg.setdefault("filters", {})["redact"] = {"()": "apps.core.logfilter.RedactSecrets"}
    for name in ("access", "default"):
        handler = cfg["handlers"].get(name)
        if handler is not None:
            handler["filters"] = list(handler.get("filters", [])) + ["redact"]
    return cfg


class Command(BaseCommand):
    help = "以 uvicorn 提供 HTTP API 並啟動 TCP 介面（同一行程）"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=settings.VISION.get("HTTP_PORT", 8000))
        parser.add_argument("--pid-file", default="", help="啟動時寫入本行程 PID（vsctl status／stop 用），結束時刪除")
        parser.add_argument("--tcp-port", type=int, default=settings.VISION["TCP_PORT"])
        parser.add_argument("--no-tcp", action="store_true")
        parser.add_argument("--capture-port", type=int, default=settings.VISION["CAPTURE_PORT"], help="擷取端連入埠（相機電腦上的擷取程式）")
        parser.add_argument("--no-capture", action="store_true")
        parser.add_argument("--no-comm", action="store_true", help="不自動開啟 Modbus 從站與觸發輪詢")
        parser.add_argument("--reload", action="store_true", help="開發用自動重載（狀態會遺失）")

    def handle(self, *args, **options):
        import uvicorn

        pid_file = Path(options["pid_file"]) if options["pid_file"] else None
        if pid_file is not None:
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(os.getpid()), encoding="ascii")
        if not options["no_tcp"]:
            from apps.vision import tcp_server

            tcp_server.start_in_background(settings.VISION["TCP_HOST"], options["tcp_port"])
        if not options["no_capture"]:
            from apps.vision.capture import hub as capture_hub

            capture_hub.start_in_background(settings.VISION["CAPTURE_HOST"], options["capture_port"])
        if not options["no_comm"]:
            from apps.comm import writers

            # 從站要一直在聽（PLC 隨時會連），設了觸發位址的連線要開始輪詢；
            # 以前得等有人按「測試」或流程跑過一次才開埠，伺服器重開後 PLC 就連不上。
            writers.autostart()
        # 持久化執行緒同時是維護執行緒：沒有任何 run 的站台也要清過期資料（只有 serve 打開，測試與 CLI 不做）
        from apps.vision import __version__, retention
        from apps.vision.runner import bus, persister

        retention.enable_background()
        persister.ensure()
        # 站台就緒：TCP、擷取端埠與連線都起來了，HTTP 接著開。設備端要「平台重開了」這個訊號
        # （PLC 常在斷電重開後要重送料號與配方），所以發成事件讓連線層的事件回報看得到。
        bus.publish({"type": "server_ready", "station_id": str(settings.VISION.get("STATION_ID", "")), "version": __version__})
        try:
            uvicorn.run(
                "config.asgi:application",
                host=options["host"],
                port=options["port"],
                reload=options["reload"],
                log_level="info",
                log_config=_log_config(),
                workers=1,
                timeout_graceful_shutdown=10,
            )
        finally:
            if pid_file is not None:
                pid_file.unlink(missing_ok=True)
