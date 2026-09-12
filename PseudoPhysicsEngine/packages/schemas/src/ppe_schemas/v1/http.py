from typing import Literal

from ppe_schemas.v1.common import ContractModel


class ApiError(ContractModel):
    code: str
    message: str


class HealthResponse(ContractModel):
    status: Literal["ok"] = "ok"
    database: Literal["ok"] = "ok"
