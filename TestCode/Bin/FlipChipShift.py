"""
Flip-Chip X 光影像：凸塊 (bump) 與基板焊墊 (pad) 圓心量測與偏移量計算

用法:
    python FlipChipShift.py <影像或資料夾> [--out 輸出資料夾] [--px-um 每像素微米]
                            [--limit 偏移門檻px] [--print-all] [--print-sizes] [--no-variants]
                            [--scale 倍率] [--pad-r MIN MAX]

每張影像輸出:
    <name>_overlay.png        全解析度疊圖 (綠=焊墊圓, 紅=凸塊圓, 藍=單圓位點, 橘線=偏移向量,
                              粗色框=晶片矩形 D#, 細色框=群的凸包, 箭頭=該群平均偏移 x15)
    <name>_overlay_half.png   縮小一半的預覽
    <name>_sites.csv          每個位點一列 (圓心、半徑、dx/dy/偏移量、擬合品質、類型、所屬群)
    <name>_clusters.csv       每群一列 (所屬晶片矩形、位點數、型態、pitch、平均偏移向量、方向一致性、t 值、
                              相似變換的旋轉/平移、扣除後殘差、外形拉長一致性、整體偏移判定)
    <name>_regions.csv        每個晶片矩形一列 (灰階層、閾值、bbox、面積、填滿率、位點數、位移估計與前處理敏感度範圍)
    <name>_circles.csv        每個圓一列 (焊點 P# / 凸塊 B#)：圓心、半徑、直徑、面積 (px；給 --px-um 則多 um 欄)
整批輸出:
    summary.csv               每張影像的統計 (位點數、偏移中位/P95/最大、全域平移與旋轉、群數與判定)

分群與整體偏移判定:
    先找晶片矩形：大核中值 (壓掉凸塊與 BGA 球) 得背景灰階圖，k-means 分成幾個灰階層，
    在每個層間閾值下取「比周圍暗的區域」，方形開運算去掉球殘影與細帶、填洞，
    留下面積夠大且填滿率 (面積/外接矩形) 夠高的連通區域 = 晶片矩形 (可巢狀：暗的在亮的裡面)。
    每個位點歸到包含它的最內層 (最暗) 矩形；同一矩形內再依焊墊半徑分成子群 (例如 r~15 與 r~21 兩種圓盤)。
    不在任何矩形內的位點以 pitch 自適應連結分群 (region 0)。
    每群以 two-level 位點的 (焊墊心 -> 凸塊心) 估相似變換，
    以平均偏移向量 |m|、方向一致性 R = |mean(v)| / mean(|v|)、t = |m| sqrt(n) / s 判定：
        高: |m| >= 1.0px 且 R >= 0.5 且 t >= 4   -> 疑似整體晶片偏移
        中: |m| >= 0.5px 且 t >= 3
        低: 其他                                 -> 看不出整體偏移
    single 群 (影像分不出兩層) 原則上無法由偏移量判定，只列出低可信度均值與外形拉長一致性作參考；
    但若群內低可信度偏移量仍滿足「高」的條件，標為「高(低可信)」提示人工確認。

位點類型:
    two-level : 凸塊邊緣與焊墊邊緣分得開 (半徑差 >= min_sep)，偏移量可信
    single    : 兩條邊緣幾乎重合 (單一斜坡)，8-bit 影像分不出凸塊與焊墊；
                仍列出兩圓心與偏移量，但只代表「量不到明顯偏移」，可信度低
"""
import argparse
import csv
from functools import lru_cache
import glob
import os
import sys

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# 參數 (依目前影像尺度：焊墊半徑約 15~26 px、凸塊半徑約 10~20 px；其他倍率用 --scale)
# ---------------------------------------------------------------------------
P = dict(
    median_ksize=5,          # 去噪：中值濾波核
    gauss_sigma=2.5,         # 量測用去噪：高斯 sigma (射線剖面用，太小則環帶紋理造成跨越點亂跳)
    detect_sigma=2.5,        # 偵測用去噪：高斯 sigma (較大，抑制雜訊斑塊)
    cs_r_in=15.0,            # 偵測：中心圓半徑 (略小於凸塊/焊墊)
    cs_r_ring=(23.0, 28.0),  # 偵測：周圍環帶半徑範圍 (焊墊外的縫隙/背景)
    cs_nms=25,               # 偵測：非極大值抑制視窗 (小於最小 pitch)
    cs_min_resp=22.0,        # 偵測：中心 vs 周圍 最小暗度差 (灰階)
    ball_thresh=100,         # 大焊球：灰階低於此值
    ball_dilate=15,          # 大焊球遮罩外擴 (開運算大小由 pad_r 上限推得，見 apply_scale)
    dedupe_dist=10.0,        # 兩個量測結果中心距離小於此值視為同一顆
    n_rays=72,               # 放射線數
    r_max=48.0,              # 放射線最遠取樣半徑
    r_step=0.5,              # 放射線取樣間距
    pad_r=(13.0, 32.0),      # 焊墊半徑合理範圍 (密集區還有一群較小較淡的 r~15 圓盤)
    bump_r_min=5.0,          # 凸塊邊緣最小半徑
    min_depth=30.0,          # 圓盤有效性：核心/圓內 vs 背景 最小對比 (去掉背景雜訊斑塊)
    min_slope=3.0,           # 外緣梯度峰值下限 (灰階/px)
    peak_rel=0.5,            # 外緣候選：梯度峰值須達最大峰值的比例
    hi_frac=0.75,            # 外緣 (焊墊) 等高線 = core + hi_frac*(bg-core)
    lo_frac=0.25,            # 內緣 (凸塊) 等高線 = core + lo_frac*(bg-core)
    min_coverage=0.6,        # 逐射線找到邊緣的比例下限 (擬合前)
    min_coverage_ok=0.6,     # 擬合後接受的覆蓋率下限 (密集區相鄰焊墊會遮掉部分方向)
    max_rms=1.3,             # 圓擬合殘差 RMS 上限 (px)
    bump_ratio=(0.4, 0.97),  # 凸塊半徑 / 焊墊半徑 合理範圍
    min_sep=4.0,             # 鄰域「焊墊半徑 - 凸塊半徑」中位 >= 此值才算分得出兩層 (px)；單一模糊邊緣約 2.5~3.5px
    vote_radius=200.0,       # 鄰域投票半徑 (px)，要蓋到最疏陣列的 1~2 個 pitch
    vote_min=4,              # 鄰域內至少幾個有效位點才投票，否則用自己的值
    depth_ratio=0.4,         # 位點深度低於鄰域中位深度的此比例 → 視為基板紋理剔除
    max_r_dev=3.0,           # 凸塊圓擬合半徑與平均剖面預期半徑的容許差 (px)，超過視為擬到內部紋理
    die_median=201,          # 晶片矩形：大核中值 (要 > BGA 球面積的 2 倍，球直徑 ~130px)
    die_sigma=6.0,           # 晶片矩形：背景圖再平滑
    die_levels=4,            # 晶片矩形：k-means 灰階層數
    die_open=151,            # 晶片矩形：方形開運算 (去掉比這小的暗塊：球殘影 ~100px、細帶)
    die_close=61,            # 晶片矩形：閉運算補小缺口
    die_min_area=0.015,      # 晶片矩形：最小面積 (影像比例)
    die_min_fill=0.75,       # 晶片矩形：最小填滿率 (面積 / 外接矩形)
    sub_r_gap=3.0,           # 矩形內子群：焊墊半徑排序後間隙 > 此值就切開
    link_factor=1.5,         # 矩形外散點分群：兩點距離 <= link_factor x 兩者 pitch 較小值 才連結
    link_pitch_ratio=1.4,    # 分群：兩點各自的 pitch 比值 <= 此值 才連結 (同一陣列 pitch 相同)
    link_r_tol=0.35,         # 分群：焊墊半徑差 <= link_r_tol x 較大半徑 才連結
    link_depth_ratio=0.5,    # 分群：兩點深度 較小/較大 >= 此值 才連結
    min_cluster=4,           # 少於此數的群不獨立成群
    shift_high=(1.0, 0.5, 4.0),   # 整體偏移「高」: |m| px, 方向一致性 R, t 值
    shift_mid=(0.5, 3.0),         # 整體偏移「中」: |m| px, t 值
    arrow_scale=15.0,        # 疊圖上平均偏移箭頭的放大倍率
    # 位點品質篩選 (估整體位移用)：同一片晶片的凸塊大小應一致、凸塊應落在焊點內、擬合要可靠
    q_min_group=8,           # 一個矩形內至少幾顆才用該矩形自己的中位數，否則用全圖
    q_r_tol=0.12,            # 凸塊半徑與中位數差 <= max(q_r_abs, q_r_tol x 中位數) 才用 (面積差約 ±25%)
    q_p_tol=0.15,            # 焊點半徑容差
    q_r_abs=2.0,             # 半徑容差下限 px
    q_depth_ratio=0.5,       # 深度 >= 中位數 x 此值 (太淡的圓盤多半不是凸塊)
    q_overlap=0.9,           # 凸塊心與焊點心距離 <= q_overlap x (r_b + r_p) 才算凸塊落在焊點上 (兩圓有重疊)
    lobe_level=0.6,          # 聯集 (暗圓 ∪ 淡瓣) 等高線 = core + lobe_level x (bg - core)
    lobe_margin=5.5,         # 聯集輪廓點離凸塊圓外緣 > 此值 才算焊點露出的弧 (px)；單一模糊邊緣 25%→75% 約 3.5px
    lobe_min_pts=8,          # 露出弧至少幾個輪廓點
    lobe_min_span=60.0,      # 露出弧至少跨幾度
    lobe_free_span=150.0,    # 弧跨度 >= 此值才做自由 (含半徑) 圓擬合，否則固定半徑只解圓心
    lobe_r_ratio=(0.6, 1.6), # 自由擬合的焊點半徑 / 凸塊半徑 合理範圍
    lobe_search=2.0,         # 聯集輪廓搜尋半徑 = lobe_search x 凸塊半徑 (太大會掃到鄰居)
    lobe_r_default=1.3,      # 陣列裡沒有足夠自由擬合時，焊點半徑 = lobe_r_default x 凸塊中位半徑
    lobe_min_depth=0.25,     # 瓣區 (焊點圓內、凸塊圓外) 平均灰階至少比背景暗 (bg-core) x 此比例，否則不算露出弧
    lobe_max_rms=2.5,        # 固定半徑擬合的殘差 RMS 上限 (px)，超過視為輪廓不是圓弧
    dark_is_bump=True,       # 暗圓 = 金屬凸塊 (較厚，衰減多)；淡瓣 = 基板焊點露出的部分。設 False 則對調
    q_rms=1.0,               # 凸塊圓擬合殘差上限
    q_cov=0.7,               # 凸塊圓邊緣覆蓋率下限
    q_border=8.0,            # 焊點圓 + 此邊距 超出影像 → 剖面被截斷不用
    # 整體位移估計 (穩健)：以中位數起始、反覆取容差內的內點求平均
    shift_tol=1.5,           # 內點容差下限 px (實際 = max(shift_tol, 2.5 x MAD))
    min_shift_sites=5,       # 一個矩形至少幾顆可用位點才報位移
)


# 隨特徵尺寸縮放的參數 (px)。影像放大倍率不同時用 --scale 一次調整。
SIZE_KEYS = ["cs_r_in", "cs_r_ring", "cs_nms", "r_max", "pad_r", "bump_r_min", "vote_radius", "dedupe_dist"]


def apply_scale(k=1.0, pad_r=None):
    """依倍率 k 縮放所有尺寸參數；pad_r 給了就直接覆寫焊墊半徑範圍。同時推得大焊球遮罩的開運算大小。"""
    for key in SIZE_KEYS:
        v = P[key]
        P[key] = tuple(x * k for x in v) if isinstance(v, tuple) else v * k
    if pad_r is not None:
        P["pad_r"] = (float(pad_r[0]), float(pad_r[1]))
    P["cs_nms"] = int(round(P["cs_nms"])) | 1
    P["ball_open"] = int(2 * P["pad_r"][1]) + 5      # 直徑大於焊墊上限的深色大塊才視為大焊球


apply_scale(1.0)


