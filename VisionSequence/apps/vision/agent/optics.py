"""取像計算：視野、工作距離、鏡頭焦距、解析度、景深、傳輸頻寬與曝光上限。

AI 助手回答「這個件要選什麼相機鏡頭」時，數字必須是算出來的而不是模型口算的——這裡是那些算式，
純函式、沒有 Django 依賴，`lookup.camera_optics` 直接呼叫（見 `agent/skills/imaging.md` 的判斷準則）。

慣例：長度一律 mm、時間一律 ms／µs、資料量一律 MB（10^6 位元組，與相機廠商標示一致）。
薄透鏡近似：β＝感光元件尺寸／視野，f＝WD·β/(1+β)＝WD·sensor/(FOV+sensor)；WD 是工件到鏡頭的距離，
真實鏡頭還有主點位置與後焦距的差，所以算出來的焦距要對到最接近的標準焦距再驗證。
"""

from __future__ import annotations

import math
from typing import Any

#: 常見感光元件格式的寬×高（mm）；1/1.8" 之類的英吋數不是實際尺寸，一律查表
SENSOR_FORMATS: dict[str, tuple[float, float]] = {
    "1/4": (3.6, 2.7), "1/3": (4.8, 3.6), "1/2.5": (5.7, 4.3), "1/2": (6.4, 4.8),
    "1/1.8": (7.2, 5.4), "1/1.7": (7.6, 5.7), "1/1.2": (10.7, 8.0),
    "2/3": (8.8, 6.6), "1": (12.8, 9.6), "1.1": (12.4, 9.8), "4/3": (17.3, 13.0),
    "aps-c": (23.5, 15.6), "35mm": (36.0, 24.0),
}
#: 常用鏡頭焦距（mm）：算出來的值要對到買得到的規格
STANDARD_FOCAL = (4.0, 6.0, 8.0, 12.0, 16.0, 25.0, 35.0, 50.0, 75.0, 100.0)
#: 介面的實際可用頻寬（MB/s，扣掉協定負擔的保守值）
INTERFACES: dict[str, float] = {
    "GigE": 115.0, "2.5GigE": 290.0, "5GigE": 580.0, "10GigE": 1150.0,
    "USB3": 380.0, "CXP-6": 600.0, "CXP-12": 1200.0, "CameraLink-Base": 255.0, "CameraLink-Full": 850.0,
}
#: 每個特徵至少要幾個像素才「看得到／量得準」
PIXELS_PER_FEATURE = {"detect": 3.0, "measure": 10.0, "read": 20.0}


