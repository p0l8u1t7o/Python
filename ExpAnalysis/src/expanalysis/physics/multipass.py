"""多次 pass 區域熔煉離散模擬。

為什麼需要數值模擬
------------------
Pfann 解析解只適用於「輸入為均勻 C0」的第一次 pass。第二次 pass 的輸入
是第一次的輸出曲線，不再均勻，沒有封閉解。所以多次 pass 只能一步步算。

離散化方式
----------
把錠切成 N 個等寬單元（cell），寬度 h = L / N；熔區佔 m = round(l/h) 個
單元。掃描時每前進一格：右緣熔化一格固體進入液池、左緣凝固一格離開液池。

單格更新用**解析積分**而非前向 Euler
------------------------------------
連續形式的質量守恆是

    l * dC_L/dx = C_in(x + l) - k * C_L(x)

在單一 cell 內把熔入濃度 C_in 視為常數，這條 ODE 有解析解：

    C_L(h) = C_in/k + (C_L(0) - C_in/k) * exp(-k*h/l)

該格凝固出的溶質量 = C_in*h - l*(C_L(h) - C_L(0))，除以 h 得到**該格的平均
濃度**——這正好對應實際取樣時切一片下來測到的值。

好處：對均勻輸入時與 Pfann 解析解逐點吻合（誤差僅來自 cell 平均 vs 點值），
不會像前向 Euler 那樣隨 N 變小而系統性偏移。tests/test_physics.py 有驗證。

終端凝固段
----------
掃到尾端後，剩下的一個熔區長度沒有新固體可熔，改為正常凝固（Scheil）。
若沿用主掃描的更新式，最後一格會殘留 (1-k)*S 的溶質造成質量不守恆。
本模組改用 Scheil 的**格內積分平均**：

    C_j = m * C_L0 * [ (1 - j/m)^k - (1 - (j+1)/m)^k ]

對 j 求和恰好等於 m * C_L0，質量嚴格守恆（tests 有驗證到 1e-12）。

陣列形狀約定
------------
所有函式支援對「元素」維度批次運算：
    C: (..., N) float64 濃度 [ppm]
    k: (...,)   float64 有效分配係數
如此可一次算完 Cu/Fe/Ni/Sn 四個元素，比逐元素迴圈快約 4 倍。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .pfann import clip_k

# 預設離散化格數。300 對 8~12 點取樣的批次已遠超需求；
# 網格掃描等大量重複模擬時可調低至 120 以換取速度。
DEFAULT_N_CELLS = 300


@dataclass
class ZoneRefiningResult:
    """多次 pass 模擬結果。"""

    x_norm: np.ndarray             # (N,) cell 中心的歸一化位置 x/L ∈ (0,1)
    profiles: np.ndarray           # (n_pass+1, ..., N) 每次 pass 後的濃度，index 0 為進料
    k: np.ndarray                  # (...,) 使用的 k_eff
    zone_len_frac: float           # l / L
    n_passes: int
    mass_error: float = 0.0        # 相對質量守恆誤差，健檢用
    meta: dict = field(default_factory=dict)

    @property
    def final(self) -> np.ndarray:
        """(..., N) 最終 pass 後的濃度分布。"""
        return self.profiles[-1]

    def profile_at(self, n_pass: int) -> np.ndarray:
        """取第 n_pass 次 pass 後的分布（n_pass=0 為進料）。"""
        if not 0 <= n_pass < self.profiles.shape[0]:
            raise IndexError(f"n_pass 需在 0..{self.profiles.shape[0]-1}")
        return self.profiles[n_pass]


def _simulate_one_pass_array(
    c_in: np.ndarray,
    k: np.ndarray,
    m: int,
) -> np.ndarray:
    """單次 pass 核心（內部用，形狀嚴格固定，不做廣播猜測）。

    Args:
        c_in: (E, N) float64 進入本次 pass 前的固體濃度 [ppm]。
        k:    (E,)   float64 有效分配係數，呼叫端須先夾到安全範圍。
        m:    熔區佔的 cell 數，1 <= m < N。

    Returns:
        (E, N) float64 本次 pass 後的固體濃度 [ppm]。
    """
    if c_in.ndim != 2:
        raise ValueError(f"c_in 需為 (E, N) 二維陣列，收到 shape={c_in.shape}")
    if k.ndim != 1 or k.shape[0] != c_in.shape[0]:
        raise ValueError(f"k 需為 (E,) 且與 c_in 第一維相符，收到 {k.shape} vs {c_in.shape}")

    n = c_in.shape[-1]
    c_out = np.empty_like(c_in)

    h_over_l = 1.0 / m                       # h / l = (L/N) / (m*L/N)
    decay = np.exp(-k * h_over_l)            # (E,) exp(-k*h/l)

    # 初始液池：頭端 m 格熔化，液池平均濃度
    c_liq = c_in[:, :m].mean(axis=1)         # (E,)

    # ── 主掃描：左緣凝固 cell i、右緣熔入 cell i+m ──────────────
    for i in range(n - m):
        c_melt = c_in[:, i + m]              # (E,)
        c_star = c_melt / k                  # 該格對應的穩態液濃度
        c_liq_new = c_star + (c_liq - c_star) * decay
        # 凝固出的溶質量（以 cell 體積為單位）：熔入量 - 液池增量；l/h = m
        c_out[:, i] = c_melt - m * (c_liq_new - c_liq)
        c_liq = c_liq_new

    # ── 終端凝固：剩下 m 格，用 Scheil 的格內積分平均 ─────────────
    j = np.arange(m, dtype=np.float64)                       # (m,)
    kk = k[:, None]                                          # (E,1)
    left = np.power(1.0 - j / m, kk)                         # (E,m)
    right = np.power(np.maximum(1.0 - (j + 1.0) / m, 0.0), kk)
    c_out[:, n - m:] = m * c_liq[:, None] * (left - right)

    return c_out


def simulate_single_pass(
    c_in: np.ndarray,
    k: float | np.ndarray,
    zone_len_frac: float,
    n_cells: int | None = None,
) -> np.ndarray:
    """對外的單次 pass 介面。

    Args:
        c_in: (N,) 或 (E, N) 進料濃度 [ppm]。
        k: 純量或 (E,)。
        zone_len_frac: l / L ∈ (0, 1)。
        n_cells: 僅用於換算熔區格數；預設取 c_in 的長度。

    Returns:
        與 c_in 同形狀的濃度陣列。
    """
    c_arr = np.asarray(c_in, dtype=np.float64)
    squeeze = c_arr.ndim == 1
    c2 = c_arr[None, :] if squeeze else c_arr

    n = c2.shape[-1] if n_cells is None else n_cells
    m = max(1, min(n - 1, int(round(zone_len_frac * n))))

    k2 = np.atleast_1d(np.asarray(clip_k(k), dtype=np.float64))
    if k2.shape[0] == 1 and c2.shape[0] > 1:
        k2 = np.repeat(k2, c2.shape[0])

    out = _simulate_one_pass_array(c2, k2, m)
    return out[0] if squeeze else out


def simulate_passes(
    k: float | np.ndarray,
    zone_len_frac: float,
    n_passes: int,
    c0: float | np.ndarray = 1.0,
    n_cells: int = DEFAULT_N_CELLS,
    keep_all: bool = True,
) -> ZoneRefiningResult:
    """從均勻進料開始，模擬 n_passes 次 pass。

    Args:
        k: 純量或 (E,) 陣列（多元素一次算完）。
        zone_len_frac: 熔區長度佔錠長的比例 l/L，典型 0.05 ~ 0.15。
        n_passes: 純化次數，>= 0。0 表示直接回傳進料。
        c0: 純量或 (E,) 初始濃度 [ppm]。
        n_cells: 離散格數。
        keep_all: True 保留每次 pass 的分布（UI 要畫「第幾次 pass」滑桿需要）。

    Returns:
        ZoneRefiningResult
    """
    if not 0.0 < zone_len_frac < 1.0:
        raise ValueError(f"zone_len_frac 需在 (0,1)，收到 {zone_len_frac}")
    if n_passes < 0:
        raise ValueError("n_passes 不可為負")

    k_arr = np.atleast_1d(np.asarray(clip_k(k), dtype=np.float64))
    c0_arr = np.broadcast_to(np.atleast_1d(np.asarray(c0, dtype=np.float64)), k_arr.shape)
    scalar_in = np.ndim(k) == 0

    m = max(1, min(n_cells - 1, int(round(zone_len_frac * n_cells))))
    c = np.repeat(c0_arr[:, None], n_cells, axis=1)      # (E, N)

    mass0 = c.sum(axis=-1)
    profiles = [c.copy()]

    for _ in range(n_passes):
        c = _simulate_one_pass_array(c, k_arr, m)
        if keep_all:
            profiles.append(c.copy())
    if not keep_all:
        profiles.append(c.copy())

    mass_err = float(np.max(np.abs(c.sum(axis=-1) - mass0) / np.maximum(mass0, 1e-30))) if n_passes else 0.0

    prof = np.stack(profiles, axis=0)                     # (P+1, E, N)
    if scalar_in:
        prof = prof[:, 0, :]
        k_out = k_arr[0]
    else:
        k_out = k_arr

    x_norm = (np.arange(n_cells, dtype=np.float64) + 0.5) / n_cells

    return ZoneRefiningResult(
        x_norm=x_norm,
        profiles=prof,
        k=np.asarray(k_out),
        zone_len_frac=m / n_cells,
        n_passes=n_passes,
        mass_error=mass_err,
        meta={"n_cells": n_cells, "zone_cells": m},
    )


def find_ultimate_pass(
    k: float | np.ndarray,
    zone_len_frac: float,
    c0: float | np.ndarray = 1.0,
    max_passes: int = 25,
    n_cells: int = DEFAULT_N_CELLS,
    threshold_ppm: float = 1.0,
    head_crop_frac: float = 0.0,
    yield_gain_tol: float = 0.005,
    yield_target_frac: float = 0.95,
    shape_rel_tol: float = 0.02,
    elements: list[str] | None = None,
) -> dict:
    """找出「再做下去也沒用」的 pass 次數。

    物理背景
    --------
    一直 pass 下去，分布會收斂到極限分布（ultimate distribution）：此時
    「往尾端掃出去的雜質」與「熔區從右邊吃回來的雜質」達成平衡，之後每次
    pass 的改善量趨近於零。

    這是 P1 階段就能交出去、能立刻省錢的結論：客戶若現在跑 15 次，模型可以
    指出第 N 次之後純度不再進步，直接砍掉多餘批次時間。

    兩個判準（同時回報，實務上以第一個為準）
    ----------------------------------------
    1. **recommended_passes**：達到可達最大得料率 95% 所需的最少 pass 次數。
       這是客戶真正在乎的指標，也是報告裡該寫的數字。
    2. **saturation_pass**：最後一次仍能讓得料率增加 ``yield_gain_tol`` 的 pass。
       在這之後每一趟都幾乎白跑。
    3. **ultimate_pass**：相鄰兩次分布的相對 L2 變化小於 ``shape_rel_tol``，
       即數學上收斂到極限分布。通常比前兩者晚。

    Args:
        k: 純量或 (E,) 各元素的 k_eff。
        zone_len_frac: l / L。
        c0: 純量或 (E,) 進料濃度 [ppm]。
        max_passes: 最多模擬幾次。
        n_cells: 離散格數。
        threshold_ppm: 6N 判定門檻（總雜質）。
        head_crop_frac: 頭端固定切除比例。
        yield_gain_tol: 單次增量飽和門檻（絕對值，0.005 = 0.5 個百分點）。
        yield_target_frac: 建議次數的目標水準，預設為可達上限的 95%。
        shape_rel_tol: 形狀收斂門檻（相對 L2）。
        elements: 元素名稱，僅用於輸出標記。

    Returns:
        dict，欄位見 ``ultimate_summary`` 的鍵；可直接序列化給前端。
    """
    from .yield_calc import compute_purity_window   # 避免模組層級循環匯入

    res = simulate_passes(k, zone_len_frac, max_passes, c0=c0,
                          n_cells=n_cells, keep_all=True)
    prof = res.profiles
    if prof.ndim == 2:                       # 單元素 → 補上元素維度
        prof = prof[:, None, :]
    n_el = prof.shape[1]
    names = elements or [f"E{i}" for i in range(n_el)]

    yields, head_totals, shape_changes = [], [], []
    for p in range(prof.shape[0]):
        pdict = {names[e]: prof[p, e, :] for e in range(n_el)}
        win = compute_purity_window(res.x_norm, pdict, threshold_ppm,
                                    head_crop_frac=head_crop_frac)
        yields.append(win.yield_frac)
        head_totals.append(float(sum(prof[p, e, 0] for e in range(n_el))))
        if p > 0:
            # 用對數比值的 RMS 而非 L2 範數：濃度跨越好幾個數量級（頭端可能
            # 是 1e-3 ppm、尾端 1e2 ppm），L2 會被尾端尖峰主導，導致「頭端
            # 還在大幅改善」卻被判為已收斂。對數比值是尺度無關的。
            eps = 1e-12
            ratio = np.log((prof[p] + eps) / (prof[p - 1] + eps))
            shape_changes.append(float(np.sqrt(np.mean(ratio ** 2))))

    # ── 判準 1：達到最大得料率的 target_frac 所需的最少 pass 次數 ──────
    # 用「相對於可達上限的百分比」而不是「單次增量」，是因為前幾次 pass 的
    # 得料率常常都還是 0（頭端尚未降到門檻以下），用單次增量會在第 1 次就
    # 誤判收斂。這個寫法對「前段平坦、中段陡升、後段飽和」的典型曲線穩健。
    best_yield = max(yields) if yields else 0.0
    recommended = max_passes
    if best_yield > 0:
        target = yield_target_frac * best_yield
        for p, y in enumerate(yields):
            if y >= target:
                recommended = p
                break
    recommended = int(max(1, recommended))

    # ── 判準 2：單次增量飽和（最後一次仍有意義的 pass）────────────────
    saturation = 0
    for p in range(1, len(yields)):
        if yields[p] - yields[p - 1] >= yield_gain_tol:
            saturation = p
    saturation = int(max(1, saturation))

    # ── 判準 3：形狀收斂（數學上的極限分布）──────────────────────────
    ultimate = max_passes
    for i, ch in enumerate(shape_changes, start=1):
        if ch < shape_rel_tol:
            ultimate = i
            break

    saved = max(0, max_passes - saturation)
    return {
        "recommended_passes": recommended,
        "saturation_pass": saturation,
        "ultimate_pass": int(ultimate),
        "max_passes_simulated": max_passes,
        "yield_by_pass": [float(v) for v in yields],
        "head_total_by_pass": head_totals,
        "shape_change_by_pass": shape_changes,
        "yield_gain_tol": yield_gain_tol,
        "yield_target_frac": yield_target_frac,
        "shape_rel_tol": shape_rel_tol,
        "best_yield": float(best_yield),
        "yield_at_recommended": float(yields[recommended]) if recommended < len(yields) else 0.0,
        "passes_saved_vs_max": saved,
        "marginal_gain_by_pass": [float(yields[i] - yields[i - 1]) for i in range(1, len(yields))],
        "note": (
            f"跑到第 {recommended} 次即可達到可達最大得料率（{best_yield*100:.1f}%）"
            f"的 {yield_target_frac*100:.0f}%；第 {saturation} 次之後每多跑一趟，"
            f"得料率增加不到 {yield_gain_tol*100:.1f} 個百分點；"
            f"分布形狀約在第 {ultimate} 次收斂到極限分布。"
        ),
    }
