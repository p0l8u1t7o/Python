"""電控資料（electrical.yaml）：器件、端子、電位網、連接、I/O 點位池、設備樣板、安全回路與盤面。

- 器件以穩定 id 連到 3D 模組（module_ref）與採購項（catalog_ref）；圖面、I/O 表與線號共用同一批 id。
- 設備樣板（equipment）依 cell.yaml 的模組實例各產生一組器件、連接與 I/O；
  ``{module}`` 會換成模組 id。
- I/O 與交換器埠等可由點位池（pools）依序自動配置；手動指定的點位優先，且檢查重複。
- 額定值缺少時只列「未評估」並提出問題，不自行宣稱容量或保護配合合格；安全回路只呈現規劃。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, model_validator

from .base import ForgeModel, Trust

# 端子與點位名稱：YAML 裡未加引號的 1、2 也當作字串（"01" 仍須加引號才會保留前導 0）。
Name = Annotated[
    str, BeforeValidator(lambda value: str(value) if isinstance(value, int) else value)
]

SignalType = Literal[
    "ac_power",
    "dc_power",
    "ground",
    "digital_in",
    "digital_out",
    "analog_in",
    "analog_out",
    "relay_contact",
    "safety",
    "ethernet",
    "gige",
    "fieldbus",
    "serial",
    "vendor",
]
DeviceKind = Literal[
    "isolator",
    "breaker",
    "fuse",
    "psu",
    "plc",
    "io_module",
    "safety_controller",
    "contactor",
    "relay",
    "terminal_block",
    "switch",
    "ipc",
    "camera",
    "light_controller",
    "light",
    "sensor",
    "valve",
    "robot_controller",
    "robot",
    "motor_drive",
    "conveyor_controller",
    "emergency_stop",
    "door_switch",
    "signal_tower",
    "force_sensor",
    "fan",
    "filter",
    "ground_bar",
    "other",
]


class Terminal(ForgeModel):
    id: Name
    signal: SignalType
    # 電位域名稱，例如 "24VDC"、"0V"、"AC-L"、"AC-N"、"PE"；受電端子必須追到同名的供電端子。
    # 訊號端子可省略。
    voltage: str | None = None
    direction: Literal["source", "sink", "bidirectional", "passive"] = "passive"
    required: bool = False
    label: str | None = None


class Ratings(ForgeModel):
    """額定值；缺少時相關容量檢查為未評估，不以預設值補。"""

    current_a: float | None = None
    power_w: float | None = None
    output_current_a: float | None = None
    source: str | None = None


class PanelPlacement(ForgeModel):
    rail: str
    order: int = 0


class Device(ForgeModel):
    id: str
    name: str
    kind: DeviceKind
    model: str = ""
    catalog_ref: str | None = None
    # 本器件佔採購項的數量；None 表示含於組套（例如 PLC 套內的 I/O），只核對採購項存在。
    catalog_quantity: float | None = 1.0
    module_ref: str | None = None
    location: Literal["panel", "field"] = "panel"
    size_mm: tuple[float, float, float] | None = None
    panel: PanelPlacement | None = None
    ratings: Ratings = Field(default_factory=Ratings)
    terminals: list[Terminal] = Field(default_factory=list)
    # 器件內部導通的端子對（例如斷路器進出線、端子排上下層），用於斷路追蹤。
    bridges: list[tuple[Name, Name]] = Field(default_factory=list)
    trust: Trust = "inferred"
    source: str | None = None
    note: str = ""


class Net(ForgeModel):
    """電位或網路：同一個 net 上的端子視為相連。"""

    id: str
    signal: SignalType
    voltage: str | None = None
    label: str | None = None


class Endpoint(ForgeModel):
    device: str | None = None
    terminal: Name | None = None
    net: str | None = None
    # 由點位池自動配置端子（例如交換器埠）
    pool: str | None = None

    @model_validator(mode="after")
    def one_target(self) -> Endpoint:
        device, terminal = self.device is not None, self.terminal is not None
        net, pool = self.net is not None, self.pool is not None
        forms = (
            device and terminal and not net and not pool,
            net and not (device or terminal or pool),
            pool and not (device or terminal or net),
        )
        if sum(forms) != 1:
            raise ValueError("連接端點必須是 device＋terminal、net 或 pool 其中一種")
        return self


class Connection(ForgeModel):
    id: str
    from_: Endpoint = Field(alias="from")
    to: Endpoint
    wire_numbers: list[str] = Field(default_factory=list)
    cable_ref: str | None = None
    note: str = ""


class Pool(ForgeModel):
    """一個器件上可依序配置的端子（I/O 通道、交換器埠、端子排位置）。"""

    id: str
    device: str
    signal: SignalType
    terminals: list[Name]


class IoPoint(ForgeModel):
    """I/O 表的一列：控制器通道（固定位址或由點位池配置）接到現場器件的端子。"""

    id: str
    signal: SignalType
    function: str
    address: Name | None = None
    pool: str | None = None
    channel_device: str | None = None
    # 經端子排轉接的位置（device＋terminal 或 pool）；盤內線與現場線分開計線。
    via: Endpoint | None = None
    field: Endpoint | None = None
    wire: str | None = None
    note: str = ""

    @model_validator(mode="after")
    def address_or_pool(self) -> IoPoint:
        if self.address is None and self.pool is None:
            raise ValueError(f"I/O {self.id} 必須指定 address 或 pool")
        if self.address is not None and self.channel_device is None and self.pool is None:
            raise ValueError(f"I/O {self.id} 指定 address 時必須一併指定 channel_device 或 pool")
        return self


class EquipmentMatch(ForgeModel):
    part: str | None = None
    vendor: str | None = None
    module: str | None = None
    tool: str | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> EquipmentMatch:
        if not any((self.part, self.vendor, self.module, self.tool)):
            raise ValueError("電控設備樣板至少要指定 part、vendor、module 或 tool 其中一項")
        return self


class EquipmentTemplate(ForgeModel):
    """每個符合條件的模組實例產生一組器件、連接與 I/O；字串中的 {module} 換成模組 id。"""

    id: str
    match: EquipmentMatch
    devices: list[dict[str, Any]] = Field(default_factory=list)
    connections: list[dict[str, Any]] = Field(default_factory=list)
    io: list[dict[str, Any]] = Field(default_factory=list)


class SafetyCircuit(ForgeModel):
    """安全功能回路（急停、門互鎖）：只呈現需求與規劃回路，不宣稱安全等級。"""

    id: str
    name: str
    devices: list[str]
    controller: str
    outputs: list[str] = Field(default_factory=list)
    requirement: str = ""
    note: str = "未完成風險評估與安全架構驗證；不宣稱安全等級或停止類別"


class PanelRail(ForgeModel):
    """盤內軌道或線槽；y_mm 為中心線距盤面上緣的距離。線槽以 height_mm 佔用上下空間。"""

    id: str
    y_mm: float
    kind: Literal["din_rail", "duct", "mounting_plate"] = "din_rail"
    height_mm: float | None = None


class PanelLayout(ForgeModel):
    width_mm: float
    height_mm: float
    depth_mm: float | None = None
    margin_mm: float = 20.0
    clearance_mm: float = 10.0
    rails: list[PanelRail] = Field(default_factory=list)
    source: str | None = None


class DrawingTemplate(ForgeModel):
    """圖框與標題欄欄位；LOGO 為圖檔路徑（案子內 drawing_templates/），未提供時顯示案名文字。"""

    paper: Literal["A3", "A4"] = "A3"
    orientation: Literal["landscape", "portrait"] = "landscape"
    logo: str | None = None
    company: str = ""
    drawing_no: str = ""
    revision: str = "V1"
    date: str | None = None
    drawn_by: str = "待填"
    designed_by: str = "待填"
    checked_by: str = "待填"
    approved_by: str = "待填"
    status: str = "工程規劃圖／非施工放行版"


class Electrical(ForgeModel):
    version: Literal[1] = 1
    title: str = ""
    nets: list[Net] = Field(default_factory=list)
    devices: list[Device] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    pools: list[Pool] = Field(default_factory=list)
    io: list[IoPoint] = Field(default_factory=list)
    equipment: list[EquipmentTemplate] = Field(default_factory=list)
    safety: list[SafetyCircuit] = Field(default_factory=list)
    panel: PanelLayout | None = None
    drawing: DrawingTemplate = Field(default_factory=DrawingTemplate)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_are_unique(self) -> Electrical:
        for kind, ids in (
            ("電位網", [net.id for net in self.nets]),
            ("器件", [device.id for device in self.devices]),
            ("連接", [connection.id for connection in self.connections]),
            ("點位池", [pool.id for pool in self.pools]),
            ("I/O", [point.id for point in self.io]),
            ("設備樣板", [template.id for template in self.equipment]),
            ("安全回路", [circuit.id for circuit in self.safety]),
        ):
            duplicate = sorted({value for value in ids if ids.count(value) > 1})
            if duplicate:
                raise ValueError(f"electrical.yaml 的{kind} id 重複：{', '.join(duplicate)}")
        for device in self.devices:
            terminals = [terminal.id for terminal in device.terminals]
            duplicate = sorted({value for value in terminals if terminals.count(value) > 1})
            if duplicate:
                raise ValueError(f"器件 {device.id} 的端子 id 重複：{', '.join(duplicate)}")
        return self
