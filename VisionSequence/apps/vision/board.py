"""看板配置：每條流程「現場要看哪幾個數字、哪一張影像」的設定，以及給看板（網頁的或整合端自建的）一次拿齊的資料。

VM 有拖拉式的運行界面設計器；現場真正需要的是「這條線要看哪幾個數」，不是排版自由——所以這裡是一份小設定：

    {
      "title": "",                       # 看板標題（空＝流程名）
      "image": "",                       # 顯示哪個節點的影像（節點 id；空＝該次 run 最後一張）
      "overlays": true,                  # 影像上疊標記
      "values": [                        # 要顯示的具名輸出，依序
        {"key": "width", "label": "Width", "unit": "mm", "decimals": 2, "low": 9.8, "high": 10.2}
      ],
      "variables": ["parts", "lot"],     # 要顯示的流程變數
      "show_verdict": true, "show_counts": true
    }

`build()` 把設定＋最新一次 run＋今日良率＋變數組成一包（`GET /flows/{id}/board`），整合端自己做 UI 時只要
輪詢這一個端點（或訂 SSE 再來拿），數值的公差判定也算好了（`ok` 欄），不必自己重算。
"""

from __future__ import annotations

import math
from typing import Any

from django.db.models import Sum
from django.utils import timezone

MAX_VALUES = 24
MAX_VARIABLES = 24
DEFAULT: dict[str, Any] = {"title": "", "image": "", "overlays": True, "values": [], "variables": [], "show_verdict": True, "show_counts": True}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def sanitize(raw: Any) -> dict[str, Any]:
    """壞掉的設定不該讓總覽頁炸掉：這裡吃任何東西，只留合法欄位。空 dict＝沒設定（看板用預設：全部具名輸出）。"""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    if raw.get("title"):
        out["title"] = str(raw["title"])[:80]
    if raw.get("image"):
        out["image"] = str(raw["image"])[:80]
    if "overlays" in raw:
        out["overlays"] = bool(raw["overlays"])
    values = []
    for item in (raw.get("values") or [])[:MAX_VALUES]:
        if isinstance(item, str):
            item = {"key": item}
        if not isinstance(item, dict) or not str(item.get("key") or "").strip():
            continue
        entry: dict[str, Any] = {"key": str(item["key"]).strip()[:80]}
        if item.get("label"):
            entry["label"] = str(item["label"])[:80]
        if item.get("unit"):
            entry["unit"] = str(item["unit"])[:16]
        decimals = _num(item.get("decimals"))
        if decimals is not None:
            entry["decimals"] = int(max(0, min(6, decimals)))
        low, high = _num(item.get("low")), _num(item.get("high"))
        if low is not None:
            entry["low"] = low
        if high is not None:
            entry["high"] = high
        values.append(entry)
    if values:
        out["values"] = values
    names = [str(n).strip()[:64] for n in (raw.get("variables") or [])[:MAX_VARIABLES] if str(n).strip()]
    if names:
        out["variables"] = names
    for flag in ("show_verdict", "show_counts"):
        if flag in raw:
            out[flag] = bool(raw[flag])
    return out


def effective(flow_board: Any) -> dict[str, Any]:
    return {**DEFAULT, **sanitize(flow_board)}


def _format(value: Any, decimals: int | None) -> str:
    if isinstance(value, bool):
        return "OK" if value else "NG"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if decimals is None:
            return str(value) if isinstance(value, int) else f"{value:.3f}".rstrip("0").rstrip(".")
        return f"{value:.{decimals}f}"
    if value is None:
        return ""
    return str(value)[:120]


