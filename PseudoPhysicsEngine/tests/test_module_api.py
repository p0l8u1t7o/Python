from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cellforge.cli import app as cli_app
from cellforge.module_cache import CACHE_ROOT_ENV
from cellforge.part_check import _load_file
from cellforge.yamlio import dump_yaml, load_yaml
from server.main import create_app

ROOT = Path(__file__).resolve().parents[1]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
GLB_SIGNATURE = b"glTF"


def _wait_for(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "failed", "cancelled"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"工作逾時：{job_id}")


GOOD_MODULE = '''"""本案自建的測試安裝台。"""
import cadquery as cq
from cellforge.schema import Frame, ModuleDef, ModuleMeta

CATEGORY = "fixturing"
COLOR = cq.Color(0.3, 0.5, 0.7)

def build(params):
    height = float(params.get("height_mm", 100))
    result = cq.Assembly(name="local_fixture")
    result.add(cq.Workplane("XY").box(100, 80, 10).translate((0, 0, 5)),
               name="mounting_plate", color=COLOR)
    for name, x in (("foot_left", -40), ("foot_right", 40)):
        result.add(cq.Workplane("XY").box(10, 10, height).translate((x, 0, height / 2)),
                   name=name, color=COLOR)
    return result

MODULE = ModuleDef(
    id="local_fixture",
    params_schema={
        "type": "object",
        "properties": {
            "height_mm": {
                "type": "number", "minimum": 80, "maximum": 120, "default": 100
            }
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(link="mounting_plate")},
    collision="box",
    meta=ModuleMeta(basis="依本案測試治具的安裝面與支撐高度作工程推估"),
)
'''

FAILING_MODULE = '''"""刻意不合格的測試模組。"""
import cadquery as cq
from cellforge.schema import ModuleDef

def build(_params):
    result = cq.Assembly(name="failing_part")
    result.add(cq.Workplane("XY").box(40, 40, 40), name="body", color=cq.Color(0.5, 0.5, 0.5))
    return result

MODULE = ModuleDef(id="failing_part", params_schema={"type": "object"})
'''


@pytest.fixture
def module_api(tmp_path: Path):
    catalog_root = tmp_path / "catalog"
    shutil.copytree(ROOT / "library", catalog_root / "library")
    cache_root = tmp_path / "module-cache"
    projects_root = tmp_path / "projects"
    app = create_app(
        projects_root,
        settings={
            "engineering_agent_mode": "local",
            "catalog_root": catalog_root,
            "module_cache_root": cache_root,
        },
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/projects",
            json={"name": "模組 API 測試案", "seed_example": "getac_qc"},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]
        project = projects_root / project_id
        (project / "parts" / "local_fixture.py").write_text(GOOD_MODULE, encoding="utf-8")
        (project / "parts" / "failing_part.py").write_text(FAILING_MODULE, encoding="utf-8")
        cell_path = project / "cell.yaml"
        cell = load_yaml(cell_path)
        local_module = _load_file(project / "parts" / "local_fixture.py")
        parameter = local_module.MODULE.params_schema["properties"]["height_mm"]
        actual_height = (parameter["minimum"] + parameter["maximum"]) / 2
        cell["machines"][0]["modules"].append(
            {
                "id": "local_fixture_instance",
                "part": "parts/local_fixture.py",
                "params": {"height_mm": actual_height},
                "pose": {"xyz": [0, 0, 0], "rpy_deg": [0, 0, 0], "trust": "inferred"},
            }
        )
        dump_yaml(cell_path, cell)
        yield client, project_id, project, catalog_root, cache_root


