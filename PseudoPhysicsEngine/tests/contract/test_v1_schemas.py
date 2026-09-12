from uuid import uuid4

import pytest
from ppe_coordinates import IDENTITY_MATRIX
from ppe_domain import TrustStatus
from ppe_schemas import (
    ChangeOperation,
    ChangeSet,
    CoordinateFrame,
    FrameTransform,
    MotionKeyframe,
    MotionTrackSpec,
    ProcessSpec,
    ProcessStep,
    SceneAssemblySpec,
    SceneNodeSpec,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
)
from ppe_schemas.v1.change_set import OperationType
from pydantic import ValidationError


def test_coordinate_contract_fixes_unit_and_axis_system() -> None:
    frame = CoordinateFrame(id=uuid4(), revision_id=uuid4(), name="Plant")

    assert frame.length_unit == "mm"
    assert frame.axis_system == "RIGHT_HANDED_Z_UP"


def test_frame_transform_rejects_same_parent_and_child() -> None:
    frame_id = uuid4()
    revision_id = uuid4()

    with pytest.raises(ValidationError, match="must differ"):
        FrameTransform(
            id=uuid4(),
            revision_id=revision_id,
            parent_frame_id=frame_id,
            child_frame_id=frame_id,
            matrix=IDENTITY_MATRIX,
            trust_status=TrustStatus.INFERRED,
            source="Initial estimate",
        )


def test_change_set_add_requires_only_after_payload() -> None:
    operation = ChangeOperation(
        operation=OperationType.ADD,
        object_type="SceneNode",
        object_id=uuid4(),
        after={"name": "Robot R-01"},
    )
    change_set = ChangeSet(
        id=uuid4(),
        project_id=uuid4(),
        base_revision_id=uuid4(),
        reason="Place initial robot",
        user_instruction="Add Robot R-01",
        interpreted_intent="Add a scene node without applying it yet",
        operations=[operation],
    )

    assert change_set.schema_version == "1.0.0"
    assert change_set.approved_by is None


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        CoordinateFrame.model_validate(
            {
                "id": str(uuid4()),
                "revision_id": str(uuid4()),
                "name": "Plant",
                "unknown": 1,
            }
        )


def test_process_spec_rejects_dependency_cycle() -> None:
    first_id = uuid4()
    second_id = uuid4()

    with pytest.raises(ValidationError, match="must not contain a cycle"):
        ProcessSpec(
            id=uuid4(),
            project_id=uuid4(),
            revision_id=uuid4(),
            target_cycle_time_seconds=10,
            steps=[
                ProcessStep(
                    id=first_id,
                    name="Pick",
                    predecessor_ids=[second_id],
                    estimated_duration_seconds=1,
                ),
                ProcessStep(
                    id=second_id,
                    name="Place",
                    predecessor_ids=[first_id],
                    estimated_duration_seconds=1,
                ),
            ],
        )


def test_scene_assembly_rejects_parent_cycle() -> None:
    first_id = uuid4()
    second_id = uuid4()

    with pytest.raises(ValidationError, match="must not contain a cycle"):
        SceneAssemblySpec(
            id=uuid4(),
            project_id=uuid4(),
            revision_id=uuid4(),
            nodes=[
                SceneNodeSpec(
                    id=first_id,
                    name="Robot",
                    asset_version_id=uuid4(),
                    coordinate_frame_id=uuid4(),
                    parent_node_id=second_id,
                ),
                SceneNodeSpec(
                    id=second_id,
                    name="Tool",
                    asset_version_id=uuid4(),
                    coordinate_frame_id=uuid4(),
                    parent_node_id=first_id,
                ),
            ],
        )


def test_motion_track_requires_strictly_increasing_time() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        MotionTrackSpec(
            id=uuid4(),
            scene_node_id=uuid4(),
            joint_name="J1",
            position_unit="degree",
            keyframes=[
                MotionKeyframe(time_seconds=1, position=0),
                MotionKeyframe(time_seconds=1, position=90),
            ],
        )


def test_validation_report_cannot_pass_with_release_blocker() -> None:
    with pytest.raises(ValidationError, match="must have FAILED status"):
        ValidationReport(
            id=uuid4(),
            project_id=uuid4(),
            revision_id=uuid4(),
            status=ValidationStatus.PASSED,
            validator_version="0.1.0",
            issues=[
                ValidationIssue(
                    code="INFERRED_COORDINATE",
                    severity=ValidationSeverity.ERROR,
                    message="Robot base coordinate is inferred",
                    blocks_release=True,
                )
            ],
        )
