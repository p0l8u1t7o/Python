"""Node type interface and registry.

The point of this package is that adding a node type does not require editing
the engine. A type registers under a key, the graph names the key, and
:mod:`apps.workflows.engine` calls whatever comes back. Nothing in the core
branches on node type.

A registry rather than an ``if/elif`` chain, for the same reason the cost
models use one: the set is explicitly meant to grow from outside, and the
console builds its palette and its parameter forms by *reading* the registry
rather than by hard-coding a parallel copy that then drifts.

Each type declares its own parameter schema and its output handles. The editor
renders the form from the schema, so a new node type appears in the UI with a
working parameter panel and nobody touches the frontend.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from apps.core.errors import ValidationError


class UnknownNodeType(ValidationError):
    """Raised when a graph names a node type that is not registered."""

    def __init__(self, key: str, available: list[str] | None = None) -> None:
        super().__init__(
            f"Unknown node type '{key}'",
            code="unknown_node_type",
            details={"node_type": key, "available": sorted(available or [])},
        )


# --------------------------------------------------------------------------
# Parameter declaration
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Param:
    """One field in a node's parameter form.

    Deliberately a small closed vocabulary rather than full JSON Schema. The
    editor has to render every one of these, and a type it cannot render is a
    node nobody can configure - so the set of kinds is exactly what the editor
    supports, and adding a kind is a deliberate act on both sides.
    """

    key: str
    label: str
    #: text | number | boolean | select | device | metric | command | workflow | duration
    kind: str = "text"
    required: bool = False
    default: Any = None
    help_text: str = ""
    #: For ``select``: ``[{"value": ..., "label": ...}]``.
    options: list[dict[str, Any]] = field(default_factory=list)
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "default": self.default,
            "help_text": self.help_text,
            "options": list(self.options),
            "unit": self.unit,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True, slots=True)
class Handle:
    """One outgoing connection point."""

    key: str
    label: str
    #: Drawn in a colour that says what it means, so a branch is readable
    #: without opening it.
    tone: str = "neutral"  # neutral | ok | warn | critical


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------
@dataclass
class NodeContext:
    """Everything a node is allowed to see, and the ways it may act.

    Passed in rather than imported so a node cannot reach past this surface.
    In particular ``dry_run`` is checked *here*, not by each node: a node type
    that forgot the check would send real commands from a test run, and that
    mistake must not be possible to make one node at a time.
    """

    run: Any
    token: Any
    node: dict[str, Any]
    organization: Any
    site: Any
    #: Mutable run-scoped values.
    context: dict[str, Any]
    moment: dt.datetime
    dry_run: bool
    #: ``log(message, *, level=..., detail=...)``
    log: Callable[..., None]

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.node.get("params") or {})

    def param(self, key: str, default: Any = None) -> Any:
        value = self.params.get(key)
        return default if value in (None, "") else value


@dataclass(frozen=True, slots=True)
class Result:
    """What a node did, and where the token goes next.

    ``branch`` names an output handle; the engine follows every edge leaving
    that handle, which is how a fork happens - two edges from one handle means
    two tokens.

    ``wait_until`` parks the token. The engine puts the run to sleep rather
    than spinning, so a thirty-second timer costs nothing.

    ``goto`` overrides edge following entirely, for ``jump``.
    """

    branch: str = "out"
    message: str = ""
    #: ``debug`` entries are kept only for test runs. A loop that ticks once a
    #: second would otherwise write three rows a second forever, and a log
    #: nobody can scroll is a log nobody reads.
    level: str = "info"
    detail: dict[str, Any] = field(default_factory=dict)
    wait_until: dt.datetime | None = None
    goto: str | None = None
    #: Updates merged into the token's own state before it moves.
    token_state: dict[str, Any] | None = None
    #: Updates merged into the run-wide context.
    context: dict[str, Any] | None = None
    #: End this token without following any edge.
    stop: bool = False


class NodeType(Protocol):
    key: str
    label: str
    description: str
    #: Grouping in the editor palette.
    category: str
    #: Lucide icon name the console maps to a component.
    icon: str
    params: list[Param]
    handles: list[Handle]

    def execute(self, ctx: NodeContext) -> Result: ...


_REGISTRY: dict[str, NodeType] = {}


def register(node_type: NodeType) -> NodeType:
    """Add a node type. Duplicate keys are a programming error, not a merge."""
    if node_type.key in _REGISTRY:
        raise RuntimeError(f"Node type '{node_type.key}' is already registered")
    _REGISTRY[node_type.key] = node_type
    return node_type


def get(key: str) -> NodeType:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownNodeType(key, list(_REGISTRY)) from None


def all_types() -> list[NodeType]:
    return sorted(_REGISTRY.values(), key=lambda t: (t.category, t.label))


def catalogue() -> list[dict[str, Any]]:
    """The palette, as the editor consumes it.

    The console builds both its node list and its parameter forms from this, so
    a new node type shows up in the UI with a working form and no frontend
    change.
    """
    return [
        {
            "key": t.key,
            "label": t.label,
            "description": t.description,
            "category": t.category,
            "icon": t.icon,
            "params": [p.as_dict() for p in t.params],
            "handles": [
                {"key": h.key, "label": h.label, "tone": h.tone} for h in t.handles
            ],
        }
        for t in all_types()
    ]
