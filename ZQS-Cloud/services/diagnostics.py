"""連線偵錯：把「一個封包在平台裡發生了什麼」記成一列，讓設備商自己看得懂。

設備接不上來時，症狀永遠只有一個：「離線」。原因卻散在四個行程裡——broker
拒絕 CONNECT、ingestor 認不得 topic 或解不開 payload、worker 發現序號不對、
節點根本沒註冊。這個模組讓每一段在「偵錯開啟」時把自己的判斷寫進
``IngressTrace``，整合頁再把它們串成一條時間線與一句診斷。

設計上刻意保守：

* 只在有人開啟偵錯（``IngressDebug.enabled_until`` 在未來）時才寫，且開關
  有到期時間——忘了關也不會把資料庫填滿。
* 開關狀態在各行程快取 :data:`FLAG_TTL` 秒；關掉後最多晚幾秒停。
* 寫入永遠 best-effort：任何例外吞掉並記 log。偵錯功能自己壞掉不能影響遙測。
* 每個租戶最多留 :data:`KEEP_ROWS` 列，寫入時順手清舊的。
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from apps.core.logging import get_logger

logger = get_logger("diagnostics")

FLAG_TTL = 5.0
KEEP_ROWS = 4000
PREVIEW_BYTES = 96

# ---- stages / outcomes（字串常數，前端與文件同一份）----------------------------
STAGE_BROKER = "broker"      # 內建 broker 或 EMQX webhook 看到的連線層事件
STAGE_INGEST = "ingest"      # ingestor：topic、payload 解碼、節點是否註冊
STAGE_WORKER = "worker"      # worker：序號、出生、別名、設備
STAGE_HOST = "host"          # 平台主動的動作：要求重生、命令下發

OUTCOME_OK = "ok"
OUTCOME_REJECTED = "rejected"
OUTCOME_DROPPED = "dropped"
OUTCOME_WARNING = "warning"
OUTCOME_INFO = "info"

_lock = threading.Lock()
_flag_cache: dict[str, Any] = {"checked": 0.0, "active": False, "filters": {}}


def _refresh_flags() -> None:
    from django.utils.timezone import now

    from apps.devices.models import IngressDebug

    rows = IngressDebug.objects.filter(enabled_until__gt=now()).values_list(
        "organization_id", "node_filter", "capture_payload"
    )
    filters = {str(org): {"node": node or "", "payload": capture} for org, node, capture in rows}
    _flag_cache.update({"checked": time.monotonic(), "active": bool(filters), "filters": filters})


def enabled(organization_id=None, edge_node_id: str = "") -> bool:
    """這一筆要不要記。``organization_id`` 為 None（節點未註冊、broker 層）時，
    只要任一租戶開著偵錯就記——不知道是誰的封包正是需要看的時候。"""
    with _lock:
        if time.monotonic() - _flag_cache["checked"] > FLAG_TTL:
            try:
                _refresh_flags()
            except Exception:  # noqa: BLE001 - 表還沒建、DB 暫時不通都不能影響遙測
                _flag_cache["checked"] = time.monotonic()
                return False
        if not _flag_cache["active"]:
            return False
        filters = _flag_cache["filters"]
    if organization_id is None:
        return any(not f["node"] or f["node"] == edge_node_id for f in filters.values())
    entry = filters.get(str(organization_id))
    if entry is None:
        return False
    return not entry["node"] or entry["node"] == edge_node_id


def capture_payload(organization_id=None) -> bool:
    entry = _flag_cache["filters"].get(str(organization_id)) if organization_id else None
    if entry is None:
        return any(f["payload"] for f in _flag_cache["filters"].values())
    return bool(entry["payload"])


def invalidate() -> None:
    with _lock:
        _flag_cache["checked"] = 0.0


def hex_preview(raw: bytes | None) -> str:
    if not raw:
        return ""
    head = raw[:PREVIEW_BYTES]
    text = " ".join(f"{b:02x}" for b in head)
    return text + (" …" if len(raw) > PREVIEW_BYTES else "")


def trace(
    stage: str,
    outcome: str,
    *,
    organization_id=None,
    group_id: str = "",
    edge_node_id: str = "",
    device_id: str = "",
    topic: str = "",
    kind: str = "",
    reason: str = "",
    message: str = "",
    detail: dict[str, Any] | None = None,
    size: int | None = None,
    raw: bytes | None = None,
    ts: dt.datetime | None = None,
) -> None:
    """寫一列。呼叫端不必先問 :func:`enabled`——這裡會問，且永不拋例外。"""
    try:
        if not enabled(organization_id, edge_node_id):
            return
        from django.utils.timezone import now

        from apps.devices.models import IngressTrace

        payload = dict(detail or {})
        if raw is not None and capture_payload(organization_id):
            payload["hex"] = hex_preview(raw)
        IngressTrace.objects.create(
            organization_id=organization_id,
            ts=ts or now(),
            stage=stage,
            outcome=outcome,
            group_id=group_id[:80],
            edge_node_id=edge_node_id[:80],
            device_id=device_id[:80],
            topic=topic[:255],
            kind=kind[:16],
            reason=reason[:64],
            message=message[:500],
            detail=payload,
            size=size if size is not None else (len(raw) if raw else 0),
        )
        _maybe_purge(organization_id)
    except Exception:  # noqa: BLE001
        logger.debug("diagnostic trace dropped", exc_info=True)


#: 給 asyncio 行程（內建 broker）用：Django ORM 不能在 event loop 執行緒上跑，
#: 丟到一條背景執行緒寫。單一 worker 保證同一行程內的順序。
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="diag-trace")


def trace_bg(stage: str, outcome: str, **kwargs: Any) -> None:
    """:func:`trace` 的非同步安全版：從 event loop 內呼叫也不會踩到 SynchronousOnlyOperation。"""
    try:
        _executor.submit(trace, stage, outcome, **kwargs)
    except Exception:  # noqa: BLE001
        logger.debug("diagnostic trace not scheduled", exc_info=True)


_purge_counter = {"n": 0}


def _maybe_purge(organization_id) -> None:
    _purge_counter["n"] += 1
    if _purge_counter["n"] % 200:
        return
    from apps.devices.models import IngressTrace

    qs = IngressTrace.objects.filter(organization_id=organization_id).order_by("-ts")
    cutoff = qs.values_list("ts", flat=True)[KEEP_ROWS:KEEP_ROWS + 1]
    if cutoff:
        IngressTrace.objects.filter(organization_id=organization_id, ts__lt=cutoff[0]).delete()
