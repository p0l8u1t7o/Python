"""第 1 階段：成像條件對策 (品質閘門、平場校正、拍攝參數、斜射偵測、像素尺寸、不變性驗證)"""
import json

import cv2
import numpy as np
import pytest

from conftest import synth_absorption, to_intensity, vignette
from xrayvision.core import acquisition, quality, serialize, validation
from xrayvision.core.calibration import CalibrationError, CalibrationProfile, prepare
from xrayvision.core.io import load_image
from xrayvision.core.pipeline import Recipe, RecipeError, analyze_image


def recipe(**kw):
    d = {"recipe_id": "t", "version": 1, "modules": [{"module_id": "bump_alignment", "params": kw.pop("params", {})}]}
    d.update(kw)
    return Recipe.from_dict(d)


# ---------------------------------------------------------------------------
# 品質規則
# ---------------------------------------------------------------------------
def test_rule_levels():
    r = quality.QualityRule("x", warn_below=10, fail_below=5, warn_above=90, fail_above=95)
    assert [r.evaluate(v) for v in (3, 7, 50, 92, 99, None)] == ["fail", "warn", "pass", "warn", "fail", None]


def test_rules_merge_and_kind_filter():
    base = [quality.QualityRule("a", warn_below=1), quality.QualityRule("b", warn_below=1, kinds=("rgb8",))]
    over = [quality.QualityRule("a", fail_below=5)]
    rules = quality.merge_rules(base, over)
    level, checks = quality.evaluate({"a": 3, "b": 0}, rules, "raw16")
    assert level == "fail" and [c["metric"] for c in checks] == ["a"]      # b 不適用於 raw16


def test_recipe_quality_override_and_bad_rule():
    r = recipe(quality_rules=[{"metric": "image.snr", "warn_below": 1000}])
    snr = [x for x in r.rules() if x.metric == "image.snr"][0]
    assert snr.warn_below == 1000 and snr.fail_below is None
    with pytest.raises(RecipeError):
        recipe(quality_rules=[{"metric": "image.snr", "bogus": 1}])


def test_saturated_image_fails_gate(tmp_path):
    A = synth_absorption()
    I = to_intensity(A, gain=1.6)                  # 過曝：大片像素飽和
    p = str(tmp_path / "sat.tiff")
    cv2.imwrite(p, I)
    res, _ = analyze_image(p, recipe())
    assert res.quality["metrics"]["image.saturation_ratio"] > 0.01
    assert res.quality["level"] == "fail" and "image_quality_insufficient" in res.notes


def test_normal_synthetic_passes_gate(synth):
    res, _ = analyze_image(synth(), recipe())
    assert res.quality["level"] == "pass", [c for c in res.quality["checks"] if c["level"] != "pass"]


# ---------------------------------------------------------------------------
# 斜射偵測
# ---------------------------------------------------------------------------
def test_oblique_view_is_rejected(synth):
    res, _ = analyze_image(synth(squash=0.8), recipe())         # 約 37° 斜射
    m = res.quality["metrics"]
    assert m["bump_alignment.oblique_angle_deg"] > 30
    assert res.quality["level"] == "fail"
    res2, _ = analyze_image(synth("n.tiff"), recipe())
    assert res2.quality["metrics"]["bump_alignment.oblique_angle_deg"] < 10


# ---------------------------------------------------------------------------
# 暗場／平場校正
# ---------------------------------------------------------------------------
def test_flat_field_correction_restores_absorption(tmp_path):
    size = (600, 600)
    A = synth_absorption(size=size, pitch=90)
    field = vignette(size, 0.4)
    dark = np.full(size, 800.0, np.float32)
    raw = to_intensity(A, field=field, dark=dark, noise=0.0)
    p = str(tmp_path / "img.tiff")
    cv2.imwrite(p, raw)
    for i in range(3):                                           # 空拍與暗場各 3 張
        cv2.imwrite(str(tmp_path / f"flat{i}.tiff"), to_intensity(np.zeros(size, np.float32), gain=0.9, field=field,
                                                                  dark=dark, noise=0.002, seed=10 + i))
        cv2.imwrite(str(tmp_path / f"dark{i}.tiff"), np.full(size, 800, np.uint16))
    prof = CalibrationProfile.build("p1", [str(tmp_path / f"flat{i}.tiff") for i in range(3)],
                                    [str(tmp_path / f"dark{i}.tiff") for i in range(3)],
                                    conditions={"tube_voltage_kv": 90})
    prof.save(str(tmp_path / "calib"))
    prof = CalibrationProfile.load(str(tmp_path / "calib"), "p1")
    img = load_image(p)
    a_raw = prepare(img).absorption
    a_cal = prepare(img, profile=prof).absorption
    center = (slice(250, 350), slice(250, 350))
    corner = (slice(0, 60), slice(0, 60))
    # 校正前：角落 (暗角) 與中心的背景吸收量差很多；校正後幾乎一致
    bg = lambda a, s: float(np.percentile(a[s], 5))
    assert abs(bg(a_raw, corner) - bg(a_raw, center)) > 0.1
    assert abs(bg(a_cal, corner) - bg(a_cal, center)) < 0.01


