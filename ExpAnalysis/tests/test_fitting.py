"""擬合層測試：k_eff 反解、設限處理、bootstrap。

核心驗證方式是「已知答案的反解」：用已知的真實 k 生成帶雜訊與設限的資料，
再讓整套流程反解，檢查能不能還原。還原不了就代表方法有問題——這比在真實
資料上「看起來合理」可靠得多。
"""

from __future__ import annotations

import numpy as np
import pytest

from expanalysis.fitting import bootstrap_keff, fit_keff, tobit_nll
from expanalysis.fitting.censored import TobitData, standardized_residuals
from expanalysis.physics.profile_grid import get_profile_grid


def _make_points(k, n_passes=8, zone=0.1, c0=5.0, n_pts=8, lod=0.0,
                 noise=0.0, seed=0):
    """由已知 k 生成一組取樣點。"""
    rng = np.random.default_rng(seed)
    grid = get_profile_grid(zone, n_passes, 240)
    x = np.linspace(0.03, 0.92, n_pts)
    true = np.interp(x, grid.x_norm, grid.profile_at_k(k, c0))
    obs = true * np.exp(rng.normal(0.0, noise, n_pts)) if noise else true
    cen = obs < lod if lod else np.zeros(n_pts, dtype=bool)
    val = np.where(cen, lod, obs)
    return x, val, np.full(n_pts, lod), cen


@pytest.mark.parametrize("k_true", [0.04, 0.12, 0.30, 0.55, 0.80])
def test_recovers_k_from_noiseless_data(k_true):
    """無雜訊、無設限時應該幾乎完全還原。"""
    x, v, lod, cen = _make_points(k_true)
    fit = fit_keff(x, v, lod, cen, zone_len_frac=0.1, n_passes=8, c0_ppm=5.0)
    assert fit.k_eff == pytest.approx(k_true, rel=0.03)


@pytest.mark.parametrize("seed", range(6))
def test_recovers_k_with_realistic_noise(seed):
    """12% 乘法性量測誤差下，k 的還原誤差應在 10% 以內。"""
    k_true = 0.18
    x, v, lod, cen = _make_points(k_true, noise=0.12, seed=seed)
    fit = fit_keff(x, v, lod, cen, zone_len_frac=0.1, n_passes=8, c0_ppm=5.0)
    assert fit.k_eff == pytest.approx(k_true, rel=0.10)


def test_censored_handling_beats_naive_substitution():
    """Tobit 處理應比「當成 0」和「當成 LOD」更接近真值。

    這是整個設限處理章節的核心主張，必須有測試撐著，不能只寫在文件裡。
    對多組隨機種子取中位偏差，避免單一樣本的運氣成分。
    """
    k_true, lod = 0.10, 0.02
    bias = {"tobit": [], "as_zero": [], "as_lod": []}
    for seed in range(12):
        x, v, lodv, cen = _make_points(k_true, lod=lod, noise=0.12, seed=seed)
        if not cen.any():
            continue
        base = dict(zone_len_frac=0.1, n_passes=8, c0_ppm=5.0)
        bias["tobit"].append(
            fit_keff(x, v, lodv, cen, **base).k_eff)
        bias["as_zero"].append(
            fit_keff(x, np.where(cen, 1e-9, v), lodv,
                     np.zeros_like(cen), **base).k_eff)
        bias["as_lod"].append(
            fit_keff(x, np.where(cen, lod, v), lodv,
                     np.zeros_like(cen), **base).k_eff)

    assert bias["tobit"], "測試資料沒有產生任何設限點，測試無效"
    err = {m: abs(np.median(vals) - k_true) / k_true for m, vals in bias.items()}
    assert err["tobit"] <= err["as_zero"], err
    assert err["tobit"] <= err["as_lod"], err


def test_all_censored_is_reported_not_silently_wrong():
    """全部測點都低於 LOD 時，必須明說「無法可靠估計」而不是給一個數字。"""
    x = np.linspace(0.05, 0.9, 8)
    lod = np.full(8, 1.0)
    fit = fit_keff(x, lod, lod, np.ones(8, dtype=bool),
                   zone_len_frac=0.1, n_passes=8, c0_ppm=5.0)
    assert "無法可靠估計" in fit.note


def test_too_few_points_raises():
    with pytest.raises(ValueError):
        fit_keff([0.1, 0.5], [1.0, 2.0], [0, 0], [False, False],
                 zone_len_frac=0.1, n_passes=4, c0_ppm=1.0)


def test_tobit_nll_prefers_prediction_below_lod_for_censored_points():
    """設限點的 likelihood 應獎勵「預測低於 LOD」、懲罰「預測高於 LOD」。"""
    data = TobitData(x=np.array([0.1]), log_y=np.log([0.05]),
                     log_lod=np.log([0.05]), censored=np.array([True]))
    low = tobit_nll(np.log([0.005]), data, 0.15)
    high = tobit_nll(np.log([0.5]), data, 0.15)
    assert low < high


def test_generalized_residual_for_censored_points():
    """設限點的期望殘差：預測遠低於 LOD 時趨近 0，預測遠高於 LOD 時是大負值。"""
    data = TobitData(x=np.array([0.1, 0.2]), log_y=np.log([0.05, 0.05]),
                     log_lod=np.log([0.05, 0.05]), censored=np.array([True, True]))
    r = standardized_residuals(np.log([0.001, 1.0]), data, 0.2)
    assert abs(r[0]) < 0.01
    assert r[1] < -3.0


def test_bootstrap_interval_contains_estimate():
    x, v, lod, cen = _make_points(0.2, noise=0.12, seed=3)
    fit = fit_keff(x, v, lod, cen, zone_len_frac=0.1, n_passes=8, c0_ppm=5.0)
    bs = bootstrap_keff(x, v, lod, cen, zone_len_frac=0.1, n_passes=8,
                        c0_ppm=fit.c0_ppm, sigma_log=fit.sigma_log,
                        k_eff=fit.k_eff, n_draws=200)
    assert bs.k_lo <= fit.k_eff <= bs.k_hi
    assert bs.k_se > 0
    assert bs.n_success > 150


def test_bootstrap_interval_widens_with_noise():
    """雜訊越大，區間應該越寬——不然這個區間就是裝飾品。"""
    widths = []
    for noise in (0.05, 0.30):
        x, v, lod, cen = _make_points(0.2, noise=noise, seed=1)
        fit = fit_keff(x, v, lod, cen, zone_len_frac=0.1, n_passes=8, c0_ppm=5.0)
        bs = bootstrap_keff(x, v, lod, cen, zone_len_frac=0.1, n_passes=8,
                            c0_ppm=fit.c0_ppm, sigma_log=fit.sigma_log,
                            k_eff=fit.k_eff, n_draws=200)
        widths.append(bs.k_hi - bs.k_lo)
    assert widths[1] > widths[0] * 1.5, widths


def test_bootstrap_rejects_case_mode_without_kwargs():
    x, v, lod, cen = _make_points(0.2, noise=0.1, seed=2)
    with pytest.raises(ValueError):
        bootstrap_keff(x, v, lod, cen, zone_len_frac=0.1, n_passes=8,
                       c0_ppm=5.0, sigma_log=0.12, method="不存在的方法")
