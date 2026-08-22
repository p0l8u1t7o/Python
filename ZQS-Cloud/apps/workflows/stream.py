"""Server-sent events for watching a workflow run.

Why SSE and not the 1-second polling it replaces: the editor needs to track a
token that spends two seconds on a node, and per-request polling pays HTTP
overhead (auth, routing, serialisation) once per second per watcher. One
streaming response holds a single connection and only sends bytes when
something changed.

What this is - and honestly is not: the server still *checks* the database on
a short interval, because the engine lives in another process and SQLite has
no cross-process notify. The win is at the HTTP layer (one connection, deltas
only), not a message bus. True push would need Redis pub/sub and an ASGI
server, which is the documented production upgrade path, not the dev default.

Auth is the normal bearer token, passed as ``?token=`` because EventSource
cannot set headers. The stream closes itself after ``MAX_STREAM_SECONDS`` and
the client reconnects - that bounds how long a dev-server thread is held, and
also re-validates the (short-lived) token on every reconnect.
"""

from __future__ import annotations

import time

import orjson
from django.http import HttpResponse, StreamingHttpResponse

from apps.accounts.security import api_auth
from apps.core.errors import APIError
from apps.workflows.models import TERMINAL_STATUSES, WorkflowLog, WorkflowRun

POLL_SECONDS = 1.0
MAX_STREAM_SECONDS = 55
HEARTBEAT_SECONDS = 15


def _run_payload(run: WorkflowRun) -> dict:
    return {
        "id": str(run.id),
        "workflow_id": str(run.workflow_id),
        "status": run.status,
        "trigger": run.trigger,
        "dry_run": run.dry_run,
        "workflow_version": run.workflow_version,
        "steps_taken": run.steps_taken,
        "step_delay_seconds": run.step_delay_seconds,
        "error": run.error,
        "context": run.context,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "wake_at": run.wake_at.isoformat() if run.wake_at else None,
        "created_at": run.created_at.isoformat(),
        "active_nodes": sorted({t.node_id for t in run.tokens.all()}),
    }


def _log_payload(log: WorkflowLog) -> dict:
    return {
        "id": log.id,
        "ts": log.ts.isoformat(),
        "node_id": log.node_id,
        "node_label": log.node_label,
        "level": log.level,
        "message": log.message,
        "branch": log.branch,
        "detail": log.detail,
    }


def _sse(event: str, data) -> bytes:
    return b"event: " + event.encode() + b"\ndata: " + orjson.dumps(data) + b"\n\n"


def run_stream(request, run_id):
    """``GET /api/workflow-runs/<id>/stream`` - SSE feed of one run."""
    token = request.GET.get("token", "")
    try:
        ctx = api_auth.authenticate(request, token)
    except APIError:
        return HttpResponse(status=401)

    run = (
        WorkflowRun.objects.filter(pk=run_id, organization=ctx.organization)
        .select_related("workflow")
        .first()
    )
    if run is None:
        return HttpResponse(status=404)

    since = int(request.GET.get("since") or 0)

    def generate():
        nonlocal since
        # Tell the browser to wait only a moment before reconnecting when the
        # window below closes the stream.
        yield b"retry: 1500\n\n"

        last_sent: dict | None = None
        last_beat = time.monotonic()
        deadline = time.monotonic() + MAX_STREAM_SECONDS

        while time.monotonic() < deadline:
            current = (
                WorkflowRun.objects.filter(pk=run.pk)
                .prefetch_related("tokens")
                .first()
            )
            if current is None:
                yield _sse("gone", {})
                return

            payload = _run_payload(current)
            if payload != last_sent:
                last_sent = payload
                yield _sse("run", payload)
                last_beat = time.monotonic()

            logs = list(
                WorkflowLog.objects.filter(run_id=run.pk, id__gt=since).order_by("id")[:200]
            )
            if logs:
                since = logs[-1].id
                yield _sse("logs", [_log_payload(log) for log in logs])
                last_beat = time.monotonic()

            if current.status in TERMINAL_STATUSES:
                # Everything above already went out; the client keeps the
                # final state and stops reconnecting on "done".
                yield _sse("done", {"status": current.status})
                return

            if time.monotonic() - last_beat > HEARTBEAT_SECONDS:
                # Comment line: keeps proxies from timing the connection out.
                yield b": ping\n\n"
                last_beat = time.monotonic()

            time.sleep(POLL_SECONDS)

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    # Nginx and friends buffer streaming bodies unless told not to.
    response["X-Accel-Buffering"] = "no"
    return response
