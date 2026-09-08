from __future__ import annotations

import os
import shutil

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision.dl import anomaly, base as dl_base, retrieval
from apps.vision.dl.base import SampleRef
from apps.vision.dl.retrieval_trainer import RetrievalTrainer
from apps.vision.tools import base as tools_base
from tests._helpers import fake_backbone, run_tool, save_png, temp_dir


SIZE = 64


def _image(label: str, variant: int = 0) -> np.ndarray:
    img = np.zeros((SIZE, SIZE, 3), np.uint8)
    if label == "red":
        img[:] = (30, 40, 210)
        img[:, (np.arange(SIZE) + variant) % 10 < 5, 1] = 95
    elif label == "green":
        img[:] = (45, 205, 35)
        img[(np.arange(SIZE) + variant) % 12 < 6, :, 0] = 115
    elif label == "blue":
        img[:] = (215, 45, 35)
        for i in range(-SIZE, SIZE, 12):
            cv2.line(img, (max(0, i), max(0, -i)), (min(SIZE - 1, i + SIZE), min(SIZE - 1, SIZE - i)), (215, 105, 90), 2)
    elif label == "yellow":
        img[:] = (35, 215, 220)
        img[::8, :, 2] = 160
    else:
        img[:] = (120, 120, 120)
    noise = np.full_like(img, variant % 7)
    return cv2.add(img, noise)


