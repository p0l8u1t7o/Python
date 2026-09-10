"""模型版本與保留集隔離；以平台工具或假 trainer 驗證，不需顯示卡。"""

import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest import mock
import uuid
import zipfile

import numpy as np
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.vision.dl import api, jobs, model_versions, retrieval
from apps.vision.dl.base import SampleRef, TrainResult
from apps.vision.models import Asset, DlModelVersion, DlProject, Flow
from tests._helpers import fake_backbone, save_png, temp_dir


class ModelVersionTests(TestCase):
    def setUp(self):
        self.folder = temp_dir()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.override = override_settings(VISION={**settings.VISION, "ASSET_DIR": self.folder})
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.project = DlProject.objects.create(name="Version test", trainer_kind="mlp_classify", classes=["dark", "bright"])
        self.rows = []
        for label, offset in [("dark", 0), ("bright", 220)]:
            for i in range(5):
                image = np.full((19, 27, 3), offset + i, np.uint8)
                self.rows.append(api._save_sample(self.project, image, label))
        self.base = f"/api/vision/dl/projects/{self.project.pk}"

    def post(self, path, data=None):
        return self.client.post(path, data=json.dumps(data or {}), content_type="application/json")

    def build(self):
        def train(samples, classes, params, device, progress):
            self.assertTrue(all(s.split != "test" for s in samples), "Holdout reached trainer")
            self.trained_ids = {s.id for s in samples}
            centres = [np.mean([s.load().mean() for s in samples if s.label == label]) for label in classes]
            return TrainResult(b"candidate", {"train_accuracy": 1.0}, tool_params={"boundary": float(np.mean(centres))})

        def infer(key, path, params, image):
            return SimpleNamespace(outputs={"label": "dark" if image.mean() < params["boundary"] else "bright"}, status="ok")

        job = jobs.TrainJob(uuid.uuid4().hex, self.project.id, self.project.name, self.project.trainer_kind, "cpu")
        with mock.patch.object(jobs, "get_trainer", return_value=SimpleNamespace(train=train)), mock.patch.object(model_versions, "infer", side_effect=infer):
            jobs._train(job, self.project.pk, {"epochs": 5})
        jobs.save("Candidate", job=job, created_by="tester")
        return self.project.model_versions.first()

    def test_save_freezes_actual_training_data_and_fixed_holdout(self):
        first = self.build()
        self.assertEqual(first.status, "candidate")
        self.assertEqual(first.created_by, "tester")
        self.assertEqual(first.metrics["accuracy"], 1.0)
        self.assertEqual(set(first.tune_samples), self.trained_ids)
        self.assertFalse(set(first.holdout_samples) & self.trained_ids)
        self.assertEqual(len(first.holdout_samples), 2)
        asset = Asset.objects.get(pk=first.dataset_version.asset_id)
        with zipfile.ZipFile(asset.path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(len(manifest["items"]), 10)
            self.assertEqual(sum(i["split"] == "test" for i in manifest["items"]), 2)
        self.project.samples.filter(pk__in=first.holdout_samples).update(split="train")
        second = self.build()
        self.assertEqual(second.holdout_samples, first.holdout_samples)
        self.assertEqual(second.parent, first)
        self.assertNotEqual(first.dataset_version_id, second.dataset_version_id)

    def test_empty_project_can_save_without_measured_accuracy(self):
        self.project.samples.all().delete()
        trainer = SimpleNamespace(train=mock.Mock(return_value=TrainResult(b"candidate", {"training": 1})))
        job = jobs.TrainJob(uuid.uuid4().hex, self.project.id, self.project.name, self.project.trainer_kind, "cpu")
        with mock.patch.object(jobs, "get_trainer", return_value=trainer), mock.patch.object(model_versions, "infer") as infer:
            jobs._train(job, self.project.pk, {})
            result = jobs.save("Empty project candidate", job=job)
        self.assertTrue(result["saved"])
        trainer.train.assert_called_once()
        self.assertEqual(trainer.train.call_args.args[0], [])
        infer.assert_not_called()
        version = self.project.model_versions.get()
        self.assertEqual(version.holdout_samples, [])
        self.assertEqual(version.metrics["holdout_count"], 0)
        self.assertIsNone(version.metrics["accuracy"])
        self.assertEqual(version.metrics["warning"], "No holdout set. Accuracy was not measured.")
        self.assertIsNotNone(version.dataset_version)

    def test_explicit_holdout_is_measured_but_never_sent_to_trainer(self):
        held = self.rows[-1]
        held.split = "test"
        held.save(update_fields=["split"])
        version = self.build()
        self.assertEqual(version.holdout_samples, [str(held.id)])
        self.assertNotIn(str(held.id), self.trained_ids)
        self.assertEqual(version.metrics["holdout_count"], 1)
        self.assertEqual(version.metrics["accuracy"], 1.0)
        self.assertNotIn("warning", version.metrics)

    def test_split_endpoint_cannot_move_frozen_holdout(self):
        version = self.build()
        sid = version.holdout_samples[0]
        response = self.client.patch(f"/api/vision/dl/samples/{sid}", data=json.dumps({"split": "train"}), content_type="application/json")
        self.assertEqual(response.status_code, 422)
        response = self.post(self.base + "/split", {"val": 0.3, "test": 0.4, "seed": 9})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(str(x) for x in self.project.samples.filter(split="test").values_list("pk", flat=True)), set(version.holdout_samples))
        self.project.samples.filter(pk__in=version.holdout_samples).delete()
        response = self.post(self.base + "/split", {"val": 0.3, "test": 0.4, "seed": 9})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["test"], 0)

    def test_auto_label_never_uses_holdout_as_reference(self):
        version = self.build()
        trainer = SimpleNamespace(label_mode="classes", suggest=mock.Mock(return_value=[]))
        with mock.patch.object(api.dl_base, "get_trainer", return_value=trainer):
            response = self.post(self.base + "/auto-label")
        self.assertEqual(response.status_code, 200, response.content)
        labeled, unlabeled = trainer.suggest.call_args.args[:2]
        self.assertFalse(set(version.holdout_samples) & {s.id for s in labeled + unlabeled})

    def test_activation_rollback_does_not_rewrite_flow(self):
        first, second = self.build(), self.build()
        flow = Flow.objects.create(name="Model user", graph={"nodes": [{"id": "cls", "type": "dl_classify", "params": {"model": first.asset_id}}], "edges": []})
        original = flow.graph
        for number in (first.number, second.number):
            response = self.post(self.base + f"/models/{number}/activate")
            self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["flows_using_previous"][0]["flow_id"], flow.id)
        first.refresh_from_db()
        self.assertEqual(first.status, "retired")
        response = self.post(self.base + f"/models/{second.number}/rollback")
        self.assertEqual(response.status_code, 200, response.content)
        first.refresh_from_db()
        second.refresh_from_db()
        flow.refresh_from_db()
        self.assertEqual((first.status, second.status), ("active", "retired"))
        self.assertEqual(flow.graph, original)
        from apps.core.models import AuditLog

        self.assertTrue(AuditLog.objects.filter(action="dl.model.activate", target_id=str(self.project.id)).exists())

    def test_compare_and_correction_cycle(self):
        for value, label in [(10, "dark"), (100, "bright")]:
            sample = api._save_sample(self.project, np.full((19, 27, 3), value, np.uint8), label)
            sample.split = "test"
            sample.save(update_fields=["split"])
        first = self.build()
        failed = first.failures[0]["sample_id"]
        response = self.post(self.base + "/corrections", {"sample_id": failed})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["holdout"])
        self.assertEqual(self.project.samples.get(pk=failed).labeled_by, "correction")
        # 另外補一張不同的修正樣本，保留影像仍只供驗證。
        correction = api._save_sample(self.project, np.full((19, 27, 3), 20, np.uint8), "bright")
        response = self.post(self.base + "/corrections", {"sample_id": str(correction.pk), "label": "bright"})
        self.assertEqual(response.status_code, 200)
        second = self.build()
        response = self.client.get(self.base + f"/models/compare?a={first.number}&b={second.number}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["new"], [])
        self.assertEqual(len(response.json()["fixed"]), 1)
        self.assertEqual((first.metrics["accuracy"], second.metrics["accuracy"]), (0.5, 1.0))
        print("Model correction cycle: holdout accuracy 0.5 -> 1.0; failures 1 -> 0; holdout unchanged")

    def test_apply_requires_current_flow_version(self):
        version = self.build()
        from apps.vision import fixed_images

        descriptor = fixed_images.store(np.zeros((19, 27, 3), np.uint8))
        flow = Flow.objects.create(name="Apply", graph={"nodes": [
            {"id": "source", "type": "fixed_image", "params": {"images": [descriptor]}},
            {"id": "model", "type": "dl_classify", "params": {"model": version.asset_id}}],
            "edges": [{"source": "source", "target": "model", "source_handle": "image", "target_handle": "image"}]})
        url = self.base + f"/models/{version.number}/apply-to-flow"
        data = {"flow_id": flow.id, "node_id": "model"}
        self.assertEqual(self.post(url, data).status_code, 422)
        data["expected_updated_at"] = "2000-01-01T00:00:00+00:00"
        self.assertEqual(self.post(url, data).status_code, 409)
        data["expected_updated_at"] = flow.updated_at.isoformat()
        response = self.post(url, data)
        self.assertEqual(response.status_code, 200, response.content)

    def test_retrieval_edits_preserve_old_asset_and_skip_identical_bytes(self):
        from apps.vision.dl.retrieval_trainer import RetrievalTrainer

        self.project.trainer_kind = "retrieval"
        self.project.save()
        rows = model_versions.prepare(self.project, {})
        path = save_png(np.zeros((8, 8, 3), np.uint8), self.folder, "unused.png")
        backbone = Path(self.folder) / "backbone.onnx"
        fake_backbone(str(backbone), size=32)
        samples = [SampleRef(str(r.id), r.label, r.path, split=r.split) for r in rows]
        result = RetrievalTrainer().train(samples, self.project.classes, {"backbone_path": str(backbone), "input_size": 32}, "cpu", lambda *args: None)
        model = retrieval.loads(result.weights_bytes)
        self.assertFalse({s.id for s in samples if s.split == "test"} & set(model["source_ids"]))
        path = Path(path).with_suffix(".npz")
        path.write_bytes(result.weights_bytes)
        asset = Asset.objects.create(name="Library", kind="model", path=str(path), meta={"tool_key": "dl_retrieval", "tool_params": result.weights_tool_params})
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with mock.patch.object(model_versions, "evaluate", return_value=({"holdout_count": 2, "accuracy": 1.0, "error_count": 0}, [])):
            same = model_versions.retrieval_edit(self.project, asset, result.weights_bytes)
            self.assertEqual(same.pk, asset.pk)
            self.assertEqual(self.project.model_versions.count(), 0)
            data = retrieval.remove(model, 0)
            newer = model_versions.retrieval_edit(self.project, asset, data)
            self.assertNotEqual(newer.pk, asset.pk)
            self.assertEqual(self.project.model_versions.count(), 1)
            model_versions.retrieval_edit(self.project, newer, data)
            self.assertEqual(self.project.model_versions.count(), 1)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        import cv2

        image = np.full((19, 27, 3), 90, np.uint8)
        upload = cv2.imencode(".png", image)[1].tobytes()
        with mock.patch.object(model_versions, "evaluate", return_value=({"holdout_count": 2, "accuracy": 1.0, "error_count": 0}, [])):
            url = self.base + "/retrieval-library/items"
            response = self.client.post(url, {"files": [SimpleUploadedFile("correction.png", upload)], "label": "dark"})
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(self.project.model_versions.count(), 2)
            response = self.client.post(url, {"files": [SimpleUploadedFile("same.png", upload)], "label": "dark"})
            self.assertEqual(response.json()["duplicates"], 1)
            self.assertEqual(self.project.model_versions.count(), 2)

    def test_registration_snapshots_are_independent_and_reusable(self):
        from apps.vision import fixed_images

        descriptor = fixed_images.store(np.zeros((19, 27, 3), np.uint8))
        flow = Flow.objects.create(name="Registration", graph={"nodes": [{"id": "reg", "type": "register_detect", "params": {"registrations": [descriptor]}}], "edges": []})
        url = f"/api/vision/dl/registrations/{flow.pk}/reg/models"
        first = self.post(url)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(self.post(url).json()["id"], first.json()["id"])
        flow.graph["nodes"][0]["params"]["registrations"] = []
        flow.save()
        second = self.post(url)
        self.assertEqual(second.json()["parent"], 1)
        version = DlModelVersion.objects.get(pk=first.json()["id"])
        self.assertEqual(version.params["settings"]["registrations"], [descriptor])
        self.assertIsNone(version.project_id)
        Path(fixed_images.path_of(descriptor["id"])).unlink()
        model_versions.restore_registration(version)
        self.assertIsNotNone(fixed_images.load(descriptor["id"]))

    def test_frozen_evidence_survives_sample_deletion(self):
        version = self.build()
        sid = version.holdout_samples[0]
        sample = self.project.samples.get(pk=sid)
        Path(sample.path).unlink()
        sample.delete()
        response = self.client.get(f"/api/vision/dl/samples/{sid}/file?max=160&model_version={version.id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        response = self.post(self.base + "/corrections", {"sample_id": sid, "model_version": version.id})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["holdout"])

    def test_batch_correction_retains_source_picture(self):
        from apps.vision.batch import store
        from apps.vision.models import BatchRun, BatchSet

        flow = Flow.objects.create(name="Batch", graph={"nodes": [], "edges": []})
        batch = BatchSet.objects.create(flow=flow, name="Corrections")
        batch.images = store.save_images(batch, [("error", np.full((23, 31, 3), 45, np.uint8))])
        batch.save()
        run = BatchRun.objects.create(batch_set=batch, graph=flow.graph)
        response = self.post(self.base + "/corrections", {"batch_run_id": run.pk, "index": 0, "label": "bright"})
        self.assertEqual(response.status_code, 200, response.content)
        sample = self.project.samples.get(pk=response.json()["sample"]["id"])
        self.assertEqual((sample.label, sample.labeled_by, sample.split), ("bright", "correction", "train"))
        self.assertEqual(SampleRef(str(sample.id), sample.label, sample.path).load().shape, (23, 31, 3))

    def test_mutations_require_dl_feature(self):
        version = self.build()
        admin = self.post("/api/auth/setup", {"username": "admin", "password": "secret1"}).json()["token"]
        self.client.post("/api/users", data=json.dumps({"username": "operator", "password": "pass123", "role": "operator"}),
                         content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {admin}")
        token = self.post("/api/auth/login", {"username": "operator", "password": "pass123"}).json()["token"]
        for path in (f"/models/{version.number}/activate", f"/models/{version.number}/rollback", "/corrections"):
            response = self.client.post(self.base + path, data="{}", content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
            self.assertEqual(response.status_code, 403, response.content)

    def test_holdout_errors_are_bounded_and_comparison_reports_truncation(self):
        sample = self.rows[0]
        refs = [SampleRef(str(uuid.uuid4()), "bright", sample.path, split="test") for _ in range(205)]
        with mock.patch.object(model_versions, "infer", return_value=SimpleNamespace(outputs={"label": "dark"})):
            metrics, failures = model_versions.evaluate("dl_classify", "fake", {}, refs, self.project.classes)
        self.assertEqual((metrics["error_count"], len(failures)), (205, 200))

    def test_project_deletion_can_collect_its_versions(self):
        self.build()
        response = self.client.delete(self.base)
        self.assertEqual(response.status_code, 204, response.content)

    def test_shape_holdout_records_overlap_and_predicted_geometry(self):
        sample = SampleRef("shape", "", self.rows[0].path,
                           shapes=[{"kind": "bbox", "label": "dark", "points": [[3 / 27, 2 / 19], [9 / 27, 7 / 19]]}], split="test")
        predicted = np.zeros((19, 27), np.uint8)
        predicted[2:8, 3:10] = 1
        with mock.patch.object(model_versions, "infer", return_value=SimpleNamespace(outputs={"class_map": predicted})):
            metrics, failures = model_versions.evaluate("dl_segment", "fake", {}, [sample], self.project.classes)
        self.assertEqual(metrics["iou"], 1.0)
        self.assertEqual(failures, [])
        predicted[:] = 0
        predicted[2:8, 13:20] = 1
        with mock.patch.object(model_versions, "infer", return_value=SimpleNamespace(outputs={"class_map": predicted})):
            metrics, failures = model_versions.evaluate("dl_segment", "fake", {}, [sample], self.project.classes)
        self.assertEqual(metrics["iou"], 0.0)
        self.assertEqual(failures[0]["prediction"]["regions"], [{"label": "dark", "x": 13, "y": 2, "w": 7, "h": 6}])
        self.assertEqual(failures[0]["truth"], sample.shapes)

    def test_real_classifier_holdout_evaluation(self):
        job = jobs.TrainJob(uuid.uuid4().hex, self.project.pk, self.project.name, "mlp_classify", "cpu")
        jobs._train(job, self.project.pk, {"input_size": 16, "hidden": 8, "epochs": 40, "val_split": 0})
        self.assertEqual(job.pending.holdout_metrics["holdout_count"], 2)
        self.assertGreaterEqual(job.pending.holdout_metrics["accuracy"], 0.5)
        jobs.discard(job)
