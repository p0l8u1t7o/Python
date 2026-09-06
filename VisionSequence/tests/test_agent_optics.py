"""取像計算：鏡頭焦距／視野／解析度／景深／頻寬／曝光上限，以及助手的 camera_optics 查詢。"""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.accounts.security import Principal
from apps.vision.agent import lookup, optics, skills


class OpticsTests(SimpleTestCase):
    def test_focal_length_and_fov_are_inverses(self):
        sensor = 8.8  # 2/3"
        f = optics.focal_length(sensor, fov_mm=100.0, wd_mm=300.0)
        self.assertAlmostEqual(f, 300 * 8.8 / 108.8, places=6)
        self.assertAlmostEqual(optics.fov_from_focal(sensor, f, 300.0), 100.0, places=4)
        self.assertAlmostEqual(optics.working_distance(sensor, 100.0, f), 300.0, places=4)

    def test_fov_needs_a_distance_beyond_the_focal_length(self):
        with self.assertRaises(ValueError):
            optics.fov_from_focal(8.8, 50.0, 40.0)

    def test_sensor_formats(self):
        self.assertEqual(optics.sensor_size('1/1.8"'), (7.2, 5.4))
        self.assertEqual(optics.sensor_size("2/3"), (8.8, 6.6))
        self.assertIsNone(optics.sensor_size("nonsense"))

    def test_pixels_and_nearest_lens(self):
        self.assertEqual(optics.pixels_for(fov_mm=100.0, feature_mm=0.5, per_feature=3.0), 600)
        self.assertEqual(optics.nearest_focal(20.5), 16.0)
        self.assertEqual(optics.nearest_focal(26.0), 25.0)
        self.assertAlmostEqual(optics.mm_per_pixel(100.0, 2000), 0.05)

    def test_bandwidth_and_interfaces(self):
        self.assertAlmostEqual(optics.bandwidth_mb_s(2448, 2048, 1, 30), 150.4, places=1)
        self.assertEqual(optics.interfaces_for(150.4)[0], "CameraLink-Base")  # GigE 撐不住
        self.assertNotIn("GigE", optics.interfaces_for(150.4))
        self.assertEqual(optics.interfaces_for(5000.0), [])  # 沒有介面夠快
        self.assertLessEqual(len(optics.interfaces_for(10.0)), 3)

    def test_exposure_and_depth_of_field(self):
        # 0.05 mm/px、500 mm/s：一個像素的模糊＝100 µs
        self.assertAlmostEqual(optics.max_exposure_us(500.0, 0.05), 100.0, places=3)
        deep = optics.depth_of_field(16.0, f_number=11, wd_mm=300.0, coc_mm=0.02)
        shallow = optics.depth_of_field(16.0, f_number=2.8, wd_mm=300.0, coc_mm=0.02)
        self.assertGreater(deep, shallow)  # 光圈越小景深越深


class SolveTests(SimpleTestCase):
    def test_full_spec_from_a_typical_question(self):
        r = optics.solve(fov_mm=120, wd_mm=300, feature_mm=0.2, task="detect", sensor_format="2/3",
                         fps=20, speed_mm_s=500, f_number=8)
        self.assertEqual(r["pixels_needed"], 1800)
        self.assertEqual(r["megapixels_needed"], round(1800 * 1350 / 1e6, 2))
        self.assertEqual(r["focal_standard_mm"], 16.0)
        self.assertGreater(r["fov_at_standard_mm"], 120)  # 標準鏡頭比算出來的短 → 視野變大
        self.assertAlmostEqual(r["max_exposure_us"], 133.3, places=1)
        self.assertIn("GigE", r["interfaces"])
        self.assertEqual(r["cycle_ms"], 50.0)
        self.assertTrue(all(isinstance(n, str) for n in r["notes"]))

    def test_measure_needs_more_pixels_than_detect(self):
        detect = optics.solve(fov_mm=50, feature_mm=0.1, task="detect")
        measure = optics.solve(fov_mm=50, feature_mm=0.1, task="measure")
        self.assertLess(detect["pixels_needed"], measure["pixels_needed"])

    def test_says_what_is_missing_instead_of_guessing(self):
        r = optics.solve(fov_mm=100, wd_mm=250)
        self.assertNotIn("focal_mm", r)
        self.assertTrue(any("感光元件" in n for n in r["notes"]))

    def test_bad_values_are_ignored(self):
        r = optics.solve(fov_mm="nonsense", wd_mm=-5, feature_mm=None)
        self.assertNotIn("pixels_needed", r)
        self.assertNotIn("focal_mm", r)

    def test_colour_triples_the_bandwidth(self):
        mono = optics.solve(fov_mm=100, feature_mm=0.2, fps=30)
        colour = optics.solve(fov_mm=100, feature_mm=0.2, fps=30, color="color")
        self.assertAlmostEqual(colour["bandwidth_mb_s"], mono["bandwidth_mb_s"] * 3, delta=0.2)  # 各自四捨五入後差一位小數


