"""L0 物理層 — Pfann 偏析方程與 BPS 有效分配係數。

這一層是整個系統的骨架。所有上層（GP、貝氏最佳化、殘差學習、LLM）
產出的任何數字，最終都必須能追溯回這裡的計算，或被標示為「模型修正量」。
"""

from .pfann import pfann_profile, pfann_head_concentration, normal_freezing_profile
from .multipass import (
    ZoneRefiningResult,
    simulate_passes,
    simulate_single_pass,
    find_ultimate_pass,
)
from .bps import (
    keff_from_bps,
    bps_linearize,
    bps_inverse_linearize,
    fit_bps_linear,
    BPSModel,
)
from .yield_calc import PurityWindow, compute_purity_window, total_impurity

__all__ = [
    "pfann_profile",
    "pfann_head_concentration",
    "normal_freezing_profile",
    "ZoneRefiningResult",
    "simulate_passes",
    "simulate_single_pass",
    "find_ultimate_pass",
    "keff_from_bps",
    "bps_linearize",
    "bps_inverse_linearize",
    "fit_bps_linear",
    "BPSModel",
    "PurityWindow",
    "compute_purity_window",
    "total_impurity",
]
