"""市電停電偵測（W6）：關口電壓低於門檻**且**持續 N 秒。

不用「柴發有輸出」當近似——柴發測試運轉也會有輸出，會把正常的月份記成
停電、節省記成 null。判準沿用告警引擎 ``for_duration`` 的語意：第一次低於
門檻的時間點記下來，持續超過 ``outage_for_seconds`` 才成立；中途回到門檻
之上就重新計時。

偵測到之後（:func:`observe` 回傳的 transition 告訴呼叫端）：

* 開一列 ``SiteOutage``（下游：彙總器把節省記 null、調度走備援模式）
* 關口電表上發 ``DeviceEvent``（code ``grid_outage``）與設備告警
* 復電時關閉那一列、清告警、再發一個 info 事件

邊緣自己的切換（孤島、watchdog）不經過這裡——那是設備的事，雲端只負責
看見並記錄。
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from django.utils.timezone import now

from apps.ems.models import AssetRole, EnergyAsset, SiteOutage
from apps.ems.plans import effective_plan

OUTAGE_CODE = "grid_outage"


@dataclass(slots=True)
class OutageRule:
    site_id: uuid.UUID
    organization_id: uuid.UUID
    device_pk: uuid.UUID
    voltage_metric: str
    threshold_v: float
    for_seconds: int


@dataclass(slots=True)
class Transition:
    """一次觀測的結果。``started`` / ``ended`` 只在狀態改變那一刻為 True。"""

    started: bool = False
    ended: bool = False
    outage: SiteOutage | None = None


class OutageDetector:
    """單一行程內的停電狀態機；規則從資產＋方案讀，30 秒快取一次。"""

    def __init__(self, ttl_seconds: int = 30) -> None:
        self._rules: dict[uuid.UUID, OutageRule | None] = {}
        self._loaded_at: dict[uuid.UUID, float] = {}
        self._below_since: dict[uuid.UUID, dt.datetime] = {}
        self._ttl = ttl_seconds

    # ---- rules -----------------------------------------------------------
    def rule_for(self, device_pk: uuid.UUID) -> OutageRule | None:
        import time

        stamp = self._loaded_at.get(device_pk)
        if stamp is not None and time.monotonic() - stamp < self._ttl:
            return self._rules.get(device_pk)
        rule = load_rule(device_pk)
        self._rules[device_pk] = rule
        self._loaded_at[device_pk] = time.monotonic()
        return rule

    def invalidate(self) -> None:
        self._rules.clear()
        self._loaded_at.clear()

    # ---- observation -----------------------------------------------------
    def observe(self, device_pk: uuid.UUID, metric_key: str, value: float | None, ts: dt.datetime) -> Transition:
        rule = self.rule_for(device_pk)
        if rule is None or metric_key != rule.voltage_metric or value is None:
            return Transition()

        active = SiteOutage.objects.filter(site_id=rule.site_id, ended_at__isnull=True).order_by("-started_at").first()
        if value < rule.threshold_v:
            since = self._below_since.setdefault(device_pk, ts)
            if active is not None:
                return Transition(outage=active)
            if (ts - since).total_seconds() < rule.for_seconds:
                return Transition()
            outage = SiteOutage.objects.create(
                organization_id=rule.organization_id, site_id=rule.site_id, device_id=device_pk,
                started_at=since, voltage_v=value, threshold_v=rule.threshold_v,
            )
            return Transition(started=True, outage=outage)

        # 電壓回到門檻之上：重新計時；有進行中的停電就結束它。
        self._below_since.pop(device_pk, None)
        if active is not None:
            active.ended_at = ts
            active.save(update_fields=["ended_at"])
            return Transition(ended=True, outage=active)
        return Transition()


def load_rule(device_pk: uuid.UUID) -> OutageRule | None:
    asset = (
        EnergyAsset.objects.filter(device_id=device_pk, role=AssetRole.GRID_METER, is_active=True)
        .exclude(voltage_metric="")
        .select_related("site")
        .first()
    )
    if asset is None:
        return None
    plan, _source = effective_plan(asset.site)
    if plan is None or plan.outage_voltage_min_v is None:
        return None
    return OutageRule(
        site_id=asset.site_id, organization_id=asset.organization_id, device_pk=device_pk,
        voltage_metric=asset.voltage_metric, threshold_v=float(plan.outage_voltage_min_v),
        for_seconds=int(plan.outage_for_seconds or 0),
    )


def active_outage(site_id, moment: dt.datetime | None = None) -> SiteOutage | None:
    """此刻進行中的停電，給調度引擎用。"""
    moment = moment or now()
    return (
        SiteOutage.objects.filter(site_id=site_id, started_at__lte=moment, ended_at__isnull=True)
        .order_by("-started_at")
        .first()
    )


def overlaps_outage(site_id, start: dt.datetime, end: dt.datetime) -> bool:
    """區間 ``[start, end)`` 有沒有和任何停電重疊——彙總器用來把節省記 null。"""
    return SiteOutage.objects.filter(site_id=site_id, started_at__lt=end).filter(
        models_q_ended_after(start)
    ).exists()


def models_q_ended_after(start: dt.datetime):
    from django.db.models import Q

    return Q(ended_at__isnull=True) | Q(ended_at__gt=start)
