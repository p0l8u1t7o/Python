"""Shared pydantic configuration and primitive models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Trust = Literal["inferred", "confirmed"]


class ForgeModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Frame(ForgeModel):
    xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    trust: Trust = "inferred"
    source: str | None = None


class ModuleDef(ForgeModel):
    id: str
    params_schema: dict[str, Any] = Field(default_factory=dict)
    frames: dict[str, Frame] = Field(default_factory=dict)
    axes: list[dict[str, Any]] = Field(default_factory=list)
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
