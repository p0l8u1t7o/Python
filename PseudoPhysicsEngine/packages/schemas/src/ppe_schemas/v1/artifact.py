from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field

from ppe_schemas.v1.common import ContractModel


class ArtifactFormat(StrEnum):
    STEP = "STEP"
    GLB = "GLB"
    PDF = "PDF"


class ArtifactRead(ContractModel):
    id: UUID
    project_id: UUID
    revision_id: UUID
    original_filename: Annotated[str, Field(min_length=1, max_length=255)]
    format: ArtifactFormat
    mime_type: Annotated[str, Field(min_length=1, max_length=200)]
    size_bytes: int = Field(gt=0)
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    storage_uri: Annotated[str, Field(pattern=r"^objects/sha256/[a-f0-9]{2}/[a-f0-9]{64}$")]
    source: Annotated[str, Field(min_length=1, max_length=500)]
    created_at: AwareDatetime
