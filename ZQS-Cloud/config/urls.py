from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.urls import path

from config.api import api


def healthz(request):
    """Liveness probe - intentionally does not touch the database."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("api/", api.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
