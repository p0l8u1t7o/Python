"""
空洞檢測模組的驗證指標 (validate-module 使用)

與標註 (正確答案) 比對：
  - 焊點配對：模組焊點中心與標註焊點中心距離 < 0.3 R
  - 空洞檢出：標註空洞面積一半以上被模組空洞覆蓋；依等效直徑 / 焊點直徑分級
  - 誤報：標註無空洞的焊點，模組找到空洞
  - 空洞率誤差：模組 - 標註 (百分點)
  - 判定：依配方規格逐顆比較；漏判 (標註超規、模組判合格) 為最嚴重的錯誤
  - 未量測：標註的焊點未被模組量測 (未偵測或不量測)
"""
import math

import cv2
import numpy as np

SIZE_CLASSES = ((0.0, 0.15, "<15%"), (0.15, 0.30, "15-30%"), (0.30, 9.9, ">=30%"))


def _raster(polys, x0, y0, w, h):
    m = np.zeros((h, w), np.uint8)
    for p in polys:
        pts = (np.asarray(p, np.float64) - [x0, y0]).round().astype(np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(m, [pts], 1)
    return m


def metrics(pairs, spec):
    lim, k = spec.get("void_pct_max"), spec.get("confidence_k", 2.0)
    det = {name: dict(detected=0, total=0) for _, _, name in SIZE_CLASSES}
    errs, clean, false_calls, unmeasured, n_balls = [], 0, 0, 0, 0
    jt = dict(false_pass=0, false_fail=0, review=0, agree=0, truth_fail=0)
    for item, mr, _res in pairs:
        balls = [f for f in mr.findings if f.category == "ball"]
        voids = [f for f in mr.findings if f.category == "void"]
        for bx, by, br in item["balls"]:
            n_balls += 1
            match = min(balls, key=lambda f: math.hypot(f.geometry["ball"]["x"] - bx, f.geometry["ball"]["y"] - by),
                        default=None)
            if match is None or math.hypot(match.geometry["ball"]["x"] - bx, match.geometry["ball"]["y"] - by) > 0.3 * br \
                    or not match.used:
                unmeasured += 1
                continue
            h = int(math.ceil(br)) + 2
            x0, y0 = int(bx) - h, int(by) - h
            w = 2 * h + 1
            disc = np.zeros((w, w), np.uint8)
            cv2.circle(disc, (int(round((bx - x0) * 8)), int(round((by - y0) * 8))), int(round(br * 8)), 1, -1, shift=3)
            tv_polys = [p for p in item["voids"] if math.hypot(np.mean([q[0] for q in p]) - bx,
                                                                 np.mean([q[1] for q in p]) - by) < br]
            truth_mask = _raster(tv_polys, x0, y0, w, w) & disc
            mine = [v.geometry["void"]["points"] for v in voids if v.flags.get("ball") == match.id]
            my_mask = _raster(mine, x0, y0, w, w)
            truth_pct = 100.0 * truth_mask.sum() / (math.pi * br * br)
            v = match.measurements["void_pct"]
            se = match.measurements.get("void_pct_se") or 0.0
            errs.append(v - truth_pct)
            if not tv_polys:
                clean += 1
                false_calls += int(match.measurements.get("void_count", 0) > 0)
            for p in tv_polys:
                pm = _raster([p], x0, y0, w, w) & disc
                area = pm.sum()
                if area == 0:
                    continue
                ratio = 2 * math.sqrt(area / math.pi) / (2 * br)
                name = next(n for lo, hi, n in SIZE_CLASSES if lo <= ratio < hi)
                det[name]["total"] += 1
                det[name]["detected"] += int((pm & my_mask).sum() >= 0.5 * area)
            if lim is not None:
                truth_fail = truth_pct > lim
                jt["truth_fail"] += int(truth_fail)
                mod = "fail" if v - k * se > lim else ("review" if v + k * se > lim else "pass")
                if mod == "review":
                    jt["review"] += 1
                elif (mod == "fail") == truth_fail:
                    jt["agree"] += 1
                elif truth_fail:
                    jt["false_pass"] += 1
                else:
                    jt["false_fail"] += 1
    e = np.abs(np.array(errs)) if errs else np.array([np.nan])
    for d in det.values():
        d["rate"] = d["detected"] / d["total"] if d["total"] else None
    big = [d for n, d in det.items() if n != "<15%"]
    big_total = sum(d["total"] for d in big)
    decided = n_balls - unmeasured - jt["review"]
    return dict(
        balls=n_balls, balls_measured=n_balls - unmeasured, unmeasured_ratio=unmeasured / n_balls if n_balls else None,
        detection_rate=(sum(d["detected"] for d in big) / big_total) if big_total else None,
        detection_by_size=det, voids_total=sum(d["total"] for d in det.values()),
        clean_balls=clean, false_call_rate=(false_calls / clean) if clean else None,
        void_pct_error_mean=float(np.nanmean(errs)) if errs else None,
        void_pct_error_p95=float(np.nanpercentile(e, 95)) if errs else None,
        void_pct_error_max=float(np.nanmax(e)) if errs else None,
        false_pass=jt["false_pass"], false_fail=jt["false_fail"], review_balls=jt["review"],
        truth_fail_balls=jt["truth_fail"],
        judgment_agreement=(jt["agree"] / decided) if decided > 0 else None)
