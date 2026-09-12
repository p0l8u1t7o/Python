import json
from typing import Protocol, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class JobGateway(Protocol):
    def claim(self, worker_id: str, lease_seconds: int) -> dict[str, object] | None: ...

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int) -> None: ...

    def validate(self, revision_id: str) -> dict[str, object]: ...

    def complete(self, job_id: str, worker_id: str) -> None: ...

    def fail(self, job_id: str, worker_id: str, error: str, *, retryable: bool) -> None: ...


class HttpJobGateway:
    def __init__(self, api_url: str, timeout_seconds: float = 10) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(
        self, path: str, *, method: str = "POST", body: dict[str, object] | None = None
    ) -> object:
        encoded = json.dumps(body).encode() if body is not None else None
        request = Request(
            f"{self.api_url}{path}",
            data=encoded,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                return json.loads(response.read())
        except HTTPError as error:
            details = error.read().decode(errors="replace")
            raise RuntimeError(f"API {method} {path} failed ({error.code}): {details}") from error

    def claim(self, worker_id: str, lease_seconds: int) -> dict[str, object] | None:
        result = self._request(
            "/jobs/claim",
            body={
                "worker_id": worker_id,
                "supported_kinds": ["SIMULATE"],
                "lease_seconds": lease_seconds,
            },
        )
        if result is None:
            return None
        return cast(dict[str, object], result)

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int) -> None:
        self._request(
            f"/jobs/{job_id}/heartbeat",
            body={"worker_id": worker_id, "lease_seconds": lease_seconds},
        )

    def validate(self, revision_id: str) -> dict[str, object]:
        return cast(dict[str, object], self._request(f"/revisions/{revision_id}/validate"))

    def complete(self, job_id: str, worker_id: str) -> None:
        self._request(
            f"/jobs/{job_id}/complete",
            body={"worker_id": worker_id, "result_artifact_ids": []},
        )

    def fail(self, job_id: str, worker_id: str, error: str, *, retryable: bool) -> None:
        self._request(
            f"/jobs/{job_id}/fail",
            body={"worker_id": worker_id, "error": error[:4000], "retryable": retryable},
        )


class Worker:
    def __init__(self, gateway: JobGateway, worker_id: str, lease_seconds: int = 60) -> None:
        self.gateway = gateway
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def run_once(self) -> bool:
        job = self.gateway.claim(self.worker_id, self.lease_seconds)
        if job is None:
            return False
        job_id = str(job["id"])
        try:
            if job.get("tool_name") != "ppe-rules":
                raise ValueError(
                    f"Unsupported SIMULATE tool {job.get('tool_name')!r}; expected 'ppe-rules'"
                )
            self.gateway.heartbeat(job_id, self.worker_id, self.lease_seconds)
            self.gateway.validate(str(job["revision_id"]))
            self.gateway.complete(job_id, self.worker_id)
        except ValueError as error:
            self.gateway.fail(job_id, self.worker_id, str(error), retryable=False)
        except Exception as error:
            self.gateway.fail(job_id, self.worker_id, str(error), retryable=True)
        return True
