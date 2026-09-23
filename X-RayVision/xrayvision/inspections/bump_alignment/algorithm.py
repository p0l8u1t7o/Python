"""
微凸塊對位量測演算法

流程：LoG 尺度空間偵測圓盤 → 逐顆擬合「二次背景＋模糊圓盤」模型並正規化 (背景 0、核心 1)
→ 放射線取高等高線 = 凸塊圓、低等高線 (凸塊 ∪ 焊墊外緣) = 焊墊圓 → 依 pitch 連結成陣列
→ 各陣列以相似變換穩健估計晶片偏移。詳細說明見 docs/bump-pad-detection-flow.md。
"""
import cv2
import numpy as np

from ...core import geometry as G
from ...core.io import KIND_RGB8

# 內部常數 (不開放配方調整)；可調參數由模組的參數結構覆寫同名鍵
DEFAULTS = dict(
    det_r_lo=10.0,           # LoG 尺度空間：最小半徑 (px)
    det_r_hi=110.0,          # LoG 尺度空間：最大半徑 (px)
    det_n_scales=24,         # LoG 尺度數
    det_rel=0.15,            # 偵測門檻 = 此值 x 響應 99.5 百分位
    det_rel_rgb=0.30,        # 8-bit 影像雜訊大，門檻提高
    bump_r_min=12.0,         # 凸塊半徑搜尋範圍 (決定標準半徑 R0 用)
    bump_r_max=48.0,
    bump_r_tol=(0.6, 1.5),   # 候選凸塊半徑 / R0 的範圍
    ball_ratio=1.8,          # 半徑 >= 此值 x R0 視為大球，遮罩排除
    ball_margin=1.08,        # 大球遮罩半徑倍率
    ball_overlap=0.3,        # 凸塊中心離大球邊 < 此值 x 凸塊半徑 (大半疊在球上) 才整顆不量
    nb_margin=3.0,           # 相鄰圓盤遮罩：半徑 + 此值 (px)
    fit_win=1.9,             # 單圓模型擬合視窗半徑 / R0
    fit_stride=2,            # 擬合取樣間隔 (px)
    n_rays=120,              # 放射線數
    ray_max=1.75,            # 放射線最遠 / R0
    ray_step=0.25,           # 放射線取樣間距 (px)
    core_frac=0.35,          # 核心值 = 半徑 < core_frac x R 內的中位數
    bump_level=0.75,         # 凸塊等高線 (背景 0 → 核心 1)
    pad_level=0.25,          # 焊墊等高線
    min_cov=0.55,            # 有效射線比例下限
    trim_k=2.5,              # 穩健圓擬合的修剪倍數
    trim_min=0.6,            # 修剪門檻下限 (px)
    max_rms=2.0,             # 圓擬合 RMS 上限 (px)
    min_contrast_raw=0.02,   # 16-bit：核心吸收量下限 (-ln 單位)
    min_contrast_rgb=0.06,   # 8-bit：核心暗度下限 (0~1)
    r_dev=0.15,              # 凸塊／焊墊半徑與陣列中位數差 <= 此比例
    link_k=1.45,             # 陣列連結：距離 <= link_k x 最近鄰距離
    min_array=6,             # 陣列至少幾顆
    trace_max_deg=40.0,      # 同心模式：連續離群段角寬 < 此值才當走線/via 剔除
    lobe="auto",             # 露出弧模式：auto (只用於 8-bit) / on / off
    lobe_margin=1.5,         # 低等高線超出「凸塊圓 + Δ0」此值 (px，且 >= 3 倍雜訊) 才算焊墊露出
    lobe_min_excess=0.12,    # 露出弧超出量 (中位數，扣掉 Δ0) 至少此值 x 凸塊半徑
    lobe_min_span=50.0,      # 露出弧至少跨幾度
    lobe_free_span=150.0,    # 弧跨度 >= 此值才自由擬合焊墊半徑
    lobe_r_ratio=(0.6, 1.8), # 自由擬合焊墊半徑 / 凸塊半徑 合理範圍
    shift_tol=0.5,           # 整體偏移內點容差下限 (px)
    shift_k=3.0,             # 內點容差 = max(shift_tol, shift_k x 1.4826 x MAD)
)


