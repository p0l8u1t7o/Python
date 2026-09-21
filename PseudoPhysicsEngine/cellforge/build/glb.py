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
        located = shape.located(child.loc)
        mesh = _shape_mesh(located)
        if len(mesh.vertices):
            mesh.visual.vertex_colors = np.tile(_vertex_color(child.color), (len(mesh.vertices), 1))
            part_name = name.rsplit("/", 1)[-1]
            link = str((child.metadata or {}).get("link") or part_name)
            meshes.append((part_name, link, mesh))
    return meshes


def _assembly_meshes(assembly: cq.Assembly) -> list[tuple[str, trimesh.Trimesh]]:
    return [(name, mesh) for name, _link, mesh in _assembly_link_meshes(assembly)]


def _rest_transforms(item: SceneItem) -> dict[str, np.ndarray]:
    transforms = {"base": np.eye(4), "link0": np.eye(4)}
    remaining = list(item.definition.axes)
    while remaining:
        progressed = False
        for axis in list(remaining):
            if axis.parent not in transforms:
                continue
            transforms[axis.child or axis.id] = transforms[axis.parent] @ matrix_from_pose(
                axis.origin.xyz, axis.origin.rpy_deg
            )
            remaining.remove(axis)
            progressed = True
        if not progressed:
            names = ", ".join(axis.id for axis in remaining)
            raise ValueError(f"模組 {item.id} 的關節鏈不連通：{names}")
    for joint in item.fixed_joints:
        if joint.parent not in transforms:
            raise ValueError(f"模組 {item.id} 的固定關節 {joint.id} 找不到 parent")
        transforms[joint.child] = transforms[joint.parent] @ joint.origin
    return transforms


def _group_mesh_parts(item: SceneItem) -> dict[str, list[trimesh.Trimesh]]:
    child_links = {axis.child or axis.id for axis in item.definition.axes}
    child_links.update(joint.child for joint in item.fixed_joints)
    grouped: dict[str, list[trimesh.Trimesh]] = {"base": []}
    grouped.update({name: [] for name in child_links})
    for name, declared_link, mesh in _assembly_link_meshes(item.assembly):
        link = declared_link if declared_link in child_links else name
        grouped[link if link in child_links else "base"].append(mesh)
    rest = _rest_transforms(item)
    result: dict[str, list[trimesh.Trimesh]] = {}
    for link, meshes in grouped.items():
        if not meshes:
            raise ValueError(f"模組 {item.id} 的 link {link} 沒有可匯出的幾何")
        inverse_rest = np.linalg.inv(rest[link])
        for mesh in meshes:
            mesh.apply_transform(inverse_rest)
        result[link] = meshes
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
        },
        fixed_joints=fixed,
    )


def _workpiece_item(workpiece: BuiltWorkpiece) -> SceneItem:
    return SceneItem(
        id="workpiece",
        assembly=workpiece.assembly,
        definition=workpiece.definition,
        transform=np.eye(4),
        extras={
            "trust": workpiece.sku.size.trust,
            "station": None,
            "vendor": None,
            "sku": workpiece.sku.id,
            "mass_kg": workpiece.sku.mass_kg,
        },
    )


def export_glb(
    modules: list[BuiltModule], path: Path, workpiece: BuiltWorkpiece | None = None
) -> None:
    items = [_module_item(module) for module in modules]
    if workpiece is not None:
        items.append(_workpiece_item(workpiece))
    scene = trimesh.Scene(base_frame="world")
    internal_nodes: dict[tuple[str, str, str], str] = {}
    for item in items:
        for link, meshes in _group_mesh_parts(item).items():
            visual = _visual_mesh(meshes)
            collision = trimesh.util.concatenate(
                [_collision_mesh(mesh, item.definition.collision) for mesh in meshes]
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
        index = geometry_indices[item_id, link, kind]
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
        link_nodes = {"base": module_index, "link0": module_index}
        remaining = list(item.definition.axes)
        while remaining:
            progressed = False
            for axis in list(remaining):
                if axis.parent not in link_nodes:
                    continue
                link = axis.child or axis.id
                translation, rotation = _trs(matrix_from_pose(axis.origin.xyz, axis.origin.rpy_deg))
                node = Node(
                    name=f"{item.id}.{axis.id}",
                    translation=translation,
                    rotation=rotation,
                    children=_geometry_children(gltf, geometry_indices, item.id, link),
                    extras=_joint_extras(axis),
                )
                gltf.nodes.append(node)
                index = len(gltf.nodes) - 1
                gltf.nodes[link_nodes[axis.parent]].children.append(index)
                link_nodes[link] = index
                remaining.remove(axis)
                progressed = True
            if not progressed:
                names = ", ".join(axis.id for axis in remaining)
                raise ValueError(f"模組 {item.id} 的關節 parent 不存在：{names}")
        for joint in item.fixed_joints:
            translation, rotation = _trs(joint.origin)
            node = Node(
                name=f"{item.id}.{joint.id}",
                translation=translation,
                rotation=rotation,
                children=_geometry_children(gltf, geometry_indices, item.id, joint.child),
                extras={
                    "joint": {
                        "type": "fixed",
                        "axis": list(joint.axis),
                        "range": [],
                        "parent": joint.parent,
                    }
                },
            )
            gltf.nodes.append(node)
            index = len(gltf.nodes) - 1
            gltf.nodes[link_nodes[joint.parent]].children.append(index)
            link_nodes[joint.child] = index
    scene.nodes = root_nodes
    gltf.save_binary(str(path))
