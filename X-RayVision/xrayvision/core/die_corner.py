"""
晶片角點偵測 (規劃書 PLAN-006 第 3 節)：在吸收量影像中找出晶片本體的兩條邊緣與其交點。

晶片本體在吸收量影像中是一塊吸收較高的矩形平台，上面疊著凸塊、焊墊等較小的高吸收物件；
晶片外側是基板，吸收較低，上面有錫球等較小物件。做法：

1. 縮小影像後以形態學開運算 (結構元素大於錫球) 抹除小物件，留下「晶片／基板」兩個亮度平台；
2. 以 Otsu 門檻分出兩個平台，沿列與欄找門檻穿越點 (次像素內插) 作為邊緣點，依梯度方向分成
   左緣、右緣、上緣、下緣四類；
3. 每類以 RANSAC 擬合直線，支撐長度須達影像尺寸的一定比例；
4. 一條垂直邊與一條水平邊的交點為候選角點，晶片落在交點的哪個象限決定角落位置；
5. 以「內側實心、外側為基板」檢查排除陣列之間的走道等假邊緣，取分數最高的候選。

座標一律為原始影像像素座標。角點只用於把影像定位到晶片座標 (力臂)，不需要次像素精度。
"""
import cv2
import numpy as np

POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right")

# 角落位置 → 晶片所在方向 (sx, sy)：+1 表示晶片在角點右方／下方
DIE_SIDE = {"top_left": (1, 1), "top_right": (-1, 1), "bottom_left": (1, -1), "bottom_right": (-1, -1)}

DEFAULTS = dict(
    work_size=540,          # 縮小後短邊像素數
    feature_ratio=0.075,    # 開運算結構元素直徑 / 短邊 (需大於錫球直徑)
    min_edge_ratio=0.2,     # 邊緣支撐長度下限 / 影像對應邊長 (整張影像搜尋)
    min_edge_region=0.08,   # 搜尋區域內的邊緣支撐長度下限 / 影像短邊 (區域由人圈選，邊緣可能較短)
    max_tilt_deg=10.0,      # 邊緣與影像軸的最大夾角
    max_ortho_dev_deg=5.0,  # 兩邊與 90° 的最大差
    min_contrast=0.05,      # 晶片平台與基板平台的吸收量差下限 (晶片內部影像約 0.02～0.04，實際邊緣約 0.08 以上)
    probe_ratio=0.15,       # 內側檢查方塊邊長 / 短邊
    strip_ratio=0.05,       # 外側檢查窄帶寬度 / 短邊 (相鄰晶片之間的基板帶可能很窄)
    min_inner_fill=0.8,     # 晶片側方塊中屬於晶片平台的比例下限
    max_outer_fill=0.25,    # 外側窄帶中屬於晶片平台的比例上限
    max_lines=3,            # 每一類邊緣最多擬合幾條線 (多晶片封裝)
    ransac_tol=1.0,         # RANSAC 內點容差 (縮小後像素)
    edge_level=0.5,         # 邊緣位置：基板平台 (0) 到晶片平台 (1) 之間的比例
)


