"""回歸核心：API 與 `manage.py regress` 共用。

流程：載入每個 GoldenCase 的影像 → 非 preview 模式跑（不保留中間影像）→ 與期望值比對 →
與最新基準比對算 regressed／improved → 只對 mismatch 的 case 再跑一次 preview 取影像 ref（上限 MAX_MISMATCH_IMAGES）。

期望值判定（match）：
- expect_status = ok|ng 時狀態必須相同；any 不比對狀態
- expect_outputs 每個 key 都要存在且相符：{"value": v, "tol": t} → |now - v| <= t；否則等值（數值用 float 比較）
混淆矩陣以 expect_status 為真值（ng = 正例）；預測「不是 ok」（ng／failed）視為正例。expect_status=any 的 case 不計入。
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import cv2
import numpy as np
from django.conf import settings

from apps.golden.models import EXPECT_STATUSES, GoldenBaseline, GoldenCase
from apps.vision.models import Flow

MAX_MISMATCH_IMAGES = 20


# ---------------------------------------------------------------------------
# 影像檔
# ---------------------------------------------------------------------------
def golden_dir(flow_id: int) -> str:
    path = os.path.join(str(settings.VISION["ASSET_DIR"]), "golden", str(flow_id))
    os.makedirs(path, exist_ok=True)
    return path


def save_image(flow_id: int, image: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("The image could not be encoded as PNG")
    path = os.path.join(golden_dir(flow_id), f"{uuid.uuid4().hex}.png")
    buf.tofile(path)
    return path


def load_image(path: str) -> np.ndarray | None:
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def remove_image(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 比對
# ---------------------------------------------------------------------------
def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def output_matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict) and "value" in expected and ("tol" in expected or len(expected) == 1):
        target, tol = _num(expected.get("value")), _num(expected.get("tol", 0)) or 0.0
        got = _num(actual)
        if target is None:
            return expected.get("value") == actual
        return got is not None and abs(got - target) <= tol
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    e, a = _num(expected), _num(actual)
    if e is not None and a is not None:
        return abs(e - a) <= 1e-9
    return expected == actual


def evaluate_expect(expect_status: str, expect_outputs: dict[str, Any] | None, status: str, outputs: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """純函式版期望比對：(match, reasons)。Golden 回歸、AI 助手評測基準與自動調參共用。"""
    reasons: list[str] = []
    if expect_status in ("ok", "ng") and status != expect_status:
        reasons.append(f"status {status} != {expect_status}")
    for key, expected in (expect_outputs or {}).items():
        if key not in (outputs or {}):
            reasons.append(f"Missing output {key}")
        elif not output_matches(expected, outputs[key]):
            reasons.append(f"{key}={outputs[key]!r} does not match {expected!r}")
    return (not reasons), reasons


def evaluate(case: GoldenCase, status: str, outputs: dict[str, Any]) -> tuple[bool, list[str]]:
    """回 (match, reasons)。"""
    return evaluate_expect(case.expect_status, case.expect_outputs, status, outputs)


def normalize_expect_status(value: Any) -> str:
    v = str(value or "any").lower().strip()
    return v if v in EXPECT_STATUSES else "any"


# ---------------------------------------------------------------------------
# 回歸
# ---------------------------------------------------------------------------
def _culprit_node(report) -> tuple[str | None, str]:
    error_node = next((nid for nid, nr in report.nodes.items() if nr.status == "error"), None)
    if error_node:
        return error_node, report.error or report.nodes[error_node].message
    ng_node = next((nid for nid, nr in report.nodes.items() if nr.status == "ng"), None)
    return ng_node, (report.nodes[ng_node].message if ng_node else report.error)


def _source_ref(report) -> str | None:
    for nr in report.nodes.values():
        for v in nr.outputs.values():
            if isinstance(v, dict) and v.get("ref") and ":image" in v["ref"]:
                return v["ref"]
    return None


def run_regression(flow: Flow, *, graph: dict | None = None, save_baseline: bool = False, fail_under: float | None = None, max_images: int = MAX_MISMATCH_IMAGES) -> dict[str, Any]:
    from apps.vision.runner import runner

    cases = list(GoldenCase.objects.filter(flow=flow).order_by("id"))
    baseline = GoldenBaseline.latest_for(flow.id)
    base_results: dict[str, Any] = (baseline.results if baseline else {}) or {}
    t0 = time.perf_counter()
    rows: list[dict[str, Any]] = []
    reports: dict[int, Any] = {}
    new_results: dict[str, Any] = {}
    for case in cases:
        image = load_image(case.image_path)
        if image is None:
            status, outputs, duration, error, node = "failed", {}, 0.0, "The image file could not be read", None
        else:
            report = runner.run_sync(flow, trigger="regress", input_image=image, graph_override=graph)
            reports[case.id] = report
            status, outputs, duration = report.status, report.outputs, round(report.duration_ms, 2)
            node, error = _culprit_node(report)
        match, reasons = evaluate(case, status, outputs)
        prev = base_results.get(str(case.id))
        was_match: bool | None = None
        changed: bool | None = None
        if prev is not None:
            was_match, _ = evaluate(case, prev.get("status", ""), prev.get("outputs") or {})
            changed = prev.get("status") != status or (prev.get("outputs") or {}) != outputs
        new_results[str(case.id)] = {"status": status, "outputs": outputs, "duration_ms": duration}
        rows.append({
            "case_id": case.id, "name": case.name, "expect": case.expect_status, "expect_outputs": case.expect_outputs or {},
            "status": status, "outputs": outputs, "duration_ms": duration, "match": match, "reasons": reasons,
            "was": prev.get("status") if prev else None, "was_match": was_match, "changed_since_baseline": changed,
            "node": node, "error": error or "", "image_ref": None,
        })

    # mismatch 的 case 重跑 preview 取影像（上限）
    shown = 0
    for row in rows:
        if row["match"] or shown >= max_images or row["case_id"] not in reports:
            continue
        case = next(c for c in cases if c.id == row["case_id"])
        image = load_image(case.image_path)
        if image is None:
            continue
        try:
            pv = runner.run_sync(flow, trigger="preview", preview=True, input_image=image, graph_override=graph)
        except Exception:  # noqa: BLE001 — 影像只是輔助，不影響回歸結果
            continue
        row["image_ref"] = _source_ref(pv)
        row["preview_run_id"] = pv.id
        shown += 1

    regressed = [
        {"case_id": r["case_id"], "name": r["name"], "was": r["was"], "now": r["status"], "node": r["node"], "error": r["error"], "reasons": r["reasons"]}
        for r in rows if r["was_match"] is True and not r["match"]
    ]
    improved = [
        {"case_id": r["case_id"], "name": r["name"], "was": r["was"], "now": r["status"], "node": r["node"], "error": ""}
        for r in rows if r["was_match"] is False and r["match"]
    ]
    confusion = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for r in rows:
        if r["expect"] not in ("ok", "ng"):
            continue
        truth_pos = r["expect"] == "ng"
        pred_pos = r["status"] != "ok"
        key = ("tp" if truth_pos else "fp") if pred_pos else ("fn" if truth_pos else "tn")
        confusion[key] += 1

    total = len(rows)
    match = sum(r["match"] for r in rows)
    rate = (match / total) if total else 1.0
    result: dict[str, Any] = {
        "flow_id": flow.id, "flow_name": flow.name, "flow_version": flow.version, "graph_override": graph is not None,
        "total": total, "match": match, "mismatch": total - match, "match_rate": round(rate, 4),
        "regressed": regressed, "improved": improved, "confusion": confusion,
        "cases": rows, "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        "baseline_version": baseline.flow_version if baseline else None,
        "baseline_at": baseline.created_at.isoformat() if baseline else None,
        "fail_under": fail_under, "passed": (fail_under is None) or (rate >= fail_under),
        "baseline_saved": False,
    }
    if save_baseline:
        nb = GoldenBaseline.objects.create(flow=flow, flow_version=flow.version, results=new_results)
        result["baseline_saved"] = True
        result["baseline_version"] = nb.flow_version
        result["baseline_at"] = nb.created_at.isoformat()
    return result


def baseline_out(b: GoldenBaseline | None) -> dict[str, Any] | None:
    if b is None:
        return None
    return {"id": b.id, "flow_id": b.flow_id, "flow_version": b.flow_version, "results": b.results, "created_at": b.created_at.isoformat(), "case_count": len(b.results or {})}
