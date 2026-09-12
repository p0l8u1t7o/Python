from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from ppe_schemas.v1.common import ContractModel


class ArtifactKind(StrEnum):
    STEP = "STEP"
    PARASOLID = "PARASOLID"
    SLDPRT = "SLDPRT"
    SLDASM = "SLDASM"
    BOM = "BOM"
    COORDINATE_REPORT = "COORDINATE_REPORT"
    VALIDATION_REPORT = "VALIDATION_REPORT"
    OTHER = "OTHER"


class ReleaseArtifact(ContractModel):
    id: UUID
    kind: ArtifactKind
    uri: Annotated[str, Field(min_length=1, max_length=2000)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    size_bytes: int = Field(ge=0)
    mime_type: Annotated[str, Field(min_length=1, max_length=200)]


class ReleaseRequest(ContractModel):
    approved_by: UUID


class ReleaseManifest(ContractModel):
    schema_name: Literal["ReleaseManifest"] = "ReleaseManifest"
    schema_version: Literal["1.0.0"] = "1.0.0"
    id: UUID
    project_id: UUID
    revision_id: UUID
    validation_report_id: UUID
    approved_by: UUID
    generated_at: AwareDatetime
    artifacts: Annotated[list[ReleaseArtifact], Field(min_length=1)]

    @model_validator(mode="after")
    def artifact_ids_and_hashes_must_be_unique(self) -> Self:
        artifact_ids = [artifact.id for artifact in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("Release artifact ids must be unique")
        hashes = [artifact.sha256 for artifact in self.artifacts]
        if len(hashes) != len(set(hashes)):
            raise ValueError("Release artifact hashes must be unique")
        return self