class LookupTests(TestCase):
    def test_camera_optics_is_available_to_any_signed_in_user(self):
        user = User.objects.create_user("optic", password="x")
        p = Principal(kind="user", user=user)
        out = lookup.dispatch(p, "camera_optics", {"fov_mm": 60, "wd_mm": 200, "feature_mm": 0.1, "sensor_format": "1/1.8"})
        self.assertNotIn("error", out)
        self.assertEqual(out["pixels_needed"], 1800)
        self.assertIn("focal_standard_mm", out)
        self.assertIn("camera_optics", [s["name"] for s in lookup.specs()])

    def test_imaging_skill_is_searchable(self):
        from apps.vision.agent import help as help_mod

        self.assertIn("imaging", skills.GUIDE_KEYS)
        self.assertTrue(skills.imaging_sections())
        hits = help_mod.search("打光 刮痕 暗場", k=5)
        self.assertTrue(any("Imaging" in s.page_title or "打光" in s.heading for s, _ in hits), [s.heading for s, _ in hits])
        lens = help_mod.search("鏡頭 焦距 怎麼選", k=5)
        self.assertTrue(any("選型" in s.heading or "鏡頭" in s.heading for s, _ in lens), [s.heading for s, _ in lens])


class ParseTests(SimpleTestCase):
    """一句話 → 參數：不跨標點、認得單位、感光元件格式裡的數字不會被當成尺寸。"""

    def test_typical_question(self):
        args = optics.parse_question("視野 120 mm、工作距離 300 mm、要看 0.2 mm 的缺陷，選什麼相機和鏡頭？介面夠嗎（20 fps）？")
        self.assertEqual(args, {"fov_mm": 120.0, "wd_mm": 300.0, "feature_mm": 0.2, "fps": 20.0})

    def test_sensor_format_digits_are_not_sizes(self):
        args = optics.parse_question("用 25 mm 鏡頭、工作距離 400 mm，2/3 吋相機的視野多大？")
        self.assertEqual(args["focal_mm"], 25.0)
        self.assertEqual(args["wd_mm"], 400.0)
        self.assertEqual(args["sensor_format"], "2/3")
        self.assertNotIn("fov_mm", args)  # 2/3 的 3 不能變成視野

    def test_units_and_task(self):
        args = optics.parse_question("量測公差 0.05 mm，視野 8 cm，輸送帶 12 m/min")
        self.assertEqual(args["task"], "measure")
        self.assertEqual(args["fov_mm"], 80.0)  # cm → mm
        self.assertAlmostEqual(args["speed_mm_s"], 200.0, places=1)  # m/min → mm/s

    def test_not_about_imaging(self):
        self.assertEqual(optics.parse_question("怎麼建立第一個流程？"), {})
        self.assertFalse(optics.relevant("怎麼建立第一個流程？"))
        self.assertTrue(optics.relevant("刮痕要怎麼打光？"))

    def test_help_precomputes_when_the_question_has_numbers(self):
        from apps.vision.agent import help as help_mod

        secs = help_mod._optics_section("視野 120 mm、工作距離 300 mm，2/3 吋相機，0.2 mm 缺陷")
        self.assertEqual(len(secs), 1)
        self.assertIn("focal_standard_mm", secs[0].text)
        self.assertIn("16", secs[0].text)
        self.assertEqual(help_mod._optics_section("怎麼建立第一個流程？"), [])
        self.assertEqual(help_mod._optics_section("刮痕要怎麼打光？"), [])  # 沒有數字就不算
