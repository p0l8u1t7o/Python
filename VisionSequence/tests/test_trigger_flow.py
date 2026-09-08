"""trigger_flow 與流程並行度。"""

from __future__ import annotations

import json
import time
from unittest import mock

from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.vision import engine
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.models import Flow
from apps.vision.runner import runner
from apps.vision.tools.base import Port, Result, Tool, register, unregister


def n(nid: str, ntype: str, **params):
    return {"id": nid, "type": ntype, "params": params}


class GateTool(Tool):
    key = "_test_trigger_gate"
    label = "gate"
    category = "logic"
    inputs = []
    outputs = [Port("value", "Value", "number")]
    allows_unconnected = True
    started = 0
    finished = 0
    current = 0
    max_seen = 0
    start_times: list[float] = []

    @classmethod
    def reset(cls) -> None:
        import threading

        cls.started = 0
        cls.finished = 0
        cls.current = 0
        cls.max_seen = 0
        cls.start_times = []
        cls.release = threading.Event()
        cls.cond = threading.Condition()

    def execute(self, ctx):
        with type(self).cond:
            type(self).started += 1
            type(self).current += 1
            type(self).max_seen = max(type(self).max_seen, type(self).current)
            type(self).start_times.append(time.perf_counter())
            type(self).cond.notify_all()
        type(self).release.wait(5)
        with type(self).cond:
            type(self).current -= 1
            type(self).finished += 1
            type(self).cond.notify_all()
        return Result(outputs={"value": 1})


