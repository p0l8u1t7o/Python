"""Restricted sequence API used by project animation/sequence.py files."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any

from cellforge.schema.models import Process

_active: contextvars.ContextVar[SequenceBuilder] = contextvars.ContextVar("cellforge_sequence")


@dataclass
class SequenceBuilder:
    process: Process
    fps: int = 50
    time_s: float = 0.0
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    station_ranges: dict[str, list[float]] = field(default_factory=dict)
    _joints: dict[str, list[float]] = field(default_factory=dict)

    def _span(self, station: str | None, duration_s: float) -> tuple[float, float]:
        t0 = self.time_s
        self.time_s += max(0.0, float(duration_s))
        if station:
            bounds = self.station_ranges.setdefault(station, [t0, self.time_s])
            bounds[0] = min(bounds[0], t0)
            bounds[1] = max(bounds[1], self.time_s)
        return t0, self.time_s

    def move_joint(
        self,
        actor: str,
        joints_deg: list[float],
        duration_s: float = 1.0,
        station: str | None = None,
    ) -> None:
        if len(joints_deg) != 6:
            raise ValueError("步驟 0 的 move_joint 需要六個關節角")
        start = self._joints.get(actor, [0.0] * 6)
        t0, t1 = self._span(station, duration_s)
        node = self.nodes.setdefault(actor, {"type": "robot", "joints_deg": []})
        if not node["joints_deg"]:
            node["joints_deg"].append([t0, *start])
        node["joints_deg"].append([t1, *[float(value) for value in joints_deg]])
        self._joints[actor] = list(joints_deg)

    def move_to(
        self,
        actor: str,
        target: dict[str, Any],
        duration_s: float = 1.0,
        station: str | None = None,
    ) -> None:
        t0, t1 = self._span(station, duration_s)
        node = self.nodes.setdefault(actor, {"type": "pose", "pose": []})
        pose = target.get("xyz", [0, 0, 0]) + target.get("rpy_deg", [0, 0, 0])
        if not node["pose"]:
            node["pose"].append([t0, *pose])
        node["pose"].append([t1, *pose])

    def actuate(
        self,
        actor: str,
        value: float,
        duration_s: float = 1.0,
        station: str | None = None,
        unit: str = "value",
    ) -> None:
        t0, t1 = self._span(station, duration_s)
        key = {"mm": "value_mm", "deg": "value_deg"}.get(unit, "value")
        node = self.nodes.setdefault(
            actor, {"type": "prismatic" if unit == "mm" else "actuator", key: []}
        )
        if not node[key]:
            node[key].append([t0, 0.0])
        node[key].append([t1, float(value)])

    def wait_for(self, duration_s: float, station: str | None = None) -> None:
        self._span(station, duration_s)

    def emit(self, event_id: str) -> None:
        self.events.append({"t": self.time_s, "id": event_id})

    def attach(self, actor: str, target: str) -> None:
        node = self.nodes.setdefault(actor, {"type": "pose", "attached_to": []})
        node.setdefault("attached_to", []).append([self.time_s, target])

    def detach(self, actor: str) -> None:
        node = self.nodes.setdefault(actor, {"type": "pose", "attached_to": []})
        node.setdefault("attached_to", []).append([self.time_s, None])

    def capture(self, actor: str, station: str | None = None, duration_s: float = 0.2) -> None:
        self._span(station, duration_s)
        self.events.append({"t": self.time_s, "id": f"{actor}.capture"})

    def timeline(self) -> dict[str, Any]:
        station_names = {station.id: station.name for station in self.process.stations}
        stations = [
            {
                "id": station_id,
                "name": station_names.get(station_id, station_id),
                "t0": bounds[0],
                "t1": bounds[1],
            }
            for station_id, bounds in self.station_ranges.items()
        ]
        return {
            "fps": self.fps,
            "duration_s": self.time_s,
            "stations": stations,
            "nodes": self.nodes,
            "events": self.events,
        }


def _builder() -> SequenceBuilder:
    try:
        return _active.get()
    except LookupError as error:
        raise RuntimeError("sequence API 只能在 cell build 載入 sequence.py 時使用") from error


def move_joint(
    actor: str, joints_deg: list[float], duration_s: float = 1.0, station: str | None = None
) -> None:
    _builder().move_joint(actor, joints_deg, duration_s, station)


def move_to(
    actor: str, target: dict[str, Any], duration_s: float = 1.0, station: str | None = None
) -> None:
    _builder().move_to(actor, target, duration_s, station)


def actuate(
    actor: str,
    value: float,
    duration_s: float = 1.0,
    station: str | None = None,
    unit: str = "value",
) -> None:
    _builder().actuate(actor, value, duration_s, station, unit)


def wait_for(duration_s: float, station: str | None = None) -> None:
    _builder().wait_for(duration_s, station)


def emit(event_id: str) -> None:
    _builder().emit(event_id)


def attach(actor: str, target: str) -> None:
    _builder().attach(actor, target)


def detach(actor: str) -> None:
    _builder().detach(actor)


def capture(actor: str, station: str | None = None, duration_s: float = 0.2) -> None:
    _builder().capture(actor, station, duration_s)


def grip(actor: str, station: str | None = None, duration_s: float = 0.2) -> None:
    actuate(f"{actor}.grip", 1.0, duration_s, station)


def release(actor: str, station: str | None = None, duration_s: float = 0.2) -> None:
    actuate(f"{actor}.grip", 0.0, duration_s, station)
