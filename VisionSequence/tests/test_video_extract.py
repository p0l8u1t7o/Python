"""影片建立 DL 樣本：不需要 GPU，分割工具以 mock 回固定 polygon。"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest import mock

import cv2
from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.vision import demo_images
from apps.vision.dl import video
from apps.vision.models import DlProject


def _wait_done(timeout: float = 5.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        job = video.status()
        if job and job["status"] != "running":
            return job
        time.sleep(0.02)
    return video.status()


def _write_video(path: Path, frames: list, fps: float = 12.0) -> None:
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    assert writer.isOpened()
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


@override_settings(DATA_DIR=Path(tempfile.gettempdir()) / "vs-codex-testdata")
class VideoExtractTests(TransactionTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vs-video-"))
        self.project = DlProject.objects.create(name=f"video-{time.time_ns()}", trainer_kind="ai_seg", classes=["part"])
        self.video_path = self.tmp / "seq.avi"
        _write_video(self.video_path, demo_images.conveyor_sequence())

    def tearDown(self):
        video.stop()

    @staticmethod
    def _segmenter():
        calls = {"n": 0}

        def run(_image, _params, _factory):
            calls["n"] += 1
            y = 12 + calls["n"] * 5
            return [{
                "label": "part", "index": 0, "score": 0.9,
                "x": 20, "y": y, "w": 24, "h": 18, "cx": 32, "cy": y + 9,
                "centroid": [32, y + 9],
                "polygon": [[20, y], [44, y], [44, y + 18], [20, y + 18]],
            }]

        return run

    def test_extract_saves_n_per_confirmed_track_and_deduplicates(self):
        params = {"n": 2, "k": 1, "confirm_frames": 2, "margin_top": 0, "margin_bottom": 0, "max_distance": 50, "split": "train"}
        with mock.patch.object(video, "ai_segment", side_effect=self._segmenter()):
            video.start(self.project.id, str(self.video_path), params)
            job = _wait_done()
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(job["saved"], 2)
        self.assertEqual(job["per_class"], {"part": 2})
        self.project.refresh_from_db()
        samples = list(self.project.samples.order_by("created_at"))
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].split, "train")
        self.assertEqual(samples[0].labeled_by, "auto")
        shape = samples[0].shapes[0]
        self.assertEqual(shape["label"], "part")
        self.assertEqual(shape["kind"], "polygon")
        self.assertGreater(shape["points"][0][0], 0)
        self.assertLess(shape["points"][1][0], 1)
        self.assertGreater(shape["points"][2][1], shape["points"][0][1])

        with mock.patch.object(video, "ai_segment", side_effect=self._segmenter()):
            video.start(self.project.id, str(self.video_path), params)
            rerun = _wait_done()
        self.assertEqual(rerun["status"], "done", rerun)
        self.assertEqual(self.project.samples.count(), 2)
        self.assertGreaterEqual(rerun["duplicates"], 1)

    def test_stop_cancels_running_job(self):
        long_path = self.tmp / "long.avi"
        frames = demo_images.conveyor_sequence() * 8
        _write_video(long_path, frames)

        def slow(image, params, factory):
            time.sleep(0.03)
            return self._segmenter()(image, params, factory)

        with mock.patch.object(video, "ai_segment", side_effect=slow):
            video.start(self.project.id, str(long_path), {"n": 10, "k": 1, "confirm_frames": 1, "margin_top": 0, "margin_bottom": 0})
            time.sleep(0.08)
            self.assertTrue(video.stop())
            job = _wait_done()
        self.assertEqual(job["status"], "cancelled", job)

    def test_api_start_status_and_video_list(self):
        videos = Path(settings.DATA_DIR) / "videos" / "api"
        videos.mkdir(parents=True, exist_ok=True)
        target = videos / "seq.avi"
        target.write_bytes(self.video_path.read_bytes())
        r = self.client.get("/api/vision/videos")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(any(item["name"] == "api/seq.avi" for item in r.json()["items"]))
        with mock.patch.object(video, "ai_segment", side_effect=self._segmenter()):
            r = self.client.post(
                f"/api/vision/dl/projects/{self.project.id}/video-extract",
                data=json.dumps({"video": "api/seq.avi", "params": {"n": 1, "k": 1, "confirm_frames": 1, "margin_top": 0, "margin_bottom": 0}}),
                content_type="application/json",
            )
            self.assertEqual(r.status_code, 202, r.content)
            job = _wait_done()
        self.assertEqual(job["status"], "done", job)
        r = self.client.get(f"/api/vision/dl/projects/{self.project.id}/video-extract/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["job"]["status"], "done")
