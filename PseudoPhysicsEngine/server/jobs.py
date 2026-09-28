"""In-memory job runner with per-project engineering serialization and SSE events."""

from __future__ import annotations

import asyncio
import json
import traceback
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cellforge.versioning import try_commit_changes

EventEmitter = Callable[[str, dict[str, Any]], None]
JobWorker = Callable[[EventEmitter], Awaitable[dict[str, Any] | None]]

# worker 以此取得自己所屬的 job id，傳給建置子程序寫入版本 manifest。
_current_job: ContextVar[str | None] = ContextVar("cellforge_current_job", default=None)


def current_job_id() -> str | None:
    return _current_job.get()


@dataclass
class Job:
    id: str
    project_id: str
    kind: str
    owner: str
    status: str = "queued"
    created: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    started: str | None = None
    finished: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    task: asyncio.Task | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "owner": self.owner,
            "status": self.status,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "result": self.result,
            "error": self.error,
            "warnings": self.warnings,
        }


class JobRunner:
    def __init__(self, projects_root: Path):
        self.projects_root = projects_root
        self.jobs: dict[str, Job] = {}
        self._engineering_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def submit(
        self,
        project_id: str,
        kind: str,
        worker: JobWorker,
        *,
        owner: str = "engineering",
    ) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], project_id=project_id, kind=kind, owner=owner)
        self.jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job, worker))
        return job

    async def _run(self, job: Job, worker: JobWorker) -> None:
        _current_job.set(job.id)
        lock = self._engineering_locks[job.project_id]
        context = lock if job.owner == "engineering" else _NullAsyncContext()
        try:
            async with context:
                job.status = "running"
                job.started = datetime.now().astimezone().isoformat()
                self.emit(job, "status", {"status": "running", "message": "工作開始"})
                job.result = await worker(lambda kind, data: self.emit(job, kind, data))
                for item in (job.result or {}).get("warnings", []):
                    if str(item) not in job.warnings:
                        job.warnings.append(str(item))
                job.status = "done"
                job.finished = datetime.now().astimezone().isoformat()
                self.emit(job, "complete", {"status": "done", "result": job.result})
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.finished = datetime.now().astimezone().isoformat()
            self.emit(job, "complete", {"status": "cancelled"})
        except Exception as error:  # The job boundary must convert failures into state.
            job.status = "failed"
            job.error = str(error)
            job.finished = datetime.now().astimezone().isoformat()
            self.emit(
                job,
                "error",
                {
                    "status": "failed",
                    "message": str(error),
                    "traceback": traceback.format_exc().splitlines()[-30:],
                },
            )
        # 工作結論已定；log 提交失敗只記警告，不可把完成的工作改判為失敗。
        warning = try_commit_changes(
            self.projects_root / job.project_id,
            f"job {job.id} {job.status}",
            [f"tasks/logs/{job.id}.jsonl"],
        )
        if warning:
            self.emit(job, "warning", {"message": warning})

    def emit(self, job: Job, kind: str, data: dict[str, Any]) -> None:
        event = {
            "seq": len(job.events),
            "time": datetime.now().astimezone().isoformat(),
            "type": kind,
            **data,
        }
        job.events.append(event)
        if kind == "warning" and data.get("message") and data["message"] not in job.warnings:
            job.warnings.append(str(data["message"]))
        log_dir = self.projects_root / job.project_id / "tasks" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / f"{job.id}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def get(self, job_id: str) -> Job:
        try:
            return self.jobs[job_id]
        except KeyError as error:
            raise KeyError(f"找不到工作：{job_id}") from error

    def active(self, project_id: str) -> list[Job]:
        """尚未結束（排隊或執行中）的工作；刪除案子前必須為空。"""
        return [
            job
            for job in self.jobs.values()
            if job.project_id == project_id and job.status in {"queued", "running"}
        ]

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.task and not job.task.done():
            job.task.cancel()
        return job


class _NullAsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None
