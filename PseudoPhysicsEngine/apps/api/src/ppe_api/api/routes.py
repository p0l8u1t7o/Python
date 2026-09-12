from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from ppe_schemas import (
    ArtifactRead,
    AuditEventRead,
    CalibrationRequest,
    CalibrationResult,
    ChangeSet,
    ChangeSetApplyResult,
    ChangeSetPreview,
    FrameCreate,
    FrameTreeRead,
    HealthResponse,
    JobClaimRequest,
    JobCompleteRequest,
    JobFailRequest,
    JobHeartbeatRequest,
    JobRead,
    JobSubmit,
    MotionSpec,
    ProcessAnalysis,
    ProcessSpec,
    ProjectCreate,
    ProjectRead,
    ProjectRevision,
    ReleaseManifest,
    ReleaseRequest,
    ReviewCommentCreate,
    ReviewCommentRead,
    ReviewCommentResolve,
    RevisionDiff,
    SceneAssemblySpec,
    ValidationReport,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from ppe_api.api.dependencies import get_session
from ppe_api.application import (
    add_frame,
    analyze_process,
    apply_change_set,
    calibrate_revision,
    cancel_job,
    claim_job,
    compare_revisions,
    complete_job,
    create_artifact,
    create_project,
    create_review_comment,
    fail_job,
    get_artifact_content,
    get_frame_tree,
    get_job,
    get_latest_validation,
    get_motion_spec,
    get_process_spec,
    get_project,
    get_release_manifest,
    get_scene_assembly,
    heartbeat_job,
    list_artifacts,
    list_audit_events,
    list_jobs,
    list_project_revisions,
    list_projects,
    list_review_comments,
    preview_change_set,
    release_revision,
    resolve_review_comment,
    run_validation,
    save_motion_spec,
    save_process_spec,
    save_scene_assembly,
    submit_job,
)
from ppe_api.settings import Settings

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_session)]
RevisionForm = Annotated[UUID, Form()]
SourceForm = Annotated[str, Form(min_length=1, max_length=500)]
UploadedFile = Annotated[UploadFile, File()]
RevisionFilter = Annotated[UUID | None, Query()]


@router.get("/health", response_model=HealthResponse)
def health(session: DatabaseSession) -> HealthResponse:
    session.execute(text("SELECT 1"))
    return HealthResponse()


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def post_project(request: ProjectCreate, session: DatabaseSession) -> ProjectRead:
    return create_project(session, request)


@router.get("/projects", response_model=list[ProjectRead])
def read_projects(session: DatabaseSession) -> list[ProjectRead]:
    return list_projects(session)


@router.get("/projects/{project_id}/revisions", response_model=list[ProjectRevision])
def read_project_revisions(project_id: UUID, session: DatabaseSession) -> list[ProjectRevision]:
    return list_project_revisions(session, project_id)


@router.get("/projects/{project_id}/revisions/diff", response_model=RevisionDiff)
def read_revision_diff(
    project_id: UUID,
    from_revision_id: Annotated[UUID, Query()],
    to_revision_id: Annotated[UUID, Query()],
    session: DatabaseSession,
) -> RevisionDiff:
    return compare_revisions(session, project_id, from_revision_id, to_revision_id)


@router.post(
    "/revisions/{revision_id}/comments",
    response_model=ReviewCommentRead,
    status_code=status.HTTP_201_CREATED,
)
def post_review_comment(
    revision_id: UUID, request: ReviewCommentCreate, session: DatabaseSession
) -> ReviewCommentRead:
    return create_review_comment(session, revision_id, request)


@router.get("/revisions/{revision_id}/comments", response_model=list[ReviewCommentRead])
def read_review_comments(revision_id: UUID, session: DatabaseSession) -> list[ReviewCommentRead]:
    return list_review_comments(session, revision_id)


