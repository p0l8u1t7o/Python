"""Build a named GLB hierarchy for the browser viewer."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from pygltflib import GLTF2, Node

from .modules import BuiltModule
from .transforms import matrix_from_pose


def _mesh_from_module(module: BuiltModule) -> trimesh.Trimesh:
    shape = module.assembly.toCompound()
    vertices, triangles = shape.tessellate(1.0, 0.2)
    mesh = trimesh.Trimesh(
        vertices=np.asarray([[v.x, v.y, v.z] for v in vertices], dtype=float),
        faces=np.asarray(triangles, dtype=int),
        process=False,
    )
    if len(mesh.faces) > 50_000:
        mesh = mesh.simplify_quadric_decimation(face_count=50_000)
    return mesh


def _collision_mesh(visual: trimesh.Trimesh) -> trimesh.Trimesh:
    extents = np.maximum(visual.extents, [1.0, 1.0, 1.0])
    collision = trimesh.creation.box(extents=extents)
    collision.apply_translation(visual.bounds.mean(axis=0))
    return collision


def export_glb(modules: list[BuiltModule], path: Path) -> None:
    scene = trimesh.Scene(base_frame="world")
    for module in modules:
        module_id = module.instance.id
        pose = module.instance.pose
        transform = matrix_from_pose(pose.xyz, pose.rpy_deg)
        visual = _mesh_from_module(module)
        visual.visual.vertex_colors = np.tile([96, 145, 180, 255], (len(visual.vertices), 1))
        collision = _collision_mesh(visual)
        collision.visual.vertex_colors = np.tile([220, 55, 55, 90], (len(collision.vertices), 1))
        scene.add_geometry(
            visual,
            node_name=f"{module_id}__visual",
            geom_name=f"{module_id}__visual",
            transform=transform,
        )
        scene.add_geometry(
            collision,
            node_name=f"{module_id}__collision",
            geom_name=f"{module_id}__collision",
            transform=transform,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(scene.export(file_type="glb"))
    _add_module_hierarchy(path, modules)


def _add_module_hierarchy(path: Path, modules: list[BuiltModule]) -> None:
    gltf = GLTF2().load_binary(str(path))
    assert gltf.nodes is not None and gltf.scenes is not None
    root_nodes = list(gltf.scenes[gltf.scene or 0].nodes or [])
    module_children: dict[str, tuple[int, int]] = {}
    for module in modules:
        module_id = module.instance.id
        module_children[module_id] = (
            next(i for i, node in enumerate(gltf.nodes) if node.name == f"{module_id}__visual"),
            next(i for i, node in enumerate(gltf.nodes) if node.name == f"{module_id}__collision"),
        )
    claimed_children = {index for pair in module_children.values() for index in pair}
    for node in gltf.nodes:
        if node.children:
            node.children = [child for child in node.children if child not in claimed_children]
    root_nodes = [
        index
        for index in root_nodes
        if gltf.nodes[index].mesh is not None or gltf.nodes[index].children
    ]
    for module in modules:
        module_id = module.instance.id
        visual_index, collision_index = module_children[module_id]
        transform = gltf.nodes[visual_index].matrix
        for index, child_name in ((visual_index, "visual"), (collision_index, "collision")):
            gltf.nodes[index].name = child_name
            gltf.nodes[index].matrix = None
            gltf.nodes[index].translation = None
            gltf.nodes[index].rotation = None
            gltf.nodes[index].scale = None
            gltf.nodes[index].extras = {"hidden": child_name == "collision"}
            if index in root_nodes:
                root_nodes.remove(index)
        pose = module.instance.pose
        module_node = Node(
            name=module_id,
            matrix=transform,
            children=[visual_index, collision_index],
            extras={
                "trust": module.instance.trust or pose.trust,
                "station": module.station,
                "vendor": module.instance.vendor,
            },
        )
        gltf.nodes.append(module_node)
        root_nodes.append(len(gltf.nodes) - 1)
    gltf.scenes[gltf.scene or 0].nodes = root_nodes
    gltf.save_binary(str(path))
