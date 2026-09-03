"""批次測試的檔案與序列化：影像存 ASSET_DIR/batch/<set_id>/NNN.png（Windows 中文路徑安全），
summary／命中率由 items 與影像集的期望標記現算，淘汰策略讀 VISION 設定。"""

from __future__ import annotations

import json
import math
import os
import shutil
import time
from typing import Any

import cv2
import numpy as np
from django.conf import settings as dj_settings

from apps.golden.regress import evaluate_expect
from apps.golden.regress import load_image as _load_path
from apps.vision.models import BatchRun, BatchSet, Flow
from apps.vision.tools import base as tools

#: 批次執行用的影像快取桶（每張跑完立即釋放，不與流程／助手的桶混用）。
BATCH_FLOW_ID = -1
EXPECTED_VALUES = ("", "ok", "ng")
RUN_TERMINAL = ("done", "cancelled", "failed")


def cfg(key: str, default: Any) -> Any:
    return dj_settings.VISION.get(key, default)


# ---------------------------------------------------------------------------
# 檔案
# ---------------------------------------------------------------------------
def batch_dir(set_id: int) -> str:
    return os.path.join(str(dj_settings.VISION["ASSET_DIR"]), "batch", str(set_id))


def save_images(batch_set: BatchSet, images: list[tuple[str, np.ndarray]]) -> list[dict[str, Any]]:
    """把影像寫進影像集資料夾並附到 images 清單；回新增的列。"""
    folder = batch_dir(batch_set.id)
    os.makedirs(folder, exist_ok=True)
    rows: list[dict[str, Any]] = []
    total = 0
    start = len(batch_set.images or [])
    for offset, (name, img) in enumerate(images):
        index = start + offset
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            continue
        path = os.path.join(folder, f"{index + 1:03d}.png")
        buf.tofile(path)
        rows.append({
            "index": index, "name": str(name or f"影像 {index + 1}")[:200], "path": path,
            "width": int(img.shape[1]), "height": int(img.shape[0]), "expected": "", "expect_outputs": {}, "note": "",
        })
        total += int(buf.size)
    batch_set.images = list(batch_set.images or []) + rows
    batch_set.image_count = len(batch_set.images)
    batch_set.size_bytes = int(batch_set.size_bytes or 0) + total
    batch_set.save(update_fields=["images", "image_count", "size_bytes", "updated_at"])
    return rows


def load_image(item: dict[str, Any] | None) -> np.ndarray | None:
    if not item or not item.get("path"):
        return None
    return _load_path(str(item["path"]))


def remove_set_files(batch_set: BatchSet) -> None:
    shutil.rmtree(batch_dir(batch_set.id), ignore_errors=True)


def image_by_index(batch_set: BatchSet, index: int) -> dict[str, Any] | None:
    for im in batch_set.images or []:
        if int(im.get("index", -1)) == index:
            return im
    return None


