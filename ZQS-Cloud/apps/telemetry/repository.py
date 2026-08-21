"""Time-series persistence and query layer.

All SQL touching the sample tables lives here, so moving from SQLite to
PostgreSQL/TimescaleDB is a change in this module rather than across the API and
worker code. The statements use ``%s`` placeholders, which Django's SQLite
backend rewrites to ``?`` - so the same string works on both engines.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from django.db import connection, transaction

from apps.core.logging import get_logger
from apps.telemetry.models import Quality, Rollup, TelemetrySample

logger = get_logger("telemetry.repository")


def adapt_uuid(value: uuid.UUID | str) -> Any:
    """Match how ``UUIDField`` stores values on the active backend.

    PostgreSQL has a native uuid type; SQLite stores the 32-character hex form
    with no dashes. Raw SQL parameters must use the same representation or the
    comparison silently matches nothing.
    """
    if connection.features.has_native_uuid_field:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    return uuid.UUID(str(value)).hex


def adapt_datetime(value: dt.datetime) -> Any:
    """Match how ``DateTimeField`` stores values on the active backend."""
    return connection.ops.adapt_datetimefield_value(value)


@dataclass(slots=True)
class SampleRow:
    organization_id: uuid.UUID
    device_id: uuid.UUID
    metric_key: str
    ts: dt.datetime
    value: float | None = None
    value_text: str | None = None
    quality: int = Quality.GOOD


def insert_samples(rows: Sequence[SampleRow]) -> int:
    """Batch insert, ignoring rows that duplicate an existing (device, metric, ts).

    At-least-once delivery means the same sample can arrive twice; the unique
    constraint plus ``ignore_conflicts`` makes ingestion idempotent.
    """
    if not rows:
        return 0
    objects = [
        TelemetrySample(
            organization_id=row.organization_id,
            device_id=row.device_id,
            metric_key=row.metric_key,
            ts=row.ts,
            value=row.value,
            value_text=row.value_text,
            quality=row.quality,
        )
        for row in rows
    ]
    created = TelemetrySample.objects.bulk_create(
        objects, batch_size=1000, ignore_conflicts=True
    )
    return len(created)


#: Upsert that refuses to move the current value backwards in time. Django's
#: bulk_create(update_conflicts=True) cannot express the WHERE clause, and
#: without it an out-of-order redelivery would overwrite a newer reading.
_UPSERT_LATEST = """
INSERT INTO telemetry_latest_sample
    (organization_id, device_id, metric_key, ts, value, value_text, quality, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (device_id, metric_key) DO UPDATE SET
    ts = excluded.ts,
    value = excluded.value,
    value_text = excluded.value_text,
    quality = excluded.quality,
    updated_at = excluded.updated_at,
    organization_id = excluded.organization_id
WHERE excluded.ts > telemetry_latest_sample.ts
"""


def upsert_latest(rows: Sequence[SampleRow], *, updated_at: dt.datetime | None = None) -> int:
    """Refresh the "current value" table used by the dashboard."""
    if not rows:
        return 0
    from apps.core.timeutils import now

    stamp = updated_at or now()

    # Collapse to the newest sample per (device, metric) so one batch issues one
    # row per series instead of fighting itself inside the same statement.
    newest: dict[tuple[uuid.UUID, str], SampleRow] = {}
    for row in rows:
        key = (row.device_id, row.metric_key)
        current = newest.get(key)
        if current is None or row.ts > current.ts:
            newest[key] = row

    adapted_stamp = adapt_datetime(stamp)
    params = [
        (
            adapt_uuid(row.organization_id),
            adapt_uuid(row.device_id),
            row.metric_key,
            adapt_datetime(row.ts),
            row.value,
            row.value_text,
            row.quality,
            adapted_stamp,
        )
        for row in newest.values()
    ]
    with connection.cursor() as cursor:
        cursor.executemany(_UPSERT_LATEST, params)
    return len(params)


def prune_samples(
    *, device_id: uuid.UUID, metric_key: str, older_than: dt.datetime, chunk: int = 5000
) -> int:
    """Delete aged rows in bounded chunks so retention never locks the table."""
    deleted_total = 0
    while True:
        pks = list(
            TelemetrySample.objects.filter(
                device_id=device_id, metric_key=metric_key, ts__lt=older_than
            ).values_list("pk", flat=True)[:chunk]
        )
        if not pks:
            break
        with transaction.atomic():
            deleted, _ = TelemetrySample.objects.filter(pk__in=pks).delete()
        deleted_total += deleted
        if len(pks) < chunk:
            break
    return deleted_total


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------
def fetch_series(
    *,
    device_ids: Sequence[uuid.UUID],
    metric_keys: Sequence[str],
    start: dt.datetime,
    end: dt.datetime,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    """Raw samples for a set of series, oldest first."""
    if not device_ids or not metric_keys:
        return []
    queryset = (
        TelemetrySample.objects.filter(
            device_id__in=list(device_ids),
            metric_key__in=list(metric_keys),
            ts__gte=start,
            ts__lt=end,
        )
        .order_by("device_id", "metric_key", "ts")
        .values("device_id", "metric_key", "ts", "value", "value_text", "quality")
    )
    return list(queryset[:limit])


#: Bucketed aggregation. The bucket expression is engine-specific, so it is
#: injected rather than hard-coded (see :func:`_bucket_expression`).
_AGGREGATE_SQL = """
SELECT
    device_id,
    metric_key,
    {bucket} AS bucket_epoch,
    COUNT(value)  AS sample_count,
    AVG(value)    AS avg_value,
    MIN(value)    AS min_value,
    MAX(value)    AS max_value,
    SUM(value)    AS sum_value
FROM telemetry_sample
WHERE device_id IN ({device_placeholders})
  AND metric_key IN ({metric_placeholders})
  AND ts >= %s AND ts < %s
GROUP BY device_id, metric_key, bucket_epoch
ORDER BY device_id, metric_key, bucket_epoch
LIMIT %s
"""


#: Same aggregation, plus each bucket's first and last value.
#:
#: Kept apart from :data:`_AGGREGATE_SQL` on purpose. Counter metrics need the
#: edges to compute a delta, but charts do not, and window functions are not
#: free - the request path that runs on every chart redraw keeps the cheap
#: query. Window functions are available on SQLite 3.25+ and PostgreSQL alike.
_AGGREGATE_EDGES_SQL = """
SELECT
    device_id,
    metric_key,
    bucket_epoch,
    COUNT(value)     AS sample_count,
    AVG(value)       AS avg_value,
    MIN(value)       AS min_value,
    MAX(value)       AS max_value,
    SUM(value)       AS sum_value,
    MIN(edge_first)  AS first_value,
    MIN(edge_last)   AS last_value
FROM (
    SELECT
        device_id,
        metric_key,
        {bucket} AS bucket_epoch,
        value,
        FIRST_VALUE(value) OVER w AS edge_first,
        LAST_VALUE(value) OVER w  AS edge_last
    FROM telemetry_sample
    WHERE device_id IN ({device_placeholders})
      AND metric_key IN ({metric_placeholders})
      AND ts >= %s AND ts < %s
    WINDOW w AS (
        PARTITION BY device_id, metric_key, {bucket}
        ORDER BY ts
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    )
) windowed
GROUP BY device_id, metric_key, bucket_epoch
ORDER BY device_id, metric_key, bucket_epoch
LIMIT %s
"""


def _bucket_expression(interval_seconds: int) -> str:
    """Floor ``ts`` to an interval, as epoch seconds."""
    vendor = connection.vendor
    if vendor == "sqlite":
        # Django stores datetimes as ISO text in SQLite.
        return f"(CAST(strftime('%%s', ts) AS INTEGER) / {interval_seconds}) * {interval_seconds}"
    if vendor == "postgresql":
        return (
            f"(FLOOR(EXTRACT(EPOCH FROM ts) / {interval_seconds}) * {interval_seconds})::bigint"
        )
    raise NotImplementedError(f"Bucketing is not implemented for '{vendor}'")


def aggregate_series(
    *,
    device_ids: Sequence[uuid.UUID],
    metric_keys: Sequence[str],
    start: dt.datetime,
    end: dt.datetime,
    interval_seconds: int,
    limit: int = 50_000,
    with_edges: bool = False,
) -> list[dict[str, Any]]:
    """Downsample on read - used whenever a chart spans more than a few hours.

    ``with_edges`` additionally reports each bucket's first and last value,
    which is what a cumulative counter needs to yield a delta.
    """
    if not device_ids or not metric_keys:
        return []

    template = _AGGREGATE_EDGES_SQL if with_edges else _AGGREGATE_SQL
    sql = template.format(
        bucket=_bucket_expression(interval_seconds),
        device_placeholders=", ".join(["%s"] * len(device_ids)),
        metric_placeholders=", ".join(["%s"] * len(metric_keys)),
    )
    params: list[Any] = [adapt_uuid(d) for d in device_ids]
    params += list(metric_keys)
    params += [adapt_datetime(start), adapt_datetime(end), limit]

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        rows = [dict(zip(columns, record)) for record in cursor.fetchall()]

    for row in rows:
        row["bucket_start"] = dt.datetime.fromtimestamp(
            int(row.pop("bucket_epoch")), tz=dt.timezone.utc
        )
        # SQLite hands back the stored hex form; normalise so callers always
        # receive real UUIDs regardless of backend.
        if not isinstance(row["device_id"], uuid.UUID):
            row["device_id"] = uuid.UUID(str(row["device_id"]))
    return rows


def build_rollups(
    *,
    organization_id: uuid.UUID,
    device_ids: Sequence[uuid.UUID],
    metric_keys: Sequence[str],
    start: dt.datetime,
    end: dt.datetime,
    interval_seconds: int,
) -> int:
    """Materialise aggregates so long-range charts skip the sample table."""
    aggregates = aggregate_series(
        device_ids=device_ids,
        metric_keys=metric_keys,
        start=start,
        end=end,
        interval_seconds=interval_seconds,
        limit=200_000,
        with_edges=True,
    )
    if not aggregates:
        return 0

    objects = [
        Rollup(
            organization_id=organization_id,
            device_id=row["device_id"],
            metric_key=row["metric_key"],
            interval_seconds=interval_seconds,
            bucket_start=row["bucket_start"],
            count=row["sample_count"] or 0,
            avg_value=row["avg_value"],
            min_value=row["min_value"],
            max_value=row["max_value"],
            sum_value=row["sum_value"],
            # Present on the model since the beginning but never populated;
            # counter deltas are unusable without them.
            first_value=row.get("first_value"),
            last_value=row.get("last_value"),
        )
        for row in aggregates
    ]
    Rollup.objects.bulk_create(
        objects,
        batch_size=1000,
        update_conflicts=True,
        unique_fields=["device", "metric_key", "interval_seconds", "bucket_start"],
        update_fields=[
            "count",
            "avg_value",
            "min_value",
            "max_value",
            "sum_value",
            "first_value",
            "last_value",
        ],
    )
    return len(objects)


def latest_values(
    *, organization_id: uuid.UUID, device_ids: Iterable[uuid.UUID] | None = None
) -> list[dict[str, Any]]:
    from apps.telemetry.models import LatestSample

    queryset = LatestSample.objects.filter(organization_id=organization_id)
    if device_ids is not None:
        queryset = queryset.filter(device_id__in=list(device_ids))
    return list(
        queryset.values("device_id", "metric_key", "ts", "value", "value_text", "quality")
    )
