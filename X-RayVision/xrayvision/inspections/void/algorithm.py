"""
空洞檢測演算法 (規則式)

流程 (規劃書 PLAN-002 第 3.2 節)：
  1. 尺度空間 LoG 偵測圓形焊點 (半徑範圍由配方設定)
  2. 逐顆擬合「無空洞時的預期外觀」：平面背景 + a·截頂球弦長輪廓 (含邊緣模糊) + 焊墊圓盤
     以穩健加權 (IRLS) 排除空洞與其他偏離像素；截頂比例與模糊寬度先以部分焊點擬合，
     取全影像中位數後固定 (同一張影像的焊點外形相同，避免大型中央空洞被「壓平輪廓」吸收)
  3. 殘差 ÷ 焊點中心吸收量 = 相對殘差；低於 -max(k·雜訊, 最小深度) 的區域為空洞 (遲滯延伸)
  4. 每顆焊點：空洞率、最大空洞、空洞數、估計誤差；影像層級彙整
所有門檻都相對於焊點自身的吸收量與局部雜訊，不使用絕對灰階。
"""
import math

import cv2
import numpy as np

DEFAULTS = dict(
    r_min=20.0,              # 焊點半徑搜尋範圍 (px)
    r_max=120.0,
    det_rel=0.25,            # 偵測門檻 = 此值 x 響應 99 百分位
    det_scales=16,
    fit_win=1.45,            # 擬合視窗半徑 / R
    fit_points=1200,         # 擬合取樣點數目標 (決定取樣間隔)
    shape_samples=16,
    refit_iters=3,
    pad_prevalence=0.6,
    method="rule",           # rule / model / both
    disagree_pct=3.0,        # both：規則式與模型的空洞率差異超過此值 (百分點) 列為需複判      # 此比例以上的焊點有焊墊時，視焊墊為產品固有結構 (找不到焊墊的焊點擴大估計誤差)
    als_neg_weight=0.15,     # 初始化用非對稱最小平方的負殘差權重           # 排除空洞後重新擬合的最多次數        # 估計外形 (截頂比例、模糊) 用的焊點數上限
    sigma_k=4.0,             # 空洞種子門檻：雜訊倍數
    min_depth=0.07,          # 空洞最小相對深度 (焊點中心吸收量的比例)；約對應直徑 11% 的球形空洞
    edge_sigma_ratio=1.3,    # 決定空洞邊界用的平滑尺度 = 此值 x 量得的邊緣模糊寬度 (px)，最小 1 px
    grow_frac=0.10,          # 遲滯延伸：延伸到局部峰值深度的此比例 (空洞邊緣深度依平方根陡降，再經模糊)
    min_diam_ratio=0.08,     # 最小空洞直徑 / 焊點直徑
    min_area_px=9,
    min_compactness=0.45,    # 內切圓半徑 / 等面積圓半徑 下限 (排除細長新月形)
    rim=0.10,                # 邊緣環帶 (半徑比例) 不列入空洞搜尋
    rim_touch=0.2,           # 空洞輪廓落在搜尋區外緣的比例超過此值視為貼邊
    rim_min_pct=2.0,
    rim_deep_ratio=0.6,      # 貼邊區域深度 ÷ 該處厚度 >= 此值視為「深」；兩個以上 → 複合結構
    rim_cut_ratio=0.8,       # 貼邊空洞深度 ÷ 該處厚度 >= 此值，且面積 >= rim_cut_pct 時視為輪廓不符
    rim_cut_pct=5.0,
    min_size_ratio=0.4,      # 深度 ÷ 同面積球形空洞應有深度 下限         # 貼邊空洞小於焊點面積此百分比時不計 (邊緣外形差異)
    max_fit_rms=0.12,        # 擬合殘差 (相對) 上限；超過視為外形不符
    min_contrast=6.0,        # 焊點中心吸收量 / 雜訊 下限
    border=1.05,             # 焊點外緣離影像邊 < 此值 x R 不量
    overlap=0.9,             # 與相鄰焊點中心距 < 此值 x (R1 + R2) 視為重疊，不量
)

_PROFILE_X = np.linspace(-3.0, 3.0, 1201)
_PROFILE_CACHE = {}


# ---------------------------------------------------------------------------
# 偵測
# ---------------------------------------------------------------------------
def _log(img, r):
    """尺度正規化的 LoG (亮圓為正)；r 為目標半徑"""
    s = r / math.sqrt(2)
    return -cv2.Laplacian(cv2.GaussianBlur(img, (0, 0), s), cv2.CV_32F, ksize=3) * s * s