# ---------------------------------------------------------------------------
# 逐張結果
# ---------------------------------------------------------------------------
def scalar_outputs(outputs: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (outputs or {}).items():
        if isinstance(v, bool) or isinstance(v, (int, str)):
            out[k] = v
        elif isinstance(v, float):
            out[k] = round(v, 4) if math.isfinite(v) else None  # NaN／inf 不是合法 JSON（SQLite JSON_VALID 會擋）
    return out


def compact_row(index: int, report: Any) -> dict[str, Any]:
    nodes = {
        nid: {"status": nr.status, "duration_ms": round(float(nr.duration_ms), 2), "message": str(nr.message or "")[:160],
              "branch": nr.branch, "outputs": scalar_outputs(nr.outputs)}
        for nid, nr in report.nodes.items()
    }
    error_node = next((nid for nid, nr in report.nodes.items() if nr.status == "error"), None)
    return {
        "index": index, "status": report.status, "duration_ms": round(float(report.duration_ms), 2),
        "outputs": scalar_outputs(report.outputs), "error": str(report.error or "")[:300], "error_node": error_node, "nodes": nodes,
    }


def failed_row(index: int, message: str) -> dict[str, Any]:
    return {"index": index, "status": "failed", "duration_ms": 0.0, "outputs": {}, "error": message, "error_node": None, "nodes": {}}


def row_match(item: dict[str, Any], image: dict[str, Any] | None) -> tuple[bool | None, list[str]]:
    """對照影像的期望標記；沒標記回 (None, [])。"""
    expected = str((image or {}).get("expected") or "")
    if expected not in ("ok", "ng"):
        return None, []
    ok, reasons = evaluate_expect(expected, (image or {}).get("expect_outputs") or None, str(item.get("status", "")), item.get("outputs") or {})
    return bool(ok), list(reasons)


def summarize(items: list[dict[str, Any]], images: list[dict[str, Any]], wall_ms: float = 0.0) -> dict[str, Any]:
    by_index = {int(im.get("index", -1)): im for im in images}
    durations = [float(it.get("duration_ms") or 0) for it in items]
    labeled = match = tp = fp = tn = fn = 0
    for it in items:
        image = by_index.get(int(it.get("index", -1)))
        m, _ = row_match(it, image)
        if m is None:
            continue
        labeled += 1
        match += int(m)
        expected, status = str(image["expected"]), str(it.get("status", ""))
        if expected == "ng":
            tp += int(status == "ng")
            fn += int(status != "ng")
        else:
            tn += int(status == "ok")
            fp += int(status != "ok")
    total = len(items)
    return {
        "total": total, "ok": sum(1 for it in items if it.get("status") == "ok"), "ng": sum(1 for it in items if it.get("status") == "ng"),
        "failed": sum(1 for it in items if it.get("status") not in ("ok", "ng")),
        "avg_ms": round(sum(durations) / total, 2) if total else 0.0, "max_ms": round(max(durations), 2) if durations else 0.0,
        "wall_ms": round(float(wall_ms), 1), "labeled": labeled, "match": match, "match_rate": round(match / labeled, 4) if labeled else None,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------
def image_url(set_id: int, index: int) -> str:
    return f"/api/vision/batch/sets/{set_id}/images/{index}"


def run_flow(r: BatchRun) -> Flow:
    """一次執行實際用的流程：BatchRun.flow（跨流程測試）優先，否則影像集的流程。"""
    return r.flow or r.batch_set.flow


def set_out(s: BatchSet, *, full: bool = False, latest: BatchRun | None = None) -> dict[str, Any]:
    images = s.images or []
    out: dict[str, Any] = {
        "id": s.id, "flow_id": s.flow_id, "flow_name": s.flow.name if s.flow_id else "", "name": s.name, "source": s.source,
        "image_count": s.image_count, "size_bytes": s.size_bytes,
        "owner_id": s.owner_id, "labeled": {"ok": sum(1 for im in images if im.get("expected") == "ok"), "ng": sum(1 for im in images if im.get("expected") == "ng")},
        "created_at": s.created_at.isoformat() if s.created_at else None, "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
    if full:
        out["images"] = [{k: v for k, v in im.items() if k != "path"} | {"image_url": image_url(s.id, int(im["index"]))} for im in images]
    if latest is not None:
        out["latest_run"] = run_out(latest, batch_set=s)
    return out


def run_out(r: BatchRun, *, batch_set: BatchSet | None = None, items: bool = False, progress: dict[str, Any] | None = None,
            live_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    s = batch_set or r.batch_set
    prog = {"done": int(r.progress_done), "total": int(r.progress_total), "stage": ""}
    if progress:
        prog.update({k: progress[k] for k in ("done", "total", "stage") if k in progress})
    finished = r.finished_at.timestamp() if r.finished_at else None
    created = r.created_at.timestamp() if r.created_at else time.time()
    flow = r.flow or s.flow
    out: dict[str, Any] = {
        "id": r.id, "set_id": r.batch_set_id, "flow_id": flow.id, "flow_name": flow.name, "set_flow_id": s.flow_id,
        "flow_version": r.flow_version, "label": r.label, "note": r.note,
        "origin": r.origin, "status": r.status, "progress": prog, "summary": r.summary or {}, "parent_id": r.parent_id, "owner_id": r.owner_id,
        "recipe_name": r.recipe_name, "meta": r.meta or {}, "error": r.error,
        "created_at": r.created_at.isoformat() if r.created_at else None, "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "duration_s": round((finished or time.time()) - created, 1),
    }
    if items:
        by_index = {int(im.get("index", -1)): im for im in (s.images or [])}
        rows = []
        for it in (live_items if live_items is not None else (r.items or [])):
            image = by_index.get(int(it.get("index", -1)), {})
            m, reasons = row_match(it, image)
            rows.append({**it, "name": image.get("name", ""), "expected": image.get("expected", ""), "match": m, "reasons": reasons,
                         "image_url": image_url(s.id, int(it.get("index", -1)))})
        out["items"] = rows
        out["graph"] = r.graph
    return out


# ---------------------------------------------------------------------------
# 完成、重算、淘汰
# ---------------------------------------------------------------------------
def finalize_run(run: BatchRun, rows: list[dict[str, Any]], *, wall_ms: float, status: str = "done", graph: dict[str, Any] | None = None,
                 meta: dict[str, Any] | None = None) -> BatchRun:
    """寫入結果、summary、洞察快取，並淘汰該影像集多餘的舊執行。"""
    from apps.vision.batch import insights
    from django.utils import timezone

    batch_set = run.batch_set
    images = batch_set.images or []
    parent_items = parent_graph = None
    if run.parent_id:
        parent = BatchRun.objects.filter(pk=run.parent_id).only("items", "graph").first()
        if parent is not None:
            parent_items, parent_graph = parent.items, parent.graph
    run.items = rows
    if graph is not None:
        run.graph = graph
    if meta:
        run.meta = {**(run.meta or {}), **meta}
    run.summary = summarize(rows, images, wall_ms)
    run.insights = insights.compute(run.graph, rows, images, parent_items=parent_items, parent_graph=parent_graph)
    run.status = status
    run.progress_done = len(rows)
    run.progress_total = max(int(run.progress_total or 0), len(images))
    run.finished_at = timezone.now()
    run.save(update_fields=["items", "graph", "meta", "summary", "insights", "status", "progress_done", "progress_total", "finished_at"])
    prune_runs(batch_set)
    return run


def save_completed_run(batch_set: BatchSet, graph: dict[str, Any], rows: list[dict[str, Any]], *, origin: str, parent: BatchRun | None = None,
                       label: str = "", owner: Any = None, meta: dict[str, Any] | None = None, wall_ms: float = 0.0,
                       flow: Flow | None = None) -> BatchRun:
    """AI 調整等已在別處跑完的結果直接落成一筆 done 的執行（不重跑）。flow 給定＝沿用來源執行的測試流程。"""
    target = flow or batch_set.flow
    run = BatchRun.objects.create(
        batch_set=batch_set, flow=None if target.id == batch_set.flow_id else target, parent=parent,
        owner=owner if getattr(owner, "pk", None) else None, flow_version=target.version,
        graph=graph, label=label[:120], origin=origin, status="running", progress_total=batch_set.image_count,
    )
    return finalize_run(run, rows, wall_ms=wall_ms, status="done", graph=graph, meta=meta)


def persist_tune(batch_run_id: int, graph: dict[str, Any], items: list[dict[str, Any]], *, origin: str = "ai_tune", label: str = "",
                 owner: Any = None, meta: dict[str, Any] | None = None) -> BatchRun | None:
    """AI 調整（tune／autotune／代理）在持久化批次上跑完的逐張結果（service._rerun_items detail=True）落成新的一次執行。"""
    run = BatchRun.objects.select_related("batch_set__flow", "flow").filter(pk=batch_run_id).first()
    if run is None:
        return None
    rows = [{k: it.get(k) for k in ("index", "status", "duration_ms", "outputs", "error", "error_node", "nodes")}
            for it in items if it.get("index") is not None and isinstance(it.get("nodes"), dict)]
    if not rows:
        return None
    return save_completed_run(run.batch_set, graph, rows, origin=origin, parent=run, label=label, owner=owner, meta=meta, flow=run_flow(run))


def refresh_matches(batch_set: BatchSet) -> None:
    """期望標記改了：該影像集所有已完成的執行重算 summary 與洞察。"""
    from apps.vision.batch import insights

    images = batch_set.images or []
    runs = {r.id: r for r in batch_set.runs.filter(status="done")}
    for r in runs.values():
        parent = runs.get(r.parent_id) if r.parent_id else None
        r.summary = summarize(r.items or [], images, float((r.summary or {}).get("wall_ms") or 0))
        r.insights = insights.compute(r.graph, r.items or [], images, parent_items=parent.items if parent else None, parent_graph=parent.graph if parent else None)
        r.save(update_fields=["summary", "insights"])


def prune_sets(flow: Flow) -> int:
    keep = int(cfg("KEEP_BATCH_SETS", 10))
    victims = list(BatchSet.objects.filter(flow=flow).order_by("-created_at")[keep:])
    removed = 0
    for s in victims:
        if s.runs.filter(status__in=("queued", "running")).exists():
            continue
        remove_set_files(s)
        s.delete()
        removed += 1
    return removed


def prune_runs(batch_set: BatchSet) -> int:
    keep = int(cfg("KEEP_BATCH_RUNS", 20))
    victims = list(batch_set.runs.filter(status__in=RUN_TERMINAL).order_by("-created_at")[keep:])
    for r in victims:
        r.delete()
    return len(victims)


def delete_set(batch_set: BatchSet) -> None:
    remove_set_files(batch_set)
    batch_set.delete()


# ---------------------------------------------------------------------------
# graph 參數差異（存為配方／比較用）
# ---------------------------------------------------------------------------
def graph_param_diff(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """只比 params（忽略 position）；回 {rows:[{node,label,type,key,from,to}], added:[id], removed:[id]}。"""
    a = {n["id"]: n for n in (base or {}).get("nodes", []) if n.get("type") != "note"}
    b = {n["id"]: n for n in (other or {}).get("nodes", []) if n.get("type") != "note"}
    rows: list[dict[str, Any]] = []
    for nid in a.keys() & b.keys():
        pa, pb = a[nid].get("params") or {}, b[nid].get("params") or {}
        for key in sorted(pa.keys() | pb.keys()):
            if json.dumps(pa.get(key), sort_keys=True) != json.dumps(pb.get(key), sort_keys=True):
                rows.append({"node": nid, "label": b[nid].get("label") or a[nid].get("label") or nid, "type": b[nid].get("type"), "key": key,
                             "from": pa.get(key), "to": pb.get(key)})
    return {"rows": rows, "added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys())}


def to_overrides(diff: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in diff.get("rows", []):
        if tools.has(str(row.get("type", ""))) and any(p.key == row["key"] for p in tools.get(str(row["type"])).params):
            out.setdefault(row["node"], {})[row["key"]] = row["to"]
    return out


def reconcile(run: BatchRun) -> BatchRun:
    """伺服器重啟後殘留的 running：沒有對應背景工作就標成 failed。"""
    if run.status in ("queued", "running"):
        from apps.vision.batch import jobs
        from django.utils import timezone

        if jobs.progress(run.id) is None:
            run.status, run.error, run.finished_at = "failed", "伺服器重新啟動，執行中斷", timezone.now()
            run.save(update_fields=["status", "error", "finished_at"])
    return run
