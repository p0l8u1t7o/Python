"""Build the articulated, named GLB hierarchy shared by simulation and the viewer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
import trimesh
from pygltflib import GLTF2, Node
from scipy.spatial.transform import Rotation

from cellforge.kinematics import Joint
from cellforge.schema import ModuleAxis, ModuleDef
from cellforge.sim.workpiece import BuiltWorkpiece

from .modules import BuiltModule
from .transforms import matrix_from_pose

MESH_LINEAR_TOLERANCE_MM = 1.0
MESH_ANGULAR_TOLERANCE_RAD = 0.2


@dataclass(slots=True)
class SceneItem:
    id: str
    assembly: cq.Assembly
    definition: ModuleDef
    transform: np.ndarray
    extras: dict[str, Any]
    fixed_joints: tuple[Joint, ...] = ()
    # 模組節點代表的 link；library 模組為 base，URDF 手臂為其根 link（例如 world、base_link）。
    base_link: str = "base"
    articulated_chain: bool = False
    # 相機節點：(節點名稱, 父 link, 相對父 link 的位姿, extras.camera)
    cameras: tuple[tuple[str, str, np.ndarray, dict[str, Any]], ...] = ()


@dataclass(frozen=True, slots=True)
class LinkEdge:
    joint_id: str
    parent: str
    child: str
    origin: np.ndarray
    axis: ModuleAxis | None
    fixed_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)


ROOT_LINKS = ("base", "link0")


def _roots(item: SceneItem) -> set[str]:
    return {*ROOT_LINKS, item.base_link}


def _link_edges(item: SceneItem) -> list[LinkEdge]:
    """Active axes and fixed joints of one item in parent-before-child order."""

    pending = [
        LinkEdge(
            axis.id,
            axis.parent,
            axis.child or axis.id,
            matrix_from_pose(axis.origin.xyz, axis.origin.rpy_deg),
            axis,
        )
        for axis in item.definition.axes
    ] + [
        LinkEdge(joint.id, joint.parent, joint.child, np.asarray(joint.origin), None, joint.axis)
        for joint in item.fixed_joints
    ]
    known = _roots(item)
    ordered: list[LinkEdge] = []
    while pending:
        ready = [edge for edge in pending if edge.parent in known]
        if not ready:
            names = ", ".join(edge.joint_id for edge in pending)
            raise ValueError(f"模組 {item.id} 的關節鏈不連通：{names}")
        for edge in ready:
            ordered.append(edge)
            known.add(edge.child)
            pending.remove(edge)
    return ordered


def _shape_mesh(shape: cq.Shape) -> trimesh.Trimesh:
    vertices, triangles = shape.tessellate(
        MESH_LINEAR_TOLERANCE_MM,
        MESH_ANGULAR_TOLERANCE_RAD,
    )
    return trimesh.Trimesh(
        vertices=np.asarray([[vertex.x, vertex.y, vertex.z] for vertex in vertices], dtype=float),
        faces=np.asarray(triangles, dtype=int),
        process=False,
    )


def _vertex_color(color: cq.Color | None) -> np.ndarray:
    """Convert a CadQuery assembly color to an sRGB 8-bit vertex color."""

    rgba = color.toTuple() if color is not None else (0.55, 0.62, 0.68, 1.0)
    return np.asarray([round(channel * 255) for channel in rgba], dtype=np.uint8)


def _assembly_link_meshes(assembly: cq.Assembly) -> list[tuple[str, str, trimesh.Trimesh]]:
    meshes: list[tuple[str, str, trimesh.Trimesh]] = []
    for name, child in assembly.objects.items():
        if name == assembly.name or child.obj is None:
            continue
        obj = child.obj
        if isinstance(obj, cq.Workplane):
            shape = obj.val()
        elif isinstance(obj, cq.Shape):
            shape = obj
        else:
            continue
        source_mesh = (child.metadata or {}).get("mesh")
        if isinstance(source_mesh, trimesh.Trimesh):
            # 廠商網格直接使用原始三角面；faceted B-rep 只供 STEP 使用，不再重新細分。
            mesh = source_mesh.copy()
            mesh.apply_transform(_location_matrix(child.loc))
        else:
            mesh = _shape_mesh(shape.located(child.loc))
        if len(mesh.vertices):
            mesh.visual.vertex_colors = np.tile(_vertex_color(child.color), (len(mesh.vertices), 1))
            part_name = name.rsplit("/", 1)[-1]
            link = str((child.metadata or {}).get("link") or part_name)
            meshes.append((part_name, link, mesh))
    return meshes


def _assembly_meshes(assembly: cq.Assembly) -> list[tuple[str, trimesh.Trimesh]]:
    return [(name, mesh) for name, _link, mesh in _assembly_link_meshes(assembly)]


def _assembly_collision_meshes(assembly: cq.Assembly) -> dict[str, trimesh.Trimesh]:
    """Explicit collision geometry (e.g. URDF ``<collision>``) keyed by sub-part name."""

    result: dict[str, trimesh.Trimesh] = {}
    for name, child in assembly.objects.items():
        mesh = (child.metadata or {}).get("collision_mesh")
        if name != assembly.name and isinstance(mesh, trimesh.Trimesh):
            located = mesh.copy()
            located.apply_transform(_location_matrix(child.loc))
            result[name.rsplit("/", 1)[-1]] = located
    return result


def _location_matrix(location: cq.Location | None) -> np.ndarray:
    if location is None:
        return np.eye(4)
    transform = location.wrapped.Transformation()
    matrix = np.eye(4)
    for row in range(3):
        for column in range(4):
            matrix[row, column] = transform.Value(row + 1, column + 1)
    return matrix


def _rest_transforms(item: SceneItem) -> dict[str, np.ndarray]:
    transforms = {root: np.eye(4) for root in _roots(item)}
    for edge in _link_edges(item):
        transforms[edge.child] = transforms[edge.parent] @ edge.origin
    return transforms


def _mesh_link(item: SceneItem, name: str, declared_link: str, child_links: set[str]) -> str:
    link = declared_link if declared_link in child_links else name
    return link if link in child_links else "base"


def _group_mesh_parts(
    item: SceneItem,
) -> dict[str, list[tuple[trimesh.Trimesh, trimesh.Trimesh | None]]]:
    """Visual meshes (with optional explicit collision mesh) per link, in link-local frames."""

    child_links = {edge.child for edge in _link_edges(item)}
    collisions = _assembly_collision_meshes(item.assembly)
    grouped: dict[str, list[tuple[trimesh.Trimesh, trimesh.Trimesh | None]]] = {"base": []}
    grouped.update({name: [] for name in child_links})
    for name, declared_link, mesh in _assembly_link_meshes(item.assembly):
        link = _mesh_link(item, name, declared_link, child_links)
        grouped[link].append((mesh, collisions.get(name)))
    rest = _rest_transforms(item)
    result: dict[str, list[tuple[trimesh.Trimesh, trimesh.Trimesh | None]]] = {}
    for link, entries in grouped.items():
        if not entries:
            # 廠商 URDF 常有只作參考座標的 link（world、tool0…），沒有外形是合法的。
            if item.articulated_chain:
                continue
            raise ValueError(f"模組 {item.id} 的 link {link} 沒有可匯出的幾何")
        inverse_rest = np.linalg.inv(rest[link])
        for mesh, collision in entries:
            mesh.apply_transform(inverse_rest)
            if collision is not None:
                collision.apply_transform(inverse_rest)
        result[link] = entries
    return result


def _visual_mesh(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    merged = trimesh.util.concatenate(meshes)
    if len(merged.faces) > 50_000:
        merged = merged.simplify_quadric_decimation(face_count=50_000)
    return merged


def _collision_mesh(visual: trimesh.Trimesh, mode: str = "box") -> trimesh.Trimesh:
    if mode == "mesh":
        return visual.copy()
    if mode == "hull":
        return visual.convex_hull
    extents = np.maximum(visual.extents, [1.0, 1.0, 1.0])
    collision = trimesh.creation.box(extents=extents)
    collision.apply_translation(visual.bounds.mean(axis=0))
    return collision


def _module_item(module: BuiltModule) -> SceneItem:
    pose = module.instance.pose
    fixed = ()
    if module.chain is not None:
        fixed = tuple(joint for joint in module.chain.joints if not joint.active)
    return SceneItem(
        id=module.instance.id,
        assembly=module.assembly,
        definition=module.definition,
        transform=matrix_from_pose(pose.xyz, pose.rpy_deg),
        extras={
            "trust": module.instance.trust or pose.trust,
            "station": module.station,
            "vendor": module.instance.vendor,
            "placeholder": module.definition.meta.placeholder,
            "model_source": module.model_source,
            "approximated": module.approximated,
        },
        fixed_joints=fixed,
        base_link=module.chain.base_link if module.chain is not None else "base",
        articulated_chain=module.chain is not None,
        cameras=_camera_nodes(module),
    )


def _camera_extras(spec) -> dict[str, Any]:
    width, height = spec.sensor_mm
    near, far = spec.depth_of_field_mm()
    return {
        "hfov_deg": float(np.degrees(2 * np.arctan(width / (2 * spec.focal_mm)))),
        "vfov_deg": float(np.degrees(2 * np.arctan(height / (2 * spec.focal_mm)))),
        "sensor_px": list(spec.sensor_px),
        "working_distance_mm": spec.working_distance_mm,
        "focus_range_mm": [near, far],
        "convention": "optical +Z forward, +X right, +Y down",
        "trust": spec.trust,
    }


def _camera_nodes(module: BuiltModule) -> tuple[tuple[str, str, np.ndarray, dict], ...]:
    """GLB nodes for fixed module cameras and cameras on a robot's tool module."""
    nodes = []
    definition = module.definition
    for frame_name, spec in definition.cameras.items():
        frame = definition.frames.get(frame_name)
        if frame is None:
            continue
        nodes.append(
            (
                f"{module.instance.id}.{frame_name}",
                frame.link or "base",
                matrix_from_pose(frame.xyz, frame.rpy_deg),
                _camera_extras(spec),
            )
        )
    if module.chain is not None:
        from cellforge.sim.scene import _load_tool_definition

        tool = _load_tool_definition(module)
        if isinstance(tool, ModuleDef):
            tcp = tool.frames.get("tool_center_point")
            tcp_matrix = np.eye(4) if tcp is None else matrix_from_pose(tcp.xyz, tcp.rpy_deg)
            for frame_name, spec in tool.cameras.items():
                frame = tool.frames.get(frame_name)
                if frame is None:
                    continue
                local = np.linalg.inv(tcp_matrix) @ matrix_from_pose(frame.xyz, frame.rpy_deg)
                nodes.append(
                    (f"{module.instance.id}.{frame_name}", "tool", local, _camera_extras(spec))
                )
    return tuple(nodes)


