"""已發布版本的獨立回讀驗證：manifest、雜湊、schema 與幾何（STEP／GLB）。

job 判定成功前以子程序執行 ``cell version verify``，讓 OCP 的原生崩潰只影響這次驗證。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cellforge.schema import VersionManifest
from cellforge.version_store import VersionPublishError, verify_outputs
from cellforge.versioning import VersionContext, VersionIncompleteError


class VersionVerificationError(RuntimeError):
    pass


def verify_version(project: Path, version: str) -> dict[str, Any]:
    context = VersionContext.open(project, version)
    if context.legacy:
        raise VersionIncompleteError(context.name, "manifest.json", "驗證版本")
    try:
        manifest = VersionManifest.model_validate(context.manifest)
    except ValueError as error:
        raise VersionVerificationError(f"{context.name} 的 manifest 格式錯誤：{error}") from error
    if manifest.version != context.name or manifest.number != context.number:
        raise VersionVerificationError(
            f"manifest 記錄的版本 {manifest.version} 與目錄 {context.name} 不符"
        )
    parts = [part.id for part in manifest.parts] or ["workpiece"]
    expected_nodes = [module.id for module in manifest.modules] + parts
    try:
        artifacts = verify_outputs(
            context.directory, manifest.build.level, manifest.number, expected_nodes
        )
    except VersionPublishError as error:
        raise VersionVerificationError(f"{context.name} 產物回讀失敗：{error}") from error
    recorded = {item.path: item.sha256 for item in manifest.artifacts}
    actual = {item["path"]: item["sha256"] for item in artifacts}
    if actual != recorded:
        changed = sorted(
            name
            for name in recorded.keys() | actual.keys()
            if recorded.get(name) != actual.get(name)
        )
        raise VersionVerificationError(
            f"{context.name} 產物與 manifest 不一致（新增、缺少或雜湊不符）：{', '.join(changed)}"
        )
    for item in manifest.sources:
        context.source(item.path, "驗證版本來源")
    for item in manifest.library:
        path = context.directory / item.path
        if not path.is_file() or _sha256(path) != item.sha256:
            raise VersionVerificationError(
                f"{context.name} 的庫模組副本 {item.path} 缺少或雜湊不符"
            )
    step = _verify_step(context)
    return {
        "status": "ok",
        "version": context.name,
        "level": manifest.build.level,
        "engineering_status": manifest.engineering.status,
        "engineering_summary": manifest.engineering.summary,
        "origin": manifest.build.origin,
        "job_id": manifest.build.job_id,
        "artifacts": len(recorded),
        "sources": len(manifest.sources),
        "library": len(manifest.library),
        "step_components": step,
    }


def _verify_step(context: VersionContext) -> int:
    from cellforge.build.stepio import inspect_step

    report = context.artifact_json("step_validation.json", "驗證 STEP")
    inspection = inspect_step(context.artifact("scene.step", "驗證 STEP"))
    names = [item.instance_name for item in inspection.components]
    if inspection.free_shape_count != 1 or names != report.get("expected_names"):
        raise VersionVerificationError(
            f"{context.name} 的 STEP 回讀結果與建置紀錄不符：頂層 {names}，"
            f"預期 {report.get('expected_names')}"
        )
    return len(names)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
