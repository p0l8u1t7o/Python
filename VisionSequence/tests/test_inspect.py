"""檢測任務翻譯器。"""

from __future__ import annotations

import copy
import json
from unittest.mock import patch

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
    def test_advanced_position_and_unmanaged_parameter_remain_editable(self):
        graph = inspect.build(base_graph(), diameter_task("d"))
        graph["nodes"][1]["position"] = {"x": 999, "y": -100}
        graph["nodes"][1]["params"]["smoothing"] = 7
        self.assertFalse(inspect.read(graph)["tasks"][0]["custom"])
        updated = inspect.update(graph, {"task_id": "d", "fields": {"upper_tol": 5}})
        expected = copy.deepcopy(graph)
        next(n for n in expected["nodes"] if n["id"] == "d_tol")["params"]["upper_tol"] = 5
        self.assertEqual(updated, expected)

    def test_missing_internal_edge_has_structured_reason_and_update_is_blocked(self):
        from apps.core.errors import ValidationError

        graph = inspect.build(base_graph(), diameter_task("d"))
        graph["edges"] = [e for e in graph["edges"] if not (e["source"] == "d_find" and e["target"] == "d_tol")]
        task = inspect.read(graph)["tasks"][0]
        self.assertEqual(task["reasons"], [{"code": "managed_edge_missing", "role": "tol", "node_id": "d_tol", "detail": "Missing d_find.diameter -> d_tol.value"}])
        before = copy.deepcopy(graph)
        with self.assertRaises(ValidationError) as caught:
            inspect.update(graph, {"task_id": "d", "fields": {"upper_tol": 9}})
        self.assertEqual(caught.exception.code, "custom_task")
        self.assertEqual(graph, before)

    def test_inserted_blur_is_unexpected_node_and_extra_edge_is_reported(self):
        graph = inspect.build(base_graph(), diameter_task("d"))
        graph["nodes"].append({"id": "extra", "type": "blur", "params": {}, "meta": {"inspect": {"task_id": "d", "role": "extra", "kind": "measure_diameter", "schema_version": 1, "required": True}}})
        graph["edges"].append(edge("d_find", "extra", "_image", "image"))
        reasons = inspect.read(graph)["tasks"][0]["reasons"]
        self.assertIn({"code": "unexpected_node", "role": "extra", "node_id": "extra", "detail": "The task contains an extra step"}, reasons)
        self.assertIn("managed_edge_changed", {r["code"] for r in reasons})

    def test_public_output_consumers_and_tolerance_diff_preserve_advanced_graph(self):
        graph = inspect.build(base_graph(), diameter_task("d"))
        for node_id, tool_key, port in (("d_formula", "formula", "a"), ("text", "format_text", "a"), ("plc", "write_modbus", "values")):
            graph["nodes"].append({"id": node_id, "type": tool_key, "label": "External consumer", "params": {}})
            graph["edges"].append(edge("d_find", node_id, "diameter", port))
        validate_graph(graph)
        self.assertFalse(inspect.read(graph)["tasks"][0]["custom"])
        updated = inspect.update(graph, {"task_id": "d", "fields": {"upper_tol": 5}})
        diff = graphdiff.diff(graph, updated)
        self.assertEqual(diff["params"], [{"node": "d_tol", "type": "tolerance_judge", "param": "upper_tol", "before": 2, "after": 5}])
        self.assertEqual(updated["edges"], graph["edges"])
        expected = copy.deepcopy(graph)
        next(n for n in expected["nodes"] if n["id"] == "d_tol")["params"]["upper_tol"] = 5
        self.assertEqual(updated, expected)
        blocked = inspect.remove(graph, "d")
        self.assertFalse(blocked["removed"])
        self.assertEqual(blocked["graph"], graph)
        self.assertEqual({(d["target"], d["title"], d["target_handle"]) for d in blocked["dependencies"]}, {("d_formula", "External consumer", "a"), ("text", "External consumer", "a"), ("plc", "External consumer", "values")})

    def test_unknown_schema_and_missing_or_changed_roles_are_custom(self):
        original = inspect.build(base_graph(), diameter_task("d"))
        for version in (99, "future", None):
            graph = copy.deepcopy(original)
            for node in graph["nodes"]:
                if (inspect.inspect_marker(node) or {}).get("task_id") == "d":
                    node["meta"]["inspect"]["schema_version"] = version
            task = inspect.read(graph)["tasks"][0]
            self.assertTrue(task["custom"])
            self.assertEqual(task["reasons"][0]["code"], "schema_version_unknown")
        for mutation, code in (("missing", "role_missing"), ("tool", "tool_changed"), ("kind", "schema_version_unknown")):
            graph = copy.deepcopy(original)
            find = next(n for n in graph["nodes"] if n["id"] == "d_find")
            if mutation == "missing":
                graph["nodes"].remove(find)
            elif mutation == "tool":
                find["type"] = "blob"
            else:
                find["meta"]["inspect"]["kind"] = "future_task"
            reasons = inspect.read(graph)["tasks"][0]["reasons"]
            self.assertIn(code, {r["code"] for r in reasons})
            for reason in reasons:
                self.assertEqual(set(reason), {"code", "role", "node_id", "detail"})
                self.assertIn(reason["code"], inspect.CUSTOM_REASON_CODES)

    def test_public_input_missing_wrong_source_and_undeclared_port_are_custom(self):
        original = inspect.build(base_graph(), diameter_task("d"))
        for mutation in ("missing", "wrong_source", "undeclared"):
            graph = copy.deepcopy(original)
            graph["edges"] = [e for e in graph["edges"] if e["source"] != "src"]
            if mutation == "wrong_source":
                graph["nodes"].append({"id": "number", "type": "formula", "params": {}})
                graph["edges"].append(edge("number", "d_find", "value", "image"))
            elif mutation == "undeclared":
                graph["edges"].append(edge("src", "d_tol", "image", "value"))
            self.assertIn("public_input_changed", {r["code"] for r in inspect.read(graph)["tasks"][0]["reasons"]})

    def test_renamed_nodes_are_matched_by_role_and_preserved_by_update(self):
        graph = inspect.build(base_graph(), diameter_task("d"))
        renamed = {"d_find": "circle", "d_tol": "judge"}
        for node in graph["nodes"]:
            node["id"] = renamed.get(node["id"], node["id"])
        for link in graph["edges"]:
            for key in ("source", "target"):
                link[key] = renamed.get(link[key], link[key])
        self.assertFalse(inspect.read(graph)["tasks"][0]["custom"])
        updated = inspect.update(graph, {"task_id": "d", "fields": {"calibration": "scale"}})
        self.assertEqual([n["id"] for n in updated["nodes"]], [n["id"] for n in graph["nodes"]])
        self.assertFalse(inspect.read(updated)["tasks"][0]["custom"])

    def test_disabled_task_and_missing_report_cannot_reuse_passing_evidence(self):
        graph = inspect.build(base_graph(), diameter_task("d"))
        report = run_graph(graph, annulus_image())
        self.assertEqual(inspect.evidence(graph, report)[0]["verdict"], "pass")
        for node_id in ("d_find", "d_tol"):
            disabled = copy.deepcopy(graph)
            next(n for n in disabled["nodes"] if n["id"] == node_id)["enabled"] = False
            self.assertTrue(inspect.read(disabled)["tasks"][0]["disabled"])
            for result in (report, run_graph(disabled, annulus_image())):
                reading = inspect.evidence(disabled, result)[0]
                self.assertEqual(reading["verdict"], "skipped")
                self.assertEqual(reading["node_id"], node_id)
                self.assertIn("disabled", reading["reason"])
                self.assertIsNone(reading["value"])
        self.assertEqual(inspect.evidence(graph, {"nodes": {}})[0]["verdict"], "skipped")

    def test_only_actual_locator_branches_explain_skipped_renamed_steps(self):
        graph = inspect.build(base_graph(), {"kind": "locate_part", "task_id": "loc", "fields": {"template_images": []}})
        graph = inspect.build(graph, diameter_task("d", locator="loc"))
        for node in graph["nodes"]:
            if node["id"] == "d_find":
                node["id"] = "circle"
        for link in graph["edges"]:
            for key in ("source", "target"):
                if link[key] == "d_find":
                    link[key] = "circle"
        rows = {n["id"]: {"status": "ok", "outputs": {}} for n in graph["nodes"]}
        rows["loc_find"] = {"status": "ng", "branch": "not_found"}
        rows["circle"] = rows["d_tol"] = {"status": "skipped"}
        reading = next(r for r in inspect.evidence(graph, {"nodes": rows}) if r["task_id"] == "d")
        self.assertEqual(reading["verdict"], "locate_failed")
        next(n for n in graph["nodes"] if n["id"] == "loc_find")["meta"]["inspect"]["kind"] = "another_task"
        reading = next(r for r in inspect.evidence(graph, {"nodes": rows}) if r["task_id"] == "d")
        self.assertEqual(reading["verdict"], "skipped")

    def test_remove_without_dependents_keeps_source_locator_other_task_and_loose_nodes(self):
        graph = inspect.build(base_graph(), {"kind": "locate_part", "task_id": "loc", "fields": {"template_images": []}})
        graph = inspect.build(graph, diameter_task("d", locator="loc"))
        graph = inspect.build(graph, diameter_task("other"))
        graph["nodes"].append({"id": "note", "type": "note", "params": {}})
        self.assertIn("note", {n["id"] for n in inspect.read(graph)["loose"]})
        result = inspect.remove(graph, "d")
        self.assertTrue(result["removed"])
        self.assertEqual(result["dependencies"], [])
        expected = copy.deepcopy(graph)
        expected["nodes"] = [n for n in expected["nodes"] if n["id"] not in {"d_find", "d_tol"}]
        expected["edges"] = [e for e in expected["edges"] if e["source"] not in {"d_find", "d_tol"} and e["target"] not in {"d_find", "d_tol"}]
        next(n for n in expected["nodes"] if n["id"] == "inspection_summary")["params"]["expected_count"] = 1
        self.assertEqual(result["graph"], expected)

    def test_calibration_rewire_preserves_published_alias_and_advanced_parameters(self):
        graph = inspect.build(base_graph(), diameter_task("d"))
        find = next(n for n in graph["nodes"] if n["id"] == "d_find")
        find["params"]["_publish"] = {"diameter": "measured_size", "cx": "centre_x"}
        find["params"]["smoothing"] = 7
        find["label"] = "Outer edge"
        updated = inspect.update(graph, {"task_id": "d", "fields": {"calibration": "scale"}})
        actual = next(n for n in updated["nodes"] if n["id"] == "d_find")
        self.assertEqual(actual["params"]["_publish"], {"diameter_world": "measured_size", "cx": "centre_x"})
        self.assertEqual(actual["params"]["smoothing"], 7)
        self.assertEqual(actual["label"], "Outer edge")

    def test_calibration_update_uses_world_measurements_in_the_engine(self):
        task = diameter_task("d", nominal=30, lower=-0.02, upper=0.02)
        graph = inspect.build(base_graph(), task)
        updated = inspect.update(graph, {"task_id": "d", "fields": {"calibration": "scale"}})
        mapping = {"unit": "mm", "world": {"matrix": [[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], "mm_per_px": 0.1}}
        with patch("apps.vision.calib.from_asset", return_value=mapping):
            result = run_graph(updated, annulus_image())
            self.assertEqual(result.status, "ok")
            self.assertAlmostEqual(result.nodes["d_find"].outputs["diameter_world"], 30, delta=0.008)
            reading = inspect.evidence(updated, result)[0]
            self.assertEqual(reading["unit"], "mm")
            self.assertAlmostEqual(reading["value"], 30, delta=0.008)
            round_graph = inspect.update(updated, {"task_id": "d", "fields": {"mode": "roundness", "upper_tol": 0.05}})
            round_result = run_graph(round_graph, annulus_image())
            self.assertEqual(round_result.status, "ok", {key: row.message for key, row in round_result.nodes.items()})
            self.assertEqual(round_result.nodes["d_scale"].outputs["scale"], 0.1)
            self.assertLess(inspect.evidence(round_graph, round_result)[0]["value"], 0.05)
        restored = inspect.update(updated, {"task_id": "d", "fields": {"calibration": ""}})
        self.assertEqual(next(t for t in inspect.read(restored)["tasks"] if t["task_id"] == "d")["fields"]["unit"], "px")

    def test_update_rebuild_fields_match_direct_build_and_preserve_external_edges(self):
        task = diameter_task("d")
        original = inspect.build(base_graph(), task)
        original = inspect.build(original, diameter_task("other"))
        original["nodes"].append({"id": "external", "type": "formula", "params": {"expression": "a"}})
        external = edge("d_tol", "external", "in_spec", "a")
        original["edges"].append(external)
        original["nodes"][1]["meta"]["editor_note"] = "preserve"
        snapshot = copy.deepcopy(original)
        for changes in ({"calibration": "calibration-id", "unit": "mm"}, {"mode": "roundness"}, {"mode": "roundness", "unit": "mm", "calibration": "calibration-id"}):
            with self.subTest(changes=changes):
                updated = inspect.update(original, {"task_id": "d", "fields": changes})
                direct = inspect.build(base_graph(), {**task, "fields": {**task["fields"], **changes}})
                for role in ("find", "tol"):
                    actual = next(n for n in updated["nodes"] if n["id"] == f"d_{role}")
                    expected = next(n for n in direct["nodes"] if n["id"] == f"d_{role}")
                    self.assertEqual(actual["type"], expected["type"])
                    self.assertEqual(actual["params"], expected["params"])
                def internal(g):
                    return [e for e in g["edges"] if e["source"].startswith("d_") and e["target"].startswith("d_")]
                self.assertEqual(internal(updated), internal(direct))
                self.assertIn(external, updated["edges"])
                self.assertEqual(updated["nodes"][1]["meta"], original["nodes"][1]["meta"])
                self.assertEqual([n for n in updated["nodes"] if n["id"].startswith("other_")], [n for n in original["nodes"] if n["id"].startswith("other_")])
                readback = next(t for t in inspect.read(updated)["tasks"] if t["task_id"] == "d")
                self.assertFalse(readback["custom"])
                self.assertEqual(readback["fields"]["result_name"], "d")
                restored = inspect.update(updated, {"task_id": "d", "fields": {"mode": "check", "unit": "px", "calibration": ""}})
                self.assertEqual(next(n for n in restored["nodes"] if n["id"] == "d_tol")["params"], next(n for n in original["nodes"] if n["id"] == "d_tol")["params"])
        self.assertEqual(original, snapshot)

    def test_update_rotation_matches_build_and_keeps_downstream_locator_edges(self):
        task = {"kind": "locate_part", "task_id": "loc", "fields": {"template_images": [], "ref_x": 10, "ref_y": 20}}
        original = inspect.build(base_graph(), task)
        original = inspect.build(original, diameter_task("d", locator="loc"))
        for enabled in (True, False):
            changes = {"allow_rotation": enabled, "angle_range": 30}
            updated = inspect.update(original, {"task_id": "loc", "fields": changes})
            direct = inspect.build(base_graph(), {**task, "fields": {**task["fields"], **changes}})
            self.assertEqual([n["params"] for n in updated["nodes"] if n["id"].startswith("loc_")], [n["params"] for n in direct["nodes"] if n["id"].startswith("loc_")])
            self.assertEqual(updated["edges"], original["edges"])
            self.assertEqual(next(t for t in inspect.read(updated)["tasks"] if t["task_id"] == "loc")["fields"]["allow_rotation"], enabled)
            original = updated

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
        self.assertEqual(task["reasons"][0]["code"], "managed_edge_missing")
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
