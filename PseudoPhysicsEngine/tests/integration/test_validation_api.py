from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient


def _project(client: TestClient) -> tuple[str, str]:
    payload = cast(
        dict[str, object], client.post("/api/v1/projects", json={"name": "Validation"}).json()
    )
    revision = cast(dict[str, object], payload["current_revision"])
    return str(payload["id"]), str(revision["id"])


def test_validation_persists_actionable_missing_input_issues(client: TestClient) -> None:
    _project_id, revision_id = _project(client)
    missing = client.get(f"/api/v1/revisions/{revision_id}/validation")
    assert missing.status_code == 404
    assert missing.json()["code"] == "VALIDATION_REPORT_NOT_FOUND"

    response = client.post(f"/api/v1/revisions/{revision_id}/validate")
    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "FAILED"
    assert {issue["code"] for issue in report["issues"]} == {
        "PROCESS_SPEC_MISSING",
        "MOTION_SPEC_MISSING",
        "SCENE_ASSEMBLY_MISSING",
        "STEP_ARTIFACT_MISSING",
        "COORDINATE_FRAME_MISSING",
    }
    assert client.get(f"/api/v1/revisions/{revision_id}/validation").json() == report


def test_complete_revision_passes_vendor_neutral_validation(client: TestClient) -> None:
    project_id, revision_id = _project(client)
    step_id = str(uuid4())
    scene_node_id = str(uuid4())
    process = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "target_cycle_time_seconds": 10,
        "steps": [{"id": step_id, "name": "Transfer", "estimated_duration_seconds": 3}],
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
                "joint_name": "linear_axis",
                "position_unit": "mm",
                "keyframes": [
                    {"time_seconds": 0, "position": 0},
                    {"time_seconds": 3, "position": 1000},
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
    step_content = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    upload = client.post(
        f"/api/v1/projects/{project_id}/files",
        data={"revision_id": revision_id, "source": "Supplier"},
        files={"file": ("machine.step", step_content, "application/step")},
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

    report = client.post(f"/api/v1/revisions/{revision_id}/validate")
    assert report.status_code == 200
    assert report.json()["status"] == "PASSED"
    assert report.json()["issues"] == []


def test_validation_reports_cycle_motion_and_trust_blockers(client: TestClient) -> None:
    project_id, revision_id = _project(client)
    root_id, child_id = str(uuid4()), str(uuid4())
    route = f"/api/v1/revisions/{revision_id}/frames"
    assert (
        client.post(
            route, json={"frame": {"id": root_id, "revision_id": revision_id, "name": "Plant"}}
        ).status_code
        == 201
    )
    assert (
        client.post(
            route,
            json={
                "frame": {
                    "id": child_id,
                    "revision_id": revision_id,
                    "name": "RobotBase",
                    "parent_frame_id": root_id,
                },
                "transform_from_parent": {
                    "id": str(uuid4()),
                    "revision_id": revision_id,
                    "parent_frame_id": root_id,
                    "child_frame_id": child_id,
                    "matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                    "trust_status": "INFERRED",
                    "source": "Estimate",
                },
            },
        ).status_code
        == 201
    )
    process = {
        "id": str(uuid4()),
        "project_id": project_id,
        "revision_id": revision_id,
        "target_cycle_time_seconds": 2,
        "assumptions": ["Payload TBD"],
        "unresolved_questions": ["Which gripper?"],
        "steps": [{"id": str(uuid4()), "name": "Pick", "estimated_duration_seconds": 4}],
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
                "scene_node_id": str(uuid4()),
                "joint_name": "J1",
                "position_unit": "degree",
                "keyframes": [
                    {"time_seconds": 0, "position": 0},
                    {"time_seconds": 5, "position": 90},
                ],
            }
        ],
    }
    assert (
        client.put(f"/api/v1/revisions/{revision_id}/motion-spec", json=motion).status_code == 200
    )

    report = client.post(f"/api/v1/revisions/{revision_id}/validate").json()
    codes = {issue["code"] for issue in report["issues"]}
    assert {
        "CYCLE_TIME_EXCEEDED",
        "MOTION_EXCEEDS_TARGET",
        "PROCESS_QUESTIONS_UNRESOLVED",
        "PROCESS_ASSUMPTIONS_REMAIN",
        "STEP_ARTIFACT_MISSING",
        "INFERRED_COORDINATE",
        "SCENE_ASSEMBLY_MISSING",
    } <= codes
    warning = next(
        issue for issue in report["issues"] if issue["code"] == "PROCESS_ASSUMPTIONS_REMAIN"
    )
    assert warning["blocks_release"] is False


def test_open_review_comments_block_validation_until_resolved(client: TestClient) -> None:
    _project_id, revision_id = _project(client)
    reviewer = str(uuid4())
    comment = client.post(
        f"/api/v1/revisions/{revision_id}/comments",
        json={"author_id": reviewer, "body": "Confirm the guarded area"},
    )
    assert comment.status_code == 201

    first_codes = {
        issue["code"]
        for issue in client.post(f"/api/v1/revisions/{revision_id}/validate").json()["issues"]
    }
    assert "REVIEW_COMMENTS_OPEN" in first_codes

    assert (
        client.post(
            f"/api/v1/comments/{comment.json()['id']}/resolve",
            json={"resolved_by": reviewer},
        ).status_code
        == 200
    )
    second_codes = {
        issue["code"]
        for issue in client.post(f"/api/v1/revisions/{revision_id}/validate").json()["issues"]
    }
    assert "REVIEW_COMMENTS_OPEN" not in second_codes