class RetrievalCoreTests(SimpleTestCase):
    def setUp(self):
        try:
            import onnxruntime  # noqa: F401
        except Exception:
            self.skipTest("onnxruntime is not available")
        self.folder = temp_dir()
        self.backbone = fake_backbone(os.path.join(self.folder, "fake.onnx"), SIZE)

    def tearDown(self):
        anomaly.clear_sessions()
        retrieval.invalidate()
        shutil.rmtree(self.folder, ignore_errors=True)

    def _samples(self, wrong: bool = False) -> tuple[list[SampleRef], list[str]]:
        classes = ["red", "green", "blue"]
        samples: list[SampleRef] = []
        for label in classes:
            for i in range(4):
                assigned = "green" if wrong and label == "red" and i == 0 else label
                path = save_png(_image(label, i), self.folder, f"{label}-{i}.png")
                samples.append(SampleRef(id=f"{label}-{i}", label=assigned, path=path, split="train"))
        return samples, classes

    def _train(self, wrong: bool = False):
        samples, classes = self._samples(wrong=wrong)
        trainer = RetrievalTrainer()
        result = trainer.train(
            samples,
            classes,
            {"input_size": SIZE, "topk": 3, "projection_dims": 0, "backbone_path": self.backbone},
            "cpu",
            lambda *_args: None,
        )
        model_path = os.path.join(self.folder, "library.npz")
        with open(model_path, "wb") as fh:
            fh.write(result.weights_bytes)
        model = retrieval.load(model_path)
        sess = retrieval.backbone_session(model, model_path, "cpu")
        return result, model, sess, model_path

    def test_build_and_query_three_clean_classes(self):
        result, model, sess, _path = self._train()
        self.assertEqual(result.weights_tool_key, "dl_retrieval")
        self.assertEqual(result.metrics["library_size"], 12)
        self.assertEqual(result.metrics["classes"], 3)
        self.assertEqual(result.metrics["leave_one_out_accuracy"], 1.0)
        red = retrieval.query(model, sess, _image("red", 9), 12)
        green = retrieval.query(model, sess, _image("green", 9), 3)
        self.assertEqual(red["label"], "red")
        self.assertEqual(green["label"], "green")
        same = max(row["similarity"] for row in red["topk"] if row["label"] == "red")
        different = max(row["similarity"] for row in red["topk"] if row["label"] != "red")
        self.assertGreater(same, different)

    def test_add_new_class_without_retraining(self):
        _result, model, sess, _path = self._train()
        old_before = retrieval.query(model, sess, _image("red", 5), 3)
        data = retrieval.add(model, _image("yellow", 0), "yellow", sess)
        updated = retrieval.loads(data)
        old_after = retrieval.query(updated, sess, _image("red", 5), 3)
        new_label = retrieval.query(updated, sess, _image("yellow", 3), 3)
        self.assertEqual(old_after["label"], old_before["label"])
        self.assertEqual(new_label["label"], "yellow")
        self.assertIn("yellow", updated["classes"])

    def test_remove_item_deletes_that_entry_from_results(self):
        _result, model, sess, _path = self._train()
        first = retrieval.query(model, sess, _image("red", 0), 12)
        removed_id = first["topk"][0]["id"]
        data = retrieval.remove(model, first["topk"][0]["index"])
        updated = retrieval.loads(data)
        second = retrieval.query(updated, sess, _image("red", 0), 12)
        self.assertNotIn(removed_id, [row["id"] for row in second["topk"]])

    def test_leave_one_out_drops_when_a_label_is_wrong(self):
        clean, _model, _sess, _path = self._train()
        wrong, _bad_model, _bad_sess, _bad_path = self._train(wrong=True)
        self.assertEqual(clean.metrics["leave_one_out_accuracy"], 1.0)
        self.assertLess(wrong.metrics["leave_one_out_accuracy"], 1.0)

    def test_npz_is_self_contained_after_backbone_file_is_removed(self):
        _result, model, sess, path = self._train()
        self.assertEqual(retrieval.query(model, sess, _image("blue", 7), 3)["label"], "blue")
        anomaly.clear_sessions()
        os.remove(self.backbone)
        loaded = retrieval.load(path)
        embedded_sess = retrieval.backbone_session(loaded, path, "cpu")
        self.assertEqual(retrieval.query(loaded, embedded_sess, _image("blue", 8), 3)["label"], "blue")

    def test_tool_branches_and_input_is_not_modified(self):
        _result, _model, _sess, path = self._train()
        image = _image("red", 4)
        original = image.copy()
        ok = run_tool("dl_retrieval", image, {"model": "m", "expected": "red", "topk": 3}, assets={"m": path})
        self.assertEqual((ok.status, ok.branch), ("ok", "ok"))
        self.assertEqual(ok.outputs["label"], "red")
        ng = run_tool("dl_retrieval", image, {"model": "m", "expected": "green", "topk": 3}, assets={"m": path})
        self.assertEqual((ng.status, ng.branch), ("ng", "ng"))
        miss = run_tool("dl_retrieval", _image("gray"), {"model": "m", "min_similarity": 0.99, "topk": 3}, assets={"m": path})
        self.assertEqual((miss.status, miss.branch), ("ng", "not_matched"))
        with self.assertRaises(tools_base.ToolError):
            run_tool("dl_retrieval", image, {"topk": 3}, assets={"m": path})
        # 指定了資產但查不到（模型被刪掉）也要是 ToolError：ctx.asset_path 是回 None
        # 不是丟例外，少擋一次現場看到的會是 Path(None) 的 TypeError。
        with self.assertRaises(tools_base.ToolError):
            run_tool("dl_retrieval", image, {"model": "gone", "topk": 3}, assets={"m": path})
        np.testing.assert_array_equal(image, original)

    def test_trainer_catalogue_registration(self):
        dl_base.register_builtins()
        trainer = dl_base.get_trainer("retrieval")
        self.assertEqual(trainer.label_mode, "classes")
        self.assertTrue(any(item["kind"] == "retrieval" for item in dl_base.catalogue()))


class RetrievalPoolingNoteTests(SimpleTestCase):
    def test_mean_and_max_pooling_separate_texture_more_than_mean_only(self):
        feats_a = np.array([[1, 0], [0, 1]], dtype=np.float32)
        feats_b = np.array([[0.5, 0.5], [0.5, 0.5]], dtype=np.float32)
        mean_a = feats_a.mean(axis=0)
        mean_b = feats_b.mean(axis=0)
        mean_sim = float(mean_a @ mean_b / (np.linalg.norm(mean_a) * np.linalg.norm(mean_b)))
        both_a = retrieval.vector_from_features(feats_a, None)
        both_b = retrieval.vector_from_features(feats_b, None)
        both_sim = float(both_a @ both_b)
        self.assertLess(both_sim, mean_sim)
