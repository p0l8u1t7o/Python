"""記憶與學習：每次 AI 助手生成存成工作階段（AgentSession），依影像特徵找相似的成功案例當先驗。

先驗用在三處：規則引擎 teach 參數（synth.candidates(priors=)）、自動調參的第一批候選（autotune priors）、
LLM／代理的「過去成功案例」段（examples_text）。成功＝影像標記全部命中或使用者按讚；按倒讚的不當先驗。
影像存在 ASSET_DIR/agent/<session_id>/NN.png；restore 時重新放進影像快取（pinned）。存檔一律 best-effort，失敗只記 log。
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
from typing import Any

import cv2
import numpy as np
from django.conf import settings as dj_settings
from django.db.models import Q

from apps.vision.models import AgentSession
from apps.vision.tools import base as tools

log = logging.getLogger("vision.agent")

#: 特徵向量各維度（都正規化到 0～1 上下）。
FEATURE_KEYS = ("mean", "std", "mad", "edge_ratio", "dark_ratio", "h", "s", "v", "log_area")
SIMILAR_MAX_DIST = 0.35
SIMILAR_LIMIT = 2
SCAN_LIMIT = 300


def session_dir(session_id: int) -> str:
    return os.path.join(str(dj_settings.VISION["ASSET_DIR"]), "agent", str(session_id))


def feature_vector(analysis: dict[str, Any] | None) -> list[float]:
    """第一個 ROI（沒有就整張）的特徵向量。"""
    if not analysis:
        return []
    rows = analysis.get("regions") or []
    info = rows[0] if rows and not rows[0].get("empty") else (analysis.get("full") or {})
    dom = info.get("dominant") or {}
    area = float(info.get("area") or (float(analysis.get("width", 1)) * float(analysis.get("height", 1))))
    vec = (
        float(info.get("mean", 128)) / 255, float(info.get("std", 0)) / 64, float(info.get("mad", 0)) / 64,
        float(info.get("edge_ratio", 0)), float(info.get("dark_ratio", 0)),
        float(dom.get("h", 0)) / 180, float(dom.get("s", 0)) / 255, float(dom.get("v", 0)) / 255,
        math.log10(max(1.0, area)) / 7,
    )
    return [round(x, 4) for x in vec]


def distance(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return float("inf")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _save_images(session_id: int, images: list[np.ndarray], names: list[str] | None) -> list[dict[str, Any]]:
    folder = session_dir(session_id)
    os.makedirs(folder, exist_ok=True)
    out = []
    for i, im in enumerate(images):
        ok, buf = cv2.imencode(".png", im)
        if not ok:
            continue
        path = os.path.join(folder, f"{i + 1:02d}.png")
        buf.tofile(path)
        out.append({"path": path, "name": (names[i] if names and i < len(names) else f"影像 {i + 1}"), "width": int(im.shape[1]), "height": int(im.shape[0])})
    return out


def success_of(statuses: list[str], labels: list[str]) -> bool | None:
    pairs = [(s, lb) for s, lb in zip(statuses, labels) if lb in ("ok", "ng")]
    if not pairs:
        return None
    return all(s == lb for s, lb in pairs)


def remember(*, owner: Any, task: str, prompt: str, intent_kind: str, images: list[np.ndarray], regions: list[dict[str, Any]],
             answers: list[dict[str, Any]], labels: list[str], analysis: dict[str, Any] | None, graph: dict[str, Any], rationale: str,
             candidates: list[dict[str, Any]], statuses: list[str], provider: str, mode: str = "single", turns: int = 0,
             names: list[str] | None = None) -> AgentSession | None:
    """存一個工作階段；任何失敗（磁碟、DB 鎖）只記 log 回 None，不影響生成結果。"""
    try:
        session = AgentSession.objects.create(
            owner=owner if getattr(owner, "pk", None) else None, task=task, prompt=prompt[:4000], intent=intent_kind, provider=provider, mode=mode, turns=turns,
            regions=regions, answers=answers, labels=labels, features={"vector": feature_vector(analysis), "image_count": len(images)},
            graph=graph, rationale=rationale[:4000], statuses=statuses, success=success_of(statuses, labels),
            candidates=[{k: c.get(k) for k in ("key", "label", "statuses", "score", "chosen")} for c in candidates],
        )
        session.images = _save_images(session.id, images, names)
        session.save(update_fields=["images"])
        return session
    except Exception:  # noqa: BLE001 - 記憶是加分項，不能讓生成失敗
        log.warning("AgentSession 儲存失敗", exc_info=True)
        return None


def forget(session: AgentSession) -> None:
    shutil.rmtree(session_dir(session.id), ignore_errors=True)
    session.delete()


def find_similar(intent_kind: str, analysis: dict[str, Any] | None, *, exclude_id: int | None = None, limit: int = SIMILAR_LIMIT) -> list[tuple[AgentSession, float]]:
    """同意圖、成功（標記全中或按讚）、特徵距離最近的 ≤limit 個工作階段。"""
    vec = feature_vector(analysis)
    if not vec:
        return []
    try:
        qs = AgentSession.objects.filter(intent=intent_kind).filter(Q(success=True) | Q(rating__gt=0)).exclude(rating__lt=0).order_by("-created_at")[:SCAN_LIMIT]
        rows: list[tuple[AgentSession, float]] = []
        for s in qs:
            if exclude_id is not None and s.id == exclude_id:
                continue
            fv = (s.features or {}).get("vector") if isinstance(s.features, dict) else None
            if not fv:
                continue
            d = distance(vec, [float(x) for x in fv])
            if d <= SIMILAR_MAX_DIST:
                rows.append((s, round(d, 4)))
    except Exception:  # noqa: BLE001
        log.warning("找相似工作階段失敗", exc_info=True)
        return []
    rows.sort(key=lambda r: r[1])
    return rows[:limit]


def priors_from_graph(graph: dict[str, Any]) -> dict[tuple[str, str], Any]:
    """成功流程裡的現場調機參數（(工具型別, 參數) → 值），只取數值／範圍／選項／布林。"""
    out: dict[tuple[str, str], Any] = {}
    for n in (graph or {}).get("nodes", []):
        t = str(n.get("type", ""))
        if not tools.has(t):
            continue
        params = n.get("params") or {}
        for p in tools.get(t).params:
            if getattr(p, "teach", False) and p.kind in ("number", "range", "select", "boolean") and p.key in params:
                out[(t, p.key)] = params[p.key]
    return out


def priors_from_sessions(rows: list[tuple[AgentSession, float]]) -> dict[tuple[str, str], Any]:
    """最近的優先（先套遠的再讓近的覆蓋）。"""
    out: dict[tuple[str, str], Any] = {}
    for s, _ in sorted(rows, key=lambda r: -r[1]):
        out.update(priors_from_graph(s.graph))
    return out


def apply_priors(graph: dict[str, Any], priors: dict[tuple[str, str], Any]) -> tuple[dict[str, Any], list[str]]:
    g = json.loads(json.dumps(graph))
    changed: list[str] = []
    for n in g.get("nodes", []):
        t = str(n.get("type", ""))
        params = n.setdefault("params", {})
        for (pt, key), val in priors.items():
            if pt != t or key not in params:
                continue
            if params[key] != val:
                changed.append(f"{n.get('label') or n['id']}.{key}: {params[key]} → {val}")
                params[key] = val
    return g, changed


def examples_text(rows: list[tuple[AgentSession, float]]) -> str:
    """給 LLM／代理的「過去成功案例」段。"""
    if not rows:
        return ""
    lines = ["# 過去成功案例（影像特徵相似，可沿用其設計與參數）"]
    for s, d in rows:
        params = {f"{t}.{k}": v for (t, k), v in priors_from_graph(s.graph).items()}
        types = [n.get("type") for n in (s.graph or {}).get("nodes", []) if n.get("type") not in ("note",)]
        lines.append(f"- #{s.id}（{s.created_at:%Y-%m-%d}，意圖 {s.intent}，特徵距離 {d}）：需求「{s.prompt[:80]}」；流程 {' → '.join(types)[:200]}；"
                     f"關鍵參數 {json.dumps(params, ensure_ascii=False)[:300]}；理由「{s.rationale[:160]}」")
    return "\n".join(lines)


def session_out(s: AgentSession, *, full: bool = False) -> dict[str, Any]:
    base = {
        "id": s.id, "owner_id": s.owner_id, "task": s.task, "prompt": s.prompt, "intent": s.intent, "provider": s.provider, "mode": s.mode, "turns": s.turns,
        "image_count": len(s.images or []), "statuses": s.statuses, "labels": s.labels, "success": s.success, "rating": s.rating, "note": s.note,
        "flow_id": s.flow_id, "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat(),
    }
    if full:
        base.update({"images": s.images, "regions": s.regions, "answers": s.answers, "graph": s.graph, "rationale": s.rationale, "candidates": s.candidates, "features": s.features})
    return base


def load_images(s: AgentSession) -> list[tuple[dict[str, Any], np.ndarray]]:
    out = []
    for item in s.images or []:
        try:
            data = np.fromfile(item["path"], dtype=np.uint8)
        except OSError:
            continue
        img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
        if img is not None:
            out.append((item, img))
    return out