# ---------------------------------------------------------------------------
# 影像讀取與前處理
# ---------------------------------------------------------------------------
def load_gray(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise IOError(f"無法讀取影像: {path}")
    if img.ndim == 3:
        img = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
    if img.dtype != np.uint8:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return img


def denoise(gray, sigma=None):
    den = cv2.medianBlur(gray, P["median_ksize"])
    den = cv2.GaussianBlur(den, (0, 0), sigma or P["gauss_sigma"])
    return den.astype(np.float32)


# 前處理敏感度：同一批候選位點改用不同去噪影像重新量測，位移估計的變化量當作系統不確定度
PREPROC_VARIANTS = [
    ("gauss1.5", "gauss", 1.5),          # 較弱的高斯
    ("bilateral", "bilateral", None),    # 邊緣保持
    ("nlm", "nlm", 45),                  # Non-Local Means (最會抹掉弱結構)
]


def preprocess(gray, kind, param=None):
    """量測用去噪影像的替代版本 (float32)"""
    if kind == "gauss":
        return denoise(gray, param)
    if kind == "bilateral":
        return cv2.bilateralFilter(cv2.medianBlur(gray, P["median_ksize"]), 9, 60, 4).astype(np.float32)
    if kind == "nlm":
        nlm = cv2.fastNlMeansDenoising(gray, None, h=float(param or 45), templateWindowSize=7, searchWindowSize=21)
        return cv2.GaussianBlur(nlm, (0, 0), 1.0).astype(np.float32)
    raise ValueError(kind)


# ---------------------------------------------------------------------------
# 候選位點偵測
# ---------------------------------------------------------------------------
def big_ball_mask(den):
    """大焊球 (直徑大於焊墊上限的深色大圓，如 BGA 球) 遮罩，用來排除落在其中的候選點"""
    dark = (den < P["ball_thresh"]).astype(np.uint8)
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (P["ball_open"], P["ball_open"]))
    balls = cv2.morphologyEx(dark, cv2.MORPH_OPEN, se)
    se2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (P["ball_dilate"], P["ball_dilate"]))
    return cv2.dilate(balls, se2)


@lru_cache(maxsize=16)
def _disc_kernel(r_in, r_out=None):
    """r_out=None: 半徑 r_in 的實心圓平均核；否則為 [r_in, r_out) 的環形平均核"""
    R = int(np.ceil(r_out if r_out else r_in))
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    rr = np.hypot(xx, yy)
    m = (rr < r_in) if r_out is None else ((rr >= r_in) & (rr < r_out))
    k = m.astype(np.float32)
    return k / k.sum()


