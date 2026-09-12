from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from ppe_api.db import ProjectRevisionRecord, create_database_engine, create_session_factory
from ppe_domain import RevisionStatus
from sqlalchemy import text


def test_sqlite_connection_pragmas(database_url: str) -> None:
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        assert connection.scalar(text("PRAGMA busy_timeout")) == 5000
    engine.dispose()


def test_create_then_get_project_keeps_uuid_and_initial_revision(client: TestClient) -> None:
    created_response = client.post(
        "/api/v1/projects",
        json={"name": "Robot pick-and-place demo", "customer_name": "Internal"},
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["current_revision"]["sequence"] == 1
    assert created["current_revision"]["status"] == "DRAFT"

    fetched_response = client.get(f"/api/v1/projects/{created['id']}")

    assert fetched_response.status_code == 200
    assert fetched_response.json() == created


def test_missing_project_uses_stable_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/projects/00000000-0000-4000-8000-000000000000")

    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"


def test_list_projects_returns_latest_revision(client: TestClient, database_url: str) -> None:
    first = client.post("/api/v1/projects", json={"name": "First project"}).json()
    second = client.post("/api/v1/projects", json={"name": "Second project"}).json()
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        session.add(
            ProjectRevisionRecord(
                id=str(uuid4()),
                project_id=first["id"],
                sequence=2,
                status=RevisionStatus.DRAFT,
                parent_revision_id=first["current_revision"]["id"],
                created_at=datetime.now(UTC),
            )
        )
    engine.dispose()

    response = client.get("/api/v1/projects")

    assert response.status_code == 200
    projects = response.json()
    assert {project["id"] for project in projects} == {first["id"], second["id"]}
    by_id = {project["id"]: project for project in projects}
    assert by_id[first["id"]]["current_revision"]["sequence"] == 2
    assert by_id[second["id"]]["current_revision"]["sequence"] == 1
