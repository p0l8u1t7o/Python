"""對話的檢測清單提案；確認以前不碰流程圖，產圖只經核心翻譯器。"""

from __future__ import annotations

import copy
import math
import re
import uuid
from typing import Any

import cv2
import numpy as np

from apps.core.errors import APIError
from apps.vision import inspect
from apps.vision.agent import analysis, clarify, llm
from apps.vision.tasks import all as all_definitions

TaskDraft = dict[str, Any]
NUMBER = r"[-+]?\d+(?:\.\d+)?"
KINDS = (
    ("inspect_circular_surface", r"圓周|圆周|外圈缺口|circular surface|circumferential|rim notch"),
    ("inspect_edge_defect", r"邊緣缺陷|边缘缺陷|毛邊|毛边|edge defect|burr"),
    ("measure_distance", r"距離|距离|間距|间距|孔距|邊距|边距|distance|spacing|gap|hole centres|hole centers"),
    ("measure_diameter", r"外徑|外径|內徑|内径|直徑|直径|真圓度|真圆度|diameter|roundness"),
    ("locate_part", r"定位|locate|localize|position part"),
    ("count_objects", r"數量|数量|計數|计数|數數|count"),
    ("check_presence", r"有無|有无|缺件|異物|异物|有沒有|有没有|presence|missing part|foreign object|absence"),
    ("read_and_verify", r"讀碼|读码|讀取|读取|字元|字符|讀字|读字|barcode|\bocr\b|character|read code|read text"),
)


def catalogue(kinds=None) -> dict[str, dict]:
    rows = kinds if kinds is not None else all_definitions()
    return {r["kind"]: r for item in rows for r in [item.as_dict() if hasattr(item, "as_dict") else item]}


def cell(value=None, status="assumed", source="default", note="") -> dict:
    return {"value": value, "status": status, "source": source, "note": note}


def visible(spec: dict, values: dict, specs: dict) -> bool:
    return all(values.get(k, specs[k].get("default")) in (v if isinstance(v, list) else [v])
               for k, v in (spec.get("visible_when") or {}).items())


def valid(spec: dict, value: Any) -> bool:
    """提案的每個欄位都依核心目錄檢查；不信任供應商或客戶端的型別。"""
    if value is None:
        return False
    kind = spec["kind"]
    if kind in ("number", "range"):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            return False
        return (spec.get("minimum") is None or value >= spec["minimum"]) and (spec.get("maximum") is None or value <= spec["maximum"])
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "select":
        return value in [o["value"] for o in spec.get("options", [])]
    if kind == "roi":
        if not isinstance(value, dict) or value.get("shape") not in spec.get("shapes", []):
            return False
        keys = {"rect": ("x", "y", "w", "h"), "rotated_rect": ("cx", "cy", "w", "h", "angle"),
                "circle": ("cx", "cy", "r"), "annulus": ("cx", "cy", "r_inner", "r_outer")}.get(value["shape"])
        if not keys or any(isinstance(value.get(k), bool) or not isinstance(value.get(k), (int, float)) or not math.isfinite(value[k]) for k in keys):
            return False
        return all(value[k] > 0 for k in keys if k in ("w", "h", "r", "r_outer")) and (value["shape"] != "annulus" or 0 <= value["r_inner"] < value["r_outer"])
    if kind == "images":
        return isinstance(value, list) and all(isinstance(v, dict) for v in value)
    if kind == "json":
        return isinstance(value, (dict, list))
    if kind == "multiselect":
        return isinstance(value, list) and all(v in [o["value"] for o in spec.get("options", [])] for v in value)
    return isinstance(value, str) and (not spec.get("required") or bool(value.strip()))


def _calibrations(graph: dict) -> list[str]:
    return sorted({str(n.get("params", {}).get("calibration")) for n in graph.get("nodes", []) if n.get("params", {}).get("calibration")})


