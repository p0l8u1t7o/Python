"""配方的匯出／匯入與合理化檢查。

POST /vision/flows/{id}/recipes/check              {param_overrides} → 逐項檢查清單（存檔前的 Check List）
GET  /vision/flows/{id}/recipes/{rid}/export        下載 .recipe.json（含工具版本與流程指紋）
POST /vision/flows/{id}/recipes/import/check        上傳檔（multipart file 或 JSON doc）→ 檢查清單，不寫入
POST /vision/flows/{id}/recipes/import              {doc, name?, accept: [item_key...], is_default?} → 只寫入被接受的項目
GET  /vision/flows/{id}/recipes/export-all          整個流程的配方一次匯出

檢查項目 status：
  ok              節點、工具、版本、參數都對得上
  node_missing    流程裡沒有這個節點 id
  type_changed    節點還在但工具型別不同
  version_changed 工具版本不同（參數語意可能變了）
  param_missing   工具沒有這個參數
  value_invalid   值不符合參數宣告（數值範圍、select 選項、布林）
  unchanged       覆寫值與目前圖上的值相同（存了也沒差；提示用）
前端把 ok／unchanged／version_changed（使用者勾選接受）送進 accept，其餘不能匯入。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from ninja import File, Router, Schema, UploadedFile

from apps.core.errors import Conflict, NotFound, ValidationError
from apps.vision.api import _editable_flow, _recipe_out, _visible_flows
from apps.vision.models import Flow, FlowRecipe
from apps.vision.runner import get_flow
from apps.vision.tools import base as tools

router = Router(tags=["recipes"])
SCHEMA_VERSION = 1


def flow_fingerprint(flow: Flow) -> str:
    """節點 id＋工具型別的指紋：圖的結構變了（不是參數變了）就會不同。"""
    nodes = sorted((str(n.get("id")), str(n.get("type"))) for n in (flow.graph or {}).get("nodes") or [])
    return hashlib.sha1(json.dumps(nodes, ensure_ascii=False).encode()).hexdigest()[:12]


def tool_versions(flow: Flow) -> dict[str, dict[str, Any]]:
    out = {}
    for n in (flow.graph or {}).get("nodes") or []:
        t = str(n.get("type"))
        if t == "note" or not tools.has(t):
            continue
        out[str(n["id"])] = {"type": t, "version": int(getattr(tools.get(t), "version", 1)), "label": n.get("label") or ""}
    return out


def _check_value(param: tools.Param, value: Any) -> str | None:
    kind = param.kind
    if kind in ("number", "range"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "not a number"
        if param.minimum is not None and value < param.minimum:
            return f"below the minimum {param.minimum}"
        if param.maximum is not None and value > param.maximum:
            return f"above the maximum {param.maximum}"
    elif kind == "boolean":
        if not isinstance(value, bool):
            return "not a boolean"
    elif kind == "select":
        allowed = {str(o.get("value")) for o in param.options}
        if allowed and str(value) not in allowed:
            return f"not one of the options ({', '.join(sorted(allowed))}）"
    elif kind == "roi":
        if not isinstance(value, dict) or not value.get("shape"):
            return "not an ROI object"
    elif kind == "json":
        if isinstance(value, str):
            try:
                json.loads(value)
            except json.JSONDecodeError:
                return "not valid JSON"
    return None


def check_overrides(flow: Flow, overrides: dict[str, Any], *, versions: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """逐項產生檢查清單。versions 是匯入檔記錄的工具版本（可為 None）。"""
    items: list[dict[str, Any]] = []
    nodes = {str(n.get("id")): n for n in (flow.graph or {}).get("nodes") or []}
    current_versions = tool_versions(flow)
    for node_id, patch in (overrides or {}).items():
        node = nodes.get(str(node_id))
        label = (node or {}).get("label") or node_id
        if not isinstance(patch, dict):
            items.append({"key": f"{node_id}", "node_id": node_id, "node_label": label, "param": "", "status": "value_invalid", "message": "An override must be an object"})
            continue
        for pkey, value in patch.items():
            item = {"key": f"{node_id}.{pkey}", "node_id": node_id, "node_label": label, "param": pkey, "value": value, "status": "ok", "message": "", "teach": False}
            if node is None:
                item.update(status="node_missing", message="That step is not in the flow")
                items.append(item)
                continue
            ntype = str(node.get("type"))
            recorded = (versions or {}).get(str(node_id)) or {}
            if recorded.get("type") and recorded["type"] != ntype:
                item.update(status="type_changed", message=f"The tool changed from {recorded['type']} to {ntype}")
                items.append(item)
                continue
            if ntype == "note" or not tools.has(ntype):
                item.update(status="type_changed", message="That step is not a runnable tool")
                items.append(item)
                continue
            tool = tools.get(ntype)
            param = next((p for p in tool.params if p.key == pkey), None)
            item["tool"] = ntype
            item["tool_label"] = tool.label
            item["param_label"] = param.label if param else pkey
            item["teach"] = bool(param.teach) if param else False
            item["current"] = (node.get("params") or {}).get(pkey)
            if param is None:
                item.update(status="param_missing", message=f"Tool {tool.label} has no parameter '{pkey}'")
                items.append(item)
                continue
            bad = _check_value(param, value)
            if bad:
                item.update(status="value_invalid", message=bad)
                items.append(item)
                continue
            cur_v = current_versions.get(str(node_id), {}).get("version", 1)
            if recorded.get("version") is not None and int(recorded["version"]) != cur_v:
                item.update(status="version_changed", message=f"Tool version {recorded['version']} → {cur_v}; the parameters may mean something different, please check")
                items.append(item)
                continue
            if item["current"] == value:
                item.update(status="unchanged", message="Same as the value already in the graph")
            items.append(item)
    return items


ACCEPTABLE = {"ok", "unchanged", "version_changed"}


class OverridesIn(Schema):
    param_overrides: dict[str, Any] = {}
    #: True 時把流程裡「所有」宣告過的參數也列進清單（覆寫沒提到的以圖值列為 unchanged），
    #: 前端把 teach=False 的放進摺疊區「其他參數」。
    include_all: bool = False


def all_param_items(flow: Flow, overrides: dict[str, Any]) -> list[dict[str, Any]]:
    """覆寫沒提到的參數：以目前圖上的值列出（unchanged），供 Check List 的「其他參數」區勾選。"""
    items = []
    for n in (flow.graph or {}).get("nodes") or []:
        ntype = str(n.get("type"))
        if ntype == "note" or not tools.has(ntype):
            continue
        tool = tools.get(ntype)
        node_id = str(n.get("id"))
        given = (overrides or {}).get(node_id) or {}
        params = n.get("params") or {}
        for p in tool.params:
            if p.key in given:
                continue
            value = params.get(p.key, p.default)
            items.append({
                "key": f"{node_id}.{p.key}", "node_id": node_id, "node_label": n.get("label") or node_id, "param": p.key,
                "param_label": p.label, "tool": ntype, "tool_label": tool.label, "kind": p.kind,
                "value": value, "current": value, "status": "unchanged", "message": "the same as the value on the graph", "teach": bool(p.teach),
            })
    return items


class ImportIn(Schema):
    doc: dict[str, Any]
    name: str | None = None
    #: 接受哪些檢查項目（key = "node_id.param"）；未列出的不寫入。
    accept: list[str] | None = None
    is_default: bool = False
    description: str | None = None


def _recipe_doc(flow: Flow, r: FlowRecipe) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "recipe",
        "flow_name": flow.name,
        "flow_version": flow.version,
        "flow_fingerprint": flow_fingerprint(flow),
        "tool_versions": tool_versions(flow),
        "recipe": {"name": r.name, "description": r.description, "param_overrides": r.param_overrides or {}, "is_default": r.is_default},
    }


def _download(doc: dict[str, Any], filename: str) -> HttpResponse:
    body = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")
    resp = HttpResponse(body, content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{filename}"
    return resp


def _visible(request: HttpRequest, flow_id: int) -> Flow:
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"Flow {flow_id} not found", code="flow_not_found")
    return flow


@router.post("/flows/{flow_id}/recipes/check")
def recipe_check(request: HttpRequest, flow_id: int, payload: OverridesIn):
    flow = _visible(request, flow_id)
    items = check_overrides(flow, payload.param_overrides)
    if payload.include_all:
        items += all_param_items(flow, payload.param_overrides)
    return {"items": items, "summary": _summary(items), "fingerprint": flow_fingerprint(flow)}


def _summary(items: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {"total": len(items)}
    for it in items:
        out[it["status"]] = out.get(it["status"], 0) + 1
    out["acceptable"] = sum(1 for it in items if it["status"] in ACCEPTABLE)
    return out


@router.get("/flows/{flow_id}/recipes/export-all")
def export_all(request: HttpRequest, flow_id: int):
    flow = _visible(request, flow_id)
    docs = [_recipe_doc(flow, r) for r in flow.recipes.all()]
    return _download({"schema_version": SCHEMA_VERSION, "kind": "recipes", "flow_name": flow.name, "flow_fingerprint": flow_fingerprint(flow), "tool_versions": tool_versions(flow), "recipes": [d["recipe"] for d in docs]}, f"{flow.name}.recipes.json")


@router.get("/flows/{flow_id}/recipes/{recipe_id}/export")
def export_recipe(request: HttpRequest, flow_id: int, recipe_id: int):
    flow = _visible(request, flow_id)
    r = flow.recipes.filter(pk=recipe_id).first()
    if r is None:
        raise NotFound("Recipe not found", code="recipe_not_found")
    return _download(_recipe_doc(flow, r), f"{flow.name}.{r.name}.recipe.json")


def _parse_doc(request: HttpRequest, file: UploadedFile | None) -> dict[str, Any]:
    if file is not None:
        raw = file.read()
    else:
        raw = request.body
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValidationError("Not a valid JSON file", code="bad_recipe_file") from None
    if isinstance(doc, dict) and "doc" in doc and isinstance(doc["doc"], dict):
        doc = doc["doc"]
    if not isinstance(doc, dict) or doc.get("kind") not in ("recipe", "recipes"):
        raise ValidationError("Not a recipe file (kind must be recipe or recipes)", code="bad_recipe_file")
    return doc


def _doc_recipes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    if doc.get("kind") == "recipes":
        return [r for r in doc.get("recipes") or [] if isinstance(r, dict)]
    r = doc.get("recipe")
    return [r] if isinstance(r, dict) else []


@router.post("/flows/{flow_id}/recipes/import/check")
def import_check(request: HttpRequest, flow_id: int, file: UploadedFile | None = File(None)):
    flow = _visible(request, flow_id)
    doc = _parse_doc(request, file)
    result = []
    for r in _doc_recipes(doc):
        items = check_overrides(flow, r.get("param_overrides") or {}, versions=doc.get("tool_versions"))
        result.append({"name": r.get("name") or "", "description": r.get("description") or "", "is_default": bool(r.get("is_default")), "items": items, "summary": _summary(items), "exists": flow.recipes.filter(name=r.get("name") or "").exists()})
    return {
        "flow_name": doc.get("flow_name"),
        "same_flow_name": doc.get("flow_name") == flow.name,
        "fingerprint_match": doc.get("flow_fingerprint") == flow_fingerprint(flow),
        "recipes": result,
    }


@router.post("/flows/{flow_id}/recipes/import", response={201: dict})
def import_recipe(request: HttpRequest, flow_id: int, payload: ImportIn):
    """只寫入 accept 裡且檢查為可接受的項目；accept 為 None 表示接受所有 ok/unchanged。"""
    flow = _editable_flow(request, flow_id)
    doc = payload.doc
    if doc.get("kind") not in ("recipe", "recipes"):
        raise ValidationError("Not a recipe file", code="bad_recipe_file")
    recipes = _doc_recipes(doc)
    if not recipes:
        raise ValidationError("The file contains no recipes", code="bad_recipe_file")
    if doc.get("kind") == "recipe" and len(recipes) == 1 and payload.name:
        recipes[0] = {**recipes[0], "name": payload.name}
    created = []
    skipped: list[dict[str, Any]] = []
    for r in recipes:
        items = check_overrides(flow, r.get("param_overrides") or {}, versions=doc.get("tool_versions"))
        overrides: dict[str, dict[str, Any]] = {}
        for it in items:
            accepted = (payload.accept is None and it["status"] in ("ok", "unchanged")) or (payload.accept is not None and it["key"] in payload.accept and it["status"] in ACCEPTABLE)
            if accepted:
                overrides.setdefault(it["node_id"], {})[it["param"]] = it["value"]
            else:
                skipped.append({"recipe": r.get("name"), **{k: it[k] for k in ("key", "status", "message")}})
        name = str(r.get("name") or "imported").strip()
        description = payload.description if payload.description is not None else str(r.get("description") or "")
        is_default = payload.is_default or (bool(r.get("is_default")) and not flow.recipes.filter(is_default=True).exists())
        try:
            with transaction.atomic():
                if is_default:
                    flow.recipes.update(is_default=False)
                row, made = FlowRecipe.objects.update_or_create(flow=flow, name=name, defaults={"description": description, "param_overrides": overrides, "is_default": is_default})
        except IntegrityError:
            raise Conflict("That recipe name is taken", code="recipe_name_taken") from None
        created.append({**_recipe_out(row), "created": made, "accepted": sum(len(v) for v in overrides.values())})
    return 201, {"items": created, "skipped": skipped}
