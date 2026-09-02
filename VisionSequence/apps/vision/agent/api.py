"""AI 助手 API。

POST /vision/agent/image     上傳影像進快取 → {ref, width, height}
POST /vision/agent/generate  {ref, prompt, regions:[{region, hint?}], use_llm?} → {graph, rationale, provider, report}
POST /vision/agent/refine    {ref, prompt, regions, graph, feedback} → 同上
GET  /vision/agent/info      供應器狀態（LLM 是否可用、模型名）

生成／微調都會在上傳影像上實跑一遍（report 內含各節點影像 ref，前端直接顯示）。
執行類端點，鎖定時 423（與 run/preview 同一條規則）。
"""

from __future__ import annotations

import uuid
from typing import Any

from django.http import HttpRequest
from ninja import File, Router, Schema, UploadedFile

from apps.accounts.security import principal
from apps.core.errors import NotFound, ValidationError
from apps.vision.agent import llm, service
from apps.vision.api import _decode_upload
from apps.vision.images import store

router = Router(tags=["agent"])


class RegionIn(Schema):
    region: dict[str, Any]
    hint: str = ""


class GenerateIn(Schema):
    ref: str
    prompt: str = ""
    regions: list[RegionIn] = []
    #: None＝有設定 LLM 就用；False＝強制離線規則引擎。
    use_llm: bool | None = None


class RefineIn(Schema):
    ref: str
    prompt: str = ""
    regions: list[RegionIn] = []
    graph: dict[str, Any]
    feedback: str


@router.get("/agent/info")
def agent_info(request: HttpRequest):
    return {"llm": llm.available(), "model": llm.model_name() if llm.available() else "", "provider": "llm" if llm.available() else "rules"}


@router.post("/agent/image", response={201: dict})
def upload_agent_image(request: HttpRequest, image: UploadedFile = File(...)):
    principal(request).can_execute()
    frame = _decode_upload(image)
    run_id = f"agent{uuid.uuid4().hex[:12]}"
    info = store.put(f"{run_id}:upload:image", frame, flow_id=service.AGENT_FLOW_ID, run_id=run_id)
    return 201, {**info, "name": image.name}


def _image_or_404(ref: str):
    frame = store.get(ref)
    if frame is None:
        raise NotFound("影像已不在快取中，請重新上傳", code="image_gone")
    return frame


def _regions(payload: list[RegionIn]) -> list[dict[str, Any]]:
    return [{"region": r.region, "hint": r.hint} for r in payload]


@router.post("/agent/generate")
def agent_generate(request: HttpRequest, payload: GenerateIn):
    principal(request).can_execute()
    frame = _image_or_404(payload.ref)
    return service.generate(frame, _regions(payload.regions), payload.prompt, use_llm=payload.use_llm)


@router.post("/agent/refine")
def agent_refine(request: HttpRequest, payload: RefineIn):
    principal(request).can_execute()
    if not payload.feedback.strip():
        raise ValidationError("回饋不能是空的", code="empty_feedback")
    frame = _image_or_404(payload.ref)
    return service.refine(frame, _regions(payload.regions), payload.prompt, payload.graph, payload.feedback)
