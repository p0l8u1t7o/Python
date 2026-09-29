"""
鋁質殼體 AOI＋共焦量測半自動設備 — 3D 設備模擬（Three.js / WebGL）
啟動本地 HTTP 伺服器並開啟瀏覽器。

    python serve.py            # 預設 http://localhost:8774
    python serve.py --port 9000
    python serve.py --no-open  # 不自動開瀏覽器

ES module 需要以 http:// 載入（file:// 會被瀏覽器擋下），所以用這支小程式提供靜態檔案。
所有依賴（three.module.js、OrbitControls.js、RoomEnvironment.js）都已放在 web/vendor，離線可用。
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import threading
import webbrowser
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent / "web"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """靜態檔案 handler：正確的 MIME、關閉快取（方便改檔即看）、精簡 log。"""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401
        if self.path.endswith((".html", "/")):
            super().log_message(fmt, *args)


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    ap = argparse.ArgumentParser(description="3D 設備模擬本地伺服器")
    ap.add_argument("--port", type=int, default=8774)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true", help="不自動開啟瀏覽器")
    args = ap.parse_args()

    if not (WEB_ROOT / "index.html").exists():
        raise SystemExit(f"找不到 {WEB_ROOT / 'index.html'}")

    handler = functools.partial(QuietHandler, directory=str(WEB_ROOT))
    with ReusableTCPServer((args.host, args.port), handler) as httpd:
        url = f"http://{args.host}:{args.port}/"
        print(f"[serve] 3D 模擬：{url}   (Ctrl+C 結束)")
        if not args.no_open:
            threading.Timer(0.6, webbrowser.open, args=(url,)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] bye")


if __name__ == "__main__":
    main()
