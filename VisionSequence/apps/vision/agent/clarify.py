"""詢問機制：生成前先確認資訊是否足夠；不足就逐步提問（規則引擎版）。

流程：prompt＋ROI＋特徵 → 意圖 → 檢查該意圖的關鍵缺口 → 產生最多 3 個問題。
使用者的回答（answers=[{id, answer}]）由 answers_to_text 轉成補充句併回提示詞，
意圖解析（intents.parse）自然就讀得到——不用另開一套結構化覆寫。
已問過的題目（不論有沒有答）不再重問；全部關鍵缺口補齊即 ready。
"""

from __future__ import annotations

from typing import Any

from apps.vision.agent.intents import Intent

QUESTION_KINDS = ("choice", "number", "text", "roi")

GOAL_OPTIONS = [
    ("count", "計數（有幾個）"), ("diameter", "量測圓孔直徑"), ("width", "量測寬度／間距"), ("angle", "量測角度"),
    ("defect", "表面缺陷"), ("color", "顏色判斷"), ("presence", "有無檢測"), ("barcode", "讀取條碼"), ("brightness", "亮度／曝光守門"),
    ("text", "印字有無"), ("distance", "兩孔中心距"), ("template", "圖案有無（範本比對）"),
    ("focus", "對焦／清晰度守門"), ("roundness", "真圓度"),
]
_GOAL_PHRASE = {
    "focus": "請檢查對焦是否清晰", "roundness": "請量測真圓度",
    "count": "請計數有幾個", "diameter": "請量測直徑", "width": "請量測寬度", "angle": "請量測角度",
    "defect": "請檢查表面缺陷刮痕", "color": "請檢查顏色是否正確", "presence": "請檢查有沒有", "barcode": "請讀取條碼", "brightness": "請檢查亮度",
    "text": "請檢查有沒有印字", "distance": "請量測兩孔的中心距離", "template": "請用範本比對檢查圖案有沒有",
}


def _q(qid: str, text: str, kind: str = "text", *, options: list[tuple[str, str]] | None = None, optional: bool = False, hint: str = "") -> dict[str, Any]:
    q: dict[str, Any] = {"id": qid, "text": text, "kind": kind, "optional": optional}
    if options:
        q["options"] = [{"value": v, "label": lbl} for v, lbl in options]
    if hint:
        q["hint"] = hint
    return q


def tasklist_questions(drafts: list[dict], kinds: dict) -> list[dict]:
    """沿用三題格式，題目由缺失欄位與核心規格產生。"""
    questions = []
    for draft in drafts:
        specs = {f["key"]: f for f in kinds.get(draft["kind"], {}).get("fields", [])}
        values = {k: v.get("value") for k, v in draft["fields"].items()}
        for key, item in draft["fields"].items():
            spec = specs.get(key)
            if item["status"] != "missing" or spec is None:
                continue
            if any(values.get(k, specs[k].get("default")) not in (v if isinstance(v, list) else [v]) for k, v in (spec.get("visible_when") or {}).items()):
                continue
            kind = {"select": "choice", "range": "number"}.get(spec["kind"], spec["kind"])
            questions.append(_q(f"{draft['draft_id']}:{key}", f"Provide {spec['label'].lower()}.", kind if kind in QUESTION_KINDS else "text",
                                options=[(o["value"], o["label"]) for o in spec.get("options", [])], hint=item.get("note", "")))
            if len(questions) == 3:
                return questions
    return questions


def answers_to_text(answers: list[dict[str, Any]]) -> str:
    """把問答轉成意圖解析看得懂的補充句。"""
    parts: list[str] = []
    for a in answers or []:
        qid, ans = str(a.get("id", "")), str(a.get("answer", "")).strip()
        if not ans:
            continue
        if qid == "goal":
            parts.append(_GOAL_PHRASE.get(ans, ans))
        elif qid == "count":
            parts.append(f"期望 {ans} 個")
        elif qid == "polarity":
            parts.append("目標比背景暗" if ans == "dark" else "目標比背景亮" if ans == "bright" else ans)
        elif qid == "nominal":
            parts.append(f"標稱 {ans}")
        elif qid == "mm_per_px":
            parts.append(f"{ans}mm=1px" if "=" not in ans else ans)
        elif qid == "golden_ref":
            parts.append("有良品可比對，請用良品比對" if ans == "yes" else "沒有良品，直接找異常")
        elif qid == "roi_scope":
            parts.append("檢查整張影像" if ans == "whole" else "檢查圈選區域")
        elif qid == "expected":
            parts.append(f"期望內容 {ans}")
        elif qid == "range":
            parts.append(f"亮度範圍 {ans}")
        else:
            parts.append(ans)
    return "；".join(parts)


