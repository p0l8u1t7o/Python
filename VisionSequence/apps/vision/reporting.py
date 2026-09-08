"""流程結果回送：跑完就把結果送給上位機，不必在圖裡接線。

PLC 客戶的第一個問題永遠是「結果怎麼回來」。圖裡接一顆「寫入 Modbus」或「格式化回覆」
一直都做得到，但每條流程都要接一次，而且換一台上位機就要改所有的圖。這一層把它變成
流程的一項設定（`Flow.comm`）：**哪條連線、什麼時候送、OK 與 NG 各送什麼**。

與站台事件回報（`apps/comm/events.py`）的分工：那一層報的是站台層的事，走事件匯流排，
忙起來會漏；**這一層是逐片的**，跑完在同一條執行緒裡直接送，不經佇列也不經匯流排，
所以不會漏掉任何一片。

只對「送得出文字」的連線有意義（`Writer.texts`）——Modbus 是位址對位址的，把
`OK,12.35` 寫進暫存器沒有意義，那種需求請在圖裡用「寫入 Modbus」把值對到位址。

上位機沒開著的時候不能拖住產線：送失敗就記一次追蹤，並且在 `RETRY_S` 秒內不再試
（每片都等連線逾時會讓節拍整個垮掉）。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: 什麼時候送。on_finish＝每跑完一片就送；interval＝每 N 毫秒送一次最近一片的結果。
WHENS = ("on_finish", "interval")
#: 條件裡看的節點狀態（與 engine.NodeReport 同一組字）。
NODE_STATUSES = ("any", "ok", "ng", "error", "skipped")
#: 一條流程最多幾條回送規則（畫面上是一張表，超過就不是設定而是程式了）。
MAX_RULES = 10
#: 送失敗之後多久才再試一次（上位機沒開著時不要每片都等到逾時）。
RETRY_S = 2.0
MIN_INTERVAL_MS = 200


@dataclass(frozen=True)
class Rule:
    id: str = ""
    name: str = ""
    enabled: bool = True
    connection: str = ""
    when: str = "on_finish"
    interval_ms: int = 1000
    node: str = ""
    node_status: str = "any"
    ok: str = ""
    ng: str = ""
    failed: str = ""

    def template_for(self, status: str) -> str:
        return {"ok": self.ok, "ng": self.ng}.get(status, self.failed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "enabled": self.enabled, "connection": self.connection,
            "when": self.when, "interval_ms": self.interval_ms, "node": self.node, "node_status": self.node_status,
            "ok": self.ok, "ng": self.ng, "failed": self.failed,
        }


def _text(value: Any, limit: int = 500) -> str:
    return str(value if value is not None else "")[:limit]


def _rule_from(raw: Any, index: int) -> Rule | None:
    if not isinstance(raw, dict):
        return None
    connection = _text(raw.get("connection"), 120).strip()
    if not connection:
        return None
    when = str(raw.get("when") or "on_finish").strip().lower()
    when = when if when in WHENS else "on_finish"
    status = str(raw.get("node_status") or "any").strip().lower()
    try:
        interval = int(raw.get("interval_ms") or 1000)
    except (TypeError, ValueError):
        interval = 1000
    rule = Rule(
        id=_text(raw.get("id"), 40).strip() or f"c{index + 1}",
        name=_text(raw.get("name"), 80).strip(),
        enabled=bool(raw.get("enabled", True)),
        connection=connection,
        when=when,
        interval_ms=max(MIN_INTERVAL_MS, interval),
        node=_text(raw.get("node"), 80).strip(),
        node_status=status if status in NODE_STATUSES else "any",
        ok=_text(raw.get("ok")),
        ng=_text(raw.get("ng")),
        failed=_text(raw.get("failed")),
    )
    if not (rule.ok or rule.ng or rule.failed):
        return None  # 三種都沒有樣板就沒有東西可送
    return rule


def sanitize(raw: Any) -> list[dict[str, Any]]:
    """存檔前正規化（壞掉的列丟掉，比照 board.sanitize——壞設定不讓流程頁炸）。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw[:MAX_RULES]):
        rule = _rule_from(item, i)
        if rule is None:
            continue
        ident = rule.id if rule.id not in seen else f"c{i + 1}"
        seen.add(ident)
        out.append(Rule(**{**rule.as_dict(), "id": ident}).as_dict())
    return out


