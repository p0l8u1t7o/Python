"""Step-0 schemas required by the development book."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .base import ForgeModel, Pose, Rect, Size3D, Trust


class Constraints(ForgeModel):
    robot_brand: str | None = None
    takt_target_s: float | None = None
    footprint_mm: tuple[float, float] | None = None
    stations_max: int | None = None
    safety_notes: str = ""
    free_text: str = ""


class Project(ForgeModel):
    name: str
    customer: str = ""
    product: str = ""
    description: str = ""
    constraints: Constraints = Field(default_factory=Constraints)
    created: date


class InputFile(ForgeModel):
    path: str
    kind: Literal[
        "product_photo",
        "inspection_spec",
        "checklist",
        "layout",
        "cad",
        "drawing",
        "text",
        "other",
    ]
    note: str = ""
    sha256: str
    added: datetime


class InputManifest(ForgeModel):
    files: list[InputFile] = Field(default_factory=list)


class Question(ForgeModel):
    id: str
    topic: Literal["workpiece", "process", "equipment", "site", "constraint"]
    text: str
    why: str
    status: Literal["open", "answered", "skipped"] = "open"
    answer: str | dict[str, str] | None = None
    default_if_skipped: str


class Questions(ForgeModel):
    questions: list[Question] = Field(default_factory=list)


class Assumption(ForgeModel):
    id: str
    from_question: str | None = None
    text: str
    basis: str
    affects: list[str] = Field(default_factory=list)
    status: Literal["active", "overridden"] = "active"
    overridden_by: str | None = None


class Assumptions(ForgeModel):
    assumptions: list[Assumption] = Field(default_factory=list)


class Cover(ForgeModel):
    id: str
    face: Literal["front", "rear", "left", "right", "top", "bottom"]
    rect: Rect
    hinge: dict[str, Any]
    latch: str


class Sku(ForgeModel):
    id: str
    size: Size3D
    mass_kg: float
    covers: list[Cover] = Field(default_factory=list)
    ports: list[dict[str, Any]] = Field(default_factory=list)
    inspect_regions: list[dict[str, Any]] = Field(default_factory=list)


class Workpiece(ForgeModel):
    units: Literal["mm"] = "mm"
    skus: list[Sku]
    variants_note: str = ""


class VendorItem(ForgeModel):
    id: str
    kind: Literal["robot", "actuator", "sensor", "frame", "gripper", "other"]
    files: dict[str, str]
    source_url: str
    downloaded: date
    sha256: str | dict[str, str]
    units_in_file: Literal["mm", "inch"]
    up_axis: Literal["x", "y", "z"]
    approximated: bool = False
    frames: dict[str, Any]
    limits: dict[str, Any] = Field(default_factory=dict)


class VendorManifest(ForgeModel):
    vendors: list[VendorItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_are_unique(self) -> VendorManifest:
        ids = [item.id for item in self.vendors]
        duplicate = sorted({item for item in ids if ids.count(item) > 1})
        if duplicate:
            raise ValueError(f"vendor id 重複：{', '.join(duplicate)}")
        return self


class ModuleInstance(ForgeModel):
    id: str
    part: str | None = None
    vendor: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    pose: Pose = Field(default_factory=Pose)
    mount: str | None = None
    trust: Trust | None = None

    @model_validator(mode="after")
    def has_source(self) -> ModuleInstance:
        if not self.part and not self.vendor:
            raise ValueError("模組必須指定 part 或 vendor")
        return self


class Machine(ForgeModel):
    id: str
    pose: Pose = Field(default_factory=Pose)
    modules: list[ModuleInstance]


class Cell(ForgeModel):
    units: Literal["mm"] = "mm"
    plant_frame: dict[str, Any]
    survey_points: list[dict[str, Any]] = Field(default_factory=list)
    machines: list[Machine]

    @model_validator(mode="after")
    def ids_are_unique(self) -> Cell:
        ids = [m.id for machine in self.machines for m in machine.modules]
        duplicate = sorted({item for item in ids if ids.count(item) > 1})
        if duplicate:
            raise ValueError(f"模組 id 重複：{', '.join(duplicate)}")
        return self


class Station(ForgeModel):
    id: str
    name: str
    modules: list[str]
    inputs: str = ""
    outputs: str = ""


class ProcessStep(ForgeModel):
    id: str
    station: str
    actor: str
    action: Literal[
        "move_to",
        "move_joint",
        "grip",
        "release",
        "actuate",
        "wait",
        "capture",
        "flip",
        "transfer",
        "attach",
        "detach",
        "emit",
    ]
    target: dict[str, Any] | None = None
    value: Any = None
    duration_s: float | None = None
    requires: list[str] = Field(default_factory=list)
    emits: list[str] = Field(default_factory=list)
    driven_by: str | None = None


class Takt(ForgeModel):
    target_s: float
    parallel_workpieces: int = 1


class Process(ForgeModel):
    stations: list[Station]
    steps: list[ProcessStep]
    takt: Takt
    workpiece_sku: str | None = None
    initial_workpiece_frame: str | None = None

    @model_validator(mode="after")
    def references_are_valid(self) -> Process:
        station_ids = [station.id for station in self.stations]
        step_ids = [step.id for step in self.steps]
        for kind, ids in (("站別", station_ids), ("步驟", step_ids)):
            duplicate = sorted({item for item in ids if ids.count(item) > 1})
            if duplicate:
                raise ValueError(f"{kind} id 重複：{', '.join(duplicate)}")
        unknown = sorted({step.station for step in self.steps} - set(station_ids))
        if unknown:
            raise ValueError(f"步驟引用不存在的站別：{', '.join(unknown)}")
        return self


class TimelineStation(ForgeModel):
    id: str
    t0: float
    t1: float


class TimelineEvent(ForgeModel):
    t: float
    id: str


class TimelineStep(ForgeModel):
    id: str
    station: str
    actor: str
    action: str
    t0: float
    t1: float
    ik: str | None = None


class TimelineIKFailure(ForgeModel):
    step_id: str
    t: float
    position_error_mm: float
    orientation_error_deg: float
    nearest_distance_mm: float


class Timeline(ForgeModel):
    fps: int
    duration_s: float
    stations: list[TimelineStation] = Field(default_factory=list)
    steps: list[TimelineStep] = Field(default_factory=list)
    nodes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    events: list[TimelineEvent] = Field(default_factory=list)
    ik_failures: list[TimelineIKFailure] = Field(default_factory=list)


class CheckSummary(ForgeModel):
    red: int = 0
    yellow: int = 0
    green: int = 0


class CheckItem(ForgeModel):
    id: str
    type: Literal["interference", "reachability", "joint_limit", "hardware", "takt"]
    severity: Literal["red", "yellow", "green"]
    t: float | None = None
    objects: list[str] = Field(default_factory=list)
    detail: str | None = None
    suggestion: str | None = None
    value: float | None = None
    limit: float | None = None
    unit: str | None = None
    source: str | None = None
    min_dist_mm: float | None = None


class CheckEngine(ForgeModel):
    collision: str
    native_fcl: bool
    samples: int
    pairs_evaluated: int


class Checks(ForgeModel):
    version: int
    generated: datetime
    summary: CheckSummary
    items: list[CheckItem] = Field(default_factory=list)
    engine: CheckEngine | None = None


class Task(ForgeModel):
    id: str
    owner: Literal["engineering", "astra"]
    created: datetime
    created_by: Literal["user", "engineering", "astra", "system"]
    status: Literal["open", "running", "done", "failed", "blocked"]
    depends_on: list[str] = Field(default_factory=list)
    instruction: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    log: str
    result: Any = None


SCHEMAS = {
    "project": Project,
    "inputs-manifest": InputManifest,
    "questions": Questions,
    "assumptions": Assumptions,
    "workpiece": Workpiece,
    "cell": Cell,
    "vendor-manifest": VendorManifest,
    "process": Process,
    "timeline": Timeline,
    "checks": Checks,
    "task": Task,
}
