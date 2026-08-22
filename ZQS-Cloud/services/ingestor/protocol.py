"""Sparkplug payload validation at the edge of the system.

Validation runs in the ingestor - before anything reaches the queue - so
malformed traffic is rejected at the edge and never costs a database round
trip. What is *not* done here is anything needing the database: alias
resolution, metric classification and device state all belong to the worker,
because the ingestor deliberately holds no connection.

See ``docs/device-protocol.md`` for the human-readable specification.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.conf import settings

from apps.core.timeutils import TimestampError, check_clock_skew
from services.sparkplug import payload as sp
from services.sparkplug import topics

#: Re-exported so callers catch one exception type for the whole decode path.
ProtocolError = sp.PayloadError


def _check_skew(moment: dt.datetime, received_at: dt.datetime) -> dt.datetime:
    check_clock_skew(
        moment,
        max_future_s=settings.INGEST["MAX_CLOCK_SKEW_FUTURE_S"],
        max_past_s=settings.INGEST["MAX_CLOCK_SKEW_PAST_S"],
        reference=received_at,
    )
    return moment


def decode_uplink(
    parsed: topics.ParsedTopic, raw: bytes, received_at: dt.datetime
) -> dict[str, Any]:
    """Decode one uplink into the envelope body the worker consumes.

    Timestamps are handled at two levels, and the asymmetry is deliberate:

    * a bad **payload** timestamp rejects the whole message, because it means
      the publisher's clock is wrong and nothing in the payload can be trusted
      to sit anywhere sensible in the series;
    * a bad **metric** timestamp drops that one metric and is counted, because
      a single stamp out of range next to a sane payload stamp is a per-metric
      bug, not a broken clock.

    Neither case silently substitutes the arrival time. Doing that would put a
    reading at a moment it was not taken, and every integral computed over that
    window would then be wrong in a way nothing downstream can detect.
    """
    view = sp.decode(raw)

    payload_ts = view.timestamp or received_at
    try:
        _check_skew(payload_ts, received_at)
    except TimestampError as exc:
        raise ProtocolError(str(exc), reason="bad_timestamp") from exc

    metrics: list[dict[str, Any]] = []
    dropped = 0
    for metric in view.metrics:
        moment = metric.timestamp or payload_ts
        try:
            _check_skew(moment, received_at)
        except TimestampError:
            dropped += 1
            continue

        metrics.append(
            {
                "name": metric.name,
                "alias": metric.alias,
                "datatype": int(metric.datatype),
                "value": metric.value,
                "ts": moment.isoformat(),
                "is_null": metric.is_null,
                "is_transient": metric.is_transient,
                "is_historical": metric.is_historical,
                "properties": metric.properties,
            }
        )

    body: dict[str, Any] = {
        "timestamp": payload_ts.isoformat(),
        "seq": view.seq,
        "metrics": metrics,
    }
    if dropped:
        body["dropped_metrics"] = dropped
    if parsed.message_type in (topics.MessageType.NBIRTH, topics.MessageType.NDEATH):
        body["bd_seq"] = sp.bd_seq_of(view)
    return body
