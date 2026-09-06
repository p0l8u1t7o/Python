"""流程變數：記憶體儲存的規則、落地與重載、沙箱、兩個工具、跨 run 的累計、API 與權限、TCP VARS／SET。"""

from __future__ import annotations

import json

import numpy as np
from django.conf import settings
from django.test import TestCase, TransactionTestCase, override_settings

from apps.accounts import permissions
from apps.vision import variables
from apps.vision.models import Flow, FlowVariable, ImageSource
from apps.vision.runner import runner
from apps.vision.tcp_server import Session
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool


class StoreTests(TestCase):
    def setUp(self):
        variables.store.clear()
        variables.store.on_dirty = None
        self.addCleanup(variables.store.clear)

    def test_names_and_values_are_checked(self):
        s = variables.store
        for bad in ("", "1abc", "a-b", "x" * 65, "has space"):
            with self.assertRaises(variables.VariableError, msg=bad):
                s.set(None, bad, 1)
        s.set(1, "ok_1", 5)
        self.assertEqual(s.get(1, "ok_1"), 5)
        self.assertEqual(s.get(1, "nope", "dflt"), "dflt")
        self.assertIsNone(s.get(None, "ok_1"))  # 範圍不同就不是同一個變數
        with self.assertRaises(variables.VariableError):
            s.set(1, "obj", object())
        with self.assertRaises(variables.VariableError):
            s.set(1, "big", ["x" * 1000] * 100)

    def test_numpy_scalars_become_plain_and_images_stay_in_memory(self):
        s = variables.store
        s.set(1, "f", np.float32(1.5))
        s.set(1, "i", np.int64(7))
        s.set(1, "b", np.bool_(True))
        self.assertEqual((type(s.get(1, "f")), s.get(1, "i"), s.get(1, "b")), (float, 7, True))
        img = np.zeros((4, 6), np.uint8)
        s.set(1, "last", img)
        self.assertIs(s.get(1, "last"), img)
        self.assertEqual(s.snapshot(1)["last"], {"image": True, "width": 6, "height": 4})
        s.set(1, "nan", float("nan"))
        self.assertIsNone(s.get(1, "nan"))

    def test_flush_and_reload(self):
        s = variables.store
        fid = Flow.objects.create(name="persist", graph={"nodes": [], "edges": []}).id
        s.set(fid, "count", 3)
        s.set(None, "lot", "A17")
        s.set(fid, "img", np.zeros((2, 2), np.uint8))
        self.assertEqual(s.flush(), 3)
        self.assertEqual(set(FlowVariable.objects.values_list("name", flat=True)), {"count", "lot"})  # 影像不落地
        self.assertEqual(s.flush(), 0)  # 沒有髒的就不寫
        s.set(fid, "count", 4)
        s.delete(None, "lot")
        s.flush()
        self.assertEqual(FlowVariable.objects.get(flow_id=fid, name="count").value, 4)
        self.assertFalse(FlowVariable.objects.filter(name="lot").exists())
        # 重開機：記憶體清掉再載入
        s.clear()
        s.ensure_loaded(fid)
        self.assertEqual(s.get(fid, "count"), 4)
        self.assertIsNone(s.get(fid, "img"))

    def test_loading_never_overwrites_a_newer_value_in_memory(self):
        FlowVariable.objects.create(flow_id=None, name="lot", value="OLD")
        variables.store.set(None, "lot", "NEW")
        variables.store.ensure_loaded(None)
        self.assertEqual(variables.store.get(None, "lot"), "NEW")

    def test_forget_and_delete(self):
        s = variables.store
        s.set(1, "a", 1)
        s.set(2, "a", 2)
        s.forget(1)
        self.assertIsNone(s.get(1, "a"))
        self.assertEqual(s.get(2, "a"), 2)
        self.assertTrue(s.delete(2, "a"))
        self.assertFalse(s.delete(2, "a"))

    def test_on_dirty_is_called(self):
        calls = []
        variables.store.on_dirty = lambda: calls.append(1)
        variables.store.set(1, "x", 1)
        self.assertEqual(calls, [1])

    def test_parse_default(self):
        self.assertEqual(variables.parse_default("12"), 12)
        self.assertEqual(variables.parse_default("1.5"), 1.5)
        self.assertEqual(variables.parse_default("true"), True)
        self.assertEqual(variables.parse_default("A17"), "A17")
        self.assertIsNone(variables.parse_default(""))


