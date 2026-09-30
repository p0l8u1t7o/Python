"""
通用疊圖：依檢測物件的幾何類型與模組宣告的樣式繪製，不需為個別模組撰寫繪圖程式。
正式介面的疊圖由前端繪製；此處供命令列與報告使用 (文字只用 ASCII，OpenCV 無法繪製中文)。
"""
import cv2

from . import plugin

_SHIFT = 2          # 子像素繪圖 (座標 x4)
_K = 1 << _SHIFT


def _p(x, y):
    return int(round(x * _K)), int(round(y * _K))


def _label(img, text, org, color, scale=0.8):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2, cv2.LINE_AA)


def _draw_geom(img, g, style):
    col, th = style.get("color", (255, 255, 255)), style.get("thickness", 1)
    t = g.get("type")
    if t == "circle":
        cv2.circle(img, _p(g["x"], g["y"]), int(round(g["r"] * _K)), col, th, cv2.LINE_AA, shift=_SHIFT)
    elif t == "vector":
        k = style.get("scale", 1.0)
        cv2.line(img, _p(g["x"], g["y"]), _p(g["x"] + k * g["dx"], g["y"] + k * g["dy"]), col, th, cv2.LINE_AA,
                 shift=_SHIFT)
    elif t == "bbox":
        cv2.rectangle(img, _p(g["x0"], g["y0"]), _p(g["x1"], g["y1"]), col, th, cv2.LINE_AA, shift=_SHIFT)
    elif t == "polygon":
        import numpy as np
        pts = (np.asarray(g["points"]) * _K).round().astype(np.int32)
        cv2.polylines(img, [pts], True, col, th, cv2.LINE_AA, shift=_SHIFT)


JUDGE_BGR = {"fail": (69, 69, 214), "review": (0, 130, 201)}     # 固定判定色 (與介面相同)


def judged_targets(reasons):
    """判定原因指到的目標 {"ballN"/"groupN": "fail"|"review"}：超出規格為 fail，其餘為 review"""
    out = {}
    for code in reasons or []:
        head, _, target = code.partition(":")
        if not target or target == "image":
            continue
        level = "fail" if "exceeds" in head else "review"
        if out.get(target) != "fail":
            out[target] = level
    return out


def render(display, result, show_rejected=True):
    """display：uint8 灰階；result：pipeline.AnalysisResult。回傳 BGR 影像"""
    vis = cv2.cvtColor(display, cv2.COLOR_GRAY2BGR)
    for mr in result.modules:
        styles = plugin.get(mr.module_id).overlay_styles
        unused = styles.get("unused", {"color": (150, 150, 150), "thickness": 1})
        for f in mr.findings:
            for name, g in f.geometry.items():
                if not f.used:
                    if g.get("type") == "circle" and name == next(iter(f.geometry)):
                        _draw_geom(vis, g, unused)
                    continue
                _draw_geom(vis, g, styles.get(name, {}))
        if show_rejected:
            for rj in mr.rejected:
                if rj["reason"] in ("border", "on_ball", "not_ball"):
                    continue
                c = (int(round(rj["x"])), int(round(rj["y"])))
                cv2.drawMarker(vis, c, (255, 0, 200), cv2.MARKER_TILTED_CROSS, max(int(rj["r"]), 8), 2)
        judged = judged_targets(mr.judgment_reasons)
        for f in mr.findings:
            lv = judged.get(f.flags.get("label", f"ball{f.id}")) if judged else None
            g = next((q for q in f.geometry.values() if q.get("type") == "circle"), None)
            if lv and g:
                _draw_geom(vis, dict(g, r=g["r"] * 1.18), dict(color=JUDGE_BGR[lv], thickness=3))
        gs, ga = styles.get("group", {}), styles.get("group_shift", {})
        for g in mr.groups:
            if g.bbox is None:
                continue
            x0, y0, x1, y1 = g.bbox
            _draw_geom(vis, dict(type="bbox", x0=x0, y0=y0, x1=x1, y1=y1), gs)
            lv = judged.get(f"group{g.id}")
            if lv:
                _draw_geom(vis, dict(type="bbox", x0=x0 - 6, y0=y0 - 6, x1=x1 + 6, y1=y1 + 6),
                           dict(color=JUDGE_BGR[lv], thickness=4))
            e = g.estimate
            txt = f"G{g.id} n={g.size}"
            if e:
                txt += f" ({e['dx']:+.2f},{e['dy']:+.2f})px {g.grade}"
                k = ga.get("scale", 40.0)
                cv2.arrowedLine(vis, _p(e["cx"], e["cy"]), _p(e["cx"] + k * e["dx"], e["cy"] + k * e["dy"]),
                                ga.get("color", (255, 160, 0)), ga.get("thickness", 4), cv2.LINE_AA, shift=_SHIFT,
                                tipLength=0.25)
            _label(vis, txt, (int(x0) + 6, max(int(y0) + 30, 30)), gs.get("color", (255, 160, 0)))
    head = f"{result.image['name']}  quality={result.quality['level'].upper()}"
    if result.reference_only:
        head += "  [REFERENCE ONLY: non-raw image]"
    _label(vis, head, (10, vis.shape[0] - 20), (255, 255, 255), 1.0)
    return vis
