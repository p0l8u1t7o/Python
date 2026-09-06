"""格式化回覆：format_text 工具，以及 TCP `fmt=` 與 HTTP `format=` 回純文字。

為什麼要有這條路：很多產線設備（PLC、舊上位機、條碼機）解析不了 JSON，只吃
`OK,12.35,8.10\r\n` 這種一行文字。流程裡用「格式化回覆」工具排好版，觸發時指定要哪一個具名輸出就好。
"""

from __future__ import annotations

import json

import numpy as np
from django.test import TestCase, TransactionTestCase, override_settings
from django.conf import settings

from apps.vision.models import Flow, ImageSource
from apps.vision.tcp_server import Session
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool


class FormatTextToolTests(TestCase):
    def test_fills_names_from_everywhere_a_line_can_come_from(self):
        r = run_tool(
            "format_text", None, {"template": "{judge},{width:.2f},{lot},{a}"},
            inputs={"a": 7}, context={"_judge": "ok", "_outputs": {"width": 12.3456}, "lot": "00123"},
        )
        self.assertEqual(r.outputs["text"], "OK,12.35,00123,7")
        self.assertEqual(r.context["_outputs"]["text"], "OK,12.35,00123,7")  # 具名輸出：回覆帶得走

    def test_line_endings_and_escapes(self):
        self.assertEqual(run_tool("format_text", None, {"template": "a\\r\\nb"}).outputs["text"], "a\r\nb")
        self.assertEqual(run_tool("format_text", None, {"template": "x", "ending": "crlf"}).outputs["text"], "x\r\n")
        self.assertEqual(run_tool("format_text", None, {"template": "x", "ending": "lf"}).outputs["text"], "x\n")
        self.assertEqual(run_tool("format_text", None, {"template": "a\\tb"}).outputs["text"], "a\tb")
        # 樣板已經自己結尾時不要重複（使用者兩種寫法都會用）
        self.assertEqual(run_tool("format_text", None, {"template": "x\\r\\n"}).outputs["text"], "x\r\n")

    def test_missing_names(self):
        self.assertEqual(run_tool("format_text", None, {"template": "a={nope}."}).outputs["text"], "a=.")
        self.assertEqual(run_tool("format_text", None, {"template": "a={nope}", "missing": "keep"}).outputs["text"], "a={nope}")
        with self.assertRaises(ToolError) as bad:
            run_tool("format_text", None, {"template": "{nope}", "missing": "fail"})
        self.assertIn("nope", str(bad.exception))

    def test_numbers_from_numpy_and_a_custom_output_name(self):
        r = run_tool("format_text", None, {"template": "{a:.1f}|{b}|{c}", "name": "plc_line"},
                     inputs={"a": np.float32(3.14159), "b": np.int64(5), "c": np.bool_(True)})
        self.assertEqual(r.outputs["text"], "3.1|5|True")
        self.assertIn("plc_line", r.context["_outputs"])

    def test_bad_layouts_are_explained(self):
        with self.assertRaises(ToolError):
            run_tool("format_text", None, {"template": "   "})
        with self.assertRaises(ToolError) as bad:
            run_tool("format_text", None, {"template": "{width:.2f}"}, context={"_outputs": {"width": "abc"}})
        self.assertIn("could not be filled in", str(bad.exception))

    def test_run_id_and_station_are_always_available(self):
        with override_settings(VISION={**settings.VISION, "STATION_ID": "ST09"}):
            r = run_tool("format_text", None, {"template": "{station}:{run_id}"})
        self.assertTrue(r.outputs["text"].startswith("ST09:"))


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class PlainTextReplyTests(TransactionTestCase):
    """跨執行緒跑 run：TransactionTestCase＋關掉背景持久化。"""

    def setUp(self):
        source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": source.id}},
                {"id": "i", "type": "intensity", "params": {}},
                {"id": "j", "type": "judge", "params": {"verdict": "ok"}},
                {"id": "f", "type": "format_text", "params": {"template": "{judge},{a:.1f},{lot}", "ending": "crlf", "name": "line"}},
            ],
            "edges": [{"source": "src", "target": "i"}, {"source": "i", "sourceHandle": "mean", "target": "f", "targetHandle": "a"}],
        }
        r = self.client.post("/api/vision/flows", data=json.dumps({"name": "fmt", "graph": graph}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.flow = Flow.objects.get(pk=r.json()["id"])

    def test_http_format_returns_one_line(self):
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/run",
                             data=json.dumps({"wait": True, "format": "line", "context": {"lot": "A17"}}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r["Content-Type"], "text/plain; charset=utf-8")
        text = r.content.decode()
        self.assertTrue(text.startswith("OK,"), text)
        self.assertTrue(text.endswith(",A17\r\n"), repr(text))

    def test_http_format_names_the_mistake(self):
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/run",
                             data=json.dumps({"wait": True, "format": "nope"}), content_type="application/json")
        self.assertEqual(r.status_code, 422)
        body = r.json()["error"]
        self.assertEqual(body["code"], "no_such_output")
        self.assertIn("line", body["details"]["outputs"])

    def test_json_reply_is_unchanged_without_format(self):
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/run", data=json.dumps({"wait": True}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r["Content-Type"].startswith("application/json"))
        self.assertTrue(r.json()["outputs"]["line"].endswith("\r\n"))

    def test_tcp_fmt_returns_the_raw_line(self):
        session = Session(secret="")
        response, _ = session.command(f'RUN {self.flow.id} fmt=line lot="B 2"')
        self.assertIn("_raw", response, response)
        self.assertTrue(response["_raw"].startswith("OK,"))
        self.assertTrue(response["_raw"].endswith(",B 2\r\n"), repr(response["_raw"]))

    def test_tcp_without_fmt_is_still_json(self):
        session = Session(secret="")
        response, _ = session.command(f"RUN {self.flow.id}")
        self.assertNotIn("_raw", response)
        self.assertTrue(response["ok"])
        self.assertEqual(response["judge"], "OK")

    def test_tcp_fmt_for_an_output_that_is_not_there(self):
        session = Session(secret="")
        response, _ = session.command(f"RUN {self.flow.id} fmt=nope")
        self.assertFalse(response["ok"])
        self.assertEqual(response["code"], "no_such_output")
        self.assertIn("line", response["outputs"])
