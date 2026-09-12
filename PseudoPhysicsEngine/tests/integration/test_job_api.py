from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx2 import Response
from ppe_api.db import JobRecord, create_database_engine
from sqlalchemy import update


def _project_scope(client: TestClient) -> tuple[str, str]:
    project = client.post("/api/v1/projects", json={"name": "Job test"}).json()
    return project["id"], project["current_revision"]["id"]


def _job_payload(
    project_id: str,
    revision_id: str,
    *,
    key: str = "tessellate-robot-v1",
    max_attempts: int = 3,
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "revision_id": revision_id,
        "kind": "TESSELLATE",
        "idempotency_key": key,
        "input_artifact_ids": [],
        "parameters": {"linear_deflection_mm": 0.1},
        "tool_name": "mock-tessellator",
        "tool_version": "1.0.0",
        "max_attempts": max_attempts,
    }


def _claim(client: TestClient, worker_id: str = "worker-1") -> Response:
    return client.post(
        "/api/v1/jobs/claim",
        json={
            "worker_id": worker_id,
            "supported_kinds": ["TESSELLATE"],
            "lease_seconds": 60,
        },
    )


def test_submit_is_idempotent_and_conflicting_reuse_is_rejected(client: TestClient) -> None:
    project_id, revision_id = _project_scope(client)
    payload = _job_payload(project_id, revision_id)

    first = client.post("/api/v1/jobs", json=payload)
    replay = client.post("/api/v1/jobs", json=payload)

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json() == first.json()
    assert first.json()["status"] == "PENDING"
    listed = client.get(f"/api/v1/projects/{project_id}/jobs", params={"revision_id": revision_id})
    assert listed.status_code == 200
    assert listed.json() == [first.json()]
    changed = dict(payload)
    changed["tool_version"] = "2.0.0"
    conflict = client.post("/api/v1/jobs", json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "JOB_CONFLICT"


def test_claim_heartbeat_and_complete_enforce_worker_lease(client: TestClient) -> None:
    project_id, revision_id = _project_scope(client)
    submitted = client.post("/api/v1/jobs", json=_job_payload(project_id, revision_id)).json()

    claimed_response = _claim(client)
    assert claimed_response.status_code == 200
    claimed = claimed_response.json()
    assert claimed["id"] == submitted["id"]
    assert claimed["status"] == "RUNNING"
    assert claimed["worker_id"] == "worker-1"
    assert claimed["attempt_count"] == 1

    wrong_worker = client.post(
        f"/api/v1/jobs/{submitted['id']}/heartbeat",
        json={"worker_id": "worker-2", "lease_seconds": 60},
    )
    assert wrong_worker.status_code == 409

    heartbeat = client.post(
        f"/api/v1/jobs/{submitted['id']}/heartbeat",
        json={"worker_id": "worker-1", "lease_seconds": 120},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["lease_expires_at"] > claimed["lease_expires_at"]

    completed = client.post(
        f"/api/v1/jobs/{submitted['id']}/complete",
        json={"worker_id": "worker-1", "result_artifact_ids": []},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "SUCCEEDED"
    assert completed.json()["finished_at"] is not None


def test_retryable_failure_requeues_until_max_attempts(client: TestClient) -> None:
    project_id, revision_id = _project_scope(client)
    job = client.post(
        "/api/v1/jobs",
        json=_job_payload(project_id, revision_id, max_attempts=2),
    ).json()
    _claim(client)

    first_failure = client.post(
        f"/api/v1/jobs/{job['id']}/fail",
        json={"worker_id": "worker-1", "error": "temporary", "retryable": True},
    )
    assert first_failure.json()["status"] == "PENDING"
    second_claim = _claim(client, "worker-2")
    assert second_claim.json()["attempt_count"] == 2

    final_failure = client.post(
        f"/api/v1/jobs/{job['id']}/fail",
        json={"worker_id": "worker-2", "error": "still broken", "retryable": True},
    )
    assert final_failure.json()["status"] == "FAILED"
    assert final_failure.json()["finished_at"] is not None


def test_expired_lease_is_reclaimed_and_exhausted_job_fails(
    client: TestClient, database_url: str
) -> None:
    project_id, revision_id = _project_scope(client)
    job = client.post(
        "/api/v1/jobs",
        json=_job_payload(project_id, revision_id, max_attempts=2),
    ).json()
    _claim(client)

    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            update(JobRecord)
            .where(JobRecord.id == job["id"])
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    engine.dispose()

    expired_heartbeat = client.post(
        f"/api/v1/jobs/{job['id']}/heartbeat",
        json={"worker_id": "worker-1", "lease_seconds": 60},
    )
    assert expired_heartbeat.status_code == 409

    reclaimed = _claim(client, "worker-2")
    assert reclaimed.status_code == 200
    assert reclaimed.json()["id"] == job["id"]
    assert reclaimed.json()["attempt_count"] == 2
    assert reclaimed.json()["worker_id"] == "worker-2"

    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            update(JobRecord)
            .where(JobRecord.id == job["id"])
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    engine.dispose()
    assert _claim(client, "worker-3").json() is None
    exhausted = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert exhausted["status"] == "FAILED"
    assert exhausted["error"] == "Worker lease expired after maximum attempts"


def test_pending_job_can_be_cancelled(client: TestClient) -> None:
    project_id, revision_id = _project_scope(client)
    job = client.post(
        "/api/v1/jobs", json=_job_payload(project_id, revision_id, key=str(uuid4()))
    ).json()

    cancelled = client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert _claim(client).json() is None
