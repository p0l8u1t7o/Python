"""快速註冊端點的流程層測試；不載入實機訓練依賴。"""

from __future__ import annotations

import json
import shutil
from types import SimpleNamespace
from unittest import mock

import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TransactionTestCase, override_settings

from apps.accounts.models import AuthToken, UserPref
from apps.core.errors import Conflict
from apps.vision.dl import base as dl_base
from apps.vision.dl import quick
from apps.vision.models import DlProject, DlSample
from tests._helpers import save_png, temp_dir


TMP = temp_dir()


def _json(body: dict) -> str:
    return json.dumps(body)


@override_settings(VISION={**settings.VISION, "ASSET_DIR": TMP, "PERSIST_RUNS": False})
class QuickRegisterTests(TransactionTestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        dl_base.register_builtins()
        self.folder = temp_dir()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def _project(self, *, samples: int = 2) -> DlProject:
        project = DlProject.objects.create(name=f"qr-{DlProject.objects.count()}", trainer_kind="ai_detect", classes=["part"])
        for i in range(samples):
            image = np.full((240 + i * 20, 320 + i * 30, 3), 80, np.uint8)
            path = save_png(image, self.folder, f"s{i}.png")
            DlSample.objects.create(project=project, path=path, width=image.shape[1], height=image.shape[0])
        return project

    def test_endpoint_labels_boxes_and_starts_training_with_params(self):
        project = self._project(samples=2)
        proposal = {"kind": "polygon", "label": "", "points": [[0.1, 0.2], [0.7, 0.25], [0.4, 0.9]]}
        started = {"id": "job123"}
        with (
            mock.patch("apps.vision.dl.sam.suggest_everything", return_value=[proposal]) as suggest,
            mock.patch.object(quick.yolo_runtime, "pick_device", return_value=("cpu", "")),
            mock.patch.object(quick.devices, "train_device", return_value="cpu"),
            mock.patch.object(quick.jobs, "start", return_value=started) as start,
        ):
            r = self.client.post(
                f"/api/vision/dl/projects/{project.id}/quick-register",
                data=_json({"asset_name": "fast-part"}),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 202, r.content)
        body = r.json()
        self.assertEqual(body["job_id"], "job123")
        self.assertEqual(body["labeled"], 2)
        self.assertEqual(body["skipped"], 0)
        self.assertEqual(body["params"], {**quick.QUICK_PRESET, "imgsz": 320})
        self.assertEqual(suggest.call_count, 2)
        self.assertEqual(suggest.call_args.kwargs["max_masks"], quick.QUICK_MAX_MASKS)
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0], project)
        self.assertEqual(start.call_args.args[1], body["params"])
        self.assertEqual(start.call_args.args[2], "cpu")
        self.assertEqual(start.call_args.args[3], "fast-part")
        shapes = [sample.shapes for sample in project.samples.order_by("created_at")]
        self.assertEqual(shapes[0], [{"label": "part", "kind": "bbox", "points": [[0.1, 0.2], [0.7, 0.9]]}])
        self.assertTrue(all(sample.labeled_by == "auto" and sample.score == quick.QUICK_LABEL_SCORE for sample in project.samples.all()))

    def test_not_enough_samples_returns_422(self):
        project = self._project(samples=1)
        r = self.client.post(f"/api/vision/dl/projects/{project.id}/quick-register", data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "not_enough_samples")

    def test_training_busy_returns_409(self):
        project = self._project(samples=2)
        proposal = {"kind": "polygon", "label": "", "points": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]]}
        with (
            mock.patch("apps.vision.dl.sam.suggest_everything", return_value=[proposal]),
            mock.patch.object(quick.yolo_runtime, "pick_device", return_value=("cpu", "")),
            mock.patch.object(quick.jobs, "start", side_effect=Conflict("Training is already running", code="training_busy")),
        ):
            r = self.client.post(f"/api/vision/dl/projects/{project.id}/quick-register", data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "training_busy")

    def test_no_dl_feature_returns_403(self):
        project = self._project(samples=2)
        user = User.objects.create_user("op", password="pass123")
        UserPref.objects.create(user=user, role="operator")
        token = AuthToken.issue(user)
        r = self.client.post(
            f"/api/vision/dl/projects/{project.id}/quick-register",
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "permission_denied")

    def test_quick_preset_is_locked(self):
        self.assertEqual(
            quick.QUICK_PRESET,
            {
                "model": "n",
                "epochs": 20,
                "batch": 4,
                "patience": 8,
                "lr0": 0.001,
                "val_ratio": 0.2,
                "workers": 0,
                "suggest_conf": 0.4,
                "degrees": 0,
                "fliplr": 0.0,
                "mosaic": 0.0,
            },
        )
        self.assertEqual(quick.quick_params([SimpleNamespace(width=1280, height=1024)])["imgsz"], 640)
        self.assertEqual(quick.quick_params([SimpleNamespace(width=800, height=600)])["imgsz"], 480)

    def test_polygon_proposal_converts_to_exact_bounding_box(self):
        boxes = quick.proposals_to_boxes(
            [{"kind": "polygon", "label": "", "points": [[0.12, 0.2], [0.66, 0.31], [0.4, 0.85], [0.22, 0.6]]}],
            ["part"],
        )
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["kind"], "bbox")
        self.assertEqual(boxes[0]["label"], "part")
        self.assertEqual(boxes[0]["points"], [[0.12, 0.2], [0.66, 0.85]])
