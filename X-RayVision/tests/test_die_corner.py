"""晶片角點偵測 (PLAN-006 第 3 節)：合成圖組的角點與角落位置、搜尋區域、配方設定、實際影像"""
import json
import os

import numpy as np
import pytest

import synthetic_die_set as sds
from xrayvision.core import die_corner, image_set
from xrayvision.core.pipeline import Recipe, RecipeError, analyze_image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIFT, THETA = (1.2, -0.8), 0.3


@pytest.fixture(scope="module")
def views():
    """四角與一張中間視野的吸收量影像，以及角點的正確位置 (影像像素)"""
    out = {}
    H, W = sds.FOV
    for name, pos, center in sds.views(SHIFT, THETA):
        A = sds.render(center, SHIFT, THETA)
        truth = None
        if pos:
            g = sds.corner_truth(pos, SHIFT, THETA)
            truth = (g[0] - center[0] + W / 2, g[1] - center[1] + H / 2)
        out[name] = (A, pos, truth)
    return out


def test_four_corners_found_with_correct_position(views):
    for name, (A, pos, truth) in views.items():
        r = die_corner.detect(A)
        if pos is None:
            assert not r["found"] and r["reason"] in ("no_die_edge", "no_die_corner"), (name, r["reason"])
            continue
        assert r["found"], (name, r["reason"])
        assert r["position"] == pos
        assert np.hypot(r["x"] - truth[0], r["y"] - truth[1]) <= 2.0, (name, r["x"], r["y"], truth)
        assert r["angle_deg"] == pytest.approx(THETA, abs=0.1)
        assert len(r["edges"]) == 2


def test_position_hint_restricts_search(views):
    A, _, _ = views["top_left"]
    assert die_corner.detect(A, position="top_left")["found"]
    assert not die_corner.detect(A, position="bottom_right")["found"]


def test_search_region(views):
    A, _, truth = views["bottom_right"]
    x, y = truth
    r = die_corner.detect(A, region=(x - 300, y - 300, x + 300, y + 300))
    assert r["found"] and r["position"] == "bottom_right"
    assert np.hypot(r["x"] - x, r["y"] - y) <= 8.0
    # 區域內沒有角點 (晶片內部)
    assert not die_corner.detect(A, region=(0, 0, 250, 250))["found"]
    assert die_corner.detect(A, region=(10, 10, 20, 20))["reason"] == "search_region_too_small"


def test_exposure_does_not_move_corner(views):
    A, _, _ = views["top_left"]
    # 吸收量加常數 (曝光改變) 不影響角點；加雜訊時移動在合成影像準確度 (2 px) 以內
    r1 = die_corner.detect(A)
    assert die_corner.detect(A + 0.3)["x"] == pytest.approx(r1["x"], abs=0.01)
    r2 = die_corner.detect(A + 0.3 + np.random.default_rng(1).normal(0, 0.004, A.shape).astype(np.float32))
    assert np.hypot(r1["x"] - r2["x"], r1["y"] - r2["y"]) <= 2.0


def test_image_set_config_normalize():
    assert image_set.normalize(None) is None
    assert image_set.normalize({"enabled": False}) is None
    cfg = image_set.normalize({"enabled": True, "reference": {"width": 1000, "height": 800},
                               "corner_regions": [{"type": "rect", "x0": 500, "y0": 0, "x1": 0, "y1": 400,
                                                   "position": "top_left"}]})
    assert cfg["corner_regions"][0]["x0"] == 0 and cfg["corner_regions"][0]["x1"] == 500
    # 尺寸不同時依比例縮放
    (box, pos), = image_set.scaled_regions(cfg, (1600, 2000))
    assert box == (0, 0, 1000, 800) and pos == "top_left"
    with pytest.raises(Exception):
        image_set.normalize({"enabled": True, "corner_regions": [{"type": "rect", "x0": 0, "y0": 0, "x1": 100, "y1": 100}]})
    with pytest.raises(Exception):
        image_set.normalize({"enabled": True, "reference": {"width": 10, "height": 10},
                             "corner_regions": [{"type": "rect", "x0": 0, "y0": 0, "x1": 100, "y1": 100,
                                                 "position": "middle"}]})


def _recipe(image_set_cfg=None):
    d = {"recipe_id": "t", "version": 1, "modules": [{"module_id": "bump_alignment"}]}
    if image_set_cfg is not None:
        d["image_set"] = image_set_cfg
    return Recipe.from_dict(d)