def _pos(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def sensor_size(fmt: str) -> tuple[float, float] | None:
    """感光元件格式（1/1.8、2/3、1"…）→ (寬 mm, 高 mm)。"""
    key = str(fmt or "").strip().lower().replace('"', "").replace("inch", "").replace("型", "").strip()
    return SENSOR_FORMATS.get(key)


def magnification(sensor_mm: float, fov_mm: float) -> float:
    return sensor_mm / fov_mm


def focal_length(sensor_mm: float, fov_mm: float, wd_mm: float) -> float:
    """薄透鏡：f = WD · sensor / (FOV + sensor)。"""
    return wd_mm * sensor_mm / (fov_mm + sensor_mm)


def fov_from_focal(sensor_mm: float, focal_mm: float, wd_mm: float) -> float:
    """已知鏡頭焦距與工作距離時的視野；WD 必須大於焦距。"""
    if wd_mm <= focal_mm:
        raise ValueError("Working distance must be larger than the focal length")
    return sensor_mm * (wd_mm - focal_mm) / focal_mm


def working_distance(sensor_mm: float, fov_mm: float, focal_mm: float) -> float:
    return focal_mm * (fov_mm + sensor_mm) / sensor_mm


def nearest_focal(focal_mm: float) -> float:
    return min(STANDARD_FOCAL, key=lambda f: abs(f - focal_mm))


def mm_per_pixel(fov_mm: float, pixels: int) -> float:
    return fov_mm / float(pixels)


def pixels_for(fov_mm: float, feature_mm: float, per_feature: float) -> int:
    """要在 fov 裡把 feature 看成 per_feature 個像素，感光元件那一軸需要幾個像素。"""
    return int(math.ceil(fov_mm / feature_mm * per_feature))


def depth_of_field(focal_mm: float, f_number: float, wd_mm: float, coc_mm: float) -> float:
    """近攝景深近似：DOF ≈ 2·N·c·(1+β)/β²（β 由 f 與 WD 推回）。"""
    beta = focal_mm / max(1e-6, wd_mm - focal_mm)
    if beta <= 0:
        raise ValueError("Bad geometry")
    return 2.0 * f_number * coc_mm * (1.0 + beta) / (beta * beta)


def bandwidth_mb_s(width: int, height: int, bytes_per_px: float, fps: float) -> float:
    return width * height * bytes_per_px * fps / 1_000_000.0


def interfaces_for(mb_s: float, limit: int = 3) -> list[str]:
    """撐得住這個頻寬的介面，由慢（便宜）到快，最多回 limit 個——夠用就好，不必列完。"""
    return [name for name, cap in sorted(INTERFACES.items(), key=lambda kv: kv[1]) if cap >= mb_s][:limit]


def max_exposure_us(speed_mm_s: float, mm_per_px: float, blur_px: float = 1.0) -> float:
    """運動模糊要壓在 blur_px 個像素內的曝光上限（µs）。"""
    return blur_px * mm_per_px / speed_mm_s * 1_000_000.0


def solve(**kw: Any) -> dict[str, Any]:
    """把使用者給的條件（視野、工作距離、特徵大小、速度、介面…）算成一份取像規格。

    給什麼算什麼：缺的條件就不算那一項，並在 `notes` 說明還需要什麼。
    """
    out: dict[str, Any] = {"inputs": {k: v for k, v in kw.items() if v not in (None, "")}, "notes": []}
    notes: list[str] = out["notes"]

    fov = _pos(kw.get("fov_mm"))
    fov_h = _pos(kw.get("fov_height_mm"))
    wd = _pos(kw.get("wd_mm"))
    focal = _pos(kw.get("focal_mm"))
    feature = _pos(kw.get("feature_mm"))
    task = str(kw.get("task") or "detect").lower()
    per_feature = _pos(kw.get("pixels_per_feature")) or PIXELS_PER_FEATURE.get(task, 3.0)
    fmt = str(kw.get("sensor_format") or "")
    sensor = _pos(kw.get("sensor_mm"))
    size = sensor_size(fmt) if fmt else None
    if sensor is None and size:
        sensor = size[0]
    width = int(_pos(kw.get("width_px")) or 0)
    height = int(_pos(kw.get("height_px")) or 0)

    # 需要多少像素
    if fov and feature:
        need = pixels_for(fov, feature, per_feature)
        out["pixels_needed"] = need
        out["pixels_per_feature"] = per_feature
        # 另一軸：有給高度視野就照比例，否則假設 4:3
        need_h = int(math.ceil(need * fov_h / fov)) if fov_h else int(math.ceil(need * 0.75))
        out["pixels_needed_height"] = need_h
        out["megapixels_needed"] = round(need * need_h / 1_000_000.0, 2)
        notes.append(f"{feature:g} mm 的特徵要 {per_feature:g} px（{task}），視野 {fov:g} mm 需要 {need} px（該軸）")
        if not width:
            width = need
    if fov and width:
        out["mm_per_px"] = round(mm_per_pixel(fov, width), 5)
        if feature:
            out["feature_px"] = round(feature / out["mm_per_px"], 1)

    # 鏡頭
    if sensor and fov and wd:
        f = focal_length(sensor, fov, wd)
        out["magnification"] = round(magnification(sensor, fov), 4)
        out["focal_mm"] = round(f, 2)
        out["focal_standard_mm"] = nearest_focal(f)
        out["fov_at_standard_mm"] = round(fov_from_focal(sensor, out["focal_standard_mm"], wd), 1)
        notes.append(f"焦距 {f:.1f} mm → 最接近的標準鏡頭 {out['focal_standard_mm']:g} mm，該鏡頭在 WD {wd:g} mm 的視野是 {out['fov_at_standard_mm']:g} mm")
    elif sensor and focal and wd:
        out["fov_mm"] = round(fov_from_focal(sensor, focal, wd), 1)
        out["magnification"] = round(sensor / out["fov_mm"], 4)
    elif sensor and fov and focal:
        out["wd_mm"] = round(working_distance(sensor, fov, focal), 1)
    elif not sensor:
        notes.append("沒有感光元件尺寸（sensor_format 或 sensor_mm）就算不出焦距")

    # 景深
    f_number = _pos(kw.get("f_number"))
    if f_number and wd and (out.get("focal_mm") or focal):
        f_eff = float(out.get("focal_mm") or focal)
        px_um = _pos(kw.get("pixel_size_um"))
        coc = (px_um * 2.0 / 1000.0) if px_um else 0.02
        out["dof_mm"] = round(depth_of_field(f_eff, f_number, wd, coc), 2)
        notes.append(f"景深約 {out['dof_mm']:g} mm（F{f_number:g}、模糊圈 {coc * 1000:.0f} µm）；工件高低差比它大就要縮光圈或改遠心鏡頭")

    # 速度、曝光與頻寬
    speed = _pos(kw.get("speed_mm_s"))
    if speed and out.get("mm_per_px"):
        out["max_exposure_us"] = round(max_exposure_us(speed, out["mm_per_px"], _pos(kw.get("blur_px")) or 1.0), 1)
        notes.append(f"線速 {speed:g} mm/s 下曝光要 ≤ {out['max_exposure_us']:.0f} µs（模糊 1 px）；不夠亮就加強打光或用頻閃")
    fps = _pos(kw.get("fps"))
    if fps and width:
        h = height or int(width * 0.75)
        bytes_per_px = _pos(kw.get("bytes_per_px")) or (3.0 if str(kw.get("color") or "").lower() in ("1", "true", "color", "rgb") else 1.0)
        mb = bandwidth_mb_s(width, h, bytes_per_px, fps)
        out["bandwidth_mb_s"] = round(mb, 1)
        out["interfaces"] = interfaces_for(mb)
        notes.append(f"{width}×{h}×{bytes_per_px:g}B × {fps:g} fps = {mb:.0f} MB/s；夠用的介面：{', '.join(out['interfaces']) or '需要更快的介面或降低需求'}")
        if not out["interfaces"]:
            notes.append("超過常見介面的頻寬：降 fps、改單色、縮 ROI，或用多相機分區")
    if fps:
        out["cycle_ms"] = round(1000.0 / fps, 2)
    return out


#: 問題裡的數字要對到哪個參數：關鍵字（中英）→ 欄位
_FIELD_WORDS: dict[str, tuple[str, ...]] = {
    "fov_mm": ("視野", "視場", "视野", "fov", "field of view"),
    "wd_mm": ("工作距離", "工作距离", "wd", "working distance"),
    "feature_mm": ("缺陷", "特徵", "特征", "瑕疵", "刮痕", "線寬", "线宽", "字高", "最小", "smallest", "defect", "feature"),
    "focal_mm": ("焦距", "focal length"),
    "fps": ("fps", "每秒", "張數", "张数", "frame rate", "幀率", "帧率"),
    "speed_mm_s": ("線速", "线速", "輸送", "输送", "速度", "speed", "belt"),
    "f_number": ("光圈", "f-number", "aperture"),
    "pixel_size_um": ("像素大小", "像元", "pixel size"),
}
#: 各欄位認得的單位（None＝可以沒有單位）
_FIELD_UNITS: dict[str, tuple[str, ...]] = {
    "fov_mm": ("mm", "cm", ""), "wd_mm": ("mm", "cm", ""), "feature_mm": ("mm", "um", "µm"),
    "focal_mm": ("mm", ""), "fps": ("fps", ""), "speed_mm_s": ("mm/s", "m/min", ""),
    "f_number": ("",), "pixel_size_um": ("um", "µm", ""),
}
_SENSOR_WORDS = ("1/1.8", "1/1.7", "1/1.2", "1/2.5", "1/2", "1/3", "1/4", "2/3", "4/3", "aps-c", "35mm")
_TASK_WORDS = {"measure": ("量測", "量测", "測量", "测量", "尺寸", "公差", "measure"), "read": ("讀字", "读字", "字元", "字符", "ocr", "條碼", "条码", "read")}
#: 子句邊界：數字不能跨過標點被抓過來（「視野 120 mm、工作距離 300 mm」不能把 300 當視野）
_BREAK = "、，,。；;（()）？?！!" + chr(10)
_NUM = r"(\d+(?:\.\d+)?)\s*(mm/s|m/min|mm|cm|um|µm|fps)?"


def _convert(value: float, unit: str, field: str) -> float | None:
    """單位換算成該欄位的基準（mm、mm/s、µm、fps）；不合的單位回 None。"""
    import re as _re

    allowed = _FIELD_UNITS.get(field, ("",))
    unit = (unit or "").lower()
    if unit and unit not in allowed:
        return None
    if not unit and "" not in allowed:
        return None
    if unit == "cm":
        return value * 10.0
    if unit == "m/min":
        return value * 1000.0 / 60.0
    if field == "feature_mm" and unit in ("um", "µm"):
        return value / 1000.0
    if _re.fullmatch(r"\s*", unit or ""):
        return value
    return value


def _first_number(chunk: str, field: str, *, last: bool = False) -> float | None:
    import re as _re

    chunk = _re.split(f"[{_BREAK}]", chunk)[-1 if last else 0]
    found = _re.findall(_NUM, chunk)
    for raw, unit in (reversed(found) if last else found):
        value = _pos(raw)
        if value is None:
            continue
        converted = _convert(value, unit, field)
        if converted is not None:
            return converted
    return None


def _find(text: str, field: str, words: tuple[str, ...], *, window: int = 16) -> float | None:
    """關鍵字附近的數字：先看後面（「視野 120 mm」），再看緊接在前面的（「0.2 mm 的缺陷」）；不跨標點。"""
    import re as _re

    low = text.lower()
    for word in words:
        for m in _re.finditer(_re.escape(word.lower()), low):
            after = _first_number(low[m.end():m.end() + window], field)
            if after is not None:
                return after
            before = _first_number(low[max(0, m.start() - window):m.start()], field, last=True)
            if before is not None:
                return before
    return None


def parse_question(text: str) -> dict[str, Any]:
    """使用者的一句話 → solve() 的參數（抓得到什麼算什麼）；抓不到就回空的，呼叫端別算。"""
    import re as _re

    text = str(text or "")
    low = text.lower()
    out: dict[str, Any] = {}
    # 感光元件格式本身含數字（2/3、1/1.8）：先遮掉，否則「2/3 吋相機的視野」會把 3 當成視野
    scrub = low
    for fmt in _SENSOR_WORDS:
        scrub = scrub.replace(fmt, " " * len(fmt))
    for field, words in _FIELD_WORDS.items():
        value = _find(scrub, field, words)
        if value is not None:
            out[field] = value
    m = _re.search(r"(\d+(?:\.\d+)?)\s*mm\s*(?:的)?\s*(?:鏡頭|镜头|lens)", low)
    if m and "focal_mm" not in out:
        out["focal_mm"] = float(m.group(1))
    for fmt in _SENSOR_WORDS:
        if fmt in low:
            out["sensor_format"] = fmt
            break
    for task, words in _TASK_WORDS.items():
        if any(w in low for w in words):
            out["task"] = task
            break
    if _re.search(r"彩色|color|colour|rgb", low):
        out["color"] = "color"
    m = _re.search(r"(\d+(?:\.\d+)?)\s*(mp|百萬畫素|百萬像素|万像素|萬畫素|萬像素)", low)
    if m:
        mp = float(m.group(1)) * (0.01 if m.group(2) in ("万像素", "萬畫素", "萬像素") else 1.0)
        out["width_px"] = int(round(math.sqrt(mp * 1_000_000 / 0.75)))
    return out


def relevant(text: str) -> bool:
    """這句話是不是在問取像硬體（值得先算一份規格）。"""
    low = str(text or "").lower()
    words = ("鏡頭", "镜头", "相機", "相机", "視野", "视野", "工作距離", "工作距离", "景深", "打光", "光源", "曝光",
             "解析度", "分辨率", "感光元件", "頻寬", "带宽", "介面", "接口", "lens", "camera", "field of view", "fov",
             "working distance", "depth of field", "lighting", "illumination", "exposure", "bandwidth", "interface", "sensor")
    return any(w in low for w in words)
