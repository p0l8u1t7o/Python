import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from server.main import create_app


def wait_for(client: TestClient, job_id: str, timeout: float | None = 30) -> dict:
    deadline = None if timeout is None else time.monotonic() + timeout
    while deadline is None or time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "failed", "cancelled"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job timeout: {job_id}")


def test_step1_wizard_api_flow(tmp_path: Path):
    with TestClient(
        create_app(
            tmp_path / "projects",
            settings={"engineering_agent_mode": "local"},
        )
    ) as client:
        created = client.post(
            "/api/projects",
            json={
                "name": "API 驗收案",
                "product": "Getac V110",
                "seed_example": "getac_qc",
            },
        )
        assert created.status_code == 201
        project_id = created.json()["id"]
        early = client.post(f"/api/projects/{project_id}/build")
        assert early.status_code == 409 and "尚未完成 intake" in early.json()["detail"]
        summary = "代理最終摘要：仍有一項佔位模組。"
        summary_path = tmp_path / "projects" / project_id / "analysis" / "first_build_summary.txt"
        summary_path.write_text(summary, encoding="utf-8")
        assert client.get(f"/api/projects/{project_id}").json()["first_build_summary"] == summary
        uploaded = client.post(
            f"/api/projects/{project_id}/files",
            files={"file": ("photo.jpg", b"step-1-photo", "image/jpeg")},
            data={"kind": "product_photo", "note": "API test"},
        )
        assert uploaded.status_code == 201
        assert len(client.get(f"/api/projects/{project_id}/files").json()["files"]) == 1

        intake = client.post(f"/api/projects/{project_id}/intake")
        intake_job = wait_for(client, intake.json()["id"])
        assert intake_job["status"] == "done"
        questions = client.get(f"/api/projects/{project_id}/questions").json()["questions"]
        assert len(questions) == 8
        skipped = client.post(
            f"/api/projects/{project_id}/questions/{questions[0]['id']}",
            json={"skip_all": True},
        )
        assert skipped.status_code == 200
        assumptions = client.get(f"/api/projects/{project_id}/assumptions").json()["assumptions"]
        override = client.put(
            f"/api/projects/{project_id}/assumptions/{assumptions[0]['id']}",
            json={"text": "改為 105°"},
        )
        assert override.status_code == 200
        assert wait_for(client, override.json()["id"])["status"] == "done"
        task = client.post(
            f"/api/projects/{project_id}/tasks",
            json={"owner": "engineering", "text": "示意任務"},
        )
        assert task.status_code == 201
        assert len(client.get(f"/api/projects/{project_id}/tasks").json()) == 1

        # intake 之後補上新證據：intake 結果過期，first_build 必須被擋下直到重新 intake。
        late = client.post(
            f"/api/projects/{project_id}/files",
            files={"file": ("late.jpg", b"late-photo", "image/jpeg")},
            data={"kind": "product_photo", "note": "補充"},
        )
        assert late.status_code == 201
        stale = client.post(f"/api/projects/{project_id}/build")
        assert stale.status_code == 409 and "已變更" in stale.json()["detail"]
        assert client.get(f"/api/projects/{project_id}/intake/state").json()["stale"] is True
        again = wait_for(client, client.post(f"/api/projects/{project_id}/intake").json()["id"])
        assert again["status"] == "done", again
        questions = client.get(f"/api/projects/{project_id}/questions").json()["questions"]
        client.post(
            f"/api/projects/{project_id}/questions/{questions[0]['id']}", json={"skip_all": True}
        )
        state = client.get(f"/api/projects/{project_id}/intake/state").json()
        assert state["state"]["status"] == "succeeded" and state["stale"] is False

        build = client.post(f"/api/projects/{project_id}/build")
        build_job = wait_for(client, build.json()["id"], timeout=None)
        assert build_job["status"] == "done", build_job
        result = build_job["result"]
        assert result["job_versions"] == [result["version_id"]]
        assert result["verification"]["status"] == "ok"
        assert result["verification"]["job_id"] == build_job["id"]
        assert result["verification"]["level"] == "L1"
        assert result["mode"] == "local" and result["agent_acceptance"] is False
        # getac 範例本來就有干涉紅項：建置成功但工程未通過，必須以警告明示。
        assert result["engineering_status"] == "fail"
        assert any("工程檢查未通過" in item for item in build_job["warnings"])
        versions = client.get(f"/api/projects/{project_id}/versions").json()
        assert versions[-1]["step"]["top_level_part_count"] == 8
        assert versions[-1]["step"]["all_names_preserved"] is True
        assert versions[-1]["id"] == result["version_id"]
        assert (
            client.get(
                f"/api/projects/{project_id}/versions/{versions[-1]['id']}/scene.glb"
            ).status_code
            == 200
        )
        events = client.get(f"/api/jobs/{build.json()['id']}/events")
        assert "event: complete" in events.text
        project_path = tmp_path / "projects" / project_id
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True,
        )
        assert status.stdout == ""


def test_all_documented_step1_routes_exist(tmp_path: Path):
    app = create_app(tmp_path / "projects", settings={"engineering_agent_mode": "local"})
    paths = set(app.openapi()["paths"])
    required = {
        "/api/projects",
        "/api/projects/{project_id}",
        "/api/projects/{project_id}/files",
        "/api/projects/{project_id}/intake",
        "/api/projects/{project_id}/questions",
        "/api/projects/{project_id}/build",
        "/api/projects/{project_id}/builds/manual",
        "/api/projects/{project_id}/intake/state",
        "/api/projects/{project_id}/versions",
        "/api/projects/{project_id}/changes",
        "/api/projects/{project_id}/tasks",
        "/api/projects/{project_id}/process",
        "/api/projects/{project_id}/export",
        "/api/jobs/{job_id}",
        "/api/jobs/{job_id}/events",
        "/api/jobs/{job_id}/cancel",
        "/api/settings",
    }
    assert required <= paths
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["service"] == "CellForge"


