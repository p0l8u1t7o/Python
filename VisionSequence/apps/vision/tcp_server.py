"""TCP 自動化介面：一行文字指令、一行 JSON 回應（Modbus TCP 設備／上位機最容易接的形式）。

指令（以 \\n 結尾，大小寫不拘）：
    RUN <flow_id 或 名稱> [key=value ...]   執行一次並等結果；回 JSON：
        {"ok": true, "status": "ok|ng|failed", "judge": "OK", "outputs": {...}, "duration_ms": 12.3, "run_id": "..."}
        帶 fmt=<具名輸出> 時**改回那個輸出的純文字**（給讀不了 JSON 的舊設備）：
        `RUN 1 fmt=text` → `OK,12.35\r\n`。那一行由流程裡的「格式化回覆」工具產生；
        沒有那個輸出時仍回 JSON 錯誤 {"ok": false, "code": "no_such_output"}，設備才知道是自己設錯。
    TRIGGER <flow> [key=value ...]         只觸發不等結果；回 {"ok": true, "queued": true, "run_id": "..."}
                                           結果之後用 GET /api/vision/runs/{run_id} 取（排隊中回 status="queued"）
    STATUS [flow]                          統計；不帶流程回容量（含 max_queue_per_flow 與 lock）
    START <flow> / STOP <flow>             連續模式
    LOCK [reason="..." ttl=秒]             鎖定引擎：網頁端只能編輯不能執行，整合方照常
    UNLOCK                                 解鎖
    LIST                                   所有流程
    VARS <flow|station>                    流程或站台的變數（累計、上一片、料號）：{"ok": true, "items": {...}}
    SET <flow|station> key=value ...       寫變數（換線送料號、重置計數）；立刻落地。值的型別規則同 RUN 的引數
    PING                                   {"ok": true, "pong": true}
    AUTH <key>                             設了 VISION_TCP_AUTH 時，連線後其他指令之前先送（PING 不用）；
                                           沒送或錯誤回 {"ok": false, "code": "unauthorized"}
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

import hmac
import orjson
from django.conf import settings
from django.db import close_old_connections

from apps.accounts.models import EngineLock
from apps.accounts.security import Principal
from apps.core import audit
from apps.core.errors import APIError
from apps.vision import trace, variables
from apps.vision.models import Flow
from apps.vision.runner import runner

log = logging.getLogger(__name__)


class _TcpActor:
    """稽核用的假 request：TCP 介面在受信任的產線網路上，身分一律記成整合方而不是 system。"""

    auth = Principal(kind="integrator")
    META: dict[str, str] = {}


_ACTOR = _TcpActor()


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
        return {"ok": False, "error": "Empty command", "code": "empty_command"}
    cmd = parts[0].upper()
    try:
        if cmd == "PING":
            return {"ok": True, "pong": True}
        if cmd in ("LOCK", "UNLOCK"):
            lock = EngineLock.current()
            if cmd == "UNLOCK":
                lock.release()
                audit.record(_ACTOR, "lock.release", target_type="engine")
                return {"ok": True, "lock": lock.to_dict()}
            try:
                args = _parse_kv(parts[1:])
            except BadArgument as bad:
                return {"ok": False, "error": f"The argument '{bad.token}' is not key=value; quote a value containing spaces", "code": "bad_argument"}
            ttl = args.pop("ttl", None) or args.pop("ttl_s", None)
            lock.acquire("integrator", str(args.pop("reason", "") or ""), int(ttl) if str(ttl or "").strip().isdigit() else None)
            audit.record(_ACTOR, "lock.acquire", summary=lock.reason or "integrator", target_type="engine", target_name="integrator")
            return {"ok": True, "lock": lock.to_dict()}
        if cmd == "LIST":
            return {"ok": True, "flows": [{"id": f.id, "name": f.name, "enabled": f.is_enabled} for f in Flow.objects.all()]}
        if cmd in ("VARS", "SET"):
            if len(parts) < 2:
                return {"ok": False, "error": f"{cmd} needs a flow id, a flow name or 'station'", "code": "missing_argument"}
            if parts[1].lower() == "station":
                scope, label = None, "station"
            else:
                flow = _find_flow(parts[1])
                if flow is None:
                    return {"ok": False, "error": f"Flow '{parts[1]}' does not exist", "code": "flow_not_found"}
                scope, label = flow.id, flow.name
            variables.store.ensure_loaded(scope)
            if cmd == "SET":
                try:
                    values = _parse_kv(parts[2:])
                except BadArgument as bad:
                    return {"ok": False, "error": f"The argument '{bad.token}' is not key=value; quote a value containing spaces", "code": "bad_argument"}
                if not values:
                    return {"ok": False, "error": "SET needs at least one key=value", "code": "missing_argument"}
                for key, value in values.items():
                    try:
                        variables.store.set(scope, key, value)
                    except variables.VariableError as exc:
                        return {"ok": False, "error": f"{key}: {exc}", "code": "bad_variable"}
                variables.store.flush()
            return {"ok": True, "scope": label, "items": variables.store.snapshot(scope)}
        if cmd in ("RUN", "TRIGGER", "START", "STOP", "STATUS"):
            if cmd == "STATUS" and len(parts) == 1:
                return {"ok": True, **runner.capacity(), "lock": EngineLock.current().to_dict()}
            if len(parts) < 2:
                return {"ok": False, "error": f"{cmd} needs a flow id or name", "code": "missing_argument"}
            flow = _find_flow(parts[1])
            if flow is None:
                return {"ok": False, "error": f"Flow '{parts[1]}' does not exist", "code": "flow_not_found"}
            if cmd == "STATUS":
                rt = runner.runtime(flow.id)
                return {"ok": True, "flow_id": flow.id, "stats": rt.stats.to_dict(), "continuous": runner.is_continuous(flow.id),
                        "queued": rt.queued, "running": rt.running, "concurrency": flow.concurrency,
                        "max_queue_per_flow": runner.max_queue_per_flow}
            if cmd == "START":
                runner.start_continuous(flow)
                return {"ok": True, "continuous": True}
            if cmd == "STOP":
                runner.stop_continuous(flow.id)
                return {"ok": True, "continuous": False}
            try:
                context = _parse_kv(parts[2:])
            except BadArgument as bad:
                return {"ok": False, "error": f"The argument '{bad.token}' is not key=value; quote a value containing spaces", "code": "bad_argument"}
            recipe = context.pop("recipe", None)
            fmt = str(context.pop("fmt", "") or "")
            if cmd == "TRIGGER":
                future = runner.submit(flow, trigger="tcp", context=context or None, recipe=recipe)
                return {"ok": True, "queued": True, "run_id": getattr(future, "run_id", "")}
            report = runner.run_sync(flow, trigger="tcp", context=context or None, recipe=recipe)
            if fmt:
                # 純文字回覆：設備要的就是這一行，不再包一層 JSON
                value = report.outputs.get(fmt)
                if value is None:
                    return {"ok": False, "error": f"This run produced no output named '{fmt}'; add a Format a reply step",
                            "code": "no_such_output", "outputs": sorted(report.outputs)}
                return {"_raw": value if isinstance(value, str) else str(value)}
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
        matched = match_rules(line)
        if matched is not None:  # 不是指令的一行：交給站台接收規則（條碼槍直接送料號就是這一種）
            return matched
        return {"ok": False, "error": f"Unknown command {cmd}", "code": "unknown_command"}
    except APIError as exc:
        return {"ok": False, "error": exc.message, "code": exc.code}
    except Exception as exc:  # noqa: BLE001
        log.exception("TCP 指令失敗：%s", line)
        return {"ok": False, "error": repr(exc), "code": "internal_error"}


def match_rules(line: str) -> dict[str, Any] | None:
    """不是指令的一行 → 站台接收規則（`apps/comm/rules.py`）。沒有規則相符回 None。

    規則可以帶回覆樣板：有樣板就回純文字（走既有的 `{"_raw"}` 通道，設備讀不了 JSON 也接得上），
    沒有就回一則 JSON 說做了什麼。動作失敗回 `code: "rule_failed"`，設備才診斷得出是規則設錯。
    """
    from apps.comm import rules as rulemod

    text = (line or "").strip()
    if not text:
        return None
    for rule in rulemod.station_rules():
        captured = rulemod.match_text(rule, text)
        if captured is None:
            continue
        try:
            outcome = rulemod.fire(rule, {"text": text, **captured}, trigger="tcp")
        except Exception as exc:  # noqa: BLE001 — 規則設錯不該讓連線斷掉
            log.warning("接收規則失敗（%s）：%s", rule.label(), exc)
            return {"ok": False, "error": str(exc)[:300], "code": "rule_failed", "rule": rule.label()}
        if rule.reply:
            outputs = outcome.get("outputs") or {}
            values = {
                "text": text, **captured, **outputs,
                "status": outcome.get("status", ""), "run_id": outcome.get("run_id", ""),
                "judge": outputs.get("judge", str(outcome.get("status", "")).upper()),
            }
            payload = rulemod.render(rule.reply, values)
            return {"_raw": payload if payload.endswith(("\n", "\r")) else payload + "\n"}
        return {
            "ok": bool(outcome.get("ok", True)), "rule": rule.label(), "action": rule.action,
            "status": outcome.get("status", ""), "run_id": outcome.get("run_id", ""),
            "outputs": outcome.get("outputs", {}), "summary": outcome.get("summary", ""),
        }
    return None


def tcp_secret() -> str:
    return str(settings.VISION.get("TCP_AUTH", "") or "")


class Session:
    """一條 TCP 連線的認證狀態：設了金鑰就要先 AUTH，之後這條連線都有效；金鑰為空＝相容舊設備，不驗證。"""

    def __init__(self, secret: str | None = None) -> None:
        self.secret = tcp_secret() if secret is None else secret
        self.authed = not self.secret

    def command(self, line: str) -> tuple[dict[str, Any], str]:
        """處理一行；回 (回應, 記進追蹤的文字——AUTH 的金鑰遮掉)。"""
        parts = _split(line)
        cmd = parts[0].upper() if parts else ""
        if cmd == "AUTH":
            given = parts[1] if len(parts) > 1 else ""
            ok = bool(self.secret) and hmac.compare_digest(given, self.secret)
            if self.secret:
                self.authed = ok  # 沒設金鑰的站台 AUTH 只是回錯，不會把開放的連線鎖起來
            if ok:
                return {"ok": True, "authenticated": True}, "AUTH ***"
            time.sleep(0.5)  # 猜金鑰的節流
            return {"ok": False, "error": "Bad key" if self.secret else "No TCP key is configured on this station", "code": "unauthorized"}, "AUTH ***"
        if not self.authed and cmd != "PING":
            return {"ok": False, "error": "Send AUTH <key> first", "code": "unauthorized"}, line.strip()[:200]
        return handle_command(line), line.strip()[:200]


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        session = Session()
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
                response, shown = session.command(line)
            finally:
                close_old_connections()  # 每條連線一條執行緒，各自的連線各自收
            trace.record(  # 整合頁「命令與結果」看得到（沒人在看時只記錯誤）
                "tcp", shown or "(blank)", direction="in", name=f"{self.client_address[0]}:{self.client_address[1]}",
                detail=response, ok=bool(response.get("ok", "_raw" in response)), ms=(time.perf_counter() - started) * 1000,
            )
            try:
                raw = response.get("_raw") if isinstance(response, dict) else None
                self.wfile.write(raw.encode("utf-8", errors="replace") if isinstance(raw, str) else orjson.dumps(response) + b"\n")
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
