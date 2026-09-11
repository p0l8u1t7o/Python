"""檢測任務 ↔ 內建複合工具實例（PRODUCT-DIRECTION v2 P4）。"""

from __future__ import annotations

import copy
import json

import numpy as np
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accounts.models import AuthToken
from apps.core.errors import ValidationError
from apps.vision import composites, fixed_images, inspect, inspect_composite
from apps.vision.agent import tasklist
from apps.vision.composites_builtin import ensure_builtin_tools
from apps.vision.graph import validate_graph
from apps.vision.tools import base as tools
from apps.vision.tools import register_builtins
from tests.test_inspect import STAGE8_KINDS, annulus_image, base_graph, diameter_task, patterned_scene, run_graph, stage8_scene, stage8_task

CTX = {"composite": True}


def node(graph: dict, node_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == node_id)


def edges_to(graph: dict, target: str, handle: str | None = None) -> list[dict]:
    return [e for e in graph["edges"] if e["target"] == target and (handle is None or e["target_handle"] == handle)]


class InstanceBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    @classmethod
    def setUpTestData(cls):
        ensure_builtin_tools()

    def setUp(self):
        composites.invalidate()


class BuildReadUpdateTests(InstanceBase):
    def test_diameter_instance_round_trips_runs_and_updates_like_the_legacy_task(self):
        image = annulus_image()
        graph = inspect.build(base_graph(), diameter_task("d", nominal=300), CTX)
        inst = node(graph, "d")
        self.assertEqual(inst["type"], "composite:measure_diameter")
        self.assertEqual(inst["meta"], {"required": True})
        self.assertEqual(tools.output_aliases(inst), {"find:diameter": "d"})
        self.assertEqual(inst["params"]["tol:nominal"], 300)
        self.assertEqual(inst["params"]["find:edge_select"], "last")
        self.assertEqual({e["target_handle"] for e in edges_to(graph, "d")}, {"find:image"})
        self.assertTrue(any(e["source"] == "d" and e["source_handle"] == "tol:in_spec" and e["target"] == "inspection_summary" for e in graph["edges"]))
        listed = inspect.read(graph)
        self.assertEqual(listed["loose"], [])
        task = listed["tasks"][0]
        self.assertEqual((task["task_id"], task["kind"], task["source"], task["tool"], task["nodes"]), ("d", "measure_diameter", "composite", "measure_diameter", {"instance": "d"}))
        self.assertFalse(task["custom"])
        sent = diameter_task("d", nominal=300)["fields"]
        self.assertEqual({k: task["fields"][k] for k in sent}, sent)
        self.assertEqual(task["fields"]["mode"], "check")
        self.assertEqual(task["unit"], "px")
        report = run_graph(graph, image)
        self.assertEqual(report.status, "ok", report.to_dict())
        self.assertAlmostEqual(report.outputs["d"], 300, delta=0.08)
        self.assertEqual(report.nodes["d"].detail["composite"], "measure_diameter")
        reading = inspect.evidence(graph, report)[0]
        self.assertEqual((reading["verdict"], reading["node_id"], reading["unit"]), ("pass", "d", "px"))
        self.assertAlmostEqual(reading["value"], 300, delta=0.08)
        # 更新：只換公差；圖上其他東西一字不動
        before = copy.deepcopy(graph)
        updated = inspect.update(graph, {"task_id": "d", "fields": {"upper_tol": 0.01, "lower_tol": -0.01, "result_name": "dia"}})
        self.assertEqual(graph, before)
        self.assertEqual(node(updated, "d")["params"]["tol:upper_tol"], 0.01)
        self.assertEqual(tools.output_aliases(node(updated, "d")), {"find:diameter": "dia"})
        self.assertEqual(len(updated["edges"]), len(graph["edges"]))
        failed = run_graph(updated, image)
        self.assertEqual(inspect.evidence(updated, failed)[0]["verdict"], "fail")
        self.assertEqual(failed.outputs["judge"], "NG")
        # 切真圓度＝換成另一個內建工具，節點 id 與影像接線保留
        roundness = inspect.update(updated, {"task_id": "d", "fields": {"mode": "roundness", "upper_tol": 5}})
        self.assertEqual(node(roundness, "d")["type"], "composite:measure_roundness")
        self.assertEqual({e["target_handle"] for e in edges_to(roundness, "d")}, {"find:image"})
        task = inspect.read(roundness)["tasks"][0]
        self.assertEqual((task["fields"]["mode"], task["fields"]["upper_tol"], task["fields"]["result_name"]), ("roundness", 5, "dia"))
        reading = inspect.evidence(roundness, run_graph(roundness, image))[0]
        self.assertEqual(reading["verdict"], "pass")
        self.assertLess(reading["value"], 1)
        # 不合格的欄位仍由任務定義擋下
        with self.assertRaises(ValidationError):
            inspect.update(graph, {"task_id": "d", "fields": {"unit": "mm"}})
        # 找不到東西＝not_found，值為 None
        dark = run_graph(graph, np.zeros((701, 1001), np.uint8))
        reading = inspect.evidence(graph, dark)[0]
        self.assertEqual((reading["verdict"], reading["value"]), ("not_found", None))

    def test_every_kind_builds_reads_back_its_fields_and_executes(self):
        for kind in STAGE8_KINDS:
            if kind == "inspect_circular_surface":
                continue  # 拍板不做內建工具：照樣退回舊的節點組
            with self.subTest(kind=kind):
                task = stage8_task(kind)
                graph = inspect.build(base_graph(), task, CTX)
                inst = node(graph, "item")
                self.assertTrue(inst["type"].startswith("composite:"), inst["type"])
                read = next(t for t in inspect.read(graph)["tasks"] if t["task_id"] == "item")
                self.assertEqual(read["source"], "composite")
                for key, value in task["fields"].items():
                    self.assertEqual(read["fields"].get(key), value, (kind, key))
                report = run_graph(graph, stage8_scene(kind))
                reading = next(r for r in inspect.evidence(graph, report) if r["task_id"] == "item")
                self.assertEqual(reading["verdict"], "pass", (kind, report.to_dict()["nodes"].get("item")))
                self.assertEqual(report.outputs["judge"], "OK", kind)
                # 每一種都能只改一個欄位再讀回
                field, new_value = {"measure_distance": ("upper_tol", 3), "count_objects": ("max_count", 4), "check_presence": ("expected", "absent"),
                                    "inspect_edge_defect": ("max_defects", 2), "read_and_verify": ("expected", "OTHER")}[kind]
                updated = inspect.update(graph, {"task_id": "item", "fields": {field: new_value}})
                self.assertEqual(next(t for t in inspect.read(updated)["tasks"] if t["task_id"] == "item")["fields"][field], new_value, kind)
        circular = inspect.build(base_graph(), stage8_task("inspect_circular_surface"), CTX)
        self.assertTrue(any(n["id"] == "item_unwrap" for n in circular["nodes"]))

    def test_method_switch_keeps_node_and_external_connections(self):
        graph = inspect.build(base_graph(), stage8_task("check_presence", method="blob"), CTX)
        self.assertEqual(node(graph, "item")["type"], "composite:check_presence_blob")
        graph["nodes"].append({"id": "f", "type": "formula", "params": {"expression": "a"}})
        graph["edges"].append({"source": "item", "source_handle": "det:detected", "target": "f", "target_handle": "a"})
        validate_graph(copy.deepcopy(graph))
        switched = inspect.update(graph, {"task_id": "item", "fields": {"method": "print", "print_polarity": "light"}})
        self.assertEqual(node(switched, "item")["type"], "composite:check_presence_print")
        self.assertTrue(any(e["source"] == "item" and e["target"] == "f" for e in switched["edges"]), "external consumer of a still-existing port survives")
        read = next(t for t in inspect.read(switched)["tasks"] if t["task_id"] == "item")
        self.assertEqual((read["fields"]["method"], read["fields"]["print_polarity"]), ("print", "light"))
        # 拿掉實例：外部使用者擋下、圖不動
        result = inspect.remove(switched, "item")
        self.assertFalse(result["removed"])
        self.assertEqual(result["dependencies"][0]["target"], "f")
        self.assertEqual(result["graph"], switched)
        switched["edges"] = [e for e in switched["edges"] if e["target"] != "f"]
        removed = inspect.remove(switched, "item")
        self.assertTrue(removed["removed"])
        self.assertFalse(any(n["id"] in ("item", "inspection_summary") for n in removed["graph"]["nodes"]))

    def test_edge_defect_reference_geometry_connects_to_the_instance_port(self):
        graph = inspect.build(base_graph(), stage8_task("inspect_edge_defect"), CTX)
        graph["nodes"].append({"id": "ln", "type": "find_line", "params": {"roi": {"shape": "rect", "x": 100, "y": 150, "w": 600, "h": 100}}})
        graph["edges"].append({"source": "src", "source_handle": "image", "target": "ln", "target_handle": "image"})
        with_ref = inspect.update(graph, {"task_id": "item", "fields": {"reference": {"node_id": "ln", "port": "line", "type": "line"}}})
        self.assertEqual([e["source"] for e in edges_to(with_ref, "item", "defect:line")], ["ln"])
        read = next(t for t in inspect.read(with_ref)["tasks"] if t["task_id"] == "item")
        self.assertEqual(read["fields"]["reference"], {"node_id": "ln", "port": "line", "type": "line"})
        cleared = inspect.update(with_ref, {"task_id": "item", "fields": {"reference": None}})
        self.assertEqual(edges_to(cleared, "item", "defect:line"), [])

    def test_disabled_instance_reads_skipped_and_ids_never_collide(self):
        graph = inspect.build(base_graph(), diameter_task("d"), CTX)
        second = inspect.build(graph, diameter_task("d"), CTX)
        self.assertEqual({t["task_id"] for t in inspect.read(second)["tasks"]}, {"d", "d_2"})
        node(second, "d")["enabled"] = False
        task = next(t for t in inspect.read(second)["tasks"] if t["task_id"] == "d")
        self.assertTrue(task["disabled"])
        report = run_graph(second, annulus_image())
        reading = next(r for r in inspect.evidence(second, report) if r["task_id"] == "d")
        self.assertEqual((reading["verdict"], reading["node_id"]), ("skipped", "d"))
        self.assertEqual(next(r for r in inspect.evidence(second, report) if r["task_id"] == "d_2")["verdict"], "pass")


