"""L0 物理層的正確性測試。

這一層錯了，上面所有東西都是錯的，所以驗證做得比其他層嚴格：
拿離散模擬去對 Pfann 的解析解，而不是只檢查「跑得動」。
"""

from __future__ import annotations

import numpy as np
import pytest

from expanalysis.physics import (
    compute_purity_window, find_ultimate_pass, keff_from_bps,
    bps_linearize, bps_inverse_linearize, fit_bps_linear,
    pfann_profile, simulate_passes, total_impurity,
)
from expanalysis.physics.profile_grid import get_profile_grid


# ── 單次 pass：離散模擬 vs Pfann 解析解 ─────────────────────────
@pytest.mark.parametrize("k", [0.02, 0.08, 0.25, 0.5, 0.85])
def test_single_pass_matches_pfann_analytic(k):
    """主掃描區（x < L − l）必須與 Pfann 解析解吻合。

    這是整個物理層最重要的一條測試。離散模擬用的是「單格解析積分」而非
    前向 Euler，所以誤差不應隨 k 放大；容忍度設在 1%，實測遠小於此。
    """
    zone_frac, n_cells, c0 = 0.10, 400, 10.0
    res = simulate_passes(k, zone_frac, 1, c0=c0, n_cells=n_cells, keep_all=False)

    # 只比主掃描區；最後一個熔區長度是終端凝固，公式不涵蓋
    main = res.x_norm < (1.0 - zone_frac - 0.02)
    x_mm = res.x_norm[main]              # 以 L = 1 為單位
    expected = pfann_profile(x_mm, k, zone_frac, c0)
    rel = np.abs(res.final[main] / expected - 1.0)
    assert rel.max() < 0.01, f"k={k} 最大相對誤差 {rel.max():.4f}"


def test_head_concentration_equals_k_times_c0():
    """頭端濃度應為 k·C0，這是單次 pass 能達到的最佳純度。"""
    k, c0 = 0.12, 8.0
    res = simulate_passes(k, 0.08, 1, c0=c0, n_cells=600, keep_all=False)
    assert res.final[0] == pytest.approx(k * c0, rel=0.02)


# ── 質量守恆 ───────────────────────────────────────────────────
@pytest.mark.parametrize("n_passes", [1, 3, 8, 15])
def test_mass_is_conserved(n_passes):
    """偏析純化不會消滅雜質，只是重新分布。

    終端凝固若用主掃描的更新式，最後一格會殘留 (1−k)·S 的溶質。本專案改用
    Scheil 的格內積分平均，質量應嚴格守恆到浮點精度。
    """
    res = simulate_passes(np.array([0.05, 0.3, 0.7]), 0.1, n_passes,
                          c0=np.array([5.0, 3.0, 2.0]), n_cells=300, keep_all=False)
    assert res.mass_error < 1e-12, f"質量誤差 {res.mass_error:.3e}"


def test_multi_element_matches_single_element():
    """一次算多個元素與逐一計算必須完全相同（向量化不可改變結果）。"""
    ks, c0s = [0.05, 0.3], [5.0, 3.0]
    multi = simulate_passes(np.array(ks), 0.1, 6, c0=np.array(c0s),
                            n_cells=200, keep_all=False).final
    for i, (k, c0) in enumerate(zip(ks, c0s)):
        single = simulate_passes(k, 0.1, 6, c0=c0, n_cells=200, keep_all=False).final
        np.testing.assert_allclose(multi[i], single, rtol=1e-12)


# ── 單調性（物理直覺）──────────────────────────────────────────
def test_lower_k_gives_cleaner_head():
    """k 越小，頭端越乾淨。這是本製程的基本物理。"""
    heads = [simulate_passes(k, 0.1, 5, c0=10.0, n_cells=200,
                             keep_all=False).final[0]
             for k in (0.05, 0.2, 0.5, 0.9)]
    assert heads == sorted(heads), heads


def test_more_passes_never_worse_at_head():
    """多做一次 pass，頭端濃度不該變高。"""
    res = simulate_passes(0.15, 0.1, 12, c0=10.0, n_cells=200, keep_all=True)
    heads = res.profiles[:, 0]
    assert np.all(np.diff(heads) <= 1e-12), heads


def test_tail_is_dirtier_than_head():
    """雜質會被掃到尾端。"""
    res = simulate_passes(0.2, 0.1, 4, c0=5.0, n_cells=200, keep_all=False)
    assert res.final[-1] > res.final[0] * 10


