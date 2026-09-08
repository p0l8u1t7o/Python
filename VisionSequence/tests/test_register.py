"""註冊式檢測：用局部平均色假模型驗證搜尋、座標與判定契約。"""

import os
import tempfile
from unittest import mock

import cv2
import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.vision import fixed_images
from apps.vision.dl import anomaly
from apps.vision.tools.base import ToolError
from tests._helpers import fake_backbone, run_tool


def pictures():
    """含背景邊界的方塊與圓形裁切圖，以及三方塊一圓的場景。"""
    square = np.full((96, 96, 3), 30, np.uint8)
    square[16:80, 16:80] = 220
    circle = np.full_like(square, 30)
    cv2.circle(circle, (48, 48), 32, (220, 220, 220), -1)
    scene = np.full((480, 640, 3), 30, np.uint8)
    for x, y in [(64, 48), (256, 48), (64, 240)]:
        scene[y:y + 96, x:x + 96] = square
    scene[240:336, 448:544] = circle
    return square, circle, scene


class RegisterTests(SimpleTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="vs-register-")
        self.addCleanup(folder.cleanup)
        override = override_settings(VISION={**settings.VISION, "ASSET_DIR": folder.name, "SAMPLE_DIR": os.path.join(folder.name, "samples")})
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(anomaly.clear_sessions)
        self.path = fake_backbone(anomaly.backbone_path(), 320)
        self.square, self.circle, self.scene = pictures()
        self.positive = fixed_images.store(self.square, "Square")
        self.negative = fixed_images.store(self.circle, "Circle")
        self.params = {"registrations": [self.positive], "device": "cpu", "min_similarity": 0.9}

    def detect(self, image=None, **params):
        return run_tool("register_detect", self.scene if image is None else image, {**self.params, **params})

    def test_detection_and_contract(self):
        result = self.detect(negatives=[self.negative])
        self.assertEqual(result.outputs['count'], 3, result.outputs)
        self.assertEqual((result.status, result.branch), ('ok', 'found'))
        self.assertIs(result.outputs['present'], True)
        reference = run_tool("template_match", self.scene, {"templates": [self.positive], "max_matches": 10})
        self.assertEqual(set(result.outputs['matches'][0]), set(reference.outputs['matches'][0]))
        for match in result.outputs['matches']:
            self.assertEqual(match['label'], 'Square')
            self.assertTrue(any(abs(match['cx'] - x) <= 16 and abs(match['cy'] - y) <= 12 for x, y in [(112, 96), (304, 96), (112, 288)]))
        self.assertEqual(result.outputs['best_score'], max(m['score'] for m in result.outputs['matches']))

    def test_negatives_remove_lookalike(self):
        before = self.detect(min_similarity=0.7)
        after = self.detect(min_similarity=0.7, negatives=[self.negative])
        self.assertEqual(before.outputs['count'], 4, before.outputs)
        self.assertEqual(after.outputs['count'], 3, after.outputs)

    def test_multiple_labels_and_negative_tie(self):
        result = self.detect(registrations=[self.positive, self.negative])
        self.assertEqual(result.outputs['count'], 4, result.outputs)
        self.assertEqual(sorted(m['label'] for m in result.outputs['matches']), ['Circle', 'Square', 'Square', 'Square'])
        self.assertEqual(self.detect(negatives=[self.positive]).outputs['count'], 0)

    def test_modes_and_empty_search(self):
        for low, high, verdict in [(3, 3, 'ok'), (4, 5, 'ng'), (0, 2, 'ng')]:
            result = self.detect(negatives=[self.negative], mode='count', min_count=low, max_count_ok=high)
            self.assertEqual((result.status, result.branch), (verdict, verdict))
        empty = np.full_like(self.scene, 30)
        for image, expected, verdict in [(self.scene, 'present', 'ok'), (self.scene, 'absent', 'ng'), (empty, 'present', 'ng'), (empty, 'absent', 'ok')]:
            result = self.detect(image, mode='presence', expected=expected)
            self.assertEqual((result.status, result.branch), (verdict, verdict))
        result = self.detect(empty)
        self.assertEqual((result.status, result.branch), ('ng', 'not_found'))
        self.assertEqual(result.outputs['best_score'], 0)
        self.assertTrue(np.isnan(result.outputs['best_x']))
        result = self.detect(empty, mode='count', min_count=0, max_count_ok=0)
        self.assertEqual(result.status, 'ok')

    def test_roi_and_purity(self):
        before = self.scene.copy()
        registered = fixed_images.load(self.positive['id']).copy()
        self.scene.setflags(write=False)
        roi = {"shape": "rect", "x": 32, "y": 24, "w": 352, "h": 156}
        result = self.detect(roi=roi, negatives=[self.negative])
        self.assertEqual(result.outputs['count'], 2, result.outputs)
        for match, overlay in zip(result.outputs['matches'], result.overlays):
            self.assertAlmostEqual(overlay['x'] + overlay['w'] / 2, match['cx'])
            self.assertGreater(match['cx'], 90)
            self.assertLess(match['cy'], 130)
        np.testing.assert_array_equal(self.scene, before)
        np.testing.assert_array_equal(fixed_images.load(self.positive['id']), registered)
        for roi in [{"shape": "rect", "x": 0, "y": 0, "w": 20, "h": 20}, {"shape": "rect", "x": 900, "y": 900, "w": 20, "h": 20}]:
            result = self.detect(roi=roi)
            self.assertEqual((result.status, result.branch), ('ng', 'not_found'))

    def test_scale_size_and_nms(self):
        image = np.full_like(self.scene, 30)
        image[120:264, 192:336] = cv2.resize(self.square, (144, 144))
        result = self.detect(image, scales='1.0,1.5', min_size=130, max_size=150)
        self.assertEqual(result.outputs['count'], 1, result.outputs)
        self.assertEqual(result.outputs['matches'][0]['w'], 144)
        self.assertEqual(self.detect(image, scales='1.5', max_size=100).outputs['count'], 0)
        result = self.detect(registrations=[self.positive, self.positive], scales='1.0,1.0', negatives=[self.negative], max_count=2)
        self.assertEqual(result.outputs['count'], 2)

    def test_errors_and_private_override(self):
        with self.assertRaisesMessage(ToolError, 'Add at least one registered picture'):
            self.detect(registrations=[])
        with self.assertRaisesMessage(ToolError, 'install the deep learning pack'):
            self.detect(backbone_path=self.path + '.missing')
        with mock.patch.object(anomaly, 'backbone_path', return_value='missing'):
            self.assertGreater(self.detect(backbone_path=self.path).outputs['count'], 0)
        for value in ['0', '-1', 'nan', 'inf', '1,,2', 'bad']:
            with self.subTest(value=value), self.assertRaises(ToolError):
                self.detect(scales=value)
        for params in [{'min_similarity': float('nan')}, {'angle_step': float('inf')}, {'nms_overlap': -1}, {'max_count': 0}]:
            with self.subTest(params=params), self.assertRaises(ToolError):
                self.detect(**params)
        with mock.patch.object(anomaly, 'session_for', side_effect=anomaly.AnomalyError('ONNX failure')):
            with self.assertRaisesMessage(ToolError, 'The feature model could not be loaded') as error:
                self.detect()
            self.assertNotIn('ONNX', str(error.exception))
        with mock.patch.object(anomaly, 'extract', side_effect=RuntimeError('ONNX failure')):
            with self.assertRaisesMessage(ToolError, 'The feature model could not process this picture'):
                self.detect()

    def test_rotation_and_rotated_roi(self):
        patch = np.full((96, 144, 3), 30, np.uint8)
        patch[16:80, 16:128] = 220
        desc = fixed_images.store(patch, 'Long part')
        image = np.full_like(self.scene, 30)
        image[120:264, 192:288] = cv2.rotate(patch, cv2.ROTATE_90_CLOCKWISE)
        result = self.detect(image, registrations=[desc], angle_range=90, angle_step=90, min_similarity=0.95)
        self.assertEqual(result.outputs['count'], 1, result.outputs)
        match = result.outputs['matches'][0]
        self.assertEqual(abs(match['angle']), 90)
        self.assertAlmostEqual(match['cx'], 240, delta=16)
        self.assertAlmostEqual(match['cy'], 192, delta=12)
        self.assertEqual(self.detect(image, registrations=[desc], angle_range=90, angle_step=0, min_similarity=0.95).outputs['count'], 0)
        image = np.full((480, 640, 3), 30, np.uint8)
        image[192:288, 248:392] = patch
        matrix = cv2.getRotationMatrix2D((320, 240), -30, 1)
        rotated = cv2.warpAffine(image, matrix, (640, 480), borderValue=(30, 30, 30))
        roi = {'shape': 'rotated_rect', 'cx': 320, 'cy': 240, 'w': 320, 'h': 240, 'angle': 30}
        result = self.detect(rotated, registrations=[desc], roi=roi)
        self.assertEqual(result.outputs['count'], 1, result.outputs)
        match = result.outputs['matches'][0]
        self.assertAlmostEqual(match['cx'], 320, delta=12)
        self.assertAlmostEqual(match['cy'], 240, delta=12)
        self.assertEqual(match['angle'], 30)
        self.assertEqual(result.overlays[0]['angle'], 30)

    def test_demo_sequence_with_installed_fake_model(self):
        from apps.vision import demo, engine
        from apps.vision.api_more import SOURCE_PLACEHOLDER, instantiate
        from apps.vision.graph import compile_graph, validate_graph

        samples = demo.template_samples('register_count')
        graph = instantiate(demo.register_count_flow(SOURCE_PLACEHOLDER), source_id=None, samples=samples)
        compiled = compile_graph(validate_graph(graph))
        statuses = []
        for sample in samples:
            result = engine.execute(compiled, flow_id=0, flow_version=1, trigger='test', grab=lambda _: None, asset_path=lambda _: None, preview=True, input_image=fixed_images.load(sample['id']))
            self.assertFalse([n.message for n in result.nodes.values() if n.status == 'error'])
            statuses.append(result.status)
        self.assertEqual(statuses, ['ok', 'ok', 'ok', 'ng'])