def test_pipeline_detects_corner_only_when_enabled(tmp_path):
    t = sds.make_set(str(tmp_path), SHIFT, THETA, interior=0)
    path = str(tmp_path / "top_left.tiff")
    res, _ = analyze_image(path, _recipe())
    assert res.die_corner is None
    res, _ = analyze_image(path, _recipe({"enabled": True}))
    c = res.die_corner
    assert c["found"] and c["position"] == "top_left" and c["source"] == "auto"
    tx, ty = t["images"]["top_left"]["corner_px"]
    assert np.hypot(c["x"] - tx, c["y"] - ty) <= 3.0
    # 配方搜尋區域
    H, W = sds.FOV
    cfg = {"enabled": True, "reference": {"width": W, "height": H},
           "corner_regions": [{"type": "rect", "x0": tx - 300, "y0": ty - 300, "x1": tx + 300, "y1": ty + 300,
                               "position": "top_left"}]}
    c = analyze_image(path, _recipe(cfg))[0].die_corner
    assert c["found"] and c["source"] == "recipe_region" and c["region"] == 1
    # 角點只是附加資訊，不影響單張判定與量測
    assert json.dumps(res.modules[0].summary["die_shift"], sort_keys=True) == \
        json.dumps(analyze_image(path, _recipe())[0].modules[0].summary["die_shift"], sort_keys=True)


def test_invalid_image_set_is_recipe_error():
    with pytest.raises(RecipeError) as e:
        _recipe({"enabled": True, "corner_regions": "x"})
    assert e.value.code == "invalid_image_set"


@pytest.mark.regression
def test_batch2_corners():
    from xrayvision.core.calibration import prepare
    from xrayvision.core.io import load_image
    expect = {1: "top_left", 2: "top_left", 4: "top_left", 8: "bottom_right", 9: "bottom_left",
              3: None, 5: None, 6: None, 7: None}
    got = {}
    for i, pos in expect.items():
        f = os.path.join(ROOT, "image", "Batch2", f"{i}.tiff")
        if not os.path.isfile(f):
            pytest.skip("Batch2 images not available")
        r = die_corner.detect(prepare(load_image(f)).absorption)
        assert r["position"] == pos, (i, r["position"], r["reason"])
        got[i] = r
    # 1 與 2 為同視野重拍 (影像位移 < 0.1 px)：角點差 <= 5 px (邊緣為寬緩坡，見規劃書第 8.2 節)
    assert np.hypot(got[1]["x"] - got[2]["x"], got[1]["y"] - got[2]["y"]) <= 5.0
    assert got[5]["reason"] == "single_edge" and got[5]["edge_only"]["side"] == "top"


# ---------------------------------------------------------------------------
# 服務：配方啟用圖組量測、手動指定角點 (只新增、可改回自動、稽核)
# ---------------------------------------------------------------------------
def test_service_corner_and_manual_override(tmp_path):
    import sqlite3

    from fastapi.testclient import TestClient
    from test_service import _wait, recipe_body
    from xrayvision.config import Settings
    from xrayvision.service.api import create_app

    sds.make_set(str(tmp_path / "set"), SHIFT, THETA, interior=0)
    app = create_app(Settings(data_dir=str(tmp_path / "data")), workers=1, watch=False, enforce_license=False)
    with TestClient(app) as c:
        c.platform = app.state.platform
        assert c.post("/api/auth/setup", json={"username": "eng", "password": "Passw0rd!"}).status_code == 200
        body = recipe_body()
        body["image_set"] = {"enabled": True}
        pk = c.post("/api/recipes", json={"body": body}).json()["id"]
        assert c.post(f"/api/recipes/{pk}/release").status_code == 200
        with open(tmp_path / "set" / "top_left.tiff", "rb") as fh:
            r = c.post("/api/imports", files=[("files", ("top_left.tiff", fh, "image/tiff"))], data={"recipe_pk": str(pk)})
        assert r.status_code == 200, r.text
        _wait(c)
        run = c.get("/api/runs").json()["items"][0]
        d = c.get(f"/api/runs/{run['id']}").json()
        assert d["result"]["die_corner"]["found"] and d["result"]["die_corner"]["position"] == "top_left"
        assert d["manual_corner"] is None
        url = f"/api/runs/{run['id']}/corner"
        assert c.put(url, json={"position": "middle", "x": 1, "y": 1}).status_code == 400
        assert c.put(url, json={"position": "top_left", "x": 99999, "y": 1}).status_code == 400
        r = c.put(url, json={"position": "top_left", "x": 350.5, "y": 270.0, "angle_deg": 0.2})
        assert r.status_code == 200 and r.json()["manual_corner"]["x"] == 350.5
        assert c.get(f"/api/runs/{run['id']}").json()["manual_corner"]["actor"] == "eng"
        assert c.put(url, json={"clear": True}).json()["manual_corner"] is None
        assert c.get(f"/api/runs/{run['id']}").json()["manual_corner"] is None
        actions = [a["action"] for a in c.get("/api/audit").json()]
        assert "image.corner_manual" in actions and "image.corner_cleared" in actions
        with pytest.raises(sqlite3.IntegrityError):
            c.platform.db.execute("UPDATE image_corners SET x = 0")
