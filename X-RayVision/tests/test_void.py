"""第 5a 階段：空洞檢測模組、模組驗證狀態"""
import glob
import math
import os

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from synthetic_void import make_image
from xrayvision.config import Settings
from xrayvision.core import judge, plugin
from xrayvision.core.calibration import prepare
from xrayvision.core.io import load_image
from xrayvision.core.pipeline import Recipe, analyze_image, module_series
from xrayvision.core.plugin import Finding, ModuleResult
from xrayvision.core.units import add_um
from xrayvision.inspections.void import algorithm as V
from xrayvision.service.api import create_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _absorb(img):
    return -np.log(np.clip(img.astype(np.float32), 1, None) / 65535)


def _match(out, b):
    return min(out["balls"], key=lambda o: math.hypot(o["x"] - b.x, o["y"] - b.y))


def _pad_clear(b):
    """焊墊未被空洞覆蓋 (被空洞蓋住的焊墊無法由影像還原，屬量測極限，另行說明)"""
    return not b.pad or all(math.hypot(b.pad[0] - vx, b.pad[1] - vy) > vr + b.pad[2] for vx, vy, vr in b.voids)


def void_recipe(limit=25.0, **params):
    return dict(recipe_id="void-a", version=1, name={"zh-TW": "空洞", "en": "Void"},
                modules=[dict(module_id="void", params=dict(ball_radius_min_px=40.0, ball_radius_max_px=100.0, **params),
                              judgment=dict(void_pct_max=limit))])


# ---------------------------------------------------------------------------
# 演算法 (合成影像)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pad", [False, True])
def test_void_accuracy_and_no_false_calls(pad):
    errs, clean_hits, clean = [], 0, 0
    # 有焊墊時多數空洞與焊墊重疊 (不列入準確度)，需要較多影像才有足夠樣本
    for seed in ((1, 2, 3, 4, 5, 6, 7, 8) if pad else (1, 2, 3)):
        img, truth = make_image(seed=seed, pad=pad)
        out = V.analyze(_absorb(img), dict(V.DEFAULTS))
        assert len(out["balls"]) == len(truth)                          # 全部焊點都找到
        for b in truth:
            o = _match(out, b)
            assert math.hypot(o["x"] - b.x, o["y"] - b.y) < 2.0 and abs(o["r"] - b.r) < 2.0
            if not b.voids:
                clean += 1
                clean_hits += o["void_count"] > 0
            elif _pad_clear(b):
                errs.append(o["void_pct"] - b.void_pct(img.shape))
    e = np.abs(errs)
    assert len(e) >= (3 if pad else 10) and clean > 10
    assert clean_hits == 0, clean_hits                                  # 無空洞焊點不誤報
    assert np.percentile(e, 95) <= 2.0 and e.max() <= 3.0, (np.percentile(e, 95), e.max())
    assert abs(np.mean(errs)) <= 0.8


def test_void_detection_rate():
    """直徑 >= 焊球直徑 15% 的空洞，面積一半以上被標出"""
    hit = total = 0
    for seed in (1, 2, 3, 4):
        img, truth = make_image(seed=seed, pad=False)
        out = V.analyze(_absorb(img), dict(V.DEFAULTS))
        for b in truth:
            o = _match(out, b)
            M = np.zeros(img.shape, np.uint8)
            for v in o["voids"]:
                cv2.fillPoly(M, [np.array(v["contour"], np.int32)], 1)
            for vx, vy, vr in b.voids:
                if vr / b.r < 0.15:
                    continue
                T = np.zeros(img.shape, np.uint8)
                cv2.circle(T, (int(round(vx)), int(round(vy))), int(round(vr)), 1, -1)
                total += 1
                hit += (M & T).sum() >= 0.5 * T.sum()
    assert total > 40 and hit / total >= 0.95, (hit, total)


def test_void_imaging_condition_invariance():
    """曝光與吸收量改變時，同一焊點空洞率的系統性偏移 (兩次雜訊平均) 維持在約 1 個百分點"""
    def run(**kw):
        vals = []
        for n in (11, 12):
            img, truth = make_image(seed=2, pad=False, noise_seed=n, **kw)
            out = V.analyze(_absorb(img), dict(V.DEFAULTS))
            vals.append([_match(out, b)["void_pct"] for b in truth])
        return np.mean(vals, 0)
    ref = run()
    for kw in (dict(exposure=0.5), dict(power=1.5), dict(power=0.6, exposure=2.0)):
        d = np.abs(run(**kw) - ref)
        assert np.percentile(d, 95) <= 1.5 and d.max() <= 2.0, (kw, np.percentile(d, 95), d.max())


