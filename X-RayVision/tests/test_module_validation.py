"""第 5e 階段：模組驗證工具 (validate-module)"""
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
from xrayvision import cli
from xrayvision.config import Settings
from xrayvision.core import inference
from xrayvision.core import module_validation as MV
from xrayvision.service.api import create_app
from xrayvision.service.updates import PUBLIC_KEY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "model_training"))
DEMO = os.path.join(ROOT, "tests", "data", "void_unet-1.0.0.xrvmodel")


def _recipe(tmp_path, **params):
    b = dict(recipe_id="val", version=1, name={}, modules=[dict(
        module_id="void", params=dict(ball_radius_min_px=40.0, ball_radius_max_px=100.0, **params),
        judgment=dict(void_pct_max=25.0))])
    p = tmp_path / f"r_{params.get('method', 'rule')}.json"
    p.write_text(json.dumps(b))
    return str(p)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    import make_synthetic_dataset
    return make_synthetic_dataset.build(str(tmp_path_factory.mktemp("ds") / "synth.zip"), n_images=3, seed=700,
                                        pad=False)


def test_validate_module_rule(tmp_path, dataset):
    rep = MV.run("void", dataset, _recipe(tmp_path), str(tmp_path / "out"))
    m = rep["metrics"]
    assert rep["images"] == 3 and m["balls"] == 60 and m["unmeasured_ratio"] == 0
    assert m["detection_rate"] >= 0.95 and m["false_call_rate"] == 0 and m["false_pass"] == 0
    assert {c["metric"] for c in rep["checks"]} == {"detection_rate", "false_call_rate", "void_pct_error_p95",
                                                    "false_pass", "unmeasured_ratio"}
    assert os.path.isfile(tmp_path / "out" / "report.html") and os.path.isfile(tmp_path / "out" / "report.json")
    html = (tmp_path / "out" / "report.html").read_text(encoding="utf-8")
    assert "檢測模組驗證報告" in html and "空洞檢出率" in html


@pytest.mark.skipif(not inference.available()["installed"], reason="onnxruntime not installed")
def test_validate_module_cli_with_model(tmp_path, dataset, capsys):
    rc = cli.main(["validate-module", "void", "--dataset", dataset, "--recipe",
                   _recipe(tmp_path, method="model", model="void_unet@1.0.0"), "--out", str(tmp_path / "m"),
                   "--model", f"void_unet@1.0.0={DEMO}"])
    out = capsys.readouterr().out
    assert rc == 0 and "PASSED" in out
    rep = json.loads((tmp_path / "m" / "report.json").read_text(encoding="utf-8"))
    assert rep["passed"] and rep["models"] == ["void_unet@1.0.0"]
    # 參照與模型檔不符
    rc = cli.main(["validate-module", "void", "--dataset", dataset, "--recipe", _recipe(tmp_path), "--out",
                   str(tmp_path / "x"), "--model", f"void_unet@2.0.0={DEMO}"])
    assert rc == 2


def test_invalid_dataset(tmp_path):
    (tmp_path / "bad.zip").write_bytes(b"nope")
    with pytest.raises(MV.ValidationSetError):
        MV.run("void", str(tmp_path / "bad.zip"), _recipe(tmp_path), str(tmp_path / "o"))
    with pytest.raises(MV.ValidationSetError) as e:
        MV.run("bump_alignment", str(tmp_path / "bad.zip"), _recipe(tmp_path), str(tmp_path / "o"))
    assert e.value.code == "validation_not_supported"


def test_platform_export_roundtrip(tmp_path):
    """平台標註 → 匯出 (含原始影像) → validate-module"""
    settings = Settings(data_dir=str(tmp_path / "data"))
    app = create_app(settings, workers=1, watch=False, enforce_license=False)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "eng", "password": "Passw0rd!"})
        body = json.loads(open(_recipe(tmp_path), encoding="utf-8").read())
        pk = c.post("/api/recipes", json={"body": body}).json()["id"]
        assert c.post(f"/api/recipes/{pk}/release").status_code == 200
        img, truth = make_image(seed=31, pad=False)
        p = str(tmp_path / "a.tiff")
        cv2.imwrite(p, img)
        with open(p, "rb") as f:
            c.post("/api/imports", files=[("files", ("a.tiff", f, "image/tiff"))], data={"recipe_pk": str(pk)})
        assert app.state.platform.queue.wait_idle(180)
        run_id = c.get("/api/runs").json()["items"][0]["id"]
        base = c.get(f"/api/runs/{run_id}/annotation").json()["base"]
        voids = [[[vx + vr * math.cos(a), vy + vr * math.sin(a)] for a in np.linspace(0, 2 * math.pi, 32, endpoint=False)]
                 for b in truth for vx, vy, vr in b.voids]
        c.put(f"/api/runs/{run_id}/annotation", json=dict(module_id="void", balls=base["balls"], voids=voids))
        r = c.post("/api/annotations/export", json=dict(run_ids=[run_id], include_images=True))
        assert r.status_code == 200
    ds = tmp_path / "export.zip"
    ds.write_bytes(r.content)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "annotations.json" in z.namelist() and any(n.startswith("images/") for n in z.namelist())
    rep = MV.run("void", str(ds), _recipe(tmp_path), str(tmp_path / "rt"))
    assert rep["metrics"]["balls"] == len(truth) and rep["metrics"]["false_pass"] == 0
