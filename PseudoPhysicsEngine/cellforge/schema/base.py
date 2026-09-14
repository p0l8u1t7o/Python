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


class ModuleDef(ForgeModel):
    id: str
    params_schema: dict[str, Any] = Field(default_factory=dict)
    frames: dict[str, Frame] = Field(default_factory=dict)
    axes: list[ModuleAxis] = Field(default_factory=list)
    collision: Literal["hull", "box", "mesh"] = "box"
    payload_kg: float | None = None
    vendor: str | None = None
    part_no: str | None = None


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
