import numpy as np
import pytest

from xrayvision.core import geometry as G


def circle_pts(cx, cy, r, n=120, noise=0.0, seed=0):
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    rr = r + np.random.default_rng(seed).normal(0, noise, n)
    return np.c_[cx + rr * np.cos(th), cy + rr * np.sin(th)], th


def test_fit_circle_exact():
    pts, _ = circle_pts(10.5, -3.25, 17.0)
    cx, cy, r = G.fit_circle(pts)
    assert (cx, cy, r) == pytest.approx((10.5, -3.25, 17.0), abs=1e-9)


def test_fit_circle_needs_five_points():
    pts, _ = circle_pts(0, 0, 5, n=4)
    assert G.fit_circle(pts) is None


def test_robust_circle_rejects_outliers():
    pts, _ = circle_pts(50, 60, 20, noise=0.1)
    pts[:6] += 8.0                                   # 少數嚴重離群點
    f = G.robust_circle(pts)
    assert f["x"] == pytest.approx(50, abs=0.05)
    assert f["y"] == pytest.approx(60, abs=0.05)
    assert f["n"] <= 114


@pytest.mark.parametrize("seed", range(5))
def test_narrow_trim_drops_narrow_spike_keeps_wide_arc(seed):
    _, th = circle_pts(0, 0, 25, n=120)
    rad = np.full(120, 25.0) + np.random.default_rng(seed).normal(0, 0.3, 120)   # 接近實際輪廓雜訊
    rad[10:18] += 6.0          # 24° 窄突起 (走線)：應剔除
    rad[60:100] += 1.5         # 120° 寬弧 (焊墊略微露出)：應保留
    pts = np.c_[rad * np.cos(th), rad * np.sin(th)]
    f = G.narrow_trim_circle(pts, np.ones(120, bool), max_deg=40)
    ideal = G.fit_circle(pts[np.r_[0:10, 18:120]])            # 只去掉窄突起的理想結果
    assert np.hypot(f["x"] - ideal[0], f["y"] - ideal[1]) < 0.15
    assert f["n"] >= 85
    # 寬弧保留下來，圓心往寬弧方向 (約 240°) 偏
    ang = np.degrees(np.arctan2(f["y"], f["x"])) % 360
    assert 200 < ang < 280


def test_circular_runs_wraps_around():
    m = np.zeros(10, bool)
    m[[0, 1, 8, 9, 4]] = True
    runs = sorted(sorted(r.tolist()) for r in G.circular_runs(m))
    assert runs == [[0, 1, 8, 9], [4]]
    assert len(G.longest_run(m)) == 4


def test_fit_center_fixed_r():
    pts, _ = circle_pts(5, 7, 12, n=40)
    c = G.fit_center_fixed_r(pts[:15], 12, (4, 6))           # 只有一段弧
    assert c == pytest.approx((5, 7), abs=1e-6)


def test_similarity_recovers_transform():
    rng = np.random.default_rng(1)
    src = rng.uniform(0, 2000, (50, 2))
    a, s, t = np.radians(0.3), 1.0015, np.array([2.5, -1.25])
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    dst = s * src @ R.T + t
    M = G.similarity_lsq(src, dst)
    assert M[:, 2] == pytest.approx(t, abs=1e-9)
    assert np.hypot(M[0, 0], M[1, 0]) == pytest.approx(s, abs=1e-12)


def test_estimate_shift_robust_to_outliers():
    rng = np.random.default_rng(2)
    src = rng.uniform(0, 1000, (80, 2))
    dst = src + np.array([0.8, -0.4]) + rng.normal(0, 0.2, (80, 2))
    dst[:8] += rng.uniform(5, 10, (8, 2))                        # 10% 離群
    e = G.estimate_shift(src, dst)
    assert e["dx"] == pytest.approx(0.8, abs=0.1)
    assert e["dy"] == pytest.approx(-0.4, abs=0.1)
    assert not e["inliers"][:8].any()
    assert e["n_in"] >= 68


def test_estimate_shift_too_few_points():
    assert G.estimate_shift(np.zeros((2, 2)), np.ones((2, 2))) is None
