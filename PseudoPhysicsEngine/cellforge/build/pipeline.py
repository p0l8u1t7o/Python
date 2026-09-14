"""CellForge L0/L1 build pipeline."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import cadquery as cq

from cellforge.checks import run_checks
from cellforge.schema import Checks, Timeline, VendorManifest
from cellforge.validation import validate_project
from cellforge.versioning import snapshot_build
from cellforge.yamlio import load_yaml

from .glb import export_glb
from .modules import BuiltModule, build_module
from .stepio import StepValidationError, export_and_validate_step
from .timeline import expand_sequence
from .transforms import cadquery_location


class BuildError(RuntimeError):
    pass


def build_project(project_dir: Path, level: str = "L0") -> dict:
    level = level.upper()
    if level not in {"L0", "L1"}:
        raise BuildError("Build level must be L0 or L1")
    project, workpiece, cell, process = validate_project(project_dir)
    vendor_manifest = VendorManifest.model_validate(
        load_yaml(project_dir / "vendor" / "manifest.yaml") or {"vendors": []}
    )
    vendor_items = {item.id: item.model_dump(mode="json") for item in vendor_manifest.vendors}
    station_by_module = {
        module_id: station.id for station in process.stations for module_id in station.modules
    }
    modules: list[BuiltModule] = []
    assembly = cq.Assembly(name="CellForge")
    for machine in cell.machines:
        for instance in machine.modules:
            built = build_module(instance, vendor_items)
            built.station = station_by_module.get(instance.id)
            modules.append(built)
            assembly.add(
                built.assembly,
                name=instance.id,
                loc=cadquery_location(instance.pose.xyz, instance.pose.rpy_deg),
            )
    build_dir = project_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            inspection, fallback = export_and_validate_step(
                assembly, build_dir / "scene.step", [module.instance.id for module in modules]
            )
    except StepValidationError as error:
        raise BuildError(str(error)) from error
    step_report = inspection.as_dict()
    step_report.update(
        {
            "expected_top_level_part_count": len(modules),
            "expected_names": [module.instance.id for module in modules],
            "name_match": True,
            "count_match": True,
            "xcaf_fallback_used": fallback,
        }
    )
    (build_dir / "step_validation.json").write_text(
        json.dumps(step_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    export_glb(modules, build_dir / "scene.glb")
    timeline = Timeline.model_validate(
        expand_sequence(project_dir / "animation" / "sequence.py", process)
    ).model_dump(mode="json")
    (build_dir / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checks = None
    if level == "L1":
        existing = [
            int(path.name[1:])
            for path in (project_dir / ".cellforge").glob("v*")
            if path.is_dir() and path.name[1:].isdigit()
        ]
        checks = Checks.model_validate(
            run_checks(
                cell, workpiece, process, timeline, max(existing, default=0) + 1, vendor_items
            )
        ).model_dump(mode="json")
        (build_dir / "checks.json").write_text(
            json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    elif (build_dir / "checks.json").exists():
        (build_dir / "checks.json").unlink()

    stations = "\n".join(
        f"- {station['id']}: {station.get('name', station['id'])} "
        f"({station['t0']:.1f}-{station['t1']:.1f}s)"
        for station in timeline["stations"]
    )
    risks = "No L1 checks requested."
    if checks:
        risks = (
            "\n".join(
                f"- [{item['severity'].upper()}] {item['id']}: {item.get('detail', '')}"
                for item in checks["items"]
                if item["severity"] in {"red", "yellow"}
            )
            or "- No red or yellow checks."
        )
    (build_dir / "render_brief.md").write_text(
        f"# {project.name} — {level} render brief\n\n{project.description}\n\n"
        f"## Stations\n{stations}\n\n## Red / yellow checks\n{risks}\n\n"
        "## Presentation guidance\nShow inferred geometry in amber, confirmed geometry in blue, "
        "and preserve engineering identifiers in labels.\n",
        encoding="utf-8",
    )
    output_names = [
        "scene.step",
        "scene.glb",
        "timeline.json",
        "step_validation.json",
        "render_brief.md",
    ]
    if checks:
        output_names.append("checks.json")
    version = snapshot_build(project_dir, output_names)
    return {
        "version": version,
        "level": level,
        "modules": len(modules),
        "duration_s": timeline["duration_s"],
        "step": step_report,
        "checks": checks["summary"] if checks else None,
        "outputs": [f"build/{name}" for name in output_names],
    }
