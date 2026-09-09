"""效能優化的舊新版等價性檢查。

這裡刻意保留被優化前的純函式副本，讓測試用同一組 bench 合成輸入比對輸出；
bench 訊息字串也一併比對，避免只看狀態碼或測試綠燈。
"""

from __future__ import annotations

import math
import tempfile
from typing import Any

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision.tools import base
from apps.vision.tools.builtin.locate import line_span, to_gray
from apps.vision.tools.roi import crop
from scripts.bench_tools import Scene, make_ctx


def _old_fft_filter(gray: np.ndarray, *, mode: str, cutoff: float, style: str) -> dict[str, np.ndarray]:
    """優化前的 NumPy FFT 路徑。"""
    x = gray.astype(np.float32)
    f = np.fft.fftshift(np.fft.fft2(x))
    h, w = x.shape
    yy, xx = np.ogrid[:h, :w]
    r = np.hypot(yy - h / 2.0, xx - w / 2.0) / (min(h, w) / 2.0)
    if style == "truncate":
        mask = (r <= cutoff).astype(np.float32)
    else:
        mask = np.exp(-(r / cutoff) ** 2).astype(np.float32)
    highpass = mode == "highpass"
    if highpass:
        mask = 1.0 - mask
    out_f = np.fft.ifft2(np.fft.ifftshift(f * mask))
    out = out_f.real.astype(np.float32)
    if gray.dtype == np.uint8:
        out = np.clip(out + (128.0 if highpass else 0.0), 0, 255).astype(np.uint8)
    elif gray.dtype == np.uint16:
        out = np.clip(out + (32768.0 if highpass else 0.0), 0, 65535).astype(np.uint16)
    spectrum = np.log1p(np.abs(f))
    spectrum = (spectrum / spectrum.max() * 255.0).astype(np.uint8) if spectrum.max() > 0 else np.zeros_like(gray, dtype=np.uint8)
    return {"image": out, "spectrum": spectrum}


def _old_fit_line_ransac(pts: np.ndarray, tol: float = 2.0, iterations: int = 200, seed: int = 0) -> tuple[tuple[float, float, float, float], np.ndarray] | None:
    """優化前的 float64 RANSAC 距離矩陣。"""
    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    if n < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(int(iterations), 2))
    idx = idx[idx[:, 0] != idx[:, 1]]
    if len(idx) == 0:
        return None
    p0 = pts[idx[:, 0]]
    d = pts[idx[:, 1]] - p0
    norm = np.hypot(d[:, 0], d[:, 1])
    good = norm >= 1e-9
    norm = np.where(good, norm, 1.0)
    nx, ny = -d[:, 1] / norm, d[:, 0] / norm
    dist = np.abs((pts[None, :, 0] - p0[:, 0:1]) * nx[:, None] + (pts[None, :, 1] - p0[:, 1:2]) * ny[:, None])
    inl = dist <= tol
    counts = inl.sum(axis=1)
    counts[~good] = -1
    best_i = int(counts.argmax())
    if counts[best_i] < 2:
        return None
    best_inliers = inl[best_i]
    vx, vy, x0, y0 = cv2.fitLine(pts[best_inliers].astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).reshape(-1)
    return (float(vx), float(vy), float(x0), float(y0)), best_inliers


def _old_find_lines_multi(image: np.ndarray, region: dict[str, Any]) -> dict[str, Any]:
    """bench 的 find_lines_multi 參數組合，只有 RANSAC 換成舊版。"""
    area = crop(to_gray(image), region)
    edges = cv2.Canny(area.image, 30, 60)
    if area.mask is not None:
        edges = cv2.bitwise_and(edges, edges, mask=area.mask)
    ys, xs = np.nonzero(edges)
    points = np.stack([xs + area.x0, ys + area.y0], axis=1).astype(np.float64)
    remaining = points
    lines: list[dict[str, float]] = []
    angles: list[float] = []
    for _ in range(4):
        if len(remaining) < 30:
            break
        fitted = _old_fit_line_ransac(remaining, tol=2)
        if fitted is None:
            break
        (vx, vy, x0, y0), inliers = fitted
        if int(inliers.sum()) < 30:
            break
        member = remaining[inliers]
        span = line_span((float(vx), float(vy), float(x0), float(y0)), member)
        length = math.hypot(span["x2"] - span["x1"], span["y2"] - span["y1"])
        angle = (math.degrees(math.atan2(float(vy), float(vx))) + 90) % 180 - 90
        remaining = remaining[~inliers]
        if length < 20:
            continue
        span["angle"] = round(angle, 3)
        span["points"] = int(inliers.sum())
        lines.append(span)
        angles.append(round(angle, 3))
    return {
        "count": len(lines),
        "lines": lines,
        "angles": angles,
        "first": lines[0] if lines else None,
        "points": points[:2000].round(2).tolist(),
        "message": f"{len(lines)} lines: " + ", ".join(f"{a:.1f}°" for a in angles[:6]) if lines else "No line was long or solid enough",
    }


