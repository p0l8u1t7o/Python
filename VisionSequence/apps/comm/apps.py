from __future__ import annotations

from django.apps import AppConfig


class CommConfig(AppConfig):
    name = "apps.comm"
    label = "comm"

    def ready(self) -> None:
        # 連線在 Runner 的 prefetch（呼叫者執行緒）預先開好；執行緒池內的工具只從快取拿。
        from apps.comm.writers import prefetch_connections
        from apps.vision.runner import Runner

        if prefetch_connections not in Runner.prefetch_hooks:
            Runner.prefetch_hooks.append(prefetch_connections)
