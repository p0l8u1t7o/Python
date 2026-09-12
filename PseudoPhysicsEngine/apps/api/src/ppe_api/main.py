from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from ppe_schemas import ApiError

from ppe_api.api import router
from ppe_api.application import (
    ArtifactNotFound,
    ArtifactRejected,
    CalibrationRejected,
    ChangeSetConflict,
    ChangeSetRejected,
    EngineeringSpecConflict,
    EngineeringSpecNotFound,
    FrameTreeConflict,
    JobConflict,
    JobNotFound,
    ProjectNotFound,
    ReleaseNotFound,
    ReleaseRejected,
    ReviewCommentConflict,
    ReviewCommentNotFound,
    RevisionComparisonConflict,
    RevisionImmutable,
    RevisionNotFound,
    ValidationReportNotFound,
)
from ppe_api.db import create_database_engine, create_session_factory
from ppe_api.settings import Settings


def create_app(
    *,
    database_url: str | None = None,
    storage_dir: Path | None = None,
    max_upload_bytes: int | None = None,
) -> FastAPI:
    settings = Settings()
    if storage_dir is not None or max_upload_bytes is not None:
        settings = settings.model_copy(
            update={
                "storage_dir": storage_dir or settings.storage_dir,
                "max_upload_bytes": max_upload_bytes or settings.max_upload_bytes,
            }
        )
    settings.prepare_local_directories()
    engine = create_database_engine(database_url or settings.database_url)

    application = FastAPI(title="PseudoPhysicsEngine API", version="0.1.0")
    application.state.settings = settings
    application.state.session_factory = create_session_factory(engine)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(ProjectNotFound)
    async def project_not_found(_request: Request, exception: ProjectNotFound) -> JSONResponse:
        body = ApiError(code="PROJECT_NOT_FOUND", message=f"Project {exception} was not found")
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=body.model_dump())

    @application.exception_handler(RevisionNotFound)
    async def revision_not_found(_request: Request, exception: RevisionNotFound) -> JSONResponse:
        body = ApiError(code="REVISION_NOT_FOUND", message=f"Revision {exception} was not found")
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=body.model_dump())

    @application.exception_handler(RevisionImmutable)
    async def revision_immutable(_request: Request, exception: RevisionImmutable) -> JSONResponse:
        body = ApiError(code="REVISION_IMMUTABLE", message=str(exception))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())

    @application.exception_handler(RevisionComparisonConflict)
    async def revision_comparison_conflict(
        _request: Request, exception: RevisionComparisonConflict
    ) -> JSONResponse:
        body = ApiError(code="REVISION_COMPARISON_CONFLICT", message=str(exception))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())

    @application.exception_handler(ReviewCommentNotFound)
    async def review_comment_not_found(
        _request: Request, exception: ReviewCommentNotFound
    ) -> JSONResponse:
        body = ApiError(
            code="REVIEW_COMMENT_NOT_FOUND", message=f"Comment {exception} was not found"
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=body.model_dump())

    @application.exception_handler(ReviewCommentConflict)
    async def review_comment_conflict(
        _request: Request, exception: ReviewCommentConflict
    ) -> JSONResponse:
        body = ApiError(code="REVIEW_COMMENT_CONFLICT", message=str(exception))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())

    @application.exception_handler(FrameTreeConflict)
    async def frame_tree_conflict(_request: Request, exception: FrameTreeConflict) -> JSONResponse:
        body = ApiError(code="FRAME_TREE_CONFLICT", message=str(exception))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())

    @application.exception_handler(ChangeSetConflict)
    async def change_set_conflict(_request: Request, exception: ChangeSetConflict) -> JSONResponse:
        body = ApiError(code="CHANGE_SET_CONFLICT", message=str(exception))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())

    @application.exception_handler(ChangeSetRejected)
    async def change_set_rejected(_request: Request, exception: ChangeSetRejected) -> JSONResponse:
        body = ApiError(code="CHANGE_SET_REJECTED", message=str(exception))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=body.model_dump(),
        )

    @application.exception_handler(ArtifactNotFound)
    async def artifact_not_found(_request: Request, exception: ArtifactNotFound) -> JSONResponse:
        body = ApiError(code="ARTIFACT_NOT_FOUND", message=f"Artifact {exception} was not found")
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=body.model_dump())

    @application.exception_handler(ArtifactRejected)
    async def artifact_rejected(_request: Request, exception: ArtifactRejected) -> JSONResponse:
        body = ApiError(code="ARTIFACT_REJECTED", message=str(exception))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=body.model_dump(),
        )

    @application.exception_handler(CalibrationRejected)
    async def calibration_rejected(
        _request: Request, exception: CalibrationRejected
    ) -> JSONResponse:
        body = ApiError(code="CALIBRATION_REJECTED", message=str(exception))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=body.model_dump(),
        )

    @application.exception_handler(JobNotFound)
    async def job_not_found(_request: Request, exception: JobNotFound) -> JSONResponse:
        body = ApiError(code="JOB_NOT_FOUND", message=f"Job {exception} was not found")
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=body.model_dump())

    @application.exception_handler(JobConflict)
    async def job_conflict(_request: Request, exception: JobConflict) -> JSONResponse:
        body = ApiError(code="JOB_CONFLICT", message=str(exception))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())

    @application.exception_handler(EngineeringSpecNotFound)
    async def engineering_spec_not_found(
        _request: Request, exception: EngineeringSpecNotFound
    ) -> JSONResponse:
        body = ApiError(code="ENGINEERING_SPEC_NOT_FOUND", message=f"{exception} was not found")
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=body.model_dump())

    @application.exception_handler(EngineeringSpecConflict)
    async def engineering_spec_conflict(
        _request: Request, exception: EngineeringSpecConflict
    ) -> JSONResponse:
        body = ApiError(code="ENGINEERING_SPEC_CONFLICT", message=str(exception))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())

    @application.exception_handler(ValidationReportNotFound)
    async def validation_report_not_found(
        _request: Request, exception: ValidationReportNotFound
    ) -> JSONResponse:
        body = ApiError(
            code="VALIDATION_REPORT_NOT_FOUND",
            message=f"No validation report exists for revision {exception}",
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=body.model_dump())

    @application.exception_handler(ReleaseNotFound)
    async def release_not_found(_request: Request, exception: ReleaseNotFound) -> JSONResponse:
        body = ApiError(
            code="RELEASE_NOT_FOUND", message=f"Revision {exception} has not been released"
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=body.model_dump())

    @application.exception_handler(ReleaseRejected)
    async def release_rejected(_request: Request, exception: ReleaseRejected) -> JSONResponse:
        body = ApiError(code="RELEASE_REJECTED", message=str(exception))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())

    application.include_router(router, prefix="/api/v1")
    return application


app = create_app()
