"""AI 助手 API。

GET   /vision/agent/info       目前生效的供應商（使用者設定優先，否則伺服器設定；不含金鑰）
GET   /vision/agent/settings   登入使用者自己的供應商設定（金鑰只回尾碼）
PATCH /vision/agent/settings   {provider, model?, api_key?, clear_key?}
POST  /vision/agent/image      上傳影像進快取 → {ref, width, height}
POST  /vision/agent/clarify    {images, prompt, regions, answers?} → {ready, questions[], summary, intent}
POST  /vision/agent/generate   {images:[ref], prompt, regions:[{region, hint?, image?}], use_llm?, answers?}
                               → {graph, rationale, provider, intent, report, reports, main_image}
POST  /vision/agent/refine     {images, prompt, regions, graph, feedback} → 同上
POST  /vision/agent/edit       {graph, instruction, image_ref?} → {graph, rationale, changes, report?, applied}
POST  /vision/agent/tune       {graph, instruction, runs:[{name, image_ref, status, outputs}]} → 前後對比

生成／微調都會在上傳影像上實跑一遍（report 內含各節點影像 ref，前端直接顯示）。
執行類端點，鎖定時 423（與 run/preview 同一條規則）。
"""

from __future__ import annotations

import uuid
from typing import Any

from django.http import HttpRequest
from ninja import File, Router, Schema, UploadedFile

from apps.accounts.models import UserPref
from apps.accounts.security import principal
from apps.core.errors import NotFound, ValidationError
from apps.vision.agent import providers, service, skills
from apps.vision.api import _decode_upload
from apps.vision.images import store

router = Router(tags=["agent"])


class RegionIn(Schema):
    region: dict[str, Any]
    hint: str = ""
    #: 屬於第幾張影像（0 起算）。
    image: int = 0


class GenerateIn(Schema):
    #: 舊欄位（單張）；images 有值時忽略。
    ref: str = ""
    images: list[str] = []
    prompt: str = ""
    regions: list[RegionIn] = []
    #: None＝有設定 LLM 就用；False＝強制離線規則引擎。
    use_llm: bool | None = None
    #: 詢問機制的回答 [{id, answer}]；會併進提示詞。
    answers: list[dict[str, Any]] = []


class RefineIn(GenerateIn):
    graph: dict[str, Any]
    feedback: str


class EditIn(Schema):
    graph: dict[str, Any]
    instruction: str
    image_ref: str = ""


class RunIn(Schema):
    name: str = ""
    image_ref: str = ""
    status: str = ""
    outputs: dict[str, Any] = {}
    expected: str = ""


class TuneIn(Schema):
    graph: dict[str, Any]
    instruction: str
    runs: list[RunIn] = []


class SettingsIn(Schema):
    provider: str
    model: str | None = None
    api_key: str | None = None
    clear_key: bool = False


def _settings_for(request: HttpRequest) -> providers.AgentSettings:
    return providers.resolve(principal(request).user)


@router.get("/agent/info")
def agent_info(request: HttpRequest):
    s = _settings_for(request)
    return {**s.public(), "reason": providers.missing_reason(s),
            "providers": [{"value": p, "label": providers.PROVIDER_LABELS[p], "default_model": providers.DEFAULT_MODELS.get(p, "")} for p in providers.PROVIDERS]}


@router.get("/agent/settings")
def get_agent_settings(request: HttpRequest):
    p = principal(request)
    if p.user is None:
        raise ValidationError("整合方金鑰沒有使用者設定", code="no_user")
    mine = providers.user_settings(p.user)
    return {"configured": mine is not None, **(mine or providers.AgentSettings()).public(), "server": providers.server_settings().public()}


@router.patch("/agent/settings")
def patch_agent_settings(request: HttpRequest, payload: SettingsIn):
    p = principal(request)
    if p.user is None:
        raise ValidationError("整合方金鑰沒有使用者設定", code="no_user")
    if payload.provider not in providers.PROVIDERS:
        raise ValidationError(f"未知的供應商 '{payload.provider}'", code="bad_provider", details={"available": list(providers.PROVIDERS)})
    row, _ = UserPref.objects.get_or_create(user=p.user)
    data = dict(row.agent or {})
    data["provider"] = payload.provider
    if payload.model is not None:
        data["model"] = payload.model.strip()
    if payload.clear_key:
        data["api_key"] = ""
    elif payload.api_key:
        data["api_key"] = payload.api_key.strip()
    row.agent = data
    row.save(update_fields=["agent", "updated_at"])
    mine = providers.user_settings(p.user) or providers.AgentSettings()
    return {"configured": True, **mine.public(), "reason": providers.missing_reason(mine)}


