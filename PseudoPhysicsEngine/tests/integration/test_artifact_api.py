import hashlib
import struct
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ppe_api.settings import Settings


def _create_project(client: TestClient, name: str = "Artifact test") -> tuple[str, str]:
    project = client.post("/api/v1/projects", json={"name": name}).json()
    return project["id"], project["current_revision"]["id"]


def _minimal_glb() -> bytes:
    json_chunk = b'{"asset":{"version":"2.0"},"scene":0,"scenes":[{}]}'
    json_chunk += b" " * (-len(json_chunk) % 4)
    total_length = 12 + 8 + len(json_chunk)
    return (
        b"glTF"
        + struct.pack("<II", 2, total_length)
        + struct.pack("<I", len(json_chunk))
        + b"JSON"
        + json_chunk
    )


def test_step_upload_hash_list_and_download(client: TestClient, storage_dir: Path) -> None:
    project_id, revision_id = _create_project(client)
    content = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"

    response = client.post(
        f"/api/v1/projects/{project_id}/files",
        data={"revision_id": revision_id, "source": "Supplier export"},
        files={"file": ("../Robot.STEP", content, "application/octet-stream")},
    )

    assert response.status_code == 201
    artifact = response.json()
    expected_hash = hashlib.sha256(content).hexdigest()
    assert artifact["original_filename"] == "Robot.STEP"
    assert artifact["format"] == "STEP"
    assert artifact["mime_type"] == "application/step"
    assert artifact["sha256"] == expected_hash
    assert artifact["size_bytes"] == len(content)
    assert artifact["storage_uri"] == f"objects/sha256/{expected_hash[:2]}/{expected_hash}"
    assert (storage_dir / artifact["storage_uri"]).read_bytes() == content

    listed = client.get(
        f"/api/v1/projects/{project_id}/artifacts",
        params={"revision_id": revision_id},
    )
    assert listed.status_code == 200
    assert listed.json() == [artifact]

    downloaded = client.get(f"/api/v1/artifacts/{artifact['id']}/content")
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert downloaded.headers["content-type"] == "application/step"


def test_duplicate_content_reuses_object_but_keeps_metadata(
    client: TestClient, storage_dir: Path
) -> None:
    project_id, revision_id = _create_project(client)
    content = _minimal_glb()
    route = f"/api/v1/projects/{project_id}/files"

    first = client.post(
        route,
        data={"revision_id": revision_id, "source": "First export"},
        files={"file": ("scene.glb", content, "model/gltf-binary")},
    )
    second = client.post(
        route,
        data={"revision_id": revision_id, "source": "Second export"},
        files={"file": ("scene-copy.glb", content, "model/gltf-binary")},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["storage_uri"] == second.json()["storage_uri"]
    object_files = [path for path in storage_dir.rglob("*") if path.is_file()]
    assert len(object_files) == 1


def test_mismatched_signature_is_rejected_without_metadata_or_object(
    client: TestClient, storage_dir: Path
) -> None:
    project_id, revision_id = _create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/files",
        data={"revision_id": revision_id, "source": "Untrusted upload"},
        files={"file": ("robot.step", b"not actually STEP", "application/step")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ARTIFACT_REJECTED"
    assert client.get(f"/api/v1/projects/{project_id}/artifacts").json() == []
    assert not list((storage_dir / "objects").rglob("*"))


def test_upload_limit_and_revision_ownership_are_enforced(client: TestClient) -> None:
    project_id, _revision_id = _create_project(client, "First")
    _other_project_id, other_revision_id = _create_project(client, "Second")
    route = f"/api/v1/projects/{project_id}/files"
    valid_pdf = b"%PDF-1.7\n" + bytes(32)

    wrong_revision = client.post(
        route,
        data={"revision_id": other_revision_id, "source": "Drawing"},
        files={"file": ("drawing.pdf", valid_pdf, "application/pdf")},
    )
    assert wrong_revision.status_code == 422
    assert wrong_revision.json()["code"] == "ARTIFACT_REJECTED"

    application = cast(FastAPI, client.app)
    settings = cast(Settings, application.state.settings)
    settings.max_upload_bytes = 10
    too_large = client.post(
        route,
        data={"revision_id": str(uuid4()), "source": "Drawing"},
        files={"file": ("drawing.pdf", valid_pdf, "application/pdf")},
    )
    assert too_large.status_code == 404
    assert too_large.json()["code"] == "REVISION_NOT_FOUND"

    _same_project, valid_revision_id = _create_project(client, "Third")
    over_limit = client.post(
        f"/api/v1/projects/{_same_project}/files",
        data={"revision_id": valid_revision_id, "source": "Drawing"},
        files={"file": ("drawing.pdf", valid_pdf, "application/pdf")},
    )
    assert over_limit.status_code == 422
    assert "upload limit" in over_limit.json()["message"]


def test_missing_artifact_uses_stable_error(client: TestClient) -> None:
    response = client.get(f"/api/v1/artifacts/{uuid4()}/content")
    assert response.status_code == 404
    assert response.json()["code"] == "ARTIFACT_NOT_FOUND"
