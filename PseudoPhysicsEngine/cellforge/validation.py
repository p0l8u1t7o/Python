"""Project validation entry point."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import ValidationError

from cellforge.build.modules import load_part, validate_params
from cellforge.schema import (
    Assumptions,
    Cell,
    InputManifest,
    Process,
    Project,
    Questions,
    VendorManifest,
    Workpiece,
)
from cellforge.schema.models import ModuleInstance
from cellforge.yamlio import load_yaml


class ProjectValidationError(RuntimeError):
    pass


def _parse(model, path: Path):
    if not path.is_file():
        raise ProjectValidationError(f"缺少必要檔案：{path.name}")
    try:
        return model.model_validate(load_yaml(path))
    except ValidationError as error:
        raise ProjectValidationError(f"{path.name} 格式錯誤：{error}") from error


def validate_project(project_dir: Path) -> tuple[Project, Workpiece, Cell, Process]:
    project = _parse(Project, project_dir / "project.yaml")
    workpiece = _parse(Workpiece, project_dir / "workpiece.yaml")
    cell = _parse(Cell, project_dir / "cell.yaml")
    process = _parse(Process, project_dir / "process.yaml")
    manifest = _parse(InputManifest, project_dir / "inputs" / "manifest.yaml")
    questions = _parse(Questions, project_dir / "analysis" / "questions.yaml")
    assumptions = _parse(Assumptions, project_dir / "analysis" / "assumptions.yaml")
    vendor_manifest = _parse(VendorManifest, project_dir / "vendor" / "manifest.yaml")
    vendor_ids = {item.id for item in vendor_manifest.vendors}
    _validate_unique_ids("問題", [item.id for item in questions.questions])
    _validate_unique_ids("假設", [item.id for item in assumptions.assumptions])
    _validate_unique_ids("vendor", [item.id for item in vendor_manifest.vendors])
    _validate_manifest(project_dir, manifest)
    module_ids = {item.id for machine in cell.machines for item in machine.modules}
    referenced = {item for station in process.stations for item in station.modules}
    unknown = sorted(referenced - module_ids)
    if unknown:
        raise ProjectValidationError(f"站別引用不存在的模組：{', '.join(unknown)}")
    for machine in cell.machines:
        for instance in machine.modules:
            _validate_module(instance, vendor_ids)
    sequence_path = project_dir / "animation" / "sequence.py"
    if not sequence_path.is_file():
        raise ProjectValidationError("缺少必要檔案：animation/sequence.py")
    return project, workpiece, cell, process


def _validate_unique_ids(kind: str, ids: list[str]) -> None:
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ProjectValidationError(f"{kind} id 重複：{', '.join(duplicates)}")


def _validate_manifest(project_dir: Path, manifest: InputManifest) -> None:
    root = project_dir.resolve()
    for item in manifest.files:
        path = (project_dir / item.path).resolve()
        if root not in path.parents:
            raise ProjectValidationError(f"輸入路徑超出案子目錄：{item.path}")
        if not path.is_file():
            raise ProjectValidationError(f"manifest 指向不存在的檔案：{item.path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest.lower() != item.sha256.lower():
            raise ProjectValidationError(f"輸入檔案 SHA-256 不符：{item.path}")


def _validate_module(instance: ModuleInstance, vendor_ids: set[str]) -> None:
    if instance.vendor:
        if instance.vendor not in vendor_ids:
            raise ProjectValidationError(
                f"模組 {instance.id} 引用不存在的 vendor：{instance.vendor}"
            )
        return
    assert instance.part is not None
    try:
        module = load_part(instance.part)
        definition = module.MODULE
        validate_params(definition, instance.params)
    except (ImportError, AttributeError, ValueError) as error:
        raise ProjectValidationError(f"模組 {instance.id} 驗證失敗：{error}") from error
