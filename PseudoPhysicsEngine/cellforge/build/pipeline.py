"""CellForge L0/L1 build pipeline."""

from __future__ import annotations

import json
import os
import warnings
from datetime import datetime
from pathlib import Path

import cadquery as cq
import numpy as np

from cellforge.checks import run_checks
from cellforge.project import source_root
from cellforge.schema import Checks, Timeline, VendorManifest
from cellforge.sim import SceneModel, build_parts
from cellforge.validation import validate_project
from cellforge.version_store import (
    BUILD_JOB_ENV,
    BUILD_ORIGIN_ENV,
    StagedBuild,
    VersionPublishError,
    commit_version,
    engine_info,
    expanded_params,
    publish,
    schema_fingerprint,
    source_policy,
    stage_build,
    verify_library_unchanged,
    verify_outputs,
    write_manifest,
)
from cellforge.versioning import MANIFEST_NAME
from cellforge.yamlio import load_yaml

from .glb import _assembly_meshes, export_glb
from .modules import BuiltModule, build_module, fresh_library_modules, project_parts
from .stepio import StepValidationError, export_and_validate_step
from .timeline import expand_sequence
from .transforms import cadquery_location, matrix_from_pose


class BuildError(RuntimeError):
    pass


FLOOR_TOLERANCE_MM = 5.0


def _has_valid_module_mount(module: BuiltModule, modules: list[BuiltModule]) -> bool:
    reference = (module.instance.mount or "").strip()
    if not reference or reference == "floor":
        return False
    module_id, separator, frame_name = reference.partition(".")
    targets = {item.instance.id: item for item in modules if item.instance.id != module.instance.id}
    target = targets.get(module_id)
    return target is not None and (not separator or frame_name in target.definition.frames)


def _module_floor_warnings(modules: list[BuiltModule]) -> list[str]:
    """Report fixed module roots that visibly float above or penetrate the plant floor."""

    messages: list[str] = []
    for module in modules:
        transform = matrix_from_pose(module.instance.pose.xyz, module.instance.pose.rpy_deg)
        lowest = np.inf
        for _name, mesh in _assembly_meshes(module.assembly):
            world = mesh.vertices @ transform[:3, :3].T + transform[:3, 3]
            if len(world):
                lowest = min(lowest, float(world[:, 2].min()))
        if not np.isfinite(lowest):
            continue
        if lowest < -FLOOR_TOLERANCE_MM:
            messages.append(
                f"模組 {module.instance.id} 最低點 z={lowest:.1f} mm，低於地板超過 "
                f"{FLOOR_TOLERANCE_MM:g} mm；請修正 pose 或幾何。"
            )
        elif lowest > FLOOR_TOLERANCE_MM and not _has_valid_module_mount(module, modules):
            messages.append(
                f"模組 {module.instance.id} 最低點 z={lowest:.1f} mm，懸空超過 "
                f"{FLOOR_TOLERANCE_MM:g} mm；請補足落地結構或以 mount 指定承載模組／frame。"
            )
    return messages


def build_project(project_dir: Path, level: str = "L0") -> dict:
    """凍結工作區來源後在 staging 建置，驗證通過才原子發布為新的 ``.cellforge/vN``。"""

    level = level.upper()
    if level not in {"L0", "L1"}:
        raise BuildError("Build level must be L0 or L1")
    project_dir = project_dir.resolve()
    library_root = source_root() / "library"
    try:
        with stage_build(project_dir, library_root) as stage:
            with project_parts(stage.source_dir), fresh_library_modules():
                report, modules = _build_into(
                    stage.source_dir, stage.output_dir, level, stage.number
                )
            return _publish(stage, level, report, modules, library_root)
    except VersionPublishError as error:
        raise BuildError(str(error)) from error


def _publish(
    stage: StagedBuild,
    level: str,
    report: dict,
    modules: list[BuiltModule],
    library_root: Path,
) -> dict:
    expected_nodes = [module.instance.id for module in modules] + [
        part["id"] for part in report["parts"]
    ]
    artifacts = verify_outputs(stage.output_dir, level, stage.number, expected_nodes)
    verify_library_unchanged(stage, library_root)
    checks = report["checks"]
    if checks is None:
        engineering = {"status": "not_evaluated", "summary": None}
    else:
        status = "fail" if checks["red"] else "warning" if checks["yellow"] else "pass"
        engineering = {"status": status, "summary": dict(checks)}
    project = load_yaml(stage.source_dir / "project.yaml") or {}
    write_manifest(
        stage,
        {
            "version": stage.name,
            "number": stage.number,
            "created": datetime.now().astimezone(),
            "project_name": str(project.get("name", "")),
            "build": {
                "level": level,
                "status": "succeeded",
                "started": stage.started,
                "finished": datetime.now().astimezone(),
                "warnings": report["warnings"],
                "origin": os.environ.get(BUILD_ORIGIN_ENV) or "direct",
                "job_id": os.environ.get(BUILD_JOB_ENV) or None,
            },
            "engineering": engineering,
            "engine": engine_info(source_root()),
            "schema_fingerprint": schema_fingerprint(),
            "source_policy": source_policy(),
            "sources": stage.sources,
            "library": stage.library,
            "modules": [
                {
                    "id": module.instance.id,
                    "source": module.source,
                    "module_file": module.module_file,
                    "module_sha256": stage.module_file_sha256(module.module_file),
                    "params": module.params,
                    "expanded_params": expanded_params(
                        module.definition.params_schema, module.params
                    ),
                    "model_source": module.model_source,
                    "approximated": module.approximated,
                }
                for module in modules
            ],
            "parts": [
                {
                    **part,
                    "module_sha256": (
                        stage.module_file_sha256(part["module_file"])
                        if part.get("module_file")
                        else None
                    ),
                }
                for part in report["parts"]
            ],
            "artifacts": artifacts,
        },
    )
    target, publish_warnings = publish(stage)
    warnings = [*report["warnings"], *publish_warnings]
    if git_warning := commit_version(stage.project, stage.name):
        warnings.append(git_warning)
    return {
        **report,
        "version": stage.number,
        "version_id": stage.name,
        "manifest": f".cellforge/{target.name}/{MANIFEST_NAME}",
        "engineering_status": engineering["status"],
        "warnings": warnings,
    }