def detect_candidates(den):
    """
    中心-周圍 (center-surround) 匹配濾波：圓盤內平均 vs 外圍環帶平均 的暗度差，
    再取局部極大值 (非極大值抑制)。相鄰焊墊各自成為一個極大值，不會像閾值+連通元件那樣黏在一起；
    也不受銅平面 / 走線造成的背景亮度差影響 (只看局部差)。
    回傳候選中心列表 [(cx, cy, response)]
    """
    inner = cv2.filter2D(den, -1, _disc_kernel(P["cs_r_in"]), borderType=cv2.BORDER_REFLECT)
    ring = cv2.filter2D(den, -1, _disc_kernel(P["cs_r_ring"][0], P["cs_r_ring"][1]), borderType=cv2.BORDER_REFLECT)
    resp = ring - inner                                    # 圓盤比周圍暗多少
    k = P["cs_nms"]
    local_max = cv2.dilate(resp, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    mask = (resp >= local_max - 1e-3) & (resp > P["cs_min_resp"])
    mask &= big_ball_mask(den) == 0
    ys, xs = np.where(mask)
    cands = []
    for x, y in zip(xs, ys):
        # 以極大值附近的暗度加權質心微調起點
        x0, x1, y0, y1 = max(x - 6, 0), min(x + 7, den.shape[1]), max(y - 6, 0), min(y + 7, den.shape[0])
        w = np.clip(resp[y0:y1, x0:x1], 0, None)
        if w.sum() <= 0:
            cx, cy = float(x), float(y)
        else:
            yy, xx = np.mgrid[y0:y1, x0:x1]
            cx, cy = float((xx * w).sum() / w.sum()), float((yy * w).sum() / w.sum())
        cands.append((cx, cy, float(resp[y, x])))
    return cands, resp


# ---------------------------------------------------------------------------
# 幾何工具
# ---------------------------------------------------------------------------
def fit_circle(pts, iters=3):
    """Kasa 代數最小平方圓擬合 + 離群點剔除。回傳 (cx, cy, R, rms, n_used) 或 None"""
    pts = np.asarray(pts, np.float64)
    if len(pts) < 6:
        return None
    keep = np.ones(len(pts), bool)
    cx = cy = R = 0.0
    res = np.zeros(len(pts))
    for _ in range(iters):
        p = pts[keep]
        if len(p) < 6:
            return None
        A = np.c_[2 * p[:, 0], 2 * p[:, 1], np.ones(len(p))]
        b = (p ** 2).sum(1)
        sol = np.linalg.lstsq(A, b, rcond=None)[0]
        cx, cy = sol[0], sol[1]
        R = float(np.sqrt(max(sol[2] + cx ** 2 + cy ** 2, 1e-9)))
        res = np.abs(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - R)
        s = res[keep].std() + 1e-6
        new_keep = res < max(2.0 * s, 0.6)
        if new_keep.sum() < 3:
            break                      # 剔除後剩太少：維持上一輪的內點
        keep = new_keep
    if keep.sum() < 3:
        return None
    rms = float(np.sqrt((res[keep] ** 2).mean()))
    return float(cx), float(cy), R, rms, int(keep.sum())


def fit_center_fixed_r(pts, R, c0=None, iters=25):
    """已知半徑 R，只解圓心：Gauss-Newton 迭代 c <- mean(p_i - R * unit(p_i - c))。回傳 (cx, cy, rms)"""
    pts = np.asarray(pts, np.float64)
    c = np.asarray(c0, np.float64) if c0 is not None else pts.mean(0)
    for _ in range(iters):
        v = pts - c
        n = np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
        c_new = (pts - R * v / n).mean(0)
        if np.linalg.norm(c_new - c) < 1e-4:
            c = c_new
            break
        c = c_new
    res = np.linalg.norm(pts - c, axis=1) - R
    return float(c[0]), float(c[1]), float(np.sqrt((res ** 2).mean()))


def angular_span(angles):
    """一組角度 (rad) 的涵蓋跨度 (deg)：排序後最大空隙的補角"""
    if len(angles) < 2:
        return 0.0
    a = np.sort(np.mod(angles, 2 * np.pi))
    gaps = np.diff(np.concatenate([a, [a[0] + 2 * np.pi]]))
    return float(np.degrees(2 * np.pi - gaps.max()))


class RaySampler:
    """以某個中心為原點，沿 n 條放射線做雙線性取樣，回傳 (n_rays, n_r) 的灰階矩陣"""

    def __init__(self, den):
        self.den = den
        self.H, self.W = den.shape
        self.th = np.deg2rad(np.arange(0, 360, 360.0 / P["n_rays"])).astype(np.float32)
        self.r = np.arange(0, P["r_max"], P["r_step"], dtype=np.float32)
        self.cos = np.cos(self.th)[:, None]
        self.sin = np.sin(self.th)[:, None]
        self.xoffs = self.r[None, :] * self.cos
        self.yoffs = self.r[None, :] * self.sin

    def sample(self, cx, cy):
        xs = self.xoffs + np.float32(cx)
        ys = self.yoffs + np.float32(cy)
        return cv2.remap(self.den, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def crossings(self, V, level, r_lo, r_hi, near=None, outermost=False):
        """
        每條射線在 [r_lo, r_hi] 內找由暗跨到亮 (>= level) 的位置，線性內插子像素。
        near=None 取由內往外第一次跨越；給 near 時取最接近該半徑的跨越
        (同時抗圓盤內部紋理造成的提早跨越，與外圍環帶的凹陷造成的延後跨越)。
        回傳 (radius array, 有效遮罩)
        """
        k_lo = int(max(r_lo / P["r_step"], 0))
        k_hi = int(min(r_hi / P["r_step"], len(self.r) - 1))
        out = np.full(len(self.th), np.nan, np.float64)
        if k_hi <= k_lo:
            return out, ~np.isnan(out)
        seg = V[:, k_lo:k_hi + 1]
        hit = (seg[:, :-1] < level) & (seg[:, 1:] >= level)
        rows = np.flatnonzero(hit.any(axis=1))
        if len(rows) == 0:
            return out, ~np.isnan(out)
        if outermost:
            idx = hit.shape[1] - 1 - np.argmax(hit[rows, ::-1], axis=1)
        elif near is None:
            idx = np.argmax(hit[rows], axis=1)
        else:
            rk = self.r[k_lo:k_hi]
            dist = np.where(hit[rows], np.abs(rk[None, :] - float(near)), np.inf)
            idx = np.argmin(dist, axis=1)
        kk = idx + k_lo
        a = V[rows, kk]
        b = V[rows, kk + 1]
        denom = b - a
        t = np.divide(level - a, denom, out=np.zeros_like(a, dtype=np.float32), where=np.abs(denom) > 1e-9)
        out[rows] = self.r[kk] + t * P["r_step"]
        return out, ~np.isnan(out)

    def to_points(self, cx, cy, rho, ok):
        return np.c_[cx + rho[ok] * np.cos(self.th[ok]), cy + rho[ok] * np.sin(self.th[ok])]


# ---------------------------------------------------------------------------
# 單一位點量測
# ---------------------------------------------------------------------------
def gradient_peaks(prof, r, r_lo, r_hi):
    """平均徑向剖面在 [r_lo, r_hi] 內的梯度局部極大值 (由暗到亮的斜坡)，回傳 [(r, level, slope)] 依斜率遞減"""
    d = np.gradient(prof, r)
    d = np.convolve(d, np.ones(3) / 3, mode="same")
    peaks = []
    for k in range(2, len(d) - 2):
        if not (r_lo <= r[k] <= r_hi):
            continue
        if d[k] >= d[k - 1] and d[k] >= d[k + 1] and d[k] > d[k - 2] and d[k] > d[k + 2] and d[k] > 0:
            peaks.append((float(r[k]), float(prof[k]), float(d[k])))
    return sorted(peaks, key=lambda pk: -pk[2])


def fit_edge(sampler, cx, cy, level, r_lo, r_hi, near=None):
    V = sampler.sample(cx, cy)
    rho, ok = sampler.crossings(V, level, r_lo, r_hi, near=near)
    if ok.mean() < P["min_coverage"]:
        return None
    pts = sampler.to_points(cx, cy, rho, ok)
    fit = fit_circle(pts)
    if fit is None:
        return None
    # 外形的 2 次諧波：res(θ) ≈ |e2| cos(2(θ - axis))，|e2| 為拉長量 (半徑差的一半)，axis 為長軸方向
    th = np.arctan2(pts[:, 1] - fit[1], pts[:, 0] - fit[0])
    res = np.hypot(pts[:, 0] - fit[0], pts[:, 1] - fit[1]) - fit[2]
    e2 = complex((res * np.exp(-2j * th)).sum() * 2 / len(res))
    return dict(x=fit[0], y=fit[1], r=fit[2], rms=fit[3], cov=float(ok.mean()), e2=e2)


REJECT = {}


def _rej(reason):
    """量測失敗時記錄原因 (供除錯統計)，回傳 None"""
    REJECT[reason] = REJECT.get(reason, 0) + 1
    return None


def measure_site(sampler, cx0, cy0):
    """
    量一個位點，回傳 dict 或 None。

    X 光穿透影像裡，凸塊 (厚、密度高) 是深色核心，焊墊 (薄) 是外圍較淡的一圈。
    兩者的邊緣在剖面上形成「核心 → 背景」的斜坡：斜坡下緣由凸塊邊緣決定、上緣由焊墊邊緣決定。
    因此：
      1. 以候選核心為中心取平均徑向剖面，找最外側的顯著梯度峰當外緣粗半徑 R0，
         估核心灰階 core 與背景灰階 bg。
      2. 外緣等高線 L_out = core + hi_frac·(bg-core)，逐射線找跨越點 (子像素) → 擬合圓 = 焊墊。
      3. 內緣等高線 L_in  = core + lo_frac·(bg-core)，逐射線取最接近預期半徑的跨越 → 擬合圓 = 凸塊。
      4. 兩圓半徑差 (sep) 交給 classify_sites() 做鄰域投票：同一陣列的 sep 中位 >= min_sep
         才代表影像分得出兩層 (two-level)；否則為 single (單一邊緣，偏移量仍照算但可信度低)。
    """
    r = sampler.r
    rmax = P["r_max"] - 1

    # ---- 1. 粗半徑與灰階平台 ----
    prof = sampler.sample(cx0, cy0).mean(0)
    pks = gradient_peaks(prof, r, 6.0, rmax - 4)
    if not pks:
        return _rej("no gradient peak")
    smax = pks[0][2]
    cand = [pk for pk in pks if pk[2] >= P["peak_rel"] * smax and pk[2] >= P["min_slope"]]
    if not cand:
        return _rej("no significant peak")
    R0 = max(pk[0] for pk in cand)
    if not (P["pad_r"][0] * 0.7 <= R0 <= P["pad_r"][1] * 1.3):
        return _rej("R0 out of range")
    core_lv = float(prof[r < 5].mean())
    outer = prof[(r > R0 + 2) & (r < min(R0 + 12, rmax))]
    if len(outer) == 0:
        return _rej("no outer samples")
    bg_lv = float(outer.max())
    if bg_lv - core_lv < P["min_depth"]:
        return _rej("depth too low")
    lv_out = core_lv + P["hi_frac"] * (bg_lv - core_lv)
    lv_in = core_lv + P["lo_frac"] * (bg_lv - core_lv)

    # ---- 2. 外緣 (焊墊) ----
    cx, cy = cx0, cy0
    pad = None
    r_exp = R0
    for it in range(2):
        f = fit_edge(sampler, cx, cy, lv_out, 0.6 * R0, min(1.5 * R0, rmax), near=r_exp)
        if f is None:
            return _rej("outer edge fit failed")
        pad = f
        cx, cy, r_exp = f["x"], f["y"], f["r"]
    R = pad["r"]
    if not (P["pad_r"][0] <= R <= P["pad_r"][1]):
        return _rej("pad radius out of range")
    if pad["rms"] > P["max_rms"] or pad["cov"] < P["min_coverage_ok"]:
        return _rej("pad fit poor")

    # 圓盤有效性：以焊墊心重取剖面，圓內平均 vs 外圍背景 要有足夠對比 (去掉背景雜訊斑塊)
    prof2 = sampler.sample(cx, cy).mean(0)
    disc_lv = float(prof2[r < 0.7 * R].mean())
    bg2 = prof2[(r > R + 2) & (r < min(R + 12, rmax))]
    if len(bg2) == 0 or float(bg2.max()) - disc_lv < P["min_depth"]:
        return _rej("disc depth too low")
    pad["core_lv"], pad["disc_lv"], pad["bg_lv"] = core_lv, disc_lv, bg_lv
    site = dict(kind="single", pad=pad, bump=None, note="", lv_in=lv_in, lv_out=lv_out)

    # ---- 3. 內緣 (暗圓)：每條射線取最接近「平均剖面跨越 lv_in 的半徑」的跨越點 ----
    k = np.where((prof2[:-1] < lv_in) & (prof2[1:] >= lv_in))[0]
    r_exp0 = float(r[k[0]]) if len(k) else 0.8 * R
    r_exp = r_exp0
    bump = None
    bx, by = cx0, cy0
    for it in range(2):
        f = fit_edge(sampler, bx, by, lv_in, P["bump_r_min"], R + 1, near=r_exp)
        if f is None:
            break
        bump = f
        bx, by, r_exp = f["x"], f["y"], f["r"]
    if bump is None:
        site["note"] = "inner edge not found"
        return site
    if bump["rms"] > P["max_rms"] or bump["cov"] < P["min_coverage_ok"]:
        site["note"] = f"inner fit poor (rms {bump['rms']:.2f}, cov {bump['cov']:.2f})"
        return site
    if abs(bump["r"] - r_exp0) > P["max_r_dev"]:
        site["note"] = f"inner fit inconsistent with profile ({bump['r']:.1f} vs {r_exp0:.1f})"
        site["sep_valid"] = False
    else:
        site["sep_valid"] = True
    rb = bump["r"]

    # ---- 4. 聯集輪廓 (暗圓 ∪ 淡瓣)：從暗圓心出發，每條射線取 lv_out 最外側的跨越 ----
    Vb = sampler.sample(bump["x"], bump["y"])
    lv_lobe = core_lv + P["lobe_level"] * (bg_lv - core_lv)
    rho, ok = sampler.crossings(Vb, lv_lobe, 0.6 * rb, min(P["lobe_search"] * rb, rmax), outermost=True)
    upts = sampler.to_points(bump["x"], bump["y"], rho, ok)
    uang = sampler.th[ok]
    # 露出弧：離暗圓外緣夠遠的輪廓點 = 另一個圓 (淡瓣) 的邊
    far = rho[ok] > rb + P["lobe_margin"]
    lobe_pts, lobe_ang = upts[far], uang[far]
    span = angular_span(lobe_ang) if far.sum() else 0.0
    site["lobe_pts"] = int(far.sum())
    site["lobe_span"] = float(span)
    other = None                       # 淡瓣圓 (x, y, r, rms, cov, free)
    ufit = fit_circle(upts) if len(upts) >= 6 else None
    site["union_fit"] = (dict(x=ufit[0], y=ufit[1], r=ufit[2], rms=ufit[3], cov=float(ok.mean())) if ufit else None)
    if far.sum() >= P["lobe_min_pts"] and span >= P["lobe_min_span"]:
        free = None
        if span >= P["lobe_free_span"]:
            fit = fit_circle(lobe_pts)
            if fit and P["lobe_r_ratio"][0] * rb <= fit[2] <= P["lobe_r_ratio"][1] * rb and fit[3] <= P["max_rms"] * 1.5:
                free = dict(x=fit[0], y=fit[1], r=fit[2], rms=fit[3])
        # 先以「同大小」假設固定半徑解圓心；之後 finalize_pads() 會用陣列中位半徑再解一次
        cx_, cy_, rms_ = fit_center_fixed_r(lobe_pts, free["r"] if free else rb, c0=(free["x"], free["y"]) if free else None)
        other = dict(x=cx_, y=cy_, r=(free["r"] if free else rb), rms=rms_, cov=float(far.sum() / len(sampler.th)),
                     free=free, pts=lobe_pts)
        site["mode"] = "lobe"
    else:
        # 沒有露出弧：聯集圓 (舊的同心兩層情況，或分不出來的單一圓)
        uf = site["union_fit"]
        if uf and uf["r"] >= rb + P["min_sep"] and uf["rms"] <= P["max_rms"]:
            other = dict(uf, free=None, pts=None)
            site["mode"] = "concentric"
        else:
            site["mode"] = "single"

    # ---- 5. 指派：暗圓 = 凸塊 (dark_is_bump) 或焊點 ----
    if other is None:
        # 只有一個圓可用：沿用聯集圓當焊點、暗圓當凸塊 (舊行為，偏移量低可信)
        site["bump"] = bump
        site["dx"], site["dy"] = bump["x"] - pad["x"], bump["y"] - pad["y"]
        site["d"] = float(np.hypot(site["dx"], site["dy"]))
        site["sep"] = pad["r"] - rb
        if not site["note"]:
            site["note"] = "edges not separable (single ramp)"
        return site
    keep = dict(core_lv=pad["core_lv"], disc_lv=pad["disc_lv"], bg_lv=pad["bg_lv"])
    dark = dict(bump, **{})
    light = dict(x=other["x"], y=other["y"], r=other["r"], rms=other["rms"], cov=other["cov"])
    if P["dark_is_bump"]:
        newpad, newbump = light, dark
    else:
        newpad, newbump = dark, light
    newpad.update(keep)
    site["pad"], site["bump"] = newpad, newbump
    site["pad_free_r"] = other["free"]["r"] if other.get("free") else None
    site["lobe_pts_xy"] = other.get("pts")
    site["dx"], site["dy"] = newbump["x"] - newpad["x"], newbump["y"] - newpad["y"]
    site["d"] = float(np.hypot(site["dx"], site["dy"]))
    site["sep"] = newpad["r"] - newbump["r"]
    if site["mode"] == "concentric":
        site["note"] = ""
    return site


def _lobe_depth(den, pad, bump):
    """焊點圓內、凸塊圓外 (瓣區) 的平均灰階；沒有這種像素回傳 None"""
    H, W = den.shape
    R = int(np.ceil(pad["r"])) + 1
    x0, x1 = max(int(pad["x"]) - R, 0), min(int(pad["x"]) + R + 1, W)
    y0, y1 = max(int(pad["y"]) - R, 0), min(int(pad["y"]) + R + 1, H)
    if x1 <= x0 or y1 <= y0:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    m = (np.hypot(xx - pad["x"], yy - pad["y"]) <= pad["r"]) & (np.hypot(xx - bump["x"], yy - bump["y"]) > bump["r"] + 1)
    if m.sum() < 20:
        return None
    return float(den[y0:y1, x0:x1][m].mean())


def _demote(s):
    """假瓣：退回聯集圓 (同心兩層) 或單圓"""
    light_key = "pad" if P["dark_is_bump"] else "bump"
    dark_key = "bump" if P["dark_is_bump"] else "pad"
    uf = s.get("union_fit")
    dark = s[dark_key]
    keep = {k: s["pad"][k] for k in ("core_lv", "disc_lv", "bg_lv") if k in s["pad"]}
    if uf and uf["r"] >= dark["r"] + P["min_sep"] and uf["rms"] <= P["max_rms"]:
        light = dict(x=uf["x"], y=uf["y"], r=uf["r"], rms=uf["rms"], cov=uf["cov"])
        s["mode"] = "concentric"
    else:
        light = dict(x=dark["x"], y=dark["y"], r=(uf["r"] if uf else dark["r"] + 1), rms=(uf["rms"] if uf else 9.9), cov=(uf["cov"] if uf else 0))
        s["mode"] = "single"
        s["note"] = "edges not separable (single ramp)"
    s[light_key] = light
    s["pad"].update(keep)
    s["dx"], s["dy"] = s["bump"]["x"] - s["pad"]["x"], s["bump"]["y"] - s["pad"]["y"]
    s["d"] = float(np.hypot(s["dx"], s["dy"]))
    s["sep"] = s["pad"]["r"] - s["bump"]["r"]


def finalize_pads(sites, den=None):
    """
    雙瓣位點：先用「陣列中位焊點半徑」(有自由擬合的位點取中位；沒有就用凸塊中位半徑) 固定半徑重解圓心，
    讓同一陣列的焊點圓大小一致，短弧位點也能得到穩定的圓心。依 region 分組。
    之後檢查瓣區是否真的比背景暗、輪廓是否真的是圓弧，不合格的退回聯集圓或單圓 (避免紋理造成的假瓣)。
    """
    groups = {}
    for s in sites:
        if s.get("mode") == "lobe" and s.get("lobe_pts_xy") is not None:
            groups.setdefault(s.get("region", 0), []).append(s)
    for reg, group in groups.items():
        free_r = [s["pad_free_r"] for s in group if s.get("pad_free_r")]
        if len(free_r) >= 3:
            r_ref = float(np.median(free_r))
        else:
            r_ref = P["lobe_r_default"] * float(np.median([s["bump"]["r"] for s in group]))
        light_key = "pad" if P["dark_is_bump"] else "bump"
        dark_key = "bump" if P["dark_is_bump"] else "pad"
        for s in group:
            c = s[light_key]
            cx_, cy_, rms_ = fit_center_fixed_r(s["lobe_pts_xy"], r_ref, c0=(c["x"], c["y"]))
            c["x"], c["y"], c["r"], c["rms"] = cx_, cy_, r_ref, rms_
            s["dx"], s["dy"] = s["bump"]["x"] - s["pad"]["x"], s["bump"]["y"] - s["pad"]["y"]
            s["d"] = float(np.hypot(s["dx"], s["dy"]))
            s["sep"] = s["pad"]["r"] - s["bump"]["r"]
            s["pad_r_ref"] = r_ref
            # 假瓣檢查：弧要像圓、瓣區要真的暗
            bad = rms_ > P["lobe_max_rms"]
            if not bad and den is not None:
                lv = _lobe_depth(den, s["pad"], s["bump"])
                bg, core = s["pad"]["bg_lv"], s["pad"]["core_lv"]
                s["lobe_depth"] = None if lv is None else float((bg - lv) / max(bg - core, 1e-6))
                bad = lv is None or (bg - lv) < P["lobe_min_depth"] * (bg - core)
            if bad:
                s["lobe_rejected"] = True
                _demote(s)
        for s in group:
            s.pop("lobe_pts_xy", None)


def drop_inconsistent(sites):
    """
    鄰域一致性：同一陣列的位點深度 (背景 - 圓內) 應相近；
    比鄰近位點中位深度淡很多的 (< depth_ratio 倍) 多半是焊墊之間的基板紋理，剔除。
    """
    if len(sites) < P["vote_min"] + 1:
        return sites
    pts = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in sites])
    depth = np.array([s["pad"]["bg_lv"] - s["pad"]["disc_lv"] for s in sites])
    keep = []
    for i, s in enumerate(sites):
        dist = np.hypot(pts[:, 0] - pts[i, 0], pts[:, 1] - pts[i, 1])
        nb = depth[(dist <= P["vote_radius"]) & (dist > 0)]
        if len(nb) >= P["vote_min"] and depth[i] < P["depth_ratio"] * float(np.median(nb)):
            continue
        keep.append(s)
    return keep


def classify_sites(sites):
    """
    鄰域投票：同一個陣列裡的位點結構相同，用鄰近位點 (半徑 vote_radius 內) 的
    「焊墊半徑 - 凸塊半徑」中位數判斷這個陣列在影像上分不分得出兩層。
    單一模糊邊緣的 25%~75% 寬約 2.5~3.5 px；真的有焊墊環時 >= 5 px。
    """
    pts = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in sites]) if sites else np.zeros((0, 2))
    seps = np.array([s.get("sep", np.nan) if (s.get("sep_valid") and s.get("mode") != "lobe") else np.nan for s in sites])
    for i, s in enumerate(sites):
        if s["bump"] is None:
            s["kind"] = "single"
            continue
        if s.get("mode") == "lobe":
            # 雙瓣：焊點露出的弧直接量到另一個圓，兩圓分得開，不需要鄰域投票
            s["kind"] = "two-level"
            s["note"] = f"lobe arc {s.get('lobe_span', 0):.0f}deg, {s.get('lobe_pts', 0)} pts"
            continue
        dist = np.hypot(pts[:, 0] - pts[i, 0], pts[:, 1] - pts[i, 1])
        nb = seps[(dist <= P["vote_radius"]) & ~np.isnan(seps)]
        med = float(np.median(nb)) if len(nb) >= P["vote_min"] else (s["sep"] if s.get("sep_valid") else np.nan)
        s["sep_local"] = med
        if not np.isnan(med) and med >= P["min_sep"] and s.get("sep_valid"):
            s["kind"] = "two-level"
        else:
            s["kind"] = "single"
            if not s["note"]:
                s["note"] = "edges not separable in this array (single ramp)"


