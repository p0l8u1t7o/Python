import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from server.main import create_app


def wait_for(client: TestClient, job_id: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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

        build = client.post(f"/api/projects/{project_id}/build")
        build_job = wait_for(client, build.json()["id"])
        assert build_job["status"] == "done", build_job
        versions = client.get(f"/api/projects/{project_id}/versions").json()
        assert versions[-1]["step"]["top_level_part_count"] == 7
        assert versions[-1]["step"]["all_names_preserved"] is True
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
