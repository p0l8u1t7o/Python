"""第 5c／5d 階段：深度學習推論、模型管理、標註與訓練資料匯出"""
import io
import json
import math
import os
import sys
import zipfile

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from synthetic_void import make_image
from xrayvision.config import Settings
from xrayvision.core import inference, modelpkg
from xrayvision.core.pipeline import Recipe, analyze_image
from xrayvision.inspections.void import algorithm as V
from xrayvision.service.api import create_app
from xrayvision.service.updates import PUBLIC_KEY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "tests", "data", "void_unet-1.0.0.xrvmodel")
REF = "void_unet@1.0.0"
DEV_KEY = os.path.join(ROOT, "tools", "keys", "update_private_DEV.pem")

pytestmark = pytest.mark.skipif(not inference.available()["installed"], reason="onnxruntime not installed")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    meta, data = modelpkg.verify(DEMO, PUBLIC_KEY)
    p = tmp_path_factory.mktemp("m") / "model.onnx"
    p.write_bytes(data)
    return dict(path=str(p), meta=meta)


def _absorb(img):
    return -np.log(np.clip(img.astype(np.float32), 1, None) / 65535)


# ---------------------------------------------------------------------------
# 模型檔
# ---------------------------------------------------------------------------
def test_model_package_verification(tmp_path):
    meta, data = modelpkg.verify(DEMO, PUBLIC_KEY)
    assert meta["model_id"] == "void_unet" and meta["module_id"] == "void" and meta["task"] == "void_segmentation"
    assert modelpkg.split_ref(REF) == ("void_unet", "1.0.0")
    # 竄改 model.onnx
    bad = tmp_path / "bad.xrvmodel"
    with zipfile.ZipFile(DEMO) as zin, zipfile.ZipFile(bad, "w") as zout:
        for n in zin.namelist():
            b = zin.read(n)
            zout.writestr(n, b[:-1] + bytes([b[-1] ^ 1]) if n == "model.onnx" else b)
    with pytest.raises(modelpkg.ModelPackageError) as e:
        modelpkg.verify(str(bad), PUBLIC_KEY)
    assert e.value.code == "model_hash_mismatch"
    # 竄改 model.json (簽章失效)
    bad2 = tmp_path / "bad2.xrvmodel"
    with zipfile.ZipFile(DEMO) as zin, zipfile.ZipFile(bad2, "w") as zout:
        for n in zin.namelist():
            b = zin.read(n)
            zout.writestr(n, b.replace(b'"1.0.0"', b'"9.0.0"') if n == "model.json" else b)
    with pytest.raises(modelpkg.ModelPackageError) as e:
        modelpkg.verify(str(bad2), PUBLIC_KEY)
    assert e.value.code == "model_signature_invalid"
    (tmp_path / "x.xrvmodel").write_bytes(b"not a zip")
    with pytest.raises(modelpkg.ModelPackageError):
        modelpkg.verify(str(tmp_path / "x.xrvmodel"), PUBLIC_KEY)


# ---------------------------------------------------------------------------
# 推論
# ---------------------------------------------------------------------------
def test_model_method_accuracy(demo):
    errs, clean_hits, clean = [], 0, 0
    for seed in (21, 22, 23):
        img, truth = make_image(seed=seed, pad=False)
        out = V.analyze(_absorb(img), dict(V.DEFAULTS, method="model"), model=demo)
        for b in truth:
            o = min(out["balls"], key=lambda q: math.hypot(q["x"] - b.x, q["y"] - b.y))
            if b.voids:
                errs.append(o["void_pct"] - b.void_pct(img.shape))
                assert "void_pct_rule" in o and "void_pct_model" in o
            else:
                clean += 1
                clean_hits += o["void_count"] > 0
    e = np.abs(errs)
    assert clean_hits == 0 and np.percentile(e, 95) <= 2.0, (clean_hits, np.percentile(e, 95))


def test_both_method_agreement_and_disagreement(demo):
    img, truth = make_image(seed=24, pad=False)
    A = _absorb(img)
    out = V.analyze(A, dict(V.DEFAULTS, method="both"), model=demo)
    diffs = [abs(b["void_pct_model"] - b["void_pct_rule"]) for b in out["balls"] if b["used"]]
    assert np.percentile(diffs, 95) <= 3.0                              # 規劃書：與規則式差異 <= 3 個百分點
    for b in out["balls"]:
        if b["used"]:
            assert b["void_pct"] == pytest.approx(max(b["void_pct_rule"], b["void_pct_model"]))
            assert b["model_disagree"] == (abs(b["void_pct_model"] - b["void_pct_rule"]) > 3.0)