# ── 查表快取的精度 ─────────────────────────────────────────────
@pytest.mark.parametrize("k", [0.037, 0.137, 0.42, 0.78])
def test_profile_grid_interpolation_accuracy(k):
    """查表內插必須與直接模擬吻合到 1% 以內，否則擬合會有系統性偏差。"""
    grid = get_profile_grid(0.1, 8, 240)
    ref = simulate_passes(k, 0.1, 8, c0=1.0, n_cells=240, keep_all=False).final
    got = grid.profile_at_k(k, 1.0)
    assert np.abs(got / ref - 1.0).max() < 0.01


def test_profile_grid_is_linear_in_c0():
    """模擬對濃度是線性的——整個查表快取的正確性建立在這個性質上。"""
    grid = get_profile_grid(0.1, 5, 200)
    a = grid.profile_at_k(0.2, 1.0)
    b = grid.profile_at_k(0.2, 7.3)
    np.testing.assert_allclose(b, a * 7.3, rtol=1e-12)


# ── BPS ────────────────────────────────────────────────────────
def test_bps_limits():
    """v → 0 時 k_eff → k0；v → ∞ 時 k_eff → 1。"""
    k0 = 0.08
    assert float(keff_from_bps(0.0, k0, 0.4)) == pytest.approx(k0, rel=1e-9)
    assert float(keff_from_bps(1e4, k0, 0.4)) == pytest.approx(1.0, abs=1e-6)


def test_bps_is_monotonic_in_speed():
    v = np.linspace(0.1, 10, 50)
    k = keff_from_bps(v, 0.08, 0.4)
    assert np.all(np.diff(k) > 0)


def test_linearize_roundtrip():
    k = np.array([0.001, 0.05, 0.3, 0.7, 0.99])
    np.testing.assert_allclose(bps_inverse_linearize(bps_linearize(k)), k, rtol=1e-9)


def test_fit_bps_recovers_known_parameters():
    """從無雜訊的 BPS 資料反解，應完全還原 k0 與 delta/D。"""
    k0_true, dd_true = 0.06, 0.35
    v = np.linspace(0.5, 8.0, 12)
    k = keff_from_bps(v, k0_true, dd_true)
    m = fit_bps_linear(v, k, use_temperature=False)
    assert m.k0 == pytest.approx(k0_true, rel=1e-4)
    assert m.delta_over_d == pytest.approx(dd_true, rel=1e-4)
    assert m.r2 > 0.9999


def test_fit_bps_flags_nonlinear_data():
    """散點不成直線時，模型必須自己說出來，而不是硬給一組參數。"""
    v = np.linspace(0.5, 8.0, 12)
    k = np.clip(0.3 + 0.35 * np.sin(v * 1.7), 0.02, 0.97)
    m = fit_bps_linear(v, k, use_temperature=False)
    assert m.linearity_note, "R² 很低時應該要有警示文字"


# ── 純度視窗 ───────────────────────────────────────────────────
def test_purity_window_basic():
    x = np.linspace(0, 1, 101)
    prof = {"Cu": np.linspace(0.1, 5.0, 101), "Fe": np.full(101, 0.2)}
    w = compute_purity_window(x, prof, threshold_ppm=1.0, head_crop_frac=0.05)
    assert 0.05 < w.tail_cut_frac < 1.0
    assert w.yield_frac == pytest.approx(w.tail_cut_frac - 0.05)
    assert w.limiting_element in ("Cu", "Fe")


def test_purity_window_all_bad():
    x = np.linspace(0, 1, 51)
    w = compute_purity_window(x, {"Cu": np.full(51, 9.0)}, threshold_ppm=1.0)
    assert w.yield_frac == 0.0
    assert w.note


def test_total_impurity_rejects_ragged_input():
    with pytest.raises(ValueError):
        total_impurity({"Cu": np.zeros(5), "Fe": np.zeros(6)})


# ── 極限分布 ───────────────────────────────────────────────────
def test_ultimate_pass_ordering():
    """建議次數 <= 邊際飽和次數；兩者都在模擬上限內。"""
    out = find_ultimate_pass(np.array([0.05, 0.15, 0.25, 0.42]), 0.10,
                             c0=np.array([5.0, 3.0, 1.5, 2.0]),
                             max_passes=20, elements=["Cu", "Fe", "Ni", "Sn"])
    assert 1 <= out["recommended_passes"] <= out["max_passes_simulated"]
    assert out["saturation_pass"] >= out["recommended_passes"] - 1
    assert len(out["yield_by_pass"]) == out["max_passes_simulated"] + 1
    assert out["yield_by_pass"] == sorted(out["yield_by_pass"]), "得料率不該隨 pass 下降"
