"""檢測任務翻譯器。"""

from __future__ import annotations

import copy
import json

import cv2
import numpy as np
from django.test import SimpleTestCase, TransactionTestCase

from apps.vision import engine, fixed_images, graphdiff, inspect
from apps.vision.graph import compile_graph, validate_graph


def edge(source: str, target: str, sh: str = "", th: str = "") -> dict[str, str]:
    return {"source": source, "target": target, "source_handle": sh, "target_handle": th}


def base_graph() -> dict:
    return {"nodes": [{"id": "src", "type": "image_source", "params": {"mode": "input"}}], "edges": []}


def annulus_image(h: int = 701, w: int = 1001, cx: float = 500, cy: float = 350, r_inner: float = 100, r_outer: float = 150) -> np.ndarray:
    y, x = np.ogrid[:h, :w]
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    cover = np.clip(dist - (r_inner - 0.5), 0, 1) * np.clip((r_outer + 0.5) - dist, 0, 1)
    return (cover * 220).astype(np.uint8)


def patterned_scene(present: bool = True) -> tuple[np.ndarray, np.ndarray]:
    image = np.full((180, 240), 35, np.uint8)
    tpl = np.full((34, 46), 210, np.uint8)
    cv2.circle(tpl, (14, 12), 6, 80, -1)
    cv2.line(tpl, (0, 33), (45, 0), 130, 2)
    if present:
        image[70:104, 90:136] = tpl
    return image, tpl


def run_graph(graph: dict, image: np.ndarray) -> engine.RunReport:
    compiled = compile_graph(validate_graph(copy.deepcopy(graph)))
    return engine.execute(
        compiled,
        flow_id=1,
        flow_version=1,
        trigger="test",
        grab=lambda _sid: None,
        asset_path=lambda _aid: None,
        preview=True,
        input_image=image,
    )


def diameter_task(task_id: str = "diam", *, edge_name: str = "outer", nominal: float = 300, lower: float = -2, upper: float = 2, locator: str = "") -> dict:
    return {
        "kind": "measure_diameter",
        "task_id": task_id,
        "fields": {
            "roi": {"shape": "annulus", "cx": 500, "cy": 350, "r_inner": 80, "r_outer": 170},
            "edge": edge_name,
            "polarity": "any",
            "nominal": nominal,
            "upper_tol": upper,
            "lower_tol": lower,
            "unit": "px",
            "result_name": task_id,
            "required": True,
            "locator": locator,
            "num_rays": 144,
        },
    }


