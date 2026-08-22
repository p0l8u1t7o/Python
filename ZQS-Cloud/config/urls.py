from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.urls import path

from config.api import api


def healthz(request):
    """Liveness probe - intentionally does not touch the database."""
    return JsonResponse({"status": "ok"})


def _run_stream(request, run_id):
    # Imported lazily so plain manage.py commands do not pay the workflows
    # import chain for a route they never serve.
    from apps.workflows.stream import run_stream

    return run_stream(request, run_id)


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    # Registered before the ninja router: a streaming response cannot go
    # through the schema layer, and EventSource cannot set auth headers, so
    # this one route handles both itself.
    path("api/workflow-runs/<uuid:run_id>/stream", _run_stream, name="run-stream"),
    path("api/", api.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
