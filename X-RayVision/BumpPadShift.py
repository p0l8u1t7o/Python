"""
Flip-Chip X 光：micro bump／pad 圓心量測與整片晶片偏移量（支援 16-bit 原始影像與 8-bit RGB 轉存影像）

用法:
    python BumpPadShift.py <影像或資料夾 ...> [--out 輸出資料夾] [--workers N]
                           [--bump-level 0.75] [--pad-level 0.25] [--px-um 每像素微米]

每張影像輸出 (在 --out/<批次資料夾名>/ 下):
    <name>_overlay.jpg     疊圖：紅＝凸塊圓、綠＝pad 圓、黃線＝偏移向量 (放大 arrow_scale 倍)、
                           灰＝被篩掉的位點；陣列外框與該陣列的晶片偏移文字
    <name>_sites.csv       每個位點一列 (凸塊/pad 圓心與半徑、偏移、擬合品質、所屬陣列、是否內點)
    <name>_arrays.csv      每個陣列一列 (位點數、相似變換的平移/旋轉/縮放、內點數、標準誤)
整批輸出:
    summary.csv            每張影像一列：整張與最大陣列的晶片偏移
    report.md              各批次整理 (含同視野重拍的重複性比較)

量測原理 (Pad 在凸塊正下方，兩者大致重疊):
    X 光穿透影像取 -ln(I) 成為吸收量，重疊的材料在吸收量空間可以相加。
    凸塊 (錫，原子序高、厚) 形成最暗的核心；pad (銅，薄) 疊在同一處、只在錯開的一側露出較淡的邊。
    因此在同一顆位點上：
      - 高等高線 (bump_level，由背景 0 到核心 1 的 75%) 主要由凸塊決定 → 凸塊圓
      - 低等高線 (pad_level，25%) 是凸塊與 pad 的聯集外緣，錯開側由 pad 決定 → pad 圓
      兩圓心差 = 凸塊相對 pad 的偏移。基板走線/via 接在圓盤上的方向，低等高線會被往外拉，
      這些射線以穩健圓擬合 (殘差修剪) 剔除。
    背景用二次曲面 (與單圓模型一起最小平方擬合) 扣除，大球 (BGA 等) 與相鄰圓盤以遮罩排除。

整體偏移:
    每張影像的位點依 pitch 連結成陣列；對每個陣列 (與整張) 以 pad 圓心 → 凸塊圓心 做相似變換
    (平移 + 旋轉 + 縮放) 的穩健最小平方，報變換在陣列中心處的偏移向量。
    縮放項吸收錐形束放大率差 (凸塊與 pad 高度不同)；correction = -shift 為晶片需要移動的量。
"""
import argparse
import csv
import glob
import os
import time
from concurrent.futures import ProcessPoolExecutor

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# 參數 (尺寸以偵測到的凸塊半徑 R0 為單位，所以不同倍率不用手調)
# ---------------------------------------------------------------------------
P = dict(
    raw_sigma=1.0,           # 16-bit：取 log 前的高斯去噪
    rgb_median=5,            # 8-bit RGB：中值去除抖動雜訊
    rgb_sigma=2.0,           # 8-bit RGB：再高斯
    det_r_lo=10.0,           # LoG 尺度空間：最小半徑 (px)
    det_r_hi=110.0,          # LoG 尺度空間：最大半徑 (px)
    det_n_scales=24,         # LoG 尺度數
    det_rel=0.15,            # 偵測門檻 = 此值 x 響應 99.5 百分位
    det_rel_rgb=0.30,        # 8-bit 影像雜訊大，門檻提高
    bump_r_range=(12.0, 48.0),  # 凸塊半徑的搜尋範圍 (決定 R0 用)
    bump_r_tol=(0.6, 1.5),   # 候選凸塊半徑 / R0 的範圍
    ball_ratio=1.8,          # 半徑 >= 此值 x R0 視為大球 (BGA 等)，遮罩排除
    ball_margin=1.08,        # 大球遮罩半徑倍率
    ball_overlap=0.3,        # 凸塊中心離大球邊 < 此值 x 凸塊半徑 (大半疊在球上) 才整顆不量
    nb_margin=3.0,           # 相鄰圓盤遮罩：半徑 + 此值 (px)
    fit_win=1.9,             # 單圓模型擬合視窗半徑 / R0
    fit_stride=2,            # 擬合取樣間隔 (px)
    n_rays=120,              # 放射線數
    ray_max=1.75,            # 放射線最遠 / R0
    ray_step=0.25,           # 放射線取樣間距 (px)
    core_frac=0.35,          # 核心灰階 = 半徑 < core_frac x R 內的中位數
    bump_level=0.75,         # 凸塊等高線 (背景 0 → 核心 1)
    pad_level=0.25,          # pad 等高線
    min_cov=0.55,            # 有效射線比例下限 (修剪後)
    trim_k=2.5,              # 穩健圓擬合：殘差 > trim_k x 1.4826 x MAD 的點剔除
    trim_min=0.6,            # 修剪門檻下限 (px)
    max_rms=2.0,             # 修剪後圓擬合 RMS 上限 (px)；凸塊外形本來就不是正圓，中位數約 1 px
    min_contrast_raw=0.02,   # 16-bit：核心吸收量下限 (-ln 單位)
    min_contrast_rgb=0.06,   # 8-bit：核心暗度下限 (0~1)
    r_dev=0.15,              # 凸塊半徑與陣列中位數差 <= 此比例
    link_k=1.45,             # 陣列連結：距離 <= link_k x 最近鄰距離中位數
    min_array=6,             # 陣列至少幾顆
    trace_max_deg=40.0,      # pad 同心模式：連續離群段角寬 < 此值才當走線/via 剔除 (更寬的是 pad 露出)
    lobe_margin=1.5,         # 低等高線超出「凸塊圓 + Δ0」此值 (px，且 >= 3 倍雜訊) 才算 pad 露出
    lobe="auto",             # pad 露出弧模式：auto (只用於 8-bit RGB) / on / off
    lobe_min_excess=0.12,    # 露出弧的超出量 (中位數，扣掉 Δ0) 至少此值 x 凸塊半徑；小的露出交給同心模式，重拍雜訊較低
    lobe_min_span=50.0,      # 露出弧至少跨幾度才用露出弧模型 (走線/via 只有窄弧)
    lobe_free_span=150.0,    # 弧跨度 >= 此值才自由擬合 pad 半徑，否則固定半徑只解圓心
    lobe_r_ratio=(0.6, 1.8), # 自由擬合 pad 半徑 / 凸塊半徑 合理範圍
    shift_tol=0.5,           # 整體偏移內點容差下限 (px)
    shift_k=3.0,             # 內點容差 = max(shift_tol, shift_k x 1.4826 x MAD)
    arrow_scale=10.0,        # 疊圖偏移向量放大倍率
)


