from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.urls import path, re_path
from django.views.static import serve

from config.api import api


def healthz(request):
    """免認證的健康檢查：監控系統輪詢用，只回不敏感的東西。"""
    from apps.vision import __version__

    return JsonResponse({"status": "ok", "version": __version__, "station_id": settings.VISION.get("STATION_ID", "")})


def _flow_stream(request, flow_id):
    from apps.vision.stream import flow_stream

    return flow_stream(request, flow_id)


def _events_stream(request):
    from apps.vision.stream import events_stream

    return events_stream(request)


def _spa(request, path=""):
    """前端路由的深連結（/flows/3）一律回 index.html；靜態檔本身由 whitenoise 在中介層供應（settings.WHITENOISE_ROOT），
    到得了這裡的檔案路徑就是不存在的檔案（例如 sourcemap），照樣回 index.html 讓前端路由處理。"""
    index = Path(settings.FRONTEND_DIST) / "index.html"
    if not index.exists():
        raise Http404("The front end has not been built: run npm run build in frontend/")
    response = FileResponse(open(index, "rb"), content_type="text/html")
    response["Cache-Control"] = "no-cache"
    return response


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    # SSE 不經 ninja：串流回應不能過 schema 層。
    path("api/vision/flows/<int:flow_id>/stream", _flow_stream, name="flow-stream"),
    path("api/vision/events", _events_stream, name="events-stream"),
    path("api/", api.urls),
    # 文件（docs/*.html）由 Django 直接提供：全域 AI 助手回答附的參考連結、說明頁連結都指向這裡。
    re_path(r"^docs/(?P<path>(?:img/)?[\w\-]+\.(?:html|png|jpg|jpeg|webp))$", serve, {"document_root": settings.BASE_DIR / "docs"}, name="docs"),
    re_path(r"^(?!api/)(?P<path>.*)$", _spa, name="spa"),
]
