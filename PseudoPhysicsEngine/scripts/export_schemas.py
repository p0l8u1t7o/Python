import json
from pathlib import Path

from ppe_schemas import (
    ArtifactRead,
    AuditEventRead,
    CalibrationRequest,
    CalibrationResult,
    ChangeSet,
    ChangeSetApplyResult,
    ChangeSetPreview,
    CoordinateFrame,
    CoordinateFrameChange,
    FrameTransform,
    FrameTreeRead,
    JobRead,
    JobSubmit,
    MotionSpec,
    ProcessAnalysis,
    ProcessSpec,
    ProjectRead,
    ProjectRevision,
    ReleaseManifest,
    ReleaseRequest,
    ReviewCommentRead,
    RevisionDiff,
    SceneAssemblySpec,
    ValidationReport,
)
from pydantic import BaseModel

SCHEMAS: dict[str, type[BaseModel]] = {
    "artifact.schema.json": ArtifactRead,
    "audit-event.schema.json": AuditEventRead,
    "calibration-request.schema.json": CalibrationRequest,
    "calibration-result.schema.json": CalibrationResult,
    "change-set.schema.json": ChangeSet,
    "change-set-apply-result.schema.json": ChangeSetApplyResult,
    "change-set-preview.schema.json": ChangeSetPreview,
    "coordinate-frame.schema.json": CoordinateFrame,
    "coordinate-frame-change.schema.json": CoordinateFrameChange,
    "frame-transform.schema.json": FrameTransform,
    "frame-tree.schema.json": FrameTreeRead,
    "job.schema.json": JobRead,
    "job-submit.schema.json": JobSubmit,
    "project.schema.json": ProjectRead,
    "project-revision.schema.json": ProjectRevision,
    "process-spec.schema.json": ProcessSpec,
    "process-analysis.schema.json": ProcessAnalysis,
    "scene-assembly-spec.schema.json": SceneAssemblySpec,
    "motion-spec.schema.json": MotionSpec,
    "validation-report.schema.json": ValidationReport,
    "release-manifest.schema.json": ReleaseManifest,
    "release-request.schema.json": ReleaseRequest,
    "revision-diff.schema.json": RevisionDiff,
    "review-comment.schema.json": ReviewCommentRead,
}


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    output_directory = project_root / "packages" / "schemas" / "json" / "v1"
    output_directory.mkdir(parents=True, exist_ok=True)

    for file_name, model in SCHEMAS.items():
        output_path = output_directory / file_name
        output_path.write_text(
            json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(output_path.relative_to(project_root))


if __name__ == "__main__":
    main()
