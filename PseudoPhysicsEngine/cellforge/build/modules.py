"""Load and validate parametric modules."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import cadquery as cq
from jsonschema import Draft202012Validator

from cellforge.schema import ModuleDef
from cellforge.schema.models import ModuleInstance


@dataclass(slots=True)
class BuiltModule:
    instance: ModuleInstance
    definition: ModuleDef
    assembly: cq.Assembly
    source: str
    station: str | None = None
    chain: Any | None = None
    module_file: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    # 幾何與運動鏈的實際來源：library／project-part／vendor-urdf／vendor-static／approximated-stub。
    model_source: str = ""
    approximated: bool = False
    warnings: list[str] = field(default_factory=list)


# 案內 parts/ 模組以檔案路徑相對於此根目錄載入；建置時指向凍結後的來源目錄。
_project_root: ContextVar[Path | None] = ContextVar("cellforge_project_root", default=None)


@contextmanager
def project_parts(root: Path) -> Iterator[None]:
    token = _project_root.set(root.resolve())
    try:
        yield
    finally:
        _project_root.reset(token)


@contextmanager
def fresh_library_modules() -> Iterator[None]:
    """讓建置從磁碟重新載入 library 子模組，避免長駐程序沿用修改前的程式碼。"""
    for name in [name for name in sys.modules if name.startswith("library.")]:
        del sys.modules[name]
    importlib.invalidate_caches()
    yield


def module_import_name(part: str) -> str:
    normalized = part.replace("\\", "/")
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    return normalized.strip("/").replace("/", ".")


def load_part(part: str) -> ModuleType:
    normalized = part.replace("\\", "/").strip("/")
    if not normalized.startswith("library/"):
        root = _project_root.get() or Path.cwd().resolve()
        path = (root / normalized).resolve()
        if root in path.parents and path.is_file():
            return _load_project_file(path)
        if normalized.startswith("parts/"):
            raise ImportError(f"找不到案內模組檔：{normalized}（案子目錄：{root}）")
    return importlib.import_module(module_import_name(normalized))


def _load_project_file(path: Path) -> ModuleType:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    name = f"_cellforge_project_part_{path.stem}_{digest}"
    loaded = sys.modules.get(name)
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"無法載入案內模組檔：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def validate_params(definition: ModuleDef, params: dict[str, Any]) -> None:
    schema = definition.params_schema or {"type": "object"}
    errors = sorted(Draft202012Validator(schema).iter_errors(params), key=lambda error: error.path)
    if errors:
        details = "; ".join(error.message for error in errors)
        raise ValueError(f"模組 {definition.id} 的 params 不符合 schema：{details}")


def build_module(
    instance: ModuleInstance, vendor_items: dict[str, dict[str, Any]] | None = None
) -> BuiltModule:
    if instance.vendor:
        item = (vendor_items or {}).get(instance.vendor)
        if not item:
            raise ValueError(f"找不到 vendor 條目：{instance.vendor}")
        if item.get("approximated", False):
            return _approximated_robot(instance, item)
        return _vendor_module(instance, item)
    assert instance.part is not None
    python_module = load_part(instance.part)
    definition = getattr(python_module, "MODULE", None)
    builder = getattr(python_module, "build", None)
    if not isinstance(definition, ModuleDef) or not callable(builder):
        raise ValueError(f"{instance.part} 必須匯出 MODULE 與 build(params)")
    validate_params(definition, instance.params)
    assembly = builder(dict(instance.params))
    if not isinstance(assembly, cq.Assembly):
        raise ValueError(f"{instance.part}.build() 必須回傳 cq.Assembly")
    dynamic_definition = getattr(python_module, "module_definition", lambda _p: definition)(
        instance.params
    )
    chain_factory = getattr(python_module, "chain_from_params", None)
    chain = chain_factory(instance.params) if callable(chain_factory) else None
    module_file = instance.part.replace("\\", "/")
    approximated = dynamic_definition.meta.approximated
    return BuiltModule(
        instance,
        dynamic_definition,
        assembly,
        instance.part,
        chain=chain,
        module_file=module_file,
        params=dict(instance.params),
        model_source="library" if module_file.startswith("library/") else "project-part",
        approximated=approximated,
        warnings=[_approximated_warning(instance.id, module_file)] if approximated else [],
    )


def _approximated_warning(instance_id: str, basis: str) -> str:
    return (
        f"模組 {instance_id} 為型錄尺寸近似（approximated stub，{basis}），"
        "外形、關節配置與限制都不是原廠模型"
    )


def _approximated_robot(instance: ModuleInstance, item: dict[str, Any]) -> BuiltModule:
    """取不到原廠檔時的型錄尺寸近似；結果處處標示 approximated，不可視為真機驗證。"""

    if item.get("kind") != "robot":
        raise ValueError(
            f"vendor 條目 {instance.vendor} 標示 approximated，但只有手臂可以用參數化近似"
        )
    python_module = load_part("library/robot_stub.py")
    definition = python_module.MODULE
    params = {
        "reach_mm": item.get("limits", {}).get("reach_mm", 905),
        "payload_kg": item.get("limits", {}).get("payload_kg", 7),
        "name": instance.id,
        **instance.params,
    }
    validate_params(definition, params)
    assembly = python_module.build(params)
    dynamic_definition = python_module.module_definition(params)
    return BuiltModule(
        instance,
        dynamic_definition,
        assembly,
        f"vendor:{instance.vendor}",
        chain=python_module.chain_from_params(params),
        module_file="library/robot_stub.py",
        params=params,
        model_source=f"approximated-stub:{instance.vendor}",
        approximated=True,
        warnings=[_approximated_warning(instance.id, f"vendor {instance.vendor}")],
    )


def _vendor_module(instance: ModuleInstance, item: dict[str, Any]) -> BuiltModule:
    from cellforge.module_cache import default_module_cache_root
    from cellforge.vendor_model import VendorModelError, build_vendor_model, verify_vendor_files

    root = _project_root.get() or Path.cwd().resolve()
    try:
        verify_vendor_files(root, item)
        model = build_vendor_model(
            item,
            {"name": instance.id, **instance.params},
            root,
            cache_root=default_module_cache_root(),
            load_tool=load_part,
        )
    except VendorModelError as error:
        raise ValueError(f"模組 {instance.id}：{error}") from error
    return BuiltModule(
        instance,
        model.definition,
        model.assembly,
        f"vendor:{instance.vendor}",
        chain=model.chain,
        module_file=str(item.get("files", {}).get("urdf") or next(iter(item["files"].values()))),
        params=model.params,
        model_source=model.model_source,
        warnings=[f"模組 {instance.id}：{message}" for message in model.warnings],
    )
