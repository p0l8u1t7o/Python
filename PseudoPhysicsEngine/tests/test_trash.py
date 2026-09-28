"""網頁刪除案子：移到回收區、可還原、可永久刪除；執行中的工作會擋下刪除。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server.jobs import Job
from server.main import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(tmp_path / "projects", settings={"engineering_agent_mode": "local"})
    )


def _create(client: TestClient, name: str) -> str:
    created = client.post("/api/projects", json={"name": name, "seed_example": "getac_qc"})
    assert created.status_code == 201
    return created.json()["id"]


def _ids(client: TestClient) -> set[str]:
    return {item["id"] for item in client.get("/api/projects").json()}


def test_delete_moves_project_to_trash_and_restore_brings_it_back(tmp_path: Path):
    with _client(tmp_path) as client:
        project_id = _create(client, "回收測試")
        keep_id = _create(client, "保留案")
        marker = tmp_path / "projects" / project_id / "analysis" / "marker.txt"
        marker.write_text("原內容", encoding="utf-8")

        deleted = client.delete(f"/api/projects/{project_id}")
        assert deleted.status_code == 200
        trash_id = deleted.json()["trash_id"]
        assert _ids(client) == {keep_id}
        assert client.get(f"/api/projects/{project_id}").status_code == 404
        trash = client.get("/api/trash").json()
        assert [item["trash_id"] for item in trash] == [trash_id]
        assert trash[0]["original_id"] == project_id
        assert trash[0]["name"] == "回收測試"
        # 回收區在專案根目錄之外，檔案完整保留
        assert (tmp_path / "trash" / trash_id / "analysis" / "marker.txt").is_file()

        restored = client.post(f"/api/trash/{trash_id}/restore")
        assert restored.status_code == 200
        assert restored.json() == {"id": project_id, "name": "回收測試", "renamed": False}
        assert _ids(client) == {keep_id, project_id}
        assert marker.read_text("utf-8") == "原內容"
        assert client.get("/api/trash").json() == []
        assert not (tmp_path / "projects" / project_id / ".cellforge_trash.json").exists()


def test_restore_never_overwrites_a_project_that_took_the_same_id(tmp_path: Path):
    with _client(tmp_path) as client:
        project_id = _create(client, "同名案")
        trash_id = client.delete(f"/api/projects/{project_id}").json()["trash_id"]
        again = _create(client, "同名案")
        assert again == project_id
        newer = tmp_path / "projects" / again / "analysis" / "newer.txt"
        newer.write_text("新案", encoding="utf-8")

        restored = client.post(f"/api/trash/{trash_id}/restore").json()
        assert restored["renamed"] is True
        assert restored["id"] != project_id
        assert newer.read_text("utf-8") == "新案"
        assert _ids(client) == {project_id, restored["id"]}


def test_active_job_blocks_delete(tmp_path: Path):
    with _client(tmp_path) as client:
        project_id = _create(client, "執行中")
        jobs = client.app.state.jobs
        jobs.jobs["busy"] = Job(
            id="busy",
            project_id=project_id,
            kind="first_build",
            owner="engineering",
            status="running",
        )
        blocked = client.delete(f"/api/projects/{project_id}")
        assert blocked.status_code == 409
        assert "執行中的工作" in blocked.json()["detail"]
        assert project_id in _ids(client)
        jobs.jobs["busy"].status = "done"
        assert client.delete(f"/api/projects/{project_id}").status_code == 200


def test_purge_removes_trash_entry_including_readonly_git_objects(tmp_path: Path):
    with _client(tmp_path) as client:
        project_id = _create(client, "永久刪除")
        trash_id = client.delete(f"/api/projects/{project_id}").json()["trash_id"]
        entry = tmp_path / "trash" / trash_id
        assert (entry / ".git").is_dir()
        purged = client.delete(f"/api/trash/{trash_id}")
        assert purged.status_code == 200
        assert not entry.exists()
        assert client.get("/api/trash").json() == []
        assert client.delete(f"/api/trash/{trash_id}").status_code == 404
        assert client.post(f"/api/trash/{trash_id}/restore").status_code == 404


def test_trash_ids_cannot_escape_the_trash_root(tmp_path: Path):
    with _client(tmp_path) as client:
        project_id = _create(client, "路徑")
        for bad in ("..", "..%2Fprojects%2F" + project_id):
            assert client.delete(f"/api/trash/{bad}").status_code in {404, 405}
        assert project_id in _ids(client)
        assert client.delete("/api/projects/..").status_code in {404, 405}
