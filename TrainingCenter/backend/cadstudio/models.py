import uuid

from django.db import models


class CadJob(models.Model):
    """CAD Studio 的一次產生：描述 →（Claude 產生 build123d 程式）→ cadgen 建置 → STEP/GLB。"""

    class Mode(models.TextChoices):
        AI = "ai", "AI 產碼"
        CODE = "code", "直接執行程式"

    class Status(models.TextChoices):
        QUEUED = "queued", "排隊中"
        GENERATING = "generating", "AI 產生程式中"
        BUILDING = "building", "建置 CAD 中"
        DONE = "done", "完成"
        FAILED = "failed", "失敗"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.AI)
    prompt = models.TextField(blank=True)
    name = models.CharField(max_length=120, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="revisions")
    code = models.TextField(blank=True, help_text="build123d 產生器程式（定義 gen_step()）")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    log = models.TextField(blank=True)
    error = models.TextField(blank=True)
    ai_notes = models.TextField(blank=True, help_text="AI 的說明與假設")
    # 產出檔（相對 MEDIA_ROOT）
    glb = models.CharField(max_length=300, blank=True)
    step = models.CharField(max_length=300, blank=True)
    stl = models.CharField(max_length=300, blank=True)
    three_mf = models.CharField(max_length=300, blank=True)
    snapshot = models.CharField(max_length=300, blank=True)
    facts = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name or self.prompt[:30]} [{self.status}]"

    @property
    def job_dir_rel(self) -> str:
        return f"cadstudio/{self.id}"
