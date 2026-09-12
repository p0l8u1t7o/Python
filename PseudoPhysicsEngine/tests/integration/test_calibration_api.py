from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _revision(client: TestClient) -> str:
    project = cast(
        dict[str, object], client.post("/api/v1/projects", json={"name": "Calibration"}).json()
    )
    return str(cast(dict[str, object], project["current_revision"])["id"])


def test_calibration_api_returns_residuals_and_acceptance(client: TestClient) -> None:
    revision_id = _revision(client)
    source = [(0, 0, 0), (100, 0, 0), (0, 100, 0), (50, 30, 20)]
    target = [(10, 20, 30), (10, 120, 30), (-90, 20, 30), (-20, 70, 50)]
    response = client.post(
        f"/api/v1/revisions/{revision_id}/calibrate",
        json={
            "control_points": [
                {"id": str(uuid4()), "source_mm": before, "target_mm": after}
                for before, after in zip(source, target, strict=True)
            ],
            "rms_tolerance_mm": 0.01,
            "max_tolerance_mm": 0.02,
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["accepted"] is True
    assert result["rms_error_mm"] < 1e-9
    assert result["transform"][0][3] == pytest.approx(10)


def test_calibration_api_rejects_degenerate_points(client: TestClient) -> None:
    revision_id = _revision(client)
    points = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
    response = client.post(
        f"/api/v1/revisions/{revision_id}/calibrate",
        json={
            "control_points": [
                {"id": str(uuid4()), "source_mm": point, "target_mm": point} for point in points
            ],
            "rms_tolerance_mm": 1,
            "max_tolerance_mm": 1,
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "CALIBRATION_REJECTED"
