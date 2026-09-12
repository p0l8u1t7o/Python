from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient
from ppe_api.db import (
    CoordinateFrameRecord,
    ProjectRevisionRecord,
    create_database_engine,
    create_session_factory,
)
from ppe_domain import RevisionStatus
from sqlalchemy import update


def _create_revision(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Frame test"})
    assert response.status_code == 201
    payload = cast(dict[str, object], response.json())
    revision = cast(dict[str, object], payload["current_revision"])
    return str(revision["id"])


def test_add_root_and_child_frame_round_trip(client: TestClient) -> None:
    revision_id = _create_revision(client)
    plant_id = str(uuid4())
    machine_id = str(uuid4())

    root_response = client.post(
        f"/api/v1/revisions/{revision_id}/frames",
        json={
            "frame": {
                "id": plant_id,
                "revision_id": revision_id,
                "name": "Plant",
            }
        },
    )
    assert root_response.status_code == 201

    matrix = [
        [1, 0, 0, 1_000],
        [0, 1, 0, 2_000],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ]
    child_response = client.post(
        f"/api/v1/revisions/{revision_id}/frames",
        json={
            "frame": {
                "id": machine_id,
                "revision_id": revision_id,
                "name": "Machine",
                "parent_frame_id": plant_id,
            },
            "transform_from_parent": {
                "id": str(uuid4()),
                "revision_id": revision_id,
                "parent_frame_id": plant_id,
                "child_frame_id": machine_id,
                "matrix": matrix,
                "trust_status": "DRAWING_CONFIRMED",
                "source": "Layout drawing A-001",
            },
        },
    )

    assert child_response.status_code == 201
    tree = child_response.json()
    assert {frame["name"] for frame in tree["frames"]} == {"Plant", "Machine"}
    assert tree["transforms"][0]["matrix"] == matrix

    fetched = client.get(f"/api/v1/revisions/{revision_id}/frames")
    assert fetched.status_code == 200
    assert fetched.json() == tree


def test_second_root_is_rejected_without_partial_write(client: TestClient) -> None:
    revision_id = _create_revision(client)
    route = f"/api/v1/revisions/{revision_id}/frames"
    first = client.post(
        route,
        json={"frame": {"id": str(uuid4()), "revision_id": revision_id, "name": "Plant"}},
    )
    assert first.status_code == 201

    rejected = client.post(
        route,
        json={"frame": {"id": str(uuid4()), "revision_id": revision_id, "name": "Line"}},
    )

    assert rejected.status_code == 409
    assert rejected.json()["code"] == "FRAME_TREE_CONFLICT"
    assert len(client.get(route).json()["frames"]) == 1


def test_approved_revision_rejects_frame_mutation(client: TestClient, database_url: str) -> None:
    revision_id = _create_revision(client)
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            update(ProjectRevisionRecord)
            .where(ProjectRevisionRecord.id == revision_id)
            .values(status=RevisionStatus.APPROVED)
        )
    engine.dispose()

    response = client.post(
        f"/api/v1/revisions/{revision_id}/frames",
        json={"frame": {"id": str(uuid4()), "revision_id": revision_id, "name": "Plant"}},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "REVISION_IMMUTABLE"


def test_frame_uuid_can_remain_stable_across_revisions(
    client: TestClient, database_url: str
) -> None:
    response = client.post("/api/v1/projects", json={"name": "Revision copy test"})
    payload = cast(dict[str, object], response.json())
    first_revision = cast(dict[str, object], payload["current_revision"])
    project_id = str(payload["id"])
    first_revision_id = str(first_revision["id"])
    second_revision_id = str(uuid4())
    stable_frame_id = str(uuid4())

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        session.add(
            ProjectRevisionRecord(
                id=second_revision_id,
                project_id=project_id,
                sequence=2,
                status=RevisionStatus.DRAFT,
                parent_revision_id=first_revision_id,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()
        session.add_all(
            [
                CoordinateFrameRecord(
                    id=stable_frame_id,
                    revision_id=revision_id,
                    name="Plant",
                    parent_frame_id=None,
                    length_unit="mm",
                    axis_system="RIGHT_HANDED_Z_UP",
                )
                for revision_id in (first_revision_id, second_revision_id)
            ]
        )
    engine.dispose()