GateTool.reset()


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False, "MAX_WORKERS": 6})
class TriggerFlowTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register(GateTool())

    @classmethod
    def tearDownClass(cls):
        unregister(GateTool.key)
        super().tearDownClass()

    def setUp(self):
        GateTool.reset()
        for fid in list(runner._runtimes):
            runner.forget(fid)

    def tearDown(self):
        GateTool.release.set()
        for fid in list(runner._runtimes):
            runner.forget(fid)

    def flow(self, name: str, graph: dict, **fields) -> Flow:
        return Flow.objects.create(name=name, graph=validate_graph(graph), **fields)

    def wait_started(self, count: int, timeout: float = 3.0) -> None:
        deadline = time.perf_counter() + timeout
        with GateTool.cond:
            while GateTool.started < count and time.perf_counter() < deadline:
                GateTool.cond.wait(0.05)
        self.assertGreaterEqual(GateTool.started, count)

    def wait_run(self, run_id: str) -> dict:
        body = {}
        for _ in range(80):
            body = self.client.get(f"/api/vision/runs/{run_id}").json()
            if not body.get("pending"):
                return body
            time.sleep(0.05)
        self.fail(f"run {run_id} did not finish: {body}")

    def test_async_returns_run_id_and_get_run_can_fetch_it(self):
        child = self.flow("child-async", {"nodes": [n("j", "judge", verdict="ok")], "edges": []})
        parent = self.flow("parent-async", {"nodes": [n("t", "trigger_flow", target_flow_id=child.id, mode="async")], "edges": []})

        report = runner.run_sync(parent, trigger="api")

        run_id = report.nodes["t"].outputs["run_id"]
        self.assertTrue(run_id)
        body = self.wait_run(run_id)
        self.assertEqual((body["id"], body["flow_id"], body["status"]), (run_id, child.id, "ok"))

    def test_flow_api_accepts_and_copies_concurrency(self):
        body = {"name": "api-concurrency", "graph": {"nodes": [], "edges": []}, "concurrency": 3}
        res = self.client.post("/api/vision/flows", data=json.dumps(body), content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        flow_id = res.json()["id"]
        self.assertEqual(res.json()["concurrency"], 3)

        res = self.client.patch(f"/api/vision/flows/{flow_id}", data=json.dumps({"concurrency": 2}), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["concurrency"], 2)

        copy = self.client.post(f"/api/vision/flows/{flow_id}/duplicate")
        self.assertEqual(copy.status_code, 201, copy.content)
        self.assertEqual(copy.json()["concurrency"], 2)

    def test_sync_returns_child_judge(self):
        child = self.flow("child-sync", {"nodes": [n("j", "judge", verdict="ng")], "edges": []})
        parent = self.flow("parent-sync", {"nodes": [n("t", "trigger_flow", target_flow_id=child.id, mode="sync")], "edges": []})

        report = runner.run_sync(parent, trigger="api")

        self.assertEqual(report.status, "ng")
        self.assertEqual(report.nodes["t"].branch, "ng")
        self.assertEqual(report.nodes["t"].outputs["judge"], "NG")
        self.assertFalse(report.nodes["t"].outputs["ok"])

    def test_self_trigger_is_blocked(self):
        flow = self.flow("self-loop", {"nodes": [], "edges": []})
        flow.graph = validate_graph({"nodes": [n("t", "trigger_flow", target_flow_id=flow.id, mode="sync")], "edges": []})
        flow.save(update_fields=["graph"])

        report = runner.run_sync(flow, trigger="api")

        self.assertEqual(report.status, "failed")
        self.assertIn("cannot trigger itself", report.nodes["t"].message)

    def test_trigger_chain_loop_is_blocked(self):
        a = self.flow("loop-a", {"nodes": [], "edges": []})
        b = self.flow("loop-b", {"nodes": [], "edges": []})
        a.graph = validate_graph({"nodes": [n("to_b", "trigger_flow", target_flow_id=b.id, mode="sync")], "edges": []})
        b.graph = validate_graph({"nodes": [n("to_a", "trigger_flow", target_flow_id=a.id, mode="sync")], "edges": []})
        a.save(update_fields=["graph"])
        b.save(update_fields=["graph"])

        report = runner.run_sync(a, trigger="api")

        self.assertEqual(report.status, "failed")
        self.assertIn("Trigger chain would loop", report.nodes["to_b"].message)

    def test_concurrency_one_keeps_second_run_waiting(self):
        flow = self.flow("serial", {"nodes": [n("g", GateTool.key)], "edges": []}, concurrency=1)
        first = runner.submit(flow)
        second = runner.submit(flow)
        self.wait_started(1)
        time.sleep(0.2)
        self.assertEqual(GateTool.started, 1)
        rt = runner.runtime(flow.id)
        self.assertEqual((rt.running, rt.queued), (1, 1))

        GateTool.release.set()
        self.assertEqual(first.result(timeout=5).status, "ok")
        self.assertEqual(second.result(timeout=5).status, "ok")
        self.assertEqual(GateTool.started, 2)
        self.assertGreaterEqual(GateTool.start_times[1] - GateTool.start_times[0], 0.18)

    def test_concurrency_three_runs_three_at_once(self):
        flow = self.flow("parallel", {"nodes": [n("g", GateTool.key)], "edges": []}, concurrency=3)
        futures = [runner.submit(flow) for _ in range(3)]
        self.wait_started(3)
        self.assertEqual(runner.runtime(flow.id).running, 3)
        self.assertEqual(GateTool.max_seen, 3)

        GateTool.release.set()
        self.assertTrue(all(f.result(timeout=5).status == "ok" for f in futures))

    def test_preview_and_flow_id_zero_do_not_trigger(self):
        graph = validate_graph({"nodes": [n("t", "trigger_flow", target_flow_id=999, mode="async")], "edges": []})
        compiled = compile_graph(graph)
        with mock.patch.object(runner, "submit") as submit:
            preview = engine.execute(compiled, flow_id=1, flow_version=1, trigger="preview", preview=True,
                                     grab=lambda _sid: None, asset_path=lambda _aid: None)
            sandbox = engine.execute(compiled, flow_id=0, flow_version=1, trigger="bench",
                                     grab=lambda _sid: None, asset_path=lambda _aid: None)
        self.assertEqual(preview.nodes["t"].message, "Would trigger flow 999")
        self.assertEqual(sandbox.nodes["t"].message, "Would trigger flow 999")
        submit.assert_not_called()
