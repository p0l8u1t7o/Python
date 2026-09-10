"""註冊式檢測：用局部平均色假模型驗證搜尋、座標與判定契約。"""

import os
import tempfile
import time
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


class RegistrationExtensionsTests(SimpleTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='vs-register-extended-')
        self.addCleanup(folder.cleanup)
        override = override_settings(VISION={**settings.VISION, 'ASSET_DIR': folder.name, 'SAMPLE_DIR': os.path.join(folder.name, 'samples')})
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(anomaly.clear_sessions)
        fake_backbone(anomaly.backbone_path(), 320)

    def test_classes_append_and_cache(self):
        from apps.vision import demo, demo_images
        from apps.vision.tools.builtin import register

        refs, _ = demo._registration_refs()
        image = demo_images.registered_classes()[0]
        params = {'registrations': refs, 'device': 'cpu', 'min_similarity': .9, 'mode': 'count',
                  'class_limits': 'circle:3,3\nsquare:3,3\ntriangle:3,3'}
        with mock.patch.object(register, '_grid', wraps=register._grid) as extract:
            before = run_tool('register_detect', image, params)
            self.assertEqual(extract.call_count, 7)
            extract.reset_mock()
            self.assertEqual(run_tool('register_detect', image, params).outputs, before.outputs)
            self.assertEqual(extract.call_count, 1)
            extra = fixed_images.store(demo_images.registration_shapes()['diamond'], 'diamond:1.png')
            extract.reset_mock()
            start = time.perf_counter()
            after = run_tool('register_detect', image, {**params, 'registrations': [*refs, extra]})
            elapsed = (time.perf_counter() - start) * 1000
            self.assertEqual(extract.call_count, 2, 'Only the scene and new reference should be extracted')
        self.assertEqual(before.outputs['counts'], {'circle': 3, 'square': 3, 'triangle': 3})
        self.assertEqual(after.outputs['counts'], {**before.outputs['counts'], 'diamond': 0})
        self.assertEqual(before.status, 'ok')
        for match in before.outputs['matches']:
            row = round((match['cy'] - 72) / 144)
            column = round((match['cx'] - 80) / 192)
            self.assertEqual(match['label'], ['circle', 'square', 'triangle'][row])
            self.assertLess(abs(match['cy'] - (72 + 144 * row)), 16)
            self.assertIn(column, range(3))
            self.assertLess(abs(match['cx'] - (80 + 192 * column)), 16)

        def projection(result):
            return [{k: v for k, v in match.items() if k not in ('runner_up', 'runner_up_score', 'margin')} for match in result.outputs['matches']]
        self.assertEqual(projection(before), projection(after))
        with_fourth = image.copy()
        with_fourth[96:192, 544:640] = demo_images.registration_shapes()['diamond']
        expanded = run_tool('register_detect', with_fourth, {**params, 'registrations': [*refs, extra]})
        self.assertEqual(expanded.outputs['counts'], {'circle': 3, 'square': 3, 'triangle': 3, 'diamond': 1})
        count_value = run_tool('formula', params={'expression': "a['diamond']"}, inputs={'a': expanded.outputs['counts']})
        self.assertEqual(count_value.outputs['value'], 1)
        diamond = next(match for match in expanded.outputs['matches'] if match['label'] == 'diamond')
        self.assertAlmostEqual(diamond['cx'], 592, delta=16)
        self.assertAlmostEqual(diamond['cy'], 144, delta=12)
        for match in after.outputs['matches']:
            self.assertNotEqual(match['label'], match['runner_up'])
            self.assertAlmostEqual(match['margin'], match['score'] - match['runner_up_score'])
        print(f'STAGE16B append reference 7: {elapsed:.3f} ms; extractions=2 (scene+new); classes=3/3/3; accuracy=9/9; fourth class=1/1')

    def test_class_limits_zero_and_validation(self):
        from apps.vision import demo, demo_images

        refs, _ = demo._registration_refs()
        image = demo_images.registered_classes()[0]
        base = {'registrations': refs, 'device': 'cpu', 'mode': 'count'}
        result = run_tool('register_detect', image, {**base, 'classes': 'circle\nsquare\ntriangle\nmissing', 'class_limits': 'missing:1,1'})
        self.assertEqual(result.outputs['counts']['missing'], 0)
        self.assertEqual(result.status, 'ng')
        for limits in ['circle:3,2', 'circle:-1,2', 'circle:1.5,2', 'missing:0,1', 'circle:0,1\ncircle:1,2', 'bad']:
            with self.subTest(limits=limits), self.assertRaises(ToolError):
                run_tool('register_detect', image, {**base, 'class_limits': limits})
        for names in ['circle\ncircle', 'wrong', 'circle:one']:
            with self.subTest(names=names), self.assertRaises(ToolError):
                run_tool('register_detect', image, {**base, 'classes': names})

    def test_segmentation_truth_modes_and_purity(self):
        from apps.vision import demo, demo_images

        refs, negatives = demo._registration_refs(segment=True)
        params = {'registrations': refs, 'negatives': negatives, 'device': 'cpu'}
        for width, height in [(641, 481), (1001, 701), (333, 297)]:
            image, truth = demo_images.registration_texture_scene(width, height)
            original = image.copy()
            image.setflags(write=False)
            result = run_tool('register_segment', image, params)
            mask = result.outputs['mask']
            iou = np.count_nonzero((mask != 0) & (truth != 0)) / np.count_nonzero((mask != 0) | (truth != 0))
            self.assertGreaterEqual(iou, .7)
            self.assertEqual(result.outputs['count'], 3)
            self.assertEqual(mask.dtype, np.uint8)
            self.assertLessEqual(set(np.unique(mask)), {0, 255})
            self.assertEqual(result.outputs['area'], int(np.count_nonzero(mask)))
            self.assertEqual(sum(r['area'] for r in result.outputs['regions']), result.outputs['area'])
            exact_area = result.outputs['area']
            self.assertEqual(run_tool('register_segment', image, {**params, 'mode': 'area_range', 'min_area_total': exact_area, 'max_area_total': exact_area}).status, 'ok')
            self.assertEqual(run_tool('register_segment', image, {**params, 'mode': 'area_range', 'max_area_total': exact_area - 1}).status, 'ng')
            np.testing.assert_array_equal(image, original)
            print(f'STAGE16B segmentation {width}x{height}: IoU={iou:.6f}, regions=3, area={result.outputs["area"]}')
        image, _ = demo_images.registration_texture_scene(empty=True)
        empty = run_tool('register_segment', image, params)
        self.assertEqual((empty.status, empty.outputs['present'], empty.outputs['area']), ('ng', False, 0))
        self.assertEqual(run_tool('register_segment', image, {**params, 'mode': 'area_range', 'max_area_total': 0}).status, 'ok')
        self.assertEqual(run_tool('register_segment', image, {**params, 'mode': 'area_range', 'min_area_total': 1}).status, 'ng')

    def test_segmentation_masks_roi_and_errors(self):
        from apps.vision import demo_images

        image, truth = demo_images.registration_texture_scene()
        refs = [fixed_images.store(image, 'Texture'), fixed_images.store(truth, 'Texture#mask')]
        params = {'registrations': refs, 'device': 'cpu'}
        result = run_tool('register_segment', image, params)
        self.assertEqual(result.outputs['count'], 3)
        region = {'shape': 'rect', 'x': 0, 'y': 0, 'w': 250, 'h': 250}
        result = run_tool('register_segment', image, {**params, 'roi': region})
        self.assertEqual(result.outputs['count'], 1)
        self.assertFalse(result.outputs['mask'][250:].any())
        self.assertFalse(result.outputs['mask'][:, 250:].any())
        self.assertEqual(run_tool('register_segment', image, {**params, 'roi': {'shape': 'rect', 'x': 999, 'y': 999, 'w': 20, 'h': 20}}).outputs['area'], 0)
        for changes in [{'registrations': []}, {'registrations': [refs[1]]},
                        {'registrations': [refs[0], fixed_images.store(np.zeros_like(truth), 'Texture#mask')]},
                        {'registrations': [refs[0], fixed_images.store(np.ones((8, 8), np.uint8), 'Texture#mask')]},
                        {'registrations': [{'id': 'missing', 'name': 'Missing'}]},
                        {'min_margin': float('nan')}, {'min_area': -1}, {'cleanup': 21}, {'mode': 'invalid'},
                        {'min_area_total': 2, 'max_area_total': 1}, {'backbone_path': 'missing'}]:
            with self.subTest(changes=changes), self.assertRaises(ToolError):
                run_tool('register_segment', image, {**params, **changes})
        with self.assertRaises(ToolError):
            run_tool('register_segment', None, params)

    def test_new_template_sequences_and_graph_ports(self):
        from apps.vision import demo, engine
        from apps.vision.api_more import SOURCE_PLACEHOLDER, instantiate
        from apps.vision.graph import compile_graph, validate_graph

        for key, builder in [('register_classes', demo.register_classes_flow), ('register_segment', demo.register_segment_flow)]:
            samples = demo.template_samples(key)
            graph = instantiate(builder(SOURCE_PLACEHOLDER), source_id=None, samples=samples)
            compiled = compile_graph(validate_graph(graph))
            statuses = []
            for sample in samples:
                result = engine.execute(compiled, flow_id=0, flow_version=1, trigger='test', grab=lambda _: None,
                                        asset_path=lambda _: None, preview=True, input_image=fixed_images.load(sample['id']))
                statuses.append(result.status)
            self.assertEqual(statuses, ['ok', 'ok', 'ok', 'ng'], key)
            print(f'STAGE16B {key}: {" ".join(statuses)}')
        graph = demo.register_segment_flow(None)
        graph['nodes'].append({'id': 'count', 'type': 'pixel_count', 'params': {}})
        graph['edges'].append(demo._edge('segment', 'count', 'mask', 'image'))
        validate_graph(graph)
        graph = demo.register_classes_flow(None)
        graph['nodes'].append({'id': 'read_count', 'type': 'formula', 'params': {'expression': "a['circle']"}})
        graph['edges'].append(demo._edge('detect', 'read_count', 'counts', 'a'))
        validate_graph(graph)

    def test_competing_classes_and_unprefixed_contract(self):
        from apps.vision import demo_images

        patch = demo_images.registration_shapes()['square']
        first = fixed_images.store(patch, 'first:1')
        other = {**first, 'name': 'other:1'}
        image = np.full((297, 333, 3), 30, np.uint8)
        image[64:160, 64:160] = patch
        result = run_tool('register_detect', image, {'registrations': [first, other], 'min_similarity': .9, 'device': 'cpu'})
        self.assertEqual(result.outputs['count'], 1)
        match = result.outputs['matches'][0]
        self.assertEqual((match['label'], match['runner_up']), ('first', 'other'))
        self.assertAlmostEqual(match['margin'], 0, places=6)
        legacy = run_tool('register_detect', image, {'registrations': [{**first, 'name': 'Original'}], 'device': 'cpu'})
        self.assertEqual(legacy.outputs['counts'], {'default': 1})
        self.assertEqual(legacy.outputs['matches'][0]['label'], 'Original')
        self.assertNotIn('runner_up', legacy.outputs['matches'][0])

    def test_segmentation_cleanup_cache_and_rotated_roi(self):
        from apps.vision import demo, demo_images
        from apps.vision.tools.builtin import register

        refs, negatives = demo._registration_refs(segment=True)
        image, _ = demo_images.registration_texture_scene()
        params = {'registrations': refs, 'negatives': negatives, 'device': 'cpu'}
        with mock.patch.object(register, '_grid', wraps=register._grid) as extract:
            result = run_tool('register_segment', image, params)
            self.assertEqual(extract.call_count, 3)
            extract.reset_mock()
            warm = run_tool('register_segment', image, params)
            self.assertEqual(extract.call_count, 1)
            np.testing.assert_array_equal(result.outputs['mask'], warm.outputs['mask'])
            extra = fixed_images.store(np.clip(demo_images.registration_texture(True).astype(int) + 3, 0, 255).astype(np.uint8), 'Extra')
            extract.reset_mock()
            run_tool('register_segment', image, {**params, 'registrations': [*refs, extra]})
            self.assertEqual(extract.call_count, 2)
        removed = run_tool('register_segment', image, {**params, 'min_area': image.shape[0] * image.shape[1]})
        self.assertEqual((removed.outputs['count'], removed.outputs['area']), (0, 0))
        self.assertFalse(removed.outputs['mask'].any())
        for angle in [-25, 25]:
            roi = {'shape': 'rotated_rect', 'cx': 140, 'cy': 140, 'w': 200, 'h': 200, 'angle': angle}
            result = run_tool('register_segment', image, {**params, 'roi': roi})
            self.assertTrue(result.outputs['present'])
            region = result.outputs['regions'][0]
            self.assertLess(region['x'] + region['w'], 320)
            self.assertLess(region['y'] + region['h'], 300)
        # 遮罩省略時全部是前景，背景省略時相似度基準為零。
        result = run_tool('register_segment', demo_images.registration_texture(True), {'registrations': refs, 'device': 'cpu'})
        self.assertEqual(result.outputs['area'], 96 * 96)
