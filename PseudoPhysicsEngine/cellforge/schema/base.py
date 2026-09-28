"""Shared pydantic configuration and primitive models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Trust = Literal["inferred", "confirmed"]


class ForgeModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Frame(ForgeModel):
    xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    trust: Trust = "inferred"
    source: str | None = None
    link: str | None = None
    free_space: bool = False


class JointOrigin(ForgeModel):
    xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)


class ModuleAxis(ForgeModel):
    """Articulated module axis with defaults for the legacy compact syntax."""

    id: str
    type: Literal["revolute", "prismatic"]
    parent: str = "base"
    child: str | None = None
    origin: JointOrigin = Field(default_factory=JointOrigin)
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    range_deg: tuple[float, float] | None = None
    range_mm: tuple[float, float] | None = None
    max_speed_dps: float | None = None
    max_speed_mm_s: float | None = None

    @model_validator(mode="before")
    @classmethod
    def legacy_child_defaults_to_id(cls, value: Any) -> Any:
        if isinstance(value, dict) and not value.get("child") and value.get("id"):
            return {**value, "child": value["id"]}
        return value

    @field_validator("axis")
    @classmethod
    def axis_is_nonzero(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if sum(component * component for component in value) <= 1e-24:
            raise ValueError("關節軸向不可為零向量")
        return value

    @model_validator(mode="after")
    def range_matches_type(self) -> ModuleAxis:
        expected = self.range_deg if self.type == "revolute" else self.range_mm
        if expected is None:
            unit = "range_deg" if self.type == "revolute" else "range_mm"
            raise ValueError(f"{self.type} 關節必須提供 {unit}")
        if expected[0] > expected[1]:
            raise ValueError(f"關節 {self.id} 的下限不可大於上限")
        return self


class ModuleMeta(ForgeModel):
    basis: str = ""
    placeholder: bool = False
    # 以型錄尺寸參數化近似某廠商產品（例如 robot_stub），不是原廠模型；檢查與報告都要標示。
    approximated: bool = False


class CameraSpec(ForgeModel):
    """相機與鏡頭的幾何參數；光學 frame 的 +Z 為視線、+X 為影像右、+Y 為影像下。"""

    sensor_px: tuple[int, int]
    pixel_um: float
    focal_mm: float
    working_distance_mm: float
    f_number: float = 8.0
    # 允許的模糊圈（像素）；景深依薄透鏡近似由此計算。
    blur_px: float = 2.0
    trust: Literal["confirmed", "inferred", "placeholder"] = "inferred"
    source: str | None = None

    @property
    def sensor_mm(self) -> tuple[float, float]:
        return (
            self.sensor_px[0] * self.pixel_um / 1000.0,
            self.sensor_px[1] * self.pixel_um / 1000.0,
        )

    def mm_per_px(self, distance_mm: float) -> float:
        return distance_mm * (self.pixel_um / 1000.0) / self.focal_mm

    def depth_of_field_mm(self) -> tuple[float, float]:
        """Near and far limits of acceptable focus around the working distance."""
        coc = self.blur_px * self.pixel_um / 1000.0
        focus = self.working_distance_mm
        hyperfocal = self.focal_mm**2 / (self.f_number * coc) + self.focal_mm
        near = hyperfocal * focus / (hyperfocal + (focus - self.focal_mm))
        far_denominator = hyperfocal - (focus - self.focal_mm)
        far = hyperfocal * focus / far_denominator if far_denominator > 0 else float("inf")
        return near, far


class ModuleDef(ForgeModel):
    id: str
    params_schema: dict[str, Any] = Field(default_factory=dict)
    frames: dict[str, Frame] = Field(default_factory=dict)
    axes: list[ModuleAxis] = Field(default_factory=list)
    collision: Literal["hull", "box", "mesh"] = "box"
    payload_kg: float | None = None
    tool_mass_kg: float | None = None
    vendor: str | None = None
    part_no: str | None = None
    meta: ModuleMeta = Field(default_factory=ModuleMeta)
    # 光學 frame 名稱 → 相機參數（固定相機模組或手臂工具上的相機）。
    cameras: dict[str, CameraSpec] = Field(default_factory=dict)


class Pose(Frame):
    pass


class Rect(ForgeModel):
    u: float
    v: float
    w: float
    h: float


class Size3D(ForgeModel):
    x: float
    y: float
    z: float
    trust: Trust = "inferred"
    source: str | None = None


class UniqueIdMixin(ForgeModel):
    @model_validator(mode="after")
    def validate_ids(self) -> UniqueIdMixin:
        return self