# ---------------------------------------------------------------------------
# 晶片矩形 (die region) 偵測
# ---------------------------------------------------------------------------
def _fill_holes(mask):
    H, W = mask.shape
    ff = np.pad(mask, 1).astype(np.uint8)
    m = np.zeros((H + 4, W + 4), np.uint8)
    cv2.floodFill(ff, m, (0, 0), 1)                    # 外框補了一圈 0，從角落一定填得到外部
    holes = (ff[1:-1, 1:-1] == 0)
    out = mask.copy()
    out[holes] = 1
    return out


def detect_die_regions(gray):
    """
    回傳 (regions, region_map)。
    regions: [dict(id, level, thr, x, y, w, h, area, fill, parent)]，id 從 1 起，依「灰階層由暗到亮」排序；
             parent = 包住它的較亮層矩形 id (0 = 沒有)，矩形可巢狀 (例如密集陣列區在整片晶片區裡面)；
    region_map: 每個像素所屬最內層 (最暗) 矩形的 id，0 = 不在任何矩形內。
    """
    H, W = gray.shape
    bg = cv2.medianBlur(cv2.medianBlur(gray, 5), int(P["die_median"]) | 1)
    bgs = cv2.GaussianBlur(bg, (0, 0), P["die_sigma"])
    Z = bgs[::4, ::4].reshape(-1, 1).astype(np.float32)
    k = int(P["die_levels"])
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
    cv2.setRNGSeed(int(P.get("kmeans_seed", 0)))
    _, _, centers = cv2.kmeans(Z, k, None, crit, 5, cv2.KMEANS_PP_CENTERS)
    centers = np.sort(centers.ravel())
    thresholds = [(centers[i] + centers[i + 1]) / 2 for i in range(k - 1)]   # 由暗到亮
    se_o = cv2.getStructuringElement(cv2.MORPH_RECT, (int(P["die_open"]) | 1,) * 2)
    se_c = cv2.getStructuringElement(cv2.MORPH_RECT, (int(P["die_close"]) | 1,) * 2)
    region_map = np.zeros((H, W), np.int32)
    regions = []
    for level, thr in enumerate(thresholds):
        dark = (bgs < thr).astype(np.uint8)
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, se_o)
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, se_c)
        dark = _fill_holes(dark)
        n, lab, st, _ = cv2.connectedComponentsWithStats(dark, 4)
        for i in range(1, n):
            x, y, w, h, a = st[i]
            fill = a / float(w * h)
            if a < P["die_min_area"] * H * W or fill < P["die_min_fill"]:
                continue
            comp = lab == i
            free = comp & (region_map == 0)
            rid = len(regions) + 1
            region_map[free] = rid                 # 只填還沒被更暗 (更內層) 矩形佔走的像素
            # 更暗層的矩形若中心落在這個元件內 → 這個矩形是它的 parent
            for rg in regions:
                if rg["parent"] == 0 and comp[min(rg["y"] + rg["h"] // 2, H - 1), min(rg["x"] + rg["w"] // 2, W - 1)]:
                    rg["parent"] = rid
            # 邊界對比：矩形內側環帶 vs 外側環帶的背景灰階差 (越大越像真的晶片邊緣)
            comp8 = comp.astype(np.uint8)
            se10 = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 21))
            se30 = cv2.getStructuringElement(cv2.MORPH_RECT, (61, 61))
            inner = (cv2.erode(comp8, se10) > 0) & (cv2.erode(comp8, se30) == 0)
            outer = (cv2.dilate(comp8, se30) > 0) & (cv2.dilate(comp8, se10) == 0)
            contrast = float(bgs[outer].mean() - bgs[inner].mean()) if inner.any() and outer.any() else 0.0
            regions.append(dict(id=rid, level=level, thr=float(thr), x=int(x), y=int(y), w=int(w), h=int(h),
                                area=int(a), fill=float(fill), parent=0, contrast=contrast))
    return regions, region_map


# ---------------------------------------------------------------------------
# 陣列分群與整體偏移分析
# ---------------------------------------------------------------------------
def link_sites(sites):
    """
    把位點連成疑似同一片晶片 / 同一陣列的群。
    每點的 pitch = 最近 3 個鄰居距離的中位數；兩點距離 <= link_factor x min(pitch_i, pitch_j)、
    pitch 相近、焊墊半徑相近、深度相近才連結；連通元件即為群。
    回傳每個 site 的群標籤 (0.. 依群大小遞減；未達 min_cluster 的為 -1)，並寫入 s["pitch"]。
    """
    n = len(sites)
    if n == 0:
        return []
    pts = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in sites])
    rad = np.array([s["pad"]["r"] for s in sites])
    dep = np.array([s["pad"]["bg_lv"] - s["pad"]["disc_lv"] for s in sites])
    D = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
    np.fill_diagonal(D, np.inf)
    srt = np.sort(D, axis=1)
    pitch = np.median(srt[:, :3], axis=1) if n > 3 else srt[:, 0]
    pitch = np.where(np.isfinite(pitch), pitch, P["vote_radius"])
    # 同一陣列 pitch 相同：距離以較小的 pitch 為準，且兩者 pitch 比值不能差太多 (避免經散點把不同陣列串起來)
    link = D <= P["link_factor"] * np.minimum(pitch[:, None], pitch[None, :])
    link &= np.maximum(pitch[:, None], pitch[None, :]) <= P["link_pitch_ratio"] * np.minimum(pitch[:, None], pitch[None, :])
    link &= np.abs(rad[:, None] - rad[None, :]) <= P["link_r_tol"] * np.maximum(rad[:, None], rad[None, :])
    link &= np.minimum(dep[:, None], dep[None, :]) >= P["link_depth_ratio"] * np.maximum(dep[:, None], dep[None, :])

    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in zip(*np.where(np.triu(link, 1))):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri
    roots = np.array([find(i) for i in range(n)])
    uniq, counts = np.unique(roots, return_counts=True)
    order = np.argsort(-counts)
    cid = {}
    k = 0
    for idx in order:
        if counts[idx] >= P["min_cluster"]:
            cid[uniq[idx]] = k
            k += 1
        else:
            cid[uniq[idx]] = -1
    for s, pc in zip(sites, pitch):
        s["pitch"] = float(pc)
    return [cid[r] for r in roots]


def _pitch_of(sites):
    if not sites:
        return
    pts = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in sites])
    D = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
    np.fill_diagonal(D, np.inf)
    srt = np.sort(D, axis=1)
    pitch = np.median(srt[:, :3], axis=1) if len(sites) > 3 else srt[:, 0]
    for s, pc in zip(sites, pitch):
        s["pitch"] = float(pc) if np.isfinite(pc) else float(P["vote_radius"])


def _split_by_radius(sites):
    """同一矩形內依焊墊半徑分子群：排序後間隙 > sub_r_gap 就切開，太小的段併入相鄰段。回傳每點的段索引"""
    if not sites:
        return []
    rad = np.array([s["pad"]["r"] for s in sites])
    order = np.argsort(rad)
    seg = np.zeros(len(sites), int)
    cur = 0
    for a, b in zip(order[:-1], order[1:]):
        if rad[b] - rad[a] > P["sub_r_gap"]:
            cur += 1
        seg[b] = cur
    # 太小的段併到半徑最接近的大段
    sizes = np.bincount(seg)
    big = [i for i, c in enumerate(sizes) if c >= P["min_cluster"]]
    if big and len(big) < len(sizes):
        means = {i: rad[seg == i].mean() for i in big}
        for i, c in enumerate(sizes):
            if c < P["min_cluster"] and i not in big:
                m = rad[seg == i].mean()
                seg[seg == i] = min(big, key=lambda j: abs(means[j] - m))
    # 重新編號
    uniq = {v: i for i, v in enumerate(sorted(set(seg.tolist())))}
    return [uniq[v] for v in seg]


def assign_region(sites, region_map):
    """位點中心所在的最內層晶片矩形 id (0 = 不在任何矩形內)"""
    for s in sites:
        if region_map is None:
            s["region"] = 0
            continue
        y, x = int(round(s["pad"]["y"])), int(round(s["pad"]["x"]))
        y = min(max(y, 0), region_map.shape[0] - 1)
        x = min(max(x, 0), region_map.shape[1] - 1)
        s["region"] = int(region_map[y, x])


def region_members(sites, regions):
    """每個矩形 (含巢狀子矩形) 內的位點清單"""
    parent = {rg["id"]: rg["parent"] for rg in regions}
    member = {rg["id"]: [] for rg in regions}
    for s in sites:
        rid = s.get("region", 0)
        while rid:
            member[rid].append(s)
            rid = parent.get(rid, 0)
    return member


def cluster_sites(sites, region_map=None):
    """
    以晶片矩形為主的分群：
      region = 位點中心所在的最內層晶片矩形 (0 = 不在任何矩形內)
      矩形內：依焊墊半徑切子群；矩形外 (region 0)：用 pitch 自適應連結分群
    每個 site 寫入 s["region"], s["cluster"] (1.. 依 (region, 群大小) 排序；太小的群為 0)。回傳群數。
    """
    if not sites:
        return 0
    assign_region(sites, region_map)
    _pitch_of(sites)
    groups = []                                     # (region, [sites])
    for reg in sorted(set(s["region"] for s in sites)):
        rs = [s for s in sites if s["region"] == reg]
        if reg == 0:
            lab = link_sites(rs)
            for g in sorted(set(lab)):
                if g < 0:
                    continue
                groups.append((reg, [s for s, l in zip(rs, lab) if l == g]))
            for s, l in zip(rs, lab):
                if l < 0:
                    s["cluster"] = 0
        else:
            seg = _split_by_radius(rs)
            for g in sorted(set(seg)):
                members = [s for s, l in zip(rs, seg) if l == g]
                if len(members) >= P["min_cluster"]:
                    groups.append((reg, members))
                else:
                    for s in members:
                        s["cluster"] = 0
    groups.sort(key=lambda g: (g[0] if g[0] > 0 else 10 ** 6, -len(g[1])))
    for k, (reg, members) in enumerate(groups, 1):
        for s in members:
            s["cluster"] = k
    for s in sites:
        s.setdefault("cluster", 0)
    return len(groups)


def similarity_fit(src, dst):
    """dst ≈ s·R·src + t (LMedS 穩健估計)。回傳 dict(tx, ty, rot_deg, scale, resid[]) 或 None"""
    if len(src) < 4:
        return None
    M, _ = cv2.estimateAffinePartial2D(np.asarray(src, np.float32), np.asarray(dst, np.float32), method=cv2.LMEDS)
    if M is None:
        return None
    pred = np.asarray(src) @ M[:, :2].T + M[:, 2]
    resid = np.linalg.norm(pred - np.asarray(dst), axis=1)
    return dict(tx=float(M[0, 2]), ty=float(M[1, 2]),
                rot_deg=float(np.degrees(np.arctan2(M[1, 0], M[0, 0]))),
                scale=float(np.hypot(M[0, 0], M[1, 0])), resid=resid)


def shift_stats(vecs):
    """平均偏移向量、方向一致性 R (0~1)、t 值"""
    v = np.asarray(vecs, np.float64)
    n = len(v)
    m = v.mean(0)
    mag = float(np.hypot(*m))
    mean_abs = float(np.hypot(v[:, 0], v[:, 1]).mean())
    coh = mag / mean_abs if mean_abs > 1e-9 else 0.0
    sd = float(np.sqrt((v[:, 0].var(ddof=1) + v[:, 1].var(ddof=1)) / 2)) if n > 1 else float("nan")
    t = mag * np.sqrt(n) / sd if sd and sd > 1e-9 else float("inf")
    return dict(mean_dx=float(m[0]), mean_dy=float(m[1]), mean_mag=mag, coherence=float(coh), sd=sd, t_stat=float(t))


