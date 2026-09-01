"""TCP 自動化介面：一行文字指令、一行 JSON 回應（Modbus TCP 設備／上位機最容易接的形式）。

指令（以 \\n 結尾，大小寫不拘）：
    RUN <flow_id 或 名稱> [key=value ...]   執行一次並等結果；回 JSON：
        {"ok": true, "status": "ok|ng|failed", "judge": "OK", "outputs": {...}, "duration_ms": 12.3, "run_id": "..."}
    TRIGGER <flow>                         只觸發不等結果；回 {"ok": true, "queued": true}
    STATUS [flow]                          統計
    START <flow> / STOP <flow>             連續模式
    LIST                                   所有流程
    PING                                   {"ok": true, "pong": true}
錯誤回 {"ok": false, "error": "..."}。

每條連線一條執行緒；指令與執行交給 runner（同一執行緒池、同樣的並行上限）。
與 HTTP API 同一個行程執行（manage.py runserver 或 uvicorn 帶 --tcp）才能共享引擎狀態，
所以以 `start_in_background()` 由 `run_tcp_server` 命令或 apps.ready 啟動。
"""

from __future__ import annotations

import logging
import socket
import socketserver
import threading
from typing import Any

import orjson
from django.db import close_old_connections

from apps.core.errors import APIError
from apps.vision.models import Flow
from apps.vision.runner import runner

log = logging.getLogger(__name__)


def _find_flow(ident: str) -> Flow | None:
    if ident.isdigit():
        return Flow.objects.filter(pk=int(ident)).first()
    return Flow.objects.filter(name=ident).first()


def _parse_kv(tokens: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tok in tokens:
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        try:
            out[k] = float(v) if "." in v else int(v)
        except ValueError:
            out[k] = v
    return out


def handle_command(line: str) -> dict[str, Any]:
    parts = line.strip().split()
    if not parts:
        return {"ok": False, "error": "empty"}
    cmd = parts[0].upper()
    try:
        if cmd == "PING":
            return {"ok": True, "pong": True}
        if cmd == "LIST":
            return {"ok": True, "flows": [{"id": f.id, "name": f.name, "enabled": f.is_enabled} for f in Flow.objects.all()]}
        if cmd in ("RUN", "TRIGGER", "START", "STOP", "STATUS"):
            if cmd == "STATUS" and len(parts) == 1:
                return {"ok": True, **runner.capacity()}
            if len(parts) < 2:
                return {"ok": False, "error": f"{cmd} 需要流程 id 或名稱"}
            flow = _find_flow(parts[1])
            if flow is None:
                return {"ok": False, "error": f"流程 '{parts[1]}' 不存在"}
            if cmd == "STATUS":
                return {"ok": True, "flow_id": flow.id, "stats": runner.runtime(flow.id).stats.to_dict(), "continuous": runner.is_continuous(flow.id)}
            if cmd == "START":
                runner.start_continuous(flow)
                return {"ok": True, "continuous": True}
            if cmd == "STOP":
                runner.stop_continuous(flow.id)
                return {"ok": True, "continuous": False}
            context = _parse_kv(parts[2:])
            recipe = context.pop("recipe", None)
            if cmd == "TRIGGER":
                runner.submit(flow, trigger="tcp", context=context or None, recipe=recipe)
                return {"ok": True, "queued": True}
            report = runner.run_sync(flow, trigger="tcp", context=context or None, recipe=recipe)
            return {
                "ok": True,
                "status": report.status,
                "station_id": report.station_id,
                "recipe": report.recipe,
                "warnings": report.warnings,
                "judge": report.outputs.get("judge", report.status.upper()),
                "outputs": report.outputs,
                "duration_ms": round(report.duration_ms, 2),
                "run_id": report.id,
                "error": report.error,
            }
        return {"ok": False, "error": f"未知指令 {cmd}"}
    except APIError as exc:
        return {"ok": False, "error": exc.message, "code": exc.code}
    except Exception as exc:  # noqa: BLE001
        log.exception("TCP 指令失敗：%s", line)
        return {"ok": False, "error": repr(exc)}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        while True:
            try:
                raw = self.rfile.readline()
            except (ConnectionResetError, OSError):
                return
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace")
            try:
                response = handle_command(line)
            finally:
                close_old_connections()  # 每條連線一條執行緒，各自的連線各自收
            try:
                self.wfile.write(orjson.dumps(response) + b"\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


_server: _Server | None = None


def start_in_background(host: str, port: int) -> _Server:
    global _server
    if _server is not None:
        return _server
    _server = _Server((host, port), _Handler)
    thread = threading.Thread(target=_server.serve_forever, name="vision-tcp", daemon=True)
    thread.start()
    log.info("TCP 自動化介面監聽 %s:%s", host, port)
    return _server


def stop() -> None:
    global _server
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
