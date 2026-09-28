"""廠商模型轉接：運動鏈、各 link 外形與碰撞幾何都取自原廠檔，不以品牌或型號名稱推定。

- 有 URDF：URDF 提供關節鏈（公尺／弧度換算成 mm／度）、各 link 的 visual 與 collision 幾何；
  網格轉成 faceted B-rep 寫入 STEP（以網格雜湊快取），GLB 與碰撞直接使用原始網格。
- 只有 STEP／網格：只當靜態外形，不宣稱任何關節軸或運動限制。
- `approximated: true` 的條目仍由 `library/robot_stub.py` 參數化近似，並在各處標示。
"""

from __future__ import annotations

import hashlib
import os
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from cellforge.kinematics.chain import Chain, Joint
from cellforge.schema import Frame, ModuleAxis, ModuleDef, ModuleMeta

# 單一 link 的網格上限；超過時要求改用較輕的原廠網格，不在建置時默默簡化。
LINK_TRIANGLE_BUDGET = 50_000
DEFAULT_COLOR = (0.86, 0.87, 0.88, 1.0)
URDF_UNITS_MM = 1000.0


class VendorModelError(ValueError):
    """原廠檔不足或不一致；訊息為繁體中文，直接顯示給使用者與代理。"""


@dataclass
class VendorModel:
    assembly: cq.Assembly
    definition: ModuleDef
    chain: Chain | None
    model_source: str
    warnings: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


def vendor_file(project_root: Path, item: dict[str, Any], key: str) -> Path:
    relative = item.get("files", {}).get(key)
    if not relative:
        raise VendorModelError(f"廠商條目 {item.get('id')} 沒有 {key} 檔")
    root = project_root.resolve()
    path = (root / relative).resolve()
    if root not in path.parents:
        raise VendorModelError(f"廠商檔路徑超出案子目錄：{relative}")
    if not path.is_file():
        raise VendorModelError(f"找不到廠商檔：{relative}")
    return path


def verify_vendor_files(project_root: Path, item: dict[str, Any]) -> None:
    """Every file listed for a vendor item must still match its recorded SHA-256."""

    recorded = item.get("sha256")
    for key, relative in (item.get("files") or {}).items():
        path = vendor_file(project_root, item, key)
        expected = recorded.get(key) if isinstance(recorded, dict) else recorded
        if expected is None:
            raise VendorModelError(f"廠商條目 {item['id']} 的 {relative} 沒有記錄 SHA-256")
        if len(item["files"]) > 1 and not isinstance(recorded, dict):
            raise VendorModelError(f"廠商條目 {item['id']} 有多個檔案，sha256 必須逐檔記錄")
        if _sha256_file(path) != str(expected).lower():
            raise VendorModelError(f"廠商檔雜湊與 manifest 不符：{relative}；請重新取得並登記")


def build_vendor_model(
    item: dict[str, Any],
    instance_params: dict[str, Any],
    project_root: Path,
    *,
    cache_root: Path | None = None,
    load_tool=None,
) -> VendorModel:
    files = item.get("files") or {}
    if "urdf" in files:
        return _urdf_model(item, instance_params, project_root, cache_root, load_tool)
    for key in ("step", "stp"):
        if key in files:
            return _static_model(item, project_root, key, cache_root)
    mesh_keys = [key for key in files if Path(files[key]).suffix.lower() in {".stl", ".obj"}]
    if mesh_keys:
        return _static_model(item, project_root, mesh_keys[0], cache_root)
    raise VendorModelError(
        f"廠商條目 {item['id']} 沒有可用的 URDF、STEP 或網格；取不到原廠檔時請改用 "
        "cell vendor stub 並標示 approximated"
    )