def detect(A, region=None, position=None, cfg=None):
    """
    A：吸收量影像 (越大越暗)；region：(x0, y0, x1, y1) 搜尋範圍 (原始像素)，None 為整張影像；
    position：指定角落位置 (POSITIONS 之一) 時只找該種角點。
    回傳 dict：found、position、x、y、angle_deg (晶片邊緣相對影像軸的旋轉)、edges (繪圖用線段)、
    quality (各項指標)、reason (未找到時的原因代碼)、edge_only (只找到單一邊緣時的邊緣資料)。
    """
    c = dict(DEFAULTS, **(cfg or {}))
    H, W = A.shape[:2]
    base = min(H, W)          # 尺度一律以整張影像為準，搜尋區域大小不影響結構元素與檢查方塊
    s = max(1.0, base / c["work_size"])
    box = None
    if region is not None:
        x0, y0, x1, y1 = (float(v) for v in region)
        x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(float(W), x1), min(float(H), y1)
        if x1 - x0 < 32 or y1 - y0 < 32:
            return _miss("search_region_too_small")
        box = (x0 / s, y0 / s, x1 / s, y1 / s)
    # 開運算與平台亮度一律以整張影像計算；搜尋區域只篩選邊緣點與角點，結果與整張搜尋一致
    a = cv2.resize(A.astype(np.float32), (max(8, int(round(W / s))), max(8, int(round(H / s)))),
                   interpolation=cv2.INTER_AREA)
    k = int(round(base * c["feature_ratio"] / s)) | 1
    c["_base"] = base / s     # 縮小後的基準長度
    # 邊緣支撐長度下限 (縮小後像素)：(垂直邊, 水平邊)
    c["_minlen"] = ((c["min_edge_region"] * c["_base"],) * 2 if box is not None
                    else (c["min_edge_ratio"] * a.shape[0], c["min_edge_ratio"] * a.shape[1]))
    op = cv2.morphologyEx(a, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    op = cv2.GaussianBlur(op, (0, 0), 2.0)

    otsu, lo, hi = _otsu(op)
    contrast = hi - lo
    if contrast < c["min_contrast"]:
        return _miss("no_die_edge", contrast=contrast)
    die = op > otsu
    # 邊緣位置取兩個平台之間的固定比例，不隨亮度與兩側面積比例變動 (Otsu 門檻會)
    thr = lo + c["edge_level"] * contrast

    pts = _crossings(op, thr)
    if box is not None:
        for key, (p, n) in pts.items():
            xy = p[:, ::-1] if key in ("left", "right") else p          # 還原為 (x, y)
            keep = (xy[:, 0] >= box[0]) & (xy[:, 0] <= box[2]) & (xy[:, 1] >= box[1]) & (xy[:, 1] <= box[3])
            pts[key] = (p[keep], n)
    lines = {}
    max_slope = np.tan(np.radians(c["max_tilt_deg"]))
    for key, (p, along_len) in pts.items():
        lines[key] = []
        for _ in range(c["max_lines"]):          # 依序擬合，每次移除已用的點
            ln = _ransac_line(p, c["ransac_tol"], max_slope)
            if ln is None or ln["support"] < c["_minlen"][0 if key in ("left", "right") else 1]:
                break
            lines[key].append(dict(ln, side=key))
            p = p[np.abs(p[:, 1] - (ln["a"] * p[:, 0] + ln["b"])) > 3 * c["ransac_tol"]]

    cands = []
    for pos, (sx, sy) in DIE_SIDE.items():
        if position and pos != position:
            continue
        for v in lines["left" if sx > 0 else "right"]:
            for hz in lines["top" if sy > 0 else "bottom"]:
                cand = _corner(v, hz, pos, sx, sy, die, op.shape, c)
                if cand and box is not None and not (box[0] <= cand["x"] <= box[2] and box[1] <= cand["y"] <= box[3]):
                    cand = None
                if cand:
                    cands.append(cand)
    q_base = dict(contrast=round(float(contrast), 4), scale=round(s, 3))
    if not cands:
        edge = _best_edge(lines, die, c)
        out = _miss("single_edge" if edge else "no_die_corner", **q_base)
        if edge:
            out["edge_only"] = _edge_out(edge, s)
        return out
    best = max(cands, key=lambda d: d["score"])
    x, y = best["x"] * s, best["y"] * s
    edges = [_edge_out(best["v"], s), _edge_out(best["h"], s)]
    q = dict(q_base, rms_px=round(float(max(best["v"]["rms"], best["h"]["rms"]) * s), 3),
             support=[round(best["v"]["support"] / op.shape[0], 3), round(best["h"]["support"] / op.shape[1], 3)],
             ortho_dev_deg=round(best["ortho"], 3), inner_fill=round(best["inner"], 3),
             outer_fill=round(best["outer"], 3), candidates=len(cands), score=round(float(best["score"]), 4))
    return dict(found=True, position=best["pos"], x=round(float(x), 2), y=round(float(y), 2),
                angle_deg=round(float(best["angle"]), 4), edges=edges, quality=q, reason="")


def _miss(reason, **q):
    return dict(found=False, position=None, x=None, y=None, angle_deg=None, edges=[], quality=q, reason=reason)


def _otsu(op):
    """兩個平台的 Otsu 門檻與兩側平均 (吸收量單位)"""
    lo_v, hi_v = np.percentile(op, 0.5), np.percentile(op, 99.5)
    u8 = np.clip((op - lo_v) / max(hi_v - lo_v, 1e-6) * 255, 0, 255).astype(np.uint8)
    t, _ = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = lo_v + (t + 0.5) / 255 * (hi_v - lo_v)
    above = op > thr
    if above.all() or not above.any():
        return thr, float(op.mean()), float(op.mean())
    # 平台高度取兩側中位數，避免殘留的小物件拉高平均
    return thr, float(np.median(op[~above])), float(np.median(op[above]))


def _crossings(op, thr):
    """門檻穿越點：沿列找垂直邊、沿欄找水平邊；依晶片 (高值) 所在側分類"""
    d = op - thr
    out = {}
    # 列方向 (x 變化)：d 由負轉正 → 晶片在右 (左緣)；由正轉負 → 晶片在左 (右緣)
    ys, xs = np.nonzero(np.signbit(d[:, :-1]) != np.signbit(d[:, 1:]))
    d0, d1 = d[ys, xs], d[ys, xs + 1]
    fx = xs + d0 / (d0 - d1)
    rising = d1 > d0
    out["left"] = (np.column_stack([fx[rising], ys[rising]]), op.shape[0])
    out["right"] = (np.column_stack([fx[~rising], ys[~rising]]), op.shape[0])
    ys, xs = np.nonzero(np.signbit(d[:-1, :]) != np.signbit(d[1:, :]))
    d0, d1 = d[ys, xs], d[ys + 1, xs]
    fy = ys + d0 / (d0 - d1)
    rising = d1 > d0
    out["top"] = (np.column_stack([xs[rising], fy[rising]]), op.shape[1])
    out["bottom"] = (np.column_stack([xs[~rising], fy[~rising]]), op.shape[1])
    # 垂直邊以 (y, x) 擬合 x = a·y + b；水平邊以 (x, y) 擬合 y = a·x + b
    out["left"] = (out["left"][0][:, ::-1], out["left"][1])
    out["right"] = (out["right"][0][:, ::-1], out["right"][1])
    return out


def _ransac_line(p, tol, max_slope, iters=300, seed=0):
    """p 為 (t, u) 點列，擬合 u = a·t + b；每個 t 只計一次內點 (支撐長度以不同 t 的數量計)"""
    if len(p) < 10:
        return None
    rng = np.random.default_rng(seed)
    t, u = p[:, 0], p[:, 1]
    best, best_n = None, 0
    for _ in range(iters):
        i, j = rng.choice(len(p), 2, replace=False)
        if abs(t[j] - t[i]) < 5:
            continue
        a = (u[j] - u[i]) / (t[j] - t[i])
        if abs(a) > max_slope:
            continue
        b = u[i] - a * t[i]
        inl = np.abs(u - (a * t + b)) <= tol
        n = len(np.unique(np.round(t[inl])))
        if n > best_n:
            best, best_n = inl, n
    if best is None:
        return None
    for _ in range(2):                     # 以內點最小平方精修
        a, b = np.polyfit(t[best], u[best], 1)
        best = np.abs(u - (a * t + b)) <= tol
    tt, uu = t[best], u[best]
    if len(tt) < 10:
        return None
    a, b = np.polyfit(tt, uu, 1)
    rms = float(np.sqrt(np.mean((uu - (a * tt + b)) ** 2)))
    return dict(a=float(a), b=float(b), rms=rms, support=len(np.unique(np.round(tt))),
                t_min=float(tt.min()), t_max=float(tt.max()), t=tt)


def _corner(v, hz, pos, sx, sy, die, shape, c):
    """垂直邊 x = av·y + bv 與水平邊 y = ah·x + bh 的交點，並檢查內外側"""
    av, bv, ah, bh = v["a"], v["b"], hz["a"], hz["b"]
    den = 1 - av * ah
    if abs(den) < 1e-6:
        return None
    y = (ah * bv + bh) / den
    x = av * y + bv
    h, w = shape
    if not (-0.02 * w <= x <= 1.02 * w and -0.02 * h <= y <= 1.02 * h):
        return None
    ang_v = np.degrees(np.arctan(-av))     # 垂直邊相對 y 軸的旋轉 (與水平邊同向為正)
    ang_h = np.degrees(np.arctan(ah))
    ortho = abs(ang_v - ang_h)
    if ortho > c["max_ortho_dev_deg"]:
        return None
    # 邊緣支撐須在晶片側：垂直邊的內點要延伸到角點的晶片那一側
    minlen_v, minlen_h = c["_minlen"]
    if _side_support(v["t"], y, sy) < minlen_v or _side_support(hz["t"], x, sx) < minlen_h:
        return None
    L, m, wo = c["probe_ratio"] * c["_base"], 0.03 * c["_base"], c["strip_ratio"] * c["_base"]
    inner = _fill_rect(die, x + sx * m, y + sy * m, x + sx * (m + L), y + sy * (m + L))
    # 外側：垂直邊外側、沿晶片方向的窄帶；水平邊外側同理
    outs = [_fill_rect(die, x - sx * m, y + sy * m, x - sx * (m + wo), y + sy * (m + L)),
            _fill_rect(die, x + sx * m, y - sy * m, x + sx * (m + L), y - sy * (m + wo))]
    outs = [o for o in outs if o is not None]
    if inner is None or inner < c["min_inner_fill"] or not outs:
        return None
    outer = max(outs)
    if outer > c["max_outer_fill"]:
        return None
    score = (v["support"] / h + hz["support"] / w) * (inner - outer)
    return dict(pos=pos, x=x, y=y, angle=(ang_v + ang_h) / 2, ortho=ortho, inner=inner, outer=outer,
                score=score, v=v, h=hz)


def _side_support(t, t0, sign):
    """內點在角點某一側的分布長度"""
    side = t[(t - t0) * sign > 0]
    return 0.0 if len(side) == 0 else float(len(np.unique(np.round(side))))


def _fill_rect(die, xa, ya, xb, yb):
    """矩形中屬於晶片平台的比例；在影像內的面積不足一半時回傳 None"""
    h, w = die.shape
    xa, xb = sorted((xa, xb))
    ya, yb = sorted((ya, yb))
    x0, x1, y0, y1 = int(max(0, xa)), int(min(w, xb)), int(max(0, ya)), int(min(h, yb))
    if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) < 0.5 * (xb - xa) * (yb - ya):
        return None
    return float(die[y0:y1, x0:x1].mean())


