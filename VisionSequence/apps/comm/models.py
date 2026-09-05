"""通訊連線：主動輸出到 Modbus TCP 設備／上位機的目的地（仿 ImageSource 的模式，一列一條連線）。

kind 的封閉集合在 `apps.comm.writers._BUILTIN`（外掛另外註冊），建立時由 `writers._resolve_class` 把關。"""

from __future__ import annotations

from django.db import models

class Connection(models.Model):
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=20)
    #: 依 kind 不同：modbus_tcp {host, port, unit_id, timeout_s, word_order}；
    #: tcp_client {host, port, timeout_s, template|format, newline, encoding, wait_reply}；
    #: modbus_server {host, port, unit_id, size, word_order}；plugin {class, ...}
    config = models.JSONField(default=dict)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
