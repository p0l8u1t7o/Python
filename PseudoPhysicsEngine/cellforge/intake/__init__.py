"""Input extraction helpers used by the engineering agent."""

from pathlib import Path
from typing import Any


def prepare_intake(project: Path, progress=None) -> dict[str, Any]:
    """Lazily import document backends so module CLIs stay warning-free."""
    from .prepare import prepare_intake as implementation

    return implementation(project, progress)


__all__ = ["prepare_intake"]
