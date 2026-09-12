from typing import Any

from ppe_worker import Worker


class FakeGateway:
    def __init__(self, job: dict[str, object] | None) -> None:
        self.job = job
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def claim(self, worker_id: str, lease_seconds: int) -> dict[str, object] | None:
        self.calls.append(("claim", (worker_id, lease_seconds)))
        return self.job

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int) -> None:
        self.calls.append(("heartbeat", (job_id, worker_id, lease_seconds)))

    def validate(self, revision_id: str) -> dict[str, object]:
        self.calls.append(("validate", (revision_id,)))
        return {"status": "PASSED"}

    def complete(self, job_id: str, worker_id: str) -> None:
        self.calls.append(("complete", (job_id, worker_id)))

    def fail(self, job_id: str, worker_id: str, error: str, *, retryable: bool) -> None:
        self.calls.append(("fail", (job_id, worker_id, error, retryable)))


def test_rules_worker_heartbeats_validates_and_completes() -> None:
    gateway = FakeGateway({"id": "job-1", "revision_id": "revision-1", "tool_name": "ppe-rules"})
    worker = Worker(gateway, "worker-1", lease_seconds=30)

    assert worker.run_once() is True
    assert [call[0] for call in gateway.calls] == ["claim", "heartbeat", "validate", "complete"]


def test_rules_worker_rejects_unconfigured_tools_without_retry() -> None:
    gateway = FakeGateway(
        {"id": "job-1", "revision_id": "revision-1", "tool_name": "vendor-simulator"}
    )
    worker = Worker(gateway, "worker-1")

    assert worker.run_once() is True
    assert gateway.calls[-1][0] == "fail"
    assert gateway.calls[-1][1][-1] is False


def test_rules_worker_reports_idle_queue() -> None:
    assert Worker(FakeGateway(None), "worker-1").run_once() is False
