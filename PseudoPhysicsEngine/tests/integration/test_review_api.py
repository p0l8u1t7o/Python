from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient


def _revision(client: TestClient, name: str) -> str:
    project = cast(dict[str, object], client.post("/api/v1/projects", json={"name": name}).json())
    return str(cast(dict[str, object], project["current_revision"])["id"])


def test_review_comment_thread_and_resolution_are_auditable(client: TestClient) -> None:
    revision_id = _revision(client, "Review")
    author = str(uuid4())
    object_id = str(uuid4())
    created = client.post(
        f"/api/v1/revisions/{revision_id}/comments",
        json={"author_id": author, "body": "Confirm the robot base", "object_ids": [object_id]},
    )
    assert created.status_code == 201
    comment = created.json()
    assert comment["resolved_at"] is None

    reply = client.post(
        f"/api/v1/revisions/{revision_id}/comments",
        json={
            "author_id": str(uuid4()),
            "body": "Confirmed against drawing A-001",
            "parent_comment_id": comment["id"],
        },
    )
    assert reply.status_code == 201
    assert reply.json()["parent_comment_id"] == comment["id"]
    listed = client.get(f"/api/v1/revisions/{revision_id}/comments")
    assert [item["id"] for item in listed.json()] == [comment["id"], reply.json()["id"]]

    reviewer = str(uuid4())
    resolved = client.post(
        f"/api/v1/comments/{comment['id']}/resolve", json={"resolved_by": reviewer}
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved_by"] == reviewer
    assert resolved.json()["resolved_at"] is not None
    assert (
        client.post(
            f"/api/v1/comments/{comment['id']}/resolve", json={"resolved_by": reviewer}
        ).json()
        == resolved.json()
    )

    conflict = client.post(
        f"/api/v1/comments/{comment['id']}/resolve", json={"resolved_by": str(uuid4())}
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "REVIEW_COMMENT_CONFLICT"


def test_review_reply_cannot_cross_revision(client: TestClient) -> None:
    first_revision = _revision(client, "First review")
    second_revision = _revision(client, "Second review")
    parent = client.post(
        f"/api/v1/revisions/{first_revision}/comments",
        json={"author_id": str(uuid4()), "body": "First"},
    ).json()

    response = client.post(
        f"/api/v1/revisions/{second_revision}/comments",
        json={
            "author_id": str(uuid4()),
            "body": "Wrong thread",
            "parent_comment_id": parent["id"],
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "REVIEW_COMMENT_CONFLICT"