@router.get("/agent/skills")
def list_agent_skills(request: HttpRequest):
    """AI 代理技能清單：平台規則、設計原則、每個工具的使用要領（給人看，也是 LLM 讀的同一份）。"""
    return {"items": skills.list_skills()}


@router.get("/agent/skills/{key}")
def get_agent_skill(request: HttpRequest, key: str):
    try:
        return {"key": key, "markdown": skills.skill_text(key)}
    except KeyError:
        raise NotFound(f"沒有 '{key}' 這個技能", code="skill_not_found") from None


@router.post("/agent/settings/models")
def list_agent_models(request: HttpRequest):
    """用目前生效的設定列出金鑰可用的模型名（先儲存供應商與金鑰再按）。"""
    return providers.list_models(_settings_for(request))


@router.post("/agent/settings/test")
def test_agent_settings(request: HttpRequest):
    """用目前生效的設定打一個最小請求，回成功與否＋失敗原因（金鑰錯、缺套件、模型名錯、網路）。"""
    return providers.test_connection(_settings_for(request))


@router.post("/agent/image", response={201: dict})
def upload_agent_image(request: HttpRequest, image: UploadedFile = File(...)):
    principal(request).can_execute()
    frame = _decode_upload(image)
    run_id = f"agent{uuid.uuid4().hex[:12]}"
    info = store.put(f"{run_id}:upload:image", frame, flow_id=service.AGENT_FLOW_ID, run_id=run_id, pinned=True)
    return 201, {**info, "name": image.name}


def _image_or_404(ref: str):
    frame = store.get(ref)
    if frame is None:
        raise NotFound("影像已不在快取中，請重新上傳", code="image_gone")
    return frame


def _images(payload: GenerateIn):
    refs = payload.images or ([payload.ref] if payload.ref else [])
    if not refs:
        raise ValidationError("至少要一張影像", code="no_image")
    return [_image_or_404(r) for r in refs]


def _regions(payload: list[RegionIn]) -> list[dict[str, Any]]:
    return [{"region": r.region, "hint": r.hint, "image": r.image} for r in payload]


@router.post("/agent/clarify")
def agent_clarify(request: HttpRequest, payload: GenerateIn):
    """生成前的確認：回 ready 或最多 3 個問題（規則或 LLM）。不執行流程。"""
    principal(request).can_execute()
    return service.clarify(_images(payload), _regions(payload.regions), payload.prompt, payload.answers, _settings_for(request))


@router.post("/agent/generate")
def agent_generate(request: HttpRequest, payload: GenerateIn):
    principal(request).can_execute()
    return service.generate(_images(payload), _regions(payload.regions), payload.prompt, _settings_for(request), use_llm=payload.use_llm, answers=payload.answers)


@router.post("/agent/refine")
def agent_refine(request: HttpRequest, payload: RefineIn):
    principal(request).can_execute()
    if not payload.feedback.strip():
        raise ValidationError("回饋不能是空的", code="empty_feedback")
    return service.refine(_images(payload), _regions(payload.regions), payload.prompt, payload.graph, payload.feedback, _settings_for(request))


@router.post("/agent/edit")
def agent_edit(request: HttpRequest, payload: EditIn):
    principal(request).can_execute()
    if not payload.instruction.strip():
        raise ValidationError("指令不能是空的", code="empty_instruction")
    image = store.get(payload.image_ref) if payload.image_ref else None
    return service.edit(payload.graph, payload.instruction, image, _settings_for(request))


@router.post("/agent/tune")
def agent_tune(request: HttpRequest, payload: TuneIn):
    principal(request).can_execute()
    if not payload.instruction.strip():
        raise ValidationError("指令不能是空的", code="empty_instruction")
    runs = [r.dict() for r in payload.runs]
    images = {r["image_ref"]: store.get(r["image_ref"]) for r in runs if r.get("image_ref")}
    images = {k: v for k, v in images.items() if v is not None}
    return service.tune(payload.graph, payload.instruction, runs, images, _settings_for(request))
