"""FastAPI 應用組裝。

設計要點
--------
* 回應約定：成功直接回傳資料；失敗一律 {ok:false, error:{code,message,detail}}。
  前端只需在 status >= 400 時讀 error，其餘直接用 body。
* 靜態檔（web/、docs/）由同一個服務提供，離線單機部署不需要另外架 nginx。
* /api/health 回報真實依賴狀態（資料庫可讀、模型可算），不是只回 200。
* 啟動時不做重運算：第一次分析在第一個請求進來時才觸發，避免拖慢啟動。
"""

from __future__ import annotations

import time
import traceback

import json
import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..config import SETTINGS, resource_path
from ..logging_setup import get_logger, setup_logging
from ..service import get_service
from .routers import analysis, assistant, batches, optimize

log = get_logger(__name__)

_START_MS = int(time.time() * 1000)


def _sanitize(obj: Any) -> Any:
    """把 NaN / ±Inf 換成 None。

    這些值在數值計算中是合法的「無法計算」訊號（例如批次數不足時的 R²、
    bootstrap 失敗時的信賴區間），但不是合法的 JSON。若不處理，序列化會
    直接丟 ValueError 變成 500——使用者只會看到「伺服器錯誤」，完全不知道
    真正的意思是「這個數字算不出來」。轉成 null 後，前端的 num() 會顯示
    「—」，語意正確。
    """
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


class SafeJSONResponse(JSONResponse):
    """全域套用的回應類別，確保不會因為 NaN 而變成 500。"""

    def render(self, content: Any) -> bytes:
        return json.dumps(
            _sanitize(content), ensure_ascii=False, allow_nan=False,
            separators=(",", ":"), default=str,
        ).encode("utf-8")


def _error(status: int, code: str, message: str, detail: str = "") -> JSONResponse:
    return SafeJSONResponse(status_code=status,
                            content={"ok": False, "data": None,
                                     "error": {"code": code, "message": message,
                                               "detail": detail}})


def create_app() -> FastAPI:
    setup_logging(SETTINGS.log_level, SETTINGS.log_dir)

    app = FastAPI(
        title="ExpAnalysis — 高純銦偏析純化製程分析平台",
        version=__version__,
        description=(
            "物理模型（Pfann + BPS）為骨架、AI 分層疊加的離線製程分析工具。"
            "本系統不參與任何設備控制。"),
        docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json",
        default_response_class=SafeJSONResponse,
    )

    # ── 統一回應包裝 ────────────────────────────────────────────
    @app.middleware("http")
    async def wrap_response(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/docs"):
            dur = (time.perf_counter() - t0) * 1000
            response.headers["X-Response-Time-Ms"] = f"{dur:.1f}"
            if dur > 3000:
                log.info("慢請求 %s %s：%.0f ms", request.method, request.url.path, dur)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return _error(exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail))
        # 非 API 路徑回傳人看得懂的頁面。
        # 注意這裡**不能 raise exc**：重新拋出的 HTTPException 沒有人接，
        # 會被最外層守護當成未處理例外，把一個普通的 404（例如瀏覽器自動請求
        # /favicon.ico）變成 500 並印出整段 traceback。
        return HTMLResponse(status_code=exc.status_code, content=(
            f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            f"<title>{exc.status_code}</title>"
            f"<style>body{{font-family:system-ui,'Microsoft JhengHei',sans-serif;"
            f"background:#0f1319;color:#e7edf5;display:grid;place-items:center;"
            f"height:100vh;margin:0;text-align:center}}"
            f"a{{color:#4c8dff}}</style></head><body><div>"
            f"<h1 style='font-size:44px;margin:0'>{exc.status_code}</h1>"
            f"<p style='color:#aab6c6'>{exc.detail}</p>"
            f"<p><a href='/'>回到分析平台</a> · <a href='/docs/'>說明文件</a></p>"
            f"</div></body></html>"))

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        first = (exc.errors() or [{}])[0]
        loc = " → ".join(str(x) for x in first.get("loc", []))
        return _error(422, "VALIDATION_ERROR",
                      f"參數驗證失敗：{loc} {first.get('msg', '')}",
                      str(exc.errors())[:800])

    @app.exception_handler(Exception)
    async def unhandled_exc(request: Request, exc: Exception):
        # 最外層守護：記錄完整 traceback，回給前端的訊息不含堆疊細節
        log.error("未處理的例外 %s %s\n%s", request.method, request.url.path,
                  traceback.format_exc())
        return _error(500, "INTERNAL_ERROR",
                      "伺服器內部錯誤，詳細內容已寫入日誌。",
                      f"{type(exc).__name__}: {exc}")

    # ── 路由 ───────────────────────────────────────────────────
    for r in (batches.router, analysis.router, optimize.router, assistant.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        checks, ok = {}, True
        try:
            svc = get_service()
            n = svc.repo.count()
            checks["database"] = {"ok": True, "n_batches": n, "path": str(svc.db.path)}
        except Exception as exc:            # noqa: BLE001
            # 健康檢查是「最需要它時最不能壞」的端點。sqlite3.Error 既不是
            # RuntimeError 也不是 OSError，若只抓那兩種，資料庫損毀時這裡會
            # 拋出去被全域處理器接走變成 500——正好在該回報 ok:false 的時候失效。
            ok = False
            checks["database"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        try:
            from ..physics.profile_grid import get_profile_grid
            g = get_profile_grid(0.1, 2, 60)
            checks["physics"] = {"ok": bool(g.profiles.size)}
        except Exception as exc:            # noqa: BLE001
            ok = False
            checks["physics"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        try:
            from ..assistant.provider import make_provider
            checks["assistant"] = {"ok": True,
                                   "provider": make_provider(get_service()).name}
        except Exception as exc:            # noqa: BLE001
            checks["assistant"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": ok, "version": __version__,
                "uptime_ms": int(time.time() * 1000) - _START_MS,
                "checks": checks}

    @app.get("/api/config")
    def config():
        """前端啟動時取得的執行期設定。不含任何金鑰。"""
        return {
            "version": __version__,
            "purity_threshold_ppm": SETTINGS.purity_threshold_ppm,
            "default_elements": list(SETTINGS.elements),
            "residual_clip_frac": SETTINGS.residual_clip_frac,
        }

    # ── 靜態檔案 ────────────────────────────────────────────────
    web_dir = resource_path("web")
    docs_dir = resource_path("docs")
    if docs_dir.is_dir():
        app.mount("/docs", StaticFiles(directory=str(docs_dir), html=True), name="docs")
    if web_dir.is_dir():
        app.mount("/css", StaticFiles(directory=str(web_dir / "css")), name="css")
        app.mount("/js", StaticFiles(directory=str(web_dir / "js")), name="js")

        @app.get("/")
        def index():
            return FileResponse(str(web_dir / "index.html"))

        @app.get("/favicon.svg")
        @app.get("/favicon.ico")          # 瀏覽器會自動請求這個路徑
        def favicon():
            fav = web_dir / "favicon.svg"
            if fav.is_file():
                return FileResponse(str(fav), media_type="image/svg+xml")
            return _error(404, "NOT_FOUND", "no favicon")
    else:
        log.warning("找不到 web 目錄（%s），只提供 API", web_dir)

    log.info("ExpAnalysis %s 已就緒（資料庫：%s）", __version__, SETTINGS.db_path)
    return app


app = create_app()
