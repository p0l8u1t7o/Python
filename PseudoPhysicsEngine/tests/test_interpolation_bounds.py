"""內插比例的邊界回歸測試。

真實代理驗收時，S3 的逼近步驟推導出 0.6271887199479829 秒的時長，
`_sample_times` 以 (t1 - t0) * count / count 反推末點後出現浮點漂移，
使 ratio 變成 1.0000000000000002，SciPy 的 Slerp 直接丟出 ValueError。
這裡用同一個時長重現，並斷言因果：末點等於原始 t1、超界比例仍能內插到目標位姿。
"""

from __future__ import annotations

import numpy as np

from cellforge.sim.engine import _interpolate_pose, _sample_times

# 真實代理產生的時長，保留原值以重現當時的浮點路徑。
AGENT_DURATION_S = 0.6271887199479829


def test_sample_times_end_is_exactly_t1():
    times = _sample_times(0.0, AGENT_DURATION_S)
    assert times[0] == 0.0
    assert times[-1] == AGENT_DURATION_S
    ratios = [(t - times[0]) / (times[-1] - times[0]) for t in times]
    assert max(ratios) <= 1.0
    assert min(ratios) >= 0.0


def test_sample_times_stay_in_range_for_many_durations():
    for steps in range(1, 400):
        duration = steps * 0.0031415926535
        times = _sample_times(0.0, duration)
        assert times[-1] == duration
        assert all(0.0 <= (t - times[0]) / duration <= 1.0 for t in times)


def test_interpolate_pose_tolerates_out_of_range_ratio():
    start = np.eye(4)
    target = np.eye(4)
    target[:3, 3] = [10.0, -4.0, 2.5]
    target[:3, :3] = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])

    beyond = _interpolate_pose(start, target, 1.0 + 2e-16)
    assert np.allclose(beyond, target)

    below = _interpolate_pose(start, target, -1e-16)
    assert np.allclose(below, start)
