from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field

from ppe_schemas.v1.common import ContractModel


class JobKind(StrEnum):
    TESSELLATE = "TESSELLATE"
    SIMULATE = "SIMULATE"
    RENDER = "RENDER"
    EXPORT = "EXPORT"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobSubmit(ContractModel):
    project_id: UUID
    revision_id: UUID
    kind: JobKind
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    input_artifact_ids: list[UUID] = Field(default_factory=list)
    parameters: dict[str, object] = Field(default_factory=dict)
    tool_name: Annotated[str, Field(min_length=1, max_length=100)]
    tool_version: Annotated[str, Field(min_length=1, max_length=100)]
    max_attempts: int = Field(default=3, ge=1, le=10)


class JobRead(ContractModel):
    id: UUID
    project_id: UUID
    revision_id: UUID
    kind: JobKind
    status: JobStatus
    idempotency_key: str
    input_artifact_ids: list[UUID]
    result_artifact_ids: list[UUID]
    parameters: dict[str, object]
    tool_name: str
    tool_version: str
    worker_id: str | None
    attempt_count: int
    max_attempts: int
    error: str | None
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    heartbeat_at: AwareDatetime | None
    lease_expires_at: AwareDatetime | None
    finished_at: AwareDatetime | None


class JobClaimRequest(ContractModel):
    worker_id: Annotated[str, Field(min_length=1, max_length=200)]
    supported_kinds: Annotated[list[JobKind], Field(min_length=1)]
    lease_seconds: int = Field(default=60, ge=10, le=3600)


class JobHeartbeatRequest(ContractModel):
    worker_id: Annotated[str, Field(min_length=1, max_length=200)]
    lease_seconds: int = Field(default=60, ge=10, le=3600)


class JobCompleteRequest(ContractModel):
    worker_id: Annotated[str, Field(min_length=1, max_length=200)]
    result_artifact_ids: list[UUID] = Field(default_factory=list)


class JobFailRequest(ContractModel):
    worker_id: Annotated[str, Field(min_length=1, max_length=200)]
    error: Annotated[str, Field(min_length=1, max_length=4000)]
    retryable: bool = True
