"""文字辨識（ocr_read）與字串驗證（ocv_verify）：讀日期碼、批號、料號並比對預期字串。

ocr_read 兩條路：
- 通用辨識（model 留空或 .onnx）：apps/vision/ocr.py 的 PP-OCRv4（離線模型在 ASSET_DIR/ocr）；mode=line 直接辨識 ROI 這一行，
  mode=detect 先偵測多行再逐行辨識。charset 限制字元集能大幅提升準確率（日期碼用 digits）。
- 現場教導字型（model 選 .npz 的字型模型）：切分（投影／連通域／固定字數）＋逐字分類，點陣噴印、DPM 打標這類通用模型會爛的字體用它。
輸出 items 的每個字都帶 box 與信心，ocv_verify 才能把第幾個字錯了框成紅色。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from apps.vision import ocr
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.locate import to_gray
from apps.vision.tools.roi import crop, region_overlay

CHARSET_OPTIONS = [
    {"value": "alnum", "label": "Letters and digits"},
    {"value": "digits", "label": "Digits (and - . / :)"},
    {"value": "upper", "label": "Upper-case letters and digits"},
    {"value": "any", "label": "Any character"},
    {"value": "custom", "label": "Custom"},
]
POLARITY_OPTIONS = [{"value": "dark_on_light", "label": "Dark text on a light background"}, {"value": "light_on_dark", "label": "Light text on a dark background"}]
SEG_OPTIONS = [{"value": "projection", "label": "Projection (gaps between characters)"}, {"value": "components", "label": "Connected components"}, {"value": "fixed", "label": "Fixed pitch (known character count)"}]
DEFAULT_CONFUSABLES = "O:0\nI:1\nS:5\nB:8\nZ:2"


def _allowed(ctx: ToolContext) -> str:
    choice = str(ctx.param("charset", "alnum"))
    if choice == "custom":
        return str(ctx.param("custom_charset", "") or "")
    return ocr.CHARSETS.get(choice, "")


def _pattern_char_ok(ch: str, spec: str) -> bool:
    if spec == "N":
        return ch.isdigit()
    if spec == "A":
        return ("A" <= ch <= "Z") or ("a" <= ch <= "z")
    if spec == "X":
        return True
    return ch == spec


def _parse_confusables(text: Any) -> dict[str, str]:
    rules: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        src, _, dst = line.partition(":")
        src, dst = src.strip(), dst.strip()
        if len(src) == 1 and len(dst) == 1:
            rules[src] = dst
    return rules


def _apply_pattern(text: str, pattern: str, confusables: str) -> tuple[str, bool, list[dict[str, Any]]]:
    """依位置樣板修正常見誤辨字；原字已符合該位置時不改。"""
    if not pattern:
        return text, True, []
    rules = _parse_confusables(confusables)
    chars = list(text)
    corrections: list[dict[str, Any]] = []
    for i, ch in enumerate(chars[:len(pattern)]):
        spec = pattern[i]
        if _pattern_char_ok(ch, spec):
            continue
        repl = rules.get(ch)
        if repl is not None and _pattern_char_ok(repl, spec):
            chars[i] = repl
            corrections.append({"index": i, "from": ch, "to": repl, "pattern": spec})
    corrected = "".join(chars)
    ok = len(corrected) == len(pattern) and all(_pattern_char_ok(ch, spec) for ch, spec in zip(corrected, pattern))
    return corrected, ok, corrections


class OcrReadTool(Tool):
    key = "ocr_read"
    label = "Text read (OCR)"
    description = (
        "Reads printed text — date codes, lot numbers, part numbers — from the region and returns the string with a confidence "
        "and a box for every character. Restricting the character set (digits for a date code) makes it markedly more accurate. "
        "For dot-matrix or laser-marked fonts that general models misread, teach the font on the assets page and pick that model here."
    )
    category = "detect"
    icon = "Type"
    heavy = True
    params = [
        Param("roi", "Text region", kind="roi", shapes=["rect", "rotated_rect", "polygon"], teach=True, help_text="Leave blank for the whole image. One line for the line mode."),
        Param("mode", "Mode", kind="select", default="line", options=[{"value": "line", "label": "Single line (read the region as one line)"}, {"value": "detect", "label": "Detect lines first (several lines)"}]),
        Param("model", "Model", kind="asset", accept="model", help_text="Blank = the built-in general model. A taught font (.npz) switches to segmentation plus per-character classification."),
        Param("charset", "Character set", kind="select", default="alnum", options=CHARSET_OPTIONS, teach=True),
        Param("custom_charset", "Custom characters", kind="text", visible_when={"param": "charset", "in": ["custom"]}, teach=True, help_text="Every character that may appear, e.g. 0123456789ABCDEF-"),
        Param("polarity", "Polarity", kind="select", default="dark_on_light", options=POLARITY_OPTIONS, teach=True),
        Param("min_confidence", "Min confidence", kind="range", default=0.5, minimum=0, maximum=1, step=0.05, teach=True, help_text="A character below this makes the read not found."),
        Param("pattern", "Position pattern", kind="text", default="", help_text="N=digit, A=letter, X=any, any other character must match exactly. Blank disables this check."),
        Param("confusables", "Confusable replacements", kind="multiline", default=DEFAULT_CONFUSABLES, help_text="One rule per line, from:to. A replacement is used only when it satisfies the pattern at that position."),
        Param("preprocess", "Pre-processing", kind="select", default="auto", options=[{"value": "auto", "label": "Auto (contrast stretch and denoise)"}, {"value": "none", "label": "None"}]),
        Param("segmentation", "Segmentation (taught font)", kind="select", default="projection", options=SEG_OPTIONS, group="Taught font"),
        Param("char_count", "Character count (fixed pitch)", kind="number", default=0, minimum=0, maximum=200, group="Taught font", help_text="Fixed-pitch segmentation splits the ink extent into this many cells."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Text region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("text", "Text", "string"), Port("corrected", "Corrected text", "string"), Port("pattern_ok", "Pattern OK", "bool"),
        Port("corrections", "Corrections", "list"), Port("items", "Lines", "list"), Port("confidence", "Confidence", "number"), Port("count", "Line count", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(gray, region, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 4:
            raise ToolError("The region falls outside the image or is too small")
        sub = np.ascontiguousarray(c.image)
        if c.mask is not None:
            fill = 255 if ctx.param("polarity", "dark_on_light") == "dark_on_light" else 0
            sub = np.where(c.mask > 0, sub, fill).astype(np.uint8)
        allowed = _allowed(ctx)
        polarity = str(ctx.param("polarity", "dark_on_light"))
        preprocess = str(ctx.param("preprocess", "auto"))
        min_conf = ctx.number("min_confidence", 0.5)
        model_id = ctx.param("model")
        font = None
        if model_id:
            path = ctx.asset_path(str(model_id))
            if not path:
                raise ToolError(f"Asset {model_id} not found")
            if path.lower().endswith(".npz"):
                try:
                    font = ocr.load_font(path)
                except ocr.OcrError as exc:
                    raise ToolError(str(exc)) from None
            elif not path.lower().endswith(".onnx"):
                raise ToolError("The model must be a taught font (.npz) or an ONNX recognition model")
        items: list[dict[str, Any]] = []
        try:
            if font is not None:
                text, chars = ocr.read_with_font(sub, font, mode=str(ctx.param("segmentation", "projection")), count=ctx.integer("char_count", 0), polarity=polarity, allowed=allowed)
                items.append(self._item(c, text, chars, 0, 0, sub.shape[1], sub.shape[0], None))
            elif ctx.param("mode", "line") == "detect":
                for b in ocr.detect_lines(sub, limit=min(736, max(64, 2 * min(sub.shape[:2])))):
                    line, inv = ocr.crop_box(sub, b["box"])
                    text, chars = ocr.recognise_line(line, allowed=allowed, polarity=polarity, preprocess=preprocess)
                    items.append(self._item(c, text, chars, 0, 0, line.shape[1], line.shape[0], (b["box"], inv, b["score"])))
            else:
                text, chars = ocr.recognise_line(sub, allowed=allowed, polarity=polarity, preprocess=preprocess)
                items.append(self._item(c, text, chars, 0, 0, sub.shape[1], sub.shape[0], None))
        except ocr.OcrError as exc:
            raise ToolError(str(exc)) from None
        items = [it for it in items if it["text"]]
        text = "\n".join(it["text"] for it in items)
        pattern = str(ctx.param("pattern", "") or "")
        raw_confusables = ctx.params.get("confusables", DEFAULT_CONFUSABLES)
        corrected, pattern_ok, corrections = _apply_pattern(text, pattern, "" if raw_confusables is None else str(raw_confusables))
        confidences = [ch["conf"] for it in items for ch in it["chars"]]
        confidence = min(confidences) if confidences else 0.0
        found = bool(text) and confidence >= min_conf and pattern_ok
        overlays: list[dict[str, Any]] = [region_overlay(region, label="text")] if region else []
        for it in items:
            overlays.append({"kind": "polygon", "points": it["box"], "color": "#22c55e" if it["confidence"] >= min_conf else "#f59e0b", "width": 2, "label": it["text"]})
            for ch in it["chars"]:
                overlays.append({"kind": "polygon", "points": ch["box"], "color": "#22c55e" if ch["conf"] >= min_conf else "#f59e0b", "width": 1, "dash": True})
        return Result(
            outputs={"text": text, "corrected": corrected, "pattern_ok": bool(pattern_ok), "corrections": corrections,
                     "items": items, "confidence": round(confidence, 4), "count": len(items)},
            overlays=overlays, branch="found" if found else "not_found", status="ok" if found else "ng",
            message=(f"'{text}' ({confidence:.2f})" if text else "no text") + ("" if found else " — pattern mismatch" if text and not pattern_ok else " — below the confidence threshold" if text else ""),
        )

    @staticmethod
    def _item(c: Any, text: str, chars: list[dict[str, Any]], x0: float, y0: float, w: float, h: float, det: tuple | None) -> dict[str, Any]:
        """行與字的框換回全圖座標：行影像座標 →（偵測模式先經 crop_box 的反向透視）→ ROI 座標 → 全圖。"""

        def to_full(x: float, y: float) -> list[float]:
            if det is not None:
                inv = det[1]
                v = inv @ np.array([x, y, 1.0])
                x, y = float(v[0] / v[2]), float(v[1] / v[2])
            fx, fy = c.to_full(x, y)
            return [round(fx, 1), round(fy, 1)]

        box = [to_full(0, 0), to_full(w, 0), to_full(w, h), to_full(0, h)] if det is None else [c.to_full(*p) for p in det[0]]
        if det is not None:
            box = [[round(p[0], 1), round(p[1], 1)] for p in box]
        out_chars = []
        for ch in chars:
            cy0, cy1 = ch.get("y0", 0.0), ch.get("y1", h)
            out_chars.append({"ch": ch["ch"], "conf": ch["conf"], "box": [to_full(ch["x0"], cy0), to_full(ch["x1"], cy0), to_full(ch["x1"], cy1), to_full(ch["x0"], cy1)]})
        conf = min((ch["conf"] for ch in chars), default=0.0)
        return {"text": text, "box": box, "confidence": round(conf, 4), "chars": out_chars, **({"detect_score": det[2]} if det is not None else {})}


class OcvVerifyTool(Tool):
    key = "ocv_verify"
    label = "Text verify (OCV)"
    description = (
        "Compares the text that was read with what it should be: a fixed string, or one handed down by the host system for this lot. "
        "? matches any character and # any digit; contains and regular-expression modes are there for longer prints. Reports which "
        "character is the first wrong one and draws it in red."
    )
    category = "detect"
    icon = "SpellCheck"
    params = [
        Param("expected", "Expected text", kind="text", teach=True, help_text="? = any character, # = any digit. Example: LOT######"),
        Param("expected_source", "Expected from", kind="select", default="param", options=[{"value": "param", "label": "This parameter"}, {"value": "input", "label": "The expected input port (host system)"}]),
        Param("mode", "Mode", kind="select", default="exact", options=[{"value": "exact", "label": "Exact"}, {"value": "contains", "label": "Contains"}, {"value": "regex", "label": "Regular expression"}]),
        Param("min_char_confidence", "Min character confidence", kind="range", default=0, minimum=0, maximum=1, step=0.05, teach=True,
              help_text="A character read with less confidence than this fails even when it is the right character. Needs the lines input."),
        Param("ignore_case", "Ignore case", kind="boolean", default=False),
        Param("strip", "Ignore surrounding spaces", kind="boolean", default=True),
    ]
    inputs = [
        Port("text", "Text", "string"), Port("expected", "Expected", "string", required=False),
        Port("items", "Lines (from Text read)", "list", required=False), Port("image", "Image (for display)", "image", required=False),
    ]
    outputs = [
        flow_out("pass", "Pass", "ok"), flow_out("fail", "Fail", "critical"),
        Port("match", "Match", "bool"), Port("actual", "Actual", "string"), Port("fail_index", "First wrong index", "number"), Port("expected_text", "Expected", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        actual = ctx.inputs.get("text")
        actual = "" if actual is None else str(actual)
        if ctx.param("expected_source", "param") == "input":
            expected = ctx.inputs.get("expected")
            if expected is None:
                raise ToolError("The expected input port is not connected")
            expected = str(expected)
        else:
            expected = str(ctx.param("expected", "") or "")
        if ctx.flag("strip", True):
            actual, expected = actual.strip(), expected.strip()
        a_cmp, e_cmp = (actual.upper(), expected.upper()) if ctx.flag("ignore_case") else (actual, expected)
        mode = str(ctx.param("mode", "exact"))
        try:
            match, fail_index = ocr.compare(a_cmp, e_cmp, mode)
        except ocr.OcrError as exc:
            raise ToolError(str(exc)) from None
        # 逐字信心：讀對了但信心不足也算失敗
        items = ctx.inputs.get("items")
        chars: list[dict[str, Any]] = []
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    chars.extend(ch for ch in it.get("chars", []) if isinstance(ch, dict))
        min_conf = ctx.number("min_char_confidence", 0)
        low = next((i for i, ch in enumerate(chars) if float(ch.get("conf", 1.0)) < min_conf), -1) if min_conf > 0 else -1
        reason = ""
        if match and low >= 0:
            match, fail_index, reason = False, low, f"character {low + 1} '{chars[low].get('ch')}' read with confidence {float(chars[low].get('conf', 0)):.2f} < {min_conf:.2f}"
        overlays: list[dict[str, Any]] = []
        if chars:
            for i, ch in enumerate(chars):
                box = ch.get("box")
                if isinstance(box, list) and len(box) == 4:
                    bad = (not match) and (i == fail_index or (fail_index >= len(chars) and i == len(chars) - 1))
                    overlays.append({"kind": "polygon", "points": box, "color": "#ef4444" if bad else "#22c55e", "width": 3 if bad else 1, **({"label": ch.get("ch", "")} if bad else {})})
        message = f"'{actual}' matches '{expected}'" if match else (f"'{actual}' does not match '{expected}' at character {fail_index + 1}" + (f" ({reason})" if reason else ""))
        return Result(
            outputs={"match": bool(match), "actual": actual, "fail_index": int(fail_index), "expected_text": expected},
            overlays=overlays, branch="pass" if match else "fail", status="ok" if match else "ng", message=message,
        )


TOOLS = [OcrReadTool(), OcvVerifyTool()]