@router.post("/comments/{comment_id}/resolve", response_model=ReviewCommentRead)
def post_review_comment_resolve(
    comment_id: UUID, request: ReviewCommentResolve, session: DatabaseSession
) -> ReviewCommentRead:
    return resolve_review_comment(session, comment_id, request)


@router.post(
    "/projects/{project_id}/files",
    response_model=ArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_project_file(
    project_id: UUID,
    request: Request,
    session: DatabaseSession,
    revision_id: RevisionForm,
    source: SourceForm,
    file: UploadedFile,
) -> ArtifactRead:
    settings: Settings = request.app.state.settings

    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    try:
        return await create_artifact(
            session,
            project_id=project_id,
            revision_id=revision_id,
            filename=file.filename or "",
            source=source,
            content=chunks(),
            storage_dir=settings.storage_dir,
            max_upload_bytes=settings.max_upload_bytes,
        )
    finally:
        await file.close()


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactRead])
def read_project_artifacts(
    project_id: UUID,
    session: DatabaseSession,
    revision_id: RevisionFilter = None,
) -> list[ArtifactRead]:
    return list_artifacts(session, project_id, revision_id)


@router.get("/projects/{project_id}/audit", response_model=list[AuditEventRead])
def read_project_audit(
    project_id: UUID,
    session: DatabaseSession,
    revision_id: RevisionFilter = None,
) -> list[AuditEventRead]:
    return list_audit_events(session, project_id, revision_id)


@router.get("/artifacts/{artifact_id}/content", response_class=FileResponse)
def read_artifact_content(
    artifact_id: UUID, request: Request, session: DatabaseSession
) -> FileResponse:
    settings: Settings = request.app.state.settings
    artifact, path = get_artifact_content(session, artifact_id, settings.storage_dir)
    return FileResponse(
        path,
        media_type=artifact.mime_type,
        filename=artifact.original_filename,
    )


@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def post_job(request: JobSubmit, session: DatabaseSession) -> JobRead:
    return submit_job(session, request)


@router.get("/jobs/{job_id}", response_model=JobRead)
def read_job(job_id: UUID, session: DatabaseSession) -> JobRead:
    return get_job(session, job_id)


@router.get("/projects/{project_id}/jobs", response_model=list[JobRead])
def read_project_jobs(
    project_id: UUID,
    session: DatabaseSession,
    revision_id: RevisionFilter = None,
) -> list[JobRead]:
    return list_jobs(session, project_id, revision_id)


@router.post("/jobs/claim", response_model=JobRead | None)
def post_job_claim(request: JobClaimRequest, session: DatabaseSession) -> JobRead | None:
    return claim_job(session, request)


@router.post("/jobs/{job_id}/heartbeat", response_model=JobRead)
def post_job_heartbeat(
    job_id: UUID, request: JobHeartbeatRequest, session: DatabaseSession
) -> JobRead:
    return heartbeat_job(session, job_id, request)


@router.post("/jobs/{job_id}/complete", response_model=JobRead)
def post_job_complete(
    job_id: UUID, request: JobCompleteRequest, session: DatabaseSession
) -> JobRead:
    return complete_job(session, job_id, request)


@router.post("/jobs/{job_id}/fail", response_model=JobRead)
def post_job_fail(job_id: UUID, request: JobFailRequest, session: DatabaseSession) -> JobRead:
    return fail_job(session, job_id, request)


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
def post_job_cancel(job_id: UUID, session: DatabaseSession) -> JobRead:
    return cancel_job(session, job_id)


@router.get("/projects/{project_id}", response_model=ProjectRead)
def read_project(project_id: UUID, session: DatabaseSession) -> ProjectRead:
    return get_project(session, project_id)


@router.post(
    "/revisions/{revision_id}/frames",
    response_model=FrameTreeRead,
    status_code=status.HTTP_201_CREATED,
)
def post_frame(revision_id: UUID, request: FrameCreate, session: DatabaseSession) -> FrameTreeRead:
    return add_frame(session, revision_id, request)


