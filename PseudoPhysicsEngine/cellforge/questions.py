"""Question and assumption state transitions shared by CLI and API."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cellforge.schema import Questions
from cellforge.yamlio import dump_yaml, load_yaml


def _next_assumption_id(items: list[dict[str, Any]]) -> str:
    numbers = []
    for item in items:
        match = re.fullmatch(r"A-(\d+)", str(item.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"A-{max(numbers, default=0) + 1:03d}"


def update_questions(
    project: Path,
    question_id: str | None,
    *,
    answer: str | None = None,
    skip: bool = False,
    skip_all: bool = False,
) -> list[str]:
    """Answer or skip questions and materialize defaults as assumptions."""
    questions_path = project / "analysis" / "questions.yaml"
    assumptions_path = project / "analysis" / "assumptions.yaml"
    raw = load_yaml(questions_path) or {"questions": []}
    validated = Questions.model_validate(raw).model_dump(mode="json")
    targets = (
        [item for item in validated["questions"] if item["status"] == "open"]
        if skip_all
        else [item for item in validated["questions"] if item["id"] == question_id]
    )
    if not targets:
        raise KeyError(question_id or "open")
    assumptions = load_yaml(assumptions_path) or {"assumptions": []}
    changed: list[str] = []
    for item in targets:
        if skip or skip_all:
            item["status"] = "skipped"
            item["answer"] = None
            existing = next(
                (
                    candidate
                    for candidate in assumptions["assumptions"]
                    if candidate.get("from_question") == item["id"]
                    and candidate.get("status") == "active"
                ),
                None,
            )
            if existing is None:
                assumptions["assumptions"].append(
                    {
                        "id": _next_assumption_id(assumptions["assumptions"]),
                        "from_question": item["id"],
                        "text": item["default_if_skipped"],
                        "basis": "使用者跳過問題，採用工程代理預設",
                        "affects": [],
                        "status": "active",
                        "overridden_by": None,
                    }
                )
        elif answer is not None:
            item["status"] = "answered"
            item["answer"] = answer
        else:
            raise ValueError("必須提供 answer 或 skip")
        changed.append(item["id"])
    dump_yaml(questions_path, validated)
    dump_yaml(assumptions_path, assumptions)
    return changed
