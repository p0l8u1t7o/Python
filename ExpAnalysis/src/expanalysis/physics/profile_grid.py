"""k 掃描網格快取 — 讓擬合與 bootstrap 從「秒」降到「毫秒」。

關鍵觀察：整個區域熔煉的離散模擬對濃度是**線性**的。
凝固帶走 k*C_L、熔化帶入 C_in，全部是線性運算，所以

    profile(c0, k, ...) = c0 * profile(1.0, k, ...)

因此只要以 c0=1 對一組 k 值先算好曲線，之後任何 c0、任何 k（線性內插）
都能立刻取得預測值。

沒有這層快取的話，每次 likelihood 評估都要重跑一次多次 pass 模擬
（8 passes × 300 cells ≈ 2400 次迴圈），bootstrap 1000 次會到十幾秒，
UI 上就不能互動了。有了它，同一組 (zone_frac, n_passes) 只需建一次表。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from .multipass import simulate_passes

# k 網格：對數等分，兩端加密。涵蓋 0.003（極易除）到 0.995（幾乎除不掉）。
DEFAULT_K_GRID = np.unique(np.concatenate([
    np.geomspace(0.003, 0.30, 72),
    np.linspace(0.30, 0.95, 52),
    np.array([0.97, 0.985, 0.995]),
]))

_CACHE: dict[tuple, "ProfileGrid"] = {}
_CACHE_LOCK = threading.Lock()
_MAX_CACHE = 128


@dataclass
class ProfileGrid:
    """(k, x) 兩維的濃度查表，c0 = 1。"""

    k_grid: np.ndarray            # (K,)
    x_norm: np.ndarray            # (N,)
    profiles: np.ndarray          # (K, N) c0=1 時的濃度
    zone_len_frac: float
    n_passes: int
    n_cells: int
    _log_profiles: np.ndarray | None = None

    def profile_at_k(self, k: float, c0: float = 1.0) -> np.ndarray:
        """(N,) 全錠濃度分布，對 k 做對數空間線性內插。

        用兩列加權混合而非逐格 np.interp，成本從約 1 ms 降到約 5 us。
        網格掃描（數千組參數 × 四個元素）全靠這個才跑得動。
        """
        kq = float(np.clip(k, self.k_grid[0], self.k_grid[-1]))
        j = int(np.searchsorted(self.k_grid, kq, side="right")) - 1
        j = max(0, min(j, self.k_grid.size - 2))
        k0, k1 = self.k_grid[j], self.k_grid[j + 1]
        w = 0.0 if k1 == k0 else (kq - k0) / (k1 - k0)
        if self._log_profiles is None:
            self._log_profiles = np.log(np.maximum(self.profiles, 1e-30))
        lp = self._log_profiles
        return np.exp((1.0 - w) * lp[j] + w * lp[j + 1]) * c0

    def predict(self, k: float | np.ndarray, x: np.ndarray,
                c0: float = 1.0) -> np.ndarray:
        """在任意 k 與任意位置取預測濃度。

        兩段線性內插：先對 x 內插（每個 k 網格點），再對 k 內插。
        對 k 的內插在 log 濃度空間進行，因為濃度隨 k 變化接近指數。

        Args:
            k: 純量或 (M,)。
            x: (P,) 歸一化位置。
            c0: 初始濃度倍率。

        Returns:
            k 為純量時 (P,)；k 為 (M,) 時 (M, P)。
        """
        x = np.atleast_1d(np.asarray(x, dtype=np.float64))
        k_arr = np.atleast_1d(np.asarray(k, dtype=np.float64))
        scalar = np.ndim(k) == 0

        # 先對 x 內插 → (K, P)
        cols = np.empty((self.k_grid.size, x.size), dtype=np.float64)
        for i in range(self.k_grid.size):
            cols[i] = np.interp(x, self.x_norm, self.profiles[i])

        log_cols = np.log(np.maximum(cols, 1e-30))
        kq = np.clip(k_arr, self.k_grid[0], self.k_grid[-1])
        out = np.empty((kq.size, x.size), dtype=np.float64)
        for p in range(x.size):
            out[:, p] = np.interp(kq, self.k_grid, log_cols[:, p])
        out = np.exp(out) * c0
        return out[0] if scalar else out


class PositionSlice:
    """把查表在固定取樣位置上先切好，供擬合迴圈重複呼叫。

    擬合與 bootstrap 會對同一組取樣位置評估數萬次不同的 k。位置內插只跟 x
    有關、與 k 無關，先算好可以省掉絕大部分工作：實測下來單次評估從
    約 260 us 降到約 10 us。
    """

    __slots__ = ("k_grid", "x", "log_cols")

    def __init__(self, grid: "ProfileGrid", x: np.ndarray):
        self.k_grid = grid.k_grid
        self.x = np.atleast_1d(np.asarray(x, dtype=np.float64))
        cols = np.empty((grid.k_grid.size, self.x.size), dtype=np.float64)
        for i in range(grid.k_grid.size):
            cols[i] = np.interp(self.x, grid.x_norm, grid.profiles[i])
        self.log_cols = np.log(np.maximum(cols, 1e-30))

    def predict(self, k: float, c0: float = 1.0) -> np.ndarray:
        """(P,) 預測濃度 [ppm]。"""
        kq = float(np.clip(k, self.k_grid[0], self.k_grid[-1]))
        out = np.empty(self.x.size, dtype=np.float64)
        for p in range(self.x.size):
            out[p] = np.interp(kq, self.k_grid, self.log_cols[:, p])
        return np.exp(out) * c0

    def predict_log(self, k: float) -> np.ndarray:
        """(P,) 預測的 ln(濃度)（c0=1）。擬合迴圈直接用這個省一次 exp/log。"""
        kq = float(np.clip(k, self.k_grid[0], self.k_grid[-1]))
        out = np.empty(self.x.size, dtype=np.float64)
        for p in range(self.x.size):
            out[p] = np.interp(kq, self.k_grid, self.log_cols[:, p])
        return out


def get_profile_grid(zone_len_frac: float, n_passes: int,
                     n_cells: int = 240,
                     k_grid: np.ndarray | None = None) -> ProfileGrid:
    """取得（必要時建立）指定製程條件的查表。行程層級快取。"""
    kg = DEFAULT_K_GRID if k_grid is None else np.asarray(k_grid, dtype=np.float64)
    key = (round(float(zone_len_frac), 5), int(n_passes), int(n_cells), kg.size,
           float(kg[0]), float(kg[-1]))
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            return hit

    res = simulate_passes(kg, zone_len_frac, int(n_passes), c0=1.0,
                          n_cells=n_cells, keep_all=False)
    grid = ProfileGrid(
        k_grid=kg, x_norm=res.x_norm, profiles=res.final,
        zone_len_frac=float(zone_len_frac), n_passes=int(n_passes), n_cells=int(n_cells),
    )
    with _CACHE_LOCK:
        if len(_CACHE) >= _MAX_CACHE:
            _CACHE.clear()          # 簡單粗暴；查表重建只需數十毫秒
        _CACHE[key] = grid
    return grid


def slice_at(zone_len_frac: float, n_passes: int, x: np.ndarray,
             n_cells: int = 240) -> PositionSlice:
    """便利函式：取得查表並在取樣位置切片。"""
    return PositionSlice(get_profile_grid(zone_len_frac, n_passes, n_cells), x)


def clear_grid_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
