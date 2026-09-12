from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from ppe_coordinates import Matrix4, matrix4, validate_rigid_transform
from ppe_domain import TrustStatus
from pydantic import Field, field_validator, model_validator

from ppe_schemas.v1.common import ContractModel
from ppe_schemas.v1.coordinate import FrameTreeRead
from ppe_schemas.v1.project import ProjectRevision


class OperationType(StrEnum):
    ADD = "ADD"
    UPDATE = "UPDATE"
    REMOVE = "REMOVE"


class ChangeOperation(ContractModel):
    operation: OperationType
    object_type: Annotated[str, Field(min_length=1, max_length=100)]
    object_id: UUID
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None

    @model_validator(mode="after")
    def payload_matches_operation(self) -> Self:
        if self.operation == OperationType.ADD and (self.before is not None or self.after is None):
            raise ValueError("ADD requires after and forbids before")
        if self.operation == OperationType.UPDATE and (self.before is None or self.after is None):
            raise ValueError("UPDATE requires before and after")
        if self.operation == OperationType.REMOVE and (
            self.before is None or self.after is not None
        ):
            raise ValueError("REMOVE requires before and forbids after")
        return self


class ChangeSet(ContractModel):
    schema_name: Literal["ChangeSet"] = "ChangeSet"
    schema_version: Literal["1.0.0"] = "1.0.0"
    id: UUID
    project_id: UUID
    base_revision_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    user_instruction: Annotated[str, Field(min_length=1, max_length=10_000)]
    interpreted_intent: Annotated[str, Field(min_length=1, max_length=10_000)]
    operations: Annotated[list[ChangeOperation], Field(min_length=1)]
    requires_tessellation: bool = False
    requires_simulation: bool = False
    requires_render: bool = False
    approved_by: UUID | None = None


class FrameTransformChange(ContractModel):
    id: UUID
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


class CoordinateFrameChange(ContractModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    parent_frame_id: UUID | None = None
    transform_from_parent: FrameTransformChange | None = None

    @model_validator(mode="after")
    def transform_matches_parent(self) -> Self:
        if self.parent_frame_id is None and self.transform_from_parent is not None:
            raise ValueError("A root frame cannot have transform_from_parent")
        if self.parent_frame_id is not None and self.transform_from_parent is None:
            raise ValueError("A non-root frame requires transform_from_parent")
        return self


class ChangeSetIssue(ContractModel):
    code: str
    message: str
    operation_index: int | None = Field(default=None, ge=0)


class ChangeSetPreview(ContractModel):
    change_set_id: UUID
    base_revision_id: UUID
    valid: bool
    affected_object_ids: list[UUID]
    issues: list[ChangeSetIssue]


class ChangeSetApplyResult(ContractModel):
    change_set_id: UUID
    revision: ProjectRevision
    frame_tree: FrameTreeRead