def build_questions(intent: Intent, regions: list[dict[str, Any]], analysis: dict[str, Any], answered: set[str]) -> list[dict[str, Any]]:
    """依意圖找關鍵缺口，回最多 3 題（已問過的不重問）。"""
    qs: list[dict[str, Any]] = []
    rows = analysis.get("regions") or []
    first_shape = str((regions[0].get("region") or {}).get("shape", "")) if regions else ""

    def ask(q: dict[str, Any]) -> None:
        if q["id"] not in answered and len(qs) < 3:
            qs.append(q)

    if intent.kind == "generic":
        ask(_q("goal", "這張影像要檢測什麼？", "choice", options=GOAL_OPTIONS, hint="提示詞不夠明確；選一項讓我用對的工具。"))
        return qs
    if intent.locate and intent.locator_roi is None:
        ask(_q("locate_roi", "請圈一個位置固定的定位標記，並在該 ROI 的提示填「定位」", "roi", hint="工件位置會變時，其他 ROI 會跟著定位標記移動；定位標記要在每張影像都看得到。"))
    work = [r for i, r in enumerate(regions) if i != intent.locator_roi]
    if intent.kind == "count":
        if intent.expected_count is None:
            ask(_q("count", "期望的數量是多少？", "number", optional=True, hint="填了就會做 OK／NG 判定；留空只回報數量。"))
        if not regions:
            ask(_q("roi_scope", "要在整張影像計數，還是特定區域？", "choice", options=[("whole", "整張影像"), ("roi", "我先圈一個區域")], optional=True, hint="留空＝整張影像；選「圈區域」後請在右側影像圈選再繼續。"))
        info = rows[0] if rows and not rows[0].get("empty") else analysis.get("full") or {}
        dark = info.get("blobs", {}).get("dark", {}).get("count", 0)
        bright = info.get("blobs", {}).get("bright", {}).get("count", 0)
        if dark and bright and abs(dark - bright) <= 1:
            ask(_q("polarity", "要數的目標比背景暗還是亮？", "choice", options=[("dark", "比背景暗"), ("bright", "比背景亮")], hint=f"影像裡暗粒子 {dark} 顆、亮粒子 {bright} 顆，分不出哪邊是目標。"))
    elif intent.kind == "diameter":
        circle_found = bool(rows and not rows[0].get("empty") and rows[0].get("circle", {}).get("found")) or bool((analysis.get("full") or {}).get("circle", {}).get("found"))
        if first_shape not in ("circle", "annulus") and not circle_found:
            ask(_q("roi", "請在孔的邊緣圈一個圓形或環形 ROI", "roi", hint="找圓需要知道圓大概在哪；環要蓋住圓緣。"))
        if intent.nominal is None:
            ask(_q("nominal", "直徑的標稱值與公差？（例：17.5±0.4mm）", "text", optional=True, hint="留空只回報量測值不判定。"))
        if intent.unit == "mm" and intent.mm_per_px is None:
            ask(_q("mm_per_px", "每像素多少 mm？（例：0.05）", "number", hint="要換算成 mm 需要像素尺寸；不知道可先用 px。"))
    elif intent.kind == "width":
        if not regions:
            ask(_q("roi", "請圈一個橫跨要量兩條邊的矩形 ROI", "roi", hint="卡尺沿 ROI 長邊掃描，找兩條邊的距離。"))
        if intent.nominal is None:
            ask(_q("nominal", "寬度的標稱值與公差？（例：160±10）", "text", optional=True))
    elif intent.kind == "angle":
        if len(regions) < 2:
            ask(_q("roi", "請再圈第二條邊的 ROI（夾角需要兩條邊）", "roi", hint=f"目前 {len(regions)} 個 ROI；每條邊各一個矩形。"))
        if intent.nominal is None:
            ask(_q("nominal", "角度的標稱值與公差？（例：90±1）", "text", optional=True))
    elif intent.kind == "defect":
        ask(_q("golden_ref", "有沒有良品影像可以比對？", "choice", options=[("yes", "有，我會再上傳並標記為好品"), ("no", "沒有，直接找異常")], hint="良品比對能抓「不知道長怎樣」的缺陷，比固定門檻穩。"))
        if not regions:
            ask(_q("roi_scope", "要檢查整張影像還是特定區域？", "choice", options=[("whole", "整張影像"), ("roi", "我先圈一個區域")], optional=True))
    elif intent.kind in ("color_match", "color_presence"):
        if not regions:
            ask(_q("roi", "請圈要判斷顏色的區域", "roi", hint="目標色會取自您圈的區域主色。"))
    elif intent.kind == "golden":
        if intent.good_roi is None:
            ask(_q("roi", "請標記哪個 ROI 是好品（在 ROI 提示填「好品」）", "roi"))
        if intent.bad_roi is None:
            ask(_q("roi_bad", "有壞品示範嗎？若有請圈選並在提示填「壞品」", "roi", optional=True))
    elif intent.kind == "presence" and not regions:
        ask(_q("roi_scope", "要檢查整張影像還是特定區域？", "choice", options=[("whole", "整張影像"), ("roi", "我先圈一個區域")], optional=True))
    elif intent.kind == "text":
        if not work:
            ask(_q("roi", "請圈住印字所在的區域", "roi", hint="筆劃密度只在 ROI 內計算，框太大會把背景算進去。"))
    elif intent.kind == "distance":
        if len(work) < 2:
            ask(_q("roi", "請為兩個孔各圈一個圓形 ROI（蓋住孔緣）", "roi", hint=f"目前 {len(work)} 個 ROI；中心距需要兩個找圓結果。"))
        if intent.nominal is None:
            ask(_q("nominal", "中心距的標稱值與公差？（例：300±10）", "text", optional=True, hint="留空只回報量測值不判定。"))
        if intent.unit == "mm" and intent.mm_per_px is None:
            ask(_q("mm_per_px", "每像素多少 mm？（例：0.05）", "number", hint="要換算成 mm 需要像素尺寸；不知道可先用 px。"))
    elif intent.kind == "template_presence":
        if not work:
            ask(_q("roi", "請圈住要找的圖案（會裁成範本）", "roi", hint="範本取自您圈的區域；比對時在其附近搜尋。"))
    elif intent.kind == "barcode":
        if not intent.expected_text:
            ask(_q("expected", "條碼內容應該是什麼？", "text", optional=True, hint="填了會比對內容；留空只讀取不比對。"))
    elif intent.kind == "brightness":
        if intent.range_low is None:
            info = rows[0] if rows and not rows[0].get("empty") else analysis.get("full") or {}
            ask(_q("range", "可接受的平均亮度範圍？（例：80~180）", "text", optional=True, hint=f"目前 ROI 平均亮度 {float(info.get('mean', 0)):.0f}；留空以目前值 ±30% 為範圍。"))
    return qs


