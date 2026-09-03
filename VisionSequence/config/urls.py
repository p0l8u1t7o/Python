from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.urls import path, re_path
from django.views.static import serve

from config.api import api


def healthz(request):
    return JsonResponse({"status": "ok"})


def _flow_stream(request, flow_id):
    from apps.vision.stream import flow_stream

    return flow_stream(request, flow_id)


def _events_stream(request):
    from apps.vision.stream import events_stream

    return events_stream(request)


def _spa(request, path=""):
    """正式環境：前端 build 產物由 Django 直接提供（前端路由一律回 index.html）。"""
    dist = Path(settings.FRONTEND_DIST)
    index = dist / "index.html"
    if not index.exists():
        raise Http404("前端尚未 build：在 frontend/ 執行 npm run build")
    candidate = dist / path
    if path and candidate.is_file():
        return serve(request, path, document_root=dist)
    return FileResponse(open(index, "rb"), content_type="text/html")


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    # SSE 不經 ninja：串流回應不能過 schema 層。
    path("api/vision/flows/<int:flow_id>/stream", _flow_stream, name="flow-stream"),
    path("api/vision/events", _events_stream, name="events-stream"),
    path("api/", api.urls),
    # 文件（docs/*.html）由 Django 直接提供：全域 AI 助手回答附的參考連結、說明頁連結都指向這裡。
    re_path(r"^docs/(?P<path>[\w\-]+\.html)$", serve, {"document_root": settings.BASE_DIR / "docs"}, name="docs"),
    re_path(r"^(?!api/)(?P<path>.*)$", _spa, name="spa"),
]
