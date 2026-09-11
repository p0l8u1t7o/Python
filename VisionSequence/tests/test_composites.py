"""複合工具（PRODUCT-DIRECTION v2 §3）：登錄表、展平、摺疊、循環與深度、API 權限與影響清單、匯出匯入。"""

from __future__ import annotations

import copy
import json

import numpy as np
from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import AuthToken, UserPref
from apps.core.errors import Conflict, NotFound, ValidationError
from apps.vision import composites, engine, serialize
from apps.vision.graph import compile_graph, restrict_to, validate_graph
from apps.vision.models import CompositeTool, Flow
from apps.vision.tools import base as tools
from apps.vision.tools import register_builtins


def n(nid: str, ntype: str, **params):
    return {"id": nid, "type": ntype, "params": params}


def e(s: str, t: str, sh: str = "", th: str = ""):
    return {"source": s, "target": t, "source_handle": sh, "target_handle": th}


def image() -> np.ndarray:
    img = np.zeros((60, 80, 3), np.uint8)
    img[10:30, 10:30] = 255
    img[35:50, 50:70] = 255
    return img


def run_graph(graph: dict, **kw) -> engine.RunReport:
    compiled = compile_graph(validate_graph(graph))
    if kw.pop("until", None):
        compiled = restrict_to(compiled, kw.pop("until_node"))
    return engine.execute(compiled, flow_id=1, flow_version=1, trigger="test", grab=lambda _sid: image(), asset_path=lambda _aid: None, **kw)


#: 「灰階 → 門檻 → blob」封裝成一個工具：對外影像輸入、對外數量／找到／遮罩輸出、對外門檻參數
TOOL_GRAPH = {
    "nodes": [n("gray", "grayscale"), n("thr", "threshold", method="fixed", threshold=128), n("blob", "blob", threshold_method="none", min_area=10)],
    "edges": [e("gray", "thr", "image", "image"), e("thr", "blob", "image", "image")],
}
TOOL_INTERFACE = {
    "inputs": [{"key": "gray:image", "exposed": True, "alias": "Picture", "order": 0}],
    "outputs": [{"key": "blob:count", "exposed": True, "order": 0}, {"key": "blob:found", "exposed": True, "order": 1}, {"key": "blob:mask", "exposed": True, "order": 2},
                {"key": "blob:largest_area", "exposed": False}],
    "params": [{"key": "thr:threshold", "alias": "Level", "teach": True, "order": 0}, {"key": "blob:min_area", "default": 5}],
}


class CompositeBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin", is_staff=True)
        cls.operator = User.objects.create_user("operator")
        UserPref.objects.create(user=cls.operator, role="operator")
        cls.tool = composites.create(cls.admin, {"key": "count_blobs", "label": "Count blobs", "category": "detect", "icon": "Boxes",
                                                 "graph": TOOL_GRAPH, "interface": TOOL_INTERFACE})

    def setUp(self):
        composites.invalidate()


