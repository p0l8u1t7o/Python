"""Canonical stream names.

Kept in one place so the ingestor, the worker and the ops tooling cannot drift
apart on naming.

One ingest stream, not one per message kind. Two things rule out the split,
and both come from Sparkplug itself:

* **A message is no longer one kind of thing.** A single DDATA legitimately
  carries a reading, an alarm and a command acknowledgement together, and the
  metrics inside may be aliases with no names at all until the birth table is
  consulted. The ingestor cannot split what it cannot read.
* **Order is load-bearing.** The ``seq`` counter is how a host learns it missed
  something, and a birth has to be processed before the data that depends on
  the aliases it defines. Separate streams consumed independently give up both
  guarantees, and prioritising state over data would actively reorder them.

The cost is that a burst of telemetry can delay a status change behind it.
That is the right trade: a late status change is a display lag, whereas a
reading filed under the wrong metric is corrupt history.
"""

from __future__ import annotations

from django.conf import settings

#: Every uplink: NBIRTH, NDEATH, DBIRTH, DDEATH, NDATA, DDATA.
INGEST = "sparkplug"
DEAD_LETTER = "dead_letter"

ALL_INGEST_STREAMS = (INGEST,)


def qualified(name: str) -> str:
    """Prefix a logical name so several environments can share one broker."""
    prefix = settings.BUS["STREAM_PREFIX"].rstrip(".:")
    return f"{prefix}.{name}" if prefix else name


def all_qualified() -> tuple[str, ...]:
    return tuple(qualified(name) for name in ALL_INGEST_STREAMS)


def logical(qualified_name: str) -> str:
    """Inverse of :func:`qualified`."""
    prefix = settings.BUS["STREAM_PREFIX"].rstrip(".:")
    if prefix and qualified_name.startswith(f"{prefix}."):
        return qualified_name[len(prefix) + 1 :]
    return qualified_name
