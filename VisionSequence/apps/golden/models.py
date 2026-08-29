"""Golden Set：帶期望值的回歸影像集，與每條流程的上次基準結果。

GoldenCase 影像存在 settings.VISION["ASSET_DIR"]/golden/<flow_id>/<uuid>.png（不進 ImageStore，回歸時直接從路徑讀）。
GoldenBaseline.results = {case_id: {status, outputs, duration_ms}}，每次 save_baseline 新增一列，取最新的當基準。
"""

from __future__ import annotations

from django.db import models

from apps.vision.models import Flow

EXPECT_STATUSES = ("ok", "ng", "any")


class GoldenCase(models.Model):
    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="golden_cases")
    name = models.CharField(max_length=200)
    image_path = models.CharField(max_length=500)
    #: ok | ng | any（any = 不比對狀態，只比對 expect_outputs）
    expect_status = models.CharField(max_length=8, default="any")
    #: {key: value} 或 {key: {"value": v, "tol": t}}（數值容差）
    expect_outputs = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.flow_id}:{self.name}"


class GoldenBaseline(models.Model):
    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="golden_baselines")
    flow_version = models.PositiveIntegerField()
    results = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @classmethod
    def latest_for(cls, flow_id: int) -> "GoldenBaseline | None":
        return cls.objects.filter(flow_id=flow_id).order_by("-created_at", "-id").first()