def _finish(draft: TaskDraft, cat: dict, graph: dict, *, defaults: bool = True) -> TaskDraft:
    specs = {f["key"]: f for f in cat[draft["kind"]]["fields"]}
    fields = draft["fields"]
    if defaults and draft["op"] == "add":
        for key, spec in specs.items():
            if key not in fields and (spec.get("required") or key in ("unit", "mode", "method", "nominal", "lower_tol", "upper_tol", "min_count", "max_count", "expected")):
                value = spec.get("default")
                fields[key] = cell(value, "assumed" if value not in (None, "", []) else "missing", note="Confirm the proposed default." if value not in (None, "", []) else "Provide this field.")
    for key, item in fields.items():
        if key not in specs or not valid(specs[key], item.get("value")):
            item.update(status="missing", note="Provide a valid value from the field specification.")
    if fields.get("unit", {}).get("value") == "mm":
        calibration = fields.get("calibration", {}).get("value")
        existing = next((t for t in inspect.read(graph)["tasks"] if t["task_id"] == draft.get("task_id")), None)
        if not calibration and existing:
            calibration = existing["fields"].get("calibration")
        choices = _calibrations(graph)
        if not calibration and len(choices) == 1:
            fields["calibration"] = cell(choices[0], source="rule", note="Confirm the calibration to use.")
        elif not calibration:
            fields["unit"].update(status="missing", note="Select a calibration before using millimetres. No conversion has been made.")
            fields["calibration"] = cell(None, "missing", "rule", "Select a calibration.")
    return draft


def parse(text: str, lang: str = "en", kinds=None, graph: dict | None = None) -> list[TaskDraft]:
    """離線解析；只把原話明確提供的值標成 confirmed。"""
    graph = graph or {"nodes": [], "edges": []}
    cat = catalogue(kinds)
    tasks = inspect.read(graph)["tasks"]
    drafts = []
    # 只在下一段有明確任務名稱／操作時分句，保留非對稱公差與上下限。
    pattern = "|".join(p for _, p in KINDS)
    chunks = re.split(r"[,，、;；\n]|\band\b(?=\s+(?:inner|outer|count|read|locate))", text, flags=re.I)
    parts: list[str] = []
    for chunk in chunks:
        if parts and not re.search(pattern + r"|刪|删|remove|delete|改成|change", chunk, re.I):
            parts[-1] += " " + chunk
        elif chunk.strip():
            parts.append(chunk.strip())
    for part in parts:
        low = part.lower()
        op = "remove" if re.search(r"刪|删|delete|remove", low) else "update" if re.search(r"改成|修改|改為|改为|change|update|set .* to", low) else "run" if re.search(r"再跑|重跑|run again|rerun", low) else "add"
        found = next((k for k, p in KINDS if re.search(p, low)), "")
        target = re.search(r"第\s*(\d+)\s*[項项]|(?:item|task)\s*#?\s*(\d+)", low)
        task = None
        if target:
            index = int(target.group(1) or target.group(2)) - 1
            task = tasks[index] if 0 <= index < len(tasks) else None
        elif op == "update":
            matches = [t for t in tasks if not found or t["kind"] == found]
            task = matches[0] if len(matches) == 1 else None
        kind = task["kind"] if task else found
        if op == "run":
            drafts.append({"draft_id": uuid.uuid4().hex, "op": op, "kind": "", "fields": {}, "regions": []})
            continue
        if not kind or kind not in cat:
            if op in ("update", "remove"):
                drafts.append({"draft_id": uuid.uuid4().hex, "op": "answer", "kind": "", "fields": {}, "regions": [], "note": "Identify an existing inspection task."})
            continue
        draft = {"draft_id": uuid.uuid4().hex, "op": op, "kind": kind, "fields": {}, "regions": []}
        if task:
            draft["task_id"] = task["task_id"]
        fields = draft["fields"]
        def put(key, value):
            if key in {f["key"] for f in cat[kind]["fields"]}:
                fields[key] = cell(value, "confirmed", "user")
        numeric = re.sub(r"第\s*\d+\s*[項项]|(?:item|task)\s*#?\s*\d+", "", low)
        sym = re.search(rf"({NUMBER})\s*(?:±|\+/-)\s*({NUMBER})", numeric)
        asym = re.search(rf"({NUMBER})\s*\+\s*({NUMBER})\s*/\s*-\s*({NUMBER})", numeric)
        interval = re.search(rf"({NUMBER})\s*(?:～|~|–|\bto\b)\s*({NUMBER})", numeric)
        if sym:
            n, tol = map(float, sym.groups())
            for k, v in (("nominal", n), ("upper_tol", abs(tol)), ("lower_tol", -abs(tol))):
                put(k, v)
        elif asym:
            n, upper, lower = map(float, asym.groups())
            for k, v in (("nominal", n), ("upper_tol", upper), ("lower_tol", -lower)):
                put(k, v)
        elif interval:
            lo, hi = map(float, interval.groups())
            for k, v in (("nominal", (lo + hi) / 2), ("lower_tol", (lo - hi) / 2), ("upper_tol", (hi - lo) / 2), ("min_count", lo), ("max_count", hi)):
                put(k, v)
        else:
            limits = {}
            for k, pat in (("low", r"下限|至少|minimum|at least|lower limit"), ("high", r"上限|最多|maximum|at most|upper limit")):
                m = re.search(rf"(?:{pat})\s*[:=]?\s*({NUMBER})", numeric)
                if m:
                    limits[k] = float(m[1])
            if limits:
                for k, v in limits.items():
                    put("min_count" if k == "low" else "max_count", v)
                if "low" in limits and "high" in limits:
                    n = (limits["low"] + limits["high"]) / 2
                    for k, v in (("nominal", n), ("lower_tol", limits["low"] - n), ("upper_tol", limits["high"] - n)):
                        put(k, v)
                elif kind in ("measure_diameter", "measure_distance"):
                    for k in ("nominal", "lower_tol", "upper_tol"):
                        fields[k] = cell(None, "missing", "user", "Provide both limits or a nominal value with tolerances.")
            else:
                m = re.search(NUMBER, numeric)
                if m and kind in ("measure_diameter", "measure_distance", "count_objects"):
                    if kind == "count_objects":
                        put("min_count", float(m[0]))
                        put("max_count", float(m[0]))
                    else:
                        put("nominal", float(m[0]))
        if re.search(r"內徑|内径|inner diameter", low):
            put("edge", "inner")
        elif re.search(r"外徑|外径|outer diameter", low):
            put("edge", "outer")
        if re.search(r"真圓度|真圆度|roundness", low):
            put("mode", "roundness")
        if re.search(r"孔距|hole cent", low):
            put("mode", "hole_centres")
        if re.search(r"異物|异物|absence|foreign object|must be absent", low):
            put("expected", "absent")
        if re.search(r"缺件|missing part|presence", low):
            put("expected", "present")
        if kind == "read_and_verify":
            put("mode", "text" if re.search(r"ocr|text|字|character", low) else "code")
            expected = re.search(r"(?:expected|equals?|應為|应为|等於|等于)\s*[:=]?\s*[\"']?([^\"'，,;；]+)", part, re.I)
            if expected:
                put("expected", expected[1].strip())
        unit = re.search(r"\b(mm|px)\b|毫米|像素|°", low)
        if unit:
            put("unit", {"毫米": "mm", "像素": "px", "°": "deg"}.get(unit[0], unit[0]))
        elif op == "add" and any(f["key"] == "unit" for f in cat[kind]["fields"]):
            fields["unit"] = cell("px", "assumed", "default", "No unit was specified. Confirm pixels or select a calibrated unit.")
        angle = re.search(rf"({NUMBER})\s*(?:°|degrees?|度)", low)
        if angle and kind == "locate_part":
            put("angle_range", abs(float(angle[1])))
            put("allow_rotation", True)
        if op != "remove":
            _finish(draft, cat, graph)
        drafts.append(draft)
    return drafts


