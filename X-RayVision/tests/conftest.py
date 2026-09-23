import os
import sys

import cv2
import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def synth_absorption(shift=(0.0, 0.0), pitch=90, R=24.0, pad_R=28.0, pad_amp=0.04, bump_amp=0.14,
                     size=(900, 900), squash=1.0):
    """
    合成吸收量影像：「凸塊圓盤 (帶圓頂) + 較淡、較大的焊墊圓盤」的陣列。
    shift 為凸塊相對焊墊的偏移 (px)；squash < 1 時 y 方向壓扁，模擬斜射觀察。
    """
    H, W = size
    ss = 4                                   # 超取樣後縮小，模擬邊緣模糊與子像素位置
    A = np.full((H * ss, W * ss), 0.35, np.float32)
    h = int(np.ceil((max(R, pad_R) + max(abs(shift[0]), abs(shift[1])) + 2) * ss))
    for cy in np.arange(pitch, H - pitch / 2, pitch):
        for cx in np.arange(pitch, W - pitch / 2, pitch):
            y0, x0 = int(cy * ss) - h, int(cx * ss) - h
            yy, xx = np.mgrid[y0:y0 + 2 * h, x0:x0 + 2 * h].astype(np.float32) / ss
            dp = np.hypot(xx - cx, (yy - cy) / squash)
            db = np.hypot(xx - (cx + shift[0]), (yy - (cy + shift[1])) / squash)
            A[y0:y0 + 2 * h, x0:x0 + 2 * h] += (pad_amp * (dp < pad_R) + bump_amp * (db < R) *
                                                (0.6 + 0.4 * np.sqrt(np.clip(1 - (db / R) ** 2, 0, 1))))
    A = cv2.resize(A, (W, H), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(A, (0, 0), 2.0)


def to_intensity(A, gain=1.0, noise=0.004, seed=0, field=None, dark=None):
    """吸收量 → 16-bit 強度；gain 模擬曝光／管電流，field 為偵測器增益不均勻，dark 為暗電流"""
    I = 65535.0 * np.exp(-A) * gain
    if field is not None:
        I = I * field
    I *= 1 + np.random.default_rng(seed).normal(0, noise, I.shape)
    if dark is not None:
        I = I + dark
    return np.clip(I, 0, 65535).astype(np.uint16)


def vignette(size, strength=0.35):
    H, W = size
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r2 = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    return (1 - strength * r2 / 2).astype(np.float32)


def synth_raw16(path, gain=1.0, seed=0, noise=0.004, **kw):
    cv2.imwrite(path, to_intensity(synth_absorption(**kw), gain=gain, noise=noise, seed=seed))
    return path


@pytest.fixture
def synth(tmp_path):
    def make(name="s.tiff", **kw):
        return synth_raw16(str(tmp_path / name), **kw)
    return make
