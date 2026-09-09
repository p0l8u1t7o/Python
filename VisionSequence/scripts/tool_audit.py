"""工具體檢：把每個內建工具丟進「輸入矩陣」找執行錯誤與明顯的 bug。

用法：
    .venv/Scripts/python.exe scripts/tool_audit.py                 # 全部工具，摘要印到 stdout
    .venv/Scripts/python.exe scripts/tool_audit.py -o out.txt      # 另存完整報告
    .venv/Scripts/python.exe scripts/tool_audit.py --tools blob,caliper --verbose

以 `scripts/bench_tools.py` 的 `cases()`（每個工具一組合理的參數與輸入）為基底，對每個案例展開變體：
- 影像尺寸：640×480（基準）、1001×701（奇數，ROI 裁切最常見）；另把基準案例的影像縮到 64×48 而參數不動（ROI 整個出界）
- 位深：u16、f32（工具要能自動正規化或宣告 accepts）
- 通道：灰階給彩色案例、彩色給灰階案例
- 常數影像：全黑、全白、雜訊（沒有東西可找時要回 ng／not_found，不能炸）
- ROI：半出界、1×1、完全出界（有 `roi` 參數的工具）
- 輸入埠：選填輸入逐一不接；必填影像不接（應該是 ToolError 不是 AttributeError）
- 參數：每個 select 的每個選項；數字參數的上下界；文字參數空字串

判定（只抓「工具自己的 bug」，不抓演算法品質）：
- BUG：非 ToolError 的例外（AttributeError／IndexError／ValueError／cv2.error…）
- TYPE：輸出值型別與宣告的輸出埠型別不符（image 埠給了 list、number 埠給了 ndarray…）
- NAN-OK：狀態是 ok 卻給出 NaN／inf 的數值（找不到東西時回 NaN 並判 ng 是慣例，不算）
- OVERLAY：標記座標含 NaN／inf，或落在影像外超過一個影像的距離
- STATUS：`Result.status` 不在 ok／ng／error
- SLOW：單次超過 5 秒
每個 (工具, 類別, 例外型別, 訊息開頭) 只記一次，並保留第一個重現用的變體描述。
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import time
import traceback
from collections import defaultdict
from typing import Any

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DATA_DIR", os.path.join(tempfile.gettempdir(), "vs-tool-audit-data"))

import django  # noqa: E402

django.setup()

from apps.vision.tools import base  # noqa: E402
from apps.vision.tools.base import ToolError  # noqa: E402
from bench_tools import Scene, cases, make_ctx  # noqa: E402

SLOW_S = 5.0
#: 已知且刻意的「狀態 ok 但數值是 NaN」：這兩個代表「沒有這個資訊」而不是失敗（測試鎖住），不列為問題
KNOWN_NAN_OK = {("undistort", "mm_per_pixel"), ("variable_get", "number")}
#: 輸出埠型別 → 允許的 Python 型別（None 一律允許：工具沒找到東西就不填）
PORT_PY_TYPES: dict[str, tuple[type, ...]] = {
    "image": (np.ndarray,),
    "number": (int, float, np.integer, np.floating),
    "bool": (bool, np.bool_),
    "string": (str,),
    "points": (list, tuple, np.ndarray),
    "contours": (list, tuple),
    "matches": (list, tuple),
    "region": (dict,),
    "list": (list, tuple),
    "json": (dict, list, tuple, str, int, float, bool),
}


class Finding:
    __slots__ = ("tool", "kind", "head", "variant", "trace", "count")

    def __init__(self, tool: str, kind: str, head: str, variant: str, trace: str) -> None:
        self.tool, self.kind, self.head, self.variant, self.trace, self.count = tool, kind, head, variant, trace, 1


class Audit:
    def __init__(self, verbose: bool = False) -> None:
        self.findings: dict[tuple[str, str, str], Finding] = {}
        self.runs = 0
        self.per_tool_runs: dict[str, int] = defaultdict(int)
        self.verbose = verbose

    def note(self, tool: str, kind: str, head: str, variant: str, trace: str = "") -> None:
        key = (tool, kind, head[:120])
        if key in self.findings:
            self.findings[key].count += 1
            return
        self.findings[key] = Finding(tool, kind, head, variant, trace)
        if self.verbose:
            print(f"  [{kind}] {tool} @ {variant}: {head[:160]}")

    # ---- 執行一個變體 ----
    def run(self, name: str, key: str, image: np.ndarray | None, params: dict[str, Any], inputs: dict[str, Any], assets: dict[str, str], context: dict[str, Any], variant: str) -> None:
        tool = base.get(key)
        self.runs += 1
        self.per_tool_runs[key] += 1
        ctx = make_ctx(key, image, params, inputs, assets, context)
        t0 = time.perf_counter()
        try:
            result = tool.execute(ctx)
        except ToolError:
            return  # 可預期的失敗：工具自己講清楚了
        except Exception as exc:  # noqa: BLE001
            self.note(key, "BUG", f"{type(exc).__name__}: {exc}", f"{name} | {variant}", traceback.format_exc(limit=6))
            return
        elapsed = time.perf_counter() - t0
        if elapsed > SLOW_S:
            self.note(key, "SLOW", f"{elapsed:.1f} s", f"{name} | {variant}")
        self.check_result(key, tool, result, image, f"{name} | {variant}")

    def check_result(self, key: str, tool: Any, result: Any, image: np.ndarray | None, variant: str) -> None:
        status = getattr(result, "status", None)
        if status not in ("ok", "ng", "error"):
            self.note(key, "STATUS", f"status={status!r}", variant)
        branch = getattr(result, "branch", None)
        if branch is not None and not isinstance(branch, str):
            self.note(key, "TYPE", f"branch is {type(branch).__name__}", variant)
        declared = {p.key: p.type for p in getattr(tool, "outputs", [])}
        outputs = getattr(result, "outputs", {}) or {}
        if not isinstance(outputs, dict):
            self.note(key, "TYPE", f"outputs is {type(outputs).__name__}", variant)
            return
        for okey, value in outputs.items():
            ptype = declared.get(okey)
            if value is None or ptype is None or ptype not in PORT_PY_TYPES:
                continue
            if ptype == "number" and isinstance(value, (bool, np.bool_)):
                continue  # 布林當數字用是常見的判定輸出
            if not isinstance(value, PORT_PY_TYPES[ptype]):
                self.note(key, "TYPE", f"output '{okey}' declared {ptype} but got {type(value).__name__}", variant)
            elif ptype == "image":
                arr = value
                if arr.ndim not in (2, 3) or arr.size == 0:
                    self.note(key, "TYPE", f"output '{okey}' image shape {arr.shape}", variant)
            elif ptype == "number" and isinstance(value, (float, np.floating)) and not math.isfinite(float(value)) and status == "ok" and branch in (None, "ok", "pass", "found") and (key, okey) not in KNOWN_NAN_OK:
                # 找不到東西時回 NaN 是平台慣例（status=ng 或走 not_found 分支）；狀態說 ok 卻給 NaN 才是問題
                self.note(key, "NAN-OK", f"output '{okey}' is {value} while status=ok branch={branch}", variant)
        h, w = (image.shape[:2] if isinstance(image, np.ndarray) else (10_000, 10_000))
        limit = max(h, w) * 2.0
        if max(h, w) < 100:
            limit = 10_000.0  # 縮到 64×48 的變體：ROI 標記照樣畫在使用者設定的位置（落在影像外是預期），只看 NaN
        for ov in getattr(result, "overlays", []) or []:
            if not isinstance(ov, dict):
                self.note(key, "OVERLAY", f"overlay is {type(ov).__name__}", variant)
                continue
            for nkey in ("x", "y", "w", "h", "cx", "cy", "r", "x1", "y1", "x2", "y2", "angle"):
                v = ov.get(nkey)
                if v is None:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    self.note(key, "OVERLAY", f"overlay {ov.get('kind')} field {nkey} is {type(v).__name__}", variant)
                    continue
                if not math.isfinite(fv):
                    self.note(key, "OVERLAY", f"overlay {ov.get('kind')} field {nkey} is {fv}", variant)
                elif nkey in ("x", "y", "cx", "cy", "x1", "y1", "x2", "y2") and abs(fv) > limit + 10:
                    self.note(key, "OVERLAY", f"overlay {ov.get('kind')} {nkey}={fv:.0f} far outside {w}x{h} (status={status} branch={branch})", variant)
            pts = ov.get("points")
            if pts is not None:
                try:
                    arr = np.asarray(pts, dtype=np.float64)
                    if arr.size and not np.isfinite(arr).all():
                        self.note(key, "OVERLAY", f"overlay {ov.get('kind')} points contain NaN/inf", variant)
                except (TypeError, ValueError):
                    self.note(key, "OVERLAY", f"overlay {ov.get('kind')} points not numeric", variant)


# ---- 變體產生 ----
def _as_u16(img: np.ndarray) -> np.ndarray:
    return (img.astype(np.uint16) * 257).astype(np.uint16)


def _as_f32(img: np.ndarray) -> np.ndarray:
    return (img.astype(np.float32) / 255.0).astype(np.float32)


def _other_channels(img: np.ndarray) -> np.ndarray:
    import cv2

    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _roi_variants(params: dict[str, Any], w: int, h: int) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    roi = params.get("roi")
    if not isinstance(roi, dict) or "shape" not in roi:
        return out
    shape = roi.get("shape")
    if shape == "rect":
        rw, rh = float(roi.get("w", 10)), float(roi.get("h", 10))
        out.append(("roi half outside", {**params, "roi": {**roi, "x": w - rw / 2, "y": h - rh / 2}}))
        out.append(("roi 1x1", {**params, "roi": {**roi, "w": 1, "h": 1}}))
        out.append(("roi fully outside", {**params, "roi": {**roi, "x": w + 5, "y": h + 5}}))
    elif shape == "rotated_rect":
        out.append(("roi half outside", {**params, "roi": {**roi, "cx": w, "cy": h}}))
        out.append(("roi 1x1", {**params, "roi": {**roi, "w": 1, "h": 1}}))
    elif shape == "circle":
        out.append(("roi half outside", {**params, "roi": {**roi, "cx": w, "cy": h}}))
        out.append(("roi r=0.5", {**params, "roi": {**roi, "r": 0.5}}))
    elif shape == "annulus":
        out.append(("roi half outside", {**params, "roi": {**roi, "cx": w, "cy": h}}))
    elif shape == "line":
        out.append(("roi half outside", {**params, "roi": {**roi, "x2": w + 50, "y2": h + 50}}))
        out.append(("roi zero length", {**params, "roi": {**roi, "x2": roi.get("x1"), "y2": roi.get("y1")}}))
    elif shape == "polygon":
        pts = roi.get("points") or []
        out.append(("roi half outside", {**params, "roi": {**roi, "points": [[float(x) + w / 2, float(y) + h / 2] for x, y in pts]}}))
    return out


def _param_variants(tool: Any, params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for p in getattr(tool, "params", []):
        if p.kind == "select":
            for opt in p.options or []:
                val = opt.get("value") if isinstance(opt, dict) else opt
                if val is None or params.get(p.key) == val:
                    continue
                out.append((f"{p.key}={val}", {**params, p.key: val}))
        elif p.kind in ("number", "range"):
            if p.minimum is not None:
                out.append((f"{p.key}=min({p.minimum})", {**params, p.key: p.minimum}))
            if p.maximum is not None:
                out.append((f"{p.key}=max({p.maximum})", {**params, p.key: p.maximum}))
            if p.minimum is None and p.maximum is None:
                out.append((f"{p.key}=0", {**params, p.key: 0}))
        elif p.kind in ("text", "multiline", "expression"):
            if params.get(p.key) not in ("", None):
                out.append((f"{p.key}=''", {**params, p.key: ""}))
        elif p.kind == "boolean":
            out.append((f"{p.key}={not bool(params.get(p.key, p.default))}", {**params, p.key: not bool(params.get(p.key, p.default))}))
    return out


def audit(only: set[str] | None, verbose: bool) -> Audit:
    a = Audit(verbose)
    folder = tempfile.mkdtemp(prefix="vs-tool-audit-")
    scenes: list[tuple[str, Scene]] = []
    for label, (w, h) in (("640x480", (640, 480)), ("1001x701", (1001, 701))):
        try:
            scenes.append((label, Scene(w, h, folder)))
        except Exception as exc:  # noqa: BLE001
            print(f"scene {label} unavailable: {type(exc).__name__}: {exc}")
    rng = np.random.default_rng(11)
    for label, scene in scenes:
        for name, key, image, params, inputs, context in cases(scene):
            if only and key not in only:
                continue
            tool = base.get(key)
            if tool is None:
                continue
            assets = scene.assets
            base_variant = f"{label}"
            a.run(name, key, image, params, inputs, assets, context, base_variant)
            if label != "640x480":
                continue  # 其餘變體只在基準尺寸展開，避免組合爆炸
            if isinstance(image, np.ndarray):
                h, w = image.shape[:2]
                a.run(name, key, _as_u16(image), params, inputs, assets, context, "u16 image")
                a.run(name, key, _as_f32(image), params, inputs, assets, context, "f32 image")
                a.run(name, key, _other_channels(image), params, inputs, assets, context, "other channel count")
                import cv2

                a.run(name, key, cv2.resize(image, (64, 48), interpolation=cv2.INTER_AREA), params, inputs, assets, context, "tiny 64x48 image (params unchanged)")
                a.run(name, key, np.zeros_like(image), params, inputs, assets, context, "all-black image")
                a.run(name, key, np.full_like(image, 255), params, inputs, assets, context, "all-white image")
                a.run(name, key, rng.integers(0, 256, image.shape, np.uint8), params, inputs, assets, context, "noise image")
                for vname, vparams in _roi_variants(params, w, h):
                    a.run(name, key, image, vparams, inputs, assets, context, vname)
                # 必填影像不接
                a.run(name, key, None, params, inputs, assets, context, "image not wired")
            for ikey in list(inputs.keys()):
                a.run(name, key, image, params, {k: v for k, v in inputs.items() if k != ikey}, assets, context, f"input '{ikey}' not wired")
            for vname, vparams in _param_variants(tool, params):
                a.run(name, key, image, vparams, inputs, assets, context, vname)
    return a


def report(a: Audit) -> str:
    lines = [f"tool audit: {a.runs} runs over {len(a.per_tool_runs)} tools, {len(a.findings)} distinct findings"]
    by_kind: dict[str, int] = defaultdict(int)
    for f in a.findings.values():
        by_kind[f.kind] += 1
    lines.append("  " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    for tool in sorted({f.tool for f in a.findings.values()}):
        lines.append(f"\n== {tool} ==")
        for f in sorted((f for f in a.findings.values() if f.tool == tool), key=lambda f: (f.kind, f.head)):
            lines.append(f"  [{f.kind}] x{f.count}  {f.head[:200]}")
            lines.append(f"      first seen: {f.variant}")
            if f.trace:
                tail = [ln for ln in f.trace.strip().splitlines() if ln.strip()][-4:]
                for ln in tail:
                    lines.append("      | " + ln.rstrip()[:200])
    lines.append("\nTOOL-AUDIT-DONE findings=%d bugs=%d" % (len(a.findings), by_kind.get("BUG", 0)))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="")
    ap.add_argument("--tools", default="", help="逗號分隔，只體檢這些工具")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    only = {t.strip() for t in args.tools.split(",") if t.strip()} or None
    a = audit(only, args.verbose)
    text = report(a)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