def is_request(text: str, graph: dict) -> bool:
    """限定清單操作語氣，避免攔截既有接線、參數修改與說明問句。"""
    if re.search(r"怎麼|如何|什麼|怎么|什么|how |what |where |\?|？", text, re.I):
        return False
    if re.search(r"接到|跟著|跟着|位移|補正|补正|connect|wire|follow", text, re.I):
        return False
    drafts = parse(text, graph=graph)
    recognized = any(d["op"] == "run" or d["kind"] and (d["op"] == "add" or d.get("task_id")) for d in drafts)
    return recognized and bool(re.search(r"新增|加入|量|檢查|检查|讀|读|定位|數量|数量|改成|修改第|刪|删|再跑|重跑|\b(add|measure|check|read|locate|count|change|update|remove|delete|rerun)\b|run again", text, re.I))


def _rounded(region):
    """候選區域的座標取到小數兩位：質心與半徑倍數算出來會是 638.5751593868889 這種值，提案卡照原樣顯示很難核對。"""
    if not isinstance(region, dict):
        return region
    return {k: round(v, 2) if isinstance(v, float) else v for k, v in region.items()}


def _regions(drafts: list[TaskDraft], cat: dict, image) -> None:
    features = analysis.analyze_region(image, None) if image is not None else None
    for draft in drafts:
        if draft["op"] != "add" or draft["kind"] not in cat:
            continue
        specs = {f["key"]: f for f in cat[draft["kind"]]["fields"]}
        values = {k: v.get("value") for k, v in draft["fields"].items()}
        for key, spec in specs.items():
            if spec["kind"] != "roi" or not visible(spec, values, specs):
                continue
            region = None
            if features:
                h, w = image.shape[:2]
                gray = analysis._to_gray(image)
                # 試探摘要只有半徑，利用同一門檻的前景元件取得偏心物體的位置。
                dark = gray <= features["otsu"]
                mask = np.uint8(dark if float(dark.mean()) < .5 else ~dark) * 255
                n, _, stats, centres = cv2.connectedComponentsWithStats(mask)
                ids = [i for i in range(1, n) if max(9, w * h * .0005) <= stats[i, 4] < w * h * .9]
                if draft["kind"] in ("measure_diameter", "inspect_circular_surface") and features["circle"]["found"] and ids:
                    i = max(ids, key=lambda j: stats[j, 4])
                    cx, cy = map(float, centres[i])
                    radius = float(features["circle"]["radius"])
                    region = {"shape": "annulus", "cx": cx, "cy": cy, "r_inner": max(1., radius * .7), "r_outer": radius * 1.3}
                elif "rect" in spec.get("shapes", []):
                    x, y, rw, rh = w * .1, h * .1, w * .8, h * .8
                    if draft["kind"] == "count_objects" and ids:
                        x, y = min(stats[i, 0] for i in ids), min(stats[i, 1] for i in ids)
                        rw, rh = max(stats[i, 0] + stats[i, 2] for i in ids) - x, max(stats[i, 1] + stats[i, 3] for i in ids) - y
                    region = {"shape": "rect", "x": float(x), "y": float(y), "w": float(rw), "h": float(rh)}
            region = _rounded(region)
            item = cell(region, "assumed" if region else "missing", "rule", "Confirm the candidate region." if region else "Draw a search region on the image.")
            # LLM 區域仍需人工確認；只補沒有提供的區域。
            if draft["fields"].get(key, {}).get("value") is None:
                draft["fields"][key] = item
            value = draft["fields"][key]
            draft["regions"].append({"field": key, "region": value["value"], "status": value["status"], "source": value["source"]})