def test_all_nine_module_endpoints_and_jobs(module_api):
    client, project_id, project, catalog_root, _cache_root = module_api
    library_response = client.get("/api/library/modules")
    assert library_response.status_code == 200
    assert (
        library_response.json()["modules"]
        == load_yaml(catalog_root / "library" / "manifest.yaml")["modules"]
    )

    listed = client.get(f"/api/projects/{project_id}/modules")
    assert listed.status_code == 200
    rows = {row["id"]: row for row in listed.json()["modules"]}
    referenced_library_ids = {
        Path(instance["part"]).stem
        for machine in load_yaml(project / "cell.yaml")["machines"]
        for instance in machine["modules"]
        if str(instance.get("part", "")).replace("\\", "/").startswith("library/")
    }
    assert referenced_library_ids <= rows.keys()
    assert {"local_fixture", "failing_part"} <= rows.keys()
    assert rows["local_fixture"]["placeholder"] is False
    assert rows["local_fixture"]["usages"][0]["instance_id"] == "local_fixture_instance"
    assert rows["local_fixture"]["usages"][0]["trust"] == "inferred"

    detail = client.get(f"/api/projects/{project_id}/modules/local_fixture")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["module_def"]["id"] == "local_fixture"
    assert payload["params"] == payload["parameter_sets"][0]
    assert payload["frames"] == payload["module_def"]["frames"]
    assert payload["axes"] == payload["module_def"]["axes"]
    assert payload["meta"] == payload["module_def"]["meta"]

    checked = client.get(f"/api/projects/{project_id}/modules/local_fixture/check")
    assert checked.status_code == 200
    assert checked.headers["x-cellforge-cache"] == "miss"
    assert {"module_id", "passed", "items", "params", "cache"} <= checked.json().keys()
    refreshed_rows = {
        row["id"]: row
        for row in client.get(f"/api/projects/{project_id}/modules").json()["modules"]
    }
    assert refreshed_rows["local_fixture"]["check"]["status"] == "passed"

    unused_library_id = next(
        entry["id"]
        for entry in library_response.json()["modules"]
        if entry["id"] not in referenced_library_ids
    )
    unused_detail = client.get(f"/api/projects/{project_id}/modules/{unused_library_id}")
    assert unused_detail.status_code == 200
    assert unused_detail.json()["id"] == unused_library_id

    rendered = client.get(f"/api/projects/{project_id}/modules/local_fixture/render.png")
    assert rendered.status_code == 200
    assert rendered.headers["content-type"].startswith("image/png")
    assert rendered.content.startswith(PNG_SIGNATURE)

    previewed = client.get(f"/api/projects/{project_id}/modules/local_fixture/preview.glb")
    assert previewed.status_code == 200
    assert previewed.headers["content-type"].startswith("model/gltf-binary")
    assert previewed.content.startswith(GLB_SIGNATURE)

    recheck = client.post(f"/api/projects/{project_id}/modules/local_fixture/recheck")
    assert recheck.status_code == 202
    assert _wait_for(client, recheck.json()["id"])["status"] == "done"

    fixed = client.post(f"/api/projects/{project_id}/modules/failing_part/fix")
    assert fixed.status_code == 202
    assert fixed.json()["change_id"].startswith("CR-")
    assert fixed.json()["task_id"].startswith("T-")
    assert _wait_for(client, fixed.json()["id"])["status"] == "done"
    fix_task = next(
        task
        for task in client.get(f"/api/projects/{project_id}/tasks").json()
        if task["id"] == fixed.json()["task_id"]
    )
    assert fix_task["status"] == "done"
    assert "6.1" in fix_task["instruction"]

    refused = client.post(f"/api/projects/{project_id}/modules/failing_part/promote")
    assert refused.status_code == 409
    assert "仍有失敗項目" in refused.json()["detail"]

    promoted = client.post(f"/api/projects/{project_id}/modules/local_fixture/promote")
    assert promoted.status_code == 202
    promoted_job = _wait_for(client, promoted.json()["id"])
    assert promoted_job["status"] == "done", promoted_job
    entry = promoted_job["result"]["module"]
    assert entry["from_project"] == project_id
    assert (catalog_root / entry["file"]).is_file()
    assert not (project / "parts" / "local_fixture.py").exists()
    promoted_instance = next(
        instance
        for machine in load_yaml(project / "cell.yaml")["machines"]
        for instance in machine["modules"]
        if instance["id"] == "local_fixture_instance"
    )
    assert promoted_instance["part"] == entry["file"]