class ToolTests(TestCase):
    """run_tool 的 ctx 是 preview=True：一律沙箱，不碰真正的儲存。"""

    def setUp(self):
        variables.store.clear()
        variables.store.on_dirty = None
        self.addCleanup(variables.store.clear)

    def test_set_modes(self):
        ctx: dict = {}
        self.assertEqual(run_tool("variable_set", None, {"name": "c", "mode": "add"}, context=ctx).outputs["value"], 1)
        self.assertEqual(run_tool("variable_set", None, {"name": "c", "mode": "add"}, inputs={"value": 2}, context=ctx).outputs["value"], 3)
        self.assertEqual(run_tool("variable_set", None, {"name": "c", "mode": "max"}, inputs={"value": 2}, context=ctx).outputs["value"], 3)
        self.assertEqual(run_tool("variable_set", None, {"name": "c", "mode": "min"}, inputs={"value": 2}, context=ctx).outputs["value"], 2)
        r = run_tool("variable_set", None, {"name": "c", "mode": "set"}, inputs={"value": "A17"}, context=ctx)
        self.assertEqual((r.outputs["value"], r.outputs["previous"]), ("A17", 2))
        self.assertIn("trial", r.message)
        self.assertEqual(variables.store.snapshot(1), {})  # 沙箱：真正的儲存沒被碰

    def test_get_defaults_and_shapes(self):
        r = run_tool("variable_get", None, {"name": "missing", "default": "1.5"})
        self.assertEqual((r.outputs["value"], r.outputs["number"], r.outputs["text"], r.outputs["found"]), (1.5, 1.5, "1.5", False))
        r = run_tool("variable_get", None, {"name": "flag", "default": "true"})
        self.assertEqual((r.outputs["value"], r.outputs["number"]), (True, 1.0))
        variables.store.set(1, "lot", "B2")
        r = run_tool("variable_get", None, {"name": "lot", "default": ""})  # 沙箱讀得到真正的值
        self.assertEqual((r.outputs["value"], r.outputs["found"]), ("B2", True))
        self.assertTrue(np.isnan(r.outputs["number"]))

    def test_errors_are_explained(self):
        with self.assertRaises(ToolError):
            run_tool("variable_set", None, {"name": "x", "mode": "set"}, inputs={})
        with self.assertRaises(ToolError):
            run_tool("variable_set", None, {"name": "x", "mode": "add"}, inputs={"value": "abc"})
        with self.assertRaises(ToolError):
            run_tool("variable_get", None, {"name": "bad name"})
        with self.assertRaises(ToolError):
            run_tool("variable_set", None, {"name": "x", "scope": "nope"}, inputs={"value": 1})

    def test_station_scope(self):
        ctx: dict = {}
        run_tool("variable_set", None, {"name": "s", "scope": "station"}, inputs={"value": 9}, context=ctx)
        self.assertEqual(run_tool("variable_get", None, {"name": "s", "scope": "station"}, context=ctx).outputs["value"], 9)
        self.assertFalse(run_tool("variable_get", None, {"name": "s", "scope": "flow"}, context=ctx).outputs["found"])

    def test_image_can_be_kept_for_the_next_part(self):
        ctx: dict = {}
        img = np.full((8, 8), 7, np.uint8)
        run_tool("variable_set", None, {"name": "prev"}, inputs={"value": img}, context=ctx)
        got = run_tool("variable_get", None, {"name": "prev"}, context=ctx).outputs["value"]
        self.assertTrue(np.array_equal(got, img))


def counting_graph(source_id: int) -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": source_id}},
            {"id": "count", "type": "variable_set", "params": {"name": "parts", "mode": "add"}},
            {"id": "read", "type": "variable_get", "params": {"name": "parts", "default": "0"}},
            {"id": "out", "type": "output", "params": {"name": "parts"}},
        ],
        # 變數工具沒有影像埠：用隱含的 _image 直通埠串出執行順序
        "edges": [
            {"source": "src", "source_handle": "image", "target": "count", "target_handle": "_image"},
            {"source": "count", "source_handle": "_image", "target": "read", "target_handle": "_image"},
            {"source": "read", "source_handle": "value", "target": "out", "target_handle": "value"},
        ],
    }


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class RunTests(TransactionTestCase):
    def setUp(self):
        variables.store.clear()
        variables.store.on_dirty = None
        self.addCleanup(variables.store.clear)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 32, "height": 24})
        self.flow = Flow.objects.create(name="counting", graph=counting_graph(self.source.id))
        self.addCleanup(runner.forget, self.flow.id)

    def test_counter_survives_between_runs_but_not_previews(self):
        first = runner.run_sync(self.flow, trigger="api")
        second = runner.run_sync(self.flow, trigger="api")
        self.assertEqual((first.outputs["parts"], second.outputs["parts"]), (1, 2))
        self.assertEqual(variables.store.get(self.flow.id, "parts"), 2)
        trial = runner.run_sync(self.flow, trigger="preview", preview=True)
        self.assertEqual(trial.outputs["parts"], 3)  # 試執行看得到自己那一次的 +1
        self.assertEqual(variables.store.get(self.flow.id, "parts"), 2)  # 但沒留下來
        variables.store.flush()
        self.assertEqual(FlowVariable.objects.get(flow_id=self.flow.id, name="parts").value, 2)

    def test_values_set_from_outside_are_visible_to_the_next_run(self):
        variables.store.set(self.flow.id, "parts", 40)
        report = runner.run_sync(self.flow, trigger="api")
        self.assertEqual(report.outputs["parts"], 41)