def detect_balls(A, cfg):
    """LoG 尺度空間偵測亮圓 (吸收量高)；回傳 [(x, y, r, 響應[, "gap"])]，"gap" 為補漏候選"""
    ds = max(1, int(cfg["r_min"] // 10))
    small = cv2.resize(A, (A.shape[1] // ds, A.shape[0] // ds), interpolation=cv2.INTER_AREA) if ds > 1 else A
    radii = np.geomspace(cfg["r_min"] * 0.8, cfg["r_max"] * 1.2, cfg["det_scales"]) / ds
    best = np.full(small.shape, -np.inf, np.float32)
    arg = np.zeros(small.shape, np.float32)
    for r in radii:
        lap = _log(small, r)
        m = lap > best
        best[m] = lap[m]
        arg[m] = r
    k = max(3, int(cfg["r_min"] / ds)) | 1
    mx = cv2.dilate(best, np.ones((k, k), np.uint8))
    cands = []
    for y, x in np.argwhere((best >= mx - 1e-12) & (best > 0)):
        r = float(arg[y, x]) * ds
        if cfg["r_min"] <= r <= cfg["r_max"]:
            cands.append(((x + 0.5) * ds - 0.5, (y + 0.5) * ds - 0.5, r, float(best[y, x])))
    if not cands:
        return []
    top = np.percentile([c[3] for c in cands], 99)
    cands = [c for c in cands if c[3] > cfg["det_rel"] * top]
    # 由大到小合併：
    #  - 中心落在較大候選內 (1.2 倍半徑；LoG 對平頂焊球的半徑估計偏小)、半徑明顯較小
    #    → 焊球內部結構 (焊墊、被空洞切開的亮區)，捨棄；相鄰的真實焊點中心不會落在另一顆焊點內
    #  - 中心很近 → 同一物件，保留響應強者
    out = []
    for c in sorted(cands, key=lambda c: -c[2]):
        x, y, r, resp = c
        if any(math.hypot(x - b[0], y - b[1]) < 1.2 * b[2] and r < 0.6 * b[2] for b in out):
            continue
        near = [j for j, b in enumerate(out) if math.hypot(x - b[0], y - b[1]) < 0.8 * max(r, b[2])]
        if near:
            if resp > out[near[0]][3]:
                out[near[0]] = c
            continue
        out.append(c)
    # 補救：空洞大時焊球被切開，最強響應落在焊墊或殘餘亮區，焊球本身在「最佳尺度」圖上消失。
    # 明顯小於典型半徑的候選，改在典型尺度上找附近的峰值；響應夠強就換成典型大小的焊點
    if len(out) >= 3:
        r_typ = float(np.median([c[2] for c in out]))
        typ_resp = float(np.median([c[3] for c in out if c[2] >= 0.8 * r_typ] or [c[3] for c in out]))
        lap = None
        for j, c in enumerate(out):
            if c[2] >= 0.6 * r_typ:
                continue
            if lap is None:
                lap = _log(small, r_typ / ds)
            h = int(r_typ / ds)
            cx, cy = int(c[0] / ds), int(c[1] / ds)
            y0, x0 = max(cy - h, 0), max(cx - h, 0)
            w = lap[y0:cy + h + 1, x0:cx + h + 1]
            if not w.size:
                continue
            yy, xx = np.unravel_index(int(np.argmax(w)), w.shape)
            nx, ny = (xx + x0 + 0.5) * ds - 0.5, (yy + y0 + 0.5) * ds - 0.5
            if w[yy, xx] >= 0.5 * typ_resp and not any(
                    k != j and math.hypot(nx - o[0], ny - o[1]) < 1.2 * max(o[2], r_typ) for k, o in enumerate(out)):
                out[j] = (float(nx), float(ny), r_typ, float(w[yy, xx]))
        # 補漏：空洞很大時焊球被切碎，最佳尺度只剩小於搜尋下限的碎片而整顆消失 (最該判不合格的焊點)。
        # 在典型尺度上找附近沒有焊點的峰值，響應夠強就補成候選；若不是焊點，擬合會判為外形不符或對比不足，
        # 列入未量測 (判定需複判)，不會被默默略過
        if lap is None:
            lap = _log(small, r_typ / ds)
        k = max(3, int(0.8 * r_typ / ds)) | 1
        mx = cv2.dilate(lap, np.ones((k, k), np.uint8))
        for y, x in np.argwhere((lap >= mx - 1e-12) & (lap >= 0.5 * typ_resp)):
            nx, ny = (x + 0.5) * ds - 0.5, (y + 0.5) * ds - 0.5
            if not any(math.hypot(nx - o[0], ny - o[1]) < 1.2 * max(o[2], r_typ) for o in out):
                out.append((float(nx), float(ny), r_typ, float(lap[y, x]), "gap"))
    return out


# ---------------------------------------------------------------------------
# 外形模型
# ---------------------------------------------------------------------------
def profile(hc, wn):
    """截頂球弦長輪廓 (以 x = d/R 表示，中心為 1)，經寬度 wn (R 的比例) 的高斯模糊；回傳 (x, y, dy/dx) 查表"""
    key = (round(hc, 3), round(wn, 4))
    if key in _PROFILE_CACHE:
        return _PROFILE_CACHE[key]
    x = _PROFILE_X
    g = np.minimum(np.sqrt(np.clip(1 - x * x, 0, None)), hc) / hc
    step = x[1] - x[0]
    s = max(wn / step, 0.5)
    k = np.arange(-int(4 * s) - 1, int(4 * s) + 2)
    ker = np.exp(-0.5 * (k / s) ** 2)
    g = np.convolve(g, ker / ker.sum(), mode="same")
    tab = (x[600:], g[600:], np.gradient(g, step)[600:])
    if len(_PROFILE_CACHE) > 5000:
        _PROFILE_CACHE.clear()
    _PROFILE_CACHE[key] = tab
    return tab


# 焊墊圓盤以邏輯函數表示模糊邊緣：邏輯分布的標準差為 s·π/√3，
# 乘上 √3/π 使其與焊點輪廓的高斯模糊 (標準差 wn·R) 一致；否則邊緣過軟，焊墊外圍出現一圈負殘差
_PAD_EDGE = math.sqrt(3) / math.pi


def _disc(d, r, w):
    return 1.0 / (1.0 + np.exp(np.clip((d - r) / max(w, 0.3), -30, 30)))


class BallFit:
    """
    單顆焊點的擬合：A ≈ c0 + c1·u + c2·v + a·P(d/R) + p·Disc(焊墊)
    非線性參數 th = [cx, cy, R, hc, wn, (px, py, pr)]；線性係數以加權最小平方消去
    """

    def __init__(self, A, cx, cy, R, mask, cfg):
        H, W = A.shape
        h = int(math.ceil(cfg["fit_win"] * R))
        self.x0, self.x1 = max(int(round(cx)) - h, 0), min(int(round(cx)) + h + 1, W)
        self.y0, self.y1 = max(int(round(cy)) - h, 0), min(int(round(cy)) + h + 1, H)
        step = max(1, int(round(math.sqrt(math.pi) * cfg["fit_win"] * R / math.sqrt(cfg["fit_points"]))))
        self.step = step
        yy, xx = np.mgrid[self.y0:self.y1:step, self.x0:self.x1:step]
        sub = A[self.y0:self.y1:step, self.x0:self.x1:step]
        # mask：整張影像的布林陣列，或 fn(y0, y1, x0, x1) 只產生視窗內的遮罩 (避免每顆焊點複製整張影像)
        local = mask(self.y0, self.y1, self.x0, self.x1) if callable(mask) else mask[self.y0:self.y1, self.x0:self.x1]
        m = ((xx - cx) ** 2 + (yy - cy) ** 2 <= (cfg["fit_win"] * R) ** 2) & local[::step, ::step]
        self.x, self.y, self.v = xx[m].astype(np.float64), yy[m].astype(np.float64), sub[m].astype(np.float64)
        self.cx0, self.cy0, self.R0 = cx, cy, R
        self.w = np.ones_like(self.v)
        # 與模型無關的雜訊估計：視窗內相鄰像素差值的穩健標準差 / sqrt(2)
        win = A[self.y0:self.y1, self.x0:self.x1]
        dif = np.diff(win, axis=1).ravel()
        self.noise0 = float(1.4826 * np.median(np.abs(dif - np.median(dif))) / math.sqrt(2)) + 1e-9
        self.pad = False

    def design(self, th, x, y):
        cx, cy, R, hc, wn = th[:5]
        d = np.hypot(x - cx, y - cy)
        px, py, _ = profile(hc, wn)
        P = np.interp(d / R, px, py, right=0.0)
        u, v = (x - self.cx0) / self.R0, (y - self.cy0) / self.R0
        cols = [np.ones_like(u), u, v, P]
        if self.pad:
            ppx, ppy, pr = th[5:8]
            cols.append(_disc(np.hypot(x - ppx, y - ppy), pr, _PAD_EDGE * wn * R))
        return np.stack(cols, 1)

    def solve(self, th):
        """線性係數以加權正規方程求解 (欄數 ≤ 5，比 SVD 形式的最小平方快)"""
        B = self.design(th, self.x, self.y)
        Bw = B * self.w[:, None]
        G = Bw.T @ B
        G[np.diag_indices_from(G)] += 1e-9 * (np.trace(G) + 1)
        c = np.linalg.solve(G, Bw.T @ self.v)
        return self.v - B @ c, c

    def reweight(self, r):
        """
        非對稱穩健權重：負殘差 (可能是空洞) 在 2.5 倍雜訊外大幅降權；正殘差 (焊墊等吸收較高的結構)
        到 6 倍雜訊才降權，讓焊墊圓盤被推去涵蓋整個亮區，被空洞蓋住的部分則不影響擬合
        """
        # 雜訊尺度取自正殘差一側 (高斯雜訊的正側中位數 = 0.6745σ)：空洞只會讓吸收量變低，
        # 空洞面積很大 (數成以上) 時，以全部殘差的 MAD 估計會被墊高，負殘差降權不足，振幅被拉低
        pos = r[r > 0]
        if len(pos) > 30:
            s = float(np.median(pos)) / 0.6745 + 1e-9
        else:
            s = 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-9
        scale = np.where(r < 0, 2.5 * s, 6.0 * s)
        self.w = 1.0 / (1.0 + (r / scale) ** 4)
        return s

    def jacobian(self, th, c, free):
        """
        殘差對非線性參數的 Jacobian，線性係數視為固定 (J_k = -dB/dθ_k · c)：
        焊點中心與半徑由輪廓查表的導數解析計算；焊墊圓盤由邏輯函數導數計算；
        截頂比例與模糊只重算輪廓欄 (差分)，不重解整個擬合
        """
        x, y = self.x, self.y
        cx, cy, R, hc, wn = th[:5]
        dx, dy = x - cx, y - cy
        d = np.maximum(np.hypot(dx, dy), 1e-6)
        u = d / R
        tx, ty, tg = profile(hc, wn)
        gp = np.interp(u, tx, tg, right=0.0)
        a = c[3]
        J = np.empty((len(x), len(free)))
        for j, k in enumerate(free):
            if k == 0:
                J[:, j] = a * gp * dx / (d * R)            # -(dP/dcx)·a，dP/dcx = P'(u)·(-dx/d)/R
            elif k == 1:
                J[:, j] = a * gp * dy / (d * R)
            elif k == 2:
                J[:, j] = a * gp * u / R                   # dP/dR = -P'(u)·u/R
            elif k in (3, 4):
                h = 0.01 if k == 3 else 0.002
                t2 = list(th[:5])
                t2[k] += h
                ax, ay, _ = profile(t2[3], t2[4])
                P0 = np.interp(u, tx, profile(hc, wn)[1], right=0.0)
                J[:, j] = -a * (np.interp(u, ax, ay, right=0.0) - P0) / h
            else:
                ppx, ppy, pr = th[5:8]
                w = max(_PAD_EDGE * wn * R, 0.3)
                ex, ey = x - ppx, y - ppy
                dp = np.maximum(np.hypot(ex, ey), 1e-6)
                D = _disc(dp, pr, w)
                s = D * (1 - D) / w                        # dD/dpr；dD/ddp = -s
                p = c[4]
                if k == 5:
                    J[:, j] = -p * s * ex / dp             # dD/dpx = s·ex/dp
                elif k == 6:
                    J[:, j] = -p * s * ey / dp
                else:
                    J[:, j] = -p * s
        return J

    def fit(self, th0, free, iters=8):
        """Levenberg-Marquardt (解析 Jacobian)，只調整 free 指定的非線性參數"""
        th = np.array(th0, np.float64)
        lam = 1e-2
        r, c = self.solve(th)
        cost = float(np.sum(self.w * r * r))
        for _ in range(iters):
            J = self.jacobian(th, c, free)
            Jw = J * self.w[:, None]
            g = Jw.T @ r
            Hm = Jw.T @ J
            improved = False
            for _ in range(6):
                try:
                    delta = -np.linalg.solve(Hm + lam * np.diag(np.diag(Hm) + 1e-12), g)
                except np.linalg.LinAlgError:
                    break
                t2 = th.copy()
                t2[free] += delta
                t2 = self.clamp(t2)
                r2, c2 = self.solve(t2)
                c2cost = float(np.sum(self.w * r2 * r2))
                if c2cost < cost:
                    th, r, c, cost = t2, r2, c2, c2cost
                    lam *= 0.3
                    improved = True
                    break
                lam *= 5
            if not improved or np.max(np.abs(delta)) < 0.02:
                break
        return th, r, c

    def clamp(self, th):
        th[2] = np.clip(th[2], 0.6 * self.R0, 1.4 * self.R0)
        th[3] = np.clip(th[3], 0.2, 1.0)
        th[4] = np.clip(th[4], 0.003, 0.25)
        if len(th) > 5:
            th[7] = np.clip(th[7], 0.08 * th[2], 0.9 * th[2])
        return th


def fit_ball(A, mask, cand, cfg, shape=None, free_shape=False, init=None):
    """
    擬合一顆焊點。
      shape=(hc, wn)：固定外形只調位置與半徑；None：外形也一起擬合
      free_shape=True：以 shape 為初值，確定焊墊後才放開外形一起調整
      init：前一次的擬合結果 (含焊墊)；給定時直接由此出發，不再重新偵測焊墊
    回傳 dict 或 None (取樣不足)
    """
    cx, cy, R = cand[:3]
    bf = BallFit(A, cx, cy, R, mask, cfg)
    if len(bf.v) < 200:
        return None
    if init is not None:
        th = np.array(init["th"], np.float64)
        bf.pad = init["pad"]
        # 焊墊位置與半徑沿用前一次 (只調振幅)：空洞區被排除後，焊墊像素可能大半被遮掉而失去約束
        free = [0, 1, 2, 3, 4]
        th, r, c = bf.fit(th, free)
        s = bf.reweight(r)
        th, r, c = bf.fit(th, free)
        s = bf.reweight(r)
        return _result(bf, th, r, c, s)
    th = np.array([cx, cy, R, shape[0] if shape else 0.8, shape[1] if shape else 0.02])
    # 先以固定外形 (或未給外形時一起) 擬合並確定焊墊；free_shape 時最後才放開外形。
    # 若一開始就放開外形，焊墊亮斑會被「提高振幅、改變截頂比例」吸收，之後偵測不到焊墊，
    # 焊球其餘部分相對變低而被誤判為空洞
    base = [0, 1, 2] if shape else [0, 1, 2, 3, 4]
    # 先只用焊點邊緣 (0.55 R 以外) 定出中心、半徑與振幅：邊緣很少有空洞、也沒有焊墊，
    # 不會被內部的亮區 (焊墊) 或暗區 (空洞) 拉偏；偵測時的初始位置常偏向焊墊一側
    # 空洞貼近邊緣時也可能落在此區，逐次以非對稱穩健權重降低其影響
    rw = np.ones_like(bf.v)
    for _ in range(3):
        bf.w = (np.hypot(bf.x - th[0], bf.y - th[1]) > 0.55 * th[2]) * rw
        th, r, c = bf.fit(th, [0, 1, 2])
        bf.reweight(r)
        rw = bf.w
    bf.w = np.ones_like(bf.v)
    r = bf.v - bf.design(th, bf.x, bf.y) @ c
    # 焊墊以邊緣擬合模型的殘差找出，一開始就納入模型；
    # 否則下方的非對稱擬合會先把模型推向焊墊亮區，焊墊被吸收進振幅後就偵測不到
    pad = _pad_init(bf, th, c, A)
    if pad is not None:
        bf.pad = True
        th = np.concatenate([th, pad])
        base = base + [5, 6, 7]
        th, r, c = bf.fit(th, base)
    # 初始化：非對稱最小平方 (負殘差權重低) 把模型推向「無空洞的上緣」。空洞佔焊點一半左右時，
    # 等權重擬合得到的是平均值，振幅偏低；由偏低的模型出發，穩健加權會卡在錯誤的解
    # 第一輪讓模型上移；第二輪把明顯高於模型的正殘差 (焊墊等) 也降權，避免焊墊把模型拉高
    bf.w = np.where(r > 0, 1.0, cfg["als_neg_weight"])
    th, r, c = bf.fit(th, base)
    bf.w = np.where((r > 0) & (r < 3 * bf.noise0), 1.0, cfg["als_neg_weight"])
    th, r, c = bf.fit(th, base)
    bf.reweight(r)
    th, r, c = bf.fit(th, base)
    s = bf.reweight(r)
    # 備援：邊緣擬合時沒找到焊墊 (例如焊墊很淡)，改由穩健擬合後的正殘差再找一次
    if not bf.pad:
        pad = _pad_init(bf, th, c, A)
        if pad is not None:
            bf.pad = True
            th = np.concatenate([th, pad])
            base = base + [5, 6, 7]
            th, r, c = bf.fit(th, base)
            s = bf.reweight(r)
            th, r, c = bf.fit(th, base)
            s = bf.reweight(r)
    if bf.pad and c[4] <= 0:                           # 焊墊應使吸收量增加；否則不採用
        bf.pad = False
        th = th[:5]
        base = [k for k in base if k < 5]
        th, r, c = bf.fit(th, base)
        s = bf.reweight(r)
    if free_shape and shape:
        th, r, c = bf.fit(th, [0, 1, 2, 3, 4] + ([5, 6, 7] if bf.pad else []))
        s = bf.reweight(r)
    return _result(bf, th, r, c, s)


def _result(bf, th, r, c, s):
    # 雜訊與擬合殘差只用內點 (權重 > 0.5)：大空洞的殘差不應墊高雜訊估計 (否則對比被低估)
    inl = bf.w > 0.5
    rms = float(np.sqrt(np.mean(r[inl] ** 2))) if inl.any() else float("inf")
    if inl.sum() > 50:
        ri = r[inl]
        s = 1.4826 * float(np.median(np.abs(ri - np.median(ri)))) + 1e-9
    return dict(th=th, coef=c, pad=bf.pad, rms=rms, noise=s, amp=float(c[3]), fit=bf)


def _pad_init(bf, th, c, A):
    """
    焊墊圓盤初值：視窗內殘差 (相對於不含焊墊的模型) 以約 0.08 R 平滑後，取包含最高點、
    高於峰值一半的連通區；需明顯高於平滑後的雜訊，且面積至少焊點的 2%。
    回傳 [x, y, r] 或 None
    """
    cx, cy, R = th[:3]
    st = bf.step
    sub = A[bf.y0:bf.y1:st, bf.x0:bf.x1:st].astype(np.float64)
    yy, xx = np.mgrid[bf.y0:bf.y1:st, bf.x0:bf.x1:st]
    dist = np.hypot(xx - cx, yy - cy)
    res = sub - (bf.design(th[:5], xx.ravel().astype(np.float64), yy.ravel().astype(np.float64))[:, :4] @ c[:4]
                 ).reshape(sub.shape)
    amp = c[3]
    inside = dist < 0.9 * R
    if inside.sum() < 30:
        return None
    sm = cv2.GaussianBlur(res.astype(np.float32), (0, 0), max(1.0, 0.08 * R / st))
    vals = sm[inside]
    sig = 1.4826 * float(np.median(np.abs(vals - np.median(vals)))) + 1e-9
    base = float(np.median(vals))
    peak_i = np.argmax(np.where(inside, sm, -np.inf))
    py0, px0 = np.unravel_index(peak_i, sm.shape)
    peak = float(sm[py0, px0]) - base
    if peak < max(5 * sig, 0.03 * abs(amp)):
        return None
    reg = ((sm - base > 0.5 * peak) & inside).astype(np.uint8)
    n, lab = cv2.connectedComponents(reg)
    comp = lab == lab[py0, px0]
    area = float(comp.sum()) * st * st
    if area < 0.02 * math.pi * R * R:
        return None
    return np.array([float(xx[comp].mean()), float(yy[comp].mean()), math.sqrt(area / math.pi)])


def model_image(fr, x0, y0, x1, y1):
    """在指定範圍內以全解析度計算擬合模型 (不含空洞)"""
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float64)
    B = fr["fit"].design(fr["th"], xx.ravel(), yy.ravel())
    return (B @ fr["coef"]).reshape(yy.shape)


# ---------------------------------------------------------------------------
# 空洞分割
# ---------------------------------------------------------------------------
def find_voids(A, fr, cfg):
    """回傳 (空洞清單 [dict(contour, area_px2, depth, cx, cy)], 相對雜訊, 空洞總面積)"""
    cx, cy, R = fr["th"][:3]
    amp = fr["amp"]
    h = int(math.ceil(R)) + 2
    H, W = A.shape
    x0, x1 = max(int(cx) - h, 0), min(int(cx) + h + 1, W)
    y0, y1 = max(int(cy) - h, 0), min(int(cy) + h + 1, H)
    rel = (A[y0:y1, x0:x1].astype(np.float64) - model_image(fr, x0, y0, x1, y1)) / amp
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d = np.hypot(xx - cx, yy - cy)
    zone = d < (1 - cfg["rim"]) * R
    # 平滑尺度依焊點大小；雜訊以平滑後相對殘差的穩健標準差估計 (兩次排除明顯偏離的像素)
    ss = max(1.0, 0.04 * R)
    sm = cv2.GaussianBlur(rel.astype(np.float32), (0, 0), ss).astype(np.float64)
    vals = sm[zone]
    sig = 1.4826 * np.median(np.abs(vals - np.median(vals))) + 1e-9
    core = vals[np.abs(vals - np.median(vals)) < 3 * sig]
    if len(core) > 50:
        sig = 1.4826 * np.median(np.abs(core - np.median(core))) + 1e-9
    seed_thr = max(cfg["sigma_k"] * sig, cfg["min_depth"])
    low_thr = max(2.0 * sig, 0.5 * cfg["min_depth"])
    low = ((sm < -low_thr) & zone).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(low, connectivity=8)
    min_area = max(cfg["min_area_px"], math.pi * (cfg["min_diam_ratio"] * R) ** 2)
    # 邊界平滑依影像本身的模糊寬度：空洞邊緣很薄、又經模糊，平滑到與模糊相當的尺度時，
    # 低門檻的輪廓才會落在真正邊界附近，雜訊下限也較低
    blur_px = fr["th"][4] * R
    rel_s1 = cv2.GaussianBlur(rel.astype(np.float32), (0, 0), max(1.0, cfg["edge_sigma_ratio"] * blur_px))
    v1 = rel_s1[zone]
    sig1 = 1.4826 * np.median(np.abs(v1 - np.median(v1))) + 1e-9
    # 空洞邊界：輕度平滑的相對殘差低於「局部峰值深度 x grow_frac」與「2.5 倍雜訊」中較深者。
    # 局部峰值取鄰近 (空洞半徑尺度) 的最深值，相連的大小空洞各自以自己的深度決定邊界
    # 在縮小 4 倍的影像上侵蝕再放大 (大核侵蝕很耗時；局部峰值只需粗略位置)
    q = 4
    small_sm = cv2.resize(sm.astype(np.float32), (max(1, sm.shape[1] // q), max(1, sm.shape[0] // q)),
                          interpolation=cv2.INTER_AREA)
    k = 2 * max(1, int(0.25 * R / q)) + 1
    local_peak = cv2.resize(cv2.erode(small_sm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))),
                            (sm.shape[1], sm.shape[0]), interpolation=cv2.INTER_LINEAR)
    union = np.zeros(low.shape, np.uint8)
    for i in range(1, n):
        comp = lab == i
        if float(sm[comp].min()) > -seed_thr:
            continue
        thr = np.minimum(cfg["grow_frac"] * local_peak, -2.5 * sig1)
        reg = comp & (rel_s1 < thr)
        union |= reg.astype(np.uint8)
    # 空洞是實心團塊：填補被包圍的孔洞 (空洞蓋住焊墊時，焊墊會抵消部分深度而形成環狀)
    union = cv2.morphologyEx(union, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cs, _ = cv2.findContours(union, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(union)
    cv2.drawContours(filled, cs, -1, 1, -1)
    filled &= zone.astype(np.uint8)
    voids = []
    total = 0.0
    n, lab, stats, cent = cv2.connectedComponentsWithStats(filled, connectivity=8)
    for i in range(1, n):
        area = float(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        reg = (lab == i).astype(np.uint8)
        # 空洞是氣泡，投影為圓潤的團塊；沿焊點邊緣的細長新月形 (外形與模型的差異) 不是空洞
        r_in = float(cv2.distanceTransform(np.pad(reg, 1), cv2.DIST_L2, 3).max())
        if r_in < cfg["min_compactness"] * math.sqrt(area / math.pi):
            continue
        cs, _ = cv2.findContours(reg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cs, key=cv2.contourArea)
        pts = c[:, 0, :] + [x0, y0]
        # 貼邊：輪廓有多少比例落在搜尋區外緣 (被截平)
        dd = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
        rim_touch = float(np.mean(dd >= (1 - cfg["rim"]) * R - 1.5))
        # 物理合理性：
        #  thick_ratio：深度 ÷ 該處焊料厚度 (模型輪廓值)；空洞是封閉氣泡，不可能挖穿整個厚度
        #  size_ratio：深度 ÷ 同面積球形空洞應有的深度 (弦長 2·r_eq 相對於中心厚度 2·hc·R)
        depth = float(-sm[reg > 0].min())
        mx, my = float(cent[i][0]) + x0, float(cent[i][1]) + y0
        tx, ty, _ = profile(fr["th"][3], fr["th"][4])
        g_local = float(np.interp(math.hypot(mx - cx, my - cy) / R, tx, ty, right=0.0)) + 1e-6
        r_eq = math.sqrt(area / math.pi)
        expect = min(g_local, r_eq / (fr["th"][3] * R))
        voids.append(dict(contour=pts.astype(float).tolist(), area_px2=area, rim=rim_touch > cfg["rim_touch"],
                          thick_ratio=depth / g_local, size_ratio=depth / max(expect, 1e-6),
                          depth=float(-sm[reg > 0].min()), perimeter_px=cv2.arcLength(c, True),
                          cx=float(cent[i][0]) + x0, cy=float(cent[i][1]) + y0))
        total += area
    return voids, sig, total


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def analyze(A, cfg, in_region=None, model=None, gpu=False):
    """
    in_region(x, y)：檢測區域判斷，中心在區域外的焊點不量測、不列入未量測 (None 為整張)
    model：深度學習模型 dict(path, meta)；cfg["method"] 為 model 或 both 時使用 (焊點位置沿用規則式擬合)
    """
    A = A.astype(np.float32)
    H, W = A.shape
    cands = detect_balls(A, cfg)
    if in_region is not None:
        cands = [c for c in cands if in_region(c[0], c[1])]
    out = dict(balls=[], rejected=[], rejects={}, metrics={}, n_cand=len(cands), shape=None)
    if not cands:
        out["metrics"] = dict(balls_found=0)
        return out

    def reject(c, reason):
        out["rejected"].append(dict(x=c[0], y=c[1], r=c[2], reason=reason))
        out["rejects"][reason] = out["rejects"].get(reason, 0) + 1

    usable = []
    for i, c in enumerate(cands):
        x, y, r = c[:3]
        if x < cfg["border"] * r or y < cfg["border"] * r or x > W - cfg["border"] * r or y > H - cfg["border"] * r:
            reject(c, "border")
            continue
        if any(j != i and math.hypot(x - o[0], y - o[1]) < cfg["overlap"] * (r + o[2]) for j, o in enumerate(cands)):
            reject(c, "overlap")
            continue
        usable.append((i, c))
    # 相鄰焊點遮罩：擬合視窗內排除其他焊點 (外擴 15%)；只在視窗內產生
    cxy = np.array([[c[0], c[1], c[2] * 1.15] for c in cands])

    def own_mask(i, voids=(), grow=0):
        def fn(y0, y1, x0, x1):
            m = np.ones((y1 - y0, x1 - x0), np.uint8)
            near = np.nonzero((cxy[:, 0] + cxy[:, 2] > x0) & (cxy[:, 0] - cxy[:, 2] < x1) &
                              (cxy[:, 1] + cxy[:, 2] > y0) & (cxy[:, 1] - cxy[:, 2] < y1))[0]
            for j in near:
                if j != i:
                    cv2.circle(m, (int(round(cxy[j, 0])) - x0, int(round(cxy[j, 1])) - y0), int(round(cxy[j, 2])), 0, -1)
            for v in voids:
                pts = (np.array(v["contour"], np.int32) - [x0, y0]).reshape(-1, 1, 2)
                cv2.fillPoly(m, [pts], 0)
                cv2.polylines(m, [pts], True, 0, thickness=2 * grow + 1)
            return m.astype(bool)
        return fn

    # 1. 外形 (截頂比例、模糊寬度)：取響應最強的部分焊點擬合，取中位數
    shape_fits = []
    for i, c in sorted(usable, key=lambda ic: -ic[1][3])[: cfg["shape_samples"]]:
        fr = fit_ball(A, own_mask(i), c, cfg, shape=(0.8, 0.02), free_shape=True)
        if fr and fr["amp"] > 0:
            shape_fits.append(fr["th"][3:5])
    if not shape_fits:
        out["metrics"] = dict(balls_found=0)
        return out
    hc, wn = (float(v) for v in np.median(np.array(shape_fits), 0))
    out["shape"] = dict(truncation=hc, blur_ratio=wn)

    # 2. 逐顆以共同外形擬合並分割空洞；補漏候選最後處理，需像個焊點才計入
    #    (擬合成功、外形與對比合格、振幅不低於一般焊點中位數的一半)，否則視為非焊點
    usable = sorted(usable, key=lambda ic: len(ic[1]) > 4)
    amps = []
    for i, c in usable:
        gap = len(c) > 4
        fr = fit_ball(A, own_mask(i), c, cfg, shape=(hc, wn))
        if fr is None or fr["amp"] <= 0:
            reject(c, "not_ball" if gap else "fit_failed")
            continue
        if gap and (not amps or fr["amp"] < 0.5 * float(np.median(amps))):
            reject(c, "not_ball")
            continue
        voids, sig, total = find_voids(A, fr, cfg)
        # 找到空洞時：排除空洞區 (外擴模糊寬度) 重新擬合，外形 (截頂比例、模糊) 逐顆自由調整，再分割；
        # 空洞面積穩定為止 (空洞很多時，第一次的振幅會被拉低，需要多次)：
        #  - 背景與振幅不再被空洞拉低
        #  - 同一張影像有不同結構時，不會套用到別種結構的外形
        #  空洞區已排除，大型中央空洞不會被「壓平輪廓」吸收
        for _ in range(cfg["refit_iters"] if voids else 0):
            grow = max(2, int(round(2 * fr["th"][4] * fr["th"][2])))
            fr2 = fit_ball(A, own_mask(i, voids, grow), fr["th"][:3], cfg, init=fr)
            if fr2 is None or fr2["amp"] <= 0:
                break
            fr = fr2
            v2, sig, t2 = find_voids(A, fr, cfg)
            stable = abs(t2 - total) < 0.01 * math.pi * fr["th"][2] ** 2
            voids, total = v2, t2
            if stable or not voids:
                break
        cx, cy, R = (float(v) for v in fr["th"][:3])
        amp = fr["amp"]
        rel_rms = fr["rms"] / amp
        contrast = amp / (fr["noise"] + 1e-9)
        reason = ""
        if contrast < cfg["min_contrast"]:
            reason = "low_contrast"
        elif rel_rms > cfg["max_fit_rms"]:
            reason = "shape_mismatch"
        if gap and reason:
            reject(c, "not_ball")
            continue
        if not gap and not reason:
            amps.append(amp)
        if reason:
            voids, sig, total = [], 0.0, 0.0
        # 兩個以上又深 (接近該處厚度) 的「空洞」貼著外緣被截平：多半是複合結構 (凸塊與多個焊墊重疊)
        # 在亮瓣之間的間隙 (真實空洞貼近邊緣時仍留有焊料外殼，深度遠小於該處厚度)，
        # 不是空洞；此焊點不量測 (判定時列入未量測焊點，不會被略過)
        # 貼邊且深度接近該處全部厚度的大區域：焊點實際輪廓與模型不符 (封閉氣泡在邊緣仍留有焊料外殼，
        # 不會大面積挖穿)，同樣不量測
        big_cut = any(v["rim"] and v["thick_ratio"] >= cfg["rim_cut_ratio"] and
                      v["area_px2"] >= cfg["rim_cut_pct"] / 100 * math.pi * R * R for v in voids)
        if sum(v["rim"] and v["thick_ratio"] >= cfg["rim_deep_ratio"] for v in voids) >= 2 or big_cut:
            reason = "shape_mismatch"
            voids, sig, total = [], 0.0, 0.0
        # 深度遠淺於同大小球形氣泡應有深度的寬淺凹陷：外形差異，不是空洞
        shallow = [v for v in voids if v["size_ratio"] < cfg["min_size_ratio"]]
        if shallow:
            voids = [v for v in voids if v not in shallow]
            total -= sum(v["area_px2"] for v in shallow)
        # 單一貼邊的小區域 (< rim_min_pct) 是邊緣外形差異，不計為空洞
        small_rim = [v for v in voids if v["rim"] and v["area_px2"] < cfg["rim_min_pct"] / 100 * math.pi * R * R]
        if small_rim:
            voids = [v for v in voids if v not in small_rim]
            total -= sum(v["area_px2"] for v in small_rim)
        area = math.pi * R * R
        void_pct = 100.0 * total / area
        largest = max((v["area_px2"] for v in voids), default=0.0)
        perim = sum(v["perimeter_px"] for v in voids)
        out["balls"].append(dict(
            x=cx, y=cy, r=R, amp=amp, rms=rel_rms, contrast=contrast, noise_rel=sig, used=not reason, reason=reason,
            voids=voids, void_pct=void_pct, largest_void_pct=100.0 * largest / area, void_count=len(voids),
            void_area_px2=total, ball_area_px2=area,
            # 估計誤差：輪廓位置 ±0.5 px 造成的面積變化
            void_pct_se=100.0 * 0.5 * perim / area,
            # 可偵測的最小空洞：中心深度 ≈ 空洞半徑 / 焊點半徑，需超過種子門檻
            min_detectable_pct=100.0 * max(cfg["sigma_k"] * sig, cfg["min_depth"]) ** 2 if sig else None,
            pad=([float(v) for v in fr["th"][5:8]] if fr["pad"] else None)))
    used = [b for b in out["balls"] if b["used"]]
    method = cfg.get("method", "rule")
    if method != "rule" and model is not None and used:
        _apply_model(A, used, model, gpu, cfg, method)
    # 焊墊可能被空洞蓋住 (無法由影像還原的量測極限)，以擴大估計誤差處理：
    # 同一張影像多數焊點都偵測到焊墊 (產品固有結構) 時，有空洞卻找不到焊墊的焊點，
    # 其焊墊很可能被空洞遮住而抵消部分深度 (無法由影像還原)；把焊墊面積的一半計入估計誤差，
    # 使接近規格者列為需複判，而不是判為合格
    with_pad = [b for b in used if b["pad"]]
    if used and len(with_pad) >= cfg["pad_prevalence"] * len(used):
        pr_ratio = float(np.median([b["pad"][2] / b["r"] for b in with_pad]))
        for b in used:
            if b["void_count"] and not b["pad"]:
                b["pad_hidden"] = True
                b["void_pct_se"] += 100.0 * 0.5 * pr_ratio ** 2
    # 空洞與偵測到的焊墊相接或重疊：被遮住那側的焊墊邊緣看不到，焊墊擬合偏小，重疊區的空洞深度被部分抵消
    for b in used:
        if b["pad"] and b["void_count"]:
            px_, py_, pr = b["pad"]
            touch = False
            for v in b["voids"]:
                c = np.array(v["contour"], np.float32)
                if np.min(np.hypot(c[:, 0] - px_, c[:, 1] - py_)) < pr + 3 or                         cv2.pointPolygonTest(c.reshape(-1, 1, 2), (float(px_), float(py_)), False) >= 0:
                    touch = True
                    break
            if touch:
                b["pad_hidden"] = True
                b["void_pct_se"] += 100.0 * 0.5 * (pr / b["r"]) ** 2
    out["metrics"] = quality_metrics(out["balls"], used)
    return out


def quality_metrics(balls, used):
    m = dict(balls_found=len(used), measurable_ratio=(len(used) / len(balls)) if balls else 0.0)
    if used:
        m["fit_rms"] = float(np.median([b["rms"] for b in used]))
        m["contrast"] = float(np.median([b["contrast"] for b in used]))
        m["min_detectable_pct"] = float(np.median([b["min_detectable_pct"] for b in used]))
    return m


def _apply_model(A, used, model, gpu, cfg, method):
    """
    深度學習分割：method=model 時以模型結果為準；method=both 時兩者都算，
    差異超過 disagree_pct 標記 (判定需複判)，並採用空洞率較大者 (保守)
    """
    from . import model_seg
    res = model_seg.segment(A, [dict(x=b["x"], y=b["y"], r=b["r"]) for b in used], model, gpu, cfg)
    for b, (mv, mt) in zip(used, res):
        area = math.pi * b["r"] ** 2
        mp = 100.0 * mt / area
        b["void_pct_rule"], b["void_pct_model"] = b["void_pct"], mp
        take = method == "model" or mp > b["void_pct"]
        if method == "both":
            b["model_disagree"] = abs(mp - b["void_pct"]) > cfg["disagree_pct"]
        if take:
            b["voids"] = mv
            b["void_pct"] = mp
            b["void_area_px2"] = mt
            b["void_count"] = len(mv)
            b["largest_void_pct"] = 100.0 * max((v["area_px2"] for v in mv), default=0.0) / area
            b["void_pct_se"] = 100.0 * 0.5 * sum(v["perimeter_px"] for v in mv) / area