def test_module_model_resolution(tmp_path, demo):
    img, _ = make_image(seed=25, pad=False)
    p = str(tmp_path / "v.tiff")
    cv2.imwrite(p, img)

    def body(method, model=REF):
        return dict(recipe_id="m", version=1, name={}, modules=[dict(module_id="void", judgment=dict(void_pct_max=25.0),
                    params=dict(ball_radius_min_px=40.0, ball_radius_max_px=100.0, method=method, model=model))])
    res, _ = analyze_image(p, Recipe.from_dict(body("model")), models={REF: demo})
    m = res.modules[0]
    assert m.status == "ok" and m.summary["method"] == "model" and m.summary["model"] == REF
    res, _ = analyze_image(p, Recipe.from_dict(body("model")), models={})
    assert res.modules[0].status == "no_result" and res.modules[0].reasons == ["model_unavailable"]
    res, _ = analyze_image(p, Recipe.from_dict(body("both")), models={})
    assert "model_unavailable" in res.modules[0].judgment_reasons and res.modules[0].judgment in ("review", "fail")
    with pytest.raises(Exception):
        Recipe.from_dict(body("model", model="bad ref"))


# ---------------------------------------------------------------------------
# API：模型管理、配方發布、工作佇列、GPU 設定
# ---------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=str(tmp_path / "data"))
    app = create_app(settings, workers=1, watch=False, enforce_license=False)
    with TestClient(app) as c:
        c.platform = app.state.platform
        assert c.post("/api/auth/setup", json={"username": "eng", "password": "Passw0rd!"}).status_code == 200
        yield c


def _import(c):
    with open(DEMO, "rb") as f:
        return c.post("/api/models/import", files=[("file", ("void_unet-1.0.0.xrvmodel", f, "application/octet-stream"))])


def _recipe(c, method="model", model=REF):
    body = dict(recipe_id=f"v-{method}", version=1, name={"zh-TW": "v"}, modules=[dict(
        module_id="void", params=dict(ball_radius_min_px=40.0, ball_radius_max_px=100.0, method=method, model=model),
        judgment=dict(void_pct_max=25.0))])
    r = c.post("/api/recipes", json={"body": body})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_model_api_release_and_job(client, tmp_path):
    r = _import(client)
    assert r.status_code == 200 and r.json()["ref"] == REF and r.json()["status"] == "active", r.text
    assert _import(client).json()["error"] == "model_exists"
    lst = client.get("/api/models", params={"module_id": "void"}).json()
    assert [m["ref"] for m in lst] == [REF]
    # 找不到模型 → 不能發布
    pk_bad = _recipe(client, model="void_unet@9.9.9")
    r = client.post(f"/api/recipes/{pk_bad}/release")
    assert r.status_code >= 400 and r.json()["error"] == "model_not_found"
    # 停用 → 不能發布；重新啟用 → 可以
    mid = lst[0]["id"]
    assert client.post(f"/api/models/{mid}/status", json={"status": "retired"}).json()["status"] == "retired"
    pk = _recipe(client)
    assert client.post(f"/api/recipes/{pk}/release").json()["error"] == "model_retired"
    client.post(f"/api/models/{mid}/status", json={"status": "active"})
    assert client.post(f"/api/recipes/{pk}/release").status_code == 200
    # 工作佇列：子行程取得模型檔並以模型分割
    img, _ = make_image(seed=26, pad=False)
    p = str(tmp_path / "v.tiff")
    cv2.imwrite(p, img)
    with open(p, "rb") as f:
        assert client.post("/api/imports", files=[("files", ("v.tiff", f, "image/tiff"))],
                           data={"recipe_pk": str(pk)}).status_code == 200
    assert client.platform.queue.wait_idle(180)
    run = client.get("/api/runs").json()["items"][0]
    detail = client.get(f"/api/runs/{run['id']}").json()
    m = detail["result"]["modules"][0]
    assert m["status"] == "ok" and m["summary"]["method"] == "model" and m["summary"]["model"] == REF
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert "model.import" in actions and "model.retire" in actions
    # GPU 設定
    s = client.get("/api/settings").json()
    assert s["gpu_inference"] is False and s["inference"]["installed"]
    assert client.put("/api/settings", json={"gpu_inference": True}).json()["gpu_inference"] is True


