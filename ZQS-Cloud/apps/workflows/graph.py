"""Validating the drawing before anything tries to run it.

Checked on save, not on start. A graph that cannot execute is a mistake the
operator made while drawing, and the moment to say so is while they are looking
at the canvas - not at 3am when something triggers it.

What is *not* checked here: whether the graph terminates. A loop built from
``jump`` is a legitimate thing to draw - "hold this setpoint until the
condition clears" is a loop - so the engine's step budget is the answer to
runaways, not a refusal to save.
"""

from __future__ import annotations

from typing import Any

from apps.core.errors import ValidationError
from apps.workflows import nodes

MAX_NODES = 200
MAX_EDGES = 400


class GraphError(ValidationError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, code="invalid_graph", details=details)


def validate_graph(graph: Any) -> dict:
    """Check the shape and return it normalised.

    Returns the graph rather than mutating, so a caller can validate a payload
    without committing to it.
    """
    if not isinstance(graph, dict):
        raise GraphError("The graph must be an object with 'nodes' and 'edges'")

    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges") or []
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise GraphError("'nodes' and 'edges' must both be lists")
    if len(raw_nodes) > MAX_NODES:
        raise GraphError(
            f"A workflow may have at most {MAX_NODES} nodes", node_count=len(raw_nodes)
        )
    if len(raw_edges) > MAX_EDGES:
        raise GraphError(
            f"A workflow may have at most {MAX_EDGES} edges", edge_count=len(raw_edges)
        )

    seen: set[str] = set()
    for node in raw_nodes:
        if not isinstance(node, dict):
            raise GraphError("Every node must be an object")
        node_id = str(node.get("id") or "")
        if not node_id:
            raise GraphError("Every node needs an id")
        if node_id in seen:
            raise GraphError(f"Duplicate node id '{node_id}'", node_id=node_id)
        seen.add(node_id)

        # Raises UnknownNodeType, which names the registered keys - so the
        # error tells the author what they could have written instead.
        nodes.get(str(node.get("type") or ""))

    decorations = {
        str(node.get("id"))
        for node in raw_nodes
        if isinstance(node, dict) and str(node.get("type")) in ("note", "arrow")
    }

    for edge in raw_edges:
        if not isinstance(edge, dict):
            raise GraphError("Every edge must be an object")
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in seen:
            raise GraphError(f"Edge starts at unknown node '{source}'", node_id=source)
        if target not in seen:
            raise GraphError(f"Edge ends at unknown node '{target}'", node_id=target)
        # Notes and arrows are decoration. A dashed edge *from* a note is an
        # annotation and is allowed - the engine never executes decoration, so
        # the edge is never followed. An edge *into* one would look like flow
        # on the canvas while the engine treats it as a dead end - the drawing
        # and the behaviour must not be allowed to disagree.
        if target in decorations:
            raise GraphError(
                "Nothing can be connected into a note or arrow", node_id=target
            )

    # Jump targets are checked here rather than at run time for the same reason
    # as everything else: a typo should surface on the canvas.
    for node in raw_nodes:
        if str(node.get("type")) != "jump":
            continue
        target = str((node.get("params") or {}).get("target") or "")
        if target and target not in seen:
            raise GraphError(
                f"Jump node '{node.get('id')}' points at '{target}', which does "
                f"not exist",
                node_id=str(node.get("id")),
                target=target,
            )

    runnable = [
        n for n in raw_nodes if str(n.get("type")) not in ("note", "arrow")
    ]
    if runnable and not entry_nodes(graph):
        raise GraphError(
            "Nothing would run: add a Start node, or a node with no incoming "
            "connection for the run to begin at"
        )

    return {"nodes": raw_nodes, "edges": raw_edges}


def entry_nodes(graph: Any) -> list[str]:
    """Where a run places its first tokens.

    Explicit ``start`` nodes if there are any. Otherwise every node with
    nothing pointing at it - so a quick three-node sketch runs without the
    author having to know that a Start node is a thing.

    Several entry points means several branches running at once. That is the
    parallelism the operator asked for, expressed by drawing rather than by a
    setting.
    """
    if not isinstance(graph, dict):
        return []
    node_list = graph.get("nodes") or []
    ids = [str(n.get("id")) for n in node_list if isinstance(n, dict) and n.get("id")]
    if not ids:
        return []

    starts = [
        str(n["id"])
        for n in node_list
        if isinstance(n, dict) and str(n.get("type")) == "start" and n.get("id")
    ]
    if starts:
        return starts

    # Decoration is not flow: notes and arrows have no incoming edges by
    # definition, and placing a token on one would run scenery.
    notes = {
        str(n.get("id"))
        for n in node_list
        if isinstance(n, dict) and str(n.get("type")) in ("note", "arrow")
    }
    # An annotation arrow from a note is not flow: being pointed at by one
    # must not stop a node from being an entry point.
    targeted = {
        str(edge.get("target"))
        for edge in graph.get("edges") or []
        if isinstance(edge, dict)
        and edge.get("target")
        and str(edge.get("source")) not in notes
    }
    return [
        node_id for node_id in ids if node_id not in targeted and node_id not in notes
    ]
