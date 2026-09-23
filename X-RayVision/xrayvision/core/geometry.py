"""幾何工具：圓擬合、穩健擬合、相似變換與整體偏移估計"""
import numpy as np


def fit_circle(pts):
    """Kasa 代數最小平方圓擬合；回傳 (cx, cy, r) 或 None"""
    if len(pts) < 5:
        return None
    A = np.c_[2 * pts, np.ones(len(pts))]
    b = (pts ** 2).sum(1)
    s, *_ = np.linalg.lstsq(A, b, rcond=None)
    r2 = s[2] + s[0] ** 2 + s[1] ** 2
    return (float(s[0]), float(s[1]), float(np.sqrt(r2))) if r2 > 0 else None


def _circle_result(pts, fit, keep):
    res = np.hypot(pts[keep, 0] - fit[0], pts[keep, 1] - fit[1]) - fit[2]
    return dict(x=fit[0], y=fit[1], r=fit[2], rms=float(np.sqrt((res ** 2).mean())), n=int(keep.sum()))


def robust_circle(pts, trim_k=2.5, trim_min=0.6):
    """反覆修剪殘差 > trim_k·σ (σ 以 MAD 估計，下限 trim_min) 的點後擬合圓；回傳 dict 或 None"""
    keep = np.ones(len(pts), bool)
    for _ in range(6):
        fit = fit_circle(pts[keep])
        if fit is None:
            return None
        res = np.hypot(pts[:, 0] - fit[0], pts[:, 1] - fit[1]) - fit[2]
        mad = 1.4826 * np.median(np.abs(res[keep] - np.median(res[keep])))
        new = np.abs(res - np.median(res[keep])) <= max(trim_min, trim_k * mad)
        if new.sum() < 5 or np.array_equal(new, keep):
            break
        keep = new
    fit = fit_circle(pts[keep])
    return None if fit is None else _circle_result(pts, fit, keep)


def circular_runs(mask):
    """環狀布林陣列中每一段連續 True 的索引陣列清單"""
    n = len(mask)
    if mask.all():
        return [np.arange(n)]
    if not mask.any():
        return []
    start = int(np.argmin(mask))           # 從某個 False 開始走，跨越 0 的區段才不會被切斷
    runs, cur = [], []
    for k in range(1, n + 1):
        i = (start + k) % n
        if mask[i]:
            cur.append(i)
        elif cur:
            runs.append(np.array(cur, int))
            cur = []
    if cur:
        runs.append(np.array(cur, int))
    return runs


def longest_run(mask):
    """環狀布林陣列中最長的連續 True 區段 (索引陣列)"""
    runs = circular_runs(mask)
    return max(runs, key=len) if runs else np.zeros(0, int)


def narrow_trim_circle(pts, ok, max_deg, trim_k=2.5, trim_min=0.6):
    """
    環狀射線點的圓擬合：反覆找出殘差離群的連續區段，只剔除角寬 < max_deg 的區段
    (窄的離群段是走線或 via 接點；寬的離群弧是真實外形，保留)。回傳 dict 或 None
    """
    n = len(pts)
    keep = ok.copy()
    for _ in range(6):
        fit = fit_circle(pts[keep])
        if fit is None:
            return None
        res = np.hypot(pts[:, 0] - fit[0], pts[:, 1] - fit[1]) - fit[2]
        rk = res[keep]
        sig = max(trim_min / trim_k, 1.4826 * float(np.median(np.abs(rk - np.median(rk)))))
        bad = ok & (np.abs(res - np.median(rk)) > trim_k * sig)
        drop = np.zeros(n, bool)
        for run in circular_runs(bad):
            if len(run) * 360.0 / n < max_deg:
                drop[run] = True
        new = ok & ~drop
        if new.sum() < 5 or np.array_equal(new, keep):
            break
        keep = new
    fit = fit_circle(pts[keep])
    return None if fit is None else _circle_result(pts, fit, keep)


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


def ray_circle(ox, oy, th, circle):
    """由 (ox, oy) 沿角度 th 的射線與圓的外側交點距離；circle 為含 x, y, r 的 dict"""
    ux, uy = np.cos(th), np.sin(th)
    qx, qy = circle["x"] - ox, circle["y"] - oy
    proj = ux * qx + uy * qy
    perp2 = (qx * qx + qy * qy) - proj * proj
    return proj + np.sqrt(np.maximum(circle["r"] ** 2 - perp2, 0.0))


def similarity_lsq(src, dst):
    """Umeyama 相似變換：dst ≈ s·R·src + t；回傳 2x3 矩陣"""
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


def estimate_shift(src, dst, tol_min=0.5, tol_k=3.0):
    """
    穩健估計一組對應點的整體偏移 (src → dst)。
    以偏移向量中位數起始選內點，再對內點做相似變換 (平移＋旋轉＋縮放)，以殘差重選內點。
    回傳 dict：dx, dy (變換在內點中心處的平移)、rot_deg、scale_ppm、n、n_in、rms、se、cx、cy、inliers；
    少於 3 點時回傳 None。
    """
    n = len(src)
    if n < 3:
        return None
    v = dst - src
    res = np.hypot(*(v - np.median(v, 0)).T)
    tol = max(tol_min, tol_k * 1.4826 * np.median(res))
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
        tol = max(tol_min, tol_k * 1.4826 * np.median(res[inl]))
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
                n=n, n_in=n_in, rms=rms, se=float(rms / np.sqrt(max(n_in - 4, 1))),
                cx=float(c[0]), cy=float(c[1]), inliers=inl)