def test_model_import_rejects_bad_signature(client, tmp_path):
    bad = tmp_path / "bad.xrvmodel"
    with zipfile.ZipFile(DEMO) as zin, zipfile.ZipFile(bad, "w") as zout:
        for n in zin.namelist():
            zout.writestr(n, zin.read(n) if n != "model.sig" else b"\0" * 64)
    with open(bad, "rb") as f:
        r = client.post("/api/models/import", files=[("file", ("bad.xrvmodel", f, "application/octet-stream"))])
    assert r.status_code == 400 and r.json()["error"] == "model_signature_invalid"


# ---------------------------------------------------------------------------
# 標註與訓練資料匯出
# ---------------------------------------------------------------------------
def _void_run(client, tmp_path):
    pk = _recipe(client, method="rule", model="")
    assert client.post(f"/api/recipes/{pk}/release").status_code == 200
    img, truth = make_image(seed=27, pad=False)
    p = str(tmp_path / "a.tiff")
    cv2.imwrite(p, img)
    with open(p, "rb") as f:
        client.post("/api/imports", files=[("files", ("a.tiff", f, "image/tiff"))], data={"recipe_pk": str(pk), "lot_no": "L1"})
    assert client.platform.queue.wait_idle(180)
    return client.get("/api/runs").json()["items"][0]["id"], truth


def test_annotation_save_history_and_export(client, tmp_path):
    run_id, truth = _void_run(client, tmp_path)
    a = client.get(f"/api/runs/{run_id}/annotation").json()
    assert a["current"] is None and a["history_count"] == 0
    assert len(a["base"]["balls"]) == len(truth) and a["base"]["voids"]
    # 以正確答案標註 (空洞輪廓取圓的多邊形)
    voids = []
    for b in truth:
        for vx, vy, vr in b.voids:
            voids.append([[vx + vr * math.cos(t), vy + vr * math.sin(t)] for t in np.linspace(0, 2 * math.pi, 24, endpoint=False)])
    r = client.put(f"/api/runs/{run_id}/annotation", json=dict(module_id="void", balls=a["base"]["balls"], voids=voids, note="truth"))
    assert r.status_code == 200 and r.json()["current"]["actor"] == "eng" and r.json()["history_count"] == 1
    client.put(f"/api/runs/{run_id}/annotation", json=dict(module_id="void", balls=a["base"]["balls"], voids=voids))
    assert client.get(f"/api/runs/{run_id}/annotation").json()["history_count"] == 2
    bad = client.put(f"/api/runs/{run_id}/annotation", json=dict(module_id="void", balls=[], voids=[[[0, 0], [1, 1]]]))
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_annotation"
    # 匯出 (去識別化)
    r = client.post("/api/annotations/export", json=dict(run_ids=[run_id], deidentify=True))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    meta = json.loads(z.read("dataset.json"))
    assert meta["format"] == "xrv-void-dataset/1" and len(meta["items"]) == len(truth)
    it = meta["items"][0]
    assert it["source"]["file"].startswith("IMG") and it["source"]["lot"] == "LOT001" and it["annotator"] == "U001"
    crop = cv2.imdecode(np.frombuffer(z.read(it["crop"]), np.uint8), cv2.IMREAD_UNCHANGED)
    assert crop.dtype == np.uint16 and crop.shape == (64, 64)
    # 訓練腳本可讀回匯出的資料集
    out = tmp_path / "ds.zip"
    out.write_bytes(r.content)
    sys.path.insert(0, os.path.join(ROOT, "tools", "model_training"))
    import train_void
    X, Y = train_void.dataset_samples(str(out))
    assert X.shape == (len(truth), 1, 64, 64) and Y.max() == 1.0
    actions = [x["action"] for x in client.get("/api/audit").json()]
    assert "annotation.save" in actions and "annotation.export" in actions
    # 沒有標註的紀錄
    r = client.post("/api/annotations/export", json=dict(run_ids=[run_id + 999]))
    assert r.status_code == 404


def test_annotation_permission(client, tmp_path):
    run_id, _ = _void_run(client, tmp_path)
    client.post("/api/users", json=dict(username="op", display_name="op", role="operator", password="Passw0rd!"))
    c2 = TestClient(client.app)
    c2.post("/api/auth/login", json={"username": "op", "password": "Passw0rd!"})
    c2.post("/api/auth/password", json={"old_password": "Passw0rd!", "new_password": "Passw0rd!2"})
    assert c2.get(f"/api/runs/{run_id}/annotation").status_code == 200
    r = c2.put(f"/api/runs/{run_id}/annotation", json=dict(module_id="void", balls=[], voids=[]))
    assert r.status_code == 403 and r.json()["error"] == "permission_denied", r.text
