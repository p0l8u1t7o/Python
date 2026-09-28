"""Playwright snapshot helper for the minimal viewer."""

from __future__ import annotations

import functools
import http.server
import shutil
import socketserver
import threading
from pathlib import Path

from cellforge.derived import record_build_snapshot

VIEWPORT = (1280, 720)


class SnapshotError(RuntimeError):
    pass


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass


def snapshot_project(
    project_dir: Path, time_s: float, camera: str, output: Path | None = None
) -> Path:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    platform_root = Path(__file__).resolve().parents[1]
    viewer_dist = platform_root / "web" / "dist"
    if not viewer_dist.is_dir():
        viewer_dist = Path(__file__).resolve().parent / "_viewer"
    if not (viewer_dist / "index.html").is_file():
        raise SnapshotError("缺少 web/dist；請先在 web 執行 npm install 與 npm run build")
    if not (project_dir / "build" / "scene.glb").is_file():
        raise SnapshotError("缺少 build/scene.glb；請先執行 cell build")
    target_viewer = project_dir / "build" / "viewer"
    if target_viewer.exists():
        shutil.rmtree(target_viewer)
    shutil.copytree(viewer_dist, target_viewer)
    output = output or project_dir / "build" / f"snapshot_t{time_s:g}_{camera}.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(_QuietHandler, directory=str(project_dir))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(headless=True)
                except PlaywrightError as error:
                    raise SnapshotError(
                        "Playwright Chromium 尚未安裝；請執行 playwright install chromium"
                    ) from error
                page = browser.new_page(viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]})
                browser_errors: list[str] = []
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                page.on(
                    "requestfailed",
                    lambda request: browser_errors.append(
                        f"{request.url}: {request.failure or 'request failed'}"
                    ),
                )
                url = (
                    f"http://127.0.0.1:{port}/build/viewer/index.html"
                    f"?scene=/build/scene.glb&timeline=/build/timeline.json&t={time_s}&cam={camera}"
                )
                try:
                    page.goto(url, wait_until="networkidle")
                    page.wait_for_function("window.cellforgeReady === true", timeout=30_000)
                except PlaywrightError as error:
                    details = "；".join(browser_errors[-5:]) or str(error)
                    raise SnapshotError(f"檢視器載入失敗：{details}") from error
                page.screenshot(path=str(output))
                browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
    # 已封存的 vN 不可改寫；截圖登記為 build/ 所鏡像版本的衍生檔。
    record_build_snapshot(
        project_dir,
        output,
        {"time_s": time_s, "camera": camera, "viewport": list(VIEWPORT), "renderer": "playwright"},
    )
    return output
