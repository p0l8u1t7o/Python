"""An edge-node-side Sparkplug client.

Used by the simulator, the test harness and the reference device, and written
to be readable as a specification of what a real edge node has to do - because
that is what a device vendor will read it as.

The state a node must keep is small but unforgiving:

* ``bdSeq`` increments once per *connection* and appears in both NBIRTH and
  NDEATH, so a death can be matched to the birth it ends;
* ``seq`` increments once per *message* and rolls over at 256, so the host can
  tell that something went missing;
* the alias table is assigned at birth and used alone afterwards, which is
  where most of the wire saving comes from.

Get any of the three wrong and the host will keep asking for rebirths, which is
the visible symptom of every Sparkplug implementation bug.
"""

from __future__ import annotations

import datetime as dt
import itertools
import threading
from typing import Any

from django.utils import timezone

from services.sparkplug import payload as sp
from services.sparkplug import topics
from services.sparkplug.datatypes import DataType, infer
from services.sparkplug.topics import MessageType


class MetricSpec:
    """One metric a device offers, as announced in its birth."""

    __slots__ = ("name", "datatype", "value", "properties", "is_transient")

    def __init__(
        self,
        name: str,
        value: Any = None,
        datatype: DataType | None = None,
        properties: dict[str, Any] | None = None,
        is_transient: bool = False,
    ) -> None:
        self.name = name
        self.value = value
        self.datatype = datatype or infer(value)
        self.properties = properties or {}
        self.is_transient = is_transient


