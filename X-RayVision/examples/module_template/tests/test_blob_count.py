"""範例模組的單元測試：合成影像 (已知數量的亮圓) → 數量正確、不受曝光影響、判定正確、顯示文字併入平台語系"""
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xrayvision.core import plugin  # noqa: E402
from xrayvision.core.pipeline import Recipe, analyze_image  # noqa: E402
from xrayvision.i18n import catalog  # noqa: E402
from xrayvision_blob_count import BlobCount  # noqa: E402


def make(tmp_path, n=6, gain=1.0):
    A = np.full((600, 900), 0.6, np.float32)
    for i in range(n):
        cv2.circle(A, (120 + 130 * i, 300), 40, 0.9, -1)
    A = cv2.GaussianBlur(A, (0, 0), 2)
    img = np.clip(65535 * np.exp(-A) * gain, 1, 65535).astype(np.uint16)
    p = str(tmp_path / f"b{n}_{gain}.tiff")
    cv2.imwrite(p, img)
    return p


@pytest.fixture(autouse=True)
def registered():
    plugin.register(BlobCount)                  # 安裝後由 entry point 自動載入；測試直接註冊
    catalog.cache_clear()
    yield
    plugin._REGISTRY.pop("blob_count", None)
    catalog.cache_clear()


def recipe(**judgment):
    return Recipe.from_dict(dict(recipe_id="blob", version=1, name={}, modules=[dict(
        module_id="blob_count", params=dict(radius_min_px=20.0, radius_max_px=80.0), judgment=judgment)]))


@pytest.mark.parametrize("gain", [0.5, 1.0, 2.0])
def test_count_is_exposure_invariant(tmp_path, gain):
    res, _ = analyze_image(make(tmp_path, 6, gain), recipe())
    assert res.modules[0].summary["count"] == 6


def test_judgment(tmp_path):
    p = make(tmp_path, 6)
    assert analyze_image(p, recipe(count_min=6, count_max=6))[0].modules[0].judgment == "pass"
    res, _ = analyze_image(p, recipe(count_min=7))
    assert res.modules[0].judgment == "fail" and res.modules[0].judgment_reasons == ["count_below_min"]


def test_translations_merged():
    assert catalog("zh-TW")["module.blob_count"] == "亮點計數（範例）"
    assert catalog("en")["reason.count_below_min"] == "Count below the minimum"
