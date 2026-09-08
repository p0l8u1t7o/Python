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


class StationRules(models.Model):
    """單列（id=1）：站台層的接收規則（`apps/comm/rules.py` 的文字規則）。

    TCP 指令埠收到「不是指令」的一行時比對這一張表——條碼槍直接把料號送進來、
    上位機送一行自訂訊息，都是這一種。規則屬於這一台站台而不是某條連線，
    因為指令埠是站台開的，不是誰連出去的。
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    rules = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "station rules"