# ---------------------------------------------------------------------------
# 讀取
# ---------------------------------------------------------------------------
def load_image(path):
    """
    回傳 dict(A=吸收量 float32 (越大越暗), disp=顯示用 8-bit 灰階, kind='raw16'|'rgb8')
    16-bit：A = -ln(I/65535)，吸收量可相加 (重疊的凸塊與 pad、疊在大球上的凸塊)。
    8-bit RGB：已是檢視軟體拉伸過的影像 (非線性、近二值抖動)，只能去噪後以 (255-I)/255 近似。
    """
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        raise IOError(f"無法讀取影像: {path}")
    if im.ndim == 3:
        g = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2GRAY)
    else:
        g = im
    if g.dtype == np.uint16:
        f = cv2.GaussianBlur(g.astype(np.float32), (0, 0), P["raw_sigma"])
        A = -np.log(np.maximum(f, 1.0) / 65535.0)
        kind = "raw16"
    else:
        g8 = g if g.dtype == np.uint8 else cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        f = cv2.GaussianBlur(cv2.medianBlur(g8, P["rgb_median"]).astype(np.float32), (0, 0), P["rgb_sigma"])
        A = (255.0 - f) / 255.0
        kind = "rgb8"
    lo, hi = np.percentile(f, [0.5, 99.5])
    disp = np.clip((f - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
    return dict(A=A.astype(np.float32), disp=disp, kind=kind)


# ---------------------------------------------------------------------------
# 偵測：LoG 尺度空間 → 凸塊候選 + 大球
# ---------------------------------------------------------------------------
def detect_blobs(A, kind):
    radii = np.geomspace(P["det_r_lo"], P["det_r_hi"], P["det_n_scales"])
    best = np.full(A.shape, -np.inf, np.float32)
    arg = np.zeros(A.shape, np.float32)
    for r in radii:
        s = r / np.sqrt(2)
        lap = -cv2.Laplacian(cv2.GaussianBlur(A, (0, 0), s), cv2.CV_32F, ksize=3) * s * s
        m = lap > best
        best[m] = lap[m]
        arg[m] = r
    k = int(P["det_r_lo"] * 1.5) | 1
    mx = cv2.dilate(best, np.ones((k, k), np.uint8))
    pk = np.argwhere((best >= mx - 1e-12) & (best > 0))
    resp = best[pk[:, 0], pk[:, 1]]
    rel = P["det_rel_rgb"] if kind == "rgb8" else P["det_rel"]
    keep = resp > rel * np.percentile(resp, 99.5)
    pk, resp = pk[keep], resp[keep]
    rr = arg[pk[:, 0], pk[:, 1]]
    # 同一物件在相鄰尺度產生多個極大值：響應大者優先，吃掉中心落在其 0.6r 內的
    blobs = []
    for i in np.argsort(-resp):
        y, x, r = int(pk[i][0]), int(pk[i][1]), float(rr[i])
        if any((x - b[0]) ** 2 + (y - b[1]) ** 2 < (0.6 * max(r, b[2])) ** 2 for b in blobs):
            continue
        blobs.append((float(x), float(y), r, float(resp[i])))
    rs = np.array([b[2] for b in blobs])
    lo, hi = P["bump_r_range"]
    sel = rs[(rs >= lo) & (rs <= hi)]
    if len(sel) < 5:
        raise RuntimeError("找不到足夠的凸塊候選")
    # R0 = 凸塊半徑的主峰 (以響應加權的對數直方圖)
    hist, edges = np.histogram(np.log(sel), bins=24)
    j = int(np.argmax(hist))
    R0 = float(np.exp(0.5 * (edges[j] + edges[j + 1])))
    bumps = [b for b in blobs if P["bump_r_tol"][0] * R0 <= b[2] <= P["bump_r_tol"][1] * R0]
    balls = [b for b in blobs if b[2] >= P["ball_ratio"] * R0]
    return bumps, balls, R0


# ---------------------------------------------------------------------------
# 單圓模型 (精修圓心、半徑、背景)：A = 二次背景 + a·S(r) + b·S(r)·(1-(d/r)^2)
# ---------------------------------------------------------------------------
def _sig(d, r, w):
    return 1.0 / (1.0 + np.exp(np.clip((d - r) / w, -30, 30)))


class DiscFit:
    def __init__(self, A, cx, cy, R, valid, off, stride):
        H, W = A.shape
        h = int(np.ceil(P["fit_win"] * R))
        x0, x1 = max(int(round(cx)) - h, 0), min(int(round(cx)) + h + 1, W)
        y0, y1 = max(int(round(cy)) - h, 0), min(int(round(cy)) + h + 1, H)
        yy, xx = np.mgrid[y0:y1:stride, x0:x1:stride]
        sub = A[y0:y1:stride, x0:x1:stride]
        vx0, vy0 = off
        m = ((xx - cx) ** 2 + (yy - cy) ** 2 <= (P["fit_win"] * R) ** 2) & \
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
# 等高線圓：放射線子像素跨越點 + 穩健圓擬合
# ---------------------------------------------------------------------------
def fit_circle(pts):
    """Kasa 代數最小平方；回傳 (cx, cy, r) 或 None"""
    if len(pts) < 5:
        return None
    A = np.c_[2 * pts, np.ones(len(pts))]
    b = (pts ** 2).sum(1)
    s, *_ = np.linalg.lstsq(A, b, rcond=None)
    r2 = s[2] + s[0] ** 2 + s[1] ** 2
    return (float(s[0]), float(s[1]), float(np.sqrt(r2))) if r2 > 0 else None


def robust_circle(pts):
    """反覆修剪 (殘差 > trim_k·σ_MAD) 的圓擬合；回傳 dict 或 None"""
    keep = np.ones(len(pts), bool)
    fit = None
    for _ in range(6):
        fit = fit_circle(pts[keep])
        if fit is None:
            return None
        res = np.hypot(pts[:, 0] - fit[0], pts[:, 1] - fit[1]) - fit[2]
        mad = 1.4826 * np.median(np.abs(res[keep] - np.median(res[keep])))
        new = np.abs(res - np.median(res[keep])) <= max(P["trim_min"], P["trim_k"] * mad)
        if new.sum() < 5 or np.array_equal(new, keep):
            break
        keep = new
    fit = fit_circle(pts[keep])
    if fit is None:
        return None
    res = np.hypot(pts[keep, 0] - fit[0], pts[keep, 1] - fit[1]) - fit[2]
    return dict(x=fit[0], y=fit[1], r=fit[2], rms=float(np.sqrt((res ** 2).mean())), n=int(keep.sum()))


class Rays:
    def __init__(self, R):
        self.th = np.linspace(0, 2 * np.pi, P["n_rays"], endpoint=False)
        self.r = np.arange(0, P["ray_max"] * R, P["ray_step"])
        self.dx = (np.cos(self.th)[:, None] * self.r[None, :]).astype(np.float32)
        self.dy = (np.sin(self.th)[:, None] * self.r[None, :]).astype(np.float32)

    def sample(self, img, cx, cy):
        return cv2.remap(img, self.dx + np.float32(cx), self.dy + np.float32(cy), cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)

    def crossing(self, T, level, k_lo, k_end, near=None):
        """
        每條射線在 [k_lo, k_end) 內找 T 由 >= level 跌到 < level 的位置 (子像素)，回傳半徑 (nan = 無)。
        near=None：取最外側的跨越 (聯集外緣；不受圓盤內部紋理影響)；
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
        out[rows] = self.r[k] + t * P["ray_step"]
        return out


def measure_site(A, valid, off, cand, R0, rays, min_contrast, lobe_on=True):
    """
    valid: 以 off=(x0, y0) 為原點的局部遮罩 (True = 可用像素)。
    回傳 (site dict, None) 或 (None, 剔除原因)
    """
    x, y = cand[0], cand[1]
    H, W = A.shape
    m = P["ray_max"] * R0 + 3
    if x < m or y < m or x > W - 1 - m or y > H - 1 - m:
        return None, "border"
    df = DiscFit(A, x, y, R0, valid, off, P["fit_stride"])
    if df.n < 50:
        return None, "masked"
    th, c, rms_model = df.fit([x, y, R0, 1.5])
    xb, yb, rb, w = th
    if not (0.6 * R0 < rb < 1.5 * R0) or np.hypot(xb - x, yb - y) > 0.5 * R0:
        return None, "model diverged"
    # 背景 (二次曲面) 沿放射線求值，扣掉後以核心值正規化成 0 (背景) ~ 1 (核心)
    V = rays.sample(A, xb, yb)
    X, Y = rays.dx + xb, rays.dy + yb
    Tbg = df.bg_eval(c, X, Y)
    D = V - Tbg
    core = float(np.median(D[:, rays.r < P["core_frac"] * rb]))
    if core < min_contrast:
        return None, "low contrast"
    T = D / core
    # 射線碰到遮罩 (相鄰圓盤/大球/影像外) 就截止
    Mv = rays.sample(valid.astype(np.float32), xb - off[0], yb - off[1]) > 0.5
    k_end = np.where(Mv.all(1), len(rays.r), np.argmin(Mv, 1))
    k_lo = int(0.3 * rb / P["ray_step"])
    out = {}
    # ---- 凸塊：高等高線 ----
    # 單圓模型在此等高線的預期半徑：logistic 邊 S = L 處 d = rb + w·ln((1-L)/L)
    r_exp = rb + w * np.log((1 - P["bump_level"]) / P["bump_level"])
    rad = rays.crossing(T, P["bump_level"], k_lo, k_end, near=r_exp)
    ok = ~np.isnan(rad)
    if ok.mean() < P["min_cov"]:
        return None, "bump coverage"
    bump = robust_circle(np.c_[xb + rad[ok] * np.cos(rays.th[ok]), yb + rad[ok] * np.sin(rays.th[ok])])
    if bump is None:
        return None, "bump fit"
    bump["cov"] = bump["n"] / len(rays.th)
    if bump["cov"] < P["min_cov"]:
        return None, "bump coverage"
    if bump["rms"] > P["max_rms"]:
        return None, "bump rms"
    # ---- pad：低等高線 (凸塊 ∪ pad 的聯集外緣) ----
    rad = rays.crossing(T, P["pad_level"], k_lo, k_end)
    ok = ~np.isnan(rad)
    if ok.mean() < P["min_cov"]:
        return None, "pad coverage"
    pts_all = np.c_[xb + rad * np.cos(rays.th), yb + rad * np.sin(rays.th)]
    # 每條射線上低等高線超出凸塊圓多少 (e)；未露出 pad 的方向 e ≈ 單一模糊邊緣的高→低等高線距離 Δ0
    e = rad - ray_circle(xb, yb, rays.th, bump)
    base = e[ok]
    delta0 = float(np.percentile(base, 30))
    low = base[base <= np.percentile(base, 60)]
    noise = 1.4826 * float(np.median(np.abs(low - np.median(low))))
    margin = max(P["lobe_margin"], 3.0 * noise)
    exposed = ok & (e > delta0 + margin)
    run = longest_run(exposed)
    span = len(run) * 360.0 / len(rays.th)
    pad = None
    if lobe_on and span >= P["lobe_min_span"] and float(np.median(e[run])) - delta0 >= P["lobe_min_excess"] * bump["r"]:
        # 露出弧：pad 在這一側超出凸塊，用這段弧擬合 pad 圓
        pts = pts_all[run]
        if span >= P["lobe_free_span"]:
            f = fit_circle(pts)
            if f and P["lobe_r_ratio"][0] * bump["r"] <= f[2] <= P["lobe_r_ratio"][1] * bump["r"]:
                pad = dict(x=f[0], y=f[1], r=f[2], free=True)
        if pad is None:
            # 弧不夠長：先假設 pad 與凸塊聯集外緣同大 (bump r + Δ0)，之後依陣列的自由擬合中位半徑重解
            R = bump["r"] + delta0
            u = np.array([np.cos(rays.th[run]).mean(), np.sin(rays.th[run]).mean()])
            u /= max(np.linalg.norm(u), 1e-9)
            shift = max(float(np.median(e[run])) - delta0, 0.0)
            c = fit_center_fixed_r(pts, R, (bump["x"] + u[0] * shift, bump["y"] + u[1] * shift))
            pad = dict(x=c[0], y=c[1], r=R, free=False)
        res = np.hypot(pts[:, 0] - pad["x"], pts[:, 1] - pad["y"]) - pad["r"]
        pad.update(rms=float(np.sqrt((res ** 2).mean())), n=len(pts), cov=len(pts) / len(rays.th),
                   mode="lobe", span=span, pts=pts)
        if pad["rms"] > P["max_rms"] * 1.5:
            pad = None
    if pad is None:
        # 沒有明顯露出弧：整圈低等高線擬合圓。只修剪「窄」的離群段 (走線/via 接點)，
        # 寬的離群弧是 pad 略微露出，保留下來才不會把小偏移低估成 0
        f = narrow_trim_circle(pts_all, ok, rays.th)
        if f is None:
            return None, "pad fit"
        f["cov"] = f["n"] / len(rays.th)
        if f["cov"] < P["min_cov"]:
            return None, "pad coverage"
        if f["rms"] > P["max_rms"]:
            return None, "pad rms"
        pad = dict(f, free=True, mode="concentric", span=span, pts=None)
    if pad["mode"] == "concentric" and pad["r"] <= bump["r"]:
        return None, "pad inside bump"
    site = dict(x0=x, y0=y, model_x=xb, model_y=yb, model_r=rb, model_w=w, model_rms=rms_model,
                contrast=core, bump=bump, pad=pad, delta0=delta0)
    set_offset(site)
    return site, None


def narrow_trim_circle(pts, ok, th):
    """
    環狀射線點的圓擬合：反覆找出殘差離群 (> trim_k·σ) 的連續區段，只剔除角寬 < trace_max_deg 的區段。
    回傳 dict 或 None
    """
    keep = ok.copy()
    n = len(th)
    fit = None
    for _ in range(6):
        fit = fit_circle(pts[keep])
        if fit is None:
            return None
        res = np.hypot(pts[:, 0] - fit[0], pts[:, 1] - fit[1]) - fit[2]
        rk = res[keep]
        sig = max(P["trim_min"] / P["trim_k"], 1.4826 * float(np.median(np.abs(rk - np.median(rk)))))
        bad = ok & (np.abs(res - np.median(rk)) > P["trim_k"] * sig)
        drop = np.zeros(n, bool)
        # 環狀連續段
        lab = np.zeros(n, int)
        cur = 0
        start = int(np.argmin(bad)) if not bad.all() else 0
        for k in range(n):
            i = (start + k) % n
            if bad[i]:
                if k == 0 or not bad[(i - 1) % n]:
                    cur += 1
                lab[i] = cur
        for g in range(1, cur + 1):
            idx = np.flatnonzero(lab == g)
            if len(idx) * 360.0 / n < P["trace_max_deg"]:
                drop[idx] = True
        new = ok & ~drop
        if new.sum() < 5 or np.array_equal(new, keep):
            break
        keep = new
    fit = fit_circle(pts[keep])
    if fit is None:
        return None
    res = np.hypot(pts[keep, 0] - fit[0], pts[keep, 1] - fit[1]) - fit[2]
    return dict(x=fit[0], y=fit[1], r=fit[2], rms=float(np.sqrt((res ** 2).mean())), n=int(keep.sum()))


def set_offset(site):
    b, p = site["bump"], site["pad"]
    site["dx"], site["dy"] = b["x"] - p["x"], b["y"] - p["y"]
    site["d"] = float(np.hypot(site["dx"], site["dy"]))


def ray_circle(ox, oy, th, c):
    """由 (ox, oy) 沿角度 th 的射線與圓 c 的交點距離 (取外側交點)"""
    ux, uy = np.cos(th), np.sin(th)
    qx, qy = c["x"] - ox, c["y"] - oy
    proj = ux * qx + uy * qy
    perp2 = (qx * qx + qy * qy) - proj * proj
    return proj + np.sqrt(np.maximum(c["r"] ** 2 - perp2, 0.0))


def longest_run(mask):
    """環狀布林陣列中最長的連續 True 區段，回傳索引陣列"""
    n = len(mask)
    if mask.all():
        return np.arange(n)
    if not mask.any():
        return np.zeros(0, int)
    start = int(np.argmin(mask))                  # 從某個 False 之後開始走，避免跨越 0 的區段被切斷
    best, cur = [], []
    for k in range(1, n + 1):
        i = (start + k) % n
        if mask[i]:
            cur.append(i)
            if len(cur) > len(best):
                best = list(cur)
        else:
            cur = []
    return np.array(best, int)


def fit_center_fixed_r(pts, R, c0, iters=30):
    """固定半徑 R，只解圓心 (Gauss-Newton)"""
    c = np.array(c0, np.float64)
    for _ in range(iters):
        d = pts - c
        rr = np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)
        J = -d / rr[:, None]
        step, *_ = np.linalg.lstsq(J, -(rr - R), rcond=None)
        c += step
        if np.abs(step).max() < 1e-4:
            break
    return c


# ---------------------------------------------------------------------------
# 陣列分群與整體偏移
# ---------------------------------------------------------------------------
def group_arrays(sites):
    """依最近鄰距離連結成陣列 (連通元件)；回傳每個位點的陣列編號 (0 = 未成群)"""
    n = len(sites)
    if n == 0:
        return np.zeros(0, int)
    xy = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in sites])
    D = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
    np.fill_diagonal(D, np.inf)
    nn = D.min(1)
    # 用兩者最近鄰距離的較大值：旁邊剛好有一顆別種小圓盤時，最近鄰會被拉短而連不上同陣列的鄰居
    link = D <= P["link_k"] * np.maximum(nn[:, None], nn[None, :])
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
    order = np.argsort(-sizes)
    out = np.zeros(n, int)
    aid = 1
    for g in order:
        if sizes[g] < P["min_array"]:
            continue
        out[lab == g] = aid
        aid += 1
    return out


def similarity_lsq(src, dst):
    """Umeyama：dst ≈ s·R·src + t；回傳 2x3 矩陣"""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    C = b.T @ a / len(src)
    U, S, Vt = np.linalg.svd(C)
    d = np.sign(np.linalg.det(U @ Vt))
    Dm = np.diag([1, d])
    Rm = U @ Dm @ Vt
    var = (a ** 2).sum() / len(src)
    s = float(np.trace(np.diag(S) @ Dm) / var)
    t = md - s * Rm @ ms
    return np.c_[s * Rm, t]


def estimate_shift(src, dst):
    """
    穩健估計一組位點的整體偏移：以偏移向量中位數起始選內點，再對內點做相似變換、以殘差重選內點。
    回傳 dict：dx/dy (變換在內點中心處的偏移)、rot_deg、scale_ppm、n、n_in、rms、se、inlier mask
    """
    n = len(src)
    if n < 3:
        return None
    v = dst - src
    med = np.median(v, 0)
    res = np.hypot(*(v - med).T)
    tol = max(P["shift_tol"], P["shift_k"] * 1.4826 * np.median(res))
    inl = res <= tol
    M = None
    for _ in range(8):
        if inl.sum() < 3:
            return None
        if inl.sum() >= 6:
            M = similarity_lsq(src[inl], dst[inl])
            pred = src @ M[:, :2].T + M[:, 2]
        else:
            M = np.c_[np.eye(2), v[inl].mean(0)]
            pred = src + v[inl].mean(0)
        res = np.hypot(*(dst - pred).T)
        tol = max(P["shift_tol"], P["shift_k"] * 1.4826 * np.median(res[inl]))
        new = res <= tol
        if np.array_equal(new, inl):
            break
        inl = new
    c = src[inl].mean(0)
    vc = M[:, :2] @ c + M[:, 2] - c
    rms = float(np.sqrt((res[inl] ** 2).mean()))
    n_in = int(inl.sum())
    return dict(dx=float(vc[0]), dy=float(vc[1]), mag=float(np.hypot(*vc)),
                rot_deg=float(np.degrees(np.arctan2(M[1, 0], M[0, 0]))),
                scale_ppm=float((np.hypot(M[0, 0], M[1, 0]) - 1) * 1e6),
                n=n, n_in=n_in, rms=rms, se=rms / np.sqrt(max(n_in - 4, 1)),
                cx=float(c[0]), cy=float(c[1]), inl=inl)


def grade(est):
    if est is None:
        return "-"
    if est["n_in"] >= 30 and est["n_in"] / est["n"] >= 0.6 and est["se"] <= 0.15:
        return "high"
    if est["n_in"] >= 10 and est["n_in"] / est["n"] >= 0.5 and est["se"] <= 0.35:
        return "mid"
    return "low"


# ---------------------------------------------------------------------------
# 單張處理
# ---------------------------------------------------------------------------
def process_image(path):
    t0 = time.time()
    img = load_image(path)
    A = img["A"]
    H, W = A.shape
    bumps, balls, R0 = detect_blobs(A, img["kind"])
    # 遮罩：大球 + 每顆候選圓盤 (量測時再把自己放回來)
    ball_mask = np.zeros((H, W), np.uint8)
    for (x, y, r, _) in balls:
        cv2.circle(ball_mask, (int(round(x)), int(round(y))), int(round(r * P["ball_margin"] + P["nb_margin"])), 1, -1)
    disc_lab = np.zeros((H, W), np.int32)
    for i, (x, y, r, _) in enumerate(bumps):
        cv2.circle(disc_lab, (int(round(x)), int(round(y))), int(round(r + P["nb_margin"])), i + 1, -1)
    rays = Rays(R0)
    min_contrast = P["min_contrast_rgb"] if img["kind"] == "rgb8" else P["min_contrast_raw"]
    # 露出弧模式：auto 時只用在 8-bit 影像 (Batch1 的「暗圓＋淡瓣」經人工確認是 pad 露出)；
    # 16-bit 影像的淡色延伸是基板走線/via 的淚滴 (上下方向都有)，當成 pad 會把 via 量進來
    lobe_on = P["lobe"] == "on" or (P["lobe"] == "auto" and img["kind"] == "rgb8")
    sites, rejects, rejected = [], {}, []
    for i, cand in enumerate(bumps):
        x, y, r = cand[0], cand[1], cand[2]
        # 疊在大球上的凸塊：背景不是平滑曲面，不量 (只是貼著大球的，靠遮罩截斷射線照量)
        if any(np.hypot(x - bx, y - by) < br * P["ball_margin"] + P["ball_overlap"] * r for (bx, by, br, _) in balls):
            rejects["on/near ball"] = rejects.get("on/near ball", 0) + 1
            rejected.append((x, y, r, "on/near ball"))
            continue
        h = int(P["ray_max"] * R0 * 1.2) + 4
        y0, y1, x0, x1 = max(int(y) - h, 0), min(int(y) + h + 1, H), max(int(x) - h, 0), min(int(x) + h + 1, W)
        lab = disc_lab[y0:y1, x0:x1]
        valid = ((lab == 0) | (lab == i + 1)) & (ball_mask[y0:y1, x0:x1] == 0)
        s, why = measure_site(A, valid, (x0, y0), cand, R0, rays, min_contrast, lobe_on)
        if s is None:
            rejects[why] = rejects.get(why, 0) + 1
            rejected.append((x, y, r, why))
            continue
        sites.append(s)
    # 凸塊半徑一致性：與同陣列中位數差太多的剔除 (圓盤被部分遮住、或不是同一種凸塊)
    arr = group_arrays(sites)
    for s, a in zip(sites, arr):
        s["array"] = int(a)
        s["used"] = a > 0
        s["reason"] = "" if a > 0 else "isolated"
    for a in set(arr.tolist()) - {0}:
        idx = np.flatnonzero(arr == a)
        resolve_fixed_pads([sites[i] for i in idx])
        rb = np.array([sites[i]["bump"]["r"] for i in idx])
        rp = np.array([sites[i]["pad"]["r"] for i in idx])
        mb, mp = np.median(rb), np.median(rp)
        for i, b_, p_ in zip(idx, rb, rp):
            if abs(b_ - mb) > P["r_dev"] * mb or abs(p_ - mp) > P["r_dev"] * mp:
                sites[i]["used"] = False
                sites[i]["reason"] = "radius outlier"
    # 整體偏移：每個陣列 + 整張
    arrays = []
    for a in sorted(set(arr.tolist()) - {0}):
        use = [s for s in sites if s["array"] == a and s["used"]]
        est = _est(use)
        arrays.append(dict(id=a, n_sites=int((arr == a).sum()), est=est, grade=grade(est),
                           bump_r=float(np.median([s["bump"]["r"] for s in use])) if use else None,
                           pad_r=float(np.median([s["pad"]["r"] for s in use])) if use else None,
                           bbox=_bbox([s for s in sites if s["array"] == a])))
    all_use = [s for s in sites if s["used"]]
    est_all = _est(all_use, mark=False)
    for s in sites:
        s.setdefault("inlier", False)
    return dict(path=path, name=os.path.basename(path), kind=img["kind"], shape=(H, W), R0=R0,
                n_cand=len(bumps), n_balls=len(balls), sites=sites, rejects=rejects, rejected=rejected, arrays=arrays,
                est=est_all, grade=grade(est_all), secs=time.time() - t0, disp=img["disp"])


def resolve_fixed_pads(group):
    """
    露出弧太短的 pad 先前用「與聯集外緣同大」的半徑解圓心；這裡改用同陣列可靠的 pad 半徑重解：
    優先用露出弧夠長的自由擬合半徑 (>= 3 顆)，否則用同陣列同心模式的 pad 半徑中位數。
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
        c = fit_center_fixed_r(p["pts"], R, (p["x"], p["y"]))
        res = np.hypot(p["pts"][:, 0] - c[0], p["pts"][:, 1] - c[1]) - R
        p.update(x=float(c[0]), y=float(c[1]), r=R, rms=float(np.sqrt((res ** 2).mean())))
        set_offset(s)


def _est(use, mark=True):
    if len(use) < 3:
        return None
    src = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in use])
    dst = np.array([[s["bump"]["x"], s["bump"]["y"]] for s in use])
    est = estimate_shift(src, dst)
    if est is not None and mark:
        for s, ok in zip(use, est["inl"]):
            s["inlier"] = bool(ok)
    return est


