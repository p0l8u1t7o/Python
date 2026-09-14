import json
import shutil
from pathlib import Path

import numpy as np
import trimesh
from pygltflib import GLTF2
from scipy.spatial.transform import Rotation

from cellforge.build.glb import export_glb
from cellforge.build.modules import build_module
from cellforge.build.pipeline import _module_floor_warnings, build_project
from cellforge.build.stepio import inspect_step
from cellforge.kinematics import make_stub_chain
from cellforge.schema.models import ModuleInstance

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "getac_qc" / "handwritten"
EXPECTED = [
    "infeed_rack",
    "conveyor_1",
    "robot_1",
    "vision_fixture",
    "robot_2",
    "conveyor_2",
    "outfeed_rack",
]
STEP_EXPECTED = [*EXPECTED, "workpiece"]


def test_l0_build_round_trips_step_and_names(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(SOURCE, project, ignore=shutil.ignore_patterns("build"))
    report = build_project(project)
    assert report["duration_s"] >= 40
    assert report["warnings"] == []
    brief = (project / "build" / "render_brief.md").read_text("utf-8")
    assert "## 建置警告\n- 無。" in brief
    inspection = inspect_step(project / "build" / "scene.step")
    assert [part.part_name for part in inspection.components] == STEP_EXPECTED
    assert [part.instance_name for part in inspection.components] == STEP_EXPECTED
    validation = json.loads((project / "build" / "step_validation.json").read_text("utf-8"))
    assert validation["top_level_part_count"] == 8
    assert validation["total_component_count"] == 51
    assert validation["assembly_node_count"] == 9
    assert validation["leaf_part_count"] == 43
    assert validation["all_names_preserved"] is True
    assert validation["count_match"] is True
    assert validation["name_match"] is True


def test_glb_has_named_module_visual_collision_hierarchy(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(SOURCE, project, ignore=shutil.ignore_patterns("build"))
    build_project(project)
    gltf = GLTF2().load_binary(str(project / "build" / "scene.glb"))
    parent_counts = {
        index: sum(index in (node.children or []) for node in gltf.nodes)
        for index in range(len(gltf.nodes))
    }
    for module_id in EXPECTED:
        module = next(node for node in gltf.nodes if node.name == module_id)
        child_names = [gltf.nodes[index].name for index in module.children]
        assert child_names[:2] == ["visual", "collision"]
        assert all(name.startswith(f"{module_id}.") for name in child_names[2:])
        assert all(parent_counts[index] == 1 for index in module.children)
        assert module.extras["trust"] == "inferred"
    names = {node.name: index for index, node in enumerate(gltf.nodes) if node.name}
    expected_chain = ["robot_1", *(f"robot_1.j{i}" for i in range(1, 7)), "robot_1.tool"]
    for parent_name, child_name in zip(expected_chain, expected_chain[1:], strict=False):
        assert names[child_name] in gltf.nodes[names[parent_name]].children
    assert names["workpiece.cover_lan"] in gltf.nodes[names["workpiece"]].children
    assert names["infeed_rack.lift"] in gltf.nodes[names["infeed_rack"]].children

    rendered = trimesh.load_scene(project / "build" / "scene.glb")
    base_colors = np.unique(
        rendered.geometry["__cf__robot_1__base__visual"].visual.vertex_colors[:, :3], axis=0
    )
    arm_colors = np.unique(
        rendered.geometry["__cf__robot_1__link1__visual"].visual.vertex_colors[:, :3], axis=0
    )
    fixture_colors = np.unique(
        rendered.geometry["__cf__vision_fixture__base__visual"].visual.vertex_colors[:, :3], axis=0
    )
    assert not np.array_equal(base_colors, arm_colors)
    source_fixture = build_module(ModuleInstance(id="fixture", part="library/fixture_stand.py"))
    expected_colors = {
        tuple(round(channel * 255) for channel in child.color.toTuple()[:3])
        for child in source_fixture.assembly.objects.values()
        if child.color is not None
    }
    assert {tuple(int(channel) for channel in row) for row in fixture_colors} == expected_colors


def _local_matrix(node, joint_value=0.0):
    if node.matrix:
        result = np.asarray(node.matrix, dtype=float).reshape((4, 4), order="F")
    else:
        result = np.eye(4)
        result[:3, 3] = node.translation or [0, 0, 0]
        result[:3, :3] = Rotation.from_quat(node.rotation or [0, 0, 0, 1]).as_matrix()
    joint = (node.extras or {}).get("joint")
    if joint and joint["type"] == "revolute":
        motion = np.eye(4)
        motion[:3, :3] = Rotation.from_rotvec(
            np.radians(joint_value) * np.asarray(joint["axis"])
        ).as_matrix()
        result = result @ motion
    elif joint and joint["type"] == "prismatic":
        motion = np.eye(4)
        motion[:3, 3] = np.asarray(joint["axis"]) * joint_value
        result = result @ motion
    return result


def _node_world(gltf, name, values):
    indices = {node.name: index for index, node in enumerate(gltf.nodes) if node.name}
    return _index_world(gltf, indices[name], values)


def _index_world(gltf, target_index, values):
    parents = {
        child: parent for parent, node in enumerate(gltf.nodes) for child in (node.children or [])
    }
    chain = []
    cursor = target_index
    while True:
        chain.append(cursor)
        if cursor not in parents:
            break
        cursor = parents[cursor]
    world = np.eye(4)
    for index in reversed(chain):
        node = gltf.nodes[index]
        joint_id = node.name.rsplit(".", 1)[-1] if "." in (node.name or "") else ""
        world = world @ _local_matrix(node, values.get(joint_id, 0.0))
    return world


def _visual_world_aabb(gltf, parent_name, values):
    parent = next(node for node in gltf.nodes if node.name == parent_name)
    visual_index = next(index for index in parent.children if gltf.nodes[index].name == "visual")
    visual = gltf.nodes[visual_index]
    world = _index_world(gltf, visual_index, values)
    lower = np.full(3, np.inf)
    upper = np.full(3, -np.inf)
    for primitive in gltf.meshes[visual.mesh].primitives:
        accessor = gltf.accessors[primitive.attributes.POSITION]
        corners = np.asarray(
            [
                [x, y, z, 1.0]
                for x in (accessor.min[0], accessor.max[0])
                for y in (accessor.min[1], accessor.max[1])
                for z in (accessor.min[2], accessor.max[2])
            ]
        )
        transformed = (world @ corners.T).T[:, :3]
        lower = np.minimum(lower, transformed.min(axis=0))
        upper = np.maximum(upper, transformed.max(axis=0))
    return lower, upper


def _point_aabb_distance(point, bounds):
    lower, upper = bounds
    return np.linalg.norm(np.maximum(np.maximum(lower - point, point - upper), 0.0))


def _aabb_distance(first, second):
    first_lower, first_upper = first
    second_lower, second_upper = second
    separation = np.maximum(np.maximum(second_lower - first_upper, first_lower - second_upper), 0.0)
    return np.linalg.norm(separation)


def _assert_robot_geometry_follows_fk(gltf, joints, module_id="robot_1", chain=None):
    values = {f"j{i + 1}": value for i, value in enumerate(joints)}
    chain = chain or make_stub_chain()
    transforms = chain.link_transforms(joints)
    module_world = _node_world(gltf, module_id, {})
    links = [*(f"link{i}" for i in range(7)), "tool"]
    node_names = [module_id, *(f"{module_id}.j{i}" for i in range(1, 7)), f"{module_id}.tool"]
    bounds = []
    for link, node_name in zip(links, node_names, strict=True):
        link_bounds = _visual_world_aabb(gltf, node_name, values)
        bounds.append(link_bounds)
        expected_origin = (module_world @ transforms[link])[:3, 3]
        assert _point_aabb_distance(expected_origin, link_bounds) <= 30.0, link
    for first, second in zip(bounds, bounds[1:], strict=False):
        assert _aabb_distance(first, second) <= 5.0
    expected_tool = module_world @ chain.fk(joints)
    actual_tool = _node_world(gltf, f"{module_id}.tool", values)
    assert np.allclose(actual_tool, expected_tool, atol=1e-7)


def test_glb_joint_rest_and_motion_match_kinematic_chain(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(SOURCE, project, ignore=shutil.ignore_patterns("build"))
    build_project(project)
    gltf = GLTF2().load_binary(str(project / "build" / "scene.glb"))
    chain = make_stub_chain(tool_length_mm=140)
    module_world = _node_world(gltf, "robot_1", {})
    rest_tool = np.linalg.inv(module_world) @ _node_world(gltf, "robot_1.tool", {})
    assert np.allclose(rest_tool, chain.fk(np.zeros(6)), atol=1e-7)
    joints = np.asarray([20, -30, 45, 10, 35, 80], dtype=float)
    values = {f"j{i + 1}": value for i, value in enumerate(joints)}
    moved_tool = np.linalg.inv(module_world) @ _node_world(gltf, "robot_1.tool", values)
    assert np.allclose(moved_tool, chain.fk(joints), atol=1e-7)
    assert not np.allclose(moved_tool[:3, 3], rest_tool[:3, 3])


def test_robot_link_visual_aabbs_form_connected_fk_chain_at_rest_and_when_posed(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(SOURCE, project, ignore=shutil.ignore_patterns("build"))
    build_project(project)
    gltf = GLTF2().load_binary(str(project / "build" / "scene.glb"))
    chain = make_stub_chain(tool_length_mm=140)
    _assert_robot_geometry_follows_fk(gltf, np.zeros(6), chain=chain)
    _assert_robot_geometry_follows_fk(
        gltf, np.asarray([20, -30, 45, 10, 35, 80], dtype=float), chain=chain
    )


def test_vendor_robot_glb_uses_the_same_fk_aligned_connected_geometry(tmp_path):
    instance = ModuleInstance(id="vendor_robot", vendor="catalog_robot")
    built = build_module(
        instance,
        {
            "catalog_robot": {
                "kind": "robot",
                "limits": {"reach_mm": 905, "payload_kg": 7},
            }
        },
    )
    path = tmp_path / "vendor.glb"
    export_glb([built], path)
    gltf = GLTF2().load_binary(str(path))
    _assert_robot_geometry_follows_fk(gltf, np.zeros(6), "vendor_robot")


def test_floating_module_warning_honors_a_valid_mount_reference():
    support = build_module(
        ModuleInstance(
            id="support",
            part="library/box.py",
            params={"size": [500, 500, 500]},
            pose={"xyz": [0, 0, 250]},
        )
    )
    floating = build_module(
        ModuleInstance(
            id="sensor",
            part="library/box.py",
            params={"size": [300, 220, 10]},
            pose={"xyz": [0, 0, 800]},
        )
    )
    assert any(
        "sensor" in message and "懸空" in message
        for message in _module_floor_warnings([support, floating])
    )

    mounted = build_module(floating.instance.model_copy(update={"mount": "support.top"}))
    assert not any(
        "sensor" in message and "懸空" in message
        for message in _module_floor_warnings([support, mounted])
    )


def test_module_below_floor_is_reported_even_when_mounted():
    module = build_module(
        ModuleInstance(
            id="buried",
            part="library/box.py",
            params={"size": [100, 100, 100]},
            pose={"xyz": [0, 0, 0]},
            mount="support",
        )
    )
    support = build_module(
        ModuleInstance(
            id="support",
            part="library/box.py",
            params={"size": [100, 100, 100]},
            pose={"xyz": [0, 0, 50]},
        )
    )
    assert any(
        "buried" in message and "低於地板" in message
        for message in _module_floor_warnings([support, module])
    )