def parse(raw: Any) -> list[Rule]:
    if not isinstance(raw, list):
        return []
    return [r for r in (_rule_from(item, i) for i, item in enumerate(raw[:MAX_RULES])) if r is not None and r.enabled]


# ---------------------------------------------------------------------------
# 樣板的值
# ---------------------------------------------------------------------------
def values_for(report, flow_name: str = "") -> dict[str, Any]:
    """能填進樣板的名字：具名輸出 → 觸發帶進來的引數，另有 judge／status／run_id／station／flow…

    與「格式化回覆」工具同一套名字，使用者學一次就好。
    """
    values: dict[str, Any] = {}
    for key, value in (report.outputs or {}).items():
        values[str(key)] = value
    for key, value in (report.context or {}).items():
        if not str(key).startswith("_"):
            values.setdefault(str(key), value)
    values.setdefault("judge", str(report.status).upper())
    values.update({
        "status": report.status, "run_id": report.id, "station": report.station_id,
        "flow": flow_name, "flow_id": report.flow_id, "recipe": report.recipe,
        "duration_ms": round(report.duration_ms, 2), "error": report.error, "ts": int(time.time()),
    })
    return values


def wanted(rule: Rule, report) -> bool:
    """這一片要不要送：有樣板、而且條件節點的狀態符合。"""
    if not rule.template_for(report.status):
        return False
    if not rule.node:
        return True
    node = (report.nodes or {}).get(rule.node)
    if node is None:
        return False
    status = node.get("status", "") if isinstance(node, dict) else getattr(node, "status", "")
    return rule.node_status == "any" or status == rule.node_status


# ---------------------------------------------------------------------------
# 送出
# ---------------------------------------------------------------------------
@dataclass
class _State:
    """一條規則的送出狀態（失敗退避、定時送的下一拍、最近一次的值）。"""

    blocked_until: float = 0.0
    next_beat: float = 0.0
    values: dict[str, Any] = field(default_factory=dict)
    status: str = ""
    sent: int = 0
    errors: int = 0
    last_error: str = ""


_lock = threading.Lock()
_states: dict[tuple[int, str], _State] = {}
#: flow_id → (流程名稱, 規則)。在呼叫者執行緒由 `runner.compiled_for` 寫入，
#: 引擎執行緒只讀——熱路徑不碰資料庫。
_registry: dict[int, tuple[str, list[Rule]]] = {}
_ticker: "_Ticker | None" = None


def set_rules(flow_id: int, raw: Any, name: str = "") -> list[Rule]:
    """呼叫者執行緒：把這條流程的回送規則放進記憶體（`Flow.comm` 是唯一事實來源）。"""
    rules = parse(raw)
    with _lock:
        if rules:
            _registry[flow_id] = (name, rules)
        else:
            _registry.pop(flow_id, None)
    if any(r.when == "interval" for r in rules):
        _ensure_ticker()
    return rules


def rules_for(flow_id: int) -> list[Rule]:
    with _lock:
        entry = _registry.get(flow_id)
    return list(entry[1]) if entry else []


def _state(flow_id: int, rule_id: str) -> _State:
    key = (flow_id, rule_id)
    with _lock:
        state = _states.get(key)
        if state is None:
            state = _states[key] = _State()
        return state


def forget(flow_id: int) -> None:
    """流程刪掉或設定改了：忘掉退避與定時送的狀態。"""
    with _lock:
        _registry.pop(flow_id, None)
        for key in [k for k in _states if k[0] == flow_id]:
            _states.pop(key, None)


def status(flow_id: int) -> list[dict[str, Any]]:
    with _lock:
        return [{"rule": rid, "sent": s.sent, "errors": s.errors, "last_error": s.last_error}
                for (fid, rid), s in _states.items() if fid == flow_id]