class RegistryTests(CompositeBase):
    def test_registry_builds_a_tool_type_from_the_interface(self):
        ct = tools.get("composite:count_blobs")
        self.assertEqual(ct.source, "composite")
        self.assertEqual([p.key for p in ct.inputs], ["gray:image"])
        self.assertEqual(ct.inputs[0].label, "Picture")
        self.assertEqual(ct.inputs[0].type, "image")
        self.assertTrue(ct.inputs[0].required)
        self.assertEqual([p.key for p in ct.outputs], ["blob:count", "blob:found", "blob:mask"])
        self.assertEqual([p.type for p in ct.outputs], ["number", "flow", "image"])
        self.assertEqual([p.key for p in ct.params], ["thr:threshold", "blob:min_area"])
        self.assertEqual(ct.params[0].label, "Level")
        self.assertTrue(ct.params[0].teach)
        self.assertEqual(ct.params[0].default, 128)  # 沒覆寫預設值 → 內部節點填的值
        self.assertEqual(ct.params[1].default, 5)
        self.assertTrue(tools.has("composite:count_blobs"))
        self.assertFalse(tools.has("composite:nope"))
        with self.assertRaises(tools.UnknownToolType):
            tools.get("composite:nope")

    def test_catalogue_lists_the_composite_with_its_source_and_only_the_pass_through_implicit_output(self):
        entry = next(item for item in tools.catalogue() if item["key"] == "composite:count_blobs")
        self.assertEqual(entry["source"], "composite")
        self.assertEqual(entry["composite"]["tool_key"], "count_blobs")
        self.assertEqual(entry["composite"]["flow_id"], self.tool.flow_id)
        self.assertIn("_image", [p["key"] for p in entry["outputs"]])
        self.assertNotIn("_overlays", [p["key"] for p in entry["outputs"]])
        self.assertNotIn("_image", [p["key"] for p in entry["inputs"]])
        self.assertTrue(next(p for p in entry["outputs"] if p["key"] == "blob:found")["primary"])

    def test_tool_flow_is_hidden_from_flow_lists(self):
        flow = self.tool.flow
        self.assertEqual(flow.kind, "tool")
        self.assertFalse(flow.is_enabled)
        token = AuthToken.issue(self.admin)
        listing = self.client.get("/api/vision/flows", HTTP_AUTHORIZATION=f"Bearer {token}").json()
        self.assertNotIn(flow.id, [f["id"] for f in listing["items"]])
        direct = self.client.get(f"/api/vision/flows/{flow.id}", HTTP_AUTHORIZATION=f"Bearer {token}").json()
        self.assertEqual(direct["kind"], "tool")
        self.assertEqual(direct["composite_tool"]["key"], "count_blobs")
        r = self.client.delete(f"/api/vision/flows/{flow.id}", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 409, r.content)


