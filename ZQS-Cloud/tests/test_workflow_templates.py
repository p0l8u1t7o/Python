"""流程範本：內建目錄、存成範本時佔位符化、載到別的場域時解回、解不回就回報。"""

from __future__ import annotations

from apps.devices.models import DeviceCategory
from apps.ems.models import AssetRole, EnergyAsset
from apps.workflows import templates as tpl
from apps.workflows.models import Workflow, WorkflowTemplate
from tests import factories
from tests.test_api import API, ApiTestCase


def _graph(bess_id: str, meter_id: str, workflow_id: str | None = None) -> dict:
    nodes = [
        {"id": "start-1", "type": "start", "label": "開始", "params": {}, "position": {"x": 0, "y": 0}},
        {"id": "condition-1", "type": "if_end", "label": "需量高", "position": {"x": 0, "y": 100},
         "params": {"device_id": meter_id, "metric_key": "grid_power_w", "operator": "gt", "threshold": 1000}},
        {"id": "command-1", "type": "set_data", "label": "放電", "position": {"x": 0, "y": 200},
         "params": {"device_id": bess_id, "command": "set_power_setpoint", "param_name": "power_w", "value": 100000}},
        {"id": "end-1", "type": "end", "label": "結束", "params": {}, "position": {"x": 0, "y": 300}},
    ]
    edges = [
        {"id": "e1", "source": "start-1", "target": "condition-1", "source_handle": "out"},
        {"id": "e2", "source": "condition-1", "target": "command-1", "source_handle": "true"},
        {"id": "e3", "source": "condition-1", "target": "end-1", "source_handle": "false"},
        {"id": "e4", "source": "command-1", "target": "end-1", "source_handle": "out"},
    ]
    if workflow_id:
        nodes.append({"id": "run_workflow-1", "type": "run_workflow", "label": "子流程", "position": {"x": 0, "y": 400},
                      "params": {"workflow_id": workflow_id}})
        edges.append({"id": "e5", "source": "command-1", "target": "run_workflow-1", "source_handle": "out"})
    return {"nodes": nodes, "edges": edges}


class TemplateLogicTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        bess_type = factories.blueprint("bess", org=self.org, category=DeviceCategory.BATTERY,
                                        can_charge=True, can_discharge=True, is_dispatchable=True)
        meter_type = factories.blueprint("meter", org=self.org, category=DeviceCategory.METER)
        self.site_a = factories.site(self.org, "a")
        self.site_b = factories.site(self.org, "b")
        self.bess_a = factories.device(self.org, "BESS-A", site_obj=self.site_a, device_type=bess_type)
        self.meter_a = factories.device(self.org, "METER-A", site_obj=self.site_a, device_type=meter_type)
        self.bess_b = factories.device(self.org, "BESS-B", site_obj=self.site_b, device_type=bess_type)
        for site, bess, meter in ((self.site_a, self.bess_a, self.meter_a), (self.site_b, self.bess_b, None)):
            EnergyAsset.objects.create(organization=self.org, site=site, device=bess, role=AssetRole.BATTERY,
                                       power_metric="battery_power_w", soc_metric="battery_soc")
            if meter:
                EnergyAsset.objects.create(organization=self.org, site=site, device=meter, role=AssetRole.GRID_METER,
                                           power_metric="grid_power_w")

    def test_builtin_catalogue_comes_from_the_showcase_builders(self) -> None:
        builtins = tpl.builtin_templates()
        self.assertEqual(len(builtins), 6)
        self.assertTrue(all(t.id.startswith("builtin:") for t in builtins))
        self.assertIn("BESS", builtins[0].placeholders)

    def test_templatize_replaces_device_ids_with_role_placeholders(self) -> None:
        graph, placeholders = tpl.templatize(_graph(str(self.bess_a.id), str(self.meter_a.id)), self.org)
        params = {n["id"]: n["params"] for n in graph["nodes"]}
        self.assertEqual(params["command-1"]["device_id"], "{BESS}")
        self.assertEqual(params["condition-1"]["device_id"], "{METER}")
        self.assertEqual(placeholders, ["BESS", "METER"])

    def test_instantiate_on_another_site_resolves_what_it_can_and_reports_the_rest(self) -> None:
        graph, _ = tpl.templatize(_graph(str(self.bess_a.id), str(self.meter_a.id)), self.org)
        resolved, missing = tpl.instantiate(graph, self.site_b, self.org)
        params = {n["id"]: n["params"] for n in resolved["nodes"]}
        self.assertEqual(params["command-1"]["device_id"], str(self.bess_b.id))
        self.assertEqual(params["condition-1"]["device_id"], "{METER}", "site B has no grid meter: left as-is")
        self.assertEqual(missing, ["METER"])

    def test_run_workflow_targets_are_kept_by_name(self) -> None:
        child = Workflow.objects.create(organization=self.org, name="子流程", graph={"nodes": [], "edges": []})
        graph, placeholders = tpl.templatize(_graph(str(self.bess_a.id), str(self.meter_a.id), str(child.id)), self.org)
        self.assertIn("WORKFLOW:子流程", placeholders)
        resolved, missing = tpl.instantiate(graph, self.site_a, self.org)
        self.assertEqual(resolved["nodes"][-1]["params"]["workflow_id"], str(child.id))
        self.assertEqual(missing, [])

    def test_fresh_ids_keep_edges_consistent(self) -> None:
        graph = tpl.with_fresh_ids(_graph("x", "y"))
        ids = {n["id"] for n in graph["nodes"]}
        self.assertEqual(len(ids), 4)
        self.assertNotIn("start-1", ids)
        for edge in graph["edges"]:
            self.assertIn(edge["source"], ids)
            self.assertIn(edge["target"], ids)


