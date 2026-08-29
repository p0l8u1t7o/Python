"""獨立行程的 TCP 介面（僅供測試；正式環境請用 `serve` 命令讓 HTTP 與 TCP 共用引擎）。"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.vision import tcp_server


class Command(BaseCommand):
    help = "啟動 TCP 自動化介面（與 HTTP API 分開的行程；引擎狀態不共享）"

    def add_arguments(self, parser):
        parser.add_argument("--host", default=settings.VISION["TCP_HOST"])
        parser.add_argument("--port", type=int, default=settings.VISION["TCP_PORT"])

    def handle(self, *args, **options):
        tcp_server.start_in_background(options["host"], options["port"])
        self.stdout.write(f"TCP 介面 {options['host']}:{options['port']}，Ctrl+C 結束")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            tcp_server.stop()
