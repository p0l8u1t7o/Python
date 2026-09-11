"""杯口複驗的數值訊息與缺陷計數回歸。"""

import math
import re

import numpy as np
from django.test import SimpleTestCase

from apps.vision import inspect
from tests._helpers import run_tool
from tests.test_inspect import base_graph, run_graph, stage8_task


class Stage9Fix2Tests(SimpleTestCase):
    def test_tolerance_message_distinguishes_measurement_from_limits(self):
        for nominal, lower_tol, upper_tol in ((35, -.2, .005), (12, -.05, .05),
                                               (-35, -.005, .2), (1e8, -.0002, .0005),
                                               (0, -1e-20, 1e-20), (35, 0, 0), (35, .005, -.2)):
            lower, upper = sorted((nominal + lower_tol, nominal + upper_tol))
            values = [lower, upper, math.nextafter(lower, -math.inf), math.nextafter(lower, math.inf),
                      math.nextafter(upper, -math.inf), math.nextafter(upper, math.inf)]
            if nominal == 35 and upper_tol == .005:
                values.append(35.012385823320194)
            for value in values:
                with self.subTest(nominal=nominal, lower_tol=lower_tol, upper_tol=upper_tol, value=value):
                    result = run_tool("tolerance_judge", params={"nominal": nominal, "lower_tol": lower_tol, "upper_tol": upper_tol}, inputs={"value": value})
                    found = re.fullmatch(r"(.+)mm deviation (.+) \((.+) to (.+)\) -> (PASS|FAIL)", result.message)
                    self.assertIsNotNone(found, result.message)
                    shown, _deviation, low, high = map(float, found.groups()[:4])
                    self.assertEqual((shown < low, shown > low), (value < lower, value > lower), result.message)
                    self.assertEqual((shown < high, shown > high), (value < upper, value > upper), result.message)
                    expected = lower <= value <= upper
                    self.assertEqual(result.status, "ok" if expected else "ng")
                    self.assertEqual(result.branch, "pass" if expected else "fail")
                    self.assertEqual(result.outputs["in_spec"], expected)
                    self.assertEqual(result.outputs["deviation"], value - nominal)
                    self.assertEqual((result.outputs["lower"], result.outputs["upper"]), (lower, upper))

    def test_tolerance_message_keeps_invalid_measurements_unchanged(self):
        for value in (None, float("nan"), float("inf")):
            result = run_tool("tolerance_judge", inputs={"value": value})
            self.assertEqual(result.message, f"The measurement is invalid ({value!r}) -> FAIL")
            self.assertEqual(result.status, "ng")
            self.assertFalse(result.outputs["in_spec"])

    def test_circular_evidence_labels_zero_one_and_multiple_defects(self):
        y, x = np.ogrid[:701, :1001]
        radius = np.hypot(x - 500, y - 350)
        theta = np.degrees(np.arctan2(y - 350, x - 500))
        graph = inspect.build(base_graph(), stage8_task("inspect_circular_surface"))
        for count in (0, 1, 2):
            outer = np.full((701, 1001), 250)
            for angle in (-60, 60)[:count]:
                outer[abs(theta - angle) < 6] = 210
            image = (np.clip(radius - 229.5, 0, 1) * np.clip(outer + .5 - radius, 0, 1) * 220).astype(np.uint8)
            reading = inspect.evidence(graph, run_graph(graph, image))[0]
            unit = "defect" if count == 1 else "defects"
            self.assertEqual(reading["value"], count)
            self.assertEqual(reading["unit"], unit)
            self.assertTrue(reading["reason"].startswith(f"{count} {unit}, longest "), reading["reason"])
            self.assertIn("deg (minimum", reading["reason"])
