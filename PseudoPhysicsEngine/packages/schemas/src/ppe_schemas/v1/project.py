from enum import StrEnum
from typing import Annotated
from uuid import UUID

from ppe_domain import RevisionStatus
from pydantic import AwareDatetime, Field

from ppe_schemas.v1.common import ContractModel

ProjectName = Annotated[str, Field(min_length=1, max_length=200)]


class ProjectCreate(ContractModel):
    name: ProjectName
    customer_name: str | None = Field(default=None, max_length=200)


class ProjectRevision(ContractModel):
    id: UUID
    project_id: UUID
    sequence: int = Field(ge=1)
    status: RevisionStatus
    parent_revision_id: UUID | None = None
    created_at: AwareDatetime


class ProjectRead(ContractModel):
    id: UUID
    name: ProjectName
    customer_name: str | None
    created_at: AwareDatetime
    current_revision: ProjectRevision


class RevisionChangeKind(StrEnum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"


class RevisionDiffEntry(ContractModel):
    object_type: Annotated[str, Field(min_length=1, max_length=100)]
    object_key: Annotated[str, Field(min_length=1, max_length=200)]
    change_kind: RevisionChangeKind
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None


class RevisionDiff(ContractModel):
    schema_name: str = "RevisionDiff"
    schema_version: str = "1.0.0"
    project_id: UUID
    from_revision_id: UUID
    to_revision_id: UUID
    entries: list[RevisionDiffEntry]
