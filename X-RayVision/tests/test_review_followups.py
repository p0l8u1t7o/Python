"""PLAN-005：空洞範本預設模型、疊圖依判定著色"""
import cv2
import numpy as np

from synthetic_void import make_image
from test_models import REF, _import, client  # noqa: F401  (client 為 fixture)
from xrayvision.core.pipeline import Recipe, analyze_image
from xrayvision.core.render import JUDGE_BGR, judged_targets, render


def test_void_template_prefers_model(client):
    t = client.get("/api/recipe-template/void").json()
    p = t["modules"][0]["params"]
    assert p["method"] == "rule" and p["model"] == "" and t["_notice"] == "void_model_missing"
    assert _import(client).status_code == 200
    t = client.get("/api/recipe-template/void").json()
    p = t["modules"][0]["params"]
    assert p["method"] == "model" and p["model"] == REF and t["_notice"] is None
    # 模組參數預設值不變 (既有配方結果不受影響)；微凸塊範本不受影響
    mods = {m["module_id"]: m for m in client.get("/api/modules").json()}
    assert next(x for x in mods["void"]["params"] if x["key"] == "method")["default"] == "rule"
    b = client.get("/api/recipe-template/bump_alignment").json()
    assert b["_notice"] is None and "method" not in b["modules"][0]["params"]
    # 範本可直接存成配方 (多出的 _notice 不影響)
    body = dict(t, recipe_id="v-tpl", name={"zh-TW": "v"})
    body["modules"][0]["params"].update(ball_radius_min_px=40.0, ball_radius_max_px=100.0)
    r = client.post("/api/recipes", json={"body": body})
    assert r.status_code == 200, r.text
    assert r.json()["body"]["modules"][0]["params"]["method"] == "model"


def test_judged_targets():
    j = judged_targets(["void_pct_exceeds_limit:ball3", "void_pct_near_limit:ball4", "model_rule_disagree:ball3",
                        "die_shift_near_limit:group2", "total_void_pct_exceeds_limit:image", "no_balls_found"])
    assert j == {"ball3": "fail", "ball4": "review", "group2": "review"}


def test_render_marks_failed_balls(tmp_path):
    img, _truth = make_image(seed=3, pad=False)
    p = str(tmp_path / "v.tiff")
    cv2.imwrite(p, img)
    body = dict(recipe_id="v", version=1, name={}, modules=[dict(
        module_id="void", params=dict(ball_radius_min_px=40.0, ball_radius_max_px=100.0), judgment=dict(void_pct_max=1.0))])
    res, prep = analyze_image(p, Recipe.from_dict(body))
    m = res.modules[0]
    failed = [t for t, lv in judged_targets(m.judgment_reasons).items() if lv == "fail"]
    assert failed
    vis = render(prep.display, res)
    f = next(x for x in m.findings if x.flags.get("label") == failed[0])
    g = next(q for q in f.geometry.values() if q.get("type") == "circle")
    x, y, r = g["x"], g["y"], g["r"] * 1.18
    ring = [vis[int(round(y + r * np.sin(a))), int(round(x + r * np.cos(a)))] for a in np.linspace(0, 2 * np.pi, 24)]
    assert sum(np.abs(np.array(c, int) - JUDGE_BGR["fail"]).sum() < 60 for c in ring) >= 12
    # 未指到的影像不變 (無判定原因時與舊版相同)
    body["modules"][0]["judgment"] = dict(void_pct_max=100.0)
    ok, _ = analyze_image(p, Recipe.from_dict(body))
    assert not judged_targets(ok.modules[0].judgment_reasons)