def propose(text: str, lang: str, graph: dict, settings, *, image=None, history=None) -> dict:
    cat = catalogue()
    rules = parse(text, lang, list(cat.values()), graph)
    drafts, warnings, provider = rules, [], "offline"
    if settings.provider != "offline":
        try:
            raw = llm.tasklist(settings, text, list(cat.values()), inspect.read(graph), history or [], lang)
            if not isinstance(raw, dict) or not isinstance(raw.get("drafts"), list) or not raw["drafts"]:
                raise ValueError("invalid task list")
            proposed = []
            for index, row in enumerate(raw["drafts"][:20]):
                if not isinstance(row, dict) or row.get("kind") not in cat or row.get("op") not in ("add", "update", "remove", "answer", "run") or not isinstance(row.get("fields"), dict):
                    raise ValueError("invalid task draft")
                draft = {"draft_id": uuid.uuid4().hex, "op": row["op"], "kind": row["kind"], "fields": {}, "regions": []}
                if row.get("task_id"):
                    draft["task_id"] = row["task_id"]
                rule = rules[index] if index < len(rules) and rules[index]["kind"] == row["kind"] and rules[index]["op"] == row["op"] and rules[index].get("task_id") == row.get("task_id") else None
                for key, value in row["fields"].items():
                    value = value.get("value") if isinstance(value, dict) and "value" in value else value
                    draft["fields"][key] = cell(value, "assumed", "llm", "Confirm the assistant's assumption.")
                    if rule and rule["fields"].get(key, {}).get("status") == "confirmed" and rule["fields"][key]["value"] == value:
                        draft["fields"][key]["status"] = "confirmed"
                for region in row.get("regions", []):
                    if not isinstance(region, dict) or not isinstance(region.get("field"), str):
                        raise ValueError("invalid region proposal")
                    draft["fields"][region["field"]] = cell(_rounded(region.get("region")), "assumed", "llm", "Confirm the candidate region.")
                if rule:
                    for key, value in rule["fields"].items():
                        if value["status"] == "confirmed" and draft["fields"].get(key, {}).get("value") != value["value"]:
                            draft["fields"][key] = copy.deepcopy(value)
                            warnings.append("An explicit value from your request was preserved.")
                _finish(draft, cat, graph)
                if any(v["status"] == "missing" for v in draft["fields"].values()):
                    warnings.append("Some proposed fields need valid values or additional information.")
                proposed.append(draft)
            drafts, provider = proposed, settings.provider
        except Exception:  # noqa: BLE001 - 供應商與 JSON 失敗都必須保留離線路徑
            warnings.append("The assistant response could not be used. The offline parser was used instead.")
    _regions(drafts, cat, image)
    return {"drafts": drafts, "warnings": warnings, "provider": provider,
            "questions": clarify.tasklist_questions(drafts, cat), "kinds": list(cat.values())}


