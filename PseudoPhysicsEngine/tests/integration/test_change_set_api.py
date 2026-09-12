from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient
from ppe_api.db import ChangeSetRecord, ProjectRevisionRecord, create_database_engine
from sqlalchemy import func, select


def _create_project_with_plant(client: TestClient) -> tuple[str, str, str]:
    project_response = client.post("/api/v1/projects", json={"name": "ChangeSet test"})
    project = cast(dict[str, object], project_response.json())
    revision = cast(dict[str, object], project["current_revision"])
    project_id = str(project["id"])
    revision_id = str(revision["id"])
    plant_id = str(uuid4())
    frame_response = client.post(
        f"/api/v1/revisions/{revision_id}/frames",
        json={"frame": {"id": plant_id, "revision_id": revision_id, "name": "Plant"}},
    )
    assert frame_response.status_code == 201
    return project_id, revision_id, plant_id


def _rename_plant_change_set(
    project_id: str,
    revision_id: str,
    plant_id: str,
    *,
    approved: bool,
) -> dict[str, object]:
    request: dict[str, object] = {
        "id": str(uuid4()),
        "project_id": project_id,
        "base_revision_id": revision_id,
        "reason": "Use the customer's coordinate naming convention",
        "user_instruction": "Rename Plant to Plant Main",
        "interpreted_intent": "Rename the existing root frame without moving it",
        "operations": [
            {
                "operation": "UPDATE",
                "object_type": "CoordinateFrame",
                "object_id": plant_id,
                "before": {"name": "Plant"},
                "after": {"name": "Plant Main"},
            }
        ],
    }
    if approved:
        request["approved_by"] = str(uuid4())
    return request


def test_preview_is_valid_and_does_not_mutate_base_revision(client: TestClient) -> None:
    project_id, revision_id, plant_id = _create_project_with_plant(client)
    change_set = _rename_plant_change_set(project_id, revision_id, plant_id, approved=False)

    response = client.post(f"/api/v1/revisions/{revision_id}/changesets/preview", json=change_set)

    assert response.status_code == 200
    preview = response.json()
    assert preview["valid"] is True
    assert preview["issues"] == []
    assert preview["affected_object_ids"] == [plant_id]
    base_tree = client.get(f"/api/v1/revisions/{revision_id}/frames").json()
    assert base_tree["frames"][0]["name"] == "Plant"


def test_approved_apply_creates_immutable_successor_and_is_idempotent(
    client: TestClient, database_url: str
) -> None:
    project_id, revision_id, plant_id = _create_project_with_plant(client)
    change_set = _rename_plant_change_set(project_id, revision_id, plant_id, approved=True)
    route = f"/api/v1/revisions/{revision_id}/changesets/apply"

    first_response = client.post(route, json=change_set)

    assert first_response.status_code == 201
    applied = first_response.json()
    result_revision_id = applied["revision"]["id"]
    assert applied["revision"]["sequence"] == 2
    assert applied["revision"]["parent_revision_id"] == revision_id
    assert applied["revision"]["status"] == "DRAFT"
    assert applied["frame_tree"]["revision_id"] == result_revision_id
    assert applied["frame_tree"]["frames"] == [
        {
            "id": plant_id,
            "revision_id": result_revision_id,
            "name": "Plant Main",
            "parent_frame_id": None,
            "length_unit": "mm",
            "axis_system": "RIGHT_HANDED_Z_UP",
        }
    ]
    assert (
        client.get(f"/api/v1/revisions/{revision_id}/frames").json()["frames"][0]["name"] == "Plant"
    )

    replay_response = client.post(route, json=change_set)
    assert replay_response.status_code == 201
    assert replay_response.json() == applied

    rejected_mutation = client.post(
        f"/api/v1/revisions/{revision_id}/frames",
        json={
            "frame": {
                "id": str(uuid4()),
                "revision_id": revision_id,
                "name": "Second root",
            }
        },
    )
    assert rejected_mutation.status_code == 409
    assert rejected_mutation.json()["code"] == "REVISION_IMMUTABLE"

    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ProjectRevisionRecord)) == 2
        assert connection.scalar(select(func.count()).select_from(ChangeSetRecord)) == 1
    engine.dispose()


def test_apply_requires_approval_without_creating_revision(
    client: TestClient, database_url: str
) -> None:
    project_id, revision_id, plant_id = _create_project_with_plant(client)
    change_set = _rename_plant_change_set(project_id, revision_id, plant_id, approved=False)

    response = client.post(f"/api/v1/revisions/{revision_id}/changesets/apply", json=change_set)

    assert response.status_code == 422
    assert response.json()["code"] == "CHANGE_SET_REJECTED"
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ProjectRevisionRecord)) == 1
        assert connection.scalar(select(func.count()).select_from(ChangeSetRecord)) == 0
    engine.dispose()