def _best_edge(lines, die, c):
    """沒有角點時，回報通過內外側檢查、支撐最長的一條邊 (供日後單邊影像使用)"""
    h, w = die.shape
    L, m, wo = c["probe_ratio"] * c["_base"], 0.03 * c["_base"], c["strip_ratio"] * c["_base"]
    best = None
    for key, lns in lines.items():
        vertical = key in ("left", "right")
        sign = 1 if key in ("left", "top") else -1          # 晶片在右方 (left) 或下方 (top) 為 +
        for ln in lns:
            tm = (ln["t_min"] + ln["t_max"]) / 2
            um = ln["a"] * tm + ln["b"]
            if vertical:
                inner = _fill_rect(die, um + sign * m, tm - L / 2, um + sign * (m + L), tm + L / 2)
                outer = _fill_rect(die, um - sign * m, tm - L / 2, um - sign * (m + wo), tm + L / 2)
            else:
                inner = _fill_rect(die, tm - L / 2, um + sign * m, tm + L / 2, um + sign * (m + L))
                outer = _fill_rect(die, tm - L / 2, um - sign * m, tm + L / 2, um - sign * (m + wo))
            if inner is None or outer is None or inner < c["min_inner_fill"] or outer > c["max_outer_fill"]:
                continue
            frac = ln["support"] / (h if vertical else w)
            if best is None or frac > best[0]:
                best = (frac, ln)
    return best[1] if best else None


def _edge_out(ln, s):
    """繪圖用線段 (原始像素座標)"""
    vertical = ln["side"] in ("left", "right")
    t0, t1 = ln["t_min"], ln["t_max"]
    u0, u1 = ln["a"] * t0 + ln["b"], ln["a"] * t1 + ln["b"]
    if vertical:
        p0, p1 = (u0, t0), (u1, t1)
    else:
        p0, p1 = (t0, u0), (t1, u1)
    return dict(side=ln["side"], x0=round(p0[0] * s, 1), y0=round(p0[1] * s, 1),
                x1=round(p1[0] * s, 1), y1=round(p1[1] * s, 1))