class LocatorTests(InstanceBase):
    def locate(self, graph: dict, threshold: float = 0.5, **fields) -> dict:
        _, tpl = patterned_scene(True)
        desc = fixed_images.store(tpl, "locator.png")
        return inspect.build(graph, {"kind": "locate_part", "task_id": "loc", "fields": {"template_images": [desc], "threshold": threshold, "ref_x": 0, "ref_y": 0, **fields}}, CTX)

    def test_locator_instance_teaches_pose_and_gates_downstream_instances(self):
        image, _ = patterned_scene(True)
        graph = self.locate(base_graph())
        inst = node(graph, "loc")
        self.assertEqual(inst["type"], "composite:locate_part_template")
        self.assertEqual(inst["params"]["align:use_angle"], False)
        task = inspect.read(graph)["tasks"][0]
        self.assertEqual((task["fields"]["method"], task["fields"]["allow_rotation"], task["fields"]["threshold"]), ("template", False, 0.5))
        # 定位是必要任務：彙總靠 formula 轉接器吃 find:count，控制線來自 find 的分支埠
        adapter = node(graph, "inspection_result_loc")
        self.assertEqual({(e["source_handle"], e["target_handle"]) for e in edges_to(graph, adapter["id"])}, {("find:count", "a"), ("find:found", "_flow"), ("find:not_found", "_flow")})
        report = run_graph(graph, image)
        self.assertEqual(report.nodes["loc"].branch, "find:found")
        reading = inspect.evidence(graph, report)[0]
        self.assertEqual((reading["verdict"], reading["detected"]), ("pass", True))
        taught = inspect.teach_pose(graph, "loc", report)
        self.assertAlmostEqual(node(taught, "loc")["params"]["align:ref_x"], 113, delta=0.2)
        self.assertAlmostEqual(node(taught, "loc")["params"]["align:ref_y"], 87, delta=0.2)
        with self.assertRaises(ValidationError):
            inspect.teach_pose(graph, "loc", run_graph(graph, np.full_like(image, 35)))
        # 下游實例接定位：兩條線（transform → _transform、found → _flow）
        downstream = inspect.build(taught, {"kind": "check_presence", "task_id": "p", "fields": {"method": "blob", "expected": "present", "roi": {"shape": "rect", "x": 90, "y": 70, "w": 46, "h": 34}, "locator": "loc"}}, CTX)
        self.assertEqual({(e["source"], e["source_handle"], e["target_handle"]) for e in edges_to(downstream, "p")} - {("src", "image", "det:image")}, {("loc", "align:transform", "_transform"), ("loc", "find:found", "_flow")})
        self.assertEqual(inspect.read(downstream)["tasks"][1]["fields"]["locator"], "loc")
        missing = run_graph(downstream, np.full_like(image, 35))
        self.assertEqual(missing.nodes["p"].status, "skipped")
        readings = {r["task_id"]: r for r in inspect.evidence(downstream, missing)}
        self.assertEqual(readings["loc"]["verdict"], "not_found")
        self.assertEqual(readings["p"]["verdict"], "locate_failed")
        self.assertEqual(missing.outputs["judge"], "NG")
        found = run_graph(downstream, image)
        self.assertEqual({r["task_id"]: r["verdict"] for r in inspect.evidence(downstream, found)}, {"loc": "pass", "p": "pass"})
        # 取消定位＝兩條線都拿掉；刪定位時下游擋下
        detached = inspect.update(downstream, {"task_id": "p", "fields": {"locator": ""}})
        self.assertEqual({e["target_handle"] for e in edges_to(detached, "p")}, {"det:image"})
        blocked = inspect.remove(downstream, "loc")
        self.assertFalse(blocked["removed"])
        self.assertEqual({d["target"] for d in blocked["dependencies"]}, {"p"})

    def test_rotation_switch_and_shape_method_change_on_a_locator_instance(self):
        graph = self.locate(base_graph())
        rotated = inspect.update(graph, {"task_id": "loc", "fields": {"allow_rotation": True, "angle_range": 20}})
        params = node(rotated, "loc")["params"]
        self.assertEqual((params["align:use_angle"], params["find:refine_rotation"], params["find:angle_range"]), (True, True, 20))
        task = inspect.read(rotated)["tasks"][0]
        self.assertEqual((task["fields"]["allow_rotation"], task["fields"]["angle_range"]), (True, 20))
        shaped = inspect.update(rotated, {"task_id": "loc", "fields": {"method": "shape", "model": "asset-1"}})
        self.assertEqual(node(shaped, "loc")["type"], "composite:locate_part_shape")
        task = inspect.read(shaped)["tasks"][0]
        self.assertEqual((task["fields"]["method"], task["fields"]["model"], task["fields"]["allow_rotation"]), ("shape", "asset-1", True))

    def test_legacy_task_can_follow_an_instance_locator_and_vice_versa(self):
        image, tpl = patterned_scene(True)
        desc = fixed_images.store(tpl, "locator.png")
        # 舊任務跟著定位實例
        graph = self.locate(base_graph())
        legacy = inspect.build(graph, {"kind": "check_presence", "task_id": "p", "fields": {"method": "blob", "expected": "present", "roi": {"shape": "rect", "x": 90, "y": 70, "w": 46, "h": 34}, "locator": "loc"}}, {})
        self.assertEqual({(e["source"], e["source_handle"], e["target_handle"]) for e in edges_to(legacy, "p_det")} - {("src", "image", "image")}, {("loc", "align:transform", "_transform"), ("loc", "find:found", "_flow")})
        self.assertEqual(next(t for t in inspect.read(legacy)["tasks"] if t["task_id"] == "p")["fields"]["locator"], "loc")
        report = run_graph(legacy, np.full_like(image, 35))
        self.assertEqual(next(r for r in inspect.evidence(legacy, report) if r["task_id"] == "p")["verdict"], "locate_failed")
        # 定位實例跟著舊的定位任務
        old_locator = inspect.build(base_graph(), {"kind": "locate_part", "task_id": "old", "fields": {"template_images": [desc], "threshold": 0.5}}, {})
        follower = inspect.build(old_locator, diameter_task("d", locator="old"), CTX)
        self.assertEqual({(e["source"], e["source_handle"], e["target_handle"]) for e in edges_to(follower, "d")} - {("src", "image", "find:image")}, {("old_align", "transform", "_transform"), ("old_find", "found", "_flow")})
        self.assertEqual(next(t for t in inspect.read(follower)["tasks"] if t["task_id"] == "d")["fields"]["locator"], "old")
        blocked = inspect.remove(follower, "old")
        self.assertEqual({d["target"] for d in blocked["dependencies"]}, {"d"})