def test_module_check_cache_reads_writes_and_invalidates_on_source_change(module_api):
    client, project_id, project, _catalog_root, cache_root = module_api
    endpoint = f"/api/projects/{project_id}/modules/local_fixture/check"
    cold = client.get(endpoint)
    assert cold.status_code == 200
    assert cold.headers["x-cellforge-cache"] == "miss"
    assert cold.json()["cache"]["hit"] is False
    first_key = cold.json()["cache"]["key"]
    artifact = cache_root / first_key / "check.json"
    assert artifact.is_file()
    first_mtime = artifact.stat().st_mtime_ns

    warm = client.get(endpoint)
    assert warm.status_code == 200
    assert warm.headers["x-cellforge-cache"] == "hit"
    assert warm.json()["cache"] == {"key": first_key, "hit": True}
    assert artifact.stat().st_mtime_ns == first_mtime

    source = project / "parts" / "local_fixture.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# 使內容雜湊失效\n", encoding="utf-8")
    refreshed = client.get(endpoint)
    assert refreshed.status_code == 200
    assert refreshed.headers["x-cellforge-cache"] == "miss"
    assert refreshed.json()["cache"]["hit"] is False
    assert refreshed.json()["cache"]["key"] != first_key
    assert (cache_root / refreshed.json()["cache"]["key"] / "check.json").is_file()
    assert artifact.stat().st_mtime_ns == first_mtime


def test_cell_part_check_cli_reads_the_same_content_addressed_cache(module_api):
    _client, _project_id, project, _catalog_root, cache_root = module_api
    cli_cache = cache_root / "cli"
    arguments = [
        "part",
        "check",
        "local_fixture",
        "--project",
        str(project),
        "--json",
    ]
    runner = CliRunner()
    first = runner.invoke(cli_app, arguments, env={CACHE_ROOT_ENV: str(cli_cache)})
    assert first.exit_code == 0, first.output
    artifacts = list(cli_cache.glob("*/check.json"))
    assert len(artifacts) == 1
    first_mtime = artifacts[0].stat().st_mtime_ns

    second = runner.invoke(cli_app, arguments, env={CACHE_ROOT_ENV: str(cli_cache)})
    assert second.exit_code == 0, second.output
    assert artifacts[0].stat().st_mtime_ns == first_mtime

    source = project / "parts" / "local_fixture.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# CLI 快取失效\n", encoding="utf-8")
    third = runner.invoke(cli_app, arguments, env={CACHE_ROOT_ENV: str(cli_cache)})
    assert third.exit_code == 0, third.output
    refreshed = list(cli_cache.glob("*/check.json"))
    assert len(refreshed) > len(artifacts)
    assert artifacts[0].stat().st_mtime_ns == first_mtime


def test_module_routes_are_documented(tmp_path: Path):
    app = create_app(
        tmp_path / "projects",
        settings={
            "catalog_root": ROOT,
            "module_cache_root": tmp_path / "module-cache",
        },
    )
    paths = set(app.openapi()["paths"])
    assert {
        "/api/library/modules",
        "/api/projects/{project_id}/modules",
        "/api/projects/{project_id}/modules/{module_id}",
        "/api/projects/{project_id}/modules/{module_id}/check",
        "/api/projects/{project_id}/modules/{module_id}/render.png",
        "/api/projects/{project_id}/modules/{module_id}/preview.glb",
        "/api/projects/{project_id}/modules/{module_id}/recheck",
        "/api/projects/{project_id}/modules/{module_id}/fix",
        "/api/projects/{project_id}/modules/{module_id}/promote",
    } <= paths
