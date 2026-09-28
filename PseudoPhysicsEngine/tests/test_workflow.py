"""intake → first_build 前置狀態、job 版本歸屬與版本回讀驗證。"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path

import pytest

from cellforge.build.pipeline import build_project
from cellforge.project import create_project
from cellforge.schema import VersionManifest
from cellforge.version_store import BUILD_JOB_ENV, BUILD_ORIGIN_ENV
from cellforge.version_verify import VersionVerificationError, verify_version
from cellforge.versioning import VersionIncompleteError
from cellforge.workflow import (
    WorkflowPreconditionError,
    inputs_fingerprint,
    record_intake,
    require_first_build_ready,
    versions_for_job,
)
from cellforge.yamlio import dump_yaml, load_yaml


def _project(root: Path) -> Path:
    return create_project(
        root / "workflow",
        {"name": "流程狀態案", "created": date.today().isoformat()},
        seed_example="getac_qc",
    )


def _add_input(project: Path, name: str, payload: bytes) -> None:
    (project / "inputs" / name).write_bytes(payload)
    manifest = load_yaml(project / "inputs" / "manifest.yaml") or {}
    manifest.setdefault("files", []).append(
        {
            "path": f"inputs/{name}",
            "kind": "product_photo",
            "note": "",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "added": datetime.now().astimezone().isoformat(),
        }
    )
    dump_yaml(project / "inputs" / "manifest.yaml", manifest)


def _record(project: Path, status: str, mode: str = "local", **extra) -> None:
    record_intake(
        project,
        job_id="intake-job",
        mode=mode,
        status=status,
        started=datetime.now().astimezone().isoformat(),
        fingerprint=inputs_fingerprint(project),
        **extra,
    )


def test_first_build_requires_fresh_successful_intake_of_matching_mode(tmp_path: Path):
    project = _project(tmp_path)
    with pytest.raises(WorkflowPreconditionError, match="尚未完成 intake"):
        require_first_build_ready(project, "local")
    _record(project, "failed", error="Claude 視覺判讀超時")
    with pytest.raises(WorkflowPreconditionError, match="failed.*視覺判讀超時"):
        require_first_build_ready(project, "local")
    _record(project, "cancelled")
    with pytest.raises(WorkflowPreconditionError, match="cancelled"):
        require_first_build_ready(project, "local")

    _record(project, "succeeded")
    assert require_first_build_ready(project, "local")["job_id"] == "intake-job"
    # 正式代理模式不接受離線 runner 的 intake。
    with pytest.raises(WorkflowPreconditionError, match="離線 runner"):
        require_first_build_ready(project, "claude")
    _record(project, "succeeded", mode="claude")
    assert require_first_build_ready(project, "claude")["mode"] == "claude"

    # intake 之後新增證據：結果過期，直到重新 intake。
    _add_input(project, "late_photo.jpg", b"late evidence")
    with pytest.raises(WorkflowPreconditionError, match="已變更"):
        require_first_build_ready(project, "claude")
    _record(project, "succeeded", mode="claude")
    require_first_build_ready(project, "claude")


def test_versions_are_attributed_only_to_the_job_that_built_them(tmp_path: Path, monkeypatch):
    project = _project(tmp_path)
    build_project(project, "L0")
    monkeypatch.setenv(BUILD_JOB_ENV, "job-a")
    monkeypatch.setenv(BUILD_ORIGIN_ENV, "manual")
    build_project(project, "L0")
    monkeypatch.setenv(BUILD_JOB_ENV, "job-b")
    build_project(project, "L0")
    assert [path.name for path in versions_for_job(project, "job-a")] == ["v2"]
    assert [path.name for path in versions_for_job(project, "job-b")] == ["v3"]
    assert versions_for_job(project, "job-c") == []
    first = VersionManifest.model_validate_json(
        (project / ".cellforge" / "v1" / "manifest.json").read_text("utf-8")
    )
    assert first.build.job_id is None and first.build.origin == "direct"


def test_verify_version_reads_back_and_detects_changes(tmp_path: Path):
    project = _project(tmp_path)
    build_project(project, "L0")
    report = verify_version(project, "v1")
    assert report["status"] == "ok" and report["level"] == "L0"
    assert report["step_components"] > 0

    brief = project / ".cellforge" / "v1" / "render_brief.md"
    original = brief.read_bytes()
    brief.write_bytes(original + b"\n")
    with pytest.raises(VersionVerificationError, match="render_brief.md"):
        verify_version(project, "v1")
    brief.write_bytes(original)

    extra = project / ".cellforge" / "v1" / "injected.json"
    extra.write_text("{}", encoding="utf-8")
    with pytest.raises(VersionVerificationError, match="injected.json"):
        verify_version(project, "v1")
    extra.unlink()
    verify_version(project, "v1")

    (project / ".cellforge" / "v1" / "manifest.json").unlink()
    with pytest.raises(VersionIncompleteError, match="manifest.json"):
        verify_version(project, "v1")
