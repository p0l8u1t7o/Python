"""DEV-003：完整來源 manifest、不可變 staging 與原子發布。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

import cellforge.build.pipeline as pipeline
from cellforge.build.pipeline import BuildError, build_project
from cellforge.filelock import HeldLock
from cellforge.project import create_project, source_root
from cellforge.schema import VersionManifest
from cellforge.version_store import (
    STAGING_DIR,
    StagedBuild,
    VersionPublishError,
    reserve_version,
    used_library_files,
    verify_library_unchanged,
)
from cellforge.versioning import VersionContext, version_dirs
from cellforge.yamlio import dump_yaml, load_yaml

ROOT = Path(__file__).resolve().parents[1]
PART_ID = "local_stand"
INPUT_NAME = "inputs/evidence_photo.jpg"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_project(root: Path, name: str = "版本快照案") -> Path:
    return create_project(
        root / "store",
        {"name": name, "created": date.today().isoformat()},
        seed_example="getac_qc",
    )


def _use_project_part(project: Path) -> str:
    """把一個站別模組改成案內 parts/ 模組，回傳被替換的 module id。"""
    shutil.copy2(ROOT / "library" / "fixture_stand.py", project / "parts" / f"{PART_ID}.py")
    cell = load_yaml(project / "cell.yaml")
    for machine in cell["machines"]:
        for module in machine["modules"]:
            if str(module.get("part", "")).endswith("fixture_stand.py"):
                module["part"] = f"parts/{PART_ID}.py"
                dump_yaml(project / "cell.yaml", cell)
                return str(module["id"])
    raise AssertionError("範例沒有 fixture_stand 模組")


def _register_input(project: Path, payload: bytes) -> None:
    path = project / INPUT_NAME
    path.write_bytes(payload)
    manifest = load_yaml(project / "inputs" / "manifest.yaml") or {}
    manifest.setdefault("files", []).append(
        {
            "path": INPUT_NAME,
            "kind": "product_photo",
            "note": "版本快照測試證據",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "added": datetime.now().astimezone().isoformat(),
        }
    )
    dump_yaml(project / "inputs" / "manifest.yaml", manifest)


def _cli_build(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "cellforge.cli", "build", "--project", str(project), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
    )


def test_manifest_freezes_sources_library_evidence_and_modules(tmp_path: Path):
    project = _make_project(tmp_path)
    part_module = _use_project_part(project)
    _register_input(project, b"\xff\xd8 fake jpeg evidence \xff\xd9")
    report = build_project(project, "L0")
    context = VersionContext.open(project, report["version_id"])
    manifest = VersionManifest.model_validate(context.manifest)
    assert manifest.version == report["version_id"] == context.name
    assert manifest.build.status == "succeeded"
    assert manifest.engineering.status == "not_evaluated"

    sources = {item.path: item for item in manifest.sources}
    for relative in (
        "project.yaml",
        "cell.yaml",
        "process.yaml",
        "workpiece.yaml",
        "animation/sequence.py",
        "analysis/questions.yaml",
        "analysis/assumptions.yaml",
        "inputs/manifest.yaml",
        f"parts/{PART_ID}.py",
        INPUT_NAME,
    ):
        assert relative in sources, relative
        frozen = context.source(relative, "測試")
        assert _sha256(frozen) == sources[relative].sha256
    evidence = sources[INPUT_NAME]
    assert evidence.stored == "object"
    assert sources["inputs/manifest.yaml"].stored == "copy"
    object_path = project / ".cellforge" / "objects" / "sha256" / evidence.sha256[:2]
    assert (object_path / evidence.sha256).is_file()

    cell = load_yaml(project / "cell.yaml")
    referenced = {
        module["part"]
        for machine in cell["machines"]
        for module in machine["modules"]
        if str(module.get("part", "")).startswith("library/")
    }
    tools = {
        module["params"]["tool"]["part"]
        for machine in cell["machines"]
        for module in machine["modules"]
        if isinstance(module.get("params", {}).get("tool"), dict)
    }
    library = {item.path: item for item in manifest.library}
    assert referenced | tools | {"library/__init__.py"} <= library.keys()
    for relative, item in library.items():
        assert _sha256(context.directory / relative) == item.sha256
        assert _sha256(source_root() / relative) == item.sha256

    modules = {item.id: item for item in manifest.modules}
    module_ids = {module["id"] for machine in cell["machines"] for module in machine["modules"]}
    assert modules.keys() == module_ids
    assert modules[part_module].module_file == f"parts/{PART_ID}.py"
    assert modules[part_module].module_sha256 == sources[f"parts/{PART_ID}.py"].sha256
    for item in modules.values():
        assert item.params.items() <= item.expanded_params.items()

    artifacts = {item.path: item for item in manifest.artifacts}
    assert {"scene.step", "scene.glb", "timeline.json", "step_validation.json"} <= artifacts.keys()
    for name, item in artifacts.items():
        assert _sha256(context.directory / name) == item.sha256
    assert manifest.engine.python and manifest.schema_fingerprint

    # 工作區證據被刪、parts 被改，都不影響已封存的 v1。
    frozen_part = _sha256(context.source(f"parts/{PART_ID}.py", "測試"))
    (project / INPUT_NAME).unlink()
    (project / "parts" / f"{PART_ID}.py").write_text("# 改壞的模組\n", encoding="utf-8")
    assert _sha256(context.source(INPUT_NAME, "測試")) == evidence.sha256
    assert _sha256(context.source(f"parts/{PART_ID}.py", "測試")) == frozen_part


def test_workspace_edit_during_build_does_not_leak_into_version(tmp_path: Path, monkeypatch):
    project = _make_project(tmp_path)
    original = pipeline._build_into
    added = "mid_build_stand"

    def edit_workspace_then_build(*args, **kwargs):
        cell = load_yaml(project / "cell.yaml")
        cell["machines"][0]["modules"].append(
            {
                "id": added,
                "part": "library/fixture_stand.py",
                "params": {},
                "pose": {"xyz": [0, -2500, 0], "rpy_deg": [0, 0, 0], "trust": "inferred"},
            }
        )
        dump_yaml(project / "cell.yaml", cell)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "_build_into", edit_workspace_then_build)
    first = build_project(project, "L0")
    monkeypatch.setattr(pipeline, "_build_into", original)
    v1 = VersionContext.open(project, first["version_id"])
    assert added not in v1.artifact_json("step_validation.json", "測試")["expected_names"]
    assert added not in v1.source("cell.yaml", "測試").read_text("utf-8")

    second = build_project(project, "L0")
    v2 = VersionContext.open(project, second["version_id"])
    assert added in v2.artifact_json("step_validation.json", "測試")["expected_names"]


def test_failed_build_publishes_nothing_and_releases_the_number(tmp_path: Path, monkeypatch):
    project = _make_project(tmp_path)

    def broken_glb(*_args, **_kwargs):
        raise RuntimeError("模擬 GLB 輸出中斷")

    monkeypatch.setattr(pipeline, "export_glb", broken_glb)
    with pytest.raises(RuntimeError, match="模擬 GLB 輸出中斷"):
        build_project(project, "L0")
    store = project / ".cellforge"
    assert version_dirs(project) == []
    assert not any((store / STAGING_DIR).iterdir())
    assert not list((store / "_reserved").glob("*.lock"))
    assert not (project / "build" / "scene.step").exists()

    monkeypatch.undo()
    assert build_project(project, "L0")["version_id"] == "v1"


def test_verification_failure_blocks_publish(tmp_path: Path, monkeypatch):
    project = _make_project(tmp_path)
    original = pipeline._build_into

    def truncate_timeline(*args, **kwargs):
        report, modules = original(*args, **kwargs)
        (args[1] / "timeline.json").write_text("", encoding="utf-8")
        return report, modules

    monkeypatch.setattr(pipeline, "_build_into", truncate_timeline)
    with pytest.raises(BuildError, match="timeline.json"):
        build_project(project, "L0")
    assert version_dirs(project) == []


def test_crashed_reservation_and_staging_are_reclaimed(tmp_path: Path):
    project = _make_project(tmp_path)
    store = project / ".cellforge"
    # 模擬崩潰的建置：保留檔還在但沒有程序持有鎖，staging 殘留半成品。
    (store / "_reserved").mkdir(parents=True)
    (store / "_reserved" / "v1.lock").write_bytes(b"")
    orphan = store / STAGING_DIR / "v1-deadbeef"
    orphan.mkdir(parents=True)
    (orphan / "scene.step").write_text("半成品", encoding="utf-8")

    held, number = reserve_version(project)
    try:
        assert number == 1
        assert not orphan.exists()
        # 另一個存活中的保留佔住 v1 時，下一個保留必須拿到不同的號碼。
        second, second_number = reserve_version(project)
        second.release(remove=True)
        assert second_number == 2
    finally:
        held.release(remove=True)


def test_reservation_lock_excludes_other_handles(tmp_path: Path):
    first = HeldLock(tmp_path / "v1.lock")
    second = HeldLock(tmp_path / "v1.lock")
    assert first.try_acquire()
    try:
        assert not second.try_acquire()
    finally:
        first.release()
    assert second.try_acquire()
    second.release(remove=True)


def test_concurrent_cli_builds_publish_distinct_consistent_versions(tmp_path: Path):
    project = _make_project(tmp_path)
    command = [sys.executable, "-m", "cellforge.cli", "build", "--project", str(project), "--json"]
    processes = [
        subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        for _ in range(2)
    ]
    outputs = [process.communicate(timeout=600) for process in processes]
    assert [process.returncode for process in processes] == [0, 0], outputs
    reports = [json.loads(stdout.strip().splitlines()[-1]) for stdout, _stderr in outputs]
    assert sorted(report["version_id"] for report in reports) == ["v1", "v2"]
    for directory in version_dirs(project):
        manifest = VersionManifest.model_validate_json(
            (directory / "manifest.json").read_text("utf-8")
        )
        assert manifest.version == directory.name
        for item in manifest.artifacts:
            assert _sha256(directory / item.path) == item.sha256
    marker = json.loads((project / "build" / ".cellforge_version.json").read_text("utf-8"))
    assert marker["version"] == "v2"
    assert _sha256(project / "build" / "scene.glb") == _sha256(
        project / ".cellforge" / "v2" / "scene.glb"
    )


def test_cli_builds_project_parts_module(tmp_path: Path):
    project = _make_project(tmp_path)
    _use_project_part(project)
    completed = _cli_build(project)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    assert report["status"] == "ok"
    assert (project / ".cellforge" / report["version_id"] / "source" / "parts").is_dir()


def test_library_change_during_build_is_detected(tmp_path: Path):
    library_root = tmp_path / "platform" / "library"
    shutil.copytree(ROOT / "library", library_root)
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    shutil.copy2(ROOT / "examples" / "getac_qc" / "handwritten" / "cell.yaml", source_dir)
    used = used_library_files(source_dir, library_root)
    assert "library/part_stopper.py" not in used
    assert "library/conveyor.py" in used
    # part_stopper 以 from library.conveyor import … 引用輸送段：遞移相依也要凍結。
    stopper_dir = tmp_path / "stopper_source"
    stopper_dir.mkdir()
    dump_yaml(
        stopper_dir / "cell.yaml",
        {"machines": [{"id": "m", "modules": [{"id": "s", "part": "library/part_stopper.py"}]}]},
    )
    assert {"library/part_stopper.py", "library/conveyor.py"} <= set(
        used_library_files(stopper_dir, library_root)
    )
    stage = StagedBuild(project=tmp_path, number=1, directory=tmp_path / "stage", started=None)
    stage.library = [
        {"path": relative, "sha256": _sha256(library_root.parent / relative)} for relative in used
    ]
    verify_library_unchanged(stage, library_root)
    (library_root / "conveyor.py").write_text("# 建置期間被改寫\n", encoding="utf-8")
    with pytest.raises(VersionPublishError, match="library/conveyor.py"):
        verify_library_unchanged(stage, library_root)
