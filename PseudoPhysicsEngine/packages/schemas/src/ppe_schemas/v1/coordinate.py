from typing import Annotated, Literal, Self
from uuid import UUID

from ppe_coordinates import Matrix4, matrix4, validate_rigid_transform
from ppe_domain import TrustStatus
from pydantic import Field, field_validator, model_validator

from ppe_schemas.v1.common import ContractModel


class CoordinateFrame(ContractModel):
    id: UUID
    revision_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=200)]
    parent_frame_id: UUID | None = None
    length_unit: Literal["mm"] = "mm"
    axis_system: Literal["RIGHT_HANDED_Z_UP"] = "RIGHT_HANDED_Z_UP"


class FrameTransform(ContractModel):
    id: UUID
    revision_id: UUID
    parent_frame_id: UUID
    child_frame_id: UUID
    matrix: Matrix4
    trust_status: TrustStatus
    source: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("matrix", mode="before")
    @classmethod
    def validate_matrix(cls, value: object) -> Matrix4:
        if not isinstance(value, (list, tuple)):
            raise ValueError("matrix must be a 4x4 array")
        result = matrix4(value)
        validate_rigid_transform(result)
        return result

    @model_validator(mode="after")
    def parent_and_child_must_differ(self) -> Self:
        if self.parent_frame_id == self.child_frame_id:
            raise ValueError("parent_frame_id and child_frame_id must differ")
        return self


class FrameCreate(ContractModel):
    frame: CoordinateFrame
    transform_from_parent: FrameTransform | None = None

    @model_validator(mode="after")
    def transform_must_match_frame(self) -> Self:
        transform = self.transform_from_parent
        if self.frame.parent_frame_id is None:
            if transform is not None:
                raise ValueError("A root frame cannot have transform_from_parent")
            return self
        if transform is None:
            raise ValueError("A non-root frame requires transform_from_parent")
        if transform.revision_id != self.frame.revision_id:
            raise ValueError("Frame and transform must belong to the same revision")
        if transform.parent_frame_id != self.frame.parent_frame_id:
            raise ValueError("Transform parent does not match frame parent")
        if transform.child_frame_id != self.frame.id:
            raise ValueError("Transform child does not match frame id")
        return self


class ControlPointPair(ContractModel):
    id: UUID
    source_mm: tuple[float, float, float]
    target_mm: tuple[float, float, float]


class CalibrationRequest(ContractModel):
    control_points: Annotated[list[ControlPointPair], Field(min_length=3)]
    rms_tolerance_mm: float = Field(gt=0)
    max_tolerance_mm: float = Field(gt=0)


class CalibrationResult(ContractModel):
    schema_name: Literal["CalibrationResult"] = "CalibrationResult"
    schema_version: Literal["1.0.0"] = "1.0.0"
    revision_id: UUID
    transform: Matrix4
    control_point_ids: list[UUID]
    residuals_mm: list[float]
    rms_error_mm: float = Field(ge=0)
    max_error_mm: float = Field(ge=0)
    accepted: bool


class FrameTreeRead(ContractModel):
    revision_id: UUID
    frames: list[CoordinateFrame]
    transforms: list[FrameTransform]
