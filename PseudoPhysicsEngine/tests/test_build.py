import json
import shutil
from pathlib import Path

from pygltflib import GLTF2

from cellforge.build.pipeline import build_project
from cellforge.build.stepio import inspect_step

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


def test_l0_build_round_trips_step_and_names(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(SOURCE, project, ignore=shutil.ignore_patterns("build"))
    report = build_project(project)
    assert report["duration_s"] >= 40
    inspection = inspect_step(project / "build" / "scene.step")
    assert [part.part_name for part in inspection.components] == EXPECTED
    assert [part.instance_name for part in inspection.components] == EXPECTED
    validation = json.loads((project / "build" / "step_validation.json").read_text("utf-8"))
    assert validation["top_level_part_count"] == 7
    assert validation["total_component_count"] == 46
    assert validation["assembly_node_count"] == 8
    assert validation["leaf_part_count"] == 39
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
        assert [gltf.nodes[index].name for index in module.children] == ["visual", "collision"]
        assert all(parent_counts[index] == 1 for index in module.children)
        assert module.extras["trust"] == "inferred"
