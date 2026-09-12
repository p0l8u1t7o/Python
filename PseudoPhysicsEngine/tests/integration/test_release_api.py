from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient


def _project(client: TestClient) -> tuple[str, str]:
    payload = cast(
        dict[str, object], client.post("/api/v1/projects", json={"name": "Release"}).json()
    )
    revision = cast(dict[str, object], payload["current_revision"])
    return str(payload["id"]), str(revision["id"])


def _prepare_releasable_revision(client: TestClient) -> tuple[str, str]:
    project_id, revision_id = _project(client)
    scene_node_id = str(uuid4())
    process = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "target_cycle_time_seconds": 10,
        "steps": [{"id": str(uuid4()), "name": "Transfer", "estimated_duration_seconds": 2}],
    }
    assert (
        client.put(f"/api/v1/revisions/{revision_id}/process-spec", json=process).status_code == 200
    )
    motion = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "tracks": [
            {
                "id": str(uuid4()),
                "scene_node_id": scene_node_id,
                "joint_name": "axis",
                "position_unit": "mm",
                "keyframes": [
                    {"time_seconds": 0, "position": 0},
                    {"time_seconds": 2, "position": 500},
                ],
            }
        ],
    }
    assert (
        client.put(f"/api/v1/revisions/{revision_id}/motion-spec", json=motion).status_code == 200
    )
    frame_id = str(uuid4())
    assert (
        client.post(
            f"/api/v1/revisions/{revision_id}/frames",
            json={"frame": {"id": frame_id, "revision_id": revision_id, "name": "Plant"}},
        ).status_code
        == 201
    )
    content = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    upload = client.post(
        f"/api/v1/projects/{project_id}/files",
        data={"revision_id": revision_id, "source": "Supplier"},
        files={"file": ("machine.step", content, "application/step")},
    )
    assert upload.status_code == 201
    scene = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "nodes": [
            {
                "id": scene_node_id,
                "name": "Machine",
                "asset_version_id": upload.json()["id"],
                "coordinate_frame_id": frame_id,
            }
        ],
    }
    assert client.put(f"/api/v1/revisions/{revision_id}/scene", json=scene).status_code == 200
    return project_id, revision_id


def test_failed_validation_blocks_release(client: TestClient) -> None:
    _project_id, revision_id = _project(client)
    response = client.post(
        f"/api/v1/revisions/{revision_id}/release", json={"approved_by": str(uuid4())}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "RELEASE_REJECTED"
    assert "PROCESS_SPEC_MISSING" in response.json()["message"]


def test_release_is_immutable_auditable_and_idempotent(client: TestClient) -> None:
    project_id, revision_id = _prepare_releasable_revision(client)
    approver = str(uuid4())
    route = f"/api/v1/revisions/{revision_id}/release"
    first = client.post(route, json={"approved_by": approver})
    assert first.status_code == 200
    manifest = first.json()
    assert manifest["revision_id"] == revision_id
    assert manifest["approved_by"] == approver
    assert manifest["artifacts"][0]["kind"] == "STEP"
    assert len(manifest["artifacts"][0]["sha256"]) == 64
    assert client.get(route).json() == manifest
    assert client.post(route, json={"approved_by": approver}).json() == manifest

    project = client.get(f"/api/v1/projects/{project_id}").json()
    assert project["current_revision"]["status"] == "RELEASED"
    mutation = client.put(
        f"/api/v1/revisions/{revision_id}/process-spec",
        json={
            "id": str(uuid4()),
            "project_id": project_id,
            "revision_id": revision_id,
            "target_cycle_time_seconds": 1,
            "steps": [{"id": str(uuid4()), "name": "Changed", "estimated_duration_seconds": 1}],
        },
    )
    assert mutation.status_code == 409
    assert mutation.json()["code"] == "REVISION_IMMUTABLE"

    conflict = client.post(route, json={"approved_by": str(uuid4())})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "RELEASE_REJECTED"