def analyze_clusters(sites):
    """
    每群：型態 (two-level 佔多數與否)、pitch、平均偏移向量與一致性、相似變換 (旋轉/平移/縮放)、
    扣除變換前後的偏移 RMS、外形拉長一致性，最後給整體偏移判定。
    同時把每個 two-level 位點扣除「所屬群變換」後的殘差寫入 s["resid_c"]。
    """
    K = max([s.get("cluster", 0) for s in sites] + [0])
    out = []
    for k in range(1, K + 1):
        cs = [s for s in sites if s["cluster"] == k]
        two = [s for s in cs if s["kind"] == "two-level"]
        meas = [s for s in cs if s["bump"] is not None]
        kind = "two-level" if len(two) >= 0.5 * len(cs) else "single"
        pts = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in cs])
        c = dict(cluster=k, region=cs[0].get("region", 0), n=len(cs), n_two_level=len(two), kind=kind,
                 pad_r_median=float(np.median([s["pad"]["r"] for s in cs])),
                 pitch_median=float(np.median([s["pitch"] for s in cs])),
                 cx=float(pts[:, 0].mean()), cy=float(pts[:, 1].mean()),
                 x0=float(pts[:, 0].min()), y0=float(pts[:, 1].min()), x1=float(pts[:, 0].max()), y1=float(pts[:, 1].max()))
        use = two if kind == "two-level" else meas
        st = shift_stats([[s["dx"], s["dy"]] for s in use]) if len(use) >= 2 else None
        if st:
            c.update(st)
        fit = None
        if len(use) >= 6:
            fit = similarity_fit([[s["pad"]["x"], s["pad"]["y"]] for s in use],
                                 [[s["bump"]["x"], s["bump"]["y"]] for s in use])
        if fit:
            rms_b = float(np.sqrt(np.mean([s["d"] ** 2 for s in use])))
            rms_a = float(np.sqrt(np.mean(fit["resid"] ** 2)))
            if rms_a > rms_b:                       # 樣本少時 LMedS 可能擬出離譜的變換，視為不可靠
                fit = None
            else:
                c.update(rot_deg=fit["rot_deg"], scale=fit["scale"], tx=fit["tx"], ty=fit["ty"],
                         rms_before=rms_b, rms_after=rms_a)
        if fit:
            if kind == "two-level":
                for s, rr in zip(use, fit["resid"]):
                    s["resid_c"] = float(rr)
        # 外形拉長一致性 (焊墊外形 2 次諧波的向量平均)
        e2 = np.array([s["pad"].get("e2", 0j) for s in cs])
        amp = np.abs(e2)
        if len(e2) >= 2 and amp.mean() > 1e-9:
            mean_e2 = e2.mean()
            c.update(elong_amp=float(amp.mean()), elong_coherence=float(abs(mean_e2) / amp.mean()),
                     elong_axis_deg=float(np.degrees(np.angle(mean_e2)) / 2))
        shift_verdict(c, kind, len(use), st)
        out.append(c)
    return out


def shift_verdict(c, kind, n_use, st):
    """依平均偏移 |m|、方向一致性 R、t 值給整體偏移判定，寫入 c["verdict"], c["level"]"""
    hi_m, hi_r, hi_t = P["shift_high"]
    mid_m, mid_t = P["shift_mid"]
    strong = st and n_use >= 6 and st["mean_mag"] >= hi_m and st["coherence"] >= hi_r and st["t_stat"] >= hi_t
    if kind != "two-level":
        # 單一斜坡：偏移量本身可信度低，但若群內方向高度一致且顯著，仍值得提示人工確認
        if strong:
            v = "低可信度: 疑似整體偏移(單一斜坡但方向一致)"
            c["level"] = "高(低可信)"
        else:
            v = "無法判定(單一斜坡)"
            c["level"] = "n/a"
        if c.get("elong_coherence", 0) >= 0.5 and c.get("elong_amp", 0) >= 1.0:
            v += f", 外形一致拉長 軸{c['elong_axis_deg']:+.0f}deg"
        c["verdict"] = v
    elif not st or n_use < 6:
        c["verdict"] = "樣本不足"
        c["level"] = "n/a"
    elif strong:
        c["verdict"] = "疑似整體晶片偏移"
        c["level"] = "高"
    elif st["mean_mag"] >= mid_m and st["t_stat"] >= mid_t:
        c["verdict"] = "可能有整體偏移(量小或方向不一致)"
        c["level"] = "中"
    else:
        c["verdict"] = "看不出整體偏移"
        c["level"] = "低"


def quality_filter(sites, shape):
    """
    依「同一片晶片的凸塊大小應一致、凸塊應落在焊點內、擬合要可靠」篩出估整體位移用的位點。
    每個 site 寫入 s["used"] (bool) 與 s["reject"] (原因)。半徑 / 深度的中位數以所在矩形為準 (太少顆則用全圖)。
    """
    H, W = shape
    withb = [s for s in sites if s["bump"] is not None]

    def meds(group):
        rb = np.median([s["bump"]["r"] for s in group]); rp = np.median([s["pad"]["r"] for s in group])
        dp = np.median([s["pad"]["bg_lv"] - s["pad"]["disc_lv"] for s in group])
        return rb, rp, dp

    glob = meds(withb) if withb else (0, 0, 0)
    per_region = {}
    for reg in set(s.get("region", 0) for s in withb):
        g = [s for s in withb if s.get("region", 0) == reg]
        per_region[reg] = meds(g) if len(g) >= P["q_min_group"] else glob
    for s in sites:
        s["used"], s["reject"] = False, ""
        b, p = s["bump"], s["pad"]
        rb_med, rp_med, dp_med = per_region.get(s.get("region", 0), glob)
        depth = p["bg_lv"] - p["disc_lv"]
        if b is None:
            s["reject"] = "no bump circle"
        elif (p["x"] - p["r"] < P["q_border"] or p["y"] - p["r"] < P["q_border"]
              or p["x"] + p["r"] > W - P["q_border"] or p["y"] + p["r"] > H - P["q_border"]):
            s["reject"] = "near image border"
        elif s["note"].startswith("inner fit inconsistent") or s["note"].startswith("inner edge not found"):
            s["reject"] = "inner fit unreliable"
        elif b["rms"] > P["q_rms"] or b["cov"] < P["q_cov"]:
            s["reject"] = f"inner fit poor (rms {b['rms']:.2f}, cov {b['cov']:.2f})"
        elif abs(b["r"] - rb_med) > max(P["q_r_abs"], P["q_r_tol"] * rb_med):
            s["reject"] = f"bump radius {b['r']:.1f} vs median {rb_med:.1f}"
        elif abs(p["r"] - rp_med) > max(P["q_r_abs"], P["q_p_tol"] * rp_med):
            s["reject"] = f"pad radius {p['r']:.1f} vs median {rp_med:.1f}"
        elif depth < P["q_depth_ratio"] * dp_med:
            s["reject"] = f"low contrast {depth:.0f} vs median {dp_med:.0f}"
        elif s["d"] > P["q_overlap"] * (b["r"] + p["r"]):
            s["reject"] = "bump not on pad (no overlap)"
        else:
            s["used"] = True


def estimate_shift(use):
    """
    穩健估計一群位點的整體偏移。
    模型：凸塊心 ≈ s·R(θ)·焊點心 + t (相似變換)。錐形束放大率差會讓偏移隨位置線性變化 (縮放項)，
    旋轉會讓偏移隨位置旋轉；「晶片需位移多少」取的是變換在晶片 (位點) 中心處的偏移向量。
    步驟：中位數起始 → 反覆取容差內內點 → 內點做相似變換最小平方 → 以變換殘差重選內點 → 報中心偏移。
    回傳 dict 或 None (少於 3 顆)。correction = -shift (晶片要移動多少才會和焊點重合)。
    """
    if len(use) < 3:
        return None
    v = np.array([[s["dx"], s["dy"]] for s in use], np.float64)
    pts = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in use], np.float64)
    n = len(v)
    # 1) 平移模型的穩健內點 (起始)
    t = np.median(v, axis=0)
    tol = P["shift_tol"]
    inl = np.ones(n, bool)
    for _ in range(5):
        res = np.linalg.norm(v - t, axis=1)
        tol = max(P["shift_tol"], 2.5 * float(np.median(res)) * 1.4826)
        inl = res <= tol
        if inl.sum() < 3:
            break
        t = v[inl].mean(axis=0)
    fit = None
    center = pts.mean(axis=0)
    # 2) 相似變換：平移 + 旋轉 + 縮放 (吸收放大率差)，殘差重選內點
    if n >= 6:
        for _ in range(3):
            M, _ = cv2.estimateAffinePartial2D(pts[inl].astype(np.float32), (pts[inl] + v[inl]).astype(np.float32),
                                               method=cv2.LMEDS)
            if M is None:
                break
            pred = pts @ M[:, :2].T + M[:, 2]
            res = np.linalg.norm(pred - (pts + v), axis=1)
            tol = max(P["shift_tol"], 2.5 * float(np.median(res[inl])) * 1.4826)
            new_inl = res <= tol
            fit = dict(M=M, res=res)
            if new_inl.sum() < 3 or np.array_equal(new_inl, inl):
                inl = new_inl if new_inl.sum() >= 3 else inl
                break
            inl = new_inl
    n_in = int(inl.sum())
    if n_in < 3:
        return None
    out = dict(n_used=int(n), n_in=n_in, ratio=float(n_in / n), tol=float(tol))
    if fit is not None and abs(np.degrees(np.arctan2(fit["M"][1, 0], fit["M"][0, 0]))) < 2:
        M = fit["M"]
        center = pts[inl].mean(axis=0)
        vc = (M[:, :2] @ center + M[:, 2]) - center           # 變換在中心處的偏移
        scale = float(np.hypot(M[0, 0], M[1, 0]))
        rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
        res = fit["res"]
        # 縮放/旋轉在晶片邊角造成的偏移變化量 (供判斷放大率差有多大)
        ext = np.linalg.norm(pts[inl] - center, axis=1).max()
        out.update(dx=float(vc[0]), dy=float(vc[1]), mag=float(np.hypot(*vc)), model="similarity",
                   rot_deg=rot, scale=scale, scale_ppm=float((scale - 1) * 1e6),
                   edge_var=float(np.hypot(scale - 1, np.radians(rot)) * ext),
                   rms_in=float(np.sqrt((res[inl] ** 2).mean())),
                   mean_dx=float(v[inl].mean(axis=0)[0]), mean_dy=float(v[inl].mean(axis=0)[1]))
        # 中心偏移的標準誤：以內點殘差估計
        out["se"] = float(out["rms_in"] / np.sqrt(n_in))
    else:
        res = np.linalg.norm(v - t, axis=1)
        sd = v[inl].std(axis=0, ddof=1) if n_in > 1 else np.zeros(2)
        out.update(dx=float(t[0]), dy=float(t[1]), mag=float(np.hypot(*t)), model="translation",
                   rot_deg=None, scale=None, scale_ppm=None, edge_var=None,
                   rms_in=float(np.sqrt((res[inl] ** 2).mean())), se=float(np.hypot(*(sd / np.sqrt(n_in)))),
                   mean_dx=float(t[0]), mean_dy=float(t[1]))
    out["corr_dx"], out["corr_dy"] = -out["dx"], -out["dy"]
    out["center"] = (float(center[0]), float(center[1]))
    if n_in >= 20 and out["ratio"] >= 0.6 and out["se"] <= 0.3:
        out["grade"] = "高"
    elif n_in >= 8 and out["ratio"] >= 0.5 and out["se"] <= 0.6:
        out["grade"] = "中"
    else:
        out["grade"] = "低"
    for s_, ok in zip(use, inl):
        s_["shift_inlier"] = bool(ok)
    return out


def analyze_regions(sites, regions):
    """
    每個晶片矩形 (含巢狀子矩形內的位點) 的整體偏移分析：
    以矩形內全部 two-level 位點的偏移向量算平均、一致性、t 值與相似變換，給判定。
    """
    member = region_members(sites, regions)
    for rg in regions:
        cs = member[rg["id"]]
        two = [s for s in cs if s["kind"] == "two-level"]
        meas = [s for s in cs if s["bump"] is not None]
        kind = "two-level" if cs and len(two) >= 0.5 * len(cs) else "single"
        rg.update(n_sites=len(cs), n_two_level=len(two), kind=kind)
        use = two if kind == "two-level" else meas
        st = shift_stats([[s["dx"], s["dy"]] for s in use]) if len(use) >= 2 else None
        if st:
            rg.update(st)
        if len(use) >= 6:
            fit = similarity_fit([[s["pad"]["x"], s["pad"]["y"]] for s in use],
                                 [[s["bump"]["x"], s["bump"]["y"]] for s in use])
            if fit:
                rms_b = float(np.sqrt(np.mean([s["d"] ** 2 for s in use])))
                rms_a = float(np.sqrt(np.mean(fit["resid"] ** 2)))
                if rms_a <= rms_b:
                    rg.update(rot_deg=fit["rot_deg"], scale=fit["scale"], tx=fit["tx"], ty=fit["ty"],
                              rms_before=rms_b, rms_after=rms_a)
        e2 = np.array([s["pad"].get("e2", 0j) for s in cs])
        amp = np.abs(e2)
        if len(e2) >= 2 and amp.mean() > 1e-9:
            rg.update(elong_amp=float(amp.mean()), elong_coherence=float(abs(e2.mean()) / amp.mean()),
                      elong_axis_deg=float(np.degrees(np.angle(e2.mean())) / 2))
        if cs:
            tmp = dict(rg)
            tmp.pop("level", None)
            shift_verdict(tmp, kind, len(use), st)
            rg["verdict"], rg["level_verdict"] = tmp["verdict"], tmp["level"]
        else:
            rg["verdict"], rg["level_verdict"] = "無位點", "n/a"
        # 整體位移估計：只用品質篩選過的位點 (含子矩形內的)
        used = [s for s in cs if s.get("used")]
        rg["n_used"] = len(used)
        rg["shift"] = estimate_shift(used) if len(used) >= P["min_shift_sites"] else None
        used_two = [s for s in used if s["kind"] == "two-level"]
        rg["shift_two"] = estimate_shift(used_two) if len(used_two) >= P["min_shift_sites"] else None
    # 主要晶片：有足夠可用位點，且邊界對比不輸給 parent 與有位點的子矩形 (巢狀鏈裡挑最像晶片邊緣的那層)
    by_id = {rg["id"]: rg for rg in regions}
    children = {}
    for rg in regions:
        children.setdefault(rg["parent"], []).append(rg)
    for rg in regions:
        ok = rg["n_used"] >= P["min_shift_sites"]
        par = by_id.get(rg["parent"])
        if ok and par and par["n_used"] >= P["min_shift_sites"] and par.get("contrast", 0) > rg.get("contrast", 0):
            ok = False
        for ch in children.get(rg["id"], []):
            if ok and ch["n_used"] >= P["min_shift_sites"] and ch.get("contrast", 0) > rg.get("contrast", 0):
                ok = False
        rg["primary"] = bool(ok)