class FlattenTests(CompositeBase):
    def flow_graph(self, **instance_params):
        return {
            "nodes": [n("src", "image_source", mode="source", source_id=1), {**n("count", "composite:count_blobs", **instance_params), "interface": {"outputs": [{"key": "blob:count", "alias": "holes"}]}},
                      n("out", "output", name="ok")],
            "edges": [e("src", "count", "image", "gray:image"), e("count", "out", "blob:found", "_flow"), e("count", "out", "blob:count", "value")],
        }

    def test_flatten_prefixes_ids_rewires_edges_binds_params_and_moves_aliases(self):
        graph = validate_graph(self.flow_graph(**{"thr:threshold": 200}))
        flat, instances = composites.flatten(graph)
        ids = [node["id"] for node in flat["nodes"]]
        self.assertEqual(ids, ["src", "count.gray", "count.thr", "count.blob", "out"])
        thr = next(node for node in flat["nodes"] if node["id"] == "count.thr")
        self.assertEqual(thr["params"]["threshold"], 200)
        blob = next(node for node in flat["nodes"] if node["id"] == "count.blob")
        self.assertEqual(blob["params"]["min_area"], 10)  # 沒填的對外參數不動內部值
        self.assertEqual(tools.output_aliases(blob), {"count": "holes"})
        edges = {(edge["source"], edge.get("source_handle"), edge["target"], edge.get("target_handle")) for edge in flat["edges"]}
        self.assertIn(("src", "image", "count.gray", "image"), edges)
        self.assertIn(("count.blob", "found", "out", "_flow"), edges)
        self.assertIn(("count.blob", "count", "out", "value"), edges)
        self.assertIn(("count.gray", "image", "count.thr", "image"), edges)
        self.assertEqual(instances["count"]["tool"], "count_blobs")
        self.assertEqual(instances["count"]["inner"], ["count.gray", "count.thr", "count.blob"])
        self.assertEqual(instances["count"]["outputs"]["blob:count"], ("count.blob", "count", "number"))

    def test_image_pass_through_feeds_the_downstream_step_with_the_instance_input(self):
        graph = self.flow_graph()
        graph["nodes"].append(n("blur", "blur", ksize=3))
        graph["edges"].append(e("count", "blur", "_image", "image"))
        flat, _ = composites.flatten(validate_graph(graph))
        edges = {(edge["source"], edge.get("source_handle"), edge["target"], edge.get("target_handle")) for edge in flat["edges"]}
        self.assertIn(("src", "image", "blur", "image"), edges)
        report = run_graph(graph)
        self.assertEqual((report.nodes["blur"].status, report.nodes["count"].status), ("ok", "ok"))
        # 沒接影像的實例：直通邊沒有東西可傳，展平時略過而不是炸
        bare = {"nodes": [n("count", "composite:count_blobs"), n("blur", "blur", ksize=3)], "edges": [e("count", "blur", "_image", "image")]}
        flat, _ = composites.flatten(validate_graph(bare))
        self.assertFalse(any(edge["target"] == "blur" for edge in flat["edges"]))

    def test_engine_runs_the_flattened_graph_and_folds_the_instance_report(self):
        report = run_graph(self.flow_graph())
        self.assertEqual(report.status, "ok", report.error)
        self.assertEqual(report.outputs["holes"], 2)
        inst = report.nodes["count"]
        self.assertEqual(inst.status, "ok")
        self.assertEqual(inst.outputs["blob:count"], 2)
        self.assertEqual(inst.branch, "blob:found")
        self.assertIn("blob:mask", inst.outputs)
        self.assertEqual(inst.detail["composite"], "count_blobs")
        self.assertEqual(inst.detail["steps"], ["count.gray", "count.thr", "count.blob"])
        self.assertGreater(inst.duration_ms, 0)
        self.assertIn("count.blob", report.nodes)
        self.assertEqual(report.nodes["out"].status, "ok")

    def test_instance_param_changes_the_result(self):
        # 門檻拉到 255 以上：白色方塊全部消失，數量 0、走 not_found，下游的 output 被跳過
        report = run_graph(self.flow_graph(**{"thr:threshold": 255}))
        self.assertEqual(report.nodes["count"].outputs["blob:count"], 0)
        self.assertEqual(report.nodes["count"].branch, None)
        self.assertEqual(report.nodes["out"].status, "skipped")

    def test_disabled_instance_skips_every_inner_step(self):
        graph = self.flow_graph()
        graph["nodes"][1]["enabled"] = False
        report = run_graph(graph)
        self.assertEqual(report.nodes["count"].status, "skipped")
        self.assertEqual(report.nodes["count"].message, "disabled")
        # 內部單進單出的節點會直通（引擎既有行為），但實例算被跳過，下游拿不到數量也跳過
        self.assertEqual(report.nodes["out"].status, "skipped")

    def test_until_node_on_an_instance_runs_its_inner_steps_only(self):
        report = run_graph(self.flow_graph(), until=True, until_node="count")
        self.assertEqual(report.nodes["count"].status, "ok")
        self.assertNotIn("out", report.nodes)

    def test_same_tool_twice_does_not_collide(self):
        graph = {
            "nodes": [n("src", "image_source", mode="source", source_id=1), n("a", "composite:count_blobs"), n("b", "composite:count_blobs", **{"thr:threshold": 255})],
            "edges": [e("src", "a", "image", "gray:image"), e("src", "b", "image", "gray:image")],
        }
        report = run_graph(graph)
        self.assertEqual(report.nodes["a"].outputs["blob:count"], 2)
        self.assertEqual(report.nodes["b"].outputs["blob:count"], 0)

    def test_inner_aliases_do_not_leak(self):
        inner = json.loads(json.dumps(TOOL_GRAPH))
        inner["nodes"][2]["interface"] = {"outputs": [{"key": "count", "alias": "inner_count"}]}
        composites.create(self.admin, {"key": "leaky", "label": "Leaky", "graph": inner, "interface": TOOL_INTERFACE})
        graph = {"nodes": [n("src", "image_source", mode="source", source_id=1), n("x", "composite:leaky")], "edges": [e("src", "x", "image", "gray:image")]}
        report = run_graph(graph)
        self.assertNotIn("inner_count", report.outputs)

    def test_validation_rejects_unknown_ports_and_bad_aliases_on_instances(self):
        graph = self.flow_graph()
        graph["edges"][0]["target_handle"] = "gray:nope"
        with self.assertRaises(ValidationError):
            validate_graph(graph)
        graph = self.flow_graph()
        graph["nodes"][1]["interface"] = {"outputs": [{"key": "blob:found", "alias": "x"}]}
        with self.assertRaises(ValidationError):
            validate_graph(graph)


