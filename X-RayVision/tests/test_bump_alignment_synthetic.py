"""微凸塊對位模組：合成影像驗證 (已知偏移、曝光強度不變性、8-bit 影像標示)"""
import cv2
import numpy as np
import pytest

from xrayvision.core.pipeline import Recipe, analyze_image

RECIPE = Recipe.from_dict({"recipe_id": "t", "version": 1, "modules": [{"module_id": "bump_alignment"}]})


def _shift(path):
    res, _ = analyze_image(path, RECIPE)
    m = res.modules[0]
    assert m.status == "ok", m.reasons
    return m.summary["die_shift"], m, res


def test_zero_offset_measures_near_zero(synth):
    e, m, _ = _shift(synth(shift=(0.0, 0.0)))
    assert m.summary["sites_used"] >= 50
    assert abs(e["dx"]) < 0.1 and abs(e["dy"]) < 0.1


def test_known_offset_direction_and_magnitude(synth):
    e, _, _ = _shift(synth(shift=(1.5, -1.0)))
    # 等高線法量到的是外形不對稱，幅度依焊墊對比而定；要求方向正確、幅度在合理範圍
    ang = np.degrees(np.arctan2(e["dy"], e["dx"]))
    assert abs(ang - np.degrees(np.arctan2(-1.0, 1.5))) < 10
    assert 0.3 < np.hypot(e["dx"], e["dy"]) < 2.5


def test_exposure_change_does_not_change_result(synth):
    """成像條件對策：曝光／管電流改變 (整體強度 x0.6) 時，量測結果應不變"""
    e1, _, _ = _shift(synth("a.tiff", shift=(1.0, 0.5), gain=1.0, seed=1))
    e2, _, _ = _shift(synth("b.tiff", shift=(1.0, 0.5), gain=0.6, seed=1))
    assert e1["dx"] == pytest.approx(e2["dx"], abs=0.05)
    assert e1["dy"] == pytest.approx(e2["dy"], abs=0.05)


def test_8bit_image_is_reference_only(synth, tmp_path):
    raw = cv2.imread(synth(), cv2.IMREAD_UNCHANGED)
    p8 = str(tmp_path / "s8.tif")
    cv2.imwrite(p8, cv2.cvtColor((raw / 257).astype(np.uint8), cv2.COLOR_GRAY2BGR))
    _, _, res = _shift(p8)
    assert res.image["kind"] == "rgb8"
    assert res.reference_only and "non_raw_image" in res.notes
