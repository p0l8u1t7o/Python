"""6N 純度視窗與得料率計算。

判定規則（可由設定覆寫）
------------------------
6N = 99.9999%，即**總雜質** < 1 ppm。實務上客戶可能改用單一元素門檻，
或對不同元素給不同上限，故本模組同時支援：

  * total_threshold_ppm  — 總雜質上限（預設 1.0）
  * per_element_ppm      — 個別元素上限 dict，任一超標即不合格

得料率定義
----------
偏析純化後，頭端最乾淨、尾端最髒。合格區是從頭端算起的一段連續區間。
本模組回傳的是「**從頭端起算、連續滿足門檻的最長區間**」，而不是全錠中
所有合格點的比例——後者在物理上沒有意義，因為切割是連續的。

另外支援 head_crop_frac：頭端第一刀切除量（實務上頭端會有接觸污染、
氧化皮，客戶通常會固定切掉一小段）。得料率會扣除這一段。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np


@dataclass
class PurityWindow:
    """純度視窗計算結果。"""

    yield_frac: float                    # 得料率（佔全錠長度比例，已扣除頭端切除）
    head_cut_frac: float                 # 高純區起點 x/L（= head_crop_frac）
    tail_cut_frac: float                 # 高純區終點 x/L；超過此處即不合格
    threshold_ppm: float
    max_total_in_window_ppm: float       # 合格區內的最高總雜質，用來看餘裕
    limiting_element: str = ""           # 決定切點的元素（誰先超標）
    concentrate_start_frac: float = 1.0  # 雜質濃縮區起點（總雜質 > 5x 門檻處）
    per_element_at_cut: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def total_impurity(profiles: dict[str, np.ndarray]) -> np.ndarray:
    """把各元素的濃度分布加總成總雜質分布 [ppm]。

    Args:
        profiles: {元素名: (N,) ppm}，所有陣列長度須一致。

    Returns:
        (N,) 總雜質 [ppm]。
    """
    if not profiles:
        raise ValueError("profiles 不可為空")
    arrays = [np.asarray(v, dtype=np.float64).ravel() for v in profiles.values()]
    n = arrays[0].size
    if any(a.size != n for a in arrays):
        raise ValueError("各元素的分布長度不一致")
    return np.sum(arrays, axis=0)


def compute_purity_window(
    x_norm: np.ndarray,
    profiles: dict[str, np.ndarray],
    threshold_ppm: float = 1.0,
    per_element_ppm: dict[str, float] | None = None,
    head_crop_frac: float = 0.0,
    concentrate_multiple: float = 5.0,
) -> PurityWindow:
    """計算高純區、雜質濃縮區與 6N 得料率。

    Args:
        x_norm: (N,) 歸一化位置 x/L，須遞增。
        profiles: {元素名: (N,) ppm}。
        threshold_ppm: 總雜質上限。
        per_element_ppm: 個別元素上限；None 表示只看總量。
        head_crop_frac: 頭端固定切除比例，例如 0.03。
        concentrate_multiple: 判定「雜質濃縮區」的倍數（預設 5 倍門檻）。

    Returns:
        PurityWindow
    """
    x = np.asarray(x_norm, dtype=np.float64).ravel()
    total = total_impurity(profiles)
    n = x.size

    # 逐點合格判定
    ok = total <= threshold_ppm
    limiting = ""
    if per_element_ppm:
        for el, lim in per_element_ppm.items():
            if el not in profiles:
                continue
            el_ok = np.asarray(profiles[el], dtype=np.float64).ravel() <= lim
            ok = ok & el_ok

    start_idx = int(np.searchsorted(x, head_crop_frac, side="left"))
    start_idx = min(start_idx, n - 1)

    if not ok[start_idx]:
        # 連頭端都不合格：這批完全沒有 6N 料
        return PurityWindow(
            yield_frac=0.0,
            head_cut_frac=float(head_crop_frac),
            tail_cut_frac=float(head_crop_frac),
            threshold_ppm=threshold_ppm,
            max_total_in_window_ppm=float(total[start_idx]),
            limiting_element=_worst_element(profiles, start_idx, per_element_ppm),
            concentrate_start_frac=_concentrate_start(x, total, threshold_ppm, concentrate_multiple),
            per_element_at_cut={k: float(v[start_idx]) for k, v in profiles.items()},
            note="頭端即已超過門檻，本條件下無 6N 得料。",
        )

    # 從頭端往後找第一個不合格點
    end_idx = n
    for i in range(start_idx, n):
        if not ok[i]:
            end_idx = i
            break

    tail_cut = float(x[end_idx]) if end_idx < n else 1.0
    cut_idx = min(end_idx, n - 1)
    window = slice(start_idx, end_idx)
    yield_frac = max(0.0, tail_cut - float(head_crop_frac))

    return PurityWindow(
        yield_frac=float(yield_frac),
        head_cut_frac=float(head_crop_frac),
        tail_cut_frac=tail_cut,
        threshold_ppm=threshold_ppm,
        max_total_in_window_ppm=float(np.max(total[window])) if end_idx > start_idx else 0.0,
        limiting_element=_worst_element(profiles, cut_idx, per_element_ppm),
        concentrate_start_frac=_concentrate_start(x, total, threshold_ppm, concentrate_multiple),
        per_element_at_cut={k: float(np.asarray(v).ravel()[cut_idx]) for k, v in profiles.items()},
    )


def _worst_element(profiles: dict[str, np.ndarray], idx: int,
                   per_element_ppm: dict[str, float] | None) -> str:
    """在切點處，哪個元素離自己的上限最近（或最先超標）。"""
    best, best_ratio = "", -1.0
    for el, arr in profiles.items():
        val = float(np.asarray(arr, dtype=np.float64).ravel()[idx])
        lim = (per_element_ppm or {}).get(el)
        ratio = val / lim if lim else val
        if ratio > best_ratio:
            best, best_ratio = el, ratio
    return best


def _concentrate_start(x: np.ndarray, total: np.ndarray,
                       threshold: float, multiple: float) -> float:
    """雜質濃縮區起點：總雜質首次超過 multiple × 門檻的位置。"""
    hits = np.nonzero(total > threshold * multiple)[0]
    return float(x[hits[0]]) if hits.size else 1.0
