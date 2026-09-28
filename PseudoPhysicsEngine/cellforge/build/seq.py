"""Restricted sequence API backed by the WP2 simulator."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any

from cellforge.schema.models import Process, ProcessStep
from cellforge.sim.engine import Simulator
from cellforge.sim.scene import SceneModel
from cellforge.sim.scheduler import schedule_process

_active: contextvars.ContextVar[SequenceBuilder] = contextvars.ContextVar("cellforge_sequence")


@dataclass
class SequenceBuilder:
    process: Process
    scene: SceneModel
    fps: int = 50
    time_s: float = 0.0
    simulator: Simulator = field(init=False)
    _legacy_index: int = 0
    _compiled: bool = False

    def __post_init__(self) -> None:
        self.simulator = Simulator(self.scene, fps=self.fps)
        self.simulator.initialize_parts(self.process.initial_workpiece_frame)

    def run_process(self) -> None:
        if self._legacy_index:
            raise ValueError("run_process() 不可與舊式逐步 sequence API 混用")
        if not self._compiled:
            schedule_process(self.process, self.simulator)
            self.time_s = self.simulator.duration_s
            self._compiled = True

    def _step(
        self,
        action: str,
        actor: str,
        *,
        station: str | None = None,
        target: dict[str, Any] | None = None,
        value: Any = None,
        duration_s: float | None = None,
    ) -> None:
        if self._compiled:
            raise ValueError("run_process() 後不可再加入舊式 sequence 動作")
        self._legacy_index += 1
        station_id = station or (self.process.stations[0].id if self.process.stations else "legacy")
        step = ProcessStep(
            id=f"legacy.{self._legacy_index}",
            station=station_id,
            actor=actor,
            action=action,
            target=target,
            value=value,
            duration_s=duration_s,
        )
        t0 = self.time_s
        t1, ik = self.simulator.execute(step, t0)
        self.time_s = t1
        self.simulator.steps.append(
            {
                "id": step.id,
                "station": station_id,
                "actor": actor,
                "action": action,
                "t0": t0,
                "t1": t1,
                "ik": ik,
            }
        )
        bounds = self.simulator.station_ranges.setdefault(station_id, [t0, t1])
        bounds[1] = max(bounds[1], t1)

    def move_joint(
        self,
        actor: str,
        joints_deg: list[float],
        duration_s: float = 1.0,
        station: str | None = None,
    ) -> None:
        self._step(
            "move_joint",
            actor,
            station=station,
            value={"joints_deg": joints_deg},
            duration_s=duration_s,
        )

    def move_to(
        self,
        actor: str,
        target: dict[str, Any],
        duration_s: float = 1.0,
        station: str | None = None,
    ) -> None:
        self._step("move_to", actor, station=station, target=target, duration_s=duration_s)

    def actuate(
        self,
        actor: str,
        value: float,
        duration_s: float = 1.0,
        station: str | None = None,
        unit: str = "value",
    ) -> None:
        encoded: Any = value if unit not in {"mm", "deg"} else {f"value_{unit}": value}
        self._step("actuate", actor, station=station, value=encoded, duration_s=duration_s)

    def wait_for(self, duration_s: float, station: str | None = None) -> None:
        self._step("wait", "system", station=station, duration_s=duration_s)

    def emit(self, event_id: str) -> None:
        self.simulator.events.append({"t": self.time_s, "id": event_id})

    def attach(self, actor: str, target: str) -> None:
        robot = target.removesuffix(".tool") if target.endswith(".tool") else actor
        self._step("attach", robot)

    def detach(self, actor: str) -> None:
        self._step("detach", actor.removesuffix(".tool"))

    def capture(self, actor: str, station: str | None = None, duration_s: float = 0.2) -> None:
        self._step("capture", actor, station=station, duration_s=duration_s)

    def timeline(self) -> dict[str, Any]:
        result = self.simulator.timeline()
        station_names = {station.id: station.name for station in self.process.stations}
        for station in result["stations"]:
            station["name"] = station_names.get(station["id"], station["id"])
        return result


def _builder() -> SequenceBuilder:
    try:
        return _active.get()
    except LookupError as error:
        raise RuntimeError("sequence API 只能在 cell build 載入 sequence.py 時使用") from error


def run_process() -> None:
    _builder().run_process()


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
    _builder()._step("grip", actor, station=station, duration_s=duration_s)


def release(
    actor: str,
    station: str | None = None,
    duration_s: float = 0.2,
    target: dict[str, Any] | None = None,
) -> None:
    _builder()._step("release", actor, station=station, duration_s=duration_s, target=target)
