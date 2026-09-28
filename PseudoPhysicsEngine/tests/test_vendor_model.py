"""DEV-007：原廠 URDF／STEP 轉接與近似 stub 標示。

測試用的 URDF 與網格都在測試內自製（不依賴外部下載）。期望值一律由 URDF 原始數值
（公尺、弧度）以獨立的 FK 推得，再與平台的運動鏈、GLB 節點（viewer 語意）、取樣與碰撞
零件比對；不寫死任何驗收數值。
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import cadquery as cq
import numpy as np
import pytest
import trimesh
from docx import Document
from pygltflib import GLTF2
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from cellforge.build.modules import build_module, project_parts
from cellforge.build.pipeline import build_project
from cellforge.checks.collision import CollisionPart, _adjacent, build_collision_parts
from cellforge.checks.runner import _hardware, _mark_approximated_models
from cellforge.exports import export_project
from cellforge.kinematics.ik import solve_ik
from cellforge.project import create_project
from cellforge.schema import VendorManifest
from cellforge.schema.models import ModuleInstance
from cellforge.sim import SceneModel, build_workpiece
from cellforge.sim.sampling import world_transforms
from cellforge.validation import ProjectValidationError, validate_project
from cellforge.vendor import add_vendor_file, add_vendor_urdf
from cellforge.vendor_model import VendorModelError, build_vendor_model
from cellforge.version_store import used_library_files
from cellforge.yamlio import dump_yaml, load_yaml

ARM_ID = "test_arm"
TOOL_LENGTH_MM = 90.0
FLANGE = {"link": "link6", "xyz": [0.0, 0.0, 15.0], "rpy_deg": [0.0, 0.0, 30.0]}


# ---------------------------------------------------------------- 自製 URDF


@dataclass(frozen=True)
class JointSpec:
    name: str
    type: str
    parent: str
    child: str
    xyz: tuple[float, float, float]  # m
    rpy: tuple[float, float, float] = (0.0, 0.0, 0.0)  # rad
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    lower: float = 0.0
    upper: float = 0.0
    velocity: float = 1.0


ARM_JOINTS = (
    JointSpec("world_joint", "fixed", "world", "base_link", (0.01, 0.0, 0.0)),
    JointSpec(
        "j1", "revolute", "base_link", "link1", (0, 0, 0.12), lower=-2.9, upper=2.9, velocity=3.9
    ),
    JointSpec(
        "j2",
        "revolute",
        "link1",
        "link2",
        (0, 0, 0.2),
        (0, 0, 0.3),
        (0, 1, 0),
        lower=-2.0,
        upper=2.0,
        velocity=3.0,
    ),
    # 夾在活動關節之間的固定關節：GLB、取樣與碰撞都必須把它當成父座標。
    JointSpec("mid_fixed", "fixed", "link2", "link2b", (0, 0, 0.35), (0.2, 0.0, 0.0)),
    JointSpec(
        "j3",
        "prismatic",
        "link2b",
        "link3",
        (0.05, 0, 0),
        axis=(1, 0, 0),
        lower=0.0,
        upper=0.15,
        velocity=0.4,
    ),
    JointSpec(
        "j4",
        "revolute",
        "link3",
        "link4",
        (0.25, 0, 0),
        axis=(1, 0, 0),
        lower=-3.0,
        upper=3.0,
        velocity=5.0,
    ),
    JointSpec(
        "j5",
        "revolute",
        "link4",
        "link5",
        (0.08, 0, 0),
        axis=(0, 1, 0),
        lower=-2.1,
        upper=2.1,
        velocity=5.0,
    ),
    JointSpec(
        "j6",
        "revolute",
        "link5",
        "link6",
        (0.06, 0, 0),
        (0, 1.5707963267948966, 0),
        lower=-6.0,
        upper=6.0,
        velocity=7.0,
    ),
    JointSpec("tool0_joint", "fixed", "link6", "tool0", (0, 0, 0.01)),
)
ARM_Q = {"j1": 35.0, "j2": -25.0, "j3": 60.0, "j4": 40.0, "j5": -30.0, "j6": 75.0}

# link → (visual, collision)；visual 刻意都偏離 link 原點，放錯 link 或座標就會被抓到。
VISUAL_ORIGINS = {
    "base_link": ((0, 0, 0.05), (0, 0, 0)),
    "link1": ((0, 0, 0.1), (0, 0, 0)),
    "link2": ((0, 0, 0.17), (0.1, 0.2, 0.3)),
    "link2b": ((0.02, 0, 0), (0, 0, 0)),
    "link4": ((0.04, 0, 0), (0, 0, 0)),
    "link5": ((0.03, 0, 0), (0, 0.4, 0)),
    "link6": ((0, 0, 0.004), (0, 0, 0)),
}
VISUAL_BOXES = {  # m
    "base_link": (0.2, 0.2, 0.1),
    "link1": (0.1, 0.1, 0.2),
    "link2": (0.08, 0.08, 0.34),
    "link2b": (0.06, 0.06, 0.06),
    "link4": (0.08, 0.05, 0.05),
    "link5": (0.06, 0.05, 0.05),
    "link6": (0.04, 0.04, 0.008),
}
COLLISION_BOXES = {  # m；比 visual 大，證明碰撞用的是 <collision> 而非外形凸包
    "link1": (0.13, 0.13, 0.23),
    "link3": (0.3, 0.07, 0.07),
    "link4": (0.1, 0.07, 0.07),
    "link5": (0.08, 0.07, 0.07),
}
LINK3_VISUAL_BOX = (0.26, 0.05, 0.05)
BASE_COLLISION_CYLINDER = (0.13, 0.11)  # radius, length (m)
LINK6_COLLISION_MESH_BOX = (0.06, 0.06, 0.012)


def _pose_m(xyz, rpy) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_euler("xyz", rpy).as_matrix()  # URDF：R = Rz·Ry·Rx
    matrix[:3, 3] = np.asarray(xyz, dtype=float) * 1000.0
    return matrix


def _urdf_fk(joints: tuple[JointSpec, ...], q: dict[str, float]) -> dict[str, np.ndarray]:
    """由 URDF 原始數值（m、rad）獨立推得的 FK，輸出 mm。"""

    result = {joints[0].parent: np.eye(4)}
    pending = list(joints)
    while pending:
        for joint in list(pending):
            if joint.parent not in result:
                continue
            motion = np.eye(4)
            axis = np.asarray(joint.axis, dtype=float) / np.linalg.norm(joint.axis)
            if joint.type == "revolute":
                motion[:3, :3] = Rotation.from_rotvec(
                    axis * math.radians(q[joint.name])
                ).as_matrix()
            elif joint.type == "prismatic":
                motion[:3, 3] = axis * q[joint.name]
            result[joint.child] = result[joint.parent] @ _pose_m(joint.xyz, joint.rpy) @ motion
            pending.remove(joint)
    return result


def _box_file(path: Path, extents, *, scale: float = 1.0) -> None:
    trimesh.creation.box(extents=np.asarray(extents) * scale).export(path)


def _write_arm(directory: Path) -> tuple[Path, list[Path]]:
    meshes = directory / "meshes"
    meshes.mkdir(parents=True)
    files = []
    for link, extents in VISUAL_BOXES.items():
        if link == "link2":
            # 網格以 mm 繪製，靠 <mesh scale> 換成公尺。
            path = meshes / "link2.stl"
            _box_file(path, extents, scale=1000.0)
        elif link == "link2b":
            path = meshes / "link2b.obj"
            _box_file(path, extents)
        else:
            path = meshes / f"{link}.stl"
            _box_file(path, extents)
        files.append(path)
    collision_mesh = meshes / "link6_collision.stl"
    _box_file(collision_mesh, LINK6_COLLISION_MESH_BOX)
    files.append(collision_mesh)

    def visual(link: str) -> str:
        xyz, rpy = VISUAL_ORIGINS[link]
        suffix = "obj" if link == "link2b" else "stl"
        prefix = "meshes/" if link == "link4" else f"package://{ARM_ID}/meshes/"
        scale = ' scale="0.001 0.001 0.001"' if link == "link2" else ""
        return (
            f'<visual><origin xyz="{_v(xyz)}" rpy="{_v(rpy)}"/><geometry>'
            f'<mesh filename="{prefix}{link}.{suffix}"{scale}/></geometry></visual>'
        )

    def collision_box(link: str) -> str:
        xyz, rpy = VISUAL_ORIGINS.get(link, ((0.13, 0, 0), (0, 0, 0)))
        return (
            f'<collision><origin xyz="{_v(xyz)}" rpy="{_v(rpy)}"/><geometry>'
            f'<box size="{_v(COLLISION_BOXES[link])}"/></geometry></collision>'
        )

    radius, length = BASE_COLLISION_CYLINDER
    links = {
        "world": "",
        "base_link": visual("base_link")
        + f'<collision><origin xyz="0 0 0.055"/><geometry><cylinder radius="{radius}" '
        f'length="{length}"/></geometry></collision>',
        "link1": visual("link1") + collision_box("link1"),
        "link2": visual("link2"),  # 沒有 <collision>：保守地用外形
        "link2b": visual("link2b"),
        "link3": '<visual><origin xyz="0.13 0 0"/><geometry>'
        f'<box size="{_v(LINK3_VISUAL_BOX)}"/></geometry></visual>' + collision_box("link3"),
        "link4": visual("link4") + collision_box("link4"),
        "link5": visual("link5") + collision_box("link5"),
        "link6": visual("link6") + '<collision><origin xyz="0 0 0.006"/><geometry>'
        f'<mesh filename="package://{ARM_ID}/meshes/link6_collision.stl"/></geometry></collision>',
        "tool0": "",
    }
    urdf = directory / f"{ARM_ID}.urdf"
    urdf.write_text(_urdf_text(ARM_ID, links, ARM_JOINTS), encoding="utf-8")
    return urdf, files


def _v(values) -> str:
    return " ".join(repr(float(value)) for value in values)


def _urdf_text(name: str, links: dict[str, str], joints: tuple[JointSpec, ...]) -> str:
    body = [f'<robot name="{name}">']
    body += [f'<link name="{link}">{content}</link>' for link, content in links.items()]
    for joint in joints:
        limit = (
            f'<limit lower="{joint.lower}" upper="{joint.upper}" effort="10" '
            f'velocity="{joint.velocity}"/>'
            if joint.type != "fixed"
            else ""
        )
        body.append(
            f'<joint name="{joint.name}" type="{joint.type}"><parent link="{joint.parent}"/>'
            f'<child link="{joint.child}"/><origin xyz="{_v(joint.xyz)}" rpy="{_v(joint.rpy)}"/>'
            f'<axis xyz="{_v(joint.axis)}"/>{limit}</joint>'
        )
    body.append("</robot>")
    return "\n".join(body)


# ---------------------------------------------------------------- 案子


def _getac_project(root: Path, name: str) -> Path:
    return create_project(
        root / name,
        {"name": name, "created": date.today().isoformat()},
        seed_example="getac_qc",
    )


def _use_vendor(project: Path, instance_id: str, vendor: str, params: dict | None = None) -> None:
    cell = load_yaml(project / "cell.yaml")
    for machine in cell["machines"]:
        for module in machine["modules"]:
            if module["id"] == instance_id:
                module.pop("part", None)
                module["vendor"] = vendor
                module["params"] = params or {}
    dump_yaml(project / "cell.yaml", cell)


def _scene(project: Path) -> SceneModel:
    _project, workpiece, cell, process = validate_project(project)
    manifest = VendorManifest.model_validate(load_yaml(project / "vendor" / "manifest.yaml"))
    items = {item.id: item.model_dump(mode="json") for item in manifest.vendors}
    with project_parts(project):
        modules = [
            build_module(instance, items)
            for machine in cell.machines
            for instance in machine.modules
        ]
    return SceneModel(cell, modules, build_workpiece(workpiece, process))


@pytest.fixture(scope="module")
def vendor_project(tmp_path_factory):
    root = tmp_path_factory.mktemp("dev007")
    urdf, meshes = _write_arm(root / "source")
    project = _getac_project(root, "vendor_arm")
    add_vendor_urdf(
        project,
        ARM_ID,
        str(urdf),
        [str(path) for path in meshes],
        flange=FLANGE,
        limits={"payload_kg": 3},
        source_url="test://self-made-arm",
    )
    _use_vendor(project, "robot_1", ARM_ID, {"tool": {"length_mm": TOOL_LENGTH_MM}})
    report = build_project(project, "L0")
    return project, report, _scene(project)


# ---------------------------------------------------------------- GLB viewer 語意


def _local(node, value: float) -> np.ndarray:
    result = np.eye(4)
    if node.matrix:
        result = np.asarray(node.matrix, dtype=float).reshape((4, 4), order="F")
    else:
        result[:3, 3] = node.translation or [0, 0, 0]
        result[:3, :3] = Rotation.from_quat(node.rotation or [0, 0, 0, 1]).as_matrix()
    joint = (node.extras or {}).get("joint") or {}
    motion = np.eye(4)
    if joint.get("type") == "revolute":
        motion[:3, :3] = Rotation.from_rotvec(
            np.radians(value) * np.asarray(joint["axis"])
        ).as_matrix()
    elif joint.get("type") == "prismatic":
        motion[:3, 3] = np.asarray(joint["axis"]) * value
    return result @ motion


def _world(gltf: GLTF2, index: int, values: dict[str, float]) -> np.ndarray:
    parents = {child: parent for parent, node in enumerate(gltf.nodes) for child in node.children}
    chain = [index]
    while chain[-1] in parents:
        chain.append(parents[chain[-1]])
    world = np.eye(4)
    for cursor in reversed(chain):
        node = gltf.nodes[cursor]
        joint_id = node.name.rsplit(".", 1)[-1] if "." in (node.name or "") else ""
        world = world @ _local(node, values.get(joint_id, 0.0))
    return world


def _node(gltf: GLTF2, name: str) -> int:
    return next(index for index, node in enumerate(gltf.nodes) if node.name == name)


def _child(gltf: GLTF2, parent: int, kind: str) -> int | None:
    return next(
        (index for index in gltf.nodes[parent].children if gltf.nodes[index].name == kind), None
    )


def _positions(gltf: GLTF2, mesh_index: int) -> np.ndarray:
    blob = gltf.binary_blob()
    chunks = []
    for primitive in gltf.meshes[mesh_index].primitives:
        accessor = gltf.accessors[primitive.attributes.POSITION]
        view = gltf.bufferViews[accessor.bufferView]
        assert view.byteStride in (None, 12)
        offset = (view.byteOffset or 0) + (accessor.byteOffset or 0)
        data = np.frombuffer(blob, dtype=np.float32, count=accessor.count * 3, offset=offset)
        chunks.append(data.reshape(-1, 3).astype(float))
    return np.vstack(chunks)


def _apply(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def _same_points(actual: np.ndarray, expected: np.ndarray, tolerance: float) -> bool:
    forward = cKDTree(expected).query(actual)[0].max()
    backward = cKDTree(actual).query(expected)[0].max()
    return max(forward, backward) <= tolerance


def _expected_visual(link: str) -> np.ndarray:
    if link == "link3":
        corners = trimesh.creation.box(extents=np.asarray(LINK3_VISUAL_BOX) * 1000).vertices
        return _apply(_pose_m((0.13, 0, 0), (0, 0, 0)), corners)
    xyz, rpy = VISUAL_ORIGINS[link]
    corners = trimesh.creation.box(extents=np.asarray(VISUAL_BOXES[link]) * 1000).vertices
    return _apply(_pose_m(xyz, rpy), corners)


# ---------------------------------------------------------------- 測試


def test_urdf_chain_converts_units_limits_and_keeps_joint_types(vendor_project):
    _project, _report, scene = vendor_project
    module = scene.modules["robot_1"]
    assert module.model_source == f"vendor-urdf:{ARM_ID}"
    assert module.approximated is False
    chain = module.chain
    assert chain.base_link == "world"
    specs = {joint.name: joint for joint in ARM_JOINTS if joint.type != "fixed"}
    assert [joint.id for joint in chain.active_joints] == list(specs)
    for joint in chain.active_joints:
        spec = specs[joint.id]
        assert joint.type == spec.type
        factor = 1000.0 if spec.type == "prismatic" else math.degrees(1.0)
        assert joint.limit == pytest.approx((spec.lower * factor, spec.upper * factor))
        assert joint.max_speed == pytest.approx(spec.velocity * factor)
    axes = {axis.id: axis for axis in module.definition.axes}
    assert axes["j3"].type == "prismatic" and axes["j3"].range_mm is not None
    assert axes["j1"].type == "revolute" and axes["j1"].range_deg is not None
    # URDF 中夾在中間的固定關節保留在鏈上，且 FK 與獨立推導一致。
    expected = _urdf_fk(ARM_JOINTS, ARM_Q)
    actual = chain.link_transforms(ARM_Q)
    for link, matrix in expected.items():
        assert np.allclose(actual[link], matrix, atol=1e-9), link


def test_acc03_visual_fk_sampling_collision_and_frames_agree_after_motion(vendor_project):
    project, report, scene = vendor_project
    manifest = json.loads((project / report["manifest"]).read_text("utf-8"))
    gltf = GLTF2().load_binary(str(project / "build" / "scene.glb"))
    assert manifest["modules"]

    fk = _urdf_fk(ARM_JOINTS, ARM_Q)
    module_pose = scene.module_poses["robot_1"]
    state = scene.initial_state()
    state.joints["robot_1"] = np.asarray([ARM_Q[name] for name in ARM_Q], dtype=float)
    sampled = world_transforms(scene, state)
    module_glb = _world(gltf, _node(gltf, "robot_1"), ARM_Q)
    assert np.allclose(module_glb, sampled["robot_1"], atol=1e-6)

    link_nodes = {joint.child: f"robot_1.{joint.name}" for joint in ARM_JOINTS}
    for link, node_name in link_nodes.items():
        expected = module_pose @ fk[link]
        index = _node(gltf, node_name)
        # viewer（GLB extras.joint）、取樣與獨立 FK 三者一致
        assert np.allclose(_world(gltf, index, ARM_Q), expected, atol=1e-6), node_name
        assert np.allclose(sampled[node_name], expected, atol=1e-6), node_name
        if link in VISUAL_BOXES or link == "link3":
            visual = _child(gltf, index, "visual")
            assert visual is not None, link
            vertices = _apply(
                _world(gltf, visual, ARM_Q), _positions(gltf, gltf.nodes[visual].mesh)
            )
            assert _same_points(vertices, _apply(expected, _expected_visual(link)), 1e-2), link
        else:
            # world、tool0 只是參考座標，沒有外形也要能建置
            assert _child(gltf, index, "visual") is None, link

    # 碰撞零件：URDF <collision> 在 FK 位姿下的位置；比 visual 大，證明用的是原廠碰撞幾何。
    parts = {part.link: part for part in build_collision_parts(scene) if part.module == "robot_1"}
    for link, extents in COLLISION_BOXES.items():
        part = parts[link]
        world = _apply(sampled[part.name], part.vertices)
        xyz, rpy = VISUAL_ORIGINS.get(link, ((0.13, 0, 0), (0, 0, 0)))
        corners = trimesh.creation.box(extents=np.asarray(extents) * 1000).vertices
        expected = _apply(module_pose @ fk[link] @ _pose_m(xyz, rpy), corners)
        assert _same_points(world, expected, 1e-6), link
        visual = _apply(module_pose @ fk[link], _expected_visual(link))
        assert not _same_points(world, visual, 1.0), link
    # 沒有 <collision> 的 link 保守地以外形（凸包）當碰撞體，位置同樣跟著 FK。
    fallback = parts["link2"]
    expected = _apply(module_pose @ fk["link2"], _expected_visual("link2"))
    assert _same_points(_apply(sampled[fallback.name], fallback.vertices), expected, 1e-6)
    base = parts["base_link"]
    local = _apply(
        np.linalg.inv(module_pose @ fk["base_link"] @ _pose_m((0, 0, 0.055), (0, 0, 0))),
        _apply(sampled[base.name], base.vertices),
    )
    radius, length = (value * 1000 for value in BASE_COLLISION_CYLINDER)
    assert np.hypot(local[:, 0], local[:, 1]).max() == pytest.approx(radius, abs=1e-6)
    assert local[:, 2].min() == pytest.approx(-length / 2, abs=1e-6)
    assert local[:, 2].max() == pytest.approx(length / 2, abs=1e-6)

    # frame：flange 依登記的 link＋偏移，tool 再沿 flange +Z 偏移 TCP 長度。
    flange = (
        module_pose
        @ fk[FLANGE["link"]]
        @ _pose_m(np.asarray(FLANGE["xyz"]) / 1000.0, np.radians(FLANGE["rpy_deg"]))
    )
    tool = flange @ _pose_m((0, 0, TOOL_LENGTH_MM / 1000.0), (0, 0, 0))
    assert np.allclose(scene.resolve_frame("robot_1.flange", state), flange, atol=1e-6)
    assert np.allclose(scene.resolve_frame("robot_1.tool", state), tool, atol=1e-6)
    assert np.allclose(_world(gltf, _node(gltf, "robot_1.tool"), ARM_Q), tool, atol=1e-6)
    rest = scene.resolve_frame("robot_1.tool", scene.initial_state())
    assert not np.allclose(rest[:3, 3], tool[:3, 3], atol=1.0)


def test_real_vendor_is_not_marked_but_remaining_stub_is(vendor_project):
    project, report, _scene_model = vendor_project
    manifest = json.loads((project / report["manifest"]).read_text("utf-8"))
    modules = {module["id"]: module for module in manifest["modules"]}
    assert modules["robot_1"]["model_source"] == f"vendor-urdf:{ARM_ID}"
    assert modules["robot_1"]["approximated"] is False
    assert modules["robot_2"]["approximated"] is True
    assert modules["conveyor_1"]["approximated"] is False
    gltf = GLTF2().load_binary(str(project / "build" / "scene.glb"))
    assert gltf.nodes[_node(gltf, "robot_1")].extras["approximated"] is False
    assert gltf.nodes[_node(gltf, "robot_2")].extras["approximated"] is True
    assert any("robot_2" in message and "approximated" in message for message in report["warnings"])
    assert not any(
        "robot_1" in message and "approximated" in message for message in report["warnings"]
    )

    exported = export_project(project, ["report"], f"v{report['version']}")
    docx = next(
        Path(exported["directory"]) / name for name in exported["files"] if name.endswith(".docx")
    )
    lines = [paragraph.text for paragraph in Document(str(docx)).paragraphs]
    marked = [line for line in lines if line.startswith("近似廠商模型")]
    assert len(marked) == 1
    assert "robot_2" in marked[0] and "robot_1" not in marked[0]


def test_tool_behind_geometryless_flange_link_is_adjacent_to_its_mount(vendor_project):
    _project, _report, scene = vendor_project

    def part(link: str) -> CollisionPart:
        return CollisionPart(
            link, f"robot_1.{link}", "robot_1", link, np.zeros((0, 3)), None, False
        )

    # 原廠鏈是 link6 →（固定）flange（無外形）→（固定）tool：工具實際裝在 link6 上，
    # 兩者貼合不是干涉；但工具與前一節 link5 之間仍要檢查。
    assert _adjacent(scene, part(FLANGE["link"]), part("tool"))
    assert not _adjacent(scene, part("link5"), part("tool"))


def test_check_items_touching_approximated_models_are_annotated(vendor_project):
    _project, _report, scene = vendor_project
    items = [
        {"id": "a", "objects": ["robot_2.j3", "conveyor_1"], "source": "FCL"},
        {"id": "b", "objects": ["robot_1.j2", "conveyor_1"], "source": "FCL"},
    ]
    _mark_approximated_models(scene, items)
    assert items[0]["approximated_models"] == ["robot_2"]
    assert "approximated stub" in items[0]["source"]
    assert "approximated_models" not in items[1]
    assert items[1]["source"] == "FCL"


def test_payload_without_vendor_rating_is_reported_unevaluated(vendor_project, monkeypatch):
    project, _report, scene = vendor_project
    _project, workpiece, _cell, _process = validate_project(project)
    holding = {"nodes": {"workpiece": {"attached_to": [[1.0, "robot_1.tool"], [2.0, None]]}}}
    module = scene.modules["robot_1"]

    def payload_items(timeline):
        return [
            item for item in _hardware(scene, workpiece, timeline) if item["objects"] == ["robot_1"]
        ]

    rated = payload_items(holding)
    assert len(rated) == 1
    assert rated[0]["limit"] == pytest.approx(module.definition.payload_kg)
    assert "未評估" not in rated[0]["detail"]
    # 公開 URDF 沒有額定負載：實際夾持時必須明示未評估，而不是默默略過或判綠。
    unrated_definition = module.definition.model_copy(update={"payload_kg": None})
    monkeypatch.setattr(module, "definition", unrated_definition)
    unrated = payload_items(holding)
    assert len(unrated) == 1
    assert unrated[0]["severity"] == "yellow"
    assert "未評估" in unrated[0]["detail"]
    assert unrated[0]["value"] == pytest.approx(rated[0]["value"])
    assert payload_items({"nodes": {}}) == []


def _scara(directory: Path, *, extra_link: str = "") -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    joints = (
        JointSpec(
            "s1", "revolute", "base_link", "arm1", (0, 0, 0.4), lower=-2.5, upper=2.5, velocity=6.0
        ),
        JointSpec(
            "s2", "revolute", "arm1", "arm2", (0.325, 0, 0), lower=-2.5, upper=2.5, velocity=6.0
        ),
        JointSpec(
            "s3",
            "prismatic",
            "arm2",
            "quill",
            (0.275, 0, 0),
            axis=(0, 0, -1),
            lower=0.0,
            upper=0.2,
            velocity=1.0,
        ),
        JointSpec(
            "s4",
            "revolute",
            "quill",
            "flange_link",
            (0, 0, -0.05),
            lower=-6.2,
            upper=6.2,
            velocity=20.0,
        ),
    )
    box = '<visual><geometry><box size="0.05 0.05 0.05"/></geometry></visual>'
    links = {name: box for name in ("base_link", "arm1", "arm2", "quill", "flange_link")}
    if extra_link:
        links[extra_link] = ""
    urdf = directory / "scara.urdf"
    urdf.write_text(_urdf_text("scara", links, joints), encoding="utf-8")
    return {
        "id": "scara",
        "kind": "robot",
        "files": {"urdf": urdf.relative_to(directory.parent).as_posix()},
        "source_url": "test://scara",
        "downloaded": date.today().isoformat(),
        "sha256": {},
        "units_in_file": "m",
        "up_axis": "z",
        "approximated": False,
        "frames": {"flange": {"link": "flange_link"}},
        "limits": {},
    }


def test_scara_urdf_keeps_four_axes_and_ik_is_honest_about_tilted_targets(tmp_path):
    item = _scara(tmp_path / "scara")
    model = build_vendor_model(item, {"name": "scara"}, tmp_path)
    chain = model.chain
    assert [joint.type for joint in chain.active_joints] == [
        "revolute",
        "revolute",
        "prismatic",
        "revolute",
    ]
    assert len(model.definition.axes) == len(chain.active_joints)
    lower, upper = chain.limits[:, 0], chain.limits[:, 1]
    q = lower + (upper - lower) * np.asarray([0.6, 0.3, 0.5, 0.7])
    target = chain.fk(q)
    solved = solve_ik(chain, target, np.zeros(len(q)))
    assert solved.success
    assert np.allclose(chain.fk(solved.joints), target, atol=1e-2)
    # SCARA 的工具軸永遠鉛直：傾斜目標必須誠實失敗，而不是被當成六軸硬解。
    tilted = target.copy()
    tilted[:3, :3] = tilted[:3, :3] @ Rotation.from_euler("x", 20, degrees=True).as_matrix()
    failed = solve_ik(chain, tilted, np.zeros(len(q)))
    assert not failed.success
    assert failed.orientation_error_deg > 0.5


def test_urdf_link_named_like_cellforge_frames_is_rejected(tmp_path):
    item = _scara(tmp_path / "scara", extra_link="tool")
    with pytest.raises(VendorModelError, match="tool"):
        build_vendor_model(item, {"name": "scara"}, tmp_path)


def test_step_only_vendor_is_static_and_cannot_be_a_move_actor(tmp_path):
    step = tmp_path / "controller.step"
    cq.exporters.export(cq.Workplane().box(300, 200, 400), str(step))
    project = _getac_project(tmp_path, "step_only")
    add_vendor_file(project, "controller", "robot", str(step))
    manifest = VendorManifest.model_validate(load_yaml(project / "vendor" / "manifest.yaml"))
    items = {item.id: item.model_dump(mode="json") for item in manifest.vendors}
    cell = load_yaml(project / "cell.yaml")
    instance = next(
        module
        for machine in cell["machines"]
        for module in machine["modules"]
        if module["id"] == "robot_1"
    )
    with project_parts(project):
        built = build_module(
            ModuleInstance.model_validate({**instance, "part": None, "vendor": "controller"}),
            items,
        )
    assert built.chain is None
    assert built.definition.axes == []
    assert built.model_source == "vendor-static:controller"
    assert any("不能作為手臂" in message for message in built.warnings)

    _use_vendor(project, "robot_1", "controller")
    with pytest.raises(ProjectValidationError, match="手臂"):
        validate_project(project)


def test_vendor_file_changed_after_registration_fails_validation(tmp_path):
    urdf, meshes = _write_arm(tmp_path / "source")
    project = _getac_project(tmp_path, "tamper")
    add_vendor_urdf(project, ARM_ID, str(urdf), [str(path) for path in meshes], flange=FLANGE)
    _use_vendor(project, "robot_1", ARM_ID)
    validate_project(project)
    target = project / "vendor" / ARM_ID / "link1.stl"
    _box_file(target, (0.3, 0.3, 0.3))
    with pytest.raises(ProjectValidationError, match="雜湊"):
        validate_project(project)


def test_urdf_registration_requires_every_referenced_mesh(tmp_path):
    urdf, meshes = _write_arm(tmp_path / "source")
    project = _getac_project(tmp_path, "missing")
    with pytest.raises(ValueError, match="網格"):
        add_vendor_urdf(project, ARM_ID, str(urdf), [str(path) for path in meshes[1:]])
    shutil.rmtree(project / "vendor" / ARM_ID)
    add_vendor_urdf(project, ARM_ID, str(urdf), [str(path) for path in meshes])


def test_only_approximated_vendor_modules_freeze_the_robot_stub(tmp_path):
    library_root = Path(__file__).resolve().parents[1] / "library"
    source = tmp_path / "source"
    (source / "vendor").mkdir(parents=True)
    dump_yaml(
        source / "cell.yaml",
        {"machines": [{"id": "m", "modules": [{"id": "robot_1", "vendor": "arm"}]}]},
    )

    def used(approximated: bool) -> set[str]:
        dump_yaml(
            source / "vendor" / "manifest.yaml",
            {"vendors": [{"id": "arm", "kind": "robot", "approximated": approximated}]},
        )
        return set(used_library_files(source, library_root))

    assert "library/robot_stub.py" in used(True)
    assert "library/robot_stub.py" not in used(False)