# ---------------------------------------------------------------------------
# 偵測
# ---------------------------------------------------------------------------
def detect_blobs(A, kind, cfg):
    """LoG 尺度空間偵測暗圓盤；回傳 (凸塊候選, 大球, 標準凸塊半徑 R0)。候選為 (x, y, r, 響應)"""
    radii = np.geomspace(cfg["det_r_lo"], cfg["det_r_hi"], cfg["det_n_scales"])
    best = np.full(A.shape, -np.inf, np.float32)
    arg = np.zeros(A.shape, np.float32)
    for r in radii:
        s = r / np.sqrt(2)
        lap = -cv2.Laplacian(cv2.GaussianBlur(A, (0, 0), s), cv2.CV_32F, ksize=3) * s * s
        m = lap > best
        best[m] = lap[m]
        arg[m] = r
    k = int(cfg["det_r_lo"] * 1.5) | 1
    mx = cv2.dilate(best, np.ones((k, k), np.uint8))
    pk = np.argwhere((best >= mx - 1e-12) & (best > 0))
    resp = best[pk[:, 0], pk[:, 1]]
    rel = cfg["det_rel_rgb"] if kind == KIND_RGB8 else cfg["det_rel"]
    keep = resp > rel * np.percentile(resp, 99.5)
    pk, resp = pk[keep], resp[keep]
    rr = arg[pk[:, 0], pk[:, 1]]
    # 同一物件在相鄰尺度有多個極大值：響應大者優先，吃掉中心落在其 0.6r 內的
    blobs = []
    for i in np.argsort(-resp):
        y, x, r = int(pk[i][0]), int(pk[i][1]), float(rr[i])
        if any((x - b[0]) ** 2 + (y - b[1]) ** 2 < (0.6 * max(r, b[2])) ** 2 for b in blobs):
            continue
        blobs.append((float(x), float(y), r, float(resp[i])))
    rs = np.array([b[2] for b in blobs])
    sel = rs[(rs >= cfg["bump_r_min"]) & (rs <= cfg["bump_r_max"])]
    if len(sel) < 5:
        return [], [], None
    hist, edges = np.histogram(np.log(sel), bins=24)
    j = int(np.argmax(hist))
    R0 = float(np.exp(0.5 * (edges[j] + edges[j + 1])))
    lo, hi = cfg["bump_r_tol"]
    bumps = [b for b in blobs if lo * R0 <= b[2] <= hi * R0]
    balls = [b for b in blobs if b[2] >= cfg["ball_ratio"] * R0]
    return bumps, balls, R0


# ---------------------------------------------------------------------------
# 單圓模型：A = 二次背景 + a·S(d) + b·S(d)·(1 - (d/r)^2)
# ---------------------------------------------------------------------------
def _sig(d, r, w):
    return 1.0 / (1.0 + np.exp(np.clip((d - r) / w, -30, 30)))


class DiscFit:
    def __init__(self, A, cx, cy, R, valid, off, cfg):
        H, W = A.shape
        stride = cfg["fit_stride"]
        win = cfg["fit_win"] * R
        h = int(np.ceil(win))
        x0, x1 = max(int(round(cx)) - h, 0), min(int(round(cx)) + h + 1, W)
        y0, y1 = max(int(round(cy)) - h, 0), min(int(round(cy)) + h + 1, H)
        yy, xx = np.mgrid[y0:y1:stride, x0:x1:stride]
        sub = A[y0:y1:stride, x0:x1:stride]
        vx0, vy0 = off
        m = ((xx - cx) ** 2 + (yy - cy) ** 2 <= win ** 2) & \
            valid[y0 - vy0:y1 - vy0:stride, x0 - vx0:x1 - vx0:stride]
        self.x, self.y, self.v = xx[m].astype(np.float64), yy[m].astype(np.float64), sub[m].astype(np.float64)
        self.cx, self.cy, self.R = cx, cy, R
        u, v = (self.x - cx) / R, (self.y - cy) / R
        self.bg = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], 1)
        self.n = len(self.v)

    def bg_eval(self, c, x, y):
        u, v = (x - self.cx) / self.R, (y - self.cy) / self.R
        return c[0] + c[1] * u + c[2] * v + c[3] * u * u + c[4] * u * v + c[5] * v * v

    def solve(self, th):
        xb, yb, rb, w = th
        d = np.hypot(self.x - xb, self.y - yb)
        S = _sig(d, rb, w)
        B = np.concatenate([self.bg, S[:, None], (S * np.clip(1 - (d / rb) ** 2, 0, None))[:, None]], 1)
        c, *_ = np.linalg.lstsq(B, self.v, rcond=None)
        return self.v - B @ c, c

    def fit(self, th0, iters=30):
        """Levenberg-Marquardt (數值 Jacobian)；線性係數以最小平方消去"""
        th = np.array(th0, np.float64)
        r, c = self.solve(th)
        cost, lam = r @ r, 1e-2
        eps = np.array([0.02, 0.02, 0.02, 0.01])
        for _ in range(iters):
            J = np.empty((self.n, 4))
            for k in range(4):
                t2 = th.copy()
                t2[k] += eps[k]
                J[:, k] = (self.solve(t2)[0] - r) / eps[k]
            JtJ, g = J.T @ J, J.T @ r
            ok = False
            for _ in range(8):
                step = -np.linalg.solve(JtJ + lam * np.diag(np.diag(JtJ) + 1e-12), g)
                t2 = th + step
                t2[2] = max(t2[2], 3.0)
                t2[3] = float(np.clip(t2[3], 0.3, 10.0))
                r2, c2 = self.solve(t2)
                if r2 @ r2 < cost:
                    th, r, c, cost = t2, r2, c2, r2 @ r2
                    lam = max(lam / 3, 1e-7)
                    ok = True
                    break
                lam *= 4
            if not ok or np.abs(step).max() < 2e-3:
                break
        return th, c, float(np.sqrt(cost / max(self.n - 10, 1)))