def _build_into(
    source_dir: Path, output_dir: Path, level: str, version_number: int
) -> tuple[dict, list[BuiltModule]]:
    """Build strictly from frozen sources into the staging output directory."""

    project, workpiece, cell, process = validate_project(source_dir)
    vendor_manifest = VendorManifest.model_validate(
        load_yaml(source_dir / "vendor" / "manifest.yaml") or {"vendors": []}
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
    built_parts = build_parts(workpiece, process)
    build_warnings = [
        *(message for part in built_parts for message in part.warnings),
        *(message for module in modules for message in module.warnings),
        *_module_floor_warnings(modules),
    ]
    scene = SceneModel(cell, modules, built_parts)
    for part in built_parts:
        assert part.assembly is not None
        assembly.add(part.assembly, name=part.id)
    expected_step_names = [module.instance.id for module in modules] + [
        part.id for part in built_parts
    ]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            inspection, fallback = export_and_validate_step(
                assembly, output_dir / "scene.step", expected_step_names
            )
    except StepValidationError as error:
        raise BuildError(str(error)) from error
    step_report = inspection.as_dict()
    step_report.update(
        {
            "expected_top_level_part_count": len(expected_step_names),
            "expected_names": expected_step_names,
            "name_match": True,
            "count_match": True,
            "xcaf_fallback_used": fallback,
        }
    )
    (output_dir / "step_validation.json").write_text(
        json.dumps(step_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    export_glb(modules, output_dir / "scene.glb", built_parts)
    timeline = Timeline.model_validate(
        expand_sequence(source_dir / "animation" / "sequence.py", process, scene)
    ).model_dump(mode="json")
    (output_dir / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checks = None
    if level == "L1":
        checks = Checks.model_validate(
            run_checks(
                cell,
                workpiece,
                process,
                timeline,
                version_number,
                vendor_items,
                scene=scene,
            )
        ).model_dump(mode="json")

    costing = None
    if (source_dir / "costing.yaml").is_file():
        from cellforge.costing import compute_costing
        from cellforge.schema.costing import Costing

        costing = {
            "version": version_number,
            **compute_costing(
                Costing.model_validate(load_yaml(source_dir / "costing.yaml")),
                cell,
                as_of=datetime.now().astimezone().date(),
            ),
        }
        (output_dir / "costing.json").write_text(
            json.dumps(costing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        build_warnings.extend(
            f"成本：{issue['message']}"
            for issue in costing["issues"]
            if issue["severity"] == "error"
        )

    electrical = None
    if (source_dir / "electrical.yaml").is_file():
        from cellforge.electrical import electrical_report
        from cellforge.schema.electrical import Electrical

        electrical = {
            "version": version_number,
            **electrical_report(
                Electrical.model_validate(load_yaml(source_dir / "electrical.yaml")),
                cell,
                scene=scene,
                process=process,
                costing=costing,
            ),
        }
        (output_dir / "electrical.json").write_text(
            json.dumps(electrical, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        build_warnings.extend(
            f"電控：{issue['message']}"
            for issue in electrical["issues"]
            if issue["severity"] == "warning"
        )
        if checks is not None:
            # 電控檢查併入同一份 L1 證據，前端與報告共用同一套紅黃綠。
            checks["items"].extend(electrical["checks"])
            checks["summary"] = {
                color: sum(item["severity"] == color for item in checks["items"])
                for color in ("red", "yellow", "green")
            }
            checks = Checks.model_validate(checks).model_dump(mode="json")
    if checks is not None:
        (output_dir / "checks.json").write_text(
            json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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
    warning_lines = "\n".join(f"- {message}" for message in build_warnings) or "- 無。"
    (output_dir / "render_brief.md").write_text(
        f"# {project.name} — {level} render brief\n\n{project.description}\n\n"
        f"## 建置警告\n{warning_lines}\n\n## Stations\n{stations}\n\n"
        f"## Red / yellow checks\n{risks}\n\n"
        "## Presentation guidance\nPreserve engineering part colors; mark inferred geometry "
        "with only a subtle amber outline or emissive rim, and preserve identifiers in labels.\n",
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
    if costing:
        output_names.append("costing.json")
    if electrical:
        output_names.append("electrical.json")
    report = {
        "level": level,
        "modules": len(modules),
        "parts": [
            {
                "id": part.id,
                "sku": part.sku.id if part.sku is not None else None,
                "module_file": part.part_file or None,
                "mass_kg": part.mass_kg,
            }
            for part in built_parts
        ],
        "warnings": build_warnings,
        "costing": (
            {
                "complete": costing["complete"],
                "currency": costing["currency"],
                "cost": costing["totals"]["cost"]["value"],
                "missing": len(costing["missing"]),
            }
            if costing
            else None
        ),
        "electrical": (
            {
                "devices": len(electrical["devices"]),
                "connections": len(electrical["connections"]),
                "io": len(electrical["io"]),
                **electrical["summary"],
            }
            if electrical
            else None
        ),
        "duration_s": timeline["duration_s"],
        "step": step_report,
        "checks": checks["summary"] if checks else None,
        "outputs": [f"build/{name}" for name in output_names],
    }
    return report, modules