def test_export_api_binds_to_requested_version(tmp_path: Path):
    from cellforge.build.pipeline import build_project

    projects_root = tmp_path / "projects"
    with TestClient(
        create_app(projects_root, settings={"engineering_agent_mode": "local"})
    ) as client:
        created = client.post(
            "/api/projects", json={"name": "版本匯出 API 案", "seed_example": "getac_qc"}
        )
        project_id = created.json()["id"]
        project = projects_root / project_id
        build_project(project, "L0")
        build_project(project, "L0")
        versions = client.get(f"/api/projects/{project_id}/versions").json()
        assert [item["id"] for item in versions] == ["v1", "v2"]
        assert all(item["complete"] for item in versions)
        assert {item["engineering_status"] for item in versions} == {"not_evaluated"}

        exported = client.post(
            f"/api/projects/{project_id}/export", json={"kinds": ["bom", "video"], "version": "v1"}
        )
        assert exported.status_code == 202
        job = wait_for(client, exported.json()["id"])
        assert job["status"] == "done", job
        assert job["result"]["version"] == "v1"
        assert job["result"]["status"] == "incomplete"
        assert [item["kind"] for item in job["result"]["missing"]] == ["video"]

        manifest = client.get(f"/api/projects/{project_id}/versions/v1/manifest").json()
        assert manifest["complete"] is True
        assert manifest["manifest"]["version"] == "v1"
        assert manifest["derived"] == []
        base = f"/api/projects/{project_id}/versions"
        assert client.get(f"{base}/v1/manifest.json").status_code == 200
        for bad in ("v9", "..", "latest"):
            assert client.get(f"{base}/{bad}/manifest").status_code == 404
            assert client.get(f"{base}/{bad}/scene.glb").status_code == 404
        missing = client.post(
            f"/api/projects/{project_id}/export", json={"kinds": ["bom"], "version": "v9"}
        )
        assert missing.status_code == 404


def test_failed_intake_blocks_first_build_and_success_needs_this_jobs_version(
    tmp_path: Path, monkeypatch
):
    import server.routes.api as api_module
    from cellforge.build.pipeline import build_project

    projects_root = tmp_path / "projects"
    with TestClient(
        create_app(projects_root, settings={"engineering_agent_mode": "local"})
    ) as client:
        project_id = client.post(
            "/api/projects", json={"name": "成功判定案", "seed_example": "getac_qc"}
        ).json()["id"]
        project = projects_root / project_id
        intake_url = f"/api/projects/{project_id}/intake"
        build_url = f"/api/projects/{project_id}/build"

        real_intake = api_module.run_local_intake

        def failing_intake(*_args, **_kwargs):
            raise RuntimeError("模擬 intake 失敗")

        monkeypatch.setattr(api_module, "run_local_intake", failing_intake)
        failed = wait_for(client, client.post(intake_url).json()["id"])
        assert failed["status"] == "failed"
        state = client.get(f"/api/projects/{project_id}/intake/state").json()["state"]
        assert state["status"] == "failed" and "模擬 intake 失敗" in state["error"]
        blocked = client.post(build_url)
        assert blocked.status_code == 409 and "failed" in blocked.json()["detail"]

        monkeypatch.setattr(api_module, "run_local_intake", real_intake)
        assert wait_for(client, client.post(intake_url).json()["id"])["status"] == "done"
        questions = client.get(f"/api/projects/{project_id}/questions").json()["questions"]
        client.post(
            f"/api/projects/{project_id}/questions/{questions[0]['id']}", json={"skip_all": True}
        )

        # 案子已有 v1，但這次 first_build 沒有發布任何版本：不能因為「已有版本」就算成功。
        build_project(project, "L0")

        async def pretend_build(*_args, **_kwargs):
            return {"status": "ok", "version": 1}

        monkeypatch.setattr(api_module, "_local_build", pretend_build)
        job = wait_for(client, client.post(build_url).json()["id"], timeout=120)
        assert job["status"] == "failed"
        assert "沒有發布任何版本" in job["error"]


def test_manual_build_is_verified_and_never_counts_as_agent_acceptance(tmp_path: Path, monkeypatch):
    import server.routes.api as api_module

    projects_root = tmp_path / "projects"
    with TestClient(
        create_app(projects_root, settings={"engineering_agent_mode": "claude"})
    ) as client:
        project_id = client.post(
            "/api/projects", json={"name": "手寫建置案", "seed_example": "getac_qc"}
        ).json()["id"]
        # 正式代理模式下沒有 intake：first_build 被擋，但手寫資料建置仍可使用。
        assert client.post(f"/api/projects/{project_id}/build").status_code == 409
        manual = client.post(f"/api/projects/{project_id}/builds/manual")
        job = wait_for(client, manual.json()["id"], timeout=None)
        assert job["status"] == "done", job
        result = job["result"]
        assert result["mode"] == "manual" and result["agent_acceptance"] is False
        assert result["verification"]["origin"] == "manual"
        assert result["verification"]["job_id"] == job["id"]

        # 工作本身完成、只有 git 提交失敗：job 仍成功並帶警告。
        monkeypatch.setattr(
            api_module,
            "try_commit_changes",
            lambda *_args, **_kwargs: "工作已完成，但案子 git 提交失敗：模擬 dubious ownership",
        )
        exported = client.post(
            f"/api/projects/{project_id}/export",
            json={"kinds": ["bom"], "version": result["version_id"]},
        )
        export_job = wait_for(client, exported.json()["id"])
        assert export_job["status"] == "done"
        assert any("模擬 dubious ownership" in item for item in export_job["warnings"])
