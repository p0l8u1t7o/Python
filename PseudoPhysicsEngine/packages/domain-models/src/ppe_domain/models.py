from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TrustStatus(StrEnum):
    INFERRED = "INFERRED"
    DRAWING_CONFIRMED = "DRAWING_CONFIRMED"
    CAD_CONFIRMED = "CAD_CONFIRMED"
    SURVEY_CALIBRATED = "SURVEY_CALIBRATED"
    RELEASED = "RELEASED"


class RevisionStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class Project:
    id: UUID
    name: str
    customer_name: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectRevision:
    id: UUID
    project_id: UUID
    sequence: int
    status: RevisionStatus
    created_at: datetime
    parent_revision_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("Revision sequence must be at least 1")