def _workpiece_item(workpiece: BuiltWorkpiece) -> SceneItem:
    extras = {
        "trust": workpiece.trust,
        "station": None,
        "vendor": None,
        "sku": workpiece.sku.id if workpiece.sku is not None else None,
        "mass_kg": workpiece.mass_kg,
        "part": True,
    }
    if workpiece.part_file:
        extras["part_file"] = workpiece.part_file
    return SceneItem(
        id=workpiece.id,
        assembly=workpiece.assembly,
        definition=workpiece.definition,
        transform=np.eye(4),
        extras=extras,
    )


def export_glb(
    modules: list[BuiltModule],
    path: Path,
    workpiece: BuiltWorkpiece | list[BuiltWorkpiece] | None = None,
) -> None:
    items = [_module_item(module) for module in modules]
    parts = [] if workpiece is None else workpiece if isinstance(workpiece, list) else [workpiece]
    items.extend(_workpiece_item(part) for part in parts)
    scene = trimesh.Scene(base_frame="world")
    internal_nodes: dict[tuple[str, str, str], str] = {}
    for item in items:
        for link, entries in _group_mesh_parts(item).items():
            visual = _visual_mesh([mesh for mesh, _collision in entries])
            collision = trimesh.util.concatenate(
                [
                    _collision_mesh(
                        explicit if explicit is not None else mesh, item.definition.collision
                    )
                    for mesh, explicit in entries
                ]
            )
            collision.visual.vertex_colors = np.tile(
                [220, 55, 55, 90], (len(collision.vertices), 1)
            )
            for kind, mesh in (("visual", visual), ("collision", collision)):
                internal = f"__cf__{item.id}__{link}__{kind}"
                internal_nodes[item.id, link, kind] = internal
                scene.add_geometry(mesh, node_name=internal, geom_name=internal)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(scene.export(file_type="glb"))
    _add_hierarchy(path, items, internal_nodes)