class InspectTranslatorTests(SimpleTestCase):
    def test_build_validate_and_engine_measure_inner_and_outer_on_odd_image(self):
        image = annulus_image()
        inner_graph = inspect.build(base_graph(), diameter_task("inner", edge_name="inner", nominal=200), {})
        outer_graph = inspect.build(base_graph(), diameter_task("outer", edge_name="outer", nominal=300), {})
        inner = run_graph(inner_graph, image)
        outer = run_graph(outer_graph, image)
        self.assertEqual(inner.status, "ok")
        self.assertEqual(outer.status, "ok")
        self.assertAlmostEqual(inner.nodes["inner_find"].outputs["diameter"], 200, delta=0.08)
        self.assertAlmostEqual(outer.nodes["outer_find"].outputs["diameter"], 300, delta=0.08)
        self.assertEqual(inner.outputs["judge"], "OK")

    def test_tolerance_boundaries_and_not_found_evidence(self):
        image = annulus_image()
        for nominal, lower, upper, status in [(300.0, 0.0, 0.1, "ng"), (300.0, -0.1, 0.1, "ok"), (299.973, -0.2, 0.0, "ok"), (302.2, -2, 0, "ng")]:
            graph = inspect.build(base_graph(), diameter_task("d", nominal=nominal, lower=lower, upper=upper), {})
            report = run_graph(graph, image)
            self.assertEqual(report.status, status, (nominal, report.nodes["d_tol"].message))
        graph = inspect.build(base_graph(), diameter_task("dark", nominal=300), {})
        report = run_graph(graph, np.zeros((701, 1001), np.uint8))
        reading = inspect.evidence(graph, report)[0]
        self.assertEqual(reading["verdict"], "not_found")
        self.assertIsNone(reading["value"])

    def test_read_update_remove_and_custom_detection(self):
        graph = inspect.build(base_graph(), diameter_task("d", nominal=300), {})
        before = copy.deepcopy(graph)
        read = inspect.read(graph)
        self.assertEqual(read["tasks"][0]["fields"]["edge"], "outer")
        updated = inspect.update(graph, {"task_id": "d", "fields": {"upper_tol": 3}})
        diff = graphdiff.diff(graph, updated)
        self.assertEqual(diff["edges_added"], 0)
        self.assertEqual(diff["edges_removed"], 0)
        self.assertEqual(diff["params"], [{"node": "d_tol", "type": "tolerance_judge", "param": "upper_tol", "before": 2, "after": 3}])
        self.assertEqual(graph, before)
        broken = copy.deepcopy(graph)
        broken["edges"] = [e for e in broken["edges"] if not (e["source"] == "d_find" and e["target"] == "d_tol")]
        task = inspect.read(broken)["tasks"][0]
        self.assertTrue(task["custom"])
        self.assertEqual(task["reasons"][0]["code"], "managed_edge_changed")
        with_formula = copy.deepcopy(graph)
        with_formula["nodes"].append({"id": "f", "type": "formula", "params": {"expression": "a"}})
        with_formula["edges"].append(edge("d_tol", "f", "in_spec", "a"))
        self.assertFalse(inspect.read(with_formula)["tasks"][0]["custom"])

    def test_template_instantiation_rewrites_task_ids(self):
        from apps.vision.api_more import instantiate as instantiate_template

        graph = inspect.build(base_graph(), diameter_task("d"), {})
        first = instantiate_template(graph, source_id=None, prefix="a_")
        second = instantiate_template(graph, source_id=None, prefix="b_")
        combined = {"nodes": first["nodes"] + second["nodes"], "edges": first["edges"] + second["edges"]}
        validate_graph(combined)
        self.assertEqual({t["task_id"] for t in inspect.read(combined)["tasks"]}, {"a_d", "b_d"})

    def test_locator_dependency_blocks_downstream_and_summary_rejects(self):
        present, tpl = patterned_scene(True)
        desc = fixed_images.store(tpl, "locator.png")
        graph = inspect.build(base_graph(), {
            "kind": "locate_part",
            "task_id": "loc",
            "fields": {"template_images": [desc], "threshold": 0.95, "ref_x": 113, "ref_y": 87, "ref_angle": 0},
        }, {})
        graph = inspect.build(graph, diameter_task("d1", locator="loc"), {})
        report = run_graph(graph, np.full_like(present, 35))
        self.assertEqual(report.nodes["loc_find"].branch, "not_found")
        self.assertEqual(report.nodes["d1_find"].status, "skipped")
        self.assertEqual(report.nodes["inspection_summary"].status, "ng")
        self.assertEqual(report.outputs["judge"], "NG")
        reading = next(r for r in inspect.evidence(graph, report) if r["task_id"] == "d1")
        self.assertEqual(reading["verdict"], "locate_failed")

    def test_remove_locator_reports_three_dependent_tasks(self):
        _img, tpl = patterned_scene(True)
        desc = fixed_images.store(tpl, "locator.png")
        graph = inspect.build(base_graph(), {"kind": "locate_part", "task_id": "loc", "fields": {"template_images": [desc], "ref_x": 113, "ref_y": 87}}, {})
        for i in range(3):
            graph = inspect.build(graph, diameter_task(f"d{i}", locator="loc"), {})
        before = json.loads(json.dumps(graph))
        result = inspect.remove(graph, "loc")
        self.assertFalse(result["removed"])
        self.assertEqual({d["task_id"] for d in result["dependencies"]}, {"d0", "d1", "d2"})
        self.assertEqual(result["graph"], before)

    def test_teach_pose_writes_locator_reference(self):
        image, tpl = patterned_scene(True)
        desc = fixed_images.store(tpl, "locator.png")
        graph = inspect.build(base_graph(), {"kind": "locate_part", "task_id": "loc", "fields": {"template_images": [desc], "threshold": 0.5, "ref_x": 0, "ref_y": 0}}, {})
        report = run_graph(graph, image)
        taught = inspect.teach_pose(graph, "loc", report)
        align = next(n for n in taught["nodes"] if n["id"] == "loc_align")
        self.assertAlmostEqual(align["params"]["ref_x"], 113, delta=0.2)
        self.assertAlmostEqual(align["params"]["ref_y"], 87, delta=0.2)


class InspectApiTests(TransactionTestCase):
    def test_stateless_endpoints_return_graphs_and_errors(self):
        payload = {"graph": base_graph(), "task": diameter_task("d")}
        built = self.client.post("/api/vision/inspect/build", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(built.status_code, 200, built.content)
        graph = built.json()["graph"]
        read = self.client.post("/api/vision/inspect/read", data=json.dumps({"graph": graph}), content_type="application/json")
        self.assertEqual(read.status_code, 200, read.content)
        self.assertEqual(read.json()["tasks"][0]["task_id"], "d")
        updated = self.client.post(
            "/api/vision/inspect/update",
            data=json.dumps({"graph": graph, "task": {"task_id": "d", "fields": {"upper_tol": 4}}}),
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        removed = self.client.post("/api/vision/inspect/remove", data=json.dumps({"graph": graph, "task_id": "d"}), content_type="application/json")
        self.assertEqual(removed.status_code, 200, removed.content)
        self.assertTrue(removed.json()["removed"])
        bad = self.client.post("/api/vision/inspect/build", data=json.dumps({"graph": {"nodes": [], "edges": []}, "task": {"kind": "nope"}}), content_type="application/json")
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["error"]["code"], "unknown_task_kind")