def _urdf_model(
    item: dict[str, Any],
    params: dict[str, Any],
    project_root: Path,
    cache_root: Path | None,
    load_tool,
) -> VendorModel:
    urdf = vendor_file(project_root, item, "urdf")
    root = ET.parse(urdf).getroot()
    base_chain = Chain.from_urdf(urdf)
    warnings: list[str] = []
    frames = item.get("frames") or {}
    flange = frames.get("flange")
    active = base_chain.active_joints
    if not active:
        raise VendorModelError(f"廠商 URDF {urdf.name} 沒有可動關節，不能作為手臂")
    if flange and flange.get("link"):
        flange_link = str(flange["link"])
        flange_local = _pose(flange.get("xyz"), flange.get("rpy_deg"))
    else:
        flange_link = active[-1].child
        flange_local = np.eye(4)
        warnings.append(
            f"廠商條目 {item['id']} 未宣告 flange frame，暫以 URDF 末端 link {flange_link} 原點"
            "作為法蘭；法蘭面位置需以型錄確認"
        )
    links = {link.get("name") for link in root.findall("link")}
    if flange_link not in links:
        raise VendorModelError(f"flange frame 引用 URDF 中不存在的 link：{flange_link}")

    # flange 與 tool 都是運動鏈上的固定 link，frame 解析、GLB 節點與碰撞都由同一條 FK 給出。
    extra: list[Joint] = []
    reuse_flange = flange_link == "flange" and np.allclose(flange_local, np.eye(4))
    joint_ids = {joint.id for joint in base_chain.joints}
    for reserved in ("flange", "tool"):
        if reserved == "flange" and reuse_flange:
            continue
        if reserved in links or reserved in joint_ids:
            raise VendorModelError(
                f"URDF 已有名為 {reserved} 的 link 或關節，與 CellForge 的 {reserved} frame 衝突；"
                "請以該 link 作為 flange 並設零偏移，或改用其他名稱"
            )
    if not reuse_flange:
        extra.append(_fixed_joint("flange", flange_link, "flange", flange_local))
    tool = _tool_spec(params.get("tool"), load_tool)
    extra.append(_fixed_joint("tool", "flange", "tool", _pose((0, 0, tool[0]))))
    chain = Chain([*base_chain.joints, *extra], tip_link="tool", name=str(item["id"]))
    rest = chain.link_transforms(np.zeros(len(chain.active_joints)))

    assembly = cq.Assembly(name=str(params.get("name", item["id"])))
    for link in root.findall("link"):
        name = str(link.get("name"))
        visual = _link_geometry(link, "visual", urdf, project_root)
        if visual is None:
            continue
        collision = _link_geometry(link, "collision", urdf, project_root)
        if collision is None:
            # 未宣告 <collision> 時保守地以外形本身當碰撞體（必須是獨立副本，下面會各自變換）。
            collision = visual.copy()
        if len(visual.faces) > LINK_TRIANGLE_BUDGET:
            raise VendorModelError(
                f"廠商網格 {name} 有 {len(visual.faces)} 個三角形，超過每個 link "
                f"{LINK_TRIANGLE_BUDGET} 的上限；請改用原廠提供的輕量網格"
            )
        world = rest[name]
        visual.apply_transform(world)
        collision.apply_transform(world)
        assembly.add(
            _faceted_shape(visual, cache_root),
            name=name,
            color=cq.Color(*_link_color(link, root)),
            metadata={"link": name, "mesh": visual, "collision_mesh": collision},
        )
    if tool[2] is not None:
        assembly.add(
            tool[2],
            name="tool",
            color=cq.Color(0.18, 0.21, 0.24),
            loc=_location(rest["flange"]),
            metadata={"link": "tool"},
        )
    if not assembly.objects or all(
        child.obj is None for name, child in assembly.objects.items() if name != assembly.name
    ):
        raise VendorModelError(f"廠商 URDF {urdf.name} 沒有任何 visual 幾何")

    limits = item.get("limits") or {}
    definition = ModuleDef(
        id=str(item["id"]),
        params_schema={"type": "object"},
        frames={
            "mount": Frame(link=chain.base_link),
            "base": Frame(link=chain.base_link),
            "flange": Frame(link="flange"),
            "tool": Frame(link="tool"),
        },
        axes=[_axis(joint) for joint in chain.active_joints],
        collision="hull",
        payload_kg=float(limits["payload_kg"]) if "payload_kg" in limits else None,
        tool_mass_kg=tool[1],
        vendor=str(item["id"]),
        part_no=item.get("part_no"),
        meta=ModuleMeta(
            basis=f"原廠 URDF：{item.get('source_url')}（{item.get('downloaded')}）",
        ),
    )
    return VendorModel(
        assembly=assembly,
        definition=definition,
        chain=chain,
        model_source=f"vendor-urdf:{item['id']}",
        warnings=warnings,
        params=dict(params),
    )


