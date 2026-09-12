from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient


def _project(client: TestClient, name: str) -> tuple[str, str]:
    project = cast(dict[str, object], client.post("/api/v1/projects", json={"name": name}).json())
    revision = cast(dict[str, object], project["current_revision"])
    return str(project["id"]), str(revision["id"])


def test_project_audit_records_core_mutations_and_supports_revision_filter(
    client: TestClient,
) -> None:
    project_id, revision_id = _project(client, "Audit")
    process_id = str(uuid4())
    response = client.put(
        f"/api/v1/revisions/{revision_id}/process-spec",
        json={
            "id": process_id,
            "project_id": project_id,
            "revision_id": revision_id,
            "target_cycle_time_seconds": 10,
            "steps": [{"id": str(uuid4()), "name": "Pick", "estimated_duration_seconds": 2}],
        },
    )
    assert response.status_code == 200
    assert client.post(f"/api/v1/revisions/{revision_id}/validate").status_code == 200

    events = client.get(f"/api/v1/projects/{project_id}/audit")
    assert events.status_code == 200
    assert [event["event_type"] for event in events.json()] == [
        "PROJECT_CREATED",
        "PROCESS_SPEC_SAVED",
        "VALIDATION_COMPLETED",
    ]
    process_event = events.json()[1]
    assert process_event["revision_id"] == revision_id
    assert process_event["entity_id"] == process_id
    assert process_event["details"]["step_count"] == 1

    filtered = client.get(
        f"/api/v1/projects/{project_id}/audit", params={"revision_id": revision_id}
    )
    assert filtered.status_code == 200
    assert filtered.json() == events.json()


def test_audit_filter_rejects_revision_from_another_project(client: TestClient) -> None:
    first_project, _first_revision = _project(client, "First")
    _second_project, second_revision = _project(client, "Second")
    response = client.get(
        f"/api/v1/projects/{first_project}/audit", params={"revision_id": second_revision}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "REVISION_COMPARISON_CONFLICT"
