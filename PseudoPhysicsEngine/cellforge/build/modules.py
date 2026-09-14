"""Load and validate parametric modules."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
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


def module_import_name(part: str) -> str:
    normalized = part.replace("\\", "/")
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    return normalized.strip("/").replace("/", ".")


def load_part(part: str) -> ModuleType:
    return importlib.import_module(module_import_name(part))


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
            raise ValueError(f"Vendor item not found: {instance.vendor}")
        if item.get("kind") != "robot":
            raise ValueError(f"Vendor asset {instance.vendor} needs a supported CAD adapter")
        python_module = load_part("library/robot_stub.py")
        definition = python_module.MODULE
        params = {
            "reach_mm": item.get("limits", {}).get("reach_mm", 905),
            "name": instance.id,
            **instance.params,
        }
        validate_params(definition, params)
        assembly = python_module.build(params)
        return BuiltModule(instance, definition, assembly, f"vendor:{instance.vendor}")
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
    return BuiltModule(instance, definition, assembly, instance.part)
