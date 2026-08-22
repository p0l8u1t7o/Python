"""The console's live feed: one SSE connection that says *what changed*.

The ingest pipeline lands a reading in the database 6-30 ms after the broker
saw it. The console then used to find out 5-15 seconds later, on its next
poll. This stream closes that gap: every half second it asks the database
"what moved since last time" - latest values, device status, alerts, device
events, commands - and pushes the affected ids. The console invalidates just
those queries and refetches at once. Observed end-to-end: well under a second
from MQTT publish to the number changing on screen.

Same honesty note as the workflow run stream: the server still *polls* the
database (the worker is another process; SQLite has no notify). The win is
replacing N browser polls at 5 s with one connection at 0.5 s that only
speaks when something happened.
"""

from __future__ import annotations

import time

import orjson
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone

from apps.accounts.security import api_auth
from apps.alerts.models import Alert
from apps.core.errors import APIError
from apps.devices.models import Command, Device, DeviceEvent
from apps.telemetry.models import LatestSample

POLL_SECONDS = 0.5
MAX_STREAM_SECONDS = 55
HEARTBEAT_SECONDS = 15


def _sse(event: str, data) -> bytes:
    return b"event: " + event.encode() + b"\ndata: " + orjson.dumps(data) + b"\n\n"


def live_stream(request):
    """``GET /api/live/stream?token=`` - change notifications for one tenant."""
    token = request.GET.get("token", "")
    try:
        ctx = api_auth.authenticate(request, token)
    except APIError:
        return HttpResponse(status=401)
    organization = ctx.organization

    def generate():
        yield b"retry: 1500\n\n"
        since = timezone.now()
        last_beat = time.monotonic()
        deadline = time.monotonic() + MAX_STREAM_SECONDS

        while time.monotonic() < deadline:
            now = timezone.now()
            sent = False

            telemetry = set(
                LatestSample.objects.filter(
                    organization=organization, updated_at__gte=since
                ).values_list("device_id", flat=True)
            )
            if telemetry:
                yield _sse("telemetry", {"device_ids": [str(d) for d in telemetry]})
                sent = True

            status = set(
                Device.objects.filter(
                    organization=organization, status_changed_at__gte=since
                ).values_list("id", flat=True)
            )
            if status:
                yield _sse("devices", {"device_ids": [str(d) for d in status]})
                sent = True

            alerts = Alert.objects.filter(
                organization=organization, updated_at__gte=since
            ).count()
            if alerts:
                yield _sse("alerts", {"count": alerts})
                sent = True

            events = set(
                DeviceEvent.objects.filter(
                    organization=organization, received_at__gte=since
                ).values_list("device_id", flat=True)
            )
            if events:
                yield _sse("events", {"device_ids": [str(d) for d in events]})
                sent = True

            commands = set(
                Command.objects.filter(
                    organization=organization, updated_at__gte=since
                ).values_list("device_id", flat=True)
            )
            if commands:
                yield _sse("commands", {"device_ids": [str(d) for d in commands]})
                sent = True

            # >= rather than >: on Windows the clock ticks every ~15 ms, so a
            # row stamped in the same tick as `since` would otherwise never be
            # announced. A change reported twice costs one redundant refetch;
            # a change never reported costs a stale screen.
            since = now
            if sent:
                last_beat = time.monotonic()
            elif time.monotonic() - last_beat > HEARTBEAT_SECONDS:
                yield b": ping\n\n"
                last_beat = time.monotonic()

            time.sleep(POLL_SECONDS)

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
