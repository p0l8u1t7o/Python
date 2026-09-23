"""第 5b 階段：檢測區域"""
import math

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import synth_raw16
from synthetic_void import make_image
from xrayvision.config import Settings
from xrayvision.core import regions as R
from xrayvision.core.pipeline import Recipe, RecipeError, analyze_image
from xrayvision.service.api import create_app


def test_normalize_and_errors():
    assert R.normalize(None) is None and R.normalize({}) is None
    assert R.normalize(dict(reference=dict(width=100, height=80), include=[], exclude=[])) is None
    n = R.normalize(dict(reference=dict(width=100, height=80, run_id=3),
                         include=[dict(type="rect", x0=50, y0=40, x1=10, y1=5)],
                         exclude=[dict(type="polygon", points=[[0, 0], [10, 0], [0, 10]])]))
    assert n["include"][0] == dict(type="rect", x0=10.0, y0=5.0, x1=50.0, y1=40.0)
    assert n["reference"] == dict(width=100, height=80, run_id=3)
    for bad in (dict(include=[dict(type="rect", x0=0, y0=0, x1=5, y1=5)]),                    # 沒有參考尺寸
                dict(reference=dict(width=10, height=10), include=[dict(type="circle")]),
                dict(reference=dict(width=10, height=10), include=[dict(type="polygon", points=[[0, 0], [1, 1]])]),
                dict(reference=dict(width=10, height=10), include=[dict(type="rect", x0=0, y0=0, x1="a", y1=3)])):
        with pytest.raises(R.RegionError):
            R.normalize(bad)


def test_mask_include_exclude_and_scaling():
    reg = R.normalize(dict(reference=dict(width=100, height=100),
                           include=[dict(type="rect", x0=10, y0=10, x1=60, y1=60)],
                           exclude=[dict(type="rect", x0=20, y0=20, x1=30, y1=30)]))
    m, scaled = R.build_mask(reg, (100, 100))
    assert not scaled and m[40, 40] and not m[5, 5] and not m[25, 25]
    m2, scaled = R.build_mask(reg, (200, 200))                           # 影像尺寸加倍：座標依比例縮放
    assert scaled and m2[80, 80] and not m2[50, 50] and not m2[150, 150]
    ex = R.normalize(dict(reference=dict(width=100, height=100), exclude=[dict(type="rect", x0=0, y0=0, x1=50, y1=100)]))
    m3, _ = R.build_mask(ex, (100, 100))                                 # 只有排除區域：其餘都檢測
    assert not m3[50, 10] and m3[50, 80]
    assert R.inside(None, 5, 5) and not R.inside(m3, 10, 50) and not R.inside(m3, 500, 5)


def test_recipe_rejects_invalid_regions():
    body = dict(recipe_id="x", version=1, name={}, modules=[dict(module_id="void", params={})],
                regions=dict(include=[dict(type="rect", x0=0, y0=0, x1=10, y1=10)]))
    with pytest.raises(RecipeError) as e:
        Recipe.from_dict(body)
    assert e.value.code == "invalid_regions"


def test_void_only_inside_region(tmp_path):
    img, truth = make_image(seed=2, pad=False)
    p = str(tmp_path / "v.tiff")
    cv2.imwrite(p, img)
    H, W = img.shape
    base = dict(recipe_id="v", version=1, name={}, modules=[dict(
        module_id="void", params=dict(ball_radius_min_px=40.0, ball_radius_max_px=100.0), judgment={})])
    full, _ = analyze_image(p, Recipe.from_dict(base))
    # 邊界放在焊球列與列之間 (焊球間距 190 px)
    def groups(vals):                                                    # 依間距 > 50 px 分欄／列
        vals, out = sorted(vals), []
        for v in vals:
            if out and v - out[-1][-1] < 50:
                out[-1].append(v)
            else:
                out.append([v])
        return [float(np.mean(g)) for g in out]
    xs, ys = groups(b.x for b in truth), groups(b.y for b in truth)
    xcut, ycut = (xs[1] + xs[2]) / 2, (ys[0] + ys[1]) / 2
    body = dict(base, regions=dict(reference=dict(width=W, height=H),
                                   include=[dict(type="rect", x0=0, y0=0, x1=xcut, y1=H)],
                                   exclude=[dict(type="rect", x0=0, y0=0, x1=xcut, y1=ycut)]))
    part, _ = analyze_image(p, Recipe.from_dict(body))
    keep = [b for b in truth if b.x < xcut and b.y >= ycut]
    balls = [f for f in part.modules[0].findings if f.category == "ball"]
    assert len(balls) == len(keep) < len([f for f in full.modules[0].findings if f.category == "ball"])
    assert all(f.geometry["ball"]["x"] < xcut and f.geometry["ball"]["y"] >= ycut for f in balls)
    assert part.recipe["regions"]["include"] and "regions_scaled" not in part.notes
    # 區域外的焊點不計入未量測
    assert part.modules[0].summary["balls_unmeasured"] == 0


def test_bump_alignment_region_and_unchanged_without(tmp_path):
    p = synth_raw16(str(tmp_path / "b.tiff"), shift=(0.5, 0.0))
    body = dict(recipe_id="b", version=1, name={}, modules=[dict(module_id="bump_alignment", params={})])
    full, _ = analyze_image(p, Recipe.from_dict(body))
    again, _ = analyze_image(p, Recipe.from_dict(dict(body, regions=None)))
    assert full.modules[0].summary["sites_measured"] == again.modules[0].summary["sites_measured"]
    H, W = full.image["height"], full.image["width"]
    half = dict(body, regions=dict(reference=dict(width=W, height=H), include=[dict(type="rect", x0=0, y0=0, x1=W, y1=H / 2)]))
    part, _ = analyze_image(p, Recipe.from_dict(half))
    sites = [f for f in part.modules[0].findings if f.category == "bump_site"]
    assert 0 < len(sites) < full.modules[0].summary["sites_measured"]
    assert all(f.geometry["bump"]["y"] < H / 2 + 5 for f in sites)


def test_regions_saved_through_api(tmp_path):
    settings = Settings(data_dir=str(tmp_path / "data"))
    app = create_app(settings, workers=1, watch=False, start=False, enforce_license=False)
    c = TestClient(app)
    c.post("/api/auth/setup", json={"username": "eng", "password": "Passw0rd!"})
    reg = dict(reference=dict(width=1000, height=800), include=[dict(type="polygon", points=[[0, 0], [500, 0], [0, 500]])])
    body = dict(recipe_id="r1", version=1, name={"zh-TW": "r"}, modules=[dict(module_id="void", params={})], regions=reg)
    r = c.post("/api/recipes", json={"body": body})
    assert r.status_code == 200, r.text
    assert r.json()["body"]["regions"]["include"][0]["points"][1] == [500.0, 0.0]
    bad = dict(body, regions=dict(include=reg["include"]))
    r = c.post("/api/recipes", json={"body": bad})
    assert r.status_code == 400 and r.json()["error"] == "invalid_regions"