class PerformanceEquivalenceTests(SimpleTestCase):
    """bench 1280×960 與 640×480 場景的逐輸出等價性。"""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        folder = tempfile.mkdtemp(prefix="vs-perf-eq-")
        cls.scenes = [Scene(1280, 960, folder), Scene(640, 480, folder)]

    def test_fft_filter_lowpass_matches_previous_output(self):
        tool = base.get("fft_filter")
        params = {"mode": "lowpass", "cutoff": 0.15}
        for scene in self.scenes:
            with self.subTest(size=(scene.w, scene.h)):
                old = _old_fft_filter(scene.gray, mode="lowpass", cutoff=0.15, style="attenuate")
                res = tool.execute(make_ctx("fft_filter", scene.gray, params, {}, scene.assets, {}))
                self.assertEqual(f"{res.status} {res.message}", "ok lowpass r=0.15")
                for key in ("image", "spectrum"):
                    got = res.outputs[key]
                    diff = np.abs(old[key].astype(np.int32) - got.astype(np.int32))
                    self.assertLessEqual(int(diff.max()), 1, (scene.w, scene.h, key, int(diff.max()), float(np.count_nonzero(diff) / diff.size)))

    def test_find_lines_multi_matches_previous_geometry(self):
        tool = base.get("find_lines_multi")
        for scene in self.scenes:
            region = scene.rect(-0.25, -0.2, 0.5, 0.4)
            params = {"roi": region, "max_lines": 4}
            with self.subTest(size=(scene.w, scene.h)):
                old = _old_find_lines_multi(scene.image, region)
                res = tool.execute(make_ctx("find_lines_multi", scene.image, params, {}, scene.assets, {}))
                self.assertEqual(f"{res.status} {res.message}", f"ok {old['message']}")
                self.assertEqual(res.outputs["count"], old["count"])
                self.assertEqual(len(res.outputs["lines"]), len(old["lines"]))
                for expected, got in zip(old["lines"], res.outputs["lines"]):
                    for key in ("x1", "y1", "x2", "y2"):
                        self.assertLessEqual(abs(float(expected[key]) - float(got[key])), 0.05, (scene.w, scene.h, key, expected, got))
                    self.assertLessEqual(abs(float(expected["angle"]) - float(got["angle"])), 0.05, (scene.w, scene.h, expected, got))
                    self.assertEqual(int(got["points"]), int(expected["points"]))
                self.assertEqual(res.outputs["angles"], old["angles"])
                self.assertEqual(res.outputs["points"], old["points"])


class FftFilterOddSizeEquivalenceTests(SimpleTestCase):
    """奇數尺寸（ROI 裁切最常見）與高通／截斷／u16 也要與舊實作一致。

    第一版換成 cv2.dft 時只以 DC 為中心算遮罩，偶數尺寸完全等價，但 333×97、cutoff 0.05 差到 11 灰階：
    舊實作的遮罩中心在 (h/2, w/2)，奇數尺寸時落在半格上，取實部又等於把遮罩對稱化。這條把整個參數空間鎖住。
    """

    def test_all_paths_match_previous_output_within_one_level(self):
        tool = base.get("fft_filter")
        rng = np.random.default_rng(5)
        for (h, w) in ((333, 97), (451, 701), (64, 65)):
            gray = cv2.GaussianBlur(rng.integers(0, 256, (h, w), np.uint8), (0, 0), 3)
            for dtype_name, img in (("u8", gray), ("u16", gray.astype(np.uint16) * 257)):
                for mode in ("lowpass", "highpass"):
                    for style in ("attenuate", "truncate"):
                        for cutoff in (0.05, 0.15, 0.4):
                            old = _old_fft_filter(img, mode=mode, cutoff=cutoff, style=style)
                            res = tool.execute(make_ctx("fft_filter", img, {"mode": mode, "cutoff": cutoff, "style": style}, {}, {}, {}))
                            for key in ("image", "spectrum"):
                                unit = 257 if (key == "image" and img.dtype == np.uint16) else 1  # u16 是 u8×257，1 灰階＝257
                                diff = int(np.abs(old[key].astype(np.int64) - res.outputs[key].astype(np.int64)).max())
                                with self.subTest(size=(h, w), dtype=dtype_name, mode=mode, style=style, cutoff=cutoff, key=key):
                                    self.assertLessEqual(diff, unit)

    def test_mask_cache_returns_the_same_read_only_array(self):
        from apps.vision.tools.builtin import preprocess

        a = preprocess.fft_mask(96, 128, 0.15, "attenuate", False)
        b = preprocess.fft_mask(96, 128, 0.15, "attenuate", False)
        self.assertIs(a, b)
        self.assertFalse(a.flags.writeable)
        self.assertEqual(a.shape, (96, 128, 2))
        self.assertEqual(a.dtype, np.float32)
        np.testing.assert_array_equal(a[:, :, 0], a[:, :, 1])
        self.assertIsNot(a, preprocess.fft_mask(96, 128, 0.15, "attenuate", True))
        self.assertIsNot(a, preprocess.fft_mask(96, 128, 0.2, "attenuate", False))
