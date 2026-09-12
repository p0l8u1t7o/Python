from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient
from ppe_worker import Worker


class TestClientGateway:
    __test__ = False

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def claim(self, worker_id: str, lease_seconds: int) -> dict[str, object] | None:
        response = self.client.post(
            "/api/v1/jobs/claim",
            json={
                "worker_id": worker_id,
                "supported_kinds": ["SIMULATE"],
                "lease_seconds": lease_seconds,
            },
        )
        assert response.status_code == 200
        return cast(dict[str, object] | None, response.json())

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int) -> None:
        response = self.client.post(
            f"/api/v1/jobs/{job_id}/heartbeat",
            json={"worker_id": worker_id, "lease_seconds": lease_seconds},
        )
        assert response.status_code == 200

    def validate(self, revision_id: str) -> dict[str, object]:
        response = self.client.post(f"/api/v1/revisions/{revision_id}/validate")
        assert response.status_code == 200
        return cast(dict[str, object], response.json())

    def complete(self, job_id: str, worker_id: str) -> None:
        response = self.client.post(
            f"/api/v1/jobs/{job_id}/complete",
            json={"worker_id": worker_id, "result_artifact_ids": []},
        )
        assert response.status_code == 200

    def fail(self, job_id: str, worker_id: str, error: str, *, retryable: bool) -> None:
        response = self.client.post(
            f"/api/v1/jobs/{job_id}/fail",
            json={"worker_id": worker_id, "error": error, "retryable": retryable},
        )
        assert response.status_code == 200


def test_rules_worker_processes_durable_simulation_job(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Worker integration"}).json()
    project_id = project["id"]
    revision_id = project["current_revision"]["id"]
    submitted = client.post(
        "/api/v1/jobs",
        json={
            "project_id": project_id,
            "revision_id": revision_id,
            "kind": "SIMULATE",
            "idempotency_key": str(uuid4()),
            "tool_name": "ppe-rules",
            "tool_version": "0.1.0",
        },
    )
    assert submitted.status_code == 202

    assert Worker(TestClientGateway(client), "integration-worker").run_once() is True
    completed = client.get(f"/api/v1/jobs/{submitted.json()['id']}")
    assert completed.json()["status"] == "SUCCEEDED"
    report = client.get(f"/api/v1/revisions/{revision_id}/validation")
    assert report.status_code == 200
    assert report.json()["status"] == "FAILED"
