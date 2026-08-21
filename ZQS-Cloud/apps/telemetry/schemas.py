from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ninja import Field, Schema

from apps.telemetry.models import Aggregation, MetricKind, ValueType


# --------------------------------------------------------------------------
# Metric catalogue
# --------------------------------------------------------------------------
class MetricOut(Schema):
    id: uuid.UUID | None = None
    key: str
    display_name: str
    label: str = ""
    translations: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    unit: str = ""
    value_type: ValueType = ValueType.FLOAT
    kind: MetricKind = MetricKind.GAUGE
    aggregation: Aggregation = Aggregation.AVG
    decimals: int = 2
    min_value: float | None = None
    max_value: float | None = None
    state_map: dict[str, Any] = Field(default_factory=dict)
    category: str = ""
    is_builtin: bool = False


class MetricIn(Schema):
    key: str = Field(max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    display_name: str = Field(max_length=120)
    translations: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    unit: str = Field(default="", max_length=24)
    value_type: ValueType = ValueType.FLOAT
    kind: MetricKind = MetricKind.GAUGE
    aggregation: Aggregation = Aggregation.AVG
    decimals: int = Field(default=2, ge=0, le=9)
    min_value: float | None = None
    max_value: float | None = None
    state_map: dict[str, Any] = Field(default_factory=dict)
    category: str = Field(default="", max_length=40)


# --------------------------------------------------------------------------
# Recording policy
# --------------------------------------------------------------------------
class RecordingRuleIn(Schema):
    metric_key: str = Field(max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    enabled: bool = True
    min_interval_seconds: int = Field(default=0, ge=0, le=86400)
    max_interval_seconds: int = Field(default=3600, ge=0, le=604800)
    deadband_absolute: float | None = Field(default=None, ge=0)
    deadband_percent: float | None = Field(default=None, ge=0, le=100)
    retention_days: int | None = Field(default=None, ge=0, le=36500)
    keep_rollups: bool = True


class RecordingRuleOut(RecordingRuleIn):
    id: int


class RecordingPolicyIn(Schema):
    name: str = Field(max_length=120)
    description: str = ""
    is_default: bool = False
    device_type_id: uuid.UUID | None = None
    record_unlisted_metrics: bool = True
    default_retention_days: int = Field(default=365, ge=0, le=36500)
    default_min_interval_seconds: int = Field(default=0, ge=0, le=86400)
    default_max_interval_seconds: int = Field(default=3600, ge=0, le=604800)
    rules: list[RecordingRuleIn] = Field(default_factory=list)


class RecordingPolicyOut(Schema):
    id: uuid.UUID
    name: str
    description: str
    is_default: bool
    device_type_id: uuid.UUID | None = None
    record_unlisted_metrics: bool
    default_retention_days: int
    default_min_interval_seconds: int
    default_max_interval_seconds: int
    rules: list[RecordingRuleOut] = Field(default_factory=list)
    device_count: int = 0
    created_at: dt.datetime


# --------------------------------------------------------------------------
# Series queries
# --------------------------------------------------------------------------
class SeriesQuery(Schema):
    #: Explicit devices. May be empty when ``site_ids`` is given instead.
    device_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    #: Pick devices by site instead of listing them. The server expands these
    #: to device ids, so the console does not have to fetch the device list
    #: first just to chart a group. Merged with ``device_ids`` when both are
    #: present, and still capped at 50 devices in total.
    site_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    #: Whether ``site_ids`` also pulls in devices of nested sites.
    include_descendants: bool = True
    #: Stitch each device together with the ones that replaced it, so a piece
    #: of equipment reads as one series across a hardware swap. Off by default:
    #: stitching is an interpretation (that the successor is equivalent), and
    #: the raw answer is one series per registered device. Each device
    #: contributes only its own window, so the two never overlap.
    follow_replacements: bool = False
    metrics: list[str] = Field(min_length=1, max_length=50)
    start: dt.datetime | None = None
    end: dt.datetime | None = None
    #: 0 (default) auto-selects a bucket that keeps the response under
    #: ``max_points``; any other value forces that bucket width in seconds.
    interval_seconds: int = Field(default=0, ge=0, le=86400)
    max_points: int = Field(default=1500, ge=10, le=20000)


class SeriesPoint(Schema):
    ts: dt.datetime
    value: float | None = None
    #: Present only on aggregated responses.
    min: float | None = None
    max: float | None = None
    count: int | None = None


class SeriesOut(Schema):
    device_id: uuid.UUID
    device_external_id: str = ""
    #: Every device folded into this series, oldest first. One entry unless
    #: ``follow_replacements`` stitched a replacement chain together.
    device_ids: list[uuid.UUID] = Field(default_factory=list)
    metric_key: str
    label: str = ""
    unit: str = ""
    aggregation: str = "raw"
    interval_seconds: int = 0
    points: list[SeriesPoint] = Field(default_factory=list)


class SeriesResponse(Schema):
    start: dt.datetime
    end: dt.datetime
    interval_seconds: int
    #: True when the response was downsampled rather than raw samples.
    downsampled: bool
    series: list[SeriesOut]


class LatestOut(Schema):
    device_id: uuid.UUID
    device_external_id: str = ""
    metric_key: str
    label: str = ""
    unit: str = ""
    value: float | None = None
    value_text: str | None = None
    ts: dt.datetime
    quality: int = 0
