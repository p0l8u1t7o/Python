from __future__ import annotations

import copy
import json

from django.conf import settings
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from apps.core.models import AuditLog
from apps.vision import dashboard, variables
from apps.vision.models import Dashboard, Flow, ImageSource
from apps.vision.runner import runner


def layout(flow_id: int = 1) -> dict:
    return {
        "rows": 2,
        "cols": 2,
        "cells": [
            {"id": "a", "row": 1, "col": 1, "row_span": 1, "col_span": 1},
            {"id": "b", "row": 1, "col": 2, "row_span": 1, "col_span": 1},
            {"id": "c", "row": 2, "col": 1, "row_span": 1, "col_span": 2},
        ],
        "bars": {"top": True, "bottom": False, "left": False, "right": False},
        "default_flow_id": flow_id,
        "widgets": [
            {"id": "img", "type": "image", "cell": "a", "props": {"overlays": True, "crosshair": False, "history": 1}, "source": {"kind": "image"}},
            {"id": "verdict", "type": "verdict", "cell": "b", "props": {}, "source": {"kind": "status"}},
            {"id": "control", "type": "run_control", "cell": "c", "props": {"flow_id": flow_id}},
        ],
        "theme": {},
    }


class DashboardValidationTests(TestCase):
    def test_default_layout_validates(self):
        out = dashboard.validate(dashboard.DEFAULT_LAYOUT)
        self.assertEqual(out["rows"], 2)
        self.assertIn("run_control", [w["type"] for w in out["widgets"]])

    def test_effective_layout_round_trips_through_validate(self):
        """檢視端 GET 回來的版面（選填欄位補成 None）必須能原樣 PATCH 回去——JSON 編輯器走的就是這條路。"""
        shown = dashboard.effective(dashboard.DEFAULT_LAYOUT)
        self.assertIn("node", shown["widgets"][0]["props"])          # image 的選填 node 被補成 None
        again = dashboard.validate(copy.deepcopy(shown))
        self.assertEqual(dashboard.effective(again), shown)
        # 明確給 null 的選填 props 也算「用預設」
        layout = copy.deepcopy(dashboard.DEFAULT_LAYOUT)
        layout["widgets"][0]["props"] = {"node": None, "port": None}
        self.assertIsNone(dashboard.validate(layout)["widgets"][0]["props"]["node"])

    def test_rejects_unknown_widget_type(self):
        raw = layout()
        raw["widgets"][0]["type"] = "nope"
        with self.assertRaisesRegex(dashboard.DashboardError, "Widget 'img'.*unknown type"):
            dashboard.validate(raw)

    def test_rejects_bad_props(self):
        raw = layout()
        raw["widgets"][0]["props"]["history"] = 0
        with self.assertRaisesRegex(dashboard.DashboardError, "Widget 'img' props.history"):
            dashboard.validate(raw)
        raw = layout()
        raw["widgets"][0]["props"]["extra"] = 1
        with self.assertRaisesRegex(dashboard.DashboardError, "Widget 'img'.*props.extra"):
            dashboard.validate(raw)

    def test_rejects_overlapping_cells(self):
        raw = layout()
        raw["cells"][1]["col"] = 1
        with self.assertRaisesRegex(dashboard.DashboardError, "overlaps"):
            dashboard.validate(raw)

    def test_rejects_duplicate_ids(self):
        raw = layout()
        raw["widgets"][1]["id"] = "img"
        with self.assertRaisesRegex(dashboard.DashboardError, "Duplicate widget id"):
            dashboard.validate(raw)
        raw = layout()
        raw["cells"][1]["id"] = "a"
        with self.assertRaisesRegex(dashboard.DashboardError, "Duplicate cell id"):
            dashboard.validate(raw)

    def test_rejects_grid_bounds_and_missing_cell(self):
        raw = layout()
        raw["rows"] = 11
        with self.assertRaisesRegex(dashboard.DashboardError, "rows"):
            dashboard.validate(raw)
        raw = layout()
        raw["widgets"][0]["cell"] = "missing"
        with self.assertRaisesRegex(dashboard.DashboardError, "Widget 'img'.*unknown cell"):
            dashboard.validate(raw)

    def test_effective_drops_bad_widgets_and_fills_defaults(self):
        raw = layout()
        raw["widgets"].append({"id": "bad", "type": "nope", "cell": "a", "props": {}})
        raw["widgets"][0]["props"] = {}
        out = dashboard.effective(raw)
        self.assertEqual([w["id"] for w in out["widgets"]], ["img", "verdict", "control"])
        self.assertEqual(out["widgets"][0]["props"]["history"], 1)
        self.assertEqual(dashboard.effective("bad")["rows"], dashboard.DEFAULT_LAYOUT["rows"])

    def test_flows_of_collects_default_props_sources_and_image_items(self):
        raw = layout(3)
        raw["widgets"].append({
            "id": "multi",
            "type": "images",
            "cell": "b",
            "props": {"items": [{"flow_id": 4, "node": "n"}]},
            "source": {"flow_id": 5, "kind": "image"},
        })
        self.assertEqual(dashboard.flows_of(raw), {3, 4, 5})