def test_invalid_frame_tree_is_previewed_and_rejected_atomically(
    client: TestClient, database_url: str
) -> None:
    project_id, revision_id, _plant_id = _create_project_with_plant(client)
    change_set = {
        "id": str(uuid4()),
        "project_id": project_id,
        "base_revision_id": revision_id,
        "reason": "Add another plant origin",
        "user_instruction": "Add Plant 2",
        "interpreted_intent": "Add a second root frame",
        "operations": [
            {
                "operation": "ADD",
                "object_type": "CoordinateFrame",
                "object_id": str(uuid4()),
                "after": {"name": "Plant 2"},
            }
        ],
        "approved_by": str(uuid4()),
    }

    preview = client.post(f"/api/v1/revisions/{revision_id}/changesets/preview", json=change_set)
    assert preview.status_code == 200
    assert preview.json()["valid"] is False
    assert {issue["code"] for issue in preview.json()["issues"]} == {"INVALID_FRAME_TREE"}

    applied = client.post(f"/api/v1/revisions/{revision_id}/changesets/apply", json=change_set)
    assert applied.status_code == 422
    assert applied.json()["code"] == "CHANGE_SET_REJECTED"

    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ProjectRevisionRecord)) == 1
        assert connection.scalar(select(func.count()).select_from(ChangeSetRecord)) == 0
    engine.dispose()


def test_apply_copies_child_frame_and_transform_with_stable_uuids(client: TestClient) -> None:
    project_id, revision_id, plant_id = _create_project_with_plant(client)
    machine_id = str(uuid4())
    transform_id = str(uuid4())
    matrix = [
        [1, 0, 0, 1_250],
        [0, 1, 0, -300],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ]
    child_response = client.post(
        f"/api/v1/revisions/{revision_id}/frames",
        json={
            "frame": {
                "id": machine_id,
                "revision_id": revision_id,
                "name": "Machine",
                "parent_frame_id": plant_id,
            },
            "transform_from_parent": {
                "id": transform_id,
                "revision_id": revision_id,
                "parent_frame_id": plant_id,
                "child_frame_id": machine_id,
                "matrix": matrix,
                "trust_status": "DRAWING_CONFIRMED",
                "source": "Layout A-001",
            },
        },
    )
    assert child_response.status_code == 201
    change_set = _rename_plant_change_set(project_id, revision_id, plant_id, approved=True)

    response = client.post(f"/api/v1/revisions/{revision_id}/changesets/apply", json=change_set)

    assert response.status_code == 201
    tree = response.json()["frame_tree"]
    assert {frame["id"] for frame in tree["frames"]} == {plant_id, machine_id}
    assert tree["transforms"] == [
        {
            "id": transform_id,
            "revision_id": tree["revision_id"],
            "parent_frame_id": plant_id,
            "child_frame_id": machine_id,
            "matrix": matrix,
            "trust_status": "DRAWING_CONFIRMED",
            "source": "Layout A-001",
        }
    ]


def test_apply_copies_complete_engineering_snapshot(client: TestClient) -> None:
    project_id, revision_id, plant_id = _create_project_with_plant(client)
    content = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    artifact = client.post(
        f"/api/v1/projects/{project_id}/files",
        data={"revision_id": revision_id, "source": "Supplier"},
        files={"file": ("robot.step", content, "application/step")},
    ).json()
    step_id = str(uuid4())
    process = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "target_cycle_time_seconds": 10,
        "steps": [{"id": step_id, "name": "Pick", "estimated_duration_seconds": 2}],
    }
    assert (
        client.put(f"/api/v1/revisions/{revision_id}/process-spec", json=process).status_code == 200
    )
    track_id = str(uuid4())
    node_id = str(uuid4())
    motion = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "tracks": [
            {
                "id": track_id,
                "scene_node_id": node_id,
                "joint_name": "J1",
                "position_unit": "degree",
                "keyframes": [
                    {"time_seconds": 0, "position": 0},
                    {"time_seconds": 2, "position": 90},
                ],
            }
        ],
    }
    assert (
        client.put(f"/api/v1/revisions/{revision_id}/motion-spec", json=motion).status_code == 200
    )
    scene = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "nodes": [
            {
                "id": node_id,
                "name": "Robot",
                "asset_version_id": artifact["id"],
                "coordinate_frame_id": plant_id,
            }
        ],
    }
    assert client.put(f"/api/v1/revisions/{revision_id}/scene", json=scene).status_code == 200

    change_set = _rename_plant_change_set(project_id, revision_id, plant_id, approved=True)
    applied = client.post(
        f"/api/v1/revisions/{revision_id}/changesets/apply", json=change_set
    ).json()
    result_revision_id = applied["revision"]["id"]

    copied_artifacts = client.get(
        f"/api/v1/projects/{project_id}/artifacts",
        params={"revision_id": result_revision_id},
    ).json()
    assert len(copied_artifacts) == 1
    assert copied_artifacts[0]["id"] != artifact["id"]
    assert copied_artifacts[0]["sha256"] == artifact["sha256"]
    copied_process = client.get(f"/api/v1/revisions/{result_revision_id}/process-spec").json()
    assert copied_process["id"] != process["id"]
    assert copied_process["revision_id"] == result_revision_id
    assert copied_process["steps"][0]["id"] == step_id
    copied_motion = client.get(f"/api/v1/revisions/{result_revision_id}/motion-spec").json()
    assert copied_motion["tracks"][0]["id"] == track_id
    copied_scene = client.get(f"/api/v1/revisions/{result_revision_id}/scene").json()
    assert copied_scene["nodes"][0]["id"] == node_id
    assert copied_scene["nodes"][0]["asset_version_id"] == copied_artifacts[0]["id"]
