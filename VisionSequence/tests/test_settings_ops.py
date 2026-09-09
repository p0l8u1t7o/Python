"""站台設定：執行策略、日誌等級與 Auto Save Solution。"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accounts.models import AuthToken, UserPref
from apps.vision import api_settings, versions
from apps.vision.models import Flow, FlowVersion
from apps.vision.runner import FlowRuntime, runner


GRAPH_A = {"nodes": [{"id": "a", "type": "judge", "params": {"verdict": "ok"}}], "edges": []}
GRAPH_B = {"nodes": [{"id": "a", "type": "judge", "params": {"verdict": "ng"}}], "edges": []}


class SettingsOpsTests(TestCase):
    def setUp(self):
        api_settings.invalidate()
        self.addCleanup(api_settings.invalidate)
        self.addCleanup(api_settings.apply_log_level, "info")
        r = self.client.post("/api/auth/setup", data='{"username": "admin", "password": "Admin12345"}', content_type="application/json")
        self.assertIn(r.status_code, (200, 201), r.content)
        self.admin = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['token']}"}
        user = User.objects.create_user("op", password="x")
        UserPref.objects.create(user=user, role="operator")
        self.operator = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(user)}"}

    def test_log_level_patch_changes_python_logger_and_validates_access(self):
        expected = {
            "error": logging.ERROR,
            "info": logging.INFO,
            "debug": logging.DEBUG,
            "trace": api_settings.TRACE_LEVEL,
        }
        for level, numeric in expected.items():
            r = self.client.patch("/api/vision/settings/log-level", data=json.dumps({"level": level}), content_type="application/json", **self.admin)
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(logging.getLogger("apps.vision.runner").getEffectiveLevel(), numeric)
            self.assertEqual(r.json()["effective"], numeric)

        r = self.client.patch("/api/vision/settings/log-level", data='{"level":"debug"}', content_type="application/json", **self.operator)
        self.assertEqual(r.status_code, 403, r.content)
        r = self.client.patch("/api/vision/settings/log-level", data='{"level":"verbose"}', content_type="application/json", **self.admin)
        self.assertEqual(r.status_code, 422, r.content)

    @override_settings(VISION={**settings.VISION, "MAX_WORKERS": 10})
    def test_stable_cycle_mode_is_read_from_memory_not_the_database(self):
        """節拍穩定模式打開後 capacity 要反映，而且**熱路徑一次 DB 都不能查**。"""
        api_settings.save({"stable_cycle_mode": True})
        rt = FlowRuntime(flow_id=99)
        flow = Flow(id=99, name="memory-only", graph=GRAPH_A, concurrency=8)
        with self.assertNumQueries(0):
            data = runner.capacity()
            concurrency = runner._flow_concurrency(rt, flow)  # noqa: SLF001 - 驗證熱路徑只讀記憶體
        self.assertTrue(data["stable_cycle_mode"])
        self.assertEqual(data["configured_max_workers"], 10)
        self.assertEqual(data["max_workers"], 1)
        self.assertEqual(concurrency, 1)

    def test_auto_save_skips_flows_whose_graph_did_not_change(self):
        """內容沒變就不存——KEEP_VERSIONS 只有 50，不然會把手動存的版本擠掉。"""
        flow = Flow.objects.create(name="auto-save", graph=GRAPH_A)
        versions.snapshot(flow, note="created")
        self.assertEqual(FlowVersion.objects.filter(flow=flow).count(), 1)

        result = api_settings.auto_save_once()
        self.assertEqual(result["saved"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(FlowVersion.objects.filter(flow=flow).count(), 1)

    def test_auto_save_snapshots_a_flow_whose_graph_changed(self):
        flow = Flow.objects.create(name="auto-save-changed", graph=GRAPH_A)
        versions.snapshot(flow, note="created")
        Flow.objects.filter(pk=flow.pk).update(graph=GRAPH_B)

        result = api_settings.auto_save_once()
        self.assertEqual(result["saved"], 1)
        self.assertEqual(FlowVersion.objects.filter(flow=flow).count(), 2)
        flow.refresh_from_db()
        self.assertEqual(flow.version, 2)
        self.assertEqual(FlowVersion.objects.get(flow=flow, version=2).graph, GRAPH_B)

    def test_new_get_endpoint_is_in_the_smoke_list(self):
        source = __import__("pathlib").Path("tests/test_smoke_api.py").read_text(encoding="utf-8")
        self.assertIn("/api/vision/settings/log-level", source)
