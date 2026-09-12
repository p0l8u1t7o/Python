from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient


def _project(client: TestClient) -> tuple[str, str]:
    response = client.post("/api/v1/projects", json={"name": "Spec test"})
    payload = cast(dict[str, object], response.json())
    revision = cast(dict[str, object], payload["current_revision"])
    return str(payload["id"]), str(revision["id"])


def test_process_spec_round_trip_and_critical_path(client: TestClient) -> None:
    project_id, revision_id = _project(client)
    spec_id = str(uuid4())
    start, long_step, short_step, finish = (str(uuid4()) for _ in range(4))
    payload = {
        "id": spec_id,
        "project_id": project_id,
        "revision_id": revision_id,
        "target_cycle_time_seconds": 9,
        "steps": [
            {"id": start, "name": "Start", "estimated_duration_seconds": 2},
            {
                "id": long_step,
                "name": "Weld",
                "predecessor_ids": [start],
                "estimated_duration_seconds": 5,
            },
            {
                "id": short_step,
                "name": "Inspect",
                "predecessor_ids": [start],
                "estimated_duration_seconds": 1,
            },
            {
                "id": finish,
                "name": "Unload",
                "predecessor_ids": [long_step, short_step],
                "estimated_duration_seconds": 3,
            },
        ],
    }
    route = f"/api/v1/revisions/{revision_id}/process-spec"
    saved = client.put(route, json=payload)
    assert saved.status_code == 200
    assert client.get(route).json() == saved.json()

    analysis = client.get(f"/api/v1/revisions/{revision_id}/process-analysis")
    assert analysis.status_code == 200
    assert analysis.json()["critical_path_step_ids"] == [start, long_step, finish]
    assert analysis.json()["cycle_time_seconds"] == 10
    assert analysis.json()["within_target"] is False


def test_process_spec_rejects_owner_mismatch_and_id_replacement(client: TestClient) -> None:
    project_id, revision_id = _project(client)
    route = f"/api/v1/revisions/{revision_id}/process-spec"
    payload = {
        "id": str(uuid4()),
        "project_id": str(uuid4()),
        "revision_id": revision_id,
        "target_cycle_time_seconds": 10,
        "steps": [{"id": str(uuid4()), "name": "Pick", "estimated_duration_seconds": 1}],
    }
    rejected = client.put(route, json=payload)
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "ENGINEERING_SPEC_CONFLICT"

    payload["project_id"] = project_id
    assert client.put(route, json=payload).status_code == 200
    payload["id"] = str(uuid4())
    assert client.put(route, json=payload).status_code == 409


def test_motion_spec_round_trip_and_missing_spec(client: TestClient) -> None:
    project_id, revision_id = _project(client)
    missing = client.get(f"/api/v1/revisions/{revision_id}/motion-spec")
    assert missing.status_code == 404
    assert missing.json()["code"] == "ENGINEERING_SPEC_NOT_FOUND"

    payload = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "tracks": [
            {
                "id": str(uuid4()),
                "scene_node_id": str(uuid4()),
                "joint_name": "J1",
                "position_unit": "degree",
                "keyframes": [
                    {"time_seconds": 0, "position": 0},
                    {"time_seconds": 2, "position": 90},
                ],
            }
        ],
    }
    route = f"/api/v1/revisions/{revision_id}/motion-spec"
    assert client.put(route, json=payload).status_code == 200
    assert client.get(route).json()["tracks"][0]["joint_name"] == "J1"


def test_scene_assembly_requires_revision_owned_frames_and_artifacts(client: TestClient) -> None:
    project_id, revision_id = _project(client)
    frame_id = str(uuid4())
    node_id = str(uuid4())
    assert (
        client.post(
            f"/api/v1/revisions/{revision_id}/frames",
            json={"frame": {"id": frame_id, "revision_id": revision_id, "name": "Plant"}},
        ).status_code
        == 201
    )
    content = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    uploaded = client.post(
        f"/api/v1/projects/{project_id}/files",
        data={"revision_id": revision_id, "source": "Supplier"},
        files={"file": ("cell.step", content, "application/step")},
    ).json()
    payload = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "nodes": [
            {
                "id": node_id,
                "name": "Robot",
                "asset_version_id": uploaded["id"],
                "coordinate_frame_id": frame_id,
            }
        ],
    }
    route = f"/api/v1/revisions/{revision_id}/scene"
    assert client.put(route, json=payload).status_code == 200
    assert client.get(route).json()["nodes"][0]["name"] == "Robot"

    rejected = client.put(
        route,
        json={
            **payload,
            "nodes": [
                {
                    "id": node_id,
                    "name": "Robot",
                    "asset_version_id": str(uuid4()),
                    "coordinate_frame_id": frame_id,
                }
            ],
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "ENGINEERING_SPEC_CONFLICT"

    motion = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "tracks": [
            {
                "id": str(uuid4()),
                "scene_node_id": str(uuid4()),
                "joint_name": "J1",
                "position_unit": "degree",
                "keyframes": [
                    {"time_seconds": 0, "position": 0},
                    {"time_seconds": 2, "position": 90},
                ],
            }
        ],
    }
    motion_route = f"/api/v1/revisions/{revision_id}/motion-spec"
    rejected_motion = client.put(motion_route, json=motion)
    assert rejected_motion.status_code == 409
    assert rejected_motion.json()["code"] == "ENGINEERING_SPEC_CONFLICT"
    motion_tracks = cast(list[dict[str, object]], motion["tracks"])
    motion_tracks[0]["scene_node_id"] = node_id
    assert client.put(motion_route, json=motion).status_code == 200
