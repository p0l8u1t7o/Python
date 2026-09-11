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
POST  /vision/agent/run        {images, graph, main?} → {graph, report, reports, main_image}（切換候選方案）
POST  /vision/agent/autotune   {graph, runs:[{name, image_ref, status, expected}], max_evals?, deadline_s?} → 同 tune ＋ autotune 摘要
                               tune／autotune／jobs(task=tune) 可改帶 batch_run_id（持久化批次），結果落成新 BatchRun（回應 batch_run_id）
POST  /vision/agent/consult    {batch_run_id, question, graph?} → {answer, provider, insights, suggestions[], warnings}
POST  /vision/agent/chat       全域助手 {message, mode, context{kind, flow_id, node_type, batch_run_id, image_ref, graph}, history} → {kind: help|edit|consult|tune, answer, …}
GET   /vision/agent/help/search?q=  說明索引檢索
POST  /vision/agent/jobs       代理模式背景工作 {task, images, prompt, regions, answers, labels, graph?, instruction?, runs?} → 202 {id, status, steps…}
GET   /vision/agent/jobs[/{id}?step_from=]、POST /jobs/{id}/cancel、POST /jobs/{id}/answer {answers}
GET   /vision/agent/sessions[/{id}]、PATCH /sessions/{id} {rating, success, note, flow_id}、POST /sessions/{id}/restore、DELETE
GET   /vision/agent/skills/custom、PUT /skills/custom/{key} {markdown, scope}、DELETE /skills/custom/{key}?scope=
POST  /vision/agent/tune       {graph, instruction, runs:[{name, image_ref, status, outputs}]} → 前後對比

生成／微調都會在上傳影像上實跑一遍（report 內含各節點影像 ref，前端直接顯示）。
執行類端點，鎖定時 423（與 run/preview 同一條規則）。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from typing import Any, Literal

from django.http import HttpRequest
from django.utils import timezone
from ninja import File, Router, Schema, UploadedFile

from apps.accounts.models import UserPref
from apps.accounts.security import principal, require_feature
from apps.core import audit
from apps.core.errors import NotFound, ValidationError
from apps.vision.agent import actions, chats, consult as consult_mod
from apps.vision.agent import help as help_mod
from apps.vision.agent import jobs, loop, memory, notes, providers, service, situation, skills, tasklist
from apps.vision.models import AgentSession, AgentSkill, Flow
from apps.vision.api import _decode_upload
from apps.vision.images import store

router = Router(tags=["agent"])


class RegionIn(Schema):
    region: dict[str, Any]
    hint: str = ""
    #: 屬於第幾張影像（0 起算）。
    image: int = 0


class ImageLabelIn(Schema):
    expected: Literal["", "ok", "ng"] = ""
    group: Literal["tune", "accept"] = "tune"


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
    #: 每張影像的期望判定（"ok"／"ng"／""，與 images 對齊）；用來排名候選方案與自動調參。
    labels: list[str | ImageLabelIn] = []
    groups: list[Literal["tune", "accept"]] = []


class RunGraphIn(Schema):
    images: list[str] = []
    ref: str = ""
    graph: dict[str, Any]
    main: int = 0


class AutotuneIn(Schema):
    graph: dict[str, Any] | None = None
    runs: list["RunIn"] = []
    max_evals: int = 60
    deadline_s: float = 25.0
    #: 持久化批次：影像與逐張資料從 BatchRun 取（graph 缺省＝該次執行的 graph）
    batch_run_id: int | None = None


class ConsultIn(Schema):
    batch_run_id: int
    question: str
    graph: dict[str, Any] | None = None


class ChatContext(Schema):
    #: page | flow_editor | tool | batch | golden | agent | dl | sources | assets | dashboard
    kind: str = "page"
    route: str = ""
    flow_id: int | None = None
    flow_name: str = ""
    node_id: str = ""
    node_type: str = ""
    batch_run_id: int | None = None
    image_ref: str = ""
    graph: dict[str, Any] | None = None
    #: 介面語言（en / zh-Hant / zh-Hans）
    lang: str = ""
    #: 頁面現況快照（選取、上次執行、未儲存…；由頁面 describe() 與 DOM 快照組成）
    page: dict[str, Any] | None = None
    #: 操作軌跡（最近的換頁、錯誤、執行結果）
    activity: list[dict[str, Any]] = []
    #: 使用者主動附上的畫面文字摘要
    screen: str = ""
    #: 使用者主動附上的截圖（jpeg base64 或 data URL；只有 LLM 看得到）
    screenshot: str = ""


class ChatIn(Schema):
    chat_id: int | None = None
    message: str
    #: auto | help | edit | consult | tune
    mode: str = "auto"
    context: ChatContext = ChatContext()
    history: list[dict[str, Any]] = []


class TaskListProposeIn(Schema):
    message: str
    graph: dict[str, Any]
    flow_id: int | None = None
    image_ref: str = ""
    history: list[dict[str, Any]] = []
    lang: str = "en"


class TaskListApplyIn(Schema):
    chat_id: int | None = None
    flow_id: int | None = None
    graph: dict[str, Any]
    drafts: list[dict[str, Any]]
    confirmations: dict[str, Any] = {}


@router.post("/agent/tasklist/propose")
def propose_tasklist(request: HttpRequest, payload: TaskListProposeIn):
    require_feature(request, "agent")
    if not payload.message.strip():
        raise ValidationError("The message cannot be empty", code="empty_message")
    return tasklist.propose(payload.message, payload.lang, payload.graph, _settings_for(request),
                            image=store.get(payload.image_ref) if payload.image_ref else None, history=payload.history)


@router.post("/agent/tasklist/apply")
def apply_tasklist(request: HttpRequest, payload: TaskListApplyIn):
    require_feature(request, "agent")
    require_feature(request, "flows.edit")
    row = _chat_for(request, payload.chat_id, payload.flow_id)
    result = tasklist.apply(payload.graph, payload.drafts, payload.confirmations)
    if result["applied"]:
        drafts = [d for d in (row.work_state.get("drafts", []) if row else []) if d.get("draft_id") not in result["applied"]]
        questions = [q for q in (row.work_state.get("pending_questions", []) if row else []) if not any(q.get("id", "").startswith(f"{item}:") for item in result["applied"])]
        assumptions = [{"task_id": d.get("task_id", ""), "field": key, "value": v.get("value"), "note": v.get("note", "")}
                       for d in drafts for key, v in d["fields"].items() if v["status"] == "assumed"]
        chats.record(row, {"drafts": drafts, "pending_questions": questions, "assumptions": assumptions}, "Confirmed task proposals applied to the draft flow.")
    return result


