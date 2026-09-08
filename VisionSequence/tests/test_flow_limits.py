from __future__ import annotations

import json
import time

from django.contrib.auth.models import User
from django.conf import settings
from django.test import TestCase, override_settings

from apps.accounts.models import AuthToken, UserPref
from apps.vision import engine
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.models import Flow
from apps.vision.runner import runner
from apps.vision.tools.base import Port, Result, Tool, register, unregister


EXECUTED: list[str] = []


def n(nid: str, ntype: str, **params):
    return {"id": nid, "type": ntype, "params": params}


def e(s: str, t: str, sh: str = "", th: str = ""):
    return {"source": s, "target": t, "source_handle": sh, "target_handle": th}


class SlowLimitTool(Tool):
    key = "_limit_slow"
    label = "slow"
    category = "logic"
    inputs = []
    outputs = [Port("value", "v", "number")]
    allows_unconnected = True

    def execute(self, ctx):
        EXECUTED.append(str(ctx.node.get("id")))
        time.sleep(ctx.number("sleep", 0.02))
        return Result(outputs={"value": 1})


class MarkLimitTool(Tool):
    key = "_limit_mark"
    label = "mark"
    category = "logic"
    inputs = []
    outputs = [Port("value", "v", "number")]
    allows_unconnected = True

    def execute(self, ctx):
        EXECUTED.append(str(ctx.node.get("id")))
        return Result(outputs={"value": 1})


class NgLimitTool(Tool):
    key = "_limit_ng"
    label = "ng"
    category = "logic"
    inputs = []
    outputs = [Port("value", "v", "number")]
    allows_unconnected = True

    def execute(self, ctx):
        EXECUTED.append(str(ctx.node.get("id")))
        return Result(status="ng", outputs={"value": 0}, message="NG")


class NgBranchLimitTool(Tool):
    key = "_limit_branch"
    label = "branch"
    category = "logic"
    inputs = []
    outputs = [Port("value", "v", "number")]
    allows_unconnected = True

    def execute(self, ctx):
        EXECUTED.append(str(ctx.node.get("id")))
        return Result(branch="ng", outputs={"value": 0}, message="branch ng")


def run_graph(graph: dict, **kw):
    compiled = compile_graph(validate_graph(graph))
    return engine.execute(
        compiled,
        flow_id=1,
        flow_version=1,
        trigger="test",
        grab=lambda sid: None,
        asset_path=lambda aid: None,
        **kw,
    )


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class FlowLimitTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for tool in (SlowLimitTool(), MarkLimitTool(), NgLimitTool(), NgBranchLimitTool()):
            register(tool)

    @classmethod
    def tearDownClass(cls):
        for key in ("_limit_slow", "_limit_mark", "_limit_ng", "_limit_branch"):
            unregister(key)
        super().tearDownClass()

    def setUp(self):
        EXECUTED.clear()
        for fid in list(runner._runtimes):
            runner.forget(fid)

    def test_flow_timeout_stops_at_node_boundary(self):
        graph = {"nodes": [n("slow", "_limit_slow", sleep=0.04), n("late", "_limit_mark")], "edges": []}
        flow = Flow.objects.create(name="timeout", graph=validate_graph(graph), timeout_s=1)
        flow.timeout_s = 0.01

        report = runner.run_sync(flow)

        self.assertEqual(report.status, "failed")
        self.assertEqual(EXECUTED, ["slow"])
        self.assertEqual(report.nodes["slow"].status, "ok")
        self.assertEqual(report.nodes["late"].status, "skipped")
        self.assertIn("Flow timed out", report.error)
        self.assertIn("slow", report.error)
        self.assertTrue(any("stopped after step 'slow'" in warning for warning in report.warnings))

    def test_timeout_zero_keeps_previous_behavior(self):
        graph = {"nodes": [n("slow", "_limit_slow", sleep=0.01), n("late", "_limit_mark")], "edges": []}
        report = run_graph(graph, flow_timeout_s=0)

        self.assertEqual(report.status, "ok")
        self.assertEqual(EXECUTED, ["slow", "late"])
        self.assertEqual(report.nodes["late"].status, "ok")

    def test_stop_on_ng_enabled_stops_later_nodes(self):
        graph = {"nodes": [n("ng", "_limit_ng"), n("late", "_limit_mark")], "edges": []}
        report = run_graph(graph, stop_on_ng=True)

        self.assertEqual(report.status, "ng")
        self.assertEqual(EXECUTED, ["ng"])
        self.assertEqual(report.nodes["late"].status, "skipped")
        self.assertTrue(any("Stopped after NG" in warning for warning in report.warnings))

    def test_stop_on_ng_disabled_continues(self):
        graph = {"nodes": [n("ng", "_limit_ng"), n("late", "_limit_mark")], "edges": []}
        report = run_graph(graph, stop_on_ng=False)

        self.assertEqual(report.status, "ng")
        self.assertEqual(EXECUTED, ["ng", "late"])
        self.assertEqual(report.nodes["late"].status, "ok")

    def test_stop_on_ng_also_stops_ng_branch(self):
        graph = {"nodes": [n("branch", "_limit_branch"), n("late", "_limit_mark")], "edges": []}
        report = run_graph(graph, stop_on_ng=True)

        self.assertEqual(report.status, "ng")
        self.assertEqual(EXECUTED, ["branch"])
        self.assertEqual(report.nodes["late"].status, "skipped")
        self.assertTrue(any("Stopped after NG" in warning for warning in report.warnings))

    def test_patch_flow_limits_and_operator_is_blocked(self):
        admin = User.objects.create_user("admin", password="x", is_staff=True)
        operator = User.objects.create_user("op", password="x")
        UserPref.objects.create(user=operator, role="operator")
        admin_auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(admin)}"}
        op_auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(operator)}"}
        flow = Flow.objects.create(name="api-limits", graph={"nodes": [], "edges": []})

        response = self.client.patch(
            f"/api/vision/flows/{flow.id}",
            data=json.dumps({"timeout_s": 12, "stop_on_ng": True}),
            content_type="application/json",
            **admin_auth,
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["timeout_s"], 12)
        self.assertIs(body["stop_on_ng"], True)
        flow.refresh_from_db()
        self.assertEqual(flow.timeout_s, 12)
        self.assertIs(flow.stop_on_ng, True)

        response = self.client.patch(
            f"/api/vision/flows/{flow.id}",
            data=json.dumps({"timeout_s": 3}),
            content_type="application/json",
            **op_auth,
        )
        self.assertEqual(response.status_code, 403, response.content)
