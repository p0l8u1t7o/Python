from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field

from ppe_schemas.v1.common import ContractModel


class ReviewCommentCreate(ContractModel):
    author_id: UUID
    body: Annotated[str, Field(min_length=1, max_length=4000)]
    object_ids: list[UUID] = Field(default_factory=list)
    parent_comment_id: UUID | None = None


class ReviewCommentResolve(ContractModel):
    resolved_by: UUID


class ReviewCommentRead(ContractModel):
    id: UUID
    project_id: UUID
    revision_id: UUID
    author_id: UUID
    body: str
    object_ids: list[UUID]
    parent_comment_id: UUID | None
    created_at: AwareDatetime
    resolved_at: AwareDatetime | None
    resolved_by: UUID | None