def _send(rule: Rule, text: str, state: _State, *, flow_id: int) -> None:
    from apps.comm.writers import get_writer

    now = time.monotonic()
    if now < state.blocked_until:  # 上位機沒開著：先不要每片都等到逾時
        return
    writer = get_writer(rule.connection)
    try:
        if writer is None:
            raise LookupError(f"Connection '{rule.connection}' is not open")
        if not getattr(writer, "texts", False):
            raise TypeError(f"Connection '{rule.connection}' cannot send a line of text; map values to addresses with a Write Modbus step instead")
        writer.send_text(text, quiet=True)
        state.sent += 1
    except Exception as exc:  # noqa: BLE001 — 回送失敗不能讓產線停
        state.errors += 1
        state.last_error = str(exc)[:200]
        state.blocked_until = now + RETRY_S
        _trace(rule, text, str(exc)[:200], flow_id=flow_id)


def _trace(rule: Rule, text: str, error: str, *, flow_id: int) -> None:
    """失敗才記（每片都記會把真正的命令沖出環形緩衝，與心跳同一個規則）。"""
    try:
        from apps.vision import trace

        trace.record("tcp", f"Result -> {rule.connection}: {text[:80]}", direction="out",
                     name=rule.connection, ok=False, detail={"flow_id": flow_id, "rule": rule.id, "error": error})
    except Exception:  # noqa: BLE001 — 追蹤不能影響回送
        pass


def deliver(report, flow_name: str = "") -> int:
    """跑完一片時呼叫（引擎執行緒）。回實際送出的則數。

    `interval` 的規則只把值記下來，由計時執行緒定時送——那是給「上位機要固定節拍」的
    場合用的；逐片回送用 `on_finish`，跑完就在這裡送出去，不經佇列也不經事件匯流排。
    """
    with _lock:
        entry = _registry.get(report.flow_id)
    if not entry:
        return 0
    from apps.comm.rules import render

    name = flow_name or entry[0]
    values = None
    sent = 0
    for rule in entry[1]:
        state = _state(report.flow_id, rule.id)
        if rule.when == "interval":
            if wanted(rule, report):
                values = values if values is not None else values_for(report, name)
                state.values = values
                state.status = report.status
            continue
        if not wanted(rule, report):
            continue
        values = values if values is not None else values_for(report, name)
        _send(rule, render(rule.template_for(report.status), values), state, flow_id=report.flow_id)
        sent += 1
    return sent


def tick() -> int:
    """定時送：每一條 `interval` 規則到點就送最近一片的結果。回送出的則數。"""
    from apps.comm.rules import render

    now = time.monotonic()
    with _lock:
        entries = list(_registry.items())
    sent = 0
    for flow_id, (_name, rules) in entries:
        for rule in rules:
            if rule.when != "interval":
                continue
            state = _state(flow_id, rule.id)
            if not state.values or now < state.next_beat:  # 還沒跑過任何一片就沒有東西好送
                continue
            state.next_beat = now + rule.interval_ms / 1000.0
            template = rule.template_for(state.status)
            if template:
                _send(rule, render(template, state.values), state, flow_id=flow_id)
                sent += 1
    return sent


class _Ticker(threading.Thread):
    """定時送的計時器（整個行程一條，不是一條流程一條）。"""

    def __init__(self) -> None:
        super().__init__(name="vision-report-tick", daemon=True)
        self.halt = threading.Event()

    def run(self) -> None:
        while not self.halt.wait(0.1):
            try:
                tick()
            except Exception:  # noqa: BLE001 — 計時器不能死
                log.warning("結果定時回送失敗", exc_info=True)


def _ensure_ticker() -> None:
    global _ticker
    with _lock:
        if _ticker is not None and _ticker.is_alive():
            return
        _ticker = _Ticker()
    _ticker.start()


def stop_ticker() -> None:
    """測試與關機用。"""
    global _ticker
    with _lock:
        current, _ticker = _ticker, None
    if current is not None:
        current.halt.set()