def test_large_near_rim_voids_are_not_missed():
    """靠近邊緣的大空洞 (>= 30%) 不能被量成遠低於規格 (漏判風險)；無法量測時必須列入未量測"""
    for seed in (4, 6):
        img, truth = make_image(seed=seed, pad=False, max_rho=0.97)
        out = V.analyze(_absorb(img), dict(V.DEFAULTS))
        for b in truth:
            tv = b.void_pct(img.shape)
            if tv >= 30:
                o = _match(out, b)
                assert (not o["used"]) or o["void_pct"] >= 25.0, (tv, o["void_pct"])


# ---------------------------------------------------------------------------
# 模組外殼與判定
# ---------------------------------------------------------------------------
def test_units_area():
    d = add_um(dict(r_px=10.0, area_px2=100.0, void_pct=5.0, flag=True), 2.0)
    assert d["r_um"] == 20.0 and d["area_um2"] == 400.0 and "void_pct_um" not in d


def _ball(i, pct, se=0.5, used=True):
    return Finding(id=i, category="ball", geometry={}, used=used,
                   measurements=dict(void_pct=pct, largest_void_pct=pct, void_pct_se=se), flags=dict(label=f"ball{i}"))


def test_void_judge_rules():
    cls = plugin.get("void")
    mod = cls()
    spec = cls.resolve_judgment(dict(void_pct_max=25.0))
    ok = ModuleResult("void", cls.version, "ok", {}, findings=[_ball(1, 3.0), _ball(2, 10.0)],
                      summary=dict(balls_unmeasured=0))
    assert mod.judge(ok, spec) == ("pass", [])
    bad = ModuleResult("void", cls.version, "ok", findings=[_ball(1, 3.0), _ball(2, 30.0)], params={},
                       summary=dict(balls_unmeasured=0))
    level, reasons = mod.judge(bad, spec)
    assert level == "fail" and reasons == ["void_pct_exceeds_limit:ball2"]
    near = ModuleResult("void", cls.version, "ok", findings=[_ball(1, 24.5)], params={},
                        summary=dict(balls_unmeasured=0))
    assert mod.judge(near, spec)[0] == "review"                         # 24.5 + 2 x 0.5 > 25
    # 允許一顆超規：合格
    assert mod.judge(bad, cls.resolve_judgment(dict(void_pct_max=25.0, max_failed_balls=1)))[0] == "pass"
    # 有未量測焊點：需複判
    unm = ModuleResult("void", cls.version, "ok", findings=[_ball(1, 3.0)], params={},
                       summary=dict(balls_unmeasured=2))
    assert mod.judge(unm, spec) == ("review", ["balls_not_measured"])
    # 未設定任何上限：未判定
    assert mod.judge(ok, cls.resolve_judgment(dict(void_pct_max=None)))[0] == "not_judged"


def test_pipeline_judgment_and_unvalidated_cap(tmp_path):
    img, truth = make_image(seed=2, pad=False)
    p = str(tmp_path / "v.tiff")
    cv2.imwrite(p, img)
    recipe = Recipe.from_dict(void_recipe())
    assert any(b.void_pct(img.shape) > 27 for b in truth)
    res, _ = analyze_image(p, recipe)                                   # 不檢查驗證狀態 (工程用)
    assert res.judgment == "fail" and not res.unvalidated_modules
    res, _ = analyze_image(p, recipe, validated=[["bump_alignment", "1.1"]])
    assert res.unvalidated_modules == ["void"] and "module_unvalidated" in res.notes
    assert res.judgment == "review" and "void.module_unvalidated" in res.judgment_reasons
    res, _ = analyze_image(p, recipe, validated=[["void", module_series(plugin.get("void").version)]])
    assert res.judgment == "fail" and not res.unvalidated_modules
    m = res.modules[0]
    balls = [f for f in m.findings if f.category == "ball"]
    voids = [f for f in m.findings if f.category == "void"]
    assert len(balls) == len(truth) and voids and all(v.geometry["void"]["type"] == "polygon" for v in voids)
    assert m.summary["max_void_pct"] > 25 and m.summary["balls_measured"] == len(truth)


def test_pixel_size_gives_um2(tmp_path):
    img, _ = make_image(seed=3, pad=False)
    p = str(tmp_path / "v.tiff")
    cv2.imwrite(p, img)
    body = void_recipe()
    body["pixel_size_um"] = 0.5
    res, _ = analyze_image(p, Recipe.from_dict(body))
    b = next(f for f in res.modules[0].findings if f.category == "ball")
    assert b.measurements["ball_area_um2"] == pytest.approx(b.measurements["ball_area_px2"] * 0.25)


# ---------------------------------------------------------------------------
# 模組驗證狀態 (API)
# ---------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=str(tmp_path / "data"))
    app = create_app(settings, workers=1, watch=False, enforce_license=False)
    with TestClient(app) as c:
        c.platform = app.state.platform
        assert c.post("/api/auth/setup", json={"username": "eng", "password": "Passw0rd!"}).status_code == 200
        yield c


