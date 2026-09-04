"""TCP 自動化介面：一行文字指令、一行 JSON 回應（Modbus TCP 設備／上位機最容易接的形式）。

指令（以 \\n 結尾，大小寫不拘）：
    RUN <flow_id 或 名稱> [key=value ...]   執行一次並等結果；回 JSON：
        {"ok": true, "status": "ok|ng|failed", "judge": "OK", "outputs": {...}, "duration_ms": 12.3, "run_id": "..."}
    TRIGGER <flow> [key=value ...]         只觸發不等結果；回 {"ok": true, "queued": true, "run_id": "..."}
                                           結果之後用 GET /api/vision/runs/{run_id} 取（排隊中回 status="queued"）
    STATUS [flow]                          統計；不帶流程回容量（含 max_queue_per_flow）
    START <flow> / STOP <flow>             連續模式
    LIST                                   所有流程
    PING                                   {"ok": true, "pong": true}
錯誤回 {"ok": false, "error": "...", "code": "..."}；code 是穩定的英數字串，設備請用它分支
（empty_command／unknown_command／missing_argument／bad_argument／flow_not_found／flow_queue_full…）。

引數的型別：值預設是字串，只有「乾淨的十進位數字」（1、-3、2.5）才轉成數字，
所以 lot=00123 保留前導零、sn=1_000 不會變成 1000。值含空白請用引號：
RUN 1 barcode="ABC DEF"；流程名稱含空白同理 RUN "我的 流程"。

每條連線一條執行緒；指令與執行交給 runner（同一執行緒池、同樣的並行上限）。
與 HTTP API 同一個行程執行（manage.py runserver 或 uvicorn 帶 --tcp）才能共享引擎狀態，
所以以 `start_in_background()` 由 `run_tcp_server` 命令或 apps.ready 啟動。
"""

from __future__ import annotations

import logging
import re
import shlex
import socket
import socketserver
import threading
import time
from typing import Any

import orjson
from django.db import close_old_connections

from apps.core.errors import APIError
from apps.vision import trace
from apps.vision.models import Flow
from apps.vision.runner import runner

log = logging.getLogger(__name__)


def _find_flow(ident: str) -> Flow | None:
    if ident.isdigit():
        return Flow.objects.filter(pk=int(ident)).first()
    return Flow.objects.filter(name=ident).first()


class BadArgument(ValueError):
    """引數不是 key=value（多半是值含空白又沒加引號）；靜默丟掉會讓料號憑空消失。"""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


#: 只有這種形狀才當數字：前導零（00123）、底線（1_000）、指數（1e3）一律保留成字串，
#: 否則料號、批號與條碼會被悄悄改掉。
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def _split(line: str) -> list[str]:
    """分詞：支援引號包住含空白的值（barcode="ABC DEF"）；引號不成對時退回空白切分。"""
    try:
        return shlex.split(line.strip())
    except ValueError:
        return line.strip().split()


def _parse_kv(tokens: list[str]) -> dict[str, Any]:
    """key=value → context。值預設是字串，只有乾淨的十進位數字才轉型。"""
    out: dict[str, Any] = {}
    for tok in tokens:
        k, sep, v = tok.partition("=")
        if not sep or not k:
            raise BadArgument(tok)
        out[k] = (float(v) if "." in v else int(v)) if _NUMBER.match(v) else v
    return out


def handle_command(line: str) -> dict[str, Any]:
    parts = _split(line)
    if not parts:
        return {"ok": False, "error": "空白指令", "code": "empty_command"}
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
                return {"ok": False, "error": f"{cmd} 需要流程 id 或名稱", "code": "missing_argument"}
            flow = _find_flow(parts[1])
            if flow is None:
                return {"ok": False, "error": f"流程 '{parts[1]}' 不存在", "code": "flow_not_found"}
            if cmd == "STATUS":
                rt = runner.runtime(flow.id)
                return {"ok": True, "flow_id": flow.id, "stats": rt.stats.to_dict(), "continuous": runner.is_continuous(flow.id),
                        "queued": rt.queued, "running": rt.running, "max_queue_per_flow": runner.max_queue_per_flow}
            if cmd == "START":
                runner.start_continuous(flow)
                return {"ok": True, "continuous": True}
            if cmd == "STOP":
                runner.stop_continuous(flow.id)
                return {"ok": True, "continuous": False}
            try:
                context = _parse_kv(parts[2:])
            except BadArgument as bad:
                return {"ok": False, "error": f"引數 '{bad.token}' 不是 key=value；值含空白請用引號", "code": "bad_argument"}
            recipe = context.pop("recipe", None)
            if cmd == "TRIGGER":
                future = runner.submit(flow, trigger="tcp", context=context or None, recipe=recipe)
                return {"ok": True, "queued": True, "run_id": getattr(future, "run_id", "")}
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
        return {"ok": False, "error": f"未知指令 {cmd}", "code": "unknown_command"}
    except APIError as exc:
        return {"ok": False, "error": exc.message, "code": exc.code}
    except Exception as exc:  # noqa: BLE001
        log.exception("TCP 指令失敗：%s", line)
        return {"ok": False, "error": repr(exc), "code": "internal_error"}


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
            started = time.perf_counter()
            try:
                response = handle_command(line)
            finally:
                close_old_connections()  # 每條連線一條執行緒，各自的連線各自收
            trace.record(  # 整合頁「命令與結果」看得到（沒人在看時只記錯誤）
                "tcp", line.strip()[:200] or "(空白)", direction="in", name=f"{self.client_address[0]}:{self.client_address[1]}",
                detail=response, ok=bool(response.get("ok", True)), ms=(time.perf_counter() - started) * 1000,
            )
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