class DashboardApiTests(TestCase):
    def setUp(self):
        self.flow = Flow.objects.create(name="dash-flow", graph={"nodes": [], "edges": []})

    def test_crud_default_unique_and_audit(self):
        r = self.client.post(
            "/api/vision/dashboards",
            data=json.dumps({"name": "Main", "layout": layout(self.flow.id), "is_default": True}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        first = r.json()
        self.assertEqual(first["name"], "Main")
        self.assertTrue(first["is_default"])
        self.assertEqual(first["widget_count"], 3)

        r = self.client.post(
            "/api/vision/dashboards",
            data=json.dumps({"name": "Second", "layout": layout(self.flow.id), "is_default": True}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertFalse(Dashboard.objects.get(pk=first["id"]).is_default)
        self.assertTrue(Dashboard.objects.get(pk=r.json()["id"]).is_default)

        r = self.client.get("/api/vision/dashboards/default")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["name"], "Second")

        patch = copy.deepcopy(layout(self.flow.id))
        patch["widgets"][0]["props"]["crosshair"] = True
        r = self.client.patch(
            f"/api/vision/dashboards/{first['id']}",
            data=json.dumps({"name": "Renamed", "layout": patch, "is_default": False}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["layout"]["widgets"][0]["props"]["crosshair"], True)

        self.assertEqual(self.client.delete(f"/api/vision/dashboards/{first['id']}").status_code, 204)
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"dashboard.create", "dashboard.update", "dashboard.delete"} <= actions)

    def test_permissions_operator_can_read_not_write_and_default_404(self):
        r = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret1"}), content_type="application/json")
        admin = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['token']}"}
        self.client.post("/api/users", data=json.dumps({"username": "op", "password": "pass123", "role": "operator"}), content_type="application/json", **admin)
        token = self.client.post("/api/auth/login", data=json.dumps({"username": "op", "password": "pass123"}), content_type="application/json").json()["token"]
        op = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        row = Dashboard.objects.create(name="Readable", layout=layout(self.flow.id))

        self.assertEqual(self.client.get("/api/vision/dashboards", **op).status_code, 200)
        self.assertEqual(self.client.get(f"/api/vision/dashboards/{row.id}", **op).status_code, 200)
        self.assertEqual(self.client.get("/api/vision/dashboards/default", **op).status_code, 404)
        r = self.client.post("/api/vision/dashboards", data=json.dumps({"name": "Nope"}), content_type="application/json", **op)
        self.assertEqual(r.status_code, 403)
        r = self.client.patch(f"/api/vision/dashboards/{row.id}", data=json.dumps({"name": "Nope"}), content_type="application/json", **op)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.delete(f"/api/vision/dashboards/{row.id}", **op).status_code, 403)

    def test_bad_layout_uses_bad_layout_code(self):
        bad = layout(self.flow.id)
        bad["widgets"][0]["type"] = "bad"
        r = self.client.post("/api/vision/dashboards", data=json.dumps({"name": "Bad", "layout": bad}), content_type="application/json")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "bad_layout")

    def test_not_found(self):
        self.assertEqual(self.client.get("/api/vision/dashboards/999").status_code, 404)
        self.assertEqual(self.client.delete("/api/vision/dashboards/999").status_code, 404)


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class DashboardDataTests(TransactionTestCase):
    def setUp(self):
        variables.store.clear()
        variables.store.on_dirty = None
        self.addCleanup(variables.store.clear)
        source = ImageSource.objects.create(name="dash-syn", kind="synthetic", config={"width": 32, "height": 24})
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": source.id}},
                {"id": "i", "type": "intensity", "params": {}},
                {"id": "o", "type": "output", "params": {"name": "mean"}},
                {"id": "j", "type": "judge", "params": {"verdict": "ok"}},
            ],
            "edges": [
                {"source": "src", "target": "i"},
                {"source": "i", "source_handle": "mean", "target": "o", "target_handle": "value"},
            ],
        }
        self.flow = Flow.objects.create(name="dash-live", graph=graph, board={"values": [{"key": "mean", "decimals": 0}]})
        runner.forget(self.flow.id)
        self.addCleanup(runner.forget, self.flow.id)
        live_layout = layout(self.flow.id)
        live_layout["widgets"].append({"id": "missing", "type": "run_status", "cell": "b", "props": {}, "source": {"flow_id": 9999, "kind": "status"}})
        self.dashboard = Dashboard.objects.create(name="Live", layout=live_layout, is_default=True)

    def test_data_shape_after_run(self):
        variables.store.set(None, "station_mode", "auto")
        runner.run_sync(self.flow, trigger="api")
        r = self.client.get(f"/api/vision/dashboards/{self.dashboard.id}/data")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertIn("generated_at", body)
        self.assertIn(str(self.flow.id), body["flows"])
        pack = body["flows"][str(self.flow.id)]
        self.assertEqual(pack["run"]["verdict"], "OK")
        self.assertIsNotNone(pack["run"]["image"])
        self.assertEqual(pack["values"][0]["key"], "mean")
        self.assertIn("device", body)
        self.assertEqual(body["device"]["station_id"], settings.VISION.get("STATION_ID", "ST01"))
        self.assertIn("capacity", body["device"])
        self.assertEqual(body["variables"]["station"]["station_mode"], "auto")
        self.assertEqual(body["flows"]["9999"], {"missing": True})


class RoundTripTests(SimpleTestCase):
    """GET 回來的版面（effective 補了 None）直接存回去必須過驗證：JSON 編輯器走的就是這條路。"""

    def test_effective_output_validates_again(self):
        from apps.vision import dashboard

        shown = dashboard.effective(dashboard.DEFAULT_LAYOUT)
        self.assertEqual(dashboard.validate(shown)["widgets"], shown["widgets"])

    def test_null_optional_prop_means_default(self):
        from apps.vision import dashboard

        layout = dashboard.effective(dashboard.DEFAULT_LAYOUT)
        image = next(w for w in layout["widgets"] if w["type"] == "image")
        image["props"]["node"] = None
        checked = dashboard.validate(layout)
        self.assertIsNone(next(w for w in checked["widgets"] if w["type"] == "image")["props"]["node"])
        with self.assertRaises(dashboard.DashboardError):
            image["props"]["node"] = 123
            dashboard.validate(layout)