def _trs(matrix: np.ndarray) -> tuple[list[float], list[float]]:
    translation = [float(value) for value in matrix[:3, 3]]
    rotation = [float(value) for value in Rotation.from_matrix(matrix[:3, :3]).as_quat()]
    return translation, rotation


def _joint_extras(axis: ModuleAxis) -> dict[str, Any]:
    limit = axis.range_deg if axis.type == "revolute" else axis.range_mm
    return {
        "joint": {
            "type": axis.type,
            "axis": list(axis.axis),
            "range": list(limit or ()),
            "parent": axis.parent,
        }
    }


def _geometry_children(
    gltf: GLTF2,
    geometry_indices: dict[tuple[str, str, str], int],
    item_id: str,
    link: str,
) -> list[int]:
    assert gltf.nodes is not None
    children = []
    for kind in ("visual", "collision"):
        index = geometry_indices.get((item_id, link, kind))
        if index is None:
            continue
        node = gltf.nodes[index]
        node.name = kind
        node.matrix = None
        node.translation = None
        node.rotation = None
        node.scale = None
        node.extras = {"hidden": kind == "collision"}
        children.append(index)
    return children


def _add_hierarchy(
    path: Path,
    items: list[SceneItem],
    internal_nodes: dict[tuple[str, str, str], str],
) -> None:
    gltf = GLTF2().load_binary(str(path))
    assert gltf.nodes is not None and gltf.scenes is not None
    scene = gltf.scenes[gltf.scene or 0]
    root_nodes = list(scene.nodes or [])
    named = {node.name: index for index, node in enumerate(gltf.nodes)}
    geometry_indices = {key: named[name] for key, name in internal_nodes.items() if name in named}
    claimed = set(geometry_indices.values())
    root_nodes = [index for index in root_nodes if index not in claimed]
    for node in gltf.nodes:
        if node.children:
            node.children = [index for index in node.children if index not in claimed]
    root_nodes = [
        index
        for index in root_nodes
        if gltf.nodes[index].mesh is not None or gltf.nodes[index].children
    ]

    for item in items:
        module_translation, module_rotation = _trs(item.transform)
        module_node = Node(
            name=item.id,
            translation=module_translation,
            rotation=module_rotation,
            children=_geometry_children(gltf, geometry_indices, item.id, "base"),
            extras={
                **item.extras,
                "joints": [axis.id for axis in item.definition.axes],
                "frames": {
                    name: frame.model_dump(mode="json")
                    for name, frame in item.definition.frames.items()
                },
            },
        )
        gltf.nodes.append(module_node)
        module_index = len(gltf.nodes) - 1
        root_nodes.append(module_index)
        link_nodes = {root: module_index for root in _roots(item)}
        for edge in _link_edges(item):
            translation, rotation = _trs(edge.origin)
            extras = (
                _joint_extras(edge.axis)
                if edge.axis is not None
                else {
                    "joint": {
                        "type": "fixed",
                        "axis": list(edge.fixed_axis),
                        "range": [],
                        "parent": edge.parent,
                    }
                }
            )
            node = Node(
                name=f"{item.id}.{edge.joint_id}",
                translation=translation,
                rotation=rotation,
                children=_geometry_children(gltf, geometry_indices, item.id, edge.child),
                extras=extras,
            )
            gltf.nodes.append(node)
            index = len(gltf.nodes) - 1
            gltf.nodes[link_nodes[edge.parent]].children.append(index)
            link_nodes[edge.child] = index
        for name, parent, local, camera in item.cameras:
            translation, rotation = _trs(local)
            gltf.nodes.append(
                Node(
                    name=name,
                    translation=translation,
                    rotation=rotation,
                    children=[],
                    extras={"camera": camera},
                )
            )
            gltf.nodes[link_nodes.get(parent, module_index)].children.append(len(gltf.nodes) - 1)
    scene.nodes = root_nodes
    gltf.save_binary(str(path))
