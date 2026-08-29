"""資料模型。

Flow：操作者畫的那張圖（整份 JSON 存一個欄位，編輯器整份存、引擎整份讀）。
FlowRun：一次執行的**摘要**記錄。影像不進資料庫；執行中的中間影像在記憶體快取
（apps.vision.images），前端用 ref 取。高速產線可用 VISION_PERSIST_RUNS=0 關掉。
ImageSource：影像來源（資料夾、單檔、USB 相機、合成、外掛）。
Asset：上傳的範本影像、ONNX 模型等檔案。
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Flow(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, default="")
    graph = models.JSONField(default=dict)
    #: 擁有者；null = 共用（示範流程、被刪除使用者留下的流程），管理員才能改。
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="flows")
    is_enabled = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    #: 連續模式的間隔（毫秒；0 = 盡快）。
    continuous_interval_ms = models.PositiveIntegerField(default=0)
    #: 現場教導完成（參數卡頁確認）；False 時 run 仍可執行，只在 RunReport 加 warnings。
    commissioned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class FlowRecipe(models.Model):
    """配方：同一流程的一組參數覆寫（多料號換線用）。param_overrides = {node_id: {param: value}}。"""

    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="recipes")
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, default="")
    param_overrides = models.JSONField(default=dict)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("flow", "name")]


RUN_STATUSES = ("ok", "ng", "failed", "cancelled")


class FlowRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="runs")
    flow_version = models.PositiveIntegerField()
    status = models.CharField(max_length=12)
    trigger = models.CharField(max_length=20, default="manual")  # manual | api | continuous | tcp | preview
    station_id = models.CharField(max_length=40, default="ST01")
    recipe = models.CharField(max_length=80, blank=True, default="")
    duration_ms = models.FloatField(default=0)
    #: 各節點摘要：{node_id: {status, duration_ms, message}}
    nodes = models.JSONField(default=dict)
    #: output 工具收集的具名輸出。
    outputs = models.JSONField(default=dict)
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["flow", "-started_at"]), models.Index(fields=["station_id", "-started_at"])]


SOURCE_KINDS = ("folder", "file", "usb", "synthetic", "upload", "plugin")


class ImageSource(models.Model):
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=20)
    #: 依 kind 不同：folder {path, loop, sort}；file {path}；usb {index, width, height, fps}；
    #: synthetic {width, height, pattern}；plugin {class, ...}
    config = models.JSONField(default=dict)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class FlowTemplate(models.Model):
    """自訂流程範本：圖裡的 image_source.source_id 存成 {SOURCE} 佔位符，載入時換成目標來源。"""

    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=40, default="custom")
    graph = models.JSONField(default=dict)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="flow_templates")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class Asset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20)  # image | model | file
    path = models.CharField(max_length=500)
    size = models.PositiveBigIntegerField(default=0)
    #: 影像資產的寬高，模型資產的輸入形狀等。
    meta = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