def _pick_image(run: dict[str, Any] | None, node_id: str, graph: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """指定節點優先，否則用結果圖；沒有結果圖時用取像節點當底圖，標記疊全流程。"""
    if not run:
        return None, []
    nodes = run.get("nodes") or {}
    overlays = [o for n in nodes.values() for o in (n.get("overlays") or [])]
    graph_types = {
        str(n.get("id")): str(n.get("type") or "")
        for n in (graph or {}).get("nodes", [])
        if isinstance(n, dict)
    }

    def image_of(node: dict[str, Any]) -> dict[str, Any] | None:
        outputs = node.get("outputs") or {}
        for key in ("image", *[k for k in outputs if k != "_image"]):
            value = outputs.get(key)
            if isinstance(value, dict) and value.get("ref") and "width" in value:
                return {"ref": value["ref"], "width": value["width"], "height": value["height"]}
        return None

    def first_of_types(types: set[str]) -> dict[str, Any] | None:
        for nid, node in nodes.items():
            if graph_types.get(str(nid)) in types:
                found = image_of(node)
                if found:
                    return found
        return None

    if node_id and node_id in nodes:
        found = image_of(nodes[node_id])
        if found:
            return found, overlays
    found = first_of_types({"draw_result"})
    if found:
        return found, overlays
    found = first_of_types({"image_source", "fixed_image", "stereo_grab"})
    if found:
        return found, overlays
    for node in reversed(list(nodes.values())):
        found = image_of(node)
        if found:
            return found, overlays
    return None, overlays


def today_counts(flow_id: int) -> dict[str, Any]:
    """今日（本地日曆日）的 OK／NG／良率，讀每小時彙總——與統計頁、/summary 同一份數字。"""
    from apps.vision.models import FlowRunHourly

    now = timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    agg = FlowRunHourly.objects.filter(flow_id=flow_id, hour__gte=start).aggregate(ok=Sum("ok"), ng=Sum("ng"), failed=Sum("failed"))
    ok, ng, failed = int(agg.get("ok") or 0), int(agg.get("ng") or 0), int(agg.get("failed") or 0)
    total = ok + ng + failed
    return {"date": start.date().isoformat(), "total": total, "ok": ok, "ng": ng, "failed": failed,
            "yield": round(ok / total * 100, 1) if total else None}


def today_counts_many(flow_ids: set[int] | list[int] | tuple[int, ...]) -> dict[int, dict[str, Any]]:
    """一次彙總多個流程今日 OK/NG，供站台 Dashboard 避免逐流程查詢。"""
    from apps.vision.models import FlowRunHourly

    ids = sorted({int(fid) for fid in flow_ids if int(fid) > 0})
    if not ids:
        return {}
    now = timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = FlowRunHourly.objects.filter(flow_id__in=ids, hour__gte=start).values("flow_id").annotate(
        ok=Sum("ok"), ng=Sum("ng"), failed=Sum("failed")
    )
    out = {
        fid: {"date": start.date().isoformat(), "total": 0, "ok": 0, "ng": 0, "failed": 0, "yield": None}
        for fid in ids
    }
    for row in rows:
        fid = int(row["flow_id"])
        ok, ng, failed = int(row.get("ok") or 0), int(row.get("ng") or 0), int(row.get("failed") or 0)
        total = ok + ng + failed
        out[fid] = {
            "date": start.date().isoformat(), "total": total, "ok": ok, "ng": ng, "failed": failed,
            "yield": round(ok / total * 100, 1) if total else None,
        }
    return out


def build(flow: Any, run: dict[str, Any] | None, *, variables: dict[str, Any] | None = None, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """組看板資料。`run` 是 RunReport.to_dict(include_node_outputs=True)；沒有 run 也要回完整結構（等待中）。"""
    cfg = effective(getattr(flow, "board", None))
    outputs = (run or {}).get("outputs") or {}
    wanted = cfg["values"] or [{"key": k} for k in outputs if k not in ("judge", "judge_label")]
    values = []
    for item in wanted:
        key = item["key"]
        value = outputs.get(key)
        low, high = item.get("low"), item.get("high")
        ok: bool | None = None
        num = _num(value) if not isinstance(value, bool) else None
        if num is not None and (low is not None or high is not None):
            ok = (low is None or num >= low) and (high is None or num <= high)
        values.append({
            "key": key, "label": item.get("label") or key, "unit": item.get("unit", ""),
            "value": value, "text": _format(value, item.get("decimals")), "ok": ok,
            "low": low, "high": high, "present": key in outputs,
        })
    image, overlays = _pick_image(run, cfg["image"], getattr(flow, "graph", None))
    verdict = None
    if run:
        verdict = outputs.get("judge") or ("OK" if run.get("status") == "ok" else "NG" if run.get("status") == "ng" else str(run.get("status") or "").upper())
    shown_vars = {name: (variables or {}).get(name) for name in cfg["variables"]} if cfg["variables"] else dict(variables or {})
    return {
        "flow": {"id": flow.id, "name": flow.name, "title": cfg["title"] or flow.name},
        "config": cfg,
        "run": None if not run else {
            "id": run.get("id"), "status": run.get("status"), "verdict": verdict, "label": outputs.get("judge_label", ""),
            "started_at": run.get("started_at"), "duration_ms": run.get("duration_ms"), "trigger": run.get("trigger"),
            "recipe": run.get("recipe", ""), "error": run.get("error", ""),
            "image": image, "overlays": overlays if cfg["overlays"] else [],
        },
        "values": values,
        "variables": shown_vars,
        "counts": today_counts(flow.id) if cfg["show_counts"] else None,
        "stats": stats or {},
    }