def _bbox(ss):
    if not ss:
        return None
    xs = [s["pad"]["x"] for s in ss]
    ys = [s["pad"]["y"] for s in ss]
    r = max(s["pad"]["r"] for s in ss)
    return (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------
ARRAY_COLORS = [(255, 128, 0), (255, 0, 255), (0, 200, 255), (0, 255, 128), (255, 255, 0), (128, 128, 255)]


def draw_overlay(res, path_out):
    vis = cv2.cvtColor(res["disp"], cv2.COLOR_GRAY2BGR)
    k = P["arrow_scale"]
    for s in res["sites"]:
        b, p = s["bump"], s["pad"]
        if not s["used"]:
            cv2.circle(vis, (int(round(b["x"])), int(round(b["y"]))), int(round(b["r"])), (140, 140, 140), 1, cv2.LINE_AA)
            continue
        cv2.circle(vis, _pt(p["x"], p["y"]), int(round(p["r"] * 4)), (0, 220, 0), 2, cv2.LINE_AA, shift=2)
        cv2.circle(vis, _pt(b["x"], b["y"]), int(round(b["r"] * 4)), (0, 0, 255), 2, cv2.LINE_AA, shift=2)
        col = (0, 255, 255) if s.get("inlier") else (0, 128, 255)
        cv2.line(vis, _pt(p["x"], p["y"]), _pt(p["x"] + k * s["dx"], p["y"] + k * s["dy"]), col, 2, cv2.LINE_AA, shift=2)
    for (x, y, r, why) in res.get("rejected", []):
        if why in ("border", "on/near ball"):
            continue
        c = (int(round(x)), int(round(y)))
        cv2.drawMarker(vis, c, (255, 0, 200), cv2.MARKER_TILTED_CROSS, int(r), 2)
        cv2.putText(vis, why.split()[0][:6], (c[0] - 20, c[1] + int(r) + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (255, 0, 200), 1, cv2.LINE_AA)
    for a in res["arrays"]:
        if a["bbox"] is None:
            continue
        col = ARRAY_COLORS[(a["id"] - 1) % len(ARRAY_COLORS)]
        x0, y0, x1, y1 = [int(round(v)) for v in a["bbox"]]
        cv2.rectangle(vis, (x0, y0), (x1, y1), col, 3)
        e = a["est"]
        txt = f"A{a['id']} n={a['n_sites']}" + (f" shift=({e['dx']:+.2f},{e['dy']:+.2f})px {a['grade']}" if e else "")
        _label(vis, txt, (x0 + 6, max(y0 + 30, 30)), col)
        if e:
            c = (e["cx"], e["cy"])
            cv2.arrowedLine(vis, _pt(*c), _pt(c[0] + 40 * e["dx"], c[1] + 40 * e["dy"]), col, 5, cv2.LINE_AA, shift=2,
                            tipLength=0.25)
    e = res["est"]
    head = f"{res['name']}  R0={res['R0']:.1f}px  sites={sum(s['used'] for s in res['sites'])}"
    if e:
        head += f"  chip shift (bump-pad) = ({e['dx']:+.2f}, {e['dy']:+.2f}) px  rot {e['rot_deg']:+.3f}deg"
    _label(vis, head, (10, vis.shape[0] - 20), (255, 255, 255), 1.0)
    _label(vis, f"red=bump green=pad yellow=offset x{k:g}  big arrow x40", (10, vis.shape[0] - 55), (255, 255, 255), 0.8)
    cv2.imwrite(path_out, vis, [cv2.IMWRITE_JPEG_QUALITY, 90])


def _pt(x, y):
    return int(round(x * 4)), int(round(y * 4))


def _label(img, txt, org, col, scale=0.9):
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, scale, col, 2, cv2.LINE_AA)


SITE_FIELDS = ["id", "array", "used", "inlier", "reason", "bump_x", "bump_y", "bump_r", "bump_rms", "bump_cov",
               "pad_x", "pad_y", "pad_r", "pad_rms", "pad_cov", "pad_mode", "pad_free_r", "lobe_span_deg",
               "dx", "dy", "d", "contrast", "model_w"]


def write_sites(res, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(SITE_FIELDS)
        for i, s in enumerate(res["sites"], 1):
            b, p = s["bump"], s["pad"]
            w.writerow([i, s["array"], int(s["used"]), int(s["inlier"]), s["reason"],
                        f"{b['x']:.3f}", f"{b['y']:.3f}", f"{b['r']:.3f}", f"{b['rms']:.3f}", f"{b['cov']:.2f}",
                        f"{p['x']:.3f}", f"{p['y']:.3f}", f"{p['r']:.3f}", f"{p['rms']:.3f}", f"{p['cov']:.2f}",
                        p["mode"], int(p["free"]), f"{p['span']:.0f}",
                        f"{s['dx']:.3f}", f"{s['dy']:.3f}", f"{s['d']:.3f}", f"{s['contrast']:.4f}", f"{s['model_w']:.2f}"])


ARRAY_FIELDS = ["array", "n_sites", "n_used", "n_inlier", "shift_dx", "shift_dy", "shift_mag", "corr_dx", "corr_dy",
                "se_px", "rms_px", "rot_deg", "scale_ppm", "center_x", "center_y", "bump_r", "pad_r", "grade"]


def _est_row(e):
    if e is None:
        return [""] * 13
    return [e["n"], e["n_in"], f"{e['dx']:.3f}", f"{e['dy']:.3f}", f"{e['mag']:.3f}", f"{-e['dx']:.3f}",
            f"{-e['dy']:.3f}", f"{e['se']:.3f}", f"{e['rms']:.3f}", f"{e['rot_deg']:.4f}", f"{e['scale_ppm']:.0f}",
            f"{e['cx']:.1f}", f"{e['cy']:.1f}"]


def write_arrays(res, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(ARRAY_FIELDS)
        for a in res["arrays"]:
            w.writerow([a["id"], a["n_sites"]] + _est_row(a["est"]) +
                       [f"{a['bump_r']:.2f}" if a["bump_r"] else "", f"{a['pad_r']:.2f}" if a["pad_r"] else "", a["grade"]])
        w.writerow(["all", len(res["sites"])] + _est_row(res["est"]) + ["", "", res["grade"]])


def run_one(args):
    path, out_dir = args
    res = process_image(path)
    stem = os.path.splitext(res["name"])[0]
    draw_overlay(res, os.path.join(out_dir, f"{stem}_overlay.jpg"))
    write_sites(res, os.path.join(out_dir, f"{stem}_sites.csv"))
    write_arrays(res, os.path.join(out_dir, f"{stem}_arrays.csv"))
    res.pop("disp")
    for s in res["sites"]:
        s["pad"].pop("pts", None)
    if res["est"] is not None:
        res["est"].pop("inl")
    for a in res["arrays"]:
        if a["est"] is not None:
            a["est"].pop("inl")
    return res


IMG_EXT = (".tif", ".tiff", ".png", ".bmp", ".jpg")


def collect(inputs):
    files = []
    for p in inputs:
        if os.path.isdir(p):
            files += sorted(f for f in glob.glob(os.path.join(p, "*")) if f.lower().endswith(IMG_EXT))
        else:
            files.append(p)
    return files


def run_quiet(args):
    """敏感度掃描用：指定等高線重跑一張，只回傳整張與各陣列的偏移"""
    path, levels = args
    P["bump_level"], P["pad_level"] = levels
    r = process_image(path)
    pick = lambda e: None if e is None else {k: e[k] for k in ("dx", "dy", "se", "n_in", "n")}
    return dict(path=path, levels=levels, est=pick(r["est"]), arrays={a["id"]: pick(a["est"]) for a in r["arrays"]})


def main():
    ap = argparse.ArgumentParser(description="X 光 micro bump / pad 偏移量測")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", default="output")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--bump-level", type=float, default=P["bump_level"])
    ap.add_argument("--pad-level", type=float, default=P["pad_level"])
    ap.add_argument("--lobe", choices=["auto", "on", "off"], default=P["lobe"],
                    help="pad 露出弧模式 (auto: 只用於 8-bit RGB 影像)")
    ap.add_argument("--sweep", action="store_true", help="另以 0.7/0.3 與 0.8/0.2 等高線重算，列出敏感度")
    ap.add_argument("--px-um", type=float, default=None, help="每像素微米 (給了就多列 µm)")
    a = ap.parse_args()
    P["bump_level"], P["pad_level"], P["lobe"] = a.bump_level, a.pad_level, a.lobe
    files = collect(a.inputs)
    jobs = []
    for f in files:
        d = os.path.join(a.out, os.path.basename(os.path.dirname(os.path.abspath(f))))
        os.makedirs(d, exist_ok=True)
        jobs.append((f, d))
    cv2.setNumThreads(1)
    sweep_levels = [(0.7, 0.3), (0.8, 0.2)] if a.sweep else []
    with ProcessPoolExecutor(max(a.workers, 1), initializer=_init_worker, initargs=(dict(P),)) as ex:
        results = list(ex.map(run_one, jobs))
        sweep = list(ex.map(run_quiet, [(f, lv) for lv in sweep_levels for f in files]))
    write_summary(results, a.out, a.px_um)
    write_report(results, sweep, a.out, a.px_um)
    print(f"\n輸出：{os.path.abspath(a.out)}")


def _init_worker(p):
    P.update(p)
    cv2.setNumThreads(1)


def _batch(r):
    return os.path.basename(os.path.dirname(os.path.abspath(r["path"])))


def _main_array(r):
    return max(r["arrays"], key=lambda a: a["n_sites"]) if r["arrays"] else None


SUMMARY_FIELDS = ["batch", "image", "kind", "R0_px", "candidates", "sites_measured", "sites_used", "lobe_sites", "arrays",
                  "shift_dx", "shift_dy", "shift_mag", "se_px", "rot_deg", "scale_ppm", "n_inlier", "grade",
                  "main_array", "main_n", "main_dx", "main_dy", "main_se", "median_site_dx", "median_site_dy", "secs"]


def write_summary(results, out, px_um=None):
    rows = []
    for r in results:
        e = r["est"]
        main = _main_array(r)
        me = main["est"] if main else None
        used = [s for s in r["sites"] if s["used"]]
        rows.append([_batch(r), r["name"], r["kind"], f"{r['R0']:.1f}", r["n_cand"], len(r["sites"]), len(used),
                     sum(s["pad"]["mode"] == "lobe" for s in used), len(r["arrays"]),
                     *([f"{e['dx']:.3f}", f"{e['dy']:.3f}", f"{e['mag']:.3f}", f"{e['se']:.3f}", f"{e['rot_deg']:.4f}",
                        f"{e['scale_ppm']:.0f}", e["n_in"]] if e else [""] * 7),
                     r["grade"],
                     *([main["id"], main["n_sites"], f"{me['dx']:.3f}", f"{me['dy']:.3f}", f"{me['se']:.3f}"] if me else [""] * 5),
                     f"{np.median([s['dx'] for s in used]):.3f}" if used else "",
                     f"{np.median([s['dy'] for s in used]):.3f}" if used else "",
                     f"{r['secs']:.1f}"])
    with open(os.path.join(out, "summary.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(SUMMARY_FIELDS)
        w.writerows(rows)
    print(f"{'image':<22}{'kind':<7}{'R0':>6}{'used':>6}{'arr':>4}  {'shift dx,dy (px)':>20}{'se':>7}{'rot_deg':>9}{'ppm':>7}  grade")
    for r in results:
        e = r["est"]
        s = (f"({e['dx']:+6.2f},{e['dy']:+6.2f})".rjust(20) + f"{e['se']:7.2f}{e['rot_deg']:9.3f}{e['scale_ppm']:7.0f}"
             if e else " " * 43)
        tag = _batch(r) + "/" + r["name"]
        print(f"{tag:<22}{r['kind']:<7}{r['R0']:6.1f}{sum(x['used'] for x in r['sites']):6d}{len(r['arrays']):4d}  {s}  {r['grade']}"
              + (f"  ({e['dx'] * px_um:+.2f},{e['dy'] * px_um:+.2f})um" if e and px_um else ""))


# ---------------------------------------------------------------------------
# 同視野重拍的重複性：兩張的位點以相似變換對位後逐點比較偏移向量
# ---------------------------------------------------------------------------
def compare_pair(r1, r2):
    s1 = [s for s in r1["sites"] if s["used"]]
    s2 = [s for s in r2["sites"] if s["used"]]
    if len(s1) < 20 or len(s2) < 20:
        return None
    q1 = np.array([[s["model_x"], s["model_y"]] for s in s1])
    q2 = np.array([[s["model_x"], s["model_y"]] for s in s2])
    D = np.hypot(q1[:, None, 0] - q2[None, :, 0], q1[:, None, 1] - q2[None, :, 1])
    j = D.argmin(1)
    ok = D.min(1) < 15
    if ok.sum() < 0.5 * min(len(s1), len(s2)):
        return None
    M = similarity_lsq(q1[ok], q2[j[ok]])
    pr = q1 @ M[:, :2].T + M[:, 2]
    D = np.hypot(pr[:, None, 0] - q2[None, :, 0], pr[:, None, 1] - q2[None, :, 1])
    j = D.argmin(1)
    ok = D.min(1) < 1.5
    if ok.sum() < 0.5 * min(len(s1), len(s2)):
        return None
    idx = np.flatnonzero(ok)
    v1 = np.array([[s1[i]["dx"], s1[i]["dy"]] for i in idx])
    v2 = np.array([[s2[j[i]]["dx"], s2[j[i]]["dy"]] for i in idx])
    if np.abs(v1 - v2).max() < 1e-9:
        return dict(n=len(idx), identical=True)
    diff = v1 - v2
    return dict(n=len(idx), identical=False, scale_ppm=float((np.hypot(M[0, 0], M[1, 0]) - 1) * 1e6),
                align_res=float(np.median(D.min(1)[ok])),
                noise=(diff.std(0) / np.sqrt(2)).tolist(), site_sd=v1.std(0).tolist(),
                corr=[float(np.corrcoef(v1[:, 0], v2[:, 0])[0, 1]), float(np.corrcoef(v1[:, 1], v2[:, 1])[0, 1])])


def _fmt(e, px_um=None):
    if e is None:
        return "-"
    t = f"({e['dx']:+.2f}, {e['dy']:+.2f}) ± {e['se']:.2f}"
    if px_um:
        t += f" px = ({e['dx'] * px_um:+.2f}, {e['dy'] * px_um:+.2f}) µm"
    return t


def write_report(results, sweep, out, px_um=None):
    L = ["# Micro bump / Pad 偏移量測報告", "",
         f"產生時間：{time.strftime('%Y-%m-%d %H:%M')}　程式：`BumpPadShift.py`　"
         f"等高線：凸塊 {P['bump_level']:.2f}／pad {P['pad_level']:.2f}", "",
         "偏移定義：shift = 凸塊圓心 − pad 圓心（px，x 向右、y 向下）；晶片需修正量 = −shift。",
         "整體偏移為相似變換（平移＋旋轉＋縮放）在陣列內點中心處的平移；± 為標準誤。", ""]
    batches = []
    for r in results:
        if _batch(r) not in batches:
            batches.append(_batch(r))
    for b in batches:
        rs = [r for r in results if _batch(r) == b]
        L += [f"## {b}（{rs[0]['kind']}，{len(rs)} 張）", "",
              "| 影像 | 凸塊半徑 R0 | 可用位點 | 露出弧位點 | 陣列數 | 整張 shift (px) | 旋轉 ° | 縮放 ppm | 等級 | 最大陣列 (n) shift |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rs:
            e = r["est"]
            used = [s for s in r["sites"] if s["used"]]
            m = _main_array(r)
            if e is None:
                L.append(f"| {r['name']} | {r['R0']:.1f} | {len(used)} | - | {len(r['arrays'])} | - | - | - | - | - |")
                continue
            L.append(f"| {r['name']} | {r['R0']:.1f} | {len(used)} | {sum(s['pad']['mode'] == 'lobe' for s in used)} | "
                     f"{len(r['arrays'])} | {_fmt(e, px_um)} | {e['rot_deg']:+.3f} | {e['scale_ppm']:+.0f} | {r['grade']} | "
                     + (f"A{m['id']} ({m['n_sites']}) {_fmt(m['est'], px_um)}" if m and m["est"] else "-") + " |")
        ests = [r["est"] for r in rs if r["est"] is not None and r["grade"] != "low"]
        if ests:
            dx = np.array([e["dx"] for e in ests])
            dy = np.array([e["dy"] for e in ests])
            L += ["", f"等級 mid 以上的 {len(ests)} 張：shift 中位數 ({np.median(dx):+.2f}, {np.median(dy):+.2f}) px，"
                      f"張與張之間標準差 ({dx.std():.2f}, {dy.std():.2f}) px。"]
        L += ["", "<details><summary>各陣列明細</summary>", "",
              "| 影像 | 陣列 | 位點 | 內點 | shift (px) | 縮放 ppm | 凸塊 r | pad r | 等級 |", "|---|---|---|---|---|---|---|---|---|"]
        for r in rs:
            for a in r["arrays"]:
                e = a["est"]
                if e is None:
                    continue
                L.append(f"| {r['name']} | A{a['id']} | {a['n_sites']} | {e['n_in']}/{e['n']} | {_fmt(e, px_um)} | "
                         f"{e['scale_ppm']:+.0f} | {a['bump_r']:.1f} | {a['pad_r']:.1f} | {a['grade']} |")
        L += ["", "</details>", ""]
        pairs = []
        for i in range(len(rs)):
            for k in range(i + 1, len(rs)):
                c = compare_pair(rs[i], rs[k])
                if c:
                    pairs.append((rs[i]["name"], rs[k]["name"], c))
        if pairs:
            L += ["### 同視野影像的重複性", ""]
            for n1, n2, c in pairs:
                if c["identical"]:
                    L.append(f"- {n1} 與 {n2}：{c['n']} 顆位點結果完全相同（同一張影像的不同存檔）。")
                else:
                    L.append(f"- {n1} vs {n2}：配對 {c['n']} 顆（兩張放大率差 {c['scale_ppm']:+.0f} ppm、對位殘差 {c['align_res']:.2f} px）；"
                             f"逐點偏移的重拍雜訊 σ = ({c['noise'][0]:.2f}, {c['noise'][1]:.2f}) px，"
                             f"點與點之間的差異 σ = ({c['site_sd'][0]:.2f}, {c['site_sd'][1]:.2f}) px，"
                             f"兩次的相關係數 ({c['corr'][0]:.2f}, {c['corr'][1]:.2f})。")
            L.append("")
        sw = [x for x in sweep if _batch(dict(path=x["path"])) == b]
        if sw:
            lvls = sorted({x["levels"] for x in sw})
            L += ["### 等高線選擇的敏感度（整張 shift, px）", "",
                  "| 影像 | " + f"{P['bump_level']:.2f}/{P['pad_level']:.2f}（採用） | " +
                  " | ".join(f"{a:.2f}/{c:.2f}" for a, c in lvls) + " |",
                  "|---|" + "---|" * (1 + len(lvls))]
            for r in rs:
                cells = [_fmt(r["est"])]
                for lv in lvls:
                    x = next((x for x in sw if x["path"] == r["path"] and x["levels"] == lv), None)
                    cells.append(_fmt(x["est"]) if x else "-")
                L.append(f"| {r['name']} | " + " | ".join(cells) + " |")
            L.append("")
        L.append("")
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