@router.get("/revisions/{revision_id}/frames", response_model=FrameTreeRead)
def read_frames(revision_id: UUID, session: DatabaseSession) -> FrameTreeRead:
    return get_frame_tree(session, revision_id)


@router.post("/revisions/{revision_id}/calibrate", response_model=CalibrationResult)
def post_calibration(
    revision_id: UUID, request: CalibrationRequest, session: DatabaseSession
) -> CalibrationResult:
    return calibrate_revision(session, revision_id, request)


@router.put("/revisions/{revision_id}/process-spec", response_model=ProcessSpec)
def put_process_spec(
    revision_id: UUID, request: ProcessSpec, session: DatabaseSession
) -> ProcessSpec:
    return save_process_spec(session, revision_id, request)


@router.get("/revisions/{revision_id}/process-spec", response_model=ProcessSpec)
def read_process_spec(revision_id: UUID, session: DatabaseSession) -> ProcessSpec:
    return get_process_spec(session, revision_id)


@router.get("/revisions/{revision_id}/process-analysis", response_model=ProcessAnalysis)
def read_process_analysis(revision_id: UUID, session: DatabaseSession) -> ProcessAnalysis:
    return analyze_process(session, revision_id)


@router.put("/revisions/{revision_id}/motion-spec", response_model=MotionSpec)
def put_motion_spec(revision_id: UUID, request: MotionSpec, session: DatabaseSession) -> MotionSpec:
    return save_motion_spec(session, revision_id, request)


@router.get("/revisions/{revision_id}/motion-spec", response_model=MotionSpec)
def read_motion_spec(revision_id: UUID, session: DatabaseSession) -> MotionSpec:
    return get_motion_spec(session, revision_id)


@router.put("/revisions/{revision_id}/scene", response_model=SceneAssemblySpec)
def put_scene_assembly(
    revision_id: UUID, request: SceneAssemblySpec, session: DatabaseSession
) -> SceneAssemblySpec:
    return save_scene_assembly(session, revision_id, request)


@router.get("/revisions/{revision_id}/scene", response_model=SceneAssemblySpec)
def read_scene_assembly(revision_id: UUID, session: DatabaseSession) -> SceneAssemblySpec:
    return get_scene_assembly(session, revision_id)


@router.post("/revisions/{revision_id}/validate", response_model=ValidationReport)
def post_validation(revision_id: UUID, session: DatabaseSession) -> ValidationReport:
    return run_validation(session, revision_id)


@router.get("/revisions/{revision_id}/validation", response_model=ValidationReport)
def read_latest_validation(revision_id: UUID, session: DatabaseSession) -> ValidationReport:
    return get_latest_validation(session, revision_id)


@router.post("/revisions/{revision_id}/release", response_model=ReleaseManifest)
def post_release(
    revision_id: UUID, request: ReleaseRequest, session: DatabaseSession
) -> ReleaseManifest:
    return release_revision(session, revision_id, request)


@router.get("/revisions/{revision_id}/release", response_model=ReleaseManifest)
def read_release(revision_id: UUID, session: DatabaseSession) -> ReleaseManifest:
    return get_release_manifest(session, revision_id)


@router.post(
    "/revisions/{revision_id}/changesets/preview",
    response_model=ChangeSetPreview,
)
def post_change_set_preview(
    revision_id: UUID, request: ChangeSet, session: DatabaseSession
) -> ChangeSetPreview:
    return preview_change_set(session, revision_id, request)


@router.post(
    "/revisions/{revision_id}/changesets/apply",
    response_model=ChangeSetApplyResult,
    status_code=status.HTTP_201_CREATED,
)
def post_change_set_apply(
    revision_id: UUID, request: ChangeSet, session: DatabaseSession
) -> ChangeSetApplyResult:
    return apply_change_set(session, revision_id, request)