class NestingTests(CompositeBase):
    def test_a_tool_cannot_contain_another_tool(self):
        # 巢狀只有兩層：流程 → 工具（2026-09-11 拍板）
        with self.assertRaises(ValidationError) as ctx:
            composites.create(self.admin, {"key": "outer", "label": "Outer", "graph": {"nodes": [n("inner", "composite:count_blobs")], "edges": []}, "interface": {}})
        self.assertEqual(ctx.exception.code, "composite_nested")
        self.assertEqual(ctx.exception.details["keys"], ["count_blobs"])
        row = CompositeTool.objects.get(key="count_blobs")
        with self.assertRaises(ValidationError) as ctx:
            composites.update(row, {"graph": {"nodes": [n("loop", "composite:count_blobs")], "edges": []}})
        self.assertEqual(ctx.exception.code, "composite_nested")
        self.assertFalse(CompositeTool.objects.filter(key="outer").exists())

    def test_flows_may_use_many_tools_side_by_side(self):
        composites.create(self.admin, {"key": "second", "label": "Second", "graph": TOOL_GRAPH, "interface": TOOL_INTERFACE})
        graph = {"nodes": [n("src", "image_source", mode="source", source_id=1), n("a", "composite:count_blobs"), n("b", "composite:second", **{"thr:threshold": 255})],
                 "edges": [e("src", "a", "image", "gray:image"), e("src", "b", "image", "gray:image")]}
        self.assertEqual(composites.check_references(None, validate_graph(graph)), 1)
        report = run_graph(graph)
        self.assertEqual(report.nodes["a"].outputs["blob:count"], 2)
        self.assertEqual(report.nodes["b"].outputs["blob:count"], 0)


class BuiltinToolsTests(CompositeBase):
    def test_builtin_tools_are_created_idempotently_and_read_only(self):
        from apps.vision.composites_builtin import SPECS, ensure_builtin_tools

        first = ensure_builtin_tools()
        self.assertEqual(first["failed"], 0, first)
        self.assertEqual(first["created"], len(SPECS))
        again = ensure_builtin_tools()
        self.assertEqual((again["created"], again["updated"], again["failed"]), (0, 0, 0), again)
        rows = {row.key: row for row in CompositeTool.objects.filter(builtin=True)}
        self.assertEqual(set(rows), {spec.key for spec in SPECS})
        for spec in SPECS:
            ct = tools.get(f"composite:{spec.key}")
            self.assertEqual(ct.category, "inspection", spec.key)
            self.assertTrue(ct.inputs, spec.key)
            self.assertTrue(ct.outputs, spec.key)
            self.assertTrue(ct.params, spec.key)
            self.assertTrue(rows[spec.key].flow.graph["nodes"], spec.key)
            self.assertTrue(all("meta" not in node for node in rows[spec.key].flow.graph["nodes"]), spec.key)
        with self.assertRaises(Conflict):
            composites.update(rows["count_objects"], {"label": "X"})
        copy_row = composites.duplicate(rows["count_objects"], self.admin, {"key": "my_count", "label": "My count"})
        self.assertFalse(copy_row.builtin)
        entry = next(item for item in tools.catalogue() if item["key"] == "composite:measure_diameter")
        self.assertEqual(entry["composite"]["builtin"], True)
        labels = {p["key"]: p["label"] for p in entry["params"]}
        self.assertEqual(labels["find:roi"], "Region")
        self.assertEqual(labels["tol:nominal"], "Nominal")
        self.assertIsNone(next(p for p in entry["params"] if p["key"] == "find:roi")["default"])
        self.assertIn("inspection", [c["key"] for c in [{"key": k} for k in tools.CATEGORY_LABELS]])

    def test_builtin_measure_diameter_runs_from_instance_params(self):
        from apps.vision.composites_builtin import ensure_builtin_tools

        ensure_builtin_tools()
        img = np.zeros((200, 200, 3), np.uint8)
        import cv2

        cv2.circle(img, (100, 100), 40, (255, 255, 255), -1)
        graph = {
            "nodes": [n("src", "image_source", mode="auto", source_id=""),
                      {**n("dia", "composite:measure_diameter", **{"find:roi": {"shape": "annulus", "cx": 100, "cy": 100, "r_inner": 20, "r_outer": 70}, "tol:nominal": 80, "tol:upper_tol": 4, "tol:lower_tol": -4}),
                       "interface": {"outputs": [{"key": "find:diameter", "alias": "d"}]}}],
            "edges": [e("src", "dia", "image", "find:image")],
        }
        compiled = compile_graph(validate_graph(graph))
        report = engine.execute(compiled, flow_id=1, flow_version=1, trigger="test", grab=lambda _sid: img, asset_path=lambda _aid: None, input_image=img)
        self.assertEqual(report.nodes["dia"].status, "ok", report.nodes["dia"].message)
        self.assertAlmostEqual(report.outputs["d"], 80, delta=2)
        self.assertEqual(report.nodes["dia"].branch, "tol:pass")
        self.assertTrue(report.nodes["dia"].outputs["tol:in_spec"])
        self.assertEqual(report.outputs["judge"], "OK")


