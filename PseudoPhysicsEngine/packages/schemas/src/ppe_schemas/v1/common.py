from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: ClassVar[str] = "1.0.0"