def test_module_validation_api_and_judgment(client, tmp_path):
    st = {m["module_id"]: m for m in client.get("/api/modules/validation").json()}
    assert st["bump_alignment"]["status"] == "validated"                # 資料庫升級時標示
    assert st["void"]["status"] == "unvalidated"
    assert {m["module_id"]: m["validation"] for m in client.get("/api/modules").json()}["void"] == "unvalidated"
    # 分析：未驗證 → 需複判
    r = client.post("/api/recipes", json={"body": void_recipe()})
    pk = r.json()["id"]
    assert client.post(f"/api/recipes/{pk}/release").status_code == 200
    img, _ = make_image(seed=2, pad=False)
    p = str(tmp_path / "v.tiff")
    cv2.imwrite(p, img)
    with open(p, "rb") as f:
        r = client.post("/api/imports", files=[("files", ("v.tiff", f, "image/tiff"))], data={"recipe_pk": str(pk)})
    assert r.status_code == 200, r.text
    assert client.platform.queue.wait_idle(180)
    run = client.get("/api/runs").json()["items"][0]
    assert run["auto_judgment"] == "review"
    detail = client.get(f"/api/runs/{run['id']}").json()
    assert detail["result"]["unvalidated_modules"] == ["void"]
    # 核准須填說明；核准後重新分析 → 正式判定
    r = client.post("/api/modules/void/validation", json={"status": "validated"})
    assert r.status_code == 400 and r.json()["error"] == "validation_note_required"
    r = client.post("/api/modules/void/validation", json={"status": "validated", "note": "synthetic set", "report_name": "VR-1"})
    assert r.status_code == 200 and r.json()["status"] == "validated" and r.json()["approved_by"] == "eng"
    r = client.post("/api/modules/void/validation", json={"status": "validated", "note": "again"})
    assert r.json()["error"] == "validation_status_unchanged"
    assert client.post("/api/modules/nope/validation", json={"status": "revoked"}).status_code == 404
    r = client.post(f"/api/images/{run['image_id']}/reanalyze", json={"recipe_pk": pk})
    assert r.status_code == 200, r.text
    assert client.platform.queue.wait_idle(180)
    latest = client.get("/api/runs").json()["items"][0]
    assert latest["id"] != run["id"] and latest["auto_judgment"] == "fail"
    # 撤銷與稽核
    r = client.post("/api/modules/void/validation", json={"status": "revoked", "note": "field images pending"})
    assert r.json()["status"] == "unvalidated" and len(r.json()["history"]) == 2
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert "module.validate" in actions and "module.revoke" in actions


# ---------------------------------------------------------------------------
# 實際影像：Batch1／Batch2 沒有可見空洞
# ---------------------------------------------------------------------------
@pytest.mark.regression
def test_real_images_bga_balls_without_voids():
    files = [os.path.join(ROOT, "image", "Batch2", f"{i}.tiff") for i in (1, 2, 4, 8, 9)]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        pytest.skip("regression images not available")
    cfg = dict(V.DEFAULTS, r_min=55.0, r_max=95.0)
    measured = flagged = 0
    for f in files:
        out = V.analyze(prepare(load_image(f)).absorption, cfg)
        used = [b for b in out["balls"] if b["used"]]
        measured += len(used)
        flagged += sum(1 for b in used if b["void_pct"] > 3.0)
    assert measured >= 70 and flagged == 0, (measured, flagged)


@pytest.mark.regression
def test_real_8bit_images_no_voids():
    files = sorted(glob.glob(os.path.join(ROOT, "image", "Batch1", "*.tif")))[:4]
    if not files:
        pytest.skip("regression images not available")
    for f in files:
        out = V.analyze(prepare(load_image(f)).absorption, dict(V.DEFAULTS))
        assert all(b["void_count"] == 0 for b in out["balls"] if b["used"]), f


def test_no_out_of_spec_ball_is_missed_or_passed():
    """
    安全性：實際空洞率 >= 25% 的焊點，不可漏偵測，也不可判為合格 (空洞率 + 2 x 估計誤差 <= 25)。
    空洞蓋住焊墊時量測值偏低 (量測極限)，以擴大估計誤差轉為需複判
    """
    for seed, kw in [(s, {}) for s in (1, 2, 5)] + [(s, dict(max_rho=0.97)) for s in (1, 2)] + \
                    [(3, dict(void_rate=0.9))]:
        img, truth = make_image(seed=seed, **kw)
        out = V.analyze(_absorb(img), dict(V.DEFAULTS))
        assert len(out["balls"]) == len(truth), (seed, kw)
        for b in truth:
            if b.void_pct(img.shape) >= 25:
                o = _match(out, b)
                assert math.hypot(o["x"] - b.x, o["y"] - b.y) < 0.3 * b.r
                assert (not o["used"]) or o["void_pct"] + 2 * o["void_pct_se"] > 25, (seed, kw, o["void_pct"])