# ---------------------------------------------------------------------------
# 放射線取樣
# ---------------------------------------------------------------------------
class Rays:
    def __init__(self, R, cfg):
        self.step = cfg["ray_step"]
        self.th = np.linspace(0, 2 * np.pi, cfg["n_rays"], endpoint=False)
        self.r = np.arange(0, cfg["ray_max"] * R, self.step)
        self.dx = (np.cos(self.th)[:, None] * self.r[None, :]).astype(np.float32)
        self.dy = (np.sin(self.th)[:, None] * self.r[None, :]).astype(np.float32)

    def sample(self, img, cx, cy):
        return cv2.remap(img, self.dx + np.float32(cx), self.dy + np.float32(cy), cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)

    def crossing(self, T, level, k_lo, k_end, near=None):
        """
        每條射線在 [k_lo, k_end) 內找 T 由 >= level 跌到 < level 的位置 (子像素)，回傳半徑 (nan = 無)。
        near=None：取最外側的跨越 (聯集外緣，不受圓盤內部紋理影響)；
        給 near：取最接近該半徑的跨越 (8-bit 影像圓盤內部有抖動紋理，第一次跨越常落在內部)。
        """
        n, m = T.shape
        kk = np.arange(m - 1)
        hit = (T[:, :-1] >= level) & (T[:, 1:] < level) & (kk[None, :] >= k_lo) & (kk[None, :] + 1 < k_end[:, None])
        rows = np.flatnonzero(hit.any(1))
        out = np.full(n, np.nan)
        if len(rows) == 0:
            return out
        if near is None:
            k = m - 2 - np.argmax(hit[rows, ::-1], 1)
        else:
            dist = np.where(hit[rows], np.abs(self.r[None, :-1] - near), np.inf)
            k = np.argmin(dist, 1)
        a, b = T[rows, k], T[rows, k + 1]
        t = (a - level) / np.where(np.abs(a - b) > 1e-12, a - b, 1.0)
        out[rows] = self.r[k] + t * self.step
        return out