class MemoryIn(Schema):
    text: str


class ChatSaveIn(Schema):
    """整條對話覆寫：messages 是前端的 ChatMessage 陣列，title 省略＝由第一句話取。"""

    messages: list[dict] | None = None
    title: str | None = None
    flow_id: int | None = None
    work_state: dict[str, Any] | None = None


class RateIn(Schema):
    #: -1 / 0 / 1
    rating: int


MAX_SCREENSHOT_B64 = 4 * 1024 * 1024


def _screenshot_b64(raw: str) -> str:
    """data URL 或純 base64 → 純 base64；只收 JPEG、4 MB 以內，不合就 422。"""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("data:"):
        if "," not in raw:
            raise ValidationError("Bad screenshot data URL", code="screenshot_invalid")
        raw = raw.split(",", 1)[1]
    if len(raw) > MAX_SCREENSHOT_B64:
        raise ValidationError("Screenshot is too large (max 4 MB)", code="screenshot_too_large")
    try:
        head = base64.b64decode(raw, validate=True)[:3]
    except (ValueError, binascii.Error):
        raise ValidationError("Screenshot is not valid base64", code="screenshot_invalid") from None
    if head != b"\xff\xd8\xff":
        raise ValidationError("Screenshot must be a JPEG", code="screenshot_invalid")
    return raw


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
    group: Literal["tune", "accept"] = "tune"
    expect_outputs: dict[str, Any] = {}


class TuneIn(Schema):
    graph: dict[str, Any] | None = None
    instruction: str
    runs: list[RunIn] = []
    batch_run_id: int | None = None


class ProbeIn(Schema):
    """列模型／測試連線要用的設定：欄位留空就用目前生效的那組，填了就用畫面上還沒儲存的（先試再存）。"""

    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


class SettingsIn(Schema):
    provider: str
    model: str | None = None
    api_key: str | None = None
    #: openai_compatible 的端點（例如 http://127.0.0.1:11434/v1）。
    base_url: str | None = None
    #: single | agentic。
    mode: str | None = None
    clear_key: bool = False


class SaveToolIn(Schema):
    """助手產出的流程封裝成複合工具＋一條用它的流程（PRODUCT-DIRECTION v2 P4）。"""
    graph: dict[str, Any]
    key: str
    label: str
    description: str = ""
    category: str = "detect"
    flow_name: str = ""
    session_id: int | None = None


class JobIn(GenerateIn):
    chat_id: int | None = None
    flow_id: int | None = None
    expected_updated_at: str = ""
    task: str = "generate"
    graph: dict[str, Any] | None = None
    instruction: str = ""
    runs: list["RunIn"] = []
    batch_run_id: int | None = None
    max_turns: int = 12
    max_trials: int = 8
    deadline_s: float = 240.0


class AnswerIn(Schema):
    answers: list[dict[str, Any]] = []


class CustomSkillIn(Schema):
    markdown: str
    scope: str = "user"


class SessionPatch(Schema):
    rating: int | None = None
    success: bool | None = None
    note: str | None = None
    flow_id: int | None = None
    lessons: dict[str, Any] | None = None


def _settings_for(request: HttpRequest) -> providers.AgentSettings:
    return providers.resolve(principal(request).user)


def _probe_settings(request: HttpRequest) -> providers.AgentSettings:
    """把畫面上的供應商設定（JSON body，可省略）疊到目前生效的設定上，沒填的欄位才沿用已儲存的。
    **換了供應商又沒填金鑰時不沿用舊金鑰**：那把金鑰是別家的，拿去打只會得到看不懂的 401。
    body 自己讀不走 ninja schema：這兩個端點在畫面上「不帶 body」也要能打（沿用已儲存的設定）。"""
    payload = ProbeIn()
    if request.content_type and request.content_type.startswith("application/json") and request.body:
        try:
            raw = json.loads(request.body)
        except ValueError:
            raise ValidationError("Body is not valid JSON", code="bad_json") from None
        if isinstance(raw, dict):
            payload = ProbeIn(**{k: v for k, v in raw.items() if k in ProbeIn.model_fields and isinstance(v, str)})
    s = _settings_for(request)
    provider = (payload.provider or s.provider).strip()
    if provider not in providers.PROVIDERS:
        raise ValidationError(f"Unknown provider '{provider}'", code="bad_provider", details={"available": list(providers.PROVIDERS)})
    same = provider == s.provider
    key = (payload.api_key or "").strip() or (s.api_key if same else "")
    base_url = (payload.base_url or "").strip() or (s.base_url if same else "")
    model = (payload.model or "").strip() or (s.model if same else "")
    return providers.AgentSettings(provider=provider, model=model, api_key=key, base_url=base_url, source=s.source, mode=s.mode)


