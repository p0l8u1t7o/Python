"""AI 助手的唯讀查詢：讓問答路徑的 LLM 能自己去看平台的即時狀態（流程、來源、連線、執行報告、鎖定、外掛、權限、文件），
而不是憑文件猜。每個查詢宣告需要的功能鍵，依呼叫者的 `Principal.can()` 把關——沒權限就回 `{"error": ...}` 讓模型如實說明；
一律只讀（DB／行程內狀態），不執行流程、不改任何東西，資料量有上限。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from apps.vision.agent import skills

MAX_ITEMS = 50
MAX_RESULT_CHARS = 6000


@dataclass
class Lookup:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[Any, dict[str, Any]], dict[str, Any]]
    #: 需要的功能鍵（None＝任何登入者）
    feature: str | None = None

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


def _scalars(values: dict[str, Any] | None, limit: int = 30) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (values or {}).items():
        if isinstance(v, bool) or isinstance(v, (int, str)):
            out[k] = v if not isinstance(v, str) else v[:200]
        elif isinstance(v, float):
            out[k] = round(v, 4)
        if len(out) >= limit:
            break
    return out


def _report_summary(rep: Any, *, full: bool = False) -> dict[str, Any]:
    """RunReport（記憶體）或 FlowRun（DB）→ 精簡摘要：狀態、錯誤、耗時、沒過的節點（full＝所有節點）。"""
    nodes_src = rep.nodes if isinstance(rep.nodes, dict) else {}
    nodes: dict[str, Any] = {}
    for nid, nr in nodes_src.items():
        status = getattr(nr, "status", None) if not isinstance(nr, dict) else nr.get("status")
        message = getattr(nr, "message", "") if not isinstance(nr, dict) else nr.get("message", "")
        outputs = getattr(nr, "outputs", {}) if not isinstance(nr, dict) else nr.get("outputs", {})
        if status == "ok" and not full:
            continue
        item: dict[str, Any] = {"status": status}
        if message:
            item["message"] = str(message)[:200]
        scal = _scalars(outputs, 10)
        if scal:
            item["outputs"] = scal
        nodes[nid] = item
    started = getattr(rep, "started_at", 0)
    if hasattr(started, "timestamp"):
        started = started.timestamp()
    return {
        "run_id": str(rep.id), "flow_id": rep.flow_id, "status": rep.status, "trigger": getattr(rep, "trigger", ""), "error": str(rep.error or "")[:300],
        "duration_ms": round(float(rep.duration_ms or 0)), "ago_s": max(0, round(time.time() - float(started or 0))) if started else None,
        "outputs": _scalars(rep.outputs), "nodes": nodes,
    }


# ---- 各查詢 ----
def h_list_flows(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from apps.vision.models import Flow
    from apps.vision.runner import runner

    q = str(args.get("query") or "").strip()
    qs = Flow.objects.all().order_by("name")
    if q:
        qs = qs.filter(name__icontains=q)
    items = []
    for f in qs[:MAX_ITEMS]:
        rt = runner.runtime(f.id)
        last = rt.recent[-1] if rt.recent else None
        items.append({
            "id": f.id, "name": f.name, "version": f.version, "enabled": f.is_enabled, "commissioned": f.commissioned,
            "nodes": len((f.graph or {}).get("nodes") or []), "recipes": f.recipes.count(), "continuous": runner.is_continuous(f.id),
            "stats": rt.stats.to_dict(), "last_run": {"status": last.status, "error": str(last.error or "")[:120], "ago_s": max(0, round(time.time() - last.started_at))} if last else None,
        })
    return {"count": qs.count(), "items": items}


def h_get_flow(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from apps.vision.models import Flow
    from apps.vision.runner import runner

    flow = Flow.objects.filter(pk=int(args.get("flow_id") or 0)).first()
    if flow is None:
        return {"error": f"No flow with id {args.get('flow_id')}"}
    graph = flow.graph or {}
    nodes = [{"id": n.get("id"), "type": n.get("type"), "label": n.get("label") or "", "enabled": n.get("enabled", True) is not False, "params": _scalars(n.get("params") or {}, 20)}
             for n in (graph.get("nodes") or [])[:MAX_ITEMS]]
    rt = runner.runtime(flow.id)
    recent = [_report_summary(r) for r in rt.recent[-3:]]
    recipes = [{"name": r.name, "is_default": r.is_default} for r in flow.recipes.all()[:20]]
    return {"id": flow.id, "name": flow.name, "description": flow.description, "version": flow.version, "enabled": flow.is_enabled, "commissioned": flow.commissioned,
            "continuous": runner.is_continuous(flow.id), "continuous_interval_ms": flow.continuous_interval_ms, "nodes": nodes, "edges": len(graph.get("edges") or []),
            "recipes": recipes, "stats": rt.stats.to_dict(), "recent_runs": recent}


def h_get_run(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from apps.vision.models import FlowRun
    from apps.vision.runner import runner

    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return {"error": "run_id is required"}
    for rt in list(runner._runtimes.values()):  # noqa: SLF001 - 唯讀掃記憶體內的最近報告
        rep = rt.report(run_id)
        if rep is not None:
            return _report_summary(rep, full=True)
    pending = runner.pending_status(run_id)
    if pending:
        return {"run_id": run_id, "flow_id": pending[0], "status": pending[1]}
    row = FlowRun.objects.filter(pk=run_id).first() if len(run_id) >= 32 else None
    if row is None:
        return {"error": f"No run {run_id} in memory or in the stored history"}
    return _report_summary(row, full=True)


def h_list_sources(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from apps.vision.models import ImageSource
    from apps.vision.sources import source_info

    items = []
    for s in ImageSource.objects.all().order_by("name")[:MAX_ITEMS]:
        info = source_info(s)
        cfg = {k: v for k, v in (s.config or {}).items() if k not in ("password", "secret", "token")}
        items.append({"id": s.id, "name": s.name, "kind": s.kind, "group": s.group, "enabled": s.is_enabled, "config": _scalars(cfg, 12), "status": _scalars(info, 16)})
    return {"items": items}


def h_list_connections(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from apps.comm import writers
    from apps.comm.models import Connection

    labels = {k["kind"]: k for k in writers.kinds()}
    items = []
    for c in Connection.objects.all().order_by("name")[:MAX_ITEMS]:
        cfg = {k: v for k, v in (c.config or {}).items() if k not in ("password", "secret", "token", "api_key")}
        info = writers.connection_info(c)
        items.append({"id": c.id, "name": c.name, "kind": c.kind, "kind_label": (labels.get(c.kind) or {}).get("label", c.kind), "page": (labels.get(c.kind) or {}).get("section", ""),
                      "enabled": c.is_enabled, "config": _scalars(cfg, 12), "status": _scalars(info, 16)})
    return {"items": items}


def h_engine_status(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from django.conf import settings

    from apps.accounts.models import EngineLock
    from apps.vision import __version__
    from apps.vision.runner import runner

    cap = runner.capacity()
    return {"version": __version__, "station_id": settings.VISION.get("STATION_ID", ""), "lock": EngineLock.current().to_dict(),
            "workers": cap.get("max_workers"), "active": cap.get("active"), "busy_flows": cap.get("flows"), "max_queue_per_flow": cap.get("max_queue_per_flow")}


def h_my_permissions(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from apps.accounts import permissions

    role = getattr(p, "role", "")
    return {"kind": getattr(p, "kind", ""), "user": getattr(getattr(p, "user", None), "username", "") or "", "role": role,
            "allowed": [k for k in permissions.FEATURES if p.can(k)], "matrix": permissions.matrix(),
            "features": {k: v.get("label", k) for k, v in ((f["key"], f) for f in permissions.catalogue())}}


def h_list_plugins(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from apps.core import plugins

    return {"items": [{k: v for k, v in it.items() if k != "path"} for it in plugins.inventory()[:MAX_ITEMS]]}


def h_capture_clients(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from apps.vision.capture import hub as capture_hub

    items = []
    for c in capture_hub.hub.clients()[:MAX_ITEMS]:
        items.append({k: (v if not isinstance(v, list) else [_scalars(ch, 10) if isinstance(ch, dict) else ch for ch in v[:16]]) for k, v in c.items() if k in ("name", "version", "hostname", "local", "connected_s", "channels")})
    return {"listening": capture_hub.hub.is_listening() if hasattr(capture_hub.hub, "is_listening") else None, "items": items}


def h_search_docs(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    from apps.vision.agent import help as help_mod

    q = str(args.get("query") or "").strip()
    if not q:
        return {"error": "query is required"}
    hits = help_mod.search(q, k=5)
    return {"items": [{"title": s.title, "url": s.url, "kind": s.kind, "text": s.text[:600]} for s, _ in hits]}


def h_get_tool(p: Any, args: dict[str, Any]) -> dict[str, Any]:
    key = str(args.get("key") or "").strip()
    try:
        return {"key": key, "skill": skills.skill_text(key, getattr(p, "user", None))[:MAX_RESULT_CHARS]}
    except KeyError:
        return {"error": f"No tool '{key}'"}


LOOKUPS: list[Lookup] = [
    Lookup("list_flows", "List the inspection flows with version, node count, recipes, continuous state, statistics and the last run. Optional name filter.", _obj({"query": {"type": "string"}}), h_list_flows),
    Lookup("get_flow", "One flow in detail: its steps (id, type, label, enabled, scalar params), recipes, statistics and the last three runs.", _obj({"flow_id": {"type": "integer"}}, ["flow_id"]), h_get_flow),
    Lookup("get_run", "One run's report by run_id: status, error, outputs and every node's status and message.", _obj({"run_id": {"type": "string"}}, ["run_id"]), h_get_run, feature="flows.run"),
    Lookup("list_sources", "The image sources with kind, configuration (no secrets) and live status (connected, last error, fps).", _obj({}), h_list_sources, feature="sources"),
    Lookup("list_connections", "The integration connections (Modbus server/client, TCP, image push, plugins) with configuration (no secrets), live status and start errors.", _obj({}), h_list_connections, feature="connections"),
    Lookup("engine_status", "Platform version, station id, engine lock, worker pool and which flows are busy.", _obj({}), h_engine_status),
    Lookup("my_permissions", "The caller's role and allowed features, plus the role-permission matrix.", _obj({}), h_my_permissions),
    Lookup("list_plugins", "Folder plugins: what each file mounted, disabled ones and load errors.", _obj({}), h_list_plugins, feature="integration"),
    Lookup("capture_clients", "Connected capture clients and their camera channels.", _obj({}), h_capture_clients, feature="sources"),
    Lookup("search_docs", "Search the documentation and the interface map for a phrase (any language).", _obj({"query": {"type": "string"}}, ["query"]), h_search_docs),
    Lookup("get_tool", "A tool's full skill text: parameters, ports and tuning guidance.", _obj({"key": {"type": "string", "description": "tool type, e.g. blob"}}, ["key"]), h_get_tool),
]
LOOKUP_MAP: dict[str, Lookup] = {x.name: x for x in LOOKUPS}


def specs() -> list[dict[str, Any]]:
    return [x.schema() for x in LOOKUPS]


def dispatch(principal: Any, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """執行一個查詢；沒權限、找不到、例外都翻成 {"error"} 回給模型（不中斷）。"""
    spec = LOOKUP_MAP.get(name)
    if spec is None:
        return {"error": f"No lookup named '{name}'", "available": list(LOOKUP_MAP)}
    if spec.feature and not (principal is not None and principal.can(spec.feature)):
        return {"error": f"Not permitted: '{name}' needs the '{spec.feature}' feature, which the caller's role does not have. Tell the user which role can."}
    try:
        return spec.handler(principal, dict(args or {}))
    except Exception as exc:  # noqa: BLE001 - 錯誤回給模型
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:300]}"}
