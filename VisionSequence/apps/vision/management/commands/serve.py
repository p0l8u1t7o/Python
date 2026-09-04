"""單一行程同時提供 HTTP API（uvicorn）、TCP 自動化介面與擷取端連入埠，引擎狀態共享。

    manage.py serve --host 0.0.0.0 --port 8000 --tcp-port 9000 --capture-port 9100

正式環境建議用這個而不是 runserver：uvicorn 以執行緒池處理同步 view，
SSE 串流不會占住整個伺服器。
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "以 uvicorn 提供 HTTP API 並啟動 TCP 介面（同一行程）"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=8000)
        parser.add_argument("--tcp-port", type=int, default=settings.VISION["TCP_PORT"])
        parser.add_argument("--no-tcp", action="store_true")
        parser.add_argument("--capture-port", type=int, default=settings.VISION["CAPTURE_PORT"], help="擷取端連入埠（相機電腦上的擷取程式）")
        parser.add_argument("--no-capture", action="store_true")
        parser.add_argument("--reload", action="store_true", help="開發用自動重載（狀態會遺失）")

    def handle(self, *args, **options):
        import uvicorn

        if not options["no_tcp"]:
            from apps.vision import tcp_server

            tcp_server.start_in_background(settings.VISION["TCP_HOST"], options["tcp_port"])
        if not options["no_capture"]:
            from apps.vision.capture import hub as capture_hub

            capture_hub.start_in_background(settings.VISION["CAPTURE_HOST"], options["capture_port"])
        uvicorn.run(
            "config.asgi:application",
            host=options["host"],
            port=options["port"],
            reload=options["reload"],
            log_level="info",
            workers=1,
        )
