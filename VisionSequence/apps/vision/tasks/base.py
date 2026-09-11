"""檢測任務定義表的核心資料結構與註冊表。"""

from __future__ import annotations

import dataclasses

from dataclasses import dataclass, field
from typing import Any, Callable

from apps.core.errors import ValidationError
from apps.vision.tools import base as tools


@dataclass(frozen=True, slots=True)
class PortRef:
    role: str
    port: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "port": self.port}


@dataclass(frozen=True, slots=True)
class EdgeSpec:
    source_role: str
    source_port: str
    target_role: str
    target_port: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source_role": self.source_role,
            "source_port": self.source_port,
            "target_role": self.target_role,
            "target_port": self.target_port,
        }


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label: str
    kind: str
    role: str | None = None
    param: str | None = None
    required: bool = False
    default: Any = None
    help_text: str = ""
    unit: str = ""
    options: tuple[dict[str, Any], ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    shapes: tuple[str, ...] = ()
    accept: str = ""
    read: Callable[[dict[str, Any]], Any] | None = None
    write: Callable[[dict[str, Any], Any], None] | None = None
    visible_when: dict[str, Any] | None = None
    source_type: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "role": self.role,
            "param": self.param,
            "required": self.required,
            "default": self.default,
            "help_text": self.help_text,
            "unit": self.unit,
            "options": [dict(o) for o in self.options],
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "shapes": list(self.shapes),
            "accept": self.accept,
            "visible_when": self.visible_when,
            "source_type": self.source_type,
        }


BuildHook = Callable[["TaskDefinition", dict[str, Any], dict[str, Any]], tuple[list[dict[str, Any]], list[dict[str, Any]]]]
EdgesHook = Callable[["TaskDefinition", dict[str, Any]], tuple[EdgeSpec, ...]]