class EdgeNodeClient:
    """Sequencing, aliasing and the birth/death dance for one connection.

    Serialised on purpose, and across the whole build-and-send - not just the
    counter. Allocating ``seq`` under a lock and then publishing outside it is
    not enough: two threads can take 7 and 8 and still reach the socket in the
    order 8, 7, and the host has no way to tell that apart from a lost message.
    A device that answers commands on its network thread while a run loop
    publishes telemetry hits this immediately.
    """

    def __init__(self, client, group_id: str, node_id: str) -> None:
        self.client = client
        self.group_id = group_id
        self.node_id = node_id
        #: Reentrant because the public methods below hold it while calling
        #: ``_next_seq``, which takes it again.
        self._lock = threading.RLock()
        self._seq = 0
        self._bd_seq = 0
        #: device_id -> {metric name: alias}. ``None`` keys the node itself.
        self._aliases: dict[str | None, dict[str, int]] = {}
        self._alias_counter = itertools.count(1)

    # ---- sequencing ------------------------------------------------------
    def _next_seq(self) -> int:
        with self._lock:
            value = self._seq
            self._seq = (self._seq + 1) % sp.SEQ_MODULUS
            return value

    def _reset_seq(self) -> None:
        with self._lock:
            self._seq = 0

    @property
    def bd_seq(self) -> int:
        return self._bd_seq

    def next_bd_seq(self) -> int:
        """Advance the birth/death counter. Call once per connection attempt."""
        self._bd_seq = (self._bd_seq + 1) % sp.SEQ_MODULUS
        return self._bd_seq

    # ---- publishing ------------------------------------------------------
    def _publish(self, message_type: MessageType, body: bytes, device_id: str = "") -> bool:
        topic = topics.build(self.group_id, message_type, self.node_id, device_id)
        qos, retain = topics.publish_options(message_type)
        return self.client.publish(topic, body, qos=qos, retain=retain)

    def _alias_for(self, device_id: str | None, name: str) -> int:
        table = self._aliases.setdefault(device_id, {})
        if name not in table:
            table[name] = next(self._alias_counter)
        return table[name]

    def death_payload(self) -> bytes:
        """The NDEATH body, which is registered as the MQTT will.

        Carries ``bdSeq`` and nothing else, and deliberately no ``seq``: the
        specification excludes it, because a will is published by the broker at
        an unknowable point in the sequence.
        """
        message = sp.new_payload(timestamp=timezone.now())
        sp.add_metric(message, sp.BDSEQ_METRIC, self._bd_seq, datatype=DataType.Int64)
        return sp.encode(message)

    def publish_nbirth(self, metrics: list[MetricSpec] | None = None) -> bool:
        """Announce the node. Resets ``seq`` to zero, as the spec requires."""
        with self._lock:
            self._reset_seq()
            self._aliases.pop(None, None)
            message = sp.new_payload(timestamp=timezone.now(), seq=self._next_seq())
            sp.add_metric(message, sp.BDSEQ_METRIC, self._bd_seq, datatype=DataType.Int64)
            # Without this the host has no sanctioned way to ask for a rebirth, and
            # a single lost message would leave the two sides permanently out of
            # step with no way back.
            sp.add_metric(message, sp.NODE_REBIRTH_METRIC, False, datatype=DataType.Boolean)
            for spec in metrics or []:
                sp.add_metric(
                    message,
                    spec.name,
                    spec.value,
                    datatype=spec.datatype,
                    alias=self._alias_for(None, spec.name),
                    properties=spec.properties,
                )
            return self._publish(MessageType.NBIRTH, sp.encode(message))

    def publish_dbirth(self, device_id: str, metrics: list[MetricSpec]) -> bool:
        """Announce a device and every metric it offers, with its aliases."""
        with self._lock:
            self._aliases.pop(device_id, None)
            message = sp.new_payload(timestamp=timezone.now(), seq=self._next_seq())
            sp.add_metric(
                message, sp.DEVICE_REBIRTH_METRIC, False, datatype=DataType.Boolean
            )
            for spec in metrics:
                sp.add_metric(
                    message,
                    spec.name,
                    spec.value,
                    datatype=spec.datatype,
                    alias=self._alias_for(device_id, spec.name),
                    properties=spec.properties,
                    is_transient=spec.is_transient,
                )
            return self._publish(MessageType.DBIRTH, sp.encode(message), device_id)

    def publish_ddata(
        self,
        device_id: str,
        values: dict[str, Any],
        *,
        timestamp: dt.datetime | None = None,
        properties: dict[str, dict[str, Any]] | None = None,
        datatypes: dict[str, DataType] | None = None,
    ) -> bool:
        """Report values by alias where one was announced, by name otherwise.

        A metric absent from the birth still travels by name. Dropping it would
        be worse than the extra bytes: the host would never see a reading the
        device chose to send.
        """
        moment = timestamp or timezone.now()
        with self._lock:
            message = sp.new_payload(timestamp=moment, seq=self._next_seq())
            table = self._aliases.get(device_id, {})
            for name, value in values.items():
                alias = table.get(name)
                sp.add_metric(
                    message,
                    "" if alias is not None else name,
                    value,
                    datatype=(datatypes or {}).get(name),
                    alias=alias,
                    timestamp=moment,
                    properties=(properties or {}).get(name),
                )
            return self._publish(MessageType.DDATA, sp.encode(message), device_id)

    def publish_ndata(self, values: dict[str, Any]) -> bool:
        moment = timezone.now()
        with self._lock:
            message = sp.new_payload(timestamp=moment, seq=self._next_seq())
            table = self._aliases.get(None, {})
            for name, value in values.items():
                alias = table.get(name)
                sp.add_metric(
                    message,
                    "" if alias is not None else name,
                    value,
                    alias=alias,
                    timestamp=moment,
                )
            return self._publish(MessageType.NDATA, sp.encode(message))

    def publish_ddeath(self, device_id: str) -> bool:
        with self._lock:
            message = sp.new_payload(timestamp=timezone.now(), seq=self._next_seq())
            return self._publish(MessageType.DDEATH, sp.encode(message), device_id)

    def publish_ndeath(self) -> bool:
        """Publish the death explicitly, for a planned shutdown.

        Necessary because a clean MQTT DISCONNECT makes the broker *discard* the
        will. Without this, a device that shuts down tidily looks online until
        the host's timeout sweep notices - which is the single most common way
        a Sparkplug deployment ends up with stale state.
        """
        with self._lock:
            return self._publish(MessageType.NDEATH, self.death_payload())

        # ---- commands --------------------------------------------------------
    def command_subscriptions(self, qos: int = 0) -> list[tuple[str, int]]:
        return [
            (topics.node_command(self.group_id, self.node_id), qos),
            (
                f"{topics.build(self.group_id, MessageType.DCMD, self.node_id)}/+",
                qos,
            ),
        ]

    def ack(
        self,
        device_id: str,
        command_id: str,
        status: str,
        *,
        message: str = "",
        result: dict[str, Any] | None = None,
    ) -> bool:
        """Answer a DCMD.

        Sparkplug has no acknowledgement message, so the answer is ordinary
        DDATA carrying the correlation metrics this platform's profile defines.
        """
        from services.sparkplug import profile

        moment = timezone.now()
        with self._lock:
            payload = sp.new_payload(timestamp=moment, seq=self._next_seq())
            sp.add_metric(payload, profile.COMMAND_ID, command_id, timestamp=moment)
            sp.add_metric(payload, profile.COMMAND_STATUS, status, timestamp=moment)
            if message:
                sp.add_metric(
                    payload, profile.COMMAND_MESSAGE, message, timestamp=moment
                )
            for key, value in (result or {}).items():
                sp.add_metric(
                    payload,
                    f"{profile.COMMAND_RESULT_PREFIX}{key}",
                    value,
                    timestamp=moment,
                )
            return self._publish(MessageType.DDATA, sp.encode(payload), device_id)
