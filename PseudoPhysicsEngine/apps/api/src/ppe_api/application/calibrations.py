from uuid import UUID

from ppe_coordinates import fit_rigid_transform
from ppe_schemas import CalibrationRequest, CalibrationResult
from sqlalchemy.orm import Session

from ppe_api.application.revisions import RevisionNotFound
from ppe_api.db.models import ProjectRevisionRecord


class CalibrationRejected(ValueError):
    pass


def calibrate_revision(
    session: Session, revision_id: UUID, request: CalibrationRequest
) -> CalibrationResult:
    if session.get(ProjectRevisionRecord, str(revision_id)) is None:
        raise RevisionNotFound(str(revision_id))
    try:
        calibration = fit_rigid_transform(
            [point.source_mm for point in request.control_points],
            [point.target_mm for point in request.control_points],
        )
    except ValueError as error:
        raise CalibrationRejected(str(error)) from error
    return CalibrationResult(
        revision_id=revision_id,
        transform=calibration.transform,
        control_point_ids=[point.id for point in request.control_points],
        residuals_mm=list(calibration.residuals_mm),
        rms_error_mm=calibration.rms_error_mm,
        max_error_mm=calibration.max_error_mm,
        accepted=(
            calibration.rms_error_mm <= request.rms_tolerance_mm
            and calibration.max_error_mm <= request.max_tolerance_mm
        ),
    )