def test_calibration_errors(tmp_path):
    cv2.imwrite(str(tmp_path / "f.tiff"), np.full((50, 50), 30000, np.uint16))
    cv2.imwrite(str(tmp_path / "f8.png"), np.full((50, 50), 200, np.uint8))
    with pytest.raises(CalibrationError) as e:
        CalibrationProfile.build("x", [str(tmp_path / "f8.png")])
    assert e.value.code == "calibration_requires_raw"
    with pytest.raises(CalibrationError) as e:
        CalibrationProfile.build("../evil", [str(tmp_path / "f.tiff")])
    assert e.value.code == "invalid_calibration_id"
    with pytest.raises(CalibrationError) as e:
        CalibrationProfile.load(str(tmp_path), "missing")
    assert e.value.code == "calibration_not_found"
    prof = CalibrationProfile.build("small", [str(tmp_path / "f.tiff")])
    with pytest.raises(CalibrationError) as e:
        prof.apply(np.zeros((60, 60), np.float32))
    assert e.value.code == "calibration_shape_mismatch"


# ---------------------------------------------------------------------------
# 拍攝參數
# ---------------------------------------------------------------------------
def test_acquisition_sidecar_and_aliases(synth, tmp_path):
    p = synth("a.tiff")
    with open(str(tmp_path / "a.json"), "w") as f:
        json.dump({"Tube Voltage (kV)": "90 kV", "Power [W]": 4.5, "Frames": 8, "Mode": "HighRes", "Operator": "A"}, f)
    acq = acquisition.collect(p)
    assert acq["source"] == "sidecar"
    assert acq["params"]["tube_voltage_kv"] == 90.0 and acq["params"]["tube_power_w"] == 4.5
    assert acq["params"]["frames"] == 8 and acq["params"]["tube_mode"] == "HighRes"
    assert acq["params"]["extra"] == {"Operator": "A"}


def test_acquisition_txt_manual_and_limits(synth, tmp_path):
    p = synth("b.tiff")
    (tmp_path / "b.txt").write_text("# settings\nkV = 130\nuA: 50\n", encoding="utf-8")
    assert acquisition.collect(p)["params"] == {"tube_voltage_kv": 130.0, "tube_current_ua": 50.0}
    manual = acquisition.parse_manual("kv=90, tilt=0")
    assert acquisition.collect(p, manual)["params"] == {"tube_voltage_kv": 90.0, "view_angle_deg": 0.0}
    r = recipe(acquisition_limits={"tube_voltage_kv": [60, 110]})
    res, _ = analyze_image(p, r)                                 # 參數檔 130 kV 超出範圍
    chk = [c for c in res.quality["checks"] if c["metric"] == "acquisition.tube_voltage_kv"][0]
    assert chk["level"] == "warn" and res.quality["level"] in ("warn", "fail")
    with pytest.raises(RecipeError):
        recipe(acquisition_limits={"not_a_param": [0, 1]})


# ---------------------------------------------------------------------------
# 像素尺寸
# ---------------------------------------------------------------------------
def test_pixel_size_from_design_pitch(synth):
    res, _ = analyze_image(synth(pitch=90), recipe(params={"design_pitch_um": 45.0}))
    s = res.modules[0].summary
    assert s["pixel_size_source"] == "design_pitch"
    assert s["pixel_size_um"] == pytest.approx(0.5, rel=0.01)
    assert s["die_shift"]["dx_um"] == pytest.approx(s["die_shift"]["dx"] * s["pixel_size_um"])
    f = res.modules[0].findings[0].measurements
    assert f["bump_r_um"] == pytest.approx(f["bump_r_px"] * s["pixel_size_um"])


def test_pitch_deviation_flags_wrong_recipe(synth):
    # 配方像素尺寸與設計間距不符 (實際 0.5 µm/px，配方寫 0.6) → 間距偏差 20% → 不合格
    res, _ = analyze_image(synth(pitch=90), recipe(pixel_size_um=0.6, params={"design_pitch_um": 45.0}))
    assert res.quality["metrics"]["bump_alignment.pitch_deviation"] == pytest.approx(0.2, abs=0.01)
    assert res.quality["level"] == "fail"


# ---------------------------------------------------------------------------
# 不變性驗證
# ---------------------------------------------------------------------------
def _results(paths, r):
    return [serialize.to_jsonable(analyze_image(p, r)[0]) for p in paths]


def test_invariance_passes_for_exposure_change(synth):
    ps = [synth("g1.tiff", shift=(0.8, 0.3), gain=1.0, seed=1), synth("g2.tiff", shift=(0.8, 0.3), gain=0.55, seed=2)]
    v = validation.invariance(_results(ps, recipe()), "bump_alignment", tolerance_px=0.1)
    assert v["passed"], v["spread"]
    pair = v["pairs"][0]["result"]
    assert pair is not None and pair["n"] >= 50
    assert pair["keys"]["dx_px"]["repeat_noise"] < 0.2


def test_invariance_fails_when_result_changes(synth):
    ps = [synth("h1.tiff", shift=(0.0, 0.0)), synth("h2.tiff", shift=(1.5, 0.0))]
    v = validation.invariance(_results(ps, recipe()), "bump_alignment", tolerance_px=0.2)
    assert not v["passed"] and v["spread"]["max_pairwise"] > 0.3
    md = validation.to_markdown(v, lambda k: k)
    assert "validation.failed" in md