class TemplateApiTests(TemplateLogicTests):
    def test_save_list_instantiate_delete_round_trip(self) -> None:
        op = self.login("op@acme-demo.com")
        admin = self.login("admin@acme-demo.com")
        body = {"name": "我的削峰", "description": "測試", "graph": _graph(str(self.bess_a.id), str(self.meter_a.id))}
        created = self.call("post", f"{API}/workflows/templates", op, body)
        self.assertEqual(created.status_code, 201, created.content)
        template_id = created.json()["id"]
        self.assertEqual(created.json()["placeholders"], ["BESS", "METER"])
        self.assertEqual(created.json()["node_count"], 4)

        listed = self.get(f"{API}/workflows/templates", op).json()
        self.assertEqual(len([t for t in listed if t["source"] == "builtin"]), 6)
        self.assertEqual(len([t for t in listed if t["source"] == "custom"]), 1)

        dup = self.call("post", f"{API}/workflows/templates", op, body)
        self.assertEqual(dup.status_code, 409)

        inst = self.call("post", f"{API}/workflows/templates/{template_id}/instantiate", op,
                         {"site_id": str(self.site_b.id), "fresh_ids": True})
        self.assertEqual(inst.status_code, 200, inst.content)
        self.assertEqual(inst.json()["missing"], ["METER"])
        self.assertEqual(inst.json()["missing_labels"]["METER"], "市電關口電表")
        self.assertNotIn("start-1", {n["id"] for n in inst.json()["graph"]["nodes"]})

        builtin = self.call("post", f"{API}/workflows/templates/builtin:0/instantiate", op,
                            {"site_id": str(self.site_a.id)})
        self.assertEqual(builtin.status_code, 200)
        self.assertNotIn("{BESS}", str(builtin.json()["graph"]))

        self.assertEqual(self.call("delete", f"{API}/workflows/templates/builtin:0", admin).status_code, 409)
        self.assertEqual(self.call("delete", f"{API}/workflows/templates/{template_id}", op).status_code, 403)
        self.assertEqual(self.call("delete", f"{API}/workflows/templates/{template_id}", admin).status_code, 200)
        self.assertFalse(WorkflowTemplate.objects.exists())

    def test_templates_are_tenant_scoped(self) -> None:
        WorkflowTemplate.objects.create(organization=self.other_org, name="別人的", graph={"nodes": [], "edges": []})
        op = self.login("op@acme-demo.com")
        listed = self.get(f"{API}/workflows/templates", op).json()
        self.assertFalse(any(t["name"] == "別人的" for t in listed))
