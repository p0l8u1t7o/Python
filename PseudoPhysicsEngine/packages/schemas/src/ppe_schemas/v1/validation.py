from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ppe_schemas.v1.common import ContractModel


class ValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ValidationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class ValidationIssue(ContractModel):
    code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=100)]
    severity: ValidationSeverity
    message: Annotated[str, Field(min_length=1, max_length=2000)]
    object_ids: list[UUID] = Field(default_factory=list)
    blocks_release: bool = False


class ValidationReport(ContractModel):
    schema_name: Literal["ValidationReport"] = "ValidationReport"
    schema_version: Literal["1.0.0"] = "1.0.0"
    id: UUID
    project_id: UUID
    revision_id: UUID
    status: ValidationStatus
    validator_version: Annotated[str, Field(min_length=1, max_length=100)]
    issues: list[ValidationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_must_match_blocking_issues(self) -> Self:
        has_blocker = any(issue.blocks_release for issue in self.issues)
        if has_blocker and self.status != ValidationStatus.FAILED:
            raise ValueError("A report with release blockers must have FAILED status")
        if not has_blocker and self.status != ValidationStatus.PASSED:
            raise ValueError("A report without release blockers must have PASSED status")
        return self