@dataclass(slots=True)
class TaskLayout:
    """同一種類各方式的實際節點、接線與讀值；不增加圖格式欄位。"""

    steps: dict[str, tuple[str, dict[str, Any]]]
    edges: tuple[EdgeSpec, ...] = ()
    inputs: tuple[PortRef, ...] = ()
    outputs: tuple[PortRef, ...] = ()
    pass_port: PortRef | None = None
    value_port: PortRef | None = None
    verdict_role: str = ""
    locator_roles: tuple[str, ...] = ()
    summary_expression: str = ""
    summary_inputs: tuple[PortRef, ...] = ()
    external: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    kind: str
    version: int
    label: str
    help_text: str
    roles: dict[str, str]
    internal_edges: tuple[EdgeSpec, ...] = ()
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    public_inputs: tuple[PortRef, ...] = ()
    public_outputs: tuple[PortRef, ...] = ()
    pass_port: PortRef | None = None
    build_hook: BuildHook | None = None
    edges_hook: EdgesHook | None = None
    layout_hook: Callable[[dict[str, Any]], TaskLayout] | None = None
    read_hook: Callable[[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]], None] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "version": self.version,
            "label": self.label,
            "help_text": self.help_text,
            "roles": dict(self.roles),
            "internal_edges": [e.as_dict() for e in self.internal_edges],
            "fields": [f.as_dict() for f in self.fields.values()],
            "public_inputs": [p.as_dict() for p in self.public_inputs],
            "public_outputs": [p.as_dict() for p in self.public_outputs],
            "pass_port": None if self.pass_port is None else self.pass_port.as_dict(),
        }

    def default_params(self, role: str) -> dict[str, Any]:
        tool = tools.get(self.roles[role])
        return {p.key: p.default for p in tool.params if p.default is not None}

    def edges_for(self, fields: dict[str, Any]) -> tuple[EdgeSpec, ...]:
        if self.layout_hook is not None:
            return self.layout_hook(fields).edges
        if self.edges_hook is not None:
            return self.edges_hook(self, fields)
        return self.internal_edges

    def inputs_for(self, fields: dict[str, Any]) -> tuple[PortRef, ...]:
        return self.layout_hook(fields).inputs if self.layout_hook else self.public_inputs

    def build(self, task: dict[str, Any], ctx: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if self.layout_hook is not None:
            fields = task_fields(task, self)
            if fields.get("unit") == "mm" and not fields.get("calibration"):
                raise ValidationError("Millimetre mode needs a calibration", code="missing_calibration")
            for key, spec in self.fields.items():
                value = fields.get(key)
                if spec.kind == "roi" and isinstance(value, dict) and spec.shapes and value.get("shape") not in spec.shapes:
                    raise ValidationError(f"Unsupported region shape for '{key}'", code="invalid_task_field")
            layout = self.layout_hook(fields)
            task_id = str(task.get("task_id") or task.get("id") or self.kind)
            required = bool(task.get("required", fields.get("required", True)))
            nodes = []
            for role, (tool_key, supplied) in layout.steps.items():
                params = {p.key: p.default for p in tools.get(tool_key).params if p.default is not None}
                params.update(supplied)
                nodes.append(task_node(task_id, role, tool_key, params, self.kind, self.version, required))
            links = [edge(f"{task_id}_{e.source_role}", e.source_port, f"{task_id}_{e.target_role}", e.target_port) for e in layout.edges]
            links.extend(edge(e["source"], e["port"], f"{task_id}_{e['role']}", e["input"]) for e in layout.external)
            return nodes, links
        if self.build_hook is not None:
            return self.build_hook(self, task, ctx)
        fields = task_fields(task, self)
        task_id = str(task.get("task_id") or task.get("id") or self.kind)
        required = bool(task.get("required", fields.get("required", True)))
        nodes: list[dict[str, Any]] = []
        for role, tool_key in self.roles.items():
            params = self.default_params(role)
            for spec in self.fields.values():
                if spec.role == role and spec.param:
                    if spec.write is not None:
                        spec.write(params, fields.get(spec.key, spec.default))
                    else:
                        params[spec.param] = fields.get(spec.key, spec.default)
            nodes.append(task_node(task_id, role, tool_key, params, self.kind, self.version, required))
        edges = [edge(f"{task_id}_{e.source_role}", e.source_port, f"{task_id}_{e.target_role}", e.target_port) for e in self.edges_for(fields)]
        return nodes, edges


_REGISTRY: dict[tuple[str, int], TaskDefinition] = {}


def register(definition: TaskDefinition) -> TaskDefinition:
    key = (definition.kind, definition.version)
    if key in _REGISTRY:
        raise RuntimeError(f"Task definition '{definition.kind}' v{definition.version} is already registered")
    # 說明文字：罐頭句換成「什麼時候用它」、沒有說明的欄位補一句（tasks/help.py；工具帶的說明不動）
    from apps.vision.tasks import help as task_help  # 延後 import：help 只有字典，避免循環

    definition = dataclasses.replace(
        definition,
        help_text=task_help.kind_help(definition.kind, definition.help_text),
        fields={k: dataclasses.replace(f, help_text=task_help.field_help(definition.kind, k, f.help_text)) for k, f in definition.fields.items()},
    )
    for role, tool_key in definition.roles.items():
        if not role or not tool_key:
            raise RuntimeError("Task roles must have a role and a tool key")
    _REGISTRY[key] = definition
    return definition


def get(kind: str, version: int | None = None) -> TaskDefinition:
    matches = [d for (k, _v), d in _REGISTRY.items() if k == kind]
    if version is None:
        if matches:
            return max(matches, key=lambda d: d.version)
    else:
        found = _REGISTRY.get((kind, int(version)))
        if found is not None:
            return found
    raise ValidationError(f"Unknown inspection task kind '{kind}'", code="unknown_task_kind")


def all() -> list[TaskDefinition]:  # noqa: A001 - 公開 API 對應派工規格
    return sorted(_REGISTRY.values(), key=lambda d: (d.kind, d.version))


def task_fields(task: dict[str, Any], definition: TaskDefinition) -> dict[str, Any]:
    raw = task.get("fields")
    values = dict(raw) if isinstance(raw, dict) else {}
    for key, spec in definition.fields.items():
        if key in task and key not in values:
            values[key] = task[key]
        if key not in values:
            values[key] = spec.default
        visible = not spec.visible_when or not any(values.get(k, definition.fields[k].default) not in (v if isinstance(v, list) else [v]) for k, v in spec.visible_when.items())
        if visible and spec.required and values.get(key) in (None, ""):
            raise ValidationError(f"Field '{key}' is required", code="task_field_required", details={"field": key})
    return values


#: 任務定義在角色參數裡用這個保留鍵指定「輸出埠 → 具名輸出名稱」，task_node() 搬到 node.interface（params 不留平台鍵）
ALIAS_KEY = "_alias"


def task_node(task_id: str, role: str, tool_key: str, params: dict[str, Any], kind: str, version: int, required: bool) -> dict[str, Any]:
    params = dict(params)
    aliases = params.pop(ALIAS_KEY, None)
    node: dict[str, Any] = {
        "id": f"{task_id}_{role}",
        "type": tool_key,
        "params": params,
        "meta": {"inspect": {"task_id": task_id, "role": role, "kind": kind, "schema_version": version, "required": bool(required)}},
    }
    if isinstance(aliases, dict):
        for port, name in aliases.items():
            tools.set_output_alias(node, str(port), name)
    return node


def edge(source: str, source_port: str, target: str, target_port: str) -> dict[str, str]:
    return {
        "id": f"{source}.{source_port}->{target}.{target_port}",
        "source": source,
        "source_handle": source_port,
        "target": target,
        "target_handle": target_port,
    }
