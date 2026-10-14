"""焊墊大幅偏移／完全分離的安全檢查 (PLAN-007 第 2.1 節)：不得判合格；正常影像不誤報、量測不變"""
import os

import pytest

from conftest import synth_raw16
from xrayvision.core.pipeline import Recipe, analyze_image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPE = Recipe.from_dict({"recipe_id": "t", "version": 1,
                           "modules": [{"module_id": "bump_alignment", "judgment": {"die_shift_max_px": 3.0}}]})


def _run(path):
    res, _ = analyze_image(path, RECIPE)
    m = res.modules[0]
    return m, (m.summary or {}).get("pad_separation") or {}


def test_small_offset_is_not_flagged(tmp_path):
    m, sep = _run(synth_raw16(str(tmp_path / "s.tiff"), shift=(1.0, 0.0)))
    assert sep["suspected"] is False
    assert sep["orphan_ratio"] < 0.2
    assert m.judgment == "pass"


@pytest.mark.parametrize("off", [32, 44, 56])
def test_separated_pads_never_pass(tmp_path, off):
    """焊墊完全分離：現有方法量到接近 0；安全檢查必須把判定壓到需複判以上"""
    m, sep = _run(synth_raw16(str(tmp_path / "s.tiff"), shift=(off, 0.0), pitch=90))
    assert sep["suspected"] is True
    assert sep["orphan_ratio"] >= 0.8
    assert m.judgment in ("review", "fail")
    assert "pad_separation_suspected" in m.judgment_reasons
    assert "pad_separation_suspected" in m.reasons


def test_pads_measured_as_bumps_are_flagged(tmp_path):
    """間距大、偏移大：分離的焊墊被當成凸塊量測 (採用點數加倍)，以低對比位點比例抓出"""
    m, sep = _run(synth_raw16(str(tmp_path / "s.tiff"), shift=(70.0, 0.0), pitch=160, size=(1120, 1120)))
    assert sep["suspected"] is True
    assert sep["low_contrast_ratio"] >= 0.25
    assert m.judgment != "pass"


def test_fail_is_kept_when_flagged(tmp_path):
    """量到的偏移已超出規格時維持不合格 (實際偏移只會更大)"""
    m, sep = _run(synth_raw16(str(tmp_path / "s.tiff"), shift=(24.0, 0.0), pitch=90))
    assert sep["suspected"] is True
    assert m.judgment == "fail"


@pytest.mark.regression
def test_real_images_are_not_flagged():
    files = [os.path.join(ROOT, "image", "Batch2", f"{i}.tiff") for i in range(1, 10)]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        pytest.skip("Batch2 images not available")
    for f in files:
        _, sep = _run(f)
        assert sep["suspected"] is False, (os.path.basename(f), sep)
        assert sep["orphan_ratio"] < 0.3 and sep["low_contrast_ratio"] < 0.1