# ---------------------------------------------------------------------------
# 單顆量測
# ---------------------------------------------------------------------------
def measure_site(A, valid, off, cand, R0, rays, cfg, min_contrast, lobe_on):
    """
    valid：以 off=(x0, y0) 為原點的局部遮罩 (True = 可用像素)。
    回傳 (site dict, None) 或 (None, 剔除原因代碼)
    """
    x, y = cand[0], cand[1]
    H, W = A.shape
    m = cfg["ray_max"] * R0 + 3
    if x < m or y < m or x > W - 1 - m or y > H - 1 - m:
        return None, "border"
    df = DiscFit(A, x, y, R0, valid, off, cfg)
    if df.n < 50:
        return None, "masked"
    th, c, rms_model = df.fit([x, y, R0, 1.5])
    xb, yb, rb, w = th
    if not (0.6 * R0 < rb < 1.5 * R0) or np.hypot(xb - x, yb - y) > 0.5 * R0:
        return None, "model_diverged"
    # 背景 (二次曲面) 沿放射線求值，扣掉後以核心值正規化成 0 (背景) ~ 1 (核心)
    V = rays.sample(A, xb, yb)
    D = V - df.bg_eval(c, rays.dx + xb, rays.dy + yb)
    core = float(np.median(D[:, rays.r < cfg["core_frac"] * rb]))
    if core < min_contrast:
        return None, "low_contrast"
    T = D / core
    # 射線碰到遮罩 (相鄰圓盤/大球/影像外) 就截止
    Mv = rays.sample(valid.astype(np.float32), xb - off[0], yb - off[1]) > 0.5
    k_end = np.where(Mv.all(1), len(rays.r), np.argmin(Mv, 1))
    k_lo = int(0.3 * rb / rays.step)
    n_rays = len(rays.th)

    # ---- 凸塊：高等高線 (取最接近單圓模型預期半徑的跨越：logistic 邊 S = L 處 d = rb + w·ln((1-L)/L)) ----
    r_exp = rb + w * np.log((1 - cfg["bump_level"]) / cfg["bump_level"])
    rad = rays.crossing(T, cfg["bump_level"], k_lo, k_end, near=r_exp)
    ok = ~np.isnan(rad)
    if ok.mean() < cfg["min_cov"]:
        return None, "bump_coverage"
    bpts = np.c_[xb + rad[ok] * np.cos(rays.th[ok]), yb + rad[ok] * np.sin(rays.th[ok])]
    bump = G.robust_circle(bpts, cfg["trim_k"], cfg["trim_min"])
    if bump is None:
        return None, "bump_fit"
    # 凸塊輪廓的橢圓長短軸比與長軸方向 (斜射影像的凸塊會一致地被壓扁)
    (_, _), (ea, eb), eang = cv2.fitEllipse(bpts.astype(np.float32))
    axis_ratio = float(min(ea, eb) / max(ea, eb)) if max(ea, eb) > 0 else 1.0
    axis_deg = float(eang if ea >= eb else eang + 90.0) % 180.0
    bump["cov"] = bump["n"] / n_rays
    if bump["cov"] < cfg["min_cov"]:
        return None, "bump_coverage"
    if bump["rms"] > cfg["max_rms"]:
        return None, "bump_rms"

    # ---- 焊墊：低等高線 (凸塊 ∪ 焊墊的聯集外緣) ----
    rad = rays.crossing(T, cfg["pad_level"], k_lo, k_end)
    ok = ~np.isnan(rad)
    if ok.mean() < cfg["min_cov"]:
        return None, "pad_coverage"
    pts_all = np.c_[xb + rad * np.cos(rays.th), yb + rad * np.sin(rays.th)]
    # 低等高線超出凸塊圓的量 e；焊墊未露出的方向 e ≈ 單一模糊邊緣的高→低等高線距離 Δ0
    e = rad - G.ray_circle(xb, yb, rays.th, bump)
    base = e[ok]
    delta0 = float(np.percentile(base, 30))
    low = base[base <= np.percentile(base, 60)]
    noise = 1.4826 * float(np.median(np.abs(low - np.median(low))))
    exposed = ok & (e > delta0 + max(cfg["lobe_margin"], 3.0 * noise))
    run = G.longest_run(exposed)
    span = len(run) * 360.0 / n_rays
    pad = None
    if lobe_on and span >= cfg["lobe_min_span"] and float(np.median(e[run])) - delta0 >= cfg["lobe_min_excess"] * bump["r"]:
        # 露出弧：焊墊在這一側超出凸塊，只用這段弧擬合焊墊圓
        pts = pts_all[run]
        if span >= cfg["lobe_free_span"]:
            f = G.fit_circle(pts)
            if f and cfg["lobe_r_ratio"][0] * bump["r"] <= f[2] <= cfg["lobe_r_ratio"][1] * bump["r"]:
                pad = dict(x=f[0], y=f[1], r=f[2], free=True)
        if pad is None:
            # 弧不夠長：先假設焊墊與聯集外緣同大 (bump r + Δ0)，之後依陣列的可靠半徑重解
            R = bump["r"] + delta0
            u = np.array([np.cos(rays.th[run]).mean(), np.sin(rays.th[run]).mean()])
            u /= max(np.linalg.norm(u), 1e-9)
            s = max(float(np.median(e[run])) - delta0, 0.0)
            cc = G.fit_center_fixed_r(pts, R, (bump["x"] + u[0] * s, bump["y"] + u[1] * s))
            pad = dict(x=float(cc[0]), y=float(cc[1]), r=R, free=False)
        res = np.hypot(pts[:, 0] - pad["x"], pts[:, 1] - pad["y"]) - pad["r"]
        pad.update(rms=float(np.sqrt((res ** 2).mean())), n=len(pts), cov=len(pts) / n_rays,
                   mode="lobe", span=span, pts=pts)
        if pad["rms"] > cfg["max_rms"] * 1.5:
            pad = None
    if pad is None:
        # 無明顯露出弧：整圈低等高線擬合圓，只修剪窄的離群段 (走線/via 接點)
        f = G.narrow_trim_circle(pts_all, ok, cfg["trace_max_deg"], cfg["trim_k"], cfg["trim_min"])
        if f is None:
            return None, "pad_fit"
        f["cov"] = f["n"] / n_rays
        if f["cov"] < cfg["min_cov"]:
            return None, "pad_coverage"
        if f["rms"] > cfg["max_rms"]:
            return None, "pad_rms"
        pad = dict(f, free=True, mode="concentric", span=span, pts=None)
    if pad["mode"] == "concentric" and pad["r"] <= bump["r"]:
        return None, "pad_inside_bump"
    site = dict(x0=x, y0=y, model_x=float(xb), model_y=float(yb), model_r=float(rb), model_w=float(w),
                model_rms=rms_model, contrast=core, bump=bump, pad=pad, delta0=delta0,
                axis_ratio=axis_ratio, axis_deg=axis_deg)
    set_offset(site)
    return site, None