# ---------------------------------------------------------------------------
# 整張影像
# ---------------------------------------------------------------------------
def dedupe(sites, min_dist=None):
    """同一顆被兩個候選核心量到時只留擬合較好的那個"""
    min_dist = min_dist or P["dedupe_dist"]
    sites = sorted(sites, key=lambda s: s["pad"]["rms"])
    min_dist2 = min_dist * min_dist
    cell = max(float(min_dist), 1.0)
    grid = {}
    kept = []
    for s in sites:
        px, py = s["pad"]["x"], s["pad"]["y"]
        gx, gy = int(np.floor(px / cell)), int(np.floor(py / cell))
        duplicate = False
        for yy in range(gy - 1, gy + 2):
            for xx in range(gx - 1, gx + 2):
                for k in grid.get((xx, yy), ()):
                    dx = px - k["pad"]["x"]
                    dy = py - k["pad"]["y"]
                    if dx * dx + dy * dy <= min_dist2:
                        duplicate = True
                        break
                if duplicate:
                    break
            if duplicate:
                break
        if not duplicate:
            kept.append(s)
            grid.setdefault((gx, gy), []).append(s)
    return kept


def global_transform(sites):
    """凸塊心 ≈ s·R·焊墊心 + t，估計晶片相對基板的整體平移 / 旋轉 / 縮放"""
    two = [s for s in sites if s["kind"] == "two-level"]
    if len(two) < 6:
        return None
    fit = similarity_fit([[s["pad"]["x"], s["pad"]["y"]] for s in two],
                         [[s["bump"]["x"], s["bump"]["y"]] for s in two])
    if fit is None:
        return None
    for s, rr in zip(two, fit["resid"]):
        s["resid"] = float(rr)
    return dict(tx=fit["tx"], ty=fit["ty"], rot_deg=fit["rot_deg"], scale=fit["scale"],
                resid_median=float(np.median(fit["resid"])), resid_max=float(fit["resid"].max()))


def measure_all(den, cands, shape, region_map=None):
    """在指定的量測影像上量所有候選位點，去重、剔除紋理、指派矩形、品質篩選"""
    sampler = RaySampler(den)
    sites = []
    for (cx, cy, _resp) in cands:
        s = measure_site(sampler, cx, cy)
        if s is not None:
            sites.append(s)
    sites = dedupe(sites)
    sites = drop_inconsistent(sites)
    assign_region(sites, region_map)
    finalize_pads(sites, den)
    quality_filter(sites, shape)
    return sites


def shift_range(main, variants):
    """主估計 + 各前處理變體估計的範圍：半幅當系統不確定度，與統計 se 合併"""
    ests = [sh for sh in [main] + list(variants.values()) if sh]
    if not main or len(ests) < 2:
        return None
    dx = np.array([sh["corr_dx"] for sh in ests]); dy = np.array([sh["corr_dy"] for sh in ests])
    sys_dx, sys_dy = float((dx.max() - dx.min()) / 2), float((dy.max() - dy.min()) / 2)
    return dict(n_variants=len(ests), dx_min=float(dx.min()), dx_max=float(dx.max()), dy_min=float(dy.min()), dy_max=float(dy.max()),
                sys_dx=sys_dx, sys_dy=sys_dy, sys=float(np.hypot(sys_dx, sys_dy)),
                total=float(np.hypot(main["se"], np.hypot(sys_dx, sys_dy))))


def process_image(path, px_um=None, variants=True, roi=None):
    """
    roi=(x, y, w, h) 時只對該區域運算 (偵測、晶片矩形、量測都在 ROI 內)，結果座標換算回全圖。
    """
    gray_full = load_gray(path)
    if roi:
        x, y, w, h = [int(v) for v in roi]
        H, W = gray_full.shape
        x, y = max(0, x), max(0, y)
        w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
        res = process_array(gray_full[y:y + h, x:x + w], px_um, variants)
        for s in res["sites"]:
            for c in (s["pad"], s["bump"]):
                if c:
                    c["x"] += x; c["y"] += y
        for rg in res["regions"]:
            rg["x"] += x; rg["y"] += y
        for c in res["clusters"]:
            for key, off in (("cx", x), ("cy", y), ("x0", x), ("y0", y), ("x1", x), ("y1", y)):
                if key in c:
                    c[key] += off
        res["gray"] = gray_full
        res["den"] = denoise(gray_full, P["detect_sigma"])
        res["roi"] = (x, y, w, h)
    else:
        res = process_array(gray_full, px_um, variants)
        res["roi"] = None
    res["path"] = path
    return res


def process_array(gray, px_um=None, variants=True):
    den_d = denoise(gray, P["detect_sigma"])      # 偵測用
    den = denoise(gray, P["gauss_sigma"])         # 量測用 (射線剖面)
    cands, _ = detect_candidates(den_d)
    regions, region_map = detect_die_regions(gray)
    sites = measure_all(den, cands, gray.shape, region_map)
    classify_sites(sites)
    # 依位置排序給編號 (先 y 再 x，y 以 40px 為一列)
    sites.sort(key=lambda s: (round(s["pad"]["y"] / 40.0), s["pad"]["x"]))
    for i, s in enumerate(sites, 1):
        s["id"] = i
    gt = global_transform(sites)
    cluster_sites(sites, region_map)
    clusters = analyze_clusters(sites)
    analyze_regions(sites, regions)
    used_all = [s for s in sites if s.get("used")]
    shift_all = estimate_shift(used_all) if len(used_all) >= P["min_shift_sites"] else None
    die_shifts = [rg for rg in regions if rg.get("primary") and rg.get("shift")]

    # ---- 前處理敏感度：同一批候選點在其他去噪影像上重量，位移估計的變化範圍 = 系統不確定度 ----
    variant_names = []
    shift_all_variants, shift_all_range = {}, None
    if variants:
        for rg in regions:
            rg["shift_variants"] = {}
        for name, kind, param in PREPROC_VARIANTS:
            try:
                den_v = preprocess(gray, kind, param)
            except cv2.error:
                continue
            variant_names.append(name)
            sites_v = measure_all(den_v, cands, gray.shape, region_map)
            member = region_members(sites_v, regions)
            for rg in regions:
                used = [s for s in member[rg["id"]] if s.get("used")]
                rg["shift_variants"][name] = estimate_shift(used) if len(used) >= P["min_shift_sites"] else None
            used_v = [s for s in sites_v if s.get("used")]
            shift_all_variants[name] = estimate_shift(used_v) if len(used_v) >= P["min_shift_sites"] else None
        for rg in regions:
            rg["shift_range"] = shift_range(rg.get("shift"), rg["shift_variants"])
        shift_all_range = shift_range(shift_all, shift_all_variants)
    if px_um:
        for s in sites:
            if s["kind"] == "two-level":
                s["d_um"] = s["d"] * px_um
    if px_um:
        for rg in regions:
            for key in ("shift", "shift_two"):
                if rg.get(key):
                    rg[key]["corr_um"] = (rg[key]["corr_dx"] * px_um, rg[key]["corr_dy"] * px_um)
        if shift_all:
            shift_all["corr_um"] = (shift_all["corr_dx"] * px_um, shift_all["corr_dy"] * px_um)
    return dict(path=None, gray=gray, den=den_d, sites=sites, n_cand=len(cands), gt=gt, clusters=clusters,
                regions=regions, region_map=region_map, shift_all=shift_all, die_shifts=die_shifts,
                n_used=len(used_all))


# ---------------------------------------------------------------------------
# 輸出：疊圖 / CSV / 摘要
# ---------------------------------------------------------------------------
def cluster_color(k):
    hsv = np.uint8([[[(k * 47) % 180, 200, 255]]])
    b, g, r = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return int(b), int(g), int(r)