class ApiTests(TestCase):
    def setUp(self):
        variables.store.clear()
        variables.store.on_dirty = None
        self.addCleanup(variables.store.clear)
        self.flow = Flow.objects.create(name="v", graph={"nodes": [], "edges": []})

    def put(self, path, values, **kw):
        return self.client.put(path, data=json.dumps({"values": values}), content_type="application/json", **kw)

    def test_flow_and_station_round_trip(self):
        r = self.put(f"/api/vision/flows/{self.flow.id}/variables", {"lot": "A17", "count": 3})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["items"], {"lot": "A17", "count": 3})
        self.assertEqual(FlowVariable.objects.filter(flow=self.flow).count(), 2)  # write-through
        r = self.put("/api/vision/variables", {"shift": "night"})
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.get(f"/api/vision/flows/{self.flow.id}/variables")
        self.assertEqual(r.json()["items"]["lot"], "A17")
        self.assertEqual(r.json()["station"], {"shift": "night"})
        self.assertEqual(self.client.get("/api/vision/variables").json()["items"], {"shift": "night"})
        self.assertEqual(self.client.delete(f"/api/vision/flows/{self.flow.id}/variables/lot").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/vision/flows/{self.flow.id}/variables/lot").status_code, 404)
        self.assertEqual(self.client.delete("/api/vision/variables/shift").status_code, 204)
        self.assertFalse(FlowVariable.objects.filter(name__in=["lot", "shift"]).exists())

    def test_bad_input(self):
        self.assertEqual(self.put(f"/api/vision/flows/{self.flow.id}/variables", {"bad name": 1}).status_code, 422)
        self.assertEqual(self.client.put(f"/api/vision/flows/{self.flow.id}/variables", data="{}", content_type="application/json").status_code, 422)
        self.assertEqual(self.put("/api/vision/flows/999/variables", {"a": 1}).status_code, 404)
        self.assertEqual(self.put(f"/api/vision/flows/{self.flow.id}/variables", {"x": {"nested": [1, 2]}}).status_code, 200)

    def test_writing_needs_the_teach_feature(self):
        r = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret1"}), content_type="application/json")
        admin = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['token']}"}
        self.client.post("/api/users", data=json.dumps({"username": "op", "password": "pass123", "role": "operator"}), content_type="application/json", **admin)
        token = self.client.post("/api/auth/login", data=json.dumps({"username": "op", "password": "pass123"}), content_type="application/json").json()["token"]
        op = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        # 出廠值：操作員可以換線（flows.teach）
        self.assertEqual(self.put(f"/api/vision/flows/{self.flow.id}/variables", {"lot": "B"}, **op).status_code, 200)
        # 管理員把 flows.teach 從操作員拿掉 → 只能讀不能寫
        keep = [f for f in permissions.defaults("operator") if f != "flows.teach"]
        r = self.client.patch("/api/users/permissions", data=json.dumps({"role": "operator", "features": keep}), content_type="application/json", **admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.put(f"/api/vision/flows/{self.flow.id}/variables", {"lot": "C"}, **op).status_code, 403)
        self.assertEqual(self.client.get(f"/api/vision/flows/{self.flow.id}/variables", **op).status_code, 200)


class TcpTests(TestCase):
    def setUp(self):
        variables.store.clear()
        variables.store.on_dirty = None
        self.addCleanup(variables.store.clear)
        self.flow = Flow.objects.create(name="line 1", graph={"nodes": [], "edges": []})
        self.session = Session(secret="")

    def cmd(self, line):
        return self.session.command(line)[0]

    def test_set_and_vars(self):
        r = self.cmd(f'SET {self.flow.id} lot=00123 target=1.5 note="two words"')
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["items"], {"lot": "00123", "target": 1.5, "note": "two words"})  # 前導零保留
        self.assertEqual(self.cmd('SET station shift=night')["items"], {"shift": "night"})
        r = self.cmd(f"VARS {self.flow.id}")
        self.assertEqual(r["items"]["lot"], "00123")
        self.assertEqual(self.cmd("VARS station")["items"], {"shift": "night"})
        self.assertEqual(self.cmd('VARS "line 1"')["scope"], "line 1")
        self.assertEqual(FlowVariable.objects.filter(flow=self.flow, name="lot").first().value, "00123")

    def test_errors(self):
        self.assertEqual(self.cmd("SET")["code"], "missing_argument")
        self.assertEqual(self.cmd("SET 999 a=1")["code"], "flow_not_found")
        self.assertEqual(self.cmd(f"SET {self.flow.id}")["code"], "missing_argument")
        self.assertEqual(self.cmd(f"SET {self.flow.id} notkv")["code"], "bad_argument")
        self.assertEqual(self.cmd(f"SET {self.flow.id} 1bad=1")["code"], "bad_variable")
