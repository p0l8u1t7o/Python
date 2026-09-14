"""Generate JSON Schema files used by the frontend and agents."""

from __future__ import annotations

import json
from pathlib import Path

from .models import SCHEMAS


def export_json_schemas(target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for name, model in SCHEMAS.items():
        output = target / f"{name}.schema.json"
        output.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        outputs.append(output)
    return outputs