def summary_of(intent: Intent, regions: list[dict[str, Any]], analysis: dict[str, Any]) -> str:
    kind_label = {
        "count": "計數", "diameter": "圓孔直徑量測", "width": "寬度量測", "angle": "角度量測", "golden": "良品比對", "defect": "表面缺陷",
        "color_match": "顏色比對", "color_presence": "顏色有無", "presence": "有無檢測", "brightness": "亮度守門", "barcode": "讀碼", "generic": "尚不明確",
        "text": "印字有無", "distance": "兩孔中心距", "template_presence": "圖案有無（範本比對）",
        "focus": "對焦／清晰度守門", "roundness": "真圓度", "template": "套用範本",
    }.get(intent.kind, intent.kind)
    bits = [f"判讀為「{kind_label}」", f"{len(regions)} 個 ROI", f"{analysis.get('image_count', 1)} 張影像"]
    if intent.expected_count is not None:
        bits.append(f"期望 {intent.expected_count} 個")
    if intent.nominal is not None:
        bits.append(f"標稱 {intent.nominal}{intent.unit}" + (f"±{intent.tol}" if intent.tol is not None else ""))
    if intent.locate:
        bits.append("含定位補正" if intent.locator_roi is not None else "位置會變（尚未指定定位標記）")
    return "；".join(bits)


def clarify(intent: Intent, regions: list[dict[str, Any]], analysis: dict[str, Any], answers: list[dict[str, Any]]) -> dict[str, Any]:
    answered = {str(a.get("id", "")) for a in answers or []}
    questions = build_questions(intent, regions, analysis, answered)
    return {
        "ready": not questions,  # 可略過的題目也先問一次；使用者留空再繼續就不會再問
        "questions": questions,
        "summary": summary_of(intent, regions, analysis),
        "intent": intent.kind,
        "provider": "rules",
    }
