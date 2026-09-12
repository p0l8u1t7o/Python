from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ppe_schemas.v1.common import ContractModel


class ProcessStep(ContractModel):
    id: UUID
    name: Annotated[str, Field(min_length=1, max_length=200)]
    predecessor_ids: list[UUID] = Field(default_factory=list)
    input_conditions: list[str] = Field(default_factory=list)
    output_conditions: list[str] = Field(default_factory=list)
    equipment_requirements: list[str] = Field(default_factory=list)
    estimated_duration_seconds: float = Field(ge=0)


class ProcessSpec(ContractModel):
    schema_name: Literal["ProcessSpec"] = "ProcessSpec"
    schema_version: Literal["1.0.0"] = "1.0.0"
    id: UUID
    project_id: UUID
    revision_id: UUID
    target_cycle_time_seconds: float = Field(gt=0)
    steps: Annotated[list[ProcessStep], Field(min_length=1)]
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_step_graph(self) -> Self:
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Process step ids must be unique")

        known_ids = set(step_ids)
        predecessors = {step.id: set(step.predecessor_ids) for step in self.steps}
        for step_id, dependencies in predecessors.items():
            if step_id in dependencies:
                raise ValueError("A process step cannot depend on itself")
            unknown = dependencies - known_ids
            if unknown:
                values = sorted(map(str, unknown))
                raise ValueError(f"Process step references unknown predecessors: {values}")

        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        def visit(step_id: UUID) -> None:
            if step_id in visiting:
                raise ValueError("Process step graph must not contain a cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for predecessor_id in predecessors[step_id]:
                visit(predecessor_id)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        return self


class ProcessAnalysis(ContractModel):
    schema_name: Literal["ProcessAnalysis"] = "ProcessAnalysis"
    schema_version: Literal["1.0.0"] = "1.0.0"
    process_spec_id: UUID
    project_id: UUID
    revision_id: UUID
    critical_path_step_ids: list[UUID]
    cycle_time_seconds: float = Field(ge=0)
    target_cycle_time_seconds: float = Field(gt=0)
    within_target: bool