class ApiTests(CompositeBase):
    def call(self, method, path="", data=None, user=None, **kw):
        token = AuthToken.issue(user or self.admin)
        url = "/api/vision/composite-tools" + path
        if method == "get":
            return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}")
        if method == "delete":
            return self.client.delete(url, HTTP_AUTHORIZATION=f"Bearer {token}")
        return getattr(self.client, method)(url, data=json.dumps(data or {}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}", **kw)

    def test_operator_can_read_but_not_write(self):
        self.assertEqual(self.call("get", user=self.operator).status_code, 200)
        self.assertEqual(self.call("post", data={"key": "x", "label": "X", "graph": TOOL_GRAPH}, user=self.operator).status_code, 403)
        self.assertEqual(self.call("put", f"/{self.tool.id}", {"label": "Y"}, self.operator).status_code, 403)
        self.assertEqual(self.call("delete", f"/{self.tool.id}", user=self.operator).status_code, 403)

    def test_crud_usage_and_delete_guard(self):
        listing = self.call("get").json()
        self.assertEqual([t["key"] for t in listing["items"]], ["count_blobs"])
        self.assertEqual(listing["items"][0]["used_by_flows"], 0)
        flow = Flow.objects.create(name="Uses it", graph={"nodes": [n("c", "composite:count_blobs")], "edges": []})
        usage = self.call("get", f"/{self.tool.id}/usage").json()
        self.assertEqual(usage["flows"], [{"id": flow.id, "name": "Uses it", "count": 1}])
        r = self.call("delete", f"/{self.tool.id}")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["error"]["details"]["flows"][0]["name"], "Uses it")
        r = self.call("put", f"/{self.tool.id}", {"label": "Renamed", "interface": {**TOOL_INTERFACE, "params": []}})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["label"], "Renamed")
        self.assertEqual([p.key for p in tools.get("composite:count_blobs").params], [])
        bad = self.call("post", data={"key": "Bad Key", "label": "X", "graph": TOOL_GRAPH})
        self.assertEqual(bad.status_code, 422, bad.content)
        dup = self.call("post", data={"key": "count_blobs", "label": "X", "graph": TOOL_GRAPH})
        self.assertEqual(dup.status_code, 409, dup.content)
        flow.delete()
        self.assertEqual(self.call("delete", f"/{self.tool.id}").status_code, 204)
        self.assertFalse(Flow.objects.filter(kind="tool").exists())
        self.assertFalse(tools.has("composite:count_blobs"))

    def test_duplicate_makes_an_editable_copy(self):
        self.tool.builtin = True
        self.tool.save()
        composites.invalidate()
        self.assertEqual(self.call("put", f"/{self.tool.id}", {"label": "Y"}).status_code, 409)
        r = self.call("post", f"/{self.tool.id}/duplicate", {"key": "my_count", "label": "My count"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["key"], "my_count")
        self.assertFalse(r.json()["builtin"])
        self.assertEqual(tools.get("composite:my_count").params[0].label, "Level")

    def test_export_and_import_round_trip(self):
        r = self.call("get", f"/{self.tool.id}/export?download=0")
        self.assertEqual(r.status_code, 200)
        doc = json.loads(r.content)
        self.assertEqual(doc["kind"], "composite_tool")
        self.assertEqual(doc["key"], "count_blobs")
        self.assertEqual(doc["interface"], TOOL_INTERFACE)
        kept = self.call("post", "/import", doc)
        self.assertEqual(kept.status_code, 200, kept.content)
        self.assertEqual(kept.json()["action"], "kept")
        doc["label"] = "Imported"
        replaced = self.call("post", "/import", {"doc": doc, "replace": True})
        self.assertEqual(replaced.json()["action"], "updated")
        self.assertEqual(CompositeTool.objects.get(key="count_blobs").label, "Imported")
        doc["key"] = "count_blobs_2"
        created = self.call("post", "/import", doc)
        self.assertEqual(created.status_code, 201, created.content)
        self.assertTrue(tools.has("composite:count_blobs_2"))
        self.assertEqual(self.call("post", "/import", {"kind": "nope"}).status_code, 422)

    def test_flow_export_embeds_dependencies_and_import_restores_them(self):
        flow = Flow.objects.create(name="Dep flow", graph={"nodes": [n("src", "image_source", mode="auto", source_id=""), n("c", "composite:count_blobs")],
                                                            "edges": [e("src", "c", "image", "gray:image")]})
        doc = serialize.export_flow(flow)
        self.assertEqual([d["key"] for d in doc["composite_tools"]], ["count_blobs"])
        CompositeTool.objects.all().delete()
        Flow.objects.filter(kind="tool").delete()
        composites.invalidate()
        doc = json.loads(json.dumps(doc))
        doc["name"] = "Dep flow (imported)"
        imported, created = serialize.import_flow(doc, owner=self.admin)
        self.assertTrue(created)
        self.assertTrue(tools.has("composite:count_blobs"))
        self.assertEqual(doc[serialize.COMPOSITE_REPORT_KEY], [{"key": "count_blobs", "action": "created"}])
        report = run_graph(imported.graph, input_image=image())
        self.assertEqual(report.nodes["c"].outputs["blob:count"], 2)

    def test_preview_on_a_tool_flow_feeds_the_scratch_image_to_exposed_image_inputs(self):
        from apps.vision.images import store

        ref = "test:tool:input"
        store.put(ref, image(), flow_id=self.tool.flow_id, run_id="test", pinned=True)
        token = AuthToken.issue(self.admin)
        r = self.client.post(f"/api/vision/flows/{self.tool.flow_id}/preview", data=json.dumps({"graph": TOOL_GRAPH, "reuse_image_ref": ref, "until_node": "blob"}),
                             content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(data["nodes"]["blob"]["status"], "ok", data["nodes"]["blob"])
        self.assertEqual(data["nodes"]["blob"]["outputs"]["count"], 2)
        self.assertEqual(data["nodes"][composites.INPUT_NODE_ID]["status"], "ok")


class DeleteGuardTests(CompositeBase):
    def test_delete_blocked_while_a_flow_uses_it(self):
        Flow.objects.create(name="Wrapper flow", graph={"nodes": [n("a", "composite:count_blobs")], "edges": []})
        with self.assertRaises(Conflict) as ctx:
            composites.delete(CompositeTool.objects.get(key="count_blobs"))
        self.assertEqual(ctx.exception.details["flows"][0]["name"], "Wrapper flow")


class VersionLockTests(CompositeBase):
    """P5：實例記 meta.tool_version，展平用那一版的快照；沒記＝跟最新。"""

    def flow(self, pinned: int | None, **params):
        node = n("count", "composite:count_blobs", **params)
        if pinned is not None:
            node["meta"] = {"tool_version": pinned}
        return {"nodes": [n("src", "image_source", mode="source", source_id=1), node, n("out", "output", name="ok")],
                "edges": [e("src", "count", "image", "gray:image"), e("count", "out", "blob:count", "value")]}

    def test_create_and_update_snapshot_versions_and_instances_pin_them(self):
        self.assertEqual(self.tool.version, 1)
        self.assertEqual([v["version"] for v in composites.versions_of(self.tool)], [1])
        pinned = validate_graph(self.flow(1))
        loose = validate_graph(self.flow(None))
        composites.update(self.tool, {"label": "Renamed"}, user=self.admin)  # 改名稱不算新版
        self.assertEqual(self.tool.version, 1)
        graph2 = copy.deepcopy(TOOL_GRAPH)
        graph2["nodes"][1]["params"]["threshold"] = 200
        composites.update(self.tool, {"graph": graph2}, user=self.admin)
        self.assertEqual(self.tool.version, 2)
        self.assertEqual([v["version"] for v in composites.versions_of(self.tool)], [2, 1])
        flat_pinned, instances = composites.flatten(pinned)
        flat_loose, _ = composites.flatten(loose)
        self.assertEqual(next(x for x in flat_pinned["nodes"] if x["id"] == "count.thr")["params"]["threshold"], 128)
        self.assertEqual(next(x for x in flat_loose["nodes"] if x["id"] == "count.thr")["params"]["threshold"], 200)
        self.assertEqual(instances["count"]["version"], 1)
        self.assertEqual(tools.catalogue()[0] and next(item for item in tools.catalogue() if item["key"] == "composite:count_blobs")["composite"]["version"], 2)
        # 更新到最新＝改 meta 即可
        updated = validate_graph({**pinned, "nodes": [{**x, "meta": {"tool_version": 2}} if x["id"] == "count" else x for x in pinned["nodes"]]})
        flat_updated, _ = composites.flatten(updated)
        self.assertEqual(next(x for x in flat_updated["nodes"] if x["id"] == "count.thr")["params"]["threshold"], 200)
        # 快照不存在的版本：退回最新、不炸
        flat_missing, _ = composites.flatten(validate_graph(self.flow(99)))
        self.assertEqual(next(x for x in flat_missing["nodes"] if x["id"] == "count.thr")["params"]["threshold"], 200)
        with self.assertRaises(ValidationError):
            validate_graph(self.flow(0))
        report = run_graph(pinned)
        self.assertEqual(report.nodes["count"].status, "ok")

    def test_pinned_instances_validate_against_their_own_interface(self):
        pinned = validate_graph({**self.flow(1), "edges": [e("src", "count", "image", "gray:image"), e("count", "out", "blob:mask", "value")]})
        iface2 = copy.deepcopy(TOOL_INTERFACE)
        iface2["outputs"] = [o for o in iface2["outputs"] if o["key"] != "blob:mask"]
        composites.update(self.tool, {"interface": iface2}, user=self.admin)
        self.assertEqual(self.tool.version, 2)
        validate_graph(copy.deepcopy(pinned))  # v1 還有 blob:mask
        loose = copy.deepcopy(pinned)
        loose["nodes"][1].pop("meta")
        with self.assertRaises(ValidationError):
            validate_graph(loose)
        diff = composites.diff_versions(self.tool, 1)
        self.assertEqual((diff["from"], diff["to"], diff["interface"]["outputs"]["removed"]), (1, 2, ["blob:mask"]))
        self.assertFalse(diff["empty"])
        with self.assertRaises(NotFound):
            composites.snapshot_of(self.tool, 7)

    def test_version_endpoints_and_encapsulate_pin(self):
        token = AuthToken.issue(self.admin)
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        graph2 = copy.deepcopy(TOOL_GRAPH)
        graph2["nodes"][1]["params"]["threshold"] = 60
        res = self.client.put(f"/api/vision/composite-tools/{self.tool.id}", data=json.dumps({"graph": graph2}), content_type="application/json", **auth)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["version"], 2)
        listed = self.client.get(f"/api/vision/composite-tools/{self.tool.id}/versions", **auth).json()
        self.assertEqual((listed["version"], [v["version"] for v in listed["items"]], listed["items"][0]["current"]), (2, [2, 1], True))
        snap = self.client.get(f"/api/vision/composite-tools/{self.tool.id}/versions/1", **auth).json()
        self.assertEqual(snap["graph"]["nodes"][1]["params"]["threshold"], 128)
        diff = self.client.get(f"/api/vision/composite-tools/{self.tool.id}/diff?from_version=1", **auth).json()
        self.assertEqual(diff["summary"], "threshold 128 → 60")
        self.assertEqual(self.client.get(f"/api/vision/composite-tools/{self.tool.id}/versions/9", **auth).status_code, 404)
        enc = composites.encapsulate(validate_graph(self.flow(None)), ["count"], "wrap", "Wrap", version=1)
        self.assertEqual(enc["instance"]["meta"], {"tool_version": 1})