def set_offset(site):
    b, p = site["bump"], site["pad"]
    site["dx"], site["dy"] = b["x"] - p["x"], b["y"] - p["y"]
    site["d"] = float(np.hypot(site["dx"], site["dy"]))


# ---------------------------------------------------------------------------
# 陣列分群與晶片偏移
# ---------------------------------------------------------------------------
def group_arrays(sites, cfg):
    """依最近鄰距離連結成陣列 (連通元件)；回傳每個位點的陣列編號 (0 = 未成群)，依陣列大小排序編號"""
    n = len(sites)
    if n == 0:
        return np.zeros(0, int)
    xy = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in sites])
    D = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
    np.fill_diagonal(D, np.inf)
    nn = D.min(1)
    # 取兩者最近鄰距離的較大值：旁邊剛好有一顆別種小圓盤時，最近鄰會被拉短而連不上同陣列的鄰居
    link = D <= cfg["link_k"] * np.maximum(nn[:, None], nn[None, :])
    lab = -np.ones(n, int)
    cur = 0
    for i in range(n):
        if lab[i] >= 0:
            continue
        stack = [i]
        lab[i] = cur
        while stack:
            j = stack.pop()
            for k in np.flatnonzero(link[j] & (lab < 0)):
                lab[k] = cur
                stack.append(k)
        cur += 1
    sizes = np.bincount(lab)
    out = np.zeros(n, int)
    aid = 1
    for g in np.argsort(-sizes):
        if sizes[g] < cfg["min_array"]:
            continue
        out[lab == g] = aid
        aid += 1
    return out


def resolve_fixed_pads(group):
    """
    露出弧太短的焊墊先前以「與聯集外緣同大」的半徑解圓心；改用同陣列可靠的焊墊半徑重解：
    優先用自由擬合的半徑 (>= 3 顆)，否則用同陣列同心模式焊墊半徑的中位數。
    """
    free = [s["pad"]["r"] for s in group if s["pad"]["mode"] == "lobe" and s["pad"]["free"]]
    conc = [s["pad"]["r"] for s in group if s["pad"]["mode"] == "concentric"]
    if len(free) >= 3:
        R = float(np.median(free))
    elif len(conc) >= 3:
        R = float(np.median(conc))
    else:
        return
    for s in group:
        p = s["pad"]
        if p["mode"] != "lobe" or p["free"]:
            continue
        c = G.fit_center_fixed_r(p["pts"], R, (p["x"], p["y"]))
        res = np.hypot(p["pts"][:, 0] - c[0], p["pts"][:, 1] - c[1]) - R
        p.update(x=float(c[0]), y=float(c[1]), r=R, rms=float(np.sqrt((res ** 2).mean())))
        set_offset(s)