def _static_model(
    item: dict[str, Any], project_root: Path, key: str, cache_root: Path | None
) -> VendorModel:
    path = vendor_file(project_root, item, key)
    scale = {"inch": 25.4, "m": URDF_UNITS_MM}.get(str(item.get("units_in_file")), 1.0)
    orientation = _up_axis_matrix(item.get("up_axis", "z"))
    if path.suffix.lower() in {".step", ".stp"}:
        shape = cq.importers.importStep(str(path)).val()
        matrix = orientation.copy()
        matrix[:3, :3] *= scale
        if not np.allclose(matrix, np.eye(4)):
            shape = shape.transformGeometry(cq.Matrix(matrix.tolist()))
        mesh = None
    else:
        mesh = _load_mesh(path)
        mesh.apply_scale(scale)
        mesh.apply_transform(orientation)
        shape = _faceted_shape(mesh, cache_root)
    assembly = cq.Assembly(name=str(item["id"]))
    metadata: dict[str, Any] = {"link": "base"}
    if mesh is not None:
        metadata.update({"mesh": mesh, "collision_mesh": mesh})
    assembly.add(shape, name="base", color=cq.Color(*DEFAULT_COLOR), metadata=metadata)
    frames = {
        name: Frame(
            xyz=tuple(value.get("xyz", (0, 0, 0))),
            rpy_deg=tuple(value.get("rpy_deg", (0, 0, 0))),
        )
        for name, value in (item.get("frames") or {}).items()
        if isinstance(value, dict)
    }
    frames.setdefault("mount", Frame())
    definition = ModuleDef(
        id=str(item["id"]),
        frames=frames,
        collision="hull",
        vendor=str(item["id"]),
        part_no=item.get("part_no"),
        meta=ModuleMeta(basis=f"原廠外形：{item.get('source_url')}（{item.get('downloaded')}）"),
    )
    warning = (
        f"廠商條目 {item['id']} 只有 {path.suffix.lstrip('.').upper()} 外形：關節軸與運動限制未知，"
        "以靜態模組處理，不能作為手臂 actor"
    )
    return VendorModel(assembly, definition, None, f"vendor-static:{item['id']}", [warning])


def _link_geometry(
    link: ET.Element, tag: str, urdf: Path, project_root: Path
) -> trimesh.Trimesh | None:
    meshes = []
    for element in link.findall(tag):
        geometry = element.find("geometry")
        if geometry is None:
            continue
        origin = element.find("origin")
        local = _urdf_origin(origin)
        mesh = _geometry_mesh(geometry, urdf, project_root)
        if mesh is None:
            continue
        mesh.apply_transform(local)
        meshes.append(mesh)
    if not meshes:
        return None
    return trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]


def _geometry_mesh(geometry: ET.Element, urdf: Path, project_root: Path) -> trimesh.Trimesh | None:
    mesh_element = geometry.find("mesh")
    if mesh_element is not None:
        path = _resolve_mesh(str(mesh_element.get("filename", "")), urdf, project_root)
        mesh = _load_mesh(path)
        scale = _numbers(mesh_element.get("scale"), (1.0, 1.0, 1.0))
        mesh.apply_scale(np.asarray(scale) * URDF_UNITS_MM)
        return mesh
    box = geometry.find("box")
    if box is not None:
        size = np.asarray(_numbers(box.get("size"), (0.0, 0.0, 0.0))) * URDF_UNITS_MM
        return trimesh.creation.box(extents=size)
    cylinder = geometry.find("cylinder")
    if cylinder is not None:
        return trimesh.creation.cylinder(
            radius=float(cylinder.get("radius", 0)) * URDF_UNITS_MM,
            height=float(cylinder.get("length", 0)) * URDF_UNITS_MM,
            sections=32,
        )
    sphere = geometry.find("sphere")
    if sphere is not None:
        return trimesh.creation.icosphere(
            subdivisions=2, radius=float(sphere.get("radius", 0)) * URDF_UNITS_MM
        )
    return None


