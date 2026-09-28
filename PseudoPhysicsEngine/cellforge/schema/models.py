"""Step-0 schemas required by the development book."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .base import ForgeModel, Pose, Rect, Size3D, Trust
from .costing import Costing
from .electrical import Electrical
from .versions import VersionManifest


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


class PartPlacement(ForgeModel):
    """零件初始位置：放在某個命名 frame（模組或另一零件的 frame）上；持有者為該 frame 的擁有者。"""

    frame: str
    offset: Pose = Field(default_factory=Pose)


class PartInstance(ForgeModel):
    """產品中的一個零件實例；外形取自 SKU 方塊或 CadQuery 零件模組（library/ 或 parts/）。"""

    id: str
    sku: str | None = None
    part: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    mass_kg: float | None = None
    initial: PartPlacement | None = None
    # 零件狀態軸的初始值（例如接頭翹起角），鍵為零件模組的軸 id。
    state: dict[str, float] = Field(default_factory=dict)
    trust: Trust | None = None
    source: str | None = None

    @model_validator(mode="after")
    def one_geometry_source(self) -> PartInstance:
        if (self.sku is None) == (self.part is None):
            raise ValueError(f"零件 {self.id} 必須在 sku 與 part 之間擇一")
        return self


class Workpiece(ForgeModel):
    units: Literal["mm"] = "mm"
    skus: list[Sku] = Field(default_factory=list)
    variants_note: str = ""
    # 多零件產品；空白時沿用單一工件（id workpiece，取 process.workpiece_sku）。
    parts: list[PartInstance] = Field(default_factory=list)

    @model_validator(mode="after")
    def part_ids_are_unique(self) -> Workpiece:
        ids = [part.id for part in self.parts]
        duplicate = sorted({item for item in ids if ids.count(item) > 1})
        if duplicate:
            raise ValueError(f"零件 id 重複：{', '.join(duplicate)}")
        skus = {sku.id for sku in self.skus}
        unknown = sorted({part.sku for part in self.parts if part.sku and part.sku not in skus})
        if unknown:
            raise ValueError(f"零件引用不存在的 SKU：{', '.join(unknown)}")
        return self


class VendorItem(ForgeModel):
    id: str
    kind: Literal["robot", "actuator", "sensor", "frame", "gripper", "other"]
    files: dict[str, str]
    source_url: str
    downloaded: date
    sha256: str | dict[str, str]
    units_in_file: Literal["mm", "inch", "m"]
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


CONTRACT_ACTIONS = ("pick", "place", "insert", "press", "inspect")


class ActionPath(ForgeModel):
    """動作契約的路徑：接近、下探／插入深度、保持與撤離，長度沿目標 frame 的 +Z（mm）。"""

    approach_mm: float = 30.0
    retract_mm: float | None = None
    depth_mm: float = 0.0
    hold_s: float = 0.0
    speed_scale: float = 0.5


class PressSpec(ForgeModel):
    """壓合：工具的壓墊 frame 依序對應 objects；各零件以 face frame 接受壓墊。"""

    pads: list[str] = Field(default_factory=list)
    face: str = "press_face"
    pad_size_mm: tuple[float, float] = (7.0, 9.0)
    # 壓墊彈簧的可壓縮行程；超過即到底，由剛性擋塊直接施力（過壓）。
    spring_mm: float = 3.0


class InspectView(ForgeModel):
    """手臂相機的觀測位姿：相機位於 ROI frame 的 +Z 方向、繞 ROI 的 X 軸傾斜 tilt_deg。"""

    distance_mm: float
    tilt_deg: float = 0.0
    spin_deg: float = 0.0


class InspectSpec(ForgeModel):
    """檢測：以相機 frame 觀察 ROI；ROI 為 frame（XY 平面上的矩形）或各零件上的同名 frame。"""

    camera: str
    roi: str
    roi_size_mm: tuple[float, float]
    max_mm_per_px: float
    view: InspectView | None = None
    # 判定依據：各零件兩個 frame 沿參考 frame 法向的距離（例如銀腳末端與焊墊的間隙）。
    gap_frames: tuple[str, str] | None = None
    max_gap_mm: float | None = None


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
        "pick",
        "place",
        "insert",
        "press",
        "inspect",
    ]
    target: dict[str, Any] | None = None
    value: Any = None
    duration_s: float | None = None
    requires: list[str] = Field(default_factory=list)
    emits: list[str] = Field(default_factory=list)
    driven_by: str | None = None
    # 本步驟作用的零件 id；單一工件案例省略時為 workpiece。
    object: str | None = None
    # 動作契約（pick／place／insert／press／inspect）的宣告：同時作用的多個零件、
    # 需要的工具模組、路徑，以及對應的合法接觸宣告 id。
    objects: list[str] = Field(default_factory=list)
    tool: str | None = None
    path: ActionPath | None = None
    contact: str | None = None
    press: PressSpec | None = None
    inspect: InspectSpec | None = None


class ContactRegion(ForgeModel):
    """接觸區域：frame 的 XY 平面上以原點為中心的矩形（mm）；省略 size 表示不限位置。"""

    frame: str
    size_mm: tuple[float, float] | None = None


class ContactDecl(ForgeModel):
    """合法接觸：只在 window 的步驟期間、區域內、方向相符且穿透不超過容差時允許。"""

    id: str
    pair: tuple[str, str]
    window: list[str]
    tolerance_mm: float
    region: ContactRegion | None = None
    # pair[0] 相對 pair[1] 的接近方向，以 region frame 表示；省略表示不檢查方向。
    direction: tuple[float, float, float] | None = None
    source: str | None = None


class Takt(ForgeModel):
    target_s: float
    parallel_workpieces: int = 1


class Process(ForgeModel):
    stations: list[Station]
    steps: list[ProcessStep]
    takt: Takt
    workpiece_sku: str | None = None
    initial_workpiece_frame: str | None = None
    contacts: list[ContactDecl] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_valid(self) -> Process:
        station_ids = [station.id for station in self.stations]
        step_ids = [step.id for step in self.steps]
        contact_ids = [contact.id for contact in self.contacts]
        for kind, ids in (("站別", station_ids), ("步驟", step_ids), ("接觸宣告", contact_ids)):
            duplicate = sorted({item for item in ids if ids.count(item) > 1})
            if duplicate:
                raise ValueError(f"{kind} id 重複：{', '.join(duplicate)}")
        unknown = sorted({step.station for step in self.steps} - set(station_ids))
        if unknown:
            raise ValueError(f"步驟引用不存在的站別：{', '.join(unknown)}")
        windows = sorted(
            {item for contact in self.contacts for item in contact.window} - set(step_ids)
        )
        if windows:
            raise ValueError(f"接觸宣告的窗口引用不存在的步驟：{', '.join(windows)}")
        referenced = sorted(
            {step.contact for step in self.steps if step.contact} - set(contact_ids)
        )
        if referenced:
            raise ValueError(f"步驟引用不存在的接觸宣告：{', '.join(referenced)}")
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


class TimelinePathDiscontinuity(ForgeModel):
    """直線移動在相鄰取樣點之間 IK 跳解：加密取樣也無法讓關節變化縮小。"""

    step_id: str
    t: float
    joint: str
    jump_deg: float


class TimelineActionResult(ForgeModel):
    """動作契約的執行結果；失敗時 reason_code 為固定代碼、reason 為中文說明。"""

    step_id: str
    action: str
    objects: list[str] = Field(default_factory=list)
    status: Literal["ok", "failed"]
    t0: float
    t1: float
    reason_code: str | None = None
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class Timeline(ForgeModel):
    fps: int
    duration_s: float
    stations: list[TimelineStation] = Field(default_factory=list)
    steps: list[TimelineStep] = Field(default_factory=list)
    nodes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    events: list[TimelineEvent] = Field(default_factory=list)
    ik_failures: list[TimelineIKFailure] = Field(default_factory=list)
    path_discontinuities: list[TimelinePathDiscontinuity] = Field(default_factory=list)
    action_results: list[TimelineActionResult] = Field(default_factory=list)


class CheckSummary(ForgeModel):
    red: int = 0
    yellow: int = 0
    green: int = 0


class CheckItem(ForgeModel):
    id: str
    type: Literal[
        "interference",
        "reachability",
        "joint_limit",
        "hardware",
        "takt",
        "process",
        "vision",
        "electrical",
    ]
    severity: Literal["red", "yellow", "green"]
    # 判定狀態；not_evaluated 表示資料不足未評估（不等於合格）。舊版項目省略。
    status: Literal["pass", "fail", "not_evaluated", "error"] | None = None
    code: str | None = None
    t: float | None = None
    objects: list[str] = Field(default_factory=list)
    detail: str | None = None
    suggestion: str | None = None
    value: float | None = None
    limit: float | None = None
    unit: str | None = None
    source: str | None = None
    min_dist_mm: float | None = None
    # 本項涉及的近似廠商模型（approximated stub）；非空時結果不代表原廠真機。
    approximated_models: list[str] = Field(default_factory=list)
    # 由合法接觸宣告評估的干涉項目所對應的宣告 id。
    contact_id: str | None = None


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
    "version-manifest": VersionManifest,
    "costing": Costing,
    "electrical": Electrical,
}