def grade(est):
    if est is None:
        return ""
    if est["n_in"] >= 30 and est["n_in"] / est["n"] >= 0.6 and est["se"] <= 0.15:
        return "high"
    if est["n_in"] >= 10 and est["n_in"] / est["n"] >= 0.5 and est["se"] <= 0.35:
        return "mid"
    return "low"


def estimate(use, cfg, mark=True):
    if len(use) < 3:
        return None
    src = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in use])
    dst = np.array([[s["bump"]["x"], s["bump"]["y"]] for s in use])
    est = G.estimate_shift(src, dst, cfg["shift_tol"], cfg["shift_k"])
    if est is None:
        return None
    if mark:
        for s, ok in zip(use, est["inliers"]):
            s["inlier"] = bool(ok)
    est.pop("inliers")
    return est


def bbox_of(ss):
    if not ss:
        return None
    xs = [s["pad"]["x"] for s in ss]
    ys = [s["pad"]["y"] for s in ss]
    r = max(s["pad"]["r"] for s in ss)
    return (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)


# ---------------------------------------------------------------------------
# 整張影像
# ---------------------------------------------------------------------------
def analyze(A, kind, cfg, in_region=None):
    """
    回傳 dict：R0、n_cand、n_balls、sites、rejects、rejected、arrays、est (整張)、grade。
    找不到足夠凸塊時 R0 為 None。in_region(x, y)：檢測區域判斷，區域外的凸塊不量測 (None 為整張)。
    """
    H, W = A.shape
    bumps, balls, R0 = detect_blobs(A, kind, cfg)
    if in_region is not None:
        bumps = [b for b in bumps if in_region(b[0], b[1])]
    out = dict(R0=R0, n_cand=len(bumps), n_balls=len(balls), sites=[], rejects={}, rejected=[], arrays=[],
               est=None, grade="", metrics={})
    if R0 is None:
        return out
    # 遮罩：大球 + 每顆候選圓盤 (量測時把自己放回來)
    ball_mask = np.zeros((H, W), np.uint8)
    for (x, y, r, _) in balls:
        cv2.circle(ball_mask, (int(round(x)), int(round(y))), int(round(r * cfg["ball_margin"] + cfg["nb_margin"])), 1, -1)
    disc_lab = np.zeros((H, W), np.int32)
    for i, (x, y, r, _) in enumerate(bumps):
        cv2.circle(disc_lab, (int(round(x)), int(round(y))), int(round(r + cfg["nb_margin"])), i + 1, -1)
    rays = Rays(R0, cfg)
    min_contrast = cfg["min_contrast_rgb"] if kind == KIND_RGB8 else cfg["min_contrast_raw"]
    # 露出弧模式：auto 時只用於 8-bit 影像 (「暗圓＋淡瓣」經人工確認是焊墊露出)；
    # 16-bit 影像的淡色延伸是基板走線/via 的淚滴，當成焊墊會把 via 量進來
    lobe_on = cfg["lobe"] == "on" or (cfg["lobe"] == "auto" and kind == KIND_RGB8)
    sites, rejects, rejected = [], {}, []

    def reject(x, y, r, why):
        rejects[why] = rejects.get(why, 0) + 1
        rejected.append(dict(x=float(x), y=float(y), r=float(r), reason=why))

    for i, cand in enumerate(bumps):
        x, y, r = cand[0], cand[1], cand[2]
        # 大半疊在大球上的凸塊：背景不是平滑曲面，不量 (只是貼著大球的，靠遮罩截斷射線照量)
        if any(np.hypot(x - bx, y - by) < br * cfg["ball_margin"] + cfg["ball_overlap"] * r for (bx, by, br, _) in balls):
            reject(x, y, r, "on_ball")
            continue
        h = int(cfg["ray_max"] * R0 * 1.2) + 4
        y0, y1, x0, x1 = max(int(y) - h, 0), min(int(y) + h + 1, H), max(int(x) - h, 0), min(int(x) + h + 1, W)
        lab = disc_lab[y0:y1, x0:x1]
        valid = ((lab == 0) | (lab == i + 1)) & (ball_mask[y0:y1, x0:x1] == 0)
        s, why = measure_site(A, valid, (x0, y0), cand, R0, rays, cfg, min_contrast, lobe_on)
        if s is None:
            reject(x, y, r, why)
            continue
        sites.append(s)

    arr = group_arrays(sites, cfg)
    for s, a in zip(sites, arr):
        s["array"] = int(a)
        s["used"] = a > 0
        s["reason"] = "" if a > 0 else "isolated"
        s["inlier"] = False
    for a in set(arr.tolist()) - {0}:
        idx = np.flatnonzero(arr == a)
        resolve_fixed_pads([sites[i] for i in idx])
        rb = np.array([sites[i]["bump"]["r"] for i in idx])
        rp = np.array([sites[i]["pad"]["r"] for i in idx])
        mb, mp = np.median(rb), np.median(rp)
        # 半徑一致性：與同陣列中位數差太多的不採用 (被部分遮住、或不是同一種凸塊)
        for i, b_, p_ in zip(idx, rb, rp):
            if abs(b_ - mb) > cfg["r_dev"] * mb or abs(p_ - mp) > cfg["r_dev"] * mp:
                sites[i]["used"] = False
                sites[i]["reason"] = "radius_outlier"
    arrays = []
    for a in sorted(set(arr.tolist()) - {0}):
        use = [s for s in sites if s["array"] == a and s["used"]]
        est = estimate(use, cfg)
        arrays.append(dict(id=a, n_sites=int((arr == a).sum()), est=est, grade=grade(est),
                           bump_r=float(np.median([s["bump"]["r"] for s in use])) if use else None,
                           pad_r=float(np.median([s["pad"]["r"] for s in use])) if use else None,
                           pitch=pitch_of(use), bbox=bbox_of([s for s in sites if s["array"] == a])))
    est_all = estimate([s for s in sites if s["used"]], cfg, mark=False)
    out.update(sites=sites, rejects=rejects, rejected=rejected, arrays=arrays, est=est_all, grade=grade(est_all))
    out["metrics"] = quality_metrics(out)
    return out


