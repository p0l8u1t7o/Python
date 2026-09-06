"""量測值 SPC 的 API（WP-14）。

    GET /vision/flows/{id}/spc?output=<name>&hours=24&limit=500&chart=imr|xbar_r&subgroup=5
        時間序列（MeasurementLog）＋管制界限／Cp、Cpk／Nelson 判異＋規格界限（從流程圖的 tolerance_judge 帶入）；
        不給 output 就回可選的輸出名稱清單與第一個的分析。
    GET /vision/spc/alerts
        總覽用：每條看得見的流程 × 每個量測輸出，最近 50 點「現在」觸發的 Nelson 法則與規格外點數；行程內快取 30 秒。
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router

from apps.core.errors import ValidationError
from apps.vision import spc
from apps.vision.api import _visible_flows
from apps.vision.models import MeasurementLog
from apps.vision.runner import get_flow

router = Router(tags=["spc"])
MAX_LIMIT = 5000
ALERT_TTL_S = 30.0
_alert_cache: dict[str, Any] = {"at": 0.0, "key": None, "items": []}
_alert_lock = threading.Lock()


def _names(flow_id: int) -> list[str]:
    return list(MeasurementLog.objects.filter(flow_id=flow_id).order_by("name").values_list("name", flat=True).distinct())


@router.get("/flows/{flow_id}/spc")
def flow_spc(request: HttpRequest, flow_id: int, output: str = "", hours: int = 24, limit: int = 500, chart: str = "imr", subgroup: int = 5):
    flow = get_flow(flow_id)
    if chart not in ("imr", "xbar_r"):
        raise ValidationError("chart must be imr or xbar_r", code="bad_chart")
    hours = max(1, min(int(hours), 24 * 400))
    limit = max(2, min(int(limit), MAX_LIMIT))
    subgroup = max(2, min(10, int(subgroup)))
    names = _names(flow_id)
    if not output:
        output = names[0] if names else ""
    enabled = bool(settings.VISION.get("MEASUREMENT_LOG", True))
    out: dict[str, Any] = {"flow_id": flow_id, "output": output, "outputs": names, "hours": hours, "chart": chart, "subgroup": subgroup, "enabled": enabled,
                           "retention_days": int(settings.VISION.get("MEASUREMENT_DAYS", 365))}
    if not output:
        out.update({"series": [], "analysis": spc.analyse([], chart, subgroup), "spec": {}})
        return out
    since = timezone.now() - dt.timedelta(hours=hours)
    rows = list(MeasurementLog.objects.filter(flow_id=flow_id, name=output, ts__gte=since).order_by("-ts").values_list("ts", "value", "run_id")[:limit])
    rows.reverse()
    values = [float(v) for _, v, _ in rows]
    spec = spc.spec_limits_from_graph(flow.graph, output)
    analysis = spc.analyse(values, chart, subgroup, spec.get("usl"), spec.get("lsl"))
    out.update({
        "series": [{"ts": ts.isoformat(), "value": float(v), "run_id": str(rid)} for ts, v, rid in rows],
        "analysis": analysis, "spec": spec, "alerts": spc.alerts_for(values, spec.get("usl"), spec.get("lsl")),
    })
    return out


@router.get("/spc/alerts")
def spc_alerts(request: HttpRequest):
    flows = list(_visible_flows(request).values_list("id", "name", "graph"))
    key = tuple(f[0] for f in flows)
    now = time.monotonic()
    with _alert_lock:
        if _alert_cache["key"] == key and now - _alert_cache["at"] < ALERT_TTL_S:
            return {"items": _alert_cache["items"], "cached": True}
    items: list[dict[str, Any]] = []
    for flow_id, name, graph in flows:
        for out_name in _names(flow_id):
            rows = list(MeasurementLog.objects.filter(flow_id=flow_id, name=out_name).order_by("-ts").values_list("ts", "value")[:50])
            if len(rows) < 2:
                continue
            rows.reverse()
            spec = spc.spec_limits_from_graph(graph, out_name)
            alerts = spc.alerts_for([float(v) for _, v in rows], spec.get("usl"), spec.get("lsl"))
            if alerts:
                items.append({"flow_id": flow_id, "flow_name": name, "output": out_name, "alerts": alerts, "last_ts": rows[-1][0].isoformat(), "points": len(rows)})
    with _alert_lock:
        _alert_cache.update({"at": now, "key": key, "items": items})
    return {"items": items, "cached": False}


def invalidate_alerts() -> None:
    with _alert_lock:
        _alert_cache["at"] = 0.0
