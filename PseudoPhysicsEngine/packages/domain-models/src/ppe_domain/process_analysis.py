from collections.abc import Collection, Mapping
from dataclasses import dataclass
from uuid import UUID


class ProcessGraphError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CriticalPathResult:
    step_ids: tuple[UUID, ...]
    cycle_time_seconds: float


def calculate_critical_path(
    steps: Mapping[UUID, tuple[float, Collection[UUID]]],
) -> CriticalPathResult:
    """Return the longest predecessor path through an acyclic process graph."""
    if not steps:
        raise ProcessGraphError("Process graph must contain at least one step")

    visiting: set[UUID] = set()
    cache: dict[UUID, CriticalPathResult] = {}

    def visit(step_id: UUID) -> CriticalPathResult:
        if step_id in cache:
            return cache[step_id]
        if step_id in visiting:
            raise ProcessGraphError("Process graph must not contain a cycle")
        try:
            duration, predecessors = steps[step_id]
        except KeyError as error:
            raise ProcessGraphError(f"Unknown process step {step_id}") from error
        if duration < 0:
            raise ProcessGraphError(f"Process step {step_id} has a negative duration")

        visiting.add(step_id)
        paths = [visit(predecessor_id) for predecessor_id in predecessors]
        visiting.remove(step_id)
        prefix = max(paths, key=lambda path: path.cycle_time_seconds, default=None)
        result = CriticalPathResult(
            step_ids=((*prefix.step_ids, step_id) if prefix else (step_id,)),
            cycle_time_seconds=(prefix.cycle_time_seconds if prefix else 0.0) + duration,
        )
        cache[step_id] = result
        return result

    return max(
        (visit(step_id) for step_id in steps),
        key=lambda path: path.cycle_time_seconds,
    )
