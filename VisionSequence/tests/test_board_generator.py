from __future__ import annotations

import cv2
import numpy as np
from django.test import SimpleTestCase, TestCase

from apps.vision import calib, calibboard


def _decode_png(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    assert image is not None
    return image


class BoardGeneratorGeometryTests(SimpleTestCase):
    def test_chessboard_spacing_matches_dpi_truth(self):
        spec = calibboard.validate_spec("chessboard", rows=6, cols=9, spacing=20, dpi=300)
        gray = _decode_png(calibboard.png_bytes(spec))
        found, corners = cv2.findChessboardCorners(gray, (9, 6))
        self.assertTrue(found)
        cv2.cornerSubPix(
            gray,
            corners,
            (7, 7),
            (-1, -1),
            (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001),
        )
        pts = corners.reshape(6, 9, 2)
        steps = np.concatenate(
            [
                np.linalg.norm(np.diff(pts, axis=1), axis=2).ravel(),
                np.linalg.norm(np.diff(pts, axis=0), axis=2).ravel(),
            ],
        )
        expected = 20 / 25.4 * 300
        self.assertLess(abs(float(np.median(steps)) - expected), 1.0)

    def test_asymmetric_circles_grid_is_detectable(self):
        spec = calibboard.validate_spec("acircles", rows=6, cols=9, spacing=20, dpi=300)
        gray = _decode_png(calibboard.png_bytes(spec))
        found, centers = cv2.findCirclesGrid(gray, (9, 6), flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
        self.assertTrue(found)
        self.assertEqual(len(centers), 54)


    def test_generated_boards_are_found_by_platform_find_board(self):
        """產生的板子，**平台自己的 `calib.find_board` 要抓得到**。

        原本這一支只直接呼叫 `cv2.findCirclesGrid`（而且沒帶 CLUSTERING），所以測的是
        「OpenCV 抓不抓得到」而不是「平台抓不抓得到」。實際上 `find_board` 一律加
        `CALIB_CB_CLUSTERING`，在乾淨的合成／列印圓點板上**四種行列組合全部失敗**——
        等於平台產生了自己讀不了的標定板，而使用者的流程就是「產板→列印→拍照→標定」。
        現在 `find_board` 會退回非 CLUSTERING，這條就守住那個退路。
        """
        for kind, rows, cols in (("chessboard", 6, 9), ("acircles", 4, 11), ("acircles", 6, 4)):
            with self.subTest(kind=kind, rows=rows, cols=cols):
                spec = calibboard.validate_spec(kind, rows=rows, cols=cols, spacing=20, dpi=300)
                gray = _decode_png(calibboard.png_bytes(spec))
                found = calib.find_board(gray, cols, rows, kind)
                self.assertIsNotNone(found, f"{kind} {rows}x{cols} 找不到")
                self.assertEqual(len(found), rows * cols)

                # 縮到現場拍攝的量級也要找得到（列印稿是高解析度，相機拍到的小得多）
                small = cv2.resize(gray, None, fx=0.28, fy=0.28, interpolation=cv2.INTER_AREA)
                shot = calib.find_board(small, cols, rows, kind)
                self.assertIsNotNone(shot, f"{kind} {rows}x{cols} 縮小後找不到")
                self.assertEqual(len(shot), rows * cols)

    def test_dark_background_boards_still_work(self):
        """深色底白點的板子是既有的退路，加了非 CLUSTERING 之後不能壞。"""
        spec = calibboard.validate_spec("acircles", rows=4, cols=11, spacing=20, dpi=300)
        inverted = 255 - _decode_png(calibboard.png_bytes(spec))
        found = calib.find_board(inverted, 11, 4, "acircles")
        self.assertIsNotNone(found)
        self.assertEqual(len(found), 44)


class BoardGeneratorApiTests(TestCase):
    def test_endpoint_returns_png(self):
        response = self.client.get("/api/vision/calibration/board.png?pattern=chessboard&rows=6&cols=9&spacing=20&dpi=300")
        self.assertEqual(response.status_code, 200, response.content[:120])
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_endpoint_rejects_bad_parameters(self):
        bad_rows = self.client.get("/api/vision/calibration/board.png?pattern=chessboard&rows=2&cols=9&spacing=20&dpi=300")
        self.assertEqual(bad_rows.status_code, 422, bad_rows.content)
        bad_dpi = self.client.get("/api/vision/calibration/board.png?pattern=chessboard&rows=6&cols=9&spacing=20&dpi=2400")
        self.assertEqual(bad_dpi.status_code, 422, bad_dpi.content)
