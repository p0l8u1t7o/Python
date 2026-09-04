"""Fleet board: one read-only view of several independent stations.

Each station is its own server with its own engine — that is deliberate, and it is what stops one
line's problem from taking out another. The cost is that a plant with twenty stations had twenty
web addresses and no way to see the yield in one place.

This module fixes the view without touching the architecture: any instance can be told about other
stations (name, base URL, API key) and will poll their `GET /vision/summary` endpoint. Nothing is
pushed — no flows, no accounts, no commands — so a board is a spectator and a station never depends
on one being there.

Two rules that matter on a shop floor:

- **A stale number must never look live.** When a station cannot be reached the board keeps its last
  figures but marks it offline and shows how old they are.
- **Polling only while somebody is watching.** The refresher thread starts on the first request and
  stops itself once no one has asked for a while, so a station that is not a board costs nothing.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from django.conf import settings

log = logging.getLogger(__name__)

#: How often the refresher polls every station.
INTERVAL_S = 10.0
#: Per-station HTTP timeout; a dead station must not hold up the others.
TIMEOUT_S = 4.0
#: Stop polling when nobody has looked at the board for this long.
IDLE_STOP_S = 180.0

_lock = threading.Lock()
#: station id → last successful snapshot plus liveness
_state: dict[int, dict[str, Any]] = {}
_thread: threading.Thread | None = None
_watch_until = 0.0


def _cfg(key: str, default: Any) -> Any:
    return getattr(settings, "VISION", {}).get(key, default)


# ---------------------------------------------------------------------------
# Talking to one station
# ---------------------------------------------------------------------------
def fetch(base_url: str, api_key: str = "", *, timeout: float = TIMEOUT_S) -> dict[str, Any]:
    """Ask one station for its summary. Raises on anything that is not a usable answer."""
    url = base_url.rstrip("/")
    if not url.endswith("/api"):
        url += "/api"
    request = urllib.request.Request(f"{url}/vision/summary", headers={"Accept": "application/json"})
    if api_key:
        request.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — 站台位址由管理員設定
        body = json.loads(response.read() or b"{}")
    if not isinstance(body, dict) or "flows" not in body:
        raise ValueError("not a VisionSequence station summary")
    return body


def _reason(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return "API key rejected"
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"unreachable ({getattr(exc, 'reason', '')})"
    return str(exc)[:120] or type(exc).__name__


def _poll_one(row) -> None:
    entry = _state.setdefault(row.id, {"summary": None, "checked_at": 0.0, "online": False, "error": "", "last_ok_at": 0.0})
    try:
        summary = fetch(row.base_url, row.api_key)
    except Exception as exc:  # noqa: BLE001 — 站台掛掉是常態，看板要照樣活著
        entry.update(online=False, error=_reason(exc), checked_at=time.time())
        return
    entry.update(summary=summary, online=True, error="", checked_at=time.time(), last_ok_at=time.time())


def refresh(rows) -> None:
    """Poll every station in parallel; one slow station must not delay the rest."""
    rows = list(rows)
    if not rows:
        return
    with ThreadPoolExecutor(max_workers=min(16, len(rows)), thread_name_prefix="fleet") as pool:
        list(pool.map(_poll_one, rows))


# ---------------------------------------------------------------------------
# The refresher
# ---------------------------------------------------------------------------
def watch(seconds: float = IDLE_STOP_S) -> None:
    """Called when the board is fetched: keep polling for a while longer."""
    global _watch_until
    _watch_until = time.monotonic() + max(10.0, seconds)
    _ensure_thread()


def watching() -> bool:
    return time.monotonic() < _watch_until


def _ensure_thread() -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, name="vision-fleet", daemon=True)
        _thread.start()


def _loop() -> None:
    from django.db import close_old_connections

    from apps.vision.models import Station

    while watching():
        try:
            refresh(Station.objects.filter(is_enabled=True))
        except Exception:  # noqa: BLE001
            log.warning("站台輪詢失敗", exc_info=True)
        finally:
            close_old_connections()
        time.sleep(INTERVAL_S)


# ---------------------------------------------------------------------------
# What the board shows
# ---------------------------------------------------------------------------
def board(rows) -> dict[str, Any]:
    """The whole board: one entry per station plus plant totals."""
    rows = list(rows)
    watch()
    # 沒問過、或資料已經過期的站台先同步問一次：第一次開看板不會是空白，而且萬一背景
    # 執行緒死了，看板也不會就這樣一直顯示愈來愈舊的數字。
    now = time.time()
    stale = [row for row in rows if now - float((_state.get(row.id) or {}).get("checked_at") or 0) > INTERVAL_S * 2]
    if stale:
        refresh(stale)
    items: list[dict[str, Any]] = []
    now = time.time()
    totals = {"total": 0, "ok": 0, "ng": 0, "failed": 0, "stations": 0, "online": 0}
    for row in rows:
        entry = _state.get(row.id) or {}
        summary = entry.get("summary") or {}
        station_totals = summary.get("totals") or {}
        online = bool(entry.get("online"))
        checked = float(entry.get("checked_at") or 0)
        items.append({
            "id": row.id,
            "name": row.name,
            "base_url": row.base_url,
            "note": row.note,
            "is_enabled": row.is_enabled,
            "online": online,
            "error": entry.get("error", "") if not online else "",
            # 離線時保留最後已知數字，但一定要說它多舊——舊數字看起來像即時的最危險
            "checked_at": checked or None,
            "age_s": round(now - checked, 1) if checked else None,
            "stale": bool(checked and not online),
            "station_id": summary.get("station_id", ""),
            "version": summary.get("version", ""),
            "locked": bool(summary.get("locked")),
            "totals": station_totals,
            "flows": summary.get("flows") or [],
        })
        totals["stations"] += 1
        if online:
            totals["online"] += 1
            for key in ("total", "ok", "ng", "failed"):
                totals[key] += int(station_totals.get(key) or 0)
    totals["yield"] = round(totals["ok"] / totals["total"] * 100, 1) if totals["total"] else None
    return {"items": items, "totals": totals, "interval_s": INTERVAL_S, "polling": watching()}


def summary_of_this_station(hours: int = 24) -> dict[str, Any]:
    """What this station reports to a board (and to its own overview)."""
    import datetime as dt

    from django.db.models import Max, Sum
    from django.utils import timezone

    from apps.accounts.models import EngineLock
    from apps.vision import __version__
    from apps.vision.models import Flow, FlowRunHourly
    from apps.vision.runner import runner

    since = (timezone.now() - dt.timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
    rolled = {
        row["flow_id"]: row
        for row in FlowRunHourly.objects.filter(hour__gte=since).values("flow_id").annotate(
            ok=Sum("ok"), ng=Sum("ng"), failed=Sum("failed"), total_ms=Sum("total_ms"), mx=Max("max_ms")
        )
    }
    flows: list[dict[str, Any]] = []
    totals = {"total": 0, "ok": 0, "ng": 0, "failed": 0}
    for flow in Flow.objects.filter(is_enabled=True).only("id", "name"):
        agg = rolled.get(flow.id) or {}
        ok, ng, failed = int(agg.get("ok") or 0), int(agg.get("ng") or 0), int(agg.get("failed") or 0)
        total = ok + ng + failed
        live = runner.runtime(flow.id).stats
        flows.append({
            "id": flow.id, "name": flow.name, "total": total, "ok": ok, "ng": ng, "failed": failed,
            "yield": round(ok / total * 100, 1) if total else None,
            "avg_ms": round((agg.get("total_ms") or 0) / total, 1) if total else 0.0,
            "max_ms": round(agg.get("mx") or 0, 1),
            "last_status": live.last_status, "last_finished_at": live.last_finished_at,
            "continuous": runner.is_continuous(flow.id),
        })
        for key, value in (("total", total), ("ok", ok), ("ng", ng), ("failed", failed)):
            totals[key] += value
    totals["yield"] = round(totals["ok"] / totals["total"] * 100, 1) if totals["total"] else None
    lock = EngineLock.current()
    return {
        "station_id": str(_cfg("STATION_ID", "ST01")),
        "version": __version__,
        "hours": hours,
        "locked": bool(lock.locked),
        "totals": totals,
        "flows": sorted(flows, key=lambda f: -f["total"]),
    }