def _resolve_mesh(filename: str, urdf: Path, project_root: Path) -> Path:
    """Resolve package:// and relative mesh references inside the vendor folder only."""

    root = project_root.resolve()
    text = filename.replace("\\", "/")
    for prefix in ("package://", "file://"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    parts = [part for part in text.split("/") if part and part != "."]
    base = urdf.parent.resolve()
    for start in range(len(parts)):
        candidate = (base / Path(*parts[start:])).resolve()
        if root in candidate.parents and candidate.is_file():
            return candidate
    raise VendorModelError(f"URDF 引用的網格找不到或不在案子目錄內：{filename}")


def _load_mesh(path: Path) -> trimesh.Trimesh:
    try:
        loaded = trimesh.load(path, force="mesh", process=False)
    except (ValueError, ImportError, OSError) as error:
        raise VendorModelError(f"無法讀取廠商網格 {path.name}：{error}") from error
    if not isinstance(loaded, trimesh.Trimesh) or not len(loaded.faces):
        raise VendorModelError(f"廠商網格 {path.name} 沒有三角面")
    return trimesh.Trimesh(
        vertices=loaded.vertices.copy(), faces=loaded.faces.copy(), process=False
    )


def _faceted_shape(mesh: trimesh.Trimesh, cache_root: Path | None) -> cq.Shape:
    """Faceted B-rep for STEP; cached by the exact vertex/face bytes."""

    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakePolygon,
        BRepBuilderAPI_MakeSolid,
        BRepBuilderAPI_Sewing,
    )
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopoDS import TopoDS

    vertices = np.ascontiguousarray(mesh.vertices, dtype=np.float64)
    faces = np.ascontiguousarray(mesh.faces, dtype=np.int64)
    key = hashlib.sha256(vertices.tobytes() + b"|" + faces.tobytes()).hexdigest()
    cache_file = (cache_root / "vendor-brep" / f"{key}.brep") if cache_root else None
    if cache_file is not None and cache_file.is_file():
        return cq.Shape.importBrep(str(cache_file))
    sewing = BRepBuilderAPI_Sewing(1e-3)
    for a, b, c in faces:
        points = [gp_Pnt(*vertices[index]) for index in (a, b, c)]
        if points[0].Distance(points[1]) < 1e-9 or points[1].Distance(points[2]) < 1e-9:
            continue
        polygon = BRepBuilderAPI_MakePolygon(*points, True)
        if polygon.IsDone():
            face = BRepBuilderAPI_MakeFace(polygon.Wire())
            if face.IsDone():
                sewing.Add(face.Face())
    sewing.Perform()
    sewed = sewing.SewedShape()
    shape = sewed
    if sewed.ShapeType() == TopAbs_SHELL:
        solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sewed))
        if solid.IsDone():
            shape = solid.Solid()
    result = cq.Shape.cast(shape)
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_name(f".{key}.{uuid.uuid4().hex}.tmp")
        result.exportBrep(str(temporary))
        os.replace(temporary, cache_file)
    return result


def _tool_spec(tool: Any, load_tool) -> tuple[float, float | None, cq.Shape | None]:
    """(TCP distance from flange along flange +Z, tool mass, tool geometry in flange frame)."""

    if not tool:
        return 0.0, None, None
    if not isinstance(tool, dict):
        raise VendorModelError("tool 必須是參數物件")
    if "part" not in tool:
        length = float(tool.get("length_mm", 0.0))
        mass = float(tool["mass_kg"]) if "mass_kg" in tool else None
        return length, mass, None
    if load_tool is None:
        raise VendorModelError("無法載入工具模組")
    module = load_tool(str(tool["part"]))
    tool_params = dict(tool.get("params", {}))
    factory = getattr(module, "module_definition", None)
    definition = factory(tool_params) if callable(factory) else module.MODULE
    tcp = definition.frames.get("tool_center_point")
    if tcp is None:
        raise VendorModelError(f"工具模組 {tool['part']} 沒有 tool_center_point frame")
    mass = float(tool.get("mass_kg", definition.payload_kg or 0.0)) or None
    shape = module.build(tool_params).toCompound()
    return float(tcp.xyz[2]), mass, shape


