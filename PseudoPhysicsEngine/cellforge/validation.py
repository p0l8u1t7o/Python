"""Project validation entry point."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from cellforge.build.modules import build_module, load_part, project_parts, validate_params
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
from cellforge.schema.costing import Costing
from cellforge.schema.electrical import Electrical
from cellforge.schema.models import ModuleInstance
from cellforge.sim import SceneModel, build_parts
from cellforge.sim.scheduler import validate_process
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
    with project_parts(project_dir):
        return _validate_project(project_dir)


def _validate_project(project_dir: Path) -> tuple[Project, Workpiece, Cell, Process]:
    project = _parse(Project, project_dir / "project.yaml")
    workpiece = _parse(Workpiece, project_dir / "workpiece.yaml")
    cell = _parse(Cell, project_dir / "cell.yaml")
    process = _parse(Process, project_dir / "process.yaml")
    manifest = _parse(InputManifest, project_dir / "inputs" / "manifest.yaml")
    questions = _parse(Questions, project_dir / "analysis" / "questions.yaml")
    assumptions = _parse(Assumptions, project_dir / "analysis" / "assumptions.yaml")
    vendor_manifest = _parse(VendorManifest, project_dir / "vendor" / "manifest.yaml")
    costing = (
        _parse(Costing, project_dir / "costing.yaml")
        if (project_dir / "costing.yaml").is_file()
        else None
    )
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
    if costing is not None:
        unknown_modules = sorted(
            {rule.match.module for rule in costing.equipment if rule.match.module} - module_ids
        )
        if unknown_modules:
            raise ProjectValidationError(
                f"costing.yaml 的設備對應引用不存在的模組：{', '.join(unknown_modules)}"
            )
    if (project_dir / "electrical.yaml").is_file():
        _validate_electrical(project_dir, _parse(Electrical, project_dir / "electrical.yaml"), cell)
    vendor_items = {item.id: item.model_dump(mode="json") for item in vendor_manifest.vendors}
    for machine in cell.machines:
        for instance in machine.modules:
            _validate_module(instance, vendor_ids)
    _validate_vendor_files(project_dir, vendor_items)
    try:
        modules = [
            _describe_module(instance, vendor_items)
            for machine in cell.machines
            for instance in machine.modules
        ]
        parts = build_parts(workpiece, process, build_geometry=False)
        clash = sorted({part.id for part in parts} & (module_ids | {"system"}))
        if clash:
            raise ValueError(f"零件 id 不可與模組 id 相同：{', '.join(clash)}")
        scene = SceneModel(cell, modules, parts)
        validate_process(scene, process)
    except (ImportError, AttributeError, KeyError, ValueError) as error:
        raise ProjectValidationError(f"流程驗證失敗：{error}") from error
    sequence_path = project_dir / "animation" / "sequence.py"
    if not sequence_path.is_file():
        raise ProjectValidationError("缺少必要檔案：animation/sequence.py")
    _validate_project_parts(project_dir)
    return project, workpiece, cell, process


def _validate_electrical(project_dir: Path, electrical: Electrical, cell: Cell) -> None:
    """未定義的器件、端子、電位網、點位池或模組一律使驗證失敗；連通問題留給檢查。"""
    from cellforge.electrical import resolve_electrical

    resolved = resolve_electrical(electrical, cell)
    errors = list(resolved.reference_errors)
    logo = electrical.drawing.logo
    if logo is not None:
        path = (project_dir / logo).resolve()
        if not path.is_relative_to((project_dir / "drawing_templates").resolve()):
            errors.append(f"圖框 LOGO 必須放在案內 drawing_templates/：{logo}")
        elif not path.is_file():
            errors.append(f"圖框 LOGO 檔案不存在：{logo}")
        elif path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".svg"}:
            errors.append(f"圖框 LOGO 只接受 PNG、JPG 或 SVG：{logo}")
    if errors:
        raise ProjectValidationError("electrical.yaml 引用錯誤：" + "；".join(errors))


def placeholder_warnings(cell: Cell, project_dir: Path | None = None) -> list[str]:
    """Return one non-blocking warning for each placeholder module instance."""
    if project_dir is not None:
        with project_parts(project_dir):
            return placeholder_warnings(cell)
    messages: list[str] = []
    for machine in cell.machines:
        for instance in machine.modules:
            if instance.vendor or not instance.part:
                continue
            module = load_part(instance.part)
            factory = getattr(module, "module_definition", None)
            definition = factory(instance.params) if callable(factory) else module.MODULE
            if definition.meta.placeholder:
                messages.append(
                    f"模組 {instance.id} 使用 {definition.id}，仍為佔位幾何；"
                    "請在工程定案前替換為實際機構。"
                )
    return messages


def _validate_project_parts(project_dir: Path) -> None:
    from cellforge.part_check import check_project_parts

    try:
        results = check_project_parts(project_dir)
    except (ImportError, OSError, ValueError) as error:
        raise ProjectValidationError(f"案內 parts 載入失敗：{error}") from error
    failures = [
        f"{result.module_id} {item.index} {item.message}"
        for result in results
        for item in result.items
        if item.severity == "fail"
    ]
    if failures:
        raise ProjectValidationError("案內 parts 品質檢查失敗：" + "；".join(failures))


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


def _validate_vendor_files(project_dir: Path, vendor_items: dict[str, dict]) -> None:
    from cellforge.vendor_model import VendorModelError, verify_vendor_files

    for item in vendor_items.values():
        try:
            verify_vendor_files(project_dir, item)
        except VendorModelError as error:
            raise ProjectValidationError(str(error)) from error


def _describe_module(instance: ModuleInstance, vendor_items: dict[str, dict]):
    if instance.vendor:
        # 廠商模組的關節鏈來自原廠檔或近似 stub，與建置使用同一個轉接流程。
        built = build_module(instance, vendor_items)
        return SimpleNamespace(instance=instance, definition=built.definition, chain=built.chain)
    else:
        assert instance.part is not None
        module = load_part(instance.part)
        params = instance.params
    definition = getattr(module, "module_definition", lambda _params: module.MODULE)(params)
    chain_factory = getattr(module, "chain_from_params", None)
    chain = chain_factory(params) if callable(chain_factory) else None
    return SimpleNamespace(instance=instance, definition=definition, chain=chain)