def _run_images(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """批次列的影像 ref → 快取影像（已釋放的略過）。"""
    images = {r["image_ref"]: store.get(r["image_ref"]) for r in runs if r.get("image_ref")}
    return {k: v for k, v in images.items() if v is not None}


def _batch_context(request: HttpRequest, batch_run_id: int, graph: dict[str, Any] | None):
    """持久化批次：runs 列（未命中優先，帶 index）＋磁碟影像＋graph（缺省＝該次執行的 graph）＋洞察文字。"""
    from apps.vision.batch import insights as insights_mod
    from apps.vision.batch import store as bstore
    from apps.vision.batch.api import _run_or_404

    run = _run_or_404(request, batch_run_id)
    bset = run.batch_set
    by_index = {int(im["index"]): im for im in bset.images or []}
    runs: list[dict[str, Any]] = []
    images: dict[str, Any] = {}
    for it in run.items or []:
        idx = int(it.get("index", -1))
        im = by_index.get(idx)
        if im is None:
            continue
        img = bstore.load_image(im)
        if img is None:
            continue
        ref = f"batch:{bset.id}:{idx}"
        images[ref] = img
        m, _ = bstore.row_match(it, im)
        runs.append({"name": str(im.get("name") or f"#{idx + 1}"), "image_ref": ref, "status": str(it.get("status", "")), "outputs": it.get("outputs") or {},
                     "expected": str(im.get("expected") or ""), "index": idx, "mismatch": m is False,
                     "group": im.get("group", "tune"), "expect_outputs": im.get("expect_outputs") or {}})
    runs.sort(key=lambda r: 0 if r["mismatch"] else 1)
    for r in runs:
        r.pop("mismatch", None)
    ins = run.insights or insights_mod.compute(run.graph, run.items or [], bset.images or [])
    return run, bset, (graph or run.graph), runs, images, "\n".join(ins.get("text") or [])


@router.get("/agent/info")
def agent_info(request: HttpRequest):
    s = _settings_for(request)
    return {**s.public(), "reason": providers.missing(s)[1], "reason_code": providers.missing(s)[0],
            "providers": [{"value": p, "label": providers.PROVIDER_LABELS[p], "default_model": providers.DEFAULT_MODELS.get(p, "")} for p in providers.PROVIDERS]}


@router.get("/agent/settings")
def get_agent_settings(request: HttpRequest):
    p = principal(request)
    if p.user is None:
        raise ValidationError("An API key has no user settings", code="no_user")
    mine = providers.user_settings(p.user)
    return {"configured": mine is not None, **(mine or providers.AgentSettings()).public(), "server": providers.server_settings().public()}


@router.patch("/agent/settings")
def patch_agent_settings(request: HttpRequest, payload: SettingsIn):
    p = principal(request)
    if p.user is None:
        raise ValidationError("An API key has no user settings", code="no_user")
    if payload.provider not in providers.PROVIDERS:
        raise ValidationError(f"Unknown provider '{payload.provider}'", code="bad_provider", details={"available": list(providers.PROVIDERS)})
    row, _ = UserPref.objects.get_or_create(user=p.user)
    data = dict(row.agent or {})
    data["provider"] = payload.provider
    if payload.model is not None:
        data["model"] = payload.model.strip()
    if payload.base_url is not None:
        data["base_url"] = payload.base_url.strip()
    if payload.mode is not None:
        if payload.mode not in providers.MODES:
            raise ValidationError(f"Unknown mode '{payload.mode}'", code="bad_mode", details={"available": list(providers.MODES)})
        data["mode"] = payload.mode
    if payload.clear_key:
        data["api_key"] = ""
    elif payload.api_key:
        data["api_key"] = payload.api_key.strip()
    row.agent = data
    row.save(update_fields=["agent", "updated_at"])
    mine = providers.user_settings(p.user) or providers.AgentSettings()
    return {"configured": True, **mine.public(), "reason": providers.missing(mine)[1], "reason_code": providers.missing(mine)[0]}


@router.get("/agent/skills")
def list_agent_skills(request: HttpRequest):
    """AI 代理技能清單：平台規則、設計原則、每個工具的使用要領（給人看，也是 LLM 讀的同一份）。"""
    return {"items": skills.list_skills()}


def _skill_keys() -> set[str]:
    return {it["key"] for it in skills.list_skills()}


@router.get("/agent/skills/custom")
def list_custom_skills(request: HttpRequest):
    """站點補充＋我的個人補充。"""
    p = principal(request)
    rows = AgentSkill.objects.filter(scope="site")
    if p.user is not None:
        rows = rows | AgentSkill.objects.filter(scope="user", owner=p.user)
    return {"items": [{"key": r.key, "scope": r.scope, "owner_id": r.owner_id, "chars": len(r.markdown), "updated_at": r.updated_at.isoformat()} for r in rows.order_by("key", "scope")]}


@router.put("/agent/skills/custom/{key}")
def put_custom_skill(request: HttpRequest, key: str, payload: CustomSkillIn):
    """新增／更新技能補充：scope=user 存自己的；scope=site 需管理員。"""
    p = principal(request)
    if key not in _skill_keys():
        raise NotFound(f"There is no skill '{key}'", code="skill_not_found")
    if payload.scope not in ("site", "user"):
        raise ValidationError("scope must be site or user", code="bad_scope")
    if payload.scope == "site" and not p.is_admin:
        raise ValidationError("Site-wide notes need an administrator", code="not_admin")
    if payload.scope == "user" and p.user is None:
        raise ValidationError("A personal note needs a signed-in user", code="no_user")
    text = payload.markdown.strip()
    if len(text) > 20000:
        raise ValidationError("The note is too long (20000 characters maximum)", code="too_long")
    owner = p.user if payload.scope == "user" else None
    row, _ = AgentSkill.objects.update_or_create(key=key, scope=payload.scope, owner=owner, defaults={"markdown": text})
    skills.invalidate()
    return {"key": key, "scope": row.scope, "chars": len(row.markdown), "updated_at": row.updated_at.isoformat(), "markdown": skills.skill_text(key, p.user)}


@router.delete("/agent/skills/custom/{key}", response={204: None})
def delete_custom_skill(request: HttpRequest, key: str, scope: str = "user"):
    p = principal(request)
    if scope == "site" and not p.is_admin:
        raise ValidationError("Site-wide notes need an administrator", code="not_admin")
    qs = AgentSkill.objects.filter(key=key, scope=scope, owner=None if scope == "site" else p.user)
    if not qs.exists():
        raise NotFound("No such note", code="custom_not_found")
    qs.delete()
    skills.invalidate()
    return 204, None


@router.get("/agent/skills/{key}")
def get_agent_skill(request: HttpRequest, key: str):
    """技能全文（含站點／個人補充）＋原始補充文字（供編輯）。"""
    p = principal(request)
    try:
        markdown = skills.skill_text(key, p.user)
    except KeyError:
        raise NotFound(f"There is no skill '{key}'", code="skill_not_found") from None
    site, mine = skills.custom_texts(key, p.user)
    return {"key": key, "markdown": markdown, "custom": {"site": site, "user": mine}, "can_site": p.is_admin}


@router.post("/agent/settings/models")
def list_agent_models(request: HttpRequest):
    """列出金鑰可用的模型名。帶著畫面上選的供應商／金鑰就用那組（不必先儲存），沒帶就用目前生效的。"""
    return providers.list_models(_probe_settings(request))


@router.post("/agent/settings/test")
def test_agent_settings(request: HttpRequest):
    """打一個最小請求，回成功與否＋失敗原因（金鑰錯、缺套件、模型名錯、網路）；同樣可帶畫面上還沒儲存的設定。"""
    return providers.test_connection(_probe_settings(request))


@router.post("/agent/image", response={201: dict})
def upload_agent_image(request: HttpRequest, image: UploadedFile = File(...)):
    require_feature(request, "agent").can_execute()
    frame = _decode_upload(image)
    run_id = f"agent{uuid.uuid4().hex[:12]}"
    info = store.put(f"{run_id}:upload:image", frame, flow_id=service.AGENT_FLOW_ID, run_id=run_id, pinned=True)
    return 201, {**info, "name": image.name}


def _image_or_404(ref: str):
    frame = store.get(ref)
    if frame is None:
        raise NotFound("That image is no longer cached; upload it again", code="image_gone")
    return frame


def _images(payload: GenerateIn):
    refs = payload.images or ([payload.ref] if payload.ref else [])
    if not refs:
        raise ValidationError("At least one image is needed", code="no_image")
    return [_image_or_404(r) for r in refs]


def _regions(payload: list[RegionIn]) -> list[dict[str, Any]]:
    return [{"region": r.region, "hint": r.hint, "image": r.image} for r in payload]


@router.post("/agent/clarify")
def agent_clarify(request: HttpRequest, payload: GenerateIn):
    """生成前的確認：回 ready 或最多 3 個問題（規則或 LLM）。不執行流程。"""
    require_feature(request, "agent").can_execute()
    return service.clarify(_images(payload), _regions(payload.regions), payload.prompt, payload.answers, _settings_for(request))


@router.post("/agent/generate")
def agent_generate(request: HttpRequest, payload: GenerateIn):
    require_feature(request, "agent").can_execute()
    return service.generate(_images(payload), _regions(payload.regions), payload.prompt, _settings_for(request), use_llm=payload.use_llm,
                            answers=payload.answers, labels=[lb.model_dump() if isinstance(lb, ImageLabelIn) else lb for lb in payload.labels], groups=payload.groups, owner=principal(request).user)


@router.post("/agent/save-tool", response={201: dict})
def agent_save_tool(request: HttpRequest, payload: SaveToolIn):
    """助手生成的流程：取像以外的步驟封裝成一個複合工具（教導參數與區域對外），再建一條「取像 → 工具實例」的流程。"""
    from django.db import IntegrityError, transaction

    from apps.core.errors import Conflict
    from apps.vision import composites, versions
    from apps.vision.graph import validate_graph
    from apps.vision.models import Flow

    p = require_feature(request, "tools.edit")
    require_feature(request, "flows.edit")
    graph = validate_graph(payload.graph)
    inner = [str(n.get("id")) for n in graph.get("nodes", []) if not actions.is_acquisition(n) and n.get("type") != "note"]
    if not inner:
        raise ValidationError("The flow has no inspection steps to encapsulate", code="empty_selection")
    enc = composites.encapsulate(graph, inner, payload.key, payload.label.strip() or payload.key, expose_params=True, version=1)
    name = payload.flow_name.strip() or payload.label.strip() or payload.key
    with transaction.atomic():
        row = composites.create(p.user, {"key": payload.key, "label": payload.label.strip() or payload.key, "description": payload.description,
                                         "category": payload.category or "detect", "icon": "Sparkles", "graph": enc["tool_graph"], "interface": enc["interface"]})
        try:
            with transaction.atomic():
                flow = Flow.objects.create(name=name, description=payload.description, owner=p.user, graph=validate_graph(enc["graph"]))
        except IntegrityError:
            raise Conflict("A flow with that name already exists", code="flow_name_taken") from None
    versions.snapshot(flow, user=p.user, note="created")
    audit.record(request, "tool.create", row, summary=row.key)
    audit.record(request, "flow.create", flow, summary=f"{len(flow.graph.get('nodes') or [])} steps (tool {row.key})")
    if payload.session_id:
        AgentSession.objects.filter(pk=payload.session_id).update(flow_id=flow.id)
    return 201, {"tool": composites.out(row, with_usage=True), "flow_id": flow.id, "instance": enc["instance"]["id"]}


@router.post("/agent/run")
def agent_run(request: HttpRequest, payload: RunGraphIn):
    """把一份 graph（例如切換的候選方案）在上傳影像上實跑，回與 generate 相同的 report／reports。"""
    require_feature(request, "agent").can_execute()
    refs = payload.images or ([payload.ref] if payload.ref else [])
    if not refs:
        raise ValidationError("At least one image is needed", code="no_image")
    return service.run_graph([_image_or_404(r) for r in refs], payload.graph, payload.main)


@router.post("/agent/autotune")
def agent_autotune(request: HttpRequest, payload: AutotuneIn):
    """批次測試的自動調參：runs[].expected（ok／ng）當標記，只動現場調機參數。"""
    p = require_feature(request, "agent")
    p.can_execute()
    limits = {"max_evals": max(1, min(200, payload.max_evals)), "deadline_s": max(1.0, min(120.0, payload.deadline_s))}
    if payload.batch_run_id is not None:
        run, bset, graph, runs, images, _ = _batch_context(request, payload.batch_run_id, payload.graph)
        result = service.autotune_runs(graph, runs, images, detail=True, **limits)
        new = None
        if result.get("applied"):
            from apps.vision.batch import store as bstore

            new = bstore.persist_tune(run.id, result["graph"], result["items"], origin="autotune", label="自動調參", owner=p.user,
                                      meta={"rationale": result["rationale"], "changes": result["changes"], "autotune": result.get("autotune"), "acceptance": result.get("acceptance")})
        return {**result, "batch_run_id": new.id if new else None}
    if payload.graph is None:
        raise ValidationError("graph or batch_run_id is required", code="bad_request")
    runs = [r.dict() for r in payload.runs]
    return service.autotune_runs(payload.graph, runs, _run_images(runs), **limits)


@router.post("/agent/refine")
def agent_refine(request: HttpRequest, payload: RefineIn):
    require_feature(request, "agent").can_execute()
    if not payload.feedback.strip():
        raise ValidationError("The feedback cannot be empty", code="empty_feedback")
    return service.refine(_images(payload), _regions(payload.regions), payload.prompt, payload.graph, payload.feedback, _settings_for(request))


@router.post("/agent/edit")
def agent_edit(request: HttpRequest, payload: EditIn):
    require_feature(request, "agent").can_execute()
    if not payload.instruction.strip():
        raise ValidationError("The instruction cannot be empty", code="empty_instruction")
    image = store.get(payload.image_ref) if payload.image_ref else None
    return service.edit(payload.graph, payload.instruction, image, _settings_for(request))


@router.post("/agent/jobs", response={202: dict})
def start_agent_job(request: HttpRequest, payload: JobIn):
    """代理模式背景工作：generate（影像＋ROI＋需求）、edit（graph＋指令＋影像 ref）、tune（graph＋指令＋批次列）。
    沒有 LLM 時工作仍會建立並立即以規則引擎完成。"""
    require_feature(request, "agent")
    chat = _chat_for(request, payload.chat_id, payload.flow_id)
    settings = _settings_for(request)
    images = _images(payload) if (payload.images or payload.ref) else []
    if payload.task == "generate" and not images:
        raise ValidationError("At least one image is needed", code="no_image")
    graph, extra_summary, batch_run_id = payload.graph, "", None
    if payload.task == "tune" and payload.batch_run_id is not None:
        run, _bset, graph, runs, run_images, extra_summary = _batch_context(request, payload.batch_run_id, payload.graph)
        batch_run_id = run.id
    else:
        runs = [r.dict() for r in payload.runs]
        run_images = _run_images(runs)
    if payload.task in ("edit", "tune") and (graph is None or not payload.instruction.strip()):
        raise ValidationError("edit and tune need a graph and an instruction", code="bad_request")
    selected = [r for r in runs if r.get("image_ref") in run_images]
    from_runs = payload.task == "tune" and not images
    if from_runs:
        images = [run_images[r["image_ref"]] for r in selected]
    labels = ([{"expected": r.get("expected", ""), "group": r.get("group", "tune")} for r in selected] if from_runs else
              [lb.model_dump() if isinstance(lb, ImageLabelIn) else lb for lb in payload.labels])
    if chat:
        extra_summary += "\n" + situation.describe({"work_state": chat.work_state})
    state = service.build_state(payload.task, images, _regions(payload.regions), payload.prompt, answers=payload.answers, labels=labels,
                                graph=graph, instruction=payload.instruction, runs=runs, owner=principal(request).user, extra_summary=extra_summary,
                                groups=None if from_runs else payload.groups)
    # 在呼叫者執行緒擷取工程知識，代理提示不用從文字猜流程身分。
    from apps.vision import notes as engineering_notes
    state.principal = principal(request)
    state.flow_id = payload.flow_id or (chat.flow_id if chat else None) or (_bset.flow_id if batch_run_id else None)
    state.engineering_notes = engineering_notes.prompt(state.flow_id) if state.owner else ""
    # 版本基準只在圖與綁定流程一致時才帶，否則儲存會以衝突回報而不是覆蓋。
    state.expected_updated_at = payload.expected_updated_at or (chat.work_state.get("flow_updated_at", "") if chat else "")
    if state.flow_id and not state.expected_updated_at:
        bound = Flow.objects.filter(pk=state.flow_id).first()
        if bound and bound.graph == graph:
            state.expected_updated_at = bound.updated_at.isoformat()
    budget = loop.Budget(max_turns=max(1, min(40, payload.max_turns)), max_trials=max(1, min(30, payload.max_trials)), deadline_s=max(10.0, min(900.0, payload.deadline_s)))
    job_question_ids = set()
    def record_progress(out):
        nonlocal job_question_ids
        chat.refresh_from_db()
        result = out.get("result") or {}
        report = result.get("report") or {}
        questions = [q for q in chat.work_state.get("pending_questions", []) if q.get("id") not in job_question_ids]
        incoming = out.get("questions", []) if out["status"] == "needs_input" else []
        update = {"pending_questions": [*questions, *incoming]}
        if state.saved_flow:
            update.update(flow_updated_at=state.saved_flow["updated_at"], flow_version=state.saved_flow["version"])
        job_question_ids = {q.get("id") for q in incoming}
        if runs:
            update["sample_groups"] = {group: [r["image_ref"] for r in runs if r.get("group", "tune") == group] for group in ("tune", "accept")}
        if report or result.get("items"):
            update["last_trial"] = {"at": timezone.now().isoformat(), "status": report.get("status", out["status"]),
                                    "summary": result.get("rationale", ""), "per_task": []}
        chats.record(chat, update, f"Assistant job {out['status']}.")
    return 202, jobs.start(payload.task, settings, state, budget, runs=runs, run_images=run_images, batch_run_id=batch_run_id,
                          **({"on_progress": record_progress} if chat else {}))


@router.get("/agent/jobs")
def list_agent_jobs(request: HttpRequest):
    return {"items": jobs.list_jobs(require_feature(request, "agent"))}


@router.get("/agent/jobs/{job_id}")
def get_agent_job(request: HttpRequest, job_id: str, step_from: int = 0):
    jobs.require_owner(job_id, require_feature(request, "agent"))
    return jobs.get(job_id, step_from)


@router.post("/agent/jobs/{job_id}/cancel")
def cancel_agent_job(request: HttpRequest, job_id: str):
    jobs.require_owner(job_id, require_feature(request, "agent"))
    return {"cancelled": jobs.cancel(job_id)}


@router.post("/agent/jobs/{job_id}/answer")
def answer_agent_job(request: HttpRequest, job_id: str, payload: AnswerIn):
    jobs.require_owner(job_id, require_feature(request, "agent"))
    result = jobs.answer(job_id, payload.answers)
    from apps.core import audit

    audit.record(request, "agent.answer", target_type="agent", target_id=str(job_id), detail={"answers": payload.answers})
    return result


# ---------------------------------------------------------------------------
# 工作階段（記憶）
# ---------------------------------------------------------------------------
def _visible_sessions(request: HttpRequest):
    p = principal(request)
    qs = AgentSession.objects.all()
    if p.is_admin:
        return qs
    return qs.filter(owner=p.user) if p.user is not None else qs.none()


def _session_or_404(request: HttpRequest, session_id: int) -> AgentSession:
    row = _visible_sessions(request).filter(pk=session_id).first()
    if row is None:
        raise NotFound(f"No session {session_id}", code="session_not_found")
    return row


@router.get("/agent/sessions")
def list_sessions(request: HttpRequest, limit: int = 50, intent: str = ""):
    qs = _visible_sessions(request)
    if intent:
        qs = qs.filter(intent=intent)
    limit = max(1, min(200, limit))
    return {"items": [memory.session_out(s) for s in qs[:limit]], "total": qs.count()}


@router.get("/agent/sessions/{session_id}")
def get_session(request: HttpRequest, session_id: int):
    return memory.session_out(_session_or_404(request, session_id), full=True)


@router.patch("/agent/sessions/{session_id}")
def patch_session(request: HttpRequest, session_id: int, payload: SessionPatch):
    """評分（1／-1／0）、成功與否、備註、關聯到存成的流程。"""
    row = _session_or_404(request, session_id)
    fields = []
    if payload.lessons is not None:
        try:
            row.lessons = memory.clean_lessons(payload.lessons)
        except ValueError as exc:
            raise ValidationError(str(exc), code="bad_lessons") from None
        fields.append("lessons")
    if payload.rating is not None:
        if payload.rating not in (-1, 0, 1):
            raise ValidationError("rating must be -1, 0 or 1", code="bad_rating")
        row.rating = payload.rating
        fields.append("rating")
    if payload.success is not None:
        row.success = payload.success
        fields.append("success")
    if payload.note is not None:
        row.note = payload.note[:2000]
        fields.append("note")
    if payload.flow_id is not None:
        flow = Flow.objects.filter(pk=payload.flow_id).first()
        if flow is None:
            raise NotFound(f"Flow {payload.flow_id} not found", code="flow_not_found")
        row.flow = flow
        fields.append("flow")
    if fields:
        row.save(update_fields=[*fields, "updated_at"])
    return memory.session_out(row)


@router.post("/agent/sessions/{session_id}/restore")
def restore_session(request: HttpRequest, session_id: int):
    """把工作階段的影像重新放進快取（pinned），回前端還原所需的一切。"""
    require_feature(request, "agent").can_execute()
    row = _session_or_404(request, session_id)
    images = []
    for item, img in memory.load_images(row):
        run_id = f"agent{uuid.uuid4().hex[:12]}"
        info = store.put(f"{run_id}:upload:image", img, flow_id=service.AGENT_FLOW_ID, run_id=run_id, pinned=True)
        images.append({**info, "name": item.get("name") or "影像", "group": item.get("group", "tune")})
    if not images:
        raise NotFound("The images of this session no longer exist", code="images_gone")
    return {**memory.session_out(row, full=True), "images": images}


@router.delete("/agent/sessions/{session_id}", response={204: None})
def delete_session(request: HttpRequest, session_id: int):
    memory.forget(_session_or_404(request, session_id))
    return 204, None


@router.post("/agent/tune")
def agent_tune(request: HttpRequest, payload: TuneIn):
    p = require_feature(request, "agent")
    p.can_execute()
    if not payload.instruction.strip():
        raise ValidationError("The instruction cannot be empty", code="empty_instruction")
    if payload.batch_run_id is not None:
        run, bset, graph, runs, images, extra = _batch_context(request, payload.batch_run_id, payload.graph)
        result = service.tune(graph, payload.instruction, runs, images, _settings_for(request), extra_summary=extra, detail=True)
        new = None
        if result.get("applied"):
            from apps.vision.batch import store as bstore

            origin = "autotune" if result.get("provider") == "autotune" else "ai_tune"
            new = bstore.persist_tune(run.id, result["graph"], result["items"], origin=origin, label=payload.instruction[:60], owner=p.user,
                                      meta={"rationale": result["rationale"], "changes": result["changes"], "provider": result.get("provider"), "autotune": result.get("autotune"), "acceptance": result.get("acceptance")})
        return {**result, "batch_run_id": new.id if new else None}
    if payload.graph is None:
        raise ValidationError("graph or batch_run_id is required", code="bad_request")
    runs = [r.dict() for r in payload.runs]
    return service.tune(payload.graph, payload.instruction, runs, _run_images(runs), _settings_for(request))


# 不放單獨的「何」：「工件可能轉到任何位置」會被當成問句（階段 15）
_QUESTION_MARKERS = ("？", "?", "如何", "怎麼", "怎样", "怎么", "為什麼", "为什么", "什麼", "什么", "是否", "哪", "有何", "為何", "为何", "何時", "何时", "何處", "何处",
                     "何謂", "何谓", "何種", "何种", "可以嗎", "介紹", "教我", "是什", "說明一下", "解釋", "解释",
                     "how ", "what ", "why ", "which ", "where ", "when ", "can i", "should i")
_EDIT_MARKERS = ("改成", "改為", "改为", "設為", "设为", "設成", "調成", "调成", "調到", "调到", "改到", "改用", "停用", "啟用", "启用", "刪除", "删除", "移除", "新增", "加上", "加入", "加一個", "加一个",
                 "後面加", "前面加", "接上", "把", "換成", "换成", "降低", "提高", "放寬", "放宽", "收緊", "收紧", "調整", "调整", "調高", "調低", "调高", "调低", "誤判", "误判", "漏檢", "漏检",
                 "期望數量", "期望数量", "公差", "自動調參", "自动调参", "set ", "disable", "enable", "delete", "remove", "add ", "change", "increase", "decrease", "loosen", "tighten", "tune",
                 # 接線與位置修正的說法（「內圓心 ROI 再跟著外圓心位移」）、以及「幫我直接修改」這種沒有內容但明確要動手的句子
                 "跟著", "跟着", "跟隨", "跟随", "位移", "補正", "补正", "接到", "連到", "连到", "串接", "修改", "改一下", "幫我改", "帮我改", "做成", "改掉",
                 "follow", "wire ", "connect", "modify", "edit ", "apply")
_DATA_MARKERS = ("張", "张", "命中", "門檻", "门槛", "阈值", "為什麼", "为什么", "哪個參數", "哪个参数", "這次執行", "这次执行", "此次執行", "此次执行", "本次", "影像", "圖像", "图像", "數值", "数值",
                 "誤判", "误判", "漏檢", "漏检", "出錯", "出错", "耗時", "耗时", "慢", "分佈", "分布", "上一次", "改善", "image", "threshold", "mismatch", "this run")
_DATA_WORDS = re.compile(r"\b(ok|ng|failed)\b")
_ACTION_REQUEST = re.compile(r"\b(?:select_source|select_asset|apply_calibration|connect_source|run_trial|auto_tune|save_flow_version|run_batch|write_output|save_to_share|enable_reporting|unlock_engine|delete_flow|delete_asset)\b|\bunlock (?:the )?engine\b|解除引擎鎖定|解鎖引擎", re.I)


def chat_intent(message: str, context: ChatContext, mode: str) -> str:
    """auto 模式下判斷意圖：問句一律問答；有修改語氣且在編輯器／工具頁→edit、批次頁→tune；批次頁的資料問題→consult。"""
    if mode in ("help", "edit", "consult", "tune"):
        return mode
    low = message.lower()
    is_question = any(m in low for m in _QUESTION_MARKERS)
    wants_edit = any(m in low for m in _EDIT_MARKERS) and not is_question
    if context.graph is not None and not is_question and _ACTION_REQUEST.search(message):
        return "edit"
    if context.kind in ("flow_editor", "inspect") and context.graph is not None and not is_question and tasklist.is_request(message, context.graph):
        return "tasklist"
    if context.kind in ("flow_editor", "tool") and context.graph and wants_edit:
        return "edit"
    if context.kind == "batch" and context.batch_run_id is not None:
        if wants_edit:
            return "tune"
        if any(m in low for m in _DATA_MARKERS) or _DATA_WORDS.search(low):
            return "consult"
    return "help"


@router.post("/agent/chat")
def agent_chat(request: HttpRequest, payload: ChatIn):
    """全域 AI 助手：一個入口依頁面脈絡分流——平台使用問答（文件檢索）、流程編輯器修改（edit）、批次資料諮詢（consult）、依資料調整（tune）。
    代理模式下 edit／tune 回 {agentic: true} 讓前端改走背景工作。"""
    p = principal(request)
    message = payload.message.strip()
    if not message:
        raise ValidationError("The message cannot be empty", code="empty_message")
    settings = _settings_for(request)
    ctx = payload.context
    chat = _chat_for(request, payload.chat_id, ctx.flow_id)
    progress = {k: chat.work_state.get(k) for k in ("pending_questions", "assumptions", "last_trial")} if chat else {}
    history = payload.history
    if progress:
        from apps.vision.agent.situation import describe

        history = [*history, {"role": "user", "text": describe({"work_state": progress})}]
    # 「記住：…」／「忘記：…」是記憶指令，不經 LLM（整合方沒有使用者身分就當一般問句）
    cmd = notes.parse_command(message)
    if cmd and p.user is not None:
        kind, text = cmd
        if kind == "remember":
            try:
                row = notes.add_fact(p.user, text)
            except ValueError as exc:
                raise ValidationError(str(exc), code="memory_empty") from None
            return {"kind": "help", "answer": notes.confirmation("remember", row.text, 0, ctx.lang), "provider": "memory", "sources": [], "warnings": [], "actions": [], "lookups": [], "memory": notes.out(row)}
        if not text:
            raise ValidationError("Say what to forget", code="memory_empty")
        deleted = notes.forget_facts(p.user, text)
        return {"kind": "help", "answer": notes.confirmation("forget", text, deleted, ctx.lang), "provider": "memory", "sources": [], "warnings": [], "actions": [], "lookups": []}
    intent = chat_intent(message, ctx, payload.mode)
    if intent == "edit" and _ACTION_REQUEST.search(message):
        require_feature(request, "agent")
        if not service.agentic(settings):
            raise ValidationError("Use an assistant configuration with action support for this request.", code="actions_unavailable")
        return {"kind": "edit", "agentic": True, "answer": "", "provider": settings.provider}
    if intent == "tasklist":
        require_feature(request, "agent")
        result = tasklist.propose(message, ctx.lang, ctx.graph, settings,
                                  image=store.get(ctx.image_ref) if ctx.image_ref else None, history=history)
        assumptions = [{"task_id": d.get("task_id", ""), "field": key, "value": v.get("value"), "note": v.get("note", "")}
                       for d in result["drafts"] for key, v in d["fields"].items() if v["status"] == "assumed"]
        previous = chat.work_state if chat else {}
        chats.record(chat, {"drafts": [*previous.get("drafts", []), *result["drafts"]],
                            "pending_questions": [*previous.get("pending_questions", []), *result["questions"]],
                            "assumptions": [*previous.get("assumptions", []), *assumptions]})
        return {"kind": "tasklist", "answer": "", **result, **_offline_degrade(settings, ctx.lang, result.get("warnings"))}
    if intent != "help":
        # 使用說明問答不動引擎、也不需要助手權限；修改／諮詢／調整會試執行，要有 agent
        p = require_feature(request, "agent")
        p.can_execute()
    if intent == "edit":
        if not ctx.graph:
            raise ValidationError("Editing a flow needs its current graph", code="no_graph")
        if service.agentic(settings):
            return {"kind": "edit", "agentic": True, "answer": "", "provider": settings.provider}
        image = store.get(ctx.image_ref) if ctx.image_ref else None
        # 帶對話脈絡：「請幫我直接修改」這種句子本身沒有內容，真正的需求在前一句
        result = service.edit(ctx.graph, message, image, settings, history=history)
        report = result.get("report") or {}
        chats.record(chat, {"last_trial": {"at": timezone.now().isoformat(), "status": report.get("status", "unknown"),
                                          "summary": result.get("rationale", ""), "per_task": []}} if report else {}, "Flow edit proposal completed.")
        return {"kind": "edit", "answer": result["rationale"], "provider": result["provider"], "result": result, **_offline_degrade(settings, ctx.lang, result.get("warnings"))}
    if intent in ("consult", "tune"):
        if ctx.batch_run_id is None:
            raise ValidationError("Consulting or tuning on data needs a batch_run_id", code="no_batch_run")
        if intent == "tune":
            if service.agentic(settings):
                return {"kind": "tune", "agentic": True, "answer": "", "provider": settings.provider}
            run, bset, graph, runs, images, extra = _batch_context(request, ctx.batch_run_id, ctx.graph)
            result = service.tune(graph, message, runs, images, settings,
                                  extra_summary=extra + ("\n" + situation.describe({"work_state": progress}) if progress else ""), detail=True)
            new = None
            if result.get("applied"):
                from apps.vision.batch import store as bstore

                origin = "autotune" if result.get("provider") == "autotune" else "ai_tune"
                new = bstore.persist_tune(run.id, result["graph"], result["items"], origin=origin, label=message[:60], owner=p.user,
                                          meta={"rationale": result["rationale"], "changes": result["changes"], "provider": result.get("provider"), "autotune": result.get("autotune"), "acceptance": result.get("acceptance")})
            work_state = chats.record(chat, {"sample_groups": {group: [r["image_ref"] for r in runs if r.get("group", "tune") == group] for group in ("tune", "accept")},
                                "last_trial": {"at": timezone.now().isoformat(), "status": "done", "summary": result["rationale"], "per_task": []}}, "Parameter tuning completed.")
            return {"kind": "tune", "answer": result["rationale"], "provider": result["provider"], "result": {**result, "batch_run_id": new.id if new else None}, "batch_run_id": new.id if new else None, "work_state": work_state}
        from apps.vision.batch.api import _run_or_404

        run = _run_or_404(request, ctx.batch_run_id)
        if run.status != "done":
            raise ValidationError("That run has not finished", code="run_not_done")
        out = consult_mod.consult(run, run.batch_set, message, settings, graph=ctx.graph, user=p.user)
        return {"kind": "consult", "answer": out["answer"], "provider": out["provider"], "suggestions": out["suggestions"], "warnings": out["warnings"]}
    from apps.accounts.models import EngineLock

    shot = _screenshot_b64(ctx.screenshot)
    context = {k: v for k, v in ctx.dict().items() if k != "screenshot"}
    context["work_state"] = progress
    out = help_mod.answer(message, settings, context=context, history=payload.history, user=p.user, principal=p, lock=EngineLock.current().to_dict(), screenshot=shot)
    row = notes.record_qa(p.user, message, str(out.get("answer") or ""), context, str(out.get("provider") or ""))
    if row is not None:
        out["memory_id"] = row.id
    if not service.has_llm(settings) and help_mod.wants_build(message):
        # 離線又在要求「幫我建一條檢測」：明確說沒有 AI 供應商，並把人帶到工具箱的檢測任務分類
        degraded = _offline_degrade(settings, ctx.lang, out.get("warnings"))
        out["warnings"] = degraded["warnings"]
        out["actions"] = [*degraded["actions"], *[a for a in (out.get("actions") or []) if a.get("kind") != "open_toolbox"]]
    return {"kind": "help", **out}


def _offline_degrade(settings: providers.AgentSettings, lang: Any, warnings: list[str] | None) -> dict[str, Any]:
    """沒有 LLM 時修改／任務清單／建立類的回覆一律附上「離線＋工具箱」的說明與動作。"""
    if service.has_llm(settings):
        return {"warnings": list(warnings or []), "actions": []}
    return {"warnings": [*(warnings or []), help_mod.msg(lang, "offline_toolbox")], "actions": [help_mod.toolbox_action(lang)]}


# ---------------------------------------------------------------------------
# 長期記憶（每位使用者自己的：事實與可評分的問答）
# ---------------------------------------------------------------------------
def _chat_for(request: HttpRequest, chat_id: int | None, flow_id: int | None = None):
    """動作前先驗證擁有者與流程綁定，不能用 best-effort 吞掉授權錯誤。"""
    if chat_id is None:
        return None
    row = chats.get(_memory_user(request), chat_id)
    if row is None:
        raise NotFound(f"No conversation {chat_id}", code="chat_not_found")
    if flow_id is not None:
        previous = row.flow_id or (row.work_state or {}).get("flow_id")
        if previous:
            chats.bind(row, flow_id)
        else:
            row = chats.save(row, flow_id=flow_id)
    return row


def _memory_user(request: HttpRequest):
    p = principal(request)
    if p.user is None:
        raise ValidationError("Assistant memory belongs to a signed-in user", code="memory_needs_user")
    return p.user


@router.get("/agent/memory")
def list_memory(request: HttpRequest):
    """自己的記憶：事實（記住：…）與最近的問答（含評分）。整合方沒有使用者身分，回空清單。"""
    p = principal(request)
    return {"facts": [notes.out(r) for r in notes.facts(p.user)], "qa": [notes.out(r) for r in notes.recent_qa(p.user)],
            "limits": {"facts": notes.MAX_FACTS, "qa": notes.MAX_QA}}


@router.post("/agent/memory", response={201: dict})
def add_memory(request: HttpRequest, payload: MemoryIn):
    user = _memory_user(request)
    try:
        row = notes.add_fact(user, payload.text)
    except ValueError as exc:
        raise ValidationError(str(exc), code="memory_empty") from None
    return 201, notes.out(row)


@router.post("/agent/memory/{memory_id}/rate")
def rate_memory(request: HttpRequest, memory_id: int, payload: RateIn):
    """評分一則回答（1 好、-1 不好、0 取消）；評過好的會在相似問題時當範例。"""
    row = notes.rate(_memory_user(request), memory_id, payload.rating)
    if row is None:
        raise NotFound(f"No memory item {memory_id}", code="memory_not_found")
    return notes.out(row)


@router.delete("/agent/memory/{memory_id}", response={204: None})
def delete_memory(request: HttpRequest, memory_id: int):
    if not notes.delete(_memory_user(request), memory_id):
        raise NotFound(f"No memory item {memory_id}", code="memory_not_found")
    return 204, None


@router.get("/agent/chats")
def list_chats(request: HttpRequest):
    """My assistant conversations, newest first (title, message count, when it was last used)."""
    p = principal(request)
    return {"items": chats.listing(p.user) if p.user else [], "limits": {"chats": chats.MAX_CHATS, "messages": chats.MAX_MESSAGES}}


@router.post("/agent/chats", response={201: dict})
def create_chat(request: HttpRequest, payload: ChatSaveIn):
    """Start a conversation (usually empty; the window saves into it as you talk)."""
    row = chats.create(_memory_user(request), payload.messages, payload.title or "", flow_id=payload.flow_id, work_state=payload.work_state)
    return 201, chats.out(row, with_messages=True)


@router.get("/agent/chats/{chat_id}")
def get_chat(request: HttpRequest, chat_id: int):
    row = chats.get(_memory_user(request), chat_id)
    if row is None:
        raise NotFound(f"No conversation {chat_id}", code="chat_not_found")
    return chats.out(row, with_messages=True)


@router.get("/agent/chats/{chat_id}/resume")
def resume_chat(request: HttpRequest, chat_id: int):
    return chats.resume(_chat_for(request, chat_id))


@router.patch("/agent/chats/{chat_id}")
def save_chat(request: HttpRequest, chat_id: int, payload: ChatSaveIn):
    """Replace the conversation's messages (the window saves after each reply) or rename it."""
    row = chats.get(_memory_user(request), chat_id)
    if row is None:
        raise NotFound(f"No conversation {chat_id}", code="chat_not_found")
    return chats.out(chats.save(row, payload.messages, payload.title,
                               flow_id=payload.flow_id if "flow_id" in payload.model_fields_set else chats.UNSET,
                               work_state=payload.work_state), with_messages=True)


@router.delete("/agent/chats/{chat_id}", response={204: None})
def delete_chat(request: HttpRequest, chat_id: int):
    if not chats.delete(_memory_user(request), chat_id):
        raise NotFound(f"No conversation {chat_id}", code="chat_not_found")
    return 204, None


@router.get("/agent/help/search")
def agent_help_search(request: HttpRequest, q: str = "", k: int = 5):
    """說明索引檢索（除錯與前端「相關文件」用）。"""
    hits = help_mod.search(q, k=max(1, min(20, k))) if q.strip() else []
    return {"items": [{"title": s.title, "page": s.page, "heading": s.heading, "url": s.url, "score": round(score, 3), "snippet": help_mod.snippet(s, q)} for s, score in hits],
            **help_mod.index_stats()}


@router.post("/agent/consult")
def agent_consult(request: HttpRequest, payload: ConsultIn):
    """資料諮詢：針對一次批次執行的資料回答問題，附規則洞察與可套用的參數建議。"""
    from apps.vision.batch.api import _run_or_404

    p = require_feature(request, "agent")
    p.can_execute()
    if not payload.question.strip():
        raise ValidationError("The question cannot be empty", code="empty_question")
    run = _run_or_404(request, payload.batch_run_id)
    if run.status != "done":
        raise ValidationError("That run has not finished", code="run_not_done")
    return consult_mod.consult(run, run.batch_set, payload.question.strip(), _settings_for(request), graph=payload.graph, user=p.user)