def pitch_of(ss):
    """陣列 pitch：各點與最近鄰距離的中位數 (px)"""
    if len(ss) < 3:
        return None
    xy = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in ss])
    D = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
    np.fill_diagonal(D, np.inf)
    return float(np.median(D.min(1)))


def quality_metrics(out):
    """
    模組品質指標：
      sites_used        可採用位點數
      measurable_ratio  可採用位點 / (候選數 - 貼邊 - 疊在大球上)
      contrast          凸塊核心吸收對比 (中位數)
      edge_width_ratio  邊緣模糊寬度 / 凸塊半徑 (中位數)；焦點變大或失焦時變大
      oblique_angle_deg 等效斜射角：各顆扁平度 e = 1 - 長短軸比，沿長軸方向 (2θ) 做向量平均得一致扁平度 ce，
                        角度 = arccos(1 - ce)。凸塊天生不圓的方向隨機會互相抵消，斜射造成的扁平方向一致會累加。
                        正射影像 (Batch1/2) 的值為 5～19°，因此只能可靠偵測約 25° 以上的斜射；
                        更小角度需以拍攝參數 view_angle_deg 把關
      axis_coherence    長軸方向一致性 (0～1)
      pitch_px          最大陣列的 pitch
    """
    used = [s for s in out["sites"] if s["used"]]
    rj = out["rejects"]
    denom = out["n_cand"] - rj.get("border", 0) - rj.get("on_ball", 0)
    m = {"sites_used": len(used), "measurable_ratio": len(used) / denom if denom > 0 else 0.0}
    if not used:
        return m
    ratios = np.array([s["axis_ratio"] for s in used])
    ang = np.radians([s["axis_deg"] for s in used]) * 2
    coh = float(np.hypot(np.cos(ang).mean(), np.sin(ang).mean()))
    ce = float(np.abs(np.mean((1 - ratios) * np.exp(1j * ang))))
    med_ratio = float(np.median(ratios))
    main = max(out["arrays"], key=lambda a: a["n_sites"]) if out["arrays"] else None
    m.update(contrast=float(np.median([s["contrast"] for s in used])),
             edge_width_px=float(np.median([s["model_w"] for s in used])),
             edge_width_ratio=float(np.median([s["model_w"] / s["model_r"] for s in used])),
             axis_ratio_median=med_ratio, axis_coherence=coh,
             axis_direction_deg=float(np.degrees(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) / 2 % 180),
             coherent_elongation=ce, oblique_angle_deg=float(np.degrees(np.arccos(np.clip(1 - ce, -1, 1)))),
             pitch_px=main["pitch"] if main else None)
    return m