def apply(graph: dict, drafts: list[TaskDraft], confirmations: dict) -> dict:
    """確認以 draft_id 分組：{fields:{key:true 或 {value:...}}, confirmed:true}。"""
    out, applied, skipped = copy.deepcopy(graph), [], []
    cat = catalogue()
    for draft in drafts:
        ident = draft.get("draft_id", "")
        confirmation = confirmations.get(ident, {})
        if not isinstance(confirmation, dict) or confirmation.get("confirmed") is not True:
            skipped.append({"draft_id": ident, "reason": "Confirm this proposal before applying it."})
            continue
        try:
            kind, op = draft.get("kind"), draft.get("op")
            if kind not in cat or op not in ("add", "update", "remove"):
                raise ValueError("This proposal does not change the inspection list.")
            existing = next((t for t in inspect.read(out)["tasks"] if t["task_id"] == draft.get("task_id")), None)
            if op in ("update", "remove") and (existing is None or existing["kind"] != kind):
                raise ValueError("Select an existing task of this kind.")
            specs = {f["key"]: f for f in cat[kind]["fields"]}
            values = {}
            selected = confirmation.get("fields", {})
            for key, item in draft.get("fields", {}).items():
                approval = selected.get(key)
                value = approval["value"] if isinstance(approval, dict) and "value" in approval else item.get("value")
                accepted = isinstance(approval, dict) and "value" in approval or approval is True and item.get("status") != "missing" or item.get("status") == "confirmed"
                if accepted:
                    if key not in specs or not valid(specs[key], value):
                        raise ValueError(f"Provide a valid value for '{key}'.")
                    values[key] = value
            effective = {**(existing["fields"] if existing else {}), **values}
            if op == "add":
                missing = [k for k, spec in specs.items() if spec.get("required") and visible(spec, effective, specs) and (k not in values or values[k] in (None, "", []))]
                # 核心量距欄位可省略；提案不可用預設公差代替尚未確認的工程規格。
                missing += [k for k in ("unit", "nominal", "upper_tol", "lower_tol") if k in specs and k not in values]
                if missing:
                    raise ValueError("Confirm required fields: " + ", ".join(sorted(set(missing))))
                sources = [n for n in out.get("nodes", []) if n.get("type") in ("image_source", "fixed_image", "stereo_grab", "multi_light_grab") and n.get("params", {}).get("role") != "reference"]
                if len(sources) != 1:
                    raise ValueError("Choose one image source before adding tasks.")
            if effective.get("unit") == "mm" and not effective.get("calibration"):
                raise ValueError("Select a calibration before using millimetres.")
            if op == "add":
                out = inspect.build(out, {"kind": kind, "fields": values}, {"image_node": sources[0]["id"]})
            elif op == "update":
                out = inspect.update(out, {"task_id": existing["task_id"], "fields": values})
            else:
                result = inspect.remove(out, existing["task_id"])
                if not result["removed"]:
                    raise ValueError("Other tasks or steps depend on this task.")
                out = result["graph"]
            applied.append(ident)
        except (APIError, ValueError, TypeError) as exc:
            skipped.append({"draft_id": ident, "reason": exc.message if isinstance(exc, APIError) else str(exc)})
    return {"graph": out, "tasks": inspect.read(out)["tasks"], "applied": applied, "skipped": skipped}
