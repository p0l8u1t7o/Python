"""檢測任務定義登錄表。"""

from __future__ import annotations

from apps.vision.tasks.base import EdgeSpec, FieldSpec, PortRef, TaskDefinition, all, get, register

# 匯入即註冊 v1 定義。
from apps.vision.tasks import definitions as definitions  # noqa: F401,E402

__all__ = ["EdgeSpec", "FieldSpec", "PortRef", "TaskDefinition", "all", "get", "register"]