def _link_color(link: ET.Element, root: ET.Element) -> tuple[float, ...]:
    material = link.find("visual/material")
    if material is None:
        return DEFAULT_COLOR
    color = material.find("color")
    if color is None and material.get("name"):
        named = root.find(f"material[@name='{material.get('name')}']/color")
        color = named
    if color is None or not color.get("rgba"):
        return DEFAULT_COLOR
    values = [float(value) for value in str(color.get("rgba")).split()]
    return tuple(values[:4]) if len(values) >= 4 else DEFAULT_COLOR


def _axis(joint: Joint) -> ModuleAxis:
    if joint.type == "prismatic":
        return ModuleAxis(
            id=joint.id,
            type="prismatic",
            parent=joint.parent,
            child=joint.child,
            origin={"xyz": joint.origin_xyz, "rpy_deg": joint.origin_rpy_deg},
            axis=joint.axis,
            range_mm=joint.limit or (-1e6, 1e6),
            max_speed_mm_s=joint.max_speed,
        )
    return ModuleAxis(
        id=joint.id,
        type="revolute",
        parent=joint.parent,
        child=joint.child,
        origin={"xyz": joint.origin_xyz, "rpy_deg": joint.origin_rpy_deg},
        axis=joint.axis,
        range_deg=joint.limit or (-360.0, 360.0),
        max_speed_dps=joint.max_speed,
    )


def _fixed_joint(joint_id: str, parent: str, child: str, origin: np.ndarray) -> Joint:
    return Joint(
        id=joint_id,
        type="fixed",
        parent=parent,
        child=child,
        origin_xyz=tuple(float(value) for value in origin[:3, 3]),
        origin_rpy_deg=_rpy(origin),
    )


def _pose(xyz: Any, rpy_deg: Any = None) -> np.ndarray:
    matrix = np.eye(4)
    rpy = np.zeros(3) if rpy_deg is None else np.asarray(rpy_deg, dtype=float)
    matrix[:3, :3] = Rotation.from_euler("xyz", np.radians(rpy)).as_matrix()
    matrix[:3, 3] = np.zeros(3) if xyz is None else np.asarray(xyz, dtype=float)
    return matrix


def _rpy(matrix: np.ndarray) -> tuple[float, float, float]:
    values = Rotation.from_matrix(matrix[:3, :3]).as_euler("xyz", degrees=True)
    return tuple(float(value) for value in values)


def _urdf_origin(origin: ET.Element | None) -> np.ndarray:
    if origin is None:
        return np.eye(4)
    xyz = np.asarray(_numbers(origin.get("xyz"), (0.0, 0.0, 0.0))) * URDF_UNITS_MM
    rpy = _numbers(origin.get("rpy"), (0.0, 0.0, 0.0))
    return _pose(xyz, np.degrees(rpy))


def _numbers(value: str | None, default: tuple[float, float, float]) -> tuple[float, ...]:
    if not value:
        return default
    return tuple(float(part) for part in value.split())


def _up_axis_matrix(up_axis: str | None) -> np.ndarray:
    """Rotation that brings a vendor file's up axis onto CellForge +Z."""

    matrix = np.eye(4)
    if up_axis == "y":
        matrix[:3, :3] = Rotation.from_euler("x", 90, degrees=True).as_matrix()
    elif up_axis == "x":
        matrix[:3, :3] = Rotation.from_euler("y", -90, degrees=True).as_matrix()
    return matrix


def _location(matrix: np.ndarray) -> cq.Location:
    from OCP.gp import gp_Trsf

    transform = gp_Trsf()
    transform.SetValues(*(float(value) for value in matrix[:3, :].ravel()))
    return cq.Location(transform)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