def draw_regions(vis, regions):
    """晶片矩形：粗框 + 標籤 D#"""
    f = cv2.FONT_HERSHEY_SIMPLEX
    for rg in regions:
        col = cluster_color(100 + rg["id"] * 3)
        x0, y0, x1, y1 = rg["x"], rg["y"], rg["x"] + rg["w"] - 1, rg["y"] + rg["h"] - 1
        cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 0, 0), 7)
        cv2.rectangle(vis, (x0, y0), (x1, y1), col, 3)
        txt = f"D{rg['id']}" + (f"<D{rg['parent']}" if rg.get("parent") else "") + f" n={rg.get('n_sites', 0)} used={rg.get('n_used', 0)}"
        sh = rg.get("shift")
        if rg.get("primary") and sh:
            txt += f" DIE MOVE ({sh['corr_dx']:+.2f},{sh['corr_dy']:+.2f})px in={sh['n_in']}/{sh['n_used']} {sh['grade']}"
            cx, cy = x0 + rg["w"] // 2, y0 + rg["h"] // 2
            p1 = (int(cx + sh["corr_dx"] * P["arrow_scale"] * 3), int(cy + sh["corr_dy"] * P["arrow_scale"] * 3))
            cv2.arrowedLine(vis, (cx, cy), p1, (0, 0, 0), 7, cv2.LINE_AA, tipLength=0.25)
            cv2.arrowedLine(vis, (cx, cy), p1, (0, 255, 255), 3, cv2.LINE_AA, tipLength=0.25)
        org = (x0 + 12, max(y0 - 10, 26) if y0 > 40 else y0 + 30)
        cv2.putText(vis, txt, org, f, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(vis, txt, org, f, 0.8, col, 2, cv2.LINE_AA)
    return vis


def draw_clusters(vis, sites, clusters):
    """每群畫凸包外框、標籤，two-level 群再畫平均偏移箭頭 (放大 arrow_scale 倍)"""
    f = cv2.FONT_HERSHEY_SIMPLEX
    for c in clusters:
        k = c["cluster"]
        col = cluster_color(k)
        cs = [s for s in sites if s.get("cluster") == k]
        pts = np.array([[s["pad"]["x"], s["pad"]["y"]] for s in cs], np.float32)
        hull = cv2.convexHull(pts).reshape(-1, 2)
        # 外框往外推一個焊墊半徑
        ctr = hull.mean(0)
        vec = hull - ctr
        norm = np.linalg.norm(vec, axis=1, keepdims=True) + 1e-6
        hull = (hull + vec / norm * (c["pad_r_median"] + 4)).astype(np.int32)
        cv2.polylines(vis, [hull.reshape(-1, 1, 2)], True, col, 1, cv2.LINE_AA)
        top = hull[np.argmin(hull[:, 1])]
        label = f"C{k}(D{c.get('region', 0)}) n={c['n']} {c['kind']}"
        if c.get("level") in ("高", "中", "高(低可信)"):
            label += f" mean=({c['mean_dx']:+.2f},{c['mean_dy']:+.2f}) t={c['t_stat']:.1f} " + \
                     {"高": "SHIFT?", "中": "shift?", "高(低可信)": "shift? (low conf)"}[c["level"]]
        elif c["kind"] == "two-level" and "mean_mag" in c:
            label += f" mean=({c['mean_dx']:+.2f},{c['mean_dy']:+.2f}) t={c['t_stat']:.1f}"
        org = (int(max(top[0] - 40, 2)), int(max(top[1] - 8, 14)))
        cv2.putText(vis, label, org, f, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(vis, label, org, f, 0.55, col, 1, cv2.LINE_AA)
        if "mean_mag" in c and c["mean_mag"] > 0.05 and (c["kind"] == "two-level" or c.get("level") == "高(低可信)"):
            p0 = (int(c["cx"]), int(c["cy"]))
            p1 = (int(c["cx"] + c["mean_dx"] * P["arrow_scale"]), int(c["cy"] + c["mean_dy"] * P["arrow_scale"]))
            cv2.arrowedLine(vis, p0, p1, (0, 0, 0), 5, cv2.LINE_AA, tipLength=0.3)
            cv2.arrowedLine(vis, p0, p1, col, 2, cv2.LINE_AA, tipLength=0.3)
    return vis


def draw_overlay(den, sites, limit, clusters=None, regions=None, roi=None):
    vis = cv2.cvtColor(np.clip(den, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    f = cv2.FONT_HERSHEY_SIMPLEX
    if roi:
        x, y, w, h = roi
        cv2.rectangle(vis, (x, y), (x + w - 1, y + h - 1), (0, 165, 255), 3)
        cv2.putText(vis, f"ROI ({x},{y},{w}x{h})", (x + 8, max(y - 8, 20)), f, 0.7, (0, 165, 255), 2, cv2.LINE_AA)
    if regions:
        draw_regions(vis, regions)
    if clusters:
        draw_clusters(vis, sites, clusters)
    for s in sites:
        p = s["pad"]
        pc = (int(round(p["x"])), int(round(p["y"])))
        if not s.get("used"):
            # 品質篩選淘汰的位點：灰色細圓，不畫偏移
            cv2.circle(vis, pc, int(round(p["r"])), (110, 110, 110), 1, cv2.LINE_AA)
            if s["bump"] is not None:
                b = s["bump"]
                cv2.circle(vis, (int(round(b["x"])), int(round(b["y"]))), int(round(b["r"])), (90, 90, 140), 1, cv2.LINE_AA)
            continue
        if s["kind"] == "two-level":
            b = s["bump"]
            bc = (int(round(b["x"])), int(round(b["y"])))
            cv2.circle(vis, pc, int(round(p["r"])), (0, 200, 0), 1, cv2.LINE_AA)
            cv2.circle(vis, bc, int(round(b["r"])), (0, 0, 255), 1, cv2.LINE_AA)
            cv2.line(vis, pc, bc, (0, 140, 255), 1, cv2.LINE_AA)
            col = (0, 0, 255) if s["d"] > limit else (0, 200, 255)
            cv2.putText(vis, f"{s['d']:.1f}", (pc[0] + 14, pc[1] - 14), f, 0.38, col, 1, cv2.LINE_AA)
        else:
            cv2.circle(vis, pc, int(round(p["r"])), (255, 80, 0), 1, cv2.LINE_AA)
            if s["bump"] is not None:
                b = s["bump"]
                cv2.putText(vis, f"({s['d']:.1f})", (pc[0] + 14, pc[1] - 14), f, 0.33, (255, 160, 60), 1, cv2.LINE_AA)
        idc = cluster_color(s["cluster"]) if s.get("cluster") else (200, 200, 200)
        cv2.putText(vis, str(s["id"]), (pc[0] - 22, pc[1] + 26), f, 0.3, idc, 1, cv2.LINE_AA)
    # 圖例
    legend = [("two-level: pad (green) / bump (red) / offset px", (0, 200, 0)),
              ("single ramp (blue): edges not separable, (offset) low confidence", (255, 80, 0)),
              (f"offset > {limit:g}px in red text", (0, 0, 255)),
              (f"die rect D# (thick) / grey = filtered out / yellow arrow = die move to align (x{P['arrow_scale'] * 3:g})", (255, 255, 255))]
    for i, (txt, col) in enumerate(legend):
        cv2.putText(vis, txt, (10, 24 + 22 * i), f, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(vis, txt, (10, 24 + 22 * i), f, 0.6, col, 1, cv2.LINE_AA)
    return vis


CSV_FIELDS = ["id", "region", "cluster", "type", "mode", "lobe_span_deg", "used", "reject_reason", "shift_inlier", "pad_x", "pad_y", "pad_r", "bump_x", "bump_y", "bump_r",
              "dx_px", "dy_px", "offset_px", "offset_um", "edge_sep_px", "edge_sep_local_px",
              "resid_after_cluster_px", "resid_after_global_px", "elong_amp_px", "elong_axis_deg",
              "pad_fit_rms", "bump_fit_rms", "pad_edge_cov", "bump_edge_cov", "note"]

CLUSTER_FIELDS = ["cluster", "region", "n", "n_two_level", "kind", "pad_r_median", "pitch_median", "cx", "cy",
                  "x0", "y0", "x1", "y1", "mean_dx", "mean_dy", "mean_mag", "coherence", "sd", "t_stat",
                  "rot_deg", "scale", "tx", "ty", "rms_before", "rms_after",
                  "elong_amp", "elong_coherence", "elong_axis_deg", "level", "verdict"]


def site_row(s):
    p, b = s["pad"], s["bump"]
    fmt = lambda v: "" if v is None else f"{v:.2f}"
    e2 = p.get("e2")
    return dict(
        id=s["id"], region=s.get("region", ""), cluster=s.get("cluster", ""), type=s["kind"],
        mode=s.get("mode", ""), lobe_span_deg=fmt(s.get("lobe_span")) if s.get("mode") == "lobe" else "",
        used=int(bool(s.get("used"))), reject_reason=s.get("reject", ""),
        shift_inlier=("" if s.get("shift_inlier") is None else int(bool(s.get("shift_inlier")))),
        pad_x=fmt(p["x"]), pad_y=fmt(p["y"]), pad_r=fmt(p["r"]),
        bump_x=fmt(b["x"]) if b else "", bump_y=fmt(b["y"]) if b else "", bump_r=fmt(b["r"]) if b else "",
        dx_px=fmt(s.get("dx")), dy_px=fmt(s.get("dy")), offset_px=fmt(s.get("d")),
        offset_um=fmt(s.get("d_um")), edge_sep_px=fmt(s.get("sep")), edge_sep_local_px=fmt(s.get("sep_local")),
        resid_after_cluster_px=fmt(s.get("resid_c")), resid_after_global_px=fmt(s.get("resid")),
        elong_amp_px=fmt(abs(e2)) if e2 is not None else "",
        elong_axis_deg=fmt(np.degrees(np.angle(e2)) / 2) if e2 is not None else "",
        pad_fit_rms=fmt(p["rms"]), bump_fit_rms=fmt(b["rms"]) if b else "",
        pad_edge_cov=fmt(p["cov"]), bump_edge_cov=fmt(b["cov"]) if b else "",
        note=s.get("note", ""),
    )


def write_csv(sites, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for s in sites:
            w.writerow(site_row(s))


def write_cluster_csv(clusters, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CLUSTER_FIELDS)
        w.writeheader()
        for c in clusters:
            row = {}
            for k in CLUSTER_FIELDS:
                v = c.get(k, "")
                row[k] = f"{v:.3f}" if isinstance(v, float) else v
            w.writerow(row)


REGION_FIELDS = ["id", "parent", "level", "thr", "x", "y", "w", "h", "area", "fill", "contrast", "primary",
                 "n_sites", "n_two_level", "n_used", "shift_dx", "shift_dy", "shift_n_in", "shift_ratio", "shift_se",
                 "shift_rot_deg", "shift_grade", "corr_dx", "corr_dy", "corr_dx_min", "corr_dx_max", "corr_dy_min", "corr_dy_max",
                 "sys_dx", "sys_dy", "total_unc", "kind",
                 "mean_dx", "mean_dy", "mean_mag", "coherence", "t_stat", "rot_deg", "scale", "tx", "ty",
                 "rms_before", "rms_after", "elong_amp", "elong_coherence", "elong_axis_deg", "level_verdict", "verdict"]


def write_region_csv(regions, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=REGION_FIELDS)
        w.writeheader()
        for rg in regions:
            row = dict(rg)
            sh = rg.get("shift") or {}
            rn = rg.get("shift_range") or {}
            row.update(primary=int(bool(rg.get("primary"))), shift_dx=sh.get("dx"), shift_dy=sh.get("dy"), shift_n_in=sh.get("n_in"),
                       shift_ratio=sh.get("ratio"), shift_se=sh.get("se"), shift_rot_deg=sh.get("rot_deg"),
                       shift_grade=sh.get("grade"), corr_dx=sh.get("corr_dx"), corr_dy=sh.get("corr_dy"),
                       corr_dx_min=rn.get("dx_min"), corr_dx_max=rn.get("dx_max"), corr_dy_min=rn.get("dy_min"), corr_dy_max=rn.get("dy_max"),
                       sys_dx=rn.get("sys_dx"), sys_dy=rn.get("sys_dy"), total_unc=rn.get("total"))
            w.writerow({k: (f"{row[k]:.3f}" if isinstance(row.get(k), float) else ("" if row.get(k) is None else row.get(k))) for k in REGION_FIELDS})


def print_regions(regions):
    if not regions:
        print("  (未偵測到晶片矩形)")
        return
    print(f"  {'矩形':>4} {'父':>3} {'層':>2} {'bbox (x,y,w,h)':<24} {'對比':>4} {'主':>2} {'位點':>4} {'可用':>4} {'位移dx':>6} {'位移dy':>6} {'內點':>7} {'±se':>5} {'信心':>4}  舊判定")
    for rg in regions:
        sh = rg.get("shift") or {}
        bbox = f"({rg['x']},{rg['y']},{rg['w']}x{rg['h']})"
        print(f"  {'D%d' % rg['id']:>4} {('D%d' % rg['parent']) if rg['parent'] else '-':>3} {rg['level']:>2} {bbox:<24} {rg.get('contrast', 0):4.0f} "
              f"{'*' if rg.get('primary') else '':>2} {rg.get('n_sites', 0):>4} {rg.get('n_used', 0):>4} "
              f"{(('%+.2f' % sh['dx']) if sh else '-'):>6} {(('%+.2f' % sh['dy']) if sh else '-'):>6} "
              f"{(('%d/%d' % (sh['n_in'], sh['n_used'])) if sh else '-'):>7} {(('%.2f' % sh['se']) if sh else '-'):>5} {(sh.get('grade', '-') if sh else '-'):>4}  {rg.get('verdict', '')}")


def circle_rows(sites, px_um=None):
    """所有圓 (焊點 P#、凸塊 B#) 的尺寸列：半徑、直徑、面積 (px)，有 px_um 就多給 um"""
    rows = []
    for s in sites:
        for tag, c in (("P", s["pad"]), ("B", s["bump"])):
            if c is None:
                continue
            row = dict(oid=f"{tag}{s['id']}", site=s["id"], kind="pad" if tag == "P" else "bump", region=s.get("region", 0),
                       cluster=s.get("cluster", 0), type=s["kind"], x=round(c["x"], 2), y=round(c["y"], 2),
                       r_px=round(c["r"], 2), d_px=round(2 * c["r"], 2), area_px=round(np.pi * c["r"] ** 2, 1),
                       fit_rms=round(c["rms"], 2), edge_cov=round(c["cov"], 2),
                       used=int(bool(s.get("used"))), reject=s.get("reject", ""))
            if px_um:
                row.update(d_um=round(2 * c["r"] * px_um, 2), area_um2=round(np.pi * (c["r"] * px_um) ** 2, 1))
            rows.append(row)
    return rows


CIRCLE_FIELDS = ["oid", "site", "kind", "region", "cluster", "type", "x", "y", "r_px", "d_px", "area_px", "d_um", "area_um2",
                 "fit_rms", "edge_cov", "used", "reject"]


def write_circles_csv(sites, path, px_um=None):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CIRCLE_FIELDS)
        w.writeheader()
        for row in circle_rows(sites, px_um):
            w.writerow({k: row.get(k, "") for k in CIRCLE_FIELDS})


def size_summary(sites, regions):
    """每個矩形 (含 0 = 矩形外) 的焊點 / 凸塊直徑統計 (px)"""
    out = []
    ids = [0] + [rg["id"] for rg in regions]
    for rid in ids:
        cs = [s for s in sites if s.get("region", 0) == rid]
        if not cs:
            continue
        pd = np.array([2 * s["pad"]["r"] for s in cs])
        bd = np.array([2 * s["bump"]["r"] for s in cs if s["bump"]])
        bu = np.array([2 * s["bump"]["r"] for s in cs if s["bump"] and s.get("used")])
        out.append(dict(region=rid, n=len(cs), n_bump=len(bd), n_used=len(bu),
                        pad_d_med=float(np.median(pd)), pad_d_min=float(pd.min()), pad_d_max=float(pd.max()),
                        bump_d_med=float(np.median(bd)) if len(bd) else None,
                        bump_d_min=float(bd.min()) if len(bd) else None, bump_d_max=float(bd.max()) if len(bd) else None,
                        bump_d_used_med=float(np.median(bu)) if len(bu) else None,
                        bump_d_used_min=float(bu.min()) if len(bu) else None, bump_d_used_max=float(bu.max()) if len(bu) else None))
    return out


def print_sizes(sites, regions, print_all=False, px_um=None):
    f = lambda v: "-" if v is None else f"{v:.1f}"
    print(f"  {'矩形':>4} {'位點':>4} {'凸塊':>4} {'可用':>4} {'焊點直徑 中位(最小~最大)':<26} {'凸塊直徑 中位(最小~最大)':<26} {'可用凸塊直徑 中位(最小~最大)':<28}")
    for r in size_summary(sites, regions):
        print(f"  {('D%d' % r['region']) if r['region'] else '外':>4} {r['n']:>4} {r['n_bump']:>4} {r['n_used']:>4} "
              f"{f(r['pad_d_med']) + ' (' + f(r['pad_d_min']) + '~' + f(r['pad_d_max']) + ')':<26} "
              f"{f(r['bump_d_med']) + ' (' + f(r['bump_d_min']) + '~' + f(r['bump_d_max']) + ')':<26} "
              f"{f(r['bump_d_used_med']) + ' (' + f(r['bump_d_used_min']) + '~' + f(r['bump_d_used_max']) + ')':<28}")
    if print_all:
        print(f"  {'圓':>6} {'位點':>4} {'類別':<4} {'矩形':>4} {'x':>8} {'y':>8} {'r px':>6} {'d px':>6} {'面積px':>8} {'採用':>4}  排除原因")
        for row in circle_rows(sites, px_um):
            print(f"  {row['oid']:>6} {row['site']:>4} {row['kind']:<4} {('D%d' % row['region']) if row['region'] else '外':>4} "
                  f"{row['x']:8.2f} {row['y']:8.2f} {row['r_px']:6.2f} {row['d_px']:6.2f} {row['area_px']:8.1f} {'v' if row['used'] else '':>4}  {row['reject']}")


def shift_line(sh, px_um=None):
    if not sh:
        return "可用位點不足"
    txt = (f"凸塊相對焊點偏移 ({sh['dx']:+.2f}, {sh['dy']:+.2f}) px → 晶片需位移 ({sh['corr_dx']:+.2f}, {sh['corr_dy']:+.2f}) px"
           f"  內點 {sh['n_in']}/{sh['n_used']} ({sh['ratio']:.0%})  ±{sh['se']:.2f} px  信心 {sh['grade']}")
    if sh.get("rot_deg") is not None:
        txt += f"  旋轉 {sh['rot_deg']:+.3f} deg  縮放 {sh.get('scale_ppm', 0):+.0f} ppm (邊角差 {sh.get('edge_var', 0):.1f} px)"
    if sh.get("corr_um"):
        txt += f"  = ({sh['corr_um'][0]:+.1f}, {sh['corr_um'][1]:+.1f}) um"
    return txt


def range_line(rgn, variants):
    if not rgn:
        return "前處理敏感度: 變體估計不足"
    parts = []
    for name, sh in (variants or {}).items():
        parts.append(f"{name} ({sh['corr_dx']:+.2f},{sh['corr_dy']:+.2f}) n={sh['n_in']}" if sh else f"{name} -")
    return (f"前處理敏感度 ({rgn['n_variants']} 種去噪): dx {rgn['dx_min']:+.2f}~{rgn['dx_max']:+.2f}, dy {rgn['dy_min']:+.2f}~{rgn['dy_max']:+.2f}"
            f" → 系統 ±({rgn['sys_dx']:.2f}, {rgn['sys_dy']:.2f}) px，合併不確定度 ±{rgn['total']:.2f} px  [" + "; ".join(parts) + "]")


def print_shifts(res):
    print(f"  品質篩選後可用位點 {res['n_used']} / {len(res['sites'])}")
    if res["die_shifts"]:
        for rg in res["die_shifts"]:
            print(f"  晶片 D{rg['id']} ({rg['x']},{rg['y']},{rg['w']}x{rg['h']}): {shift_line(rg['shift'])}")
            if rg.get("shift_two"):
                print(f"      只用 two-level: {shift_line(rg['shift_two'])}")
            if rg.get("shift_variants") is not None:
                print(f"      {range_line(rg.get('shift_range'), rg.get('shift_variants'))}")
    else:
        print("  沒有主要晶片矩形達到最少可用位點數")
    print(f"  全圖 (所有可用位點): {shift_line(res['shift_all'])}")
    if res.get("variant_names"):
        print(f"      {range_line(res.get('shift_all_range'), res.get('shift_all_variants'))}")


def print_clusters(clusters):
    if not clusters:
        print("  (無可分群的位點)")
        return
    print(f"  {'群':>3} {'矩形':>4} {'位點':>4} {'兩層':>4} {'型態':<9} {'焊墊r':>5} {'pitch':>5} {'均dx':>6} {'均dy':>6} {'|均|':>5} "
          f"{'一致R':>5} {'t值':>5} {'旋轉deg':>7} {'RMS前/後':>9}  判定")
    for c in clusters:
        g = lambda k, f="{:.2f}": (f.format(c[k]) if k in c and c[k] == c[k] else "-")
        print(f"  {c['cluster']:>3} {'D%d' % c.get('region', 0):>4} {c['n']:>4} {c['n_two_level']:>4} {c['kind']:<9} {c['pad_r_median']:5.1f} {c['pitch_median']:5.0f} "
              f"{g('mean_dx'):>6} {g('mean_dy'):>6} {g('mean_mag'):>5} {g('coherence'):>5} {g('t_stat', '{:.1f}'):>5} "
              f"{g('rot_deg', '{:+.3f}'):>7} {g('rms_before'):>4}/{g('rms_after'):<4}  {c['verdict']}")


def print_table(sites, limit, print_all):
    two = [s for s in sites if s["kind"] == "two-level"]
    rows = two if print_all else sorted(two, key=lambda s: -s["d"])[:30]
    if not print_all:
        print(f"  偏移量最大的 {len(rows)} 顆 (完整列表見 CSV):")
    print(f"  {'id':>4} {'pad_x':>8} {'pad_y':>8} {'pad_r':>6} {'bump_x':>8} {'bump_y':>8} {'bump_r':>6} "
          f"{'dx':>6} {'dy':>6} {'|d|px':>6}  flag")
    for s in rows:
        p, b = s["pad"], s["bump"]
        flag = "NG" if s["d"] > limit else ""
        print(f"  {s['id']:>4} {p['x']:8.2f} {p['y']:8.2f} {p['r']:6.1f} {b['x']:8.2f} {b['y']:8.2f} {b['r']:6.1f} "
              f"{s['dx']:6.2f} {s['dy']:6.2f} {s['d']:6.2f}  {flag}")


def summarize(res, limit):
    sites = res["sites"]
    two = [s for s in sites if s["kind"] == "two-level"]
    single = [s for s in sites if s["kind"] == "single"]
    d = np.array([s["d"] for s in two]) if two else np.array([])
    out = dict(image=os.path.basename(res["path"]), candidates=res["n_cand"], sites=len(sites),
               two_level=len(two), single=len(single),
               offset_median=f"{np.median(d):.2f}" if len(d) else "",
               offset_p95=f"{np.percentile(d, 95):.2f}" if len(d) else "",
               offset_max=f"{d.max():.2f}" if len(d) else "",
               over_limit=int((d > limit).sum()) if len(d) else 0)
    cl = res.get("clusters", [])
    rgs = res.get("regions", [])
    ds = res.get("die_shifts", [])
    sa = res.get("shift_all")
    out.update(n_used=res.get("n_used", 0),
               die_shift="; ".join(f"D{rg['id']}: corr({rg['shift']['corr_dx']:+.2f}/{rg['shift']['corr_dy']:+.2f}) n={rg['shift']['n_in']} {rg['shift']['grade']}" for rg in ds),
               global_corr_dx=f"{sa['corr_dx']:+.2f}" if sa else "", global_corr_dy=f"{sa['corr_dy']:+.2f}" if sa else "",
               global_shift_grade=sa["grade"] if sa else "",
               die_regions=len(rgs),
               regions_shift="; ".join(f"D{r['id']}({r['mean_dx']:+.2f}/{r['mean_dy']:+.2f}){'*' if '低可信' in r['level_verdict'] else ''}"
                                       for r in rgs if r.get("level_verdict") in ("高", "中", "高(低可信)")),
               clusters=len(cl),
               clusters_shift_high=sum(c.get("level") == "高" for c in cl),
               clusters_shift_mid=sum(c.get("level") == "中" for c in cl),
               clusters_shift_lowconf=sum(c.get("level") == "高(低可信)" for c in cl),
               shift_clusters="; ".join(f"C{c['cluster']}({c['mean_dx']:+.2f}/{c['mean_dy']:+.2f}){'*' if '低可信' in c['level'] else ''}"
                                        for c in cl if c.get("level") in ("高", "中", "高(低可信)")))
    gt = res["gt"]
    if gt:
        out.update(global_tx=f"{gt['tx']:.2f}", global_ty=f"{gt['ty']:.2f}",
                   global_rot_deg=f"{gt['rot_deg']:.3f}", global_scale=f"{gt['scale']:.4f}",
                   resid_median=f"{gt['resid_median']:.2f}", resid_max=f"{gt['resid_max']:.2f}")
    else:
        out.update(global_tx="", global_ty="", global_rot_deg="", global_scale="", resid_median="", resid_max="")
    return out


def main():
    ap = argparse.ArgumentParser(description="Flip-chip X 光凸塊 / 焊墊偏移量測")
    ap.add_argument("src", help="影像檔或資料夾")
    ap.add_argument("--out", default=None, help="輸出資料夾 (預設: <src>/FlipChipShift_out)")
    ap.add_argument("--px-um", type=float, default=None, help="每像素微米數，給了就多算 offset_um")
    ap.add_argument("--limit", type=float, default=5.0, help="偏移門檻 px，超過在疊圖上標紅 (預設 5)")
    ap.add_argument("--print-all", action="store_true", help="在終端印出全部位點 (預設只印偏移最大的 30 顆)")
    ap.add_argument("--print-sizes", action="store_true", help="在終端印出所有圓的 px 尺寸表 (預設只印每個矩形的統計)")
    ap.add_argument("--no-variants", action="store_true", help="不做前處理敏感度 (省時間)")
    ap.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"), default=None, help="只分析這個矩形區域 (px)")
    ap.add_argument("--ext", default="tif,tiff,png,bmp,jpg", help="資料夾模式要處理的副檔名")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="特徵尺寸倍率 (預設 1 = 焊墊半徑約 13~32px)；影像放大倍率較高時例如給 1.8")
    ap.add_argument("--pad-r", type=float, nargs=2, metavar=("MIN", "MAX"), default=None,
                    help="直接指定焊墊半徑範圍 px (覆寫 --scale 後的值)")
    args = ap.parse_args()
    apply_scale(args.scale, args.pad_r)
    print(f"尺寸參數: 焊墊半徑 {P['pad_r'][0]:.0f}~{P['pad_r'][1]:.0f} px, 偵測中心半徑 {P['cs_r_in']:.0f} px, 大焊球遮罩 > {P['ball_open']} px")

    if os.path.isdir(args.src):
        exts = args.ext.split(",")
        files = sorted(f for f in glob.glob(os.path.join(args.src, "*")) if f.lower().rsplit(".", 1)[-1] in exts)
        out_dir = args.out or os.path.join(args.src, "FlipChipShift_out")
    else:
        files = [args.src]
        out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.src)), "FlipChipShift_out")
    if not files:
        print("找不到影像"); sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)

    summaries = []
    for path in files:
        name = os.path.splitext(os.path.basename(path))[0]
        print(f"\n===== {os.path.basename(path)} =====")
        res = process_image(path, args.px_um, variants=not args.no_variants, roi=args.roi)
        sites = res["sites"]
        vis = draw_overlay(res["den"], sites, args.limit, res["clusters"], res["regions"], res.get("roi"))
        cv2.imwrite(os.path.join(out_dir, f"{name}_overlay.png"), vis)
        cv2.imwrite(os.path.join(out_dir, f"{name}_overlay_half.png"),
                    cv2.resize(vis, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
        write_csv(sites, os.path.join(out_dir, f"{name}_sites.csv"))
        write_cluster_csv(res["clusters"], os.path.join(out_dir, f"{name}_clusters.csv"))
        write_region_csv(res["regions"], os.path.join(out_dir, f"{name}_regions.csv"))
        write_circles_csv(sites, os.path.join(out_dir, f"{name}_circles.csv"), args.px_um)

        sm = summarize(res, args.limit)
        summaries.append(sm)
        print(f"  候選 {sm['candidates']}  位點 {sm['sites']}  兩層(可量偏移) {sm['two_level']}  單圓 {sm['single']}")
        if sm["two_level"]:
            print(f"  偏移量 px: 中位 {sm['offset_median']}  P95 {sm['offset_p95']}  最大 {sm['offset_max']}  "
                  f"超過 {args.limit:g}px: {sm['over_limit']} 顆")
        if res["gt"]:
            g = res["gt"]
            print(f"  全域 (晶片 vs 基板): 平移 ({g['tx']:+.2f}, {g['ty']:+.2f}) px, 旋轉 {g['rot_deg']:+.3f} deg, "
                  f"縮放 {g['scale']:.4f}; 扣除全域後殘餘偏移 中位 {g['resid_median']:.2f} / 最大 {g['resid_max']:.2f} px")
        print(f"  分群 {sm['clusters']} 群，整體偏移判定 高 {sm['clusters_shift_high']} 群 / 中 {sm['clusters_shift_mid']} 群"
              f" / 低可信度疑似 {sm['clusters_shift_lowconf']} 群")
        print("  ---- 整體位移估計 (品質篩選 + 穩健內點平均) ----")
        print_shifts(res)
        print(f"  晶片矩形 {len(res['regions'])} 個 (* = 主要晶片；位移欄為篩選後位點的穩健估計):")
        print_regions(res["regions"])
        print_clusters(res["clusters"])
        if sm["two_level"]:
            print_table(sites, args.limit, args.print_all)
        print("  ---- 圓尺寸 (px) ----")
        print_sizes(sites, res["regions"], args.print_sizes, args.px_um)
        print(f"  -> {name}_overlay.png / {name}_sites.csv / {name}_clusters.csv / {name}_regions.csv / {name}_circles.csv")

    with open(os.path.join(out_dir, "summary.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summaries[0].keys()))
        w.writeheader()
        w.writerows(summaries)
    print(f"\n輸出資料夾: {out_dir}")


if __name__ == "__main__":
    main()
