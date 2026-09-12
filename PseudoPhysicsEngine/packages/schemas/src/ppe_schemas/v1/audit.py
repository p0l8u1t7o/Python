from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field

from ppe_schemas.v1.common import ContractModel


class AuditEventRead(ContractModel):
    id: UUID
    project_id: UUID
    revision_id: UUID | None
    actor_id: UUID | None
    event_type: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=100)]
    entity_type: Annotated[str, Field(min_length=1, max_length=100)]
    entity_id: UUID | None
    details: dict[str, object]
    created_at: AwareDatetime