class EntryPointTests(InstanceBase):
    def test_tasklist_apply_places_instances_by_default_and_setting_turns_it_off(self):
        graph = base_graph()
        draft = tasklist.parse("量外徑 300±2 px", graph=graph)[0]
        confirm = {draft["draft_id"]: {"confirmed": True, "fields": {"roi": {"value": {"shape": "annulus", "cx": 500, "cy": 350, "r_inner": 80, "r_outer": 170}}}}}
        out = tasklist.apply(graph, [draft], confirm)
        self.assertEqual(out["skipped"], [])
        self.assertEqual(out["tasks"][0]["source"], "composite")
        self.assertEqual(node(out["graph"], out["tasks"][0]["task_id"])["type"], "composite:measure_diameter")
        with override_settings(VISION={**__import__("django.conf").conf.settings.VISION, "INSPECT_COMPOSITE": "0"}):
            self.assertFalse(inspect_composite.default_enabled())
            legacy = tasklist.apply(graph, [draft], confirm)
        self.assertNotIn("source", legacy["tasks"][0])
        self.assertTrue(any(n["id"].endswith("_find") for n in legacy["graph"]["nodes"]))
        # 助手的修改與刪除對實例照樣有效
        target = out["tasks"][0]["task_id"]
        update = {"draft_id": "u", "kind": "measure_diameter", "op": "update", "task_id": target, "fields": {"upper_tol": tasklist.cell(.2, "confirmed", "user")}, "regions": []}
        changed = tasklist.apply(out["graph"], [update], {"u": {"confirmed": True}})
        self.assertEqual(changed["tasks"][0]["fields"]["upper_tol"], .2)
        removed = tasklist.apply(changed["graph"], [{**update, "op": "remove", "fields": {}}], {"u": {"confirmed": True}})
        self.assertEqual(removed["tasks"], [])

    def test_api_build_defaults_to_instances_and_the_rest_of_the_endpoints_accept_them(self):
        user = User.objects.create_superuser("p4", "", "password")
        auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(user)}"}
        post = lambda path, body: self.client.post(path, data=json.dumps(body), content_type="application/json", **auth)  # noqa: E731
        built = post("/api/vision/inspect/build", {"graph": base_graph(), "task": diameter_task("d")})
        self.assertEqual(built.status_code, 200, built.content)
        graph = built.json()["graph"]
        self.assertEqual(node(graph, "d")["type"], "composite:measure_diameter")
        read = post("/api/vision/inspect/read", {"graph": graph}).json()
        self.assertEqual((read["tasks"][0]["task_id"], read["tasks"][0]["source"]), ("d", "composite"))
        updated = post("/api/vision/inspect/update", {"graph": graph, "task": {"task_id": "d", "fields": {"upper_tol": 4}}})
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(node(updated.json()["graph"], "d")["params"]["tol:upper_tol"], 4)
        report = run_graph(graph, annulus_image()).to_dict()
        evidence = post("/api/vision/inspect/evidence", {"graph": graph, "report": report}).json()["items"]
        self.assertEqual((evidence[0]["verdict"], evidence[0]["node_id"]), ("pass", "d"))
        legacy = post("/api/vision/inspect/build", {"graph": base_graph(), "task": diameter_task("d"), "ctx": {"composite": False}}).json()["graph"]
        self.assertTrue(any(n["id"] == "d_find" for n in legacy["nodes"]))
        removed = post("/api/vision/inspect/remove", {"graph": graph, "task_id": "d"}).json()
        self.assertTrue(removed["removed"])
