from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient


def _create_project_with_process(client: TestClient, name: str) -> tuple[str, str, str]:
    project = cast(dict[str, object], client.post("/api/v1/projects", json={"name": name}).json())
    project_id = str(project["id"])
    revision_id = str(cast(dict[str, object], project["current_revision"])["id"])
    plant_id = str(uuid4())
    assert (
        client.post(
            f"/api/v1/revisions/{revision_id}/frames",
            json={"frame": {"id": plant_id, "revision_id": revision_id, "name": "Plant"}},
        ).status_code
        == 201
    )
    process = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "target_cycle_time_seconds": 10,
        "steps": [{"id": str(uuid4()), "name": "Pick", "estimated_duration_seconds": 2}],
    }
    assert (
        client.put(f"/api/v1/revisions/{revision_id}/process-spec", json=process).status_code == 200
    )
    return project_id, revision_id, plant_id


def _apply_rename(client: TestClient, project_id: str, revision_id: str, plant_id: str) -> str:
    response = client.post(
        f"/api/v1/revisions/{revision_id}/changesets/apply",
        json={
            "id": str(uuid4()),
            "project_id": project_id,
            "base_revision_id": revision_id,
            "reason": "Rename frame",
            "user_instruction": "Rename Plant",
            "interpreted_intent": "Rename Plant to Main Plant",
            "approved_by": str(uuid4()),
            "operations": [
                {
                    "operation": "UPDATE",
                    "object_type": "CoordinateFrame",
                    "object_id": plant_id,
                    "before": {"name": "Plant"},
                    "after": {"name": "Main Plant"},
                }
            ],
        },
    )
    assert response.status_code == 201
    return str(response.json()["revision"]["id"])


def test_revision_history_and_structured_diff(client: TestClient) -> None:
    project_id, first_id, plant_id = _create_project_with_process(client, "Diff")
    second_id = _apply_rename(client, project_id, first_id, plant_id)
    process = client.get(f"/api/v1/revisions/{second_id}/process-spec").json()
    process["steps"][0]["estimated_duration_seconds"] = 3
    assert (
        client.put(f"/api/v1/revisions/{second_id}/process-spec", json=process).status_code == 200
    )

    history = client.get(f"/api/v1/projects/{project_id}/revisions")
    assert history.status_code == 200
    assert [revision["id"] for revision in history.json()] == [second_id, first_id]
    assert [revision["sequence"] for revision in history.json()] == [2, 1]

    response = client.get(
        f"/api/v1/projects/{project_id}/revisions/diff",
        params={"from_revision_id": first_id, "to_revision_id": second_id},
    )
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [(entry["object_type"], entry["change_kind"]) for entry in entries] == [
        ("CoordinateFrame", "MODIFIED"),
        ("ProcessSpec", "MODIFIED"),
    ]
    assert entries[0]["object_key"] == plant_id
    assert entries[0]["before"]["name"] == "Plant"
    assert entries[0]["after"]["name"] == "Main Plant"


def test_revision_diff_rejects_cross_project_comparison(client: TestClient) -> None:
    first_project, first_revision, _ = _create_project_with_process(client, "First")
    _second_project, second_revision, _ = _create_project_with_process(client, "Second")
    response = client.get(
        f"/api/v1/projects/{first_project}/revisions/diff",
        params={"from_revision_id": first_revision, "to_revision_id": second_revision},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "REVISION_COMPARISON_CONFLICT"
