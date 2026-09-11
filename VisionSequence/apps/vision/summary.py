"""這一站的良率摘要：`GET /vision/summary` 與總覽頁共用的同一份數字。

數字來自 `FlowRunHourly`（每小時彙總、永久保留），所以明細被淘汰或伺服器重開都不會讓
良率曲線消失；「現在在跑什麼」則來自記憶體中的 `runner`。

這是給外部系統輪詢的端點——多站台的彙總看板由外部整合負責，平台本身不去輪詢別台。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.conf import settings
from django.db.models import Max, Sum
from django.utils import timezone


def of_this_station(hours: int = 24) -> dict[str, Any]:
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
    for flow in Flow.objects.filter(is_enabled=True, kind="flow").only("id", "name"):
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
        "station_id": str(getattr(settings, "VISION", {}).get("STATION_ID", "ST01")),
        "version": __version__,
        "hours": hours,
        "locked": bool(lock.locked),
        "totals": totals,
        "flows": sorted(flows, key=lambda f: -f["total"]),
    }
