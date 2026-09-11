"""跨流程配對、並行、沙箱隔離與管理權限的回歸測試。"""

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, TestCase

from apps.core.models import AuditLog
from apps.vision import engine, images, queues
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.models import Flow
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool


def node(nid, kind, **params):
    publish = params.pop("_publish", None)
    out = {"id": nid, "type": kind, "params": params}
    if publish is not None:
        out["interface"] = {"outputs": [{"key": k, "alias": v} for k, v in publish.items()]}
    return out


def edge(source, target, sh, th):
    return {"source": source, "target": target, "source_handle": sh, "target_handle": th}


def run(graph, *, flow_id=1, preview=False, context=None, image=None):
    return engine.execute(compile_graph(validate_graph(graph)), flow_id=flow_id, flow_version=1,
                          trigger="test", grab=lambda _: image, asset_path=lambda _: None,
                          initial_context=context, preview=preview, input_image=image)


class QueueTests(SimpleTestCase):
    def setUp(self):
        self.store = queues.QueueStore()
        self.replace = patch.object(queues, "store", self.store)
        self.replace.start()
        self.addCleanup(self.replace.stop)

    def test_order_key_peek_and_copies(self):
        values = {"height": [1]}
        for key in ("a", "b", "a"):
            self.store.push("parts", values, key=key)
        values["height"][0] = 9
        peek, _ = self.store.pop("parts", match="key", key="a", remove=False)
        self.assertEqual(peek["seq"], 1)
        peek["values"]["height"][0] = 8
        self.assertEqual(self.store.pop("parts", match="lifo")[0]["seq"], 3)
        first, _ = self.store.pop("parts")
        self.assertEqual((first["seq"], first["values"]), (1, {"height": [1]}))
        self.assertIsNone(self.store.pop("parts", match="key", key="missing")[0])
        self.assertEqual(self.store.pop("parts")[0]["key"], "b")

    def test_capacity_drop_reject_and_sequence(self):
        for i in range(3):
            result = self.store.push("parts", {"i": i}, max_items=2)
        self.assertEqual(result, {"seq": 3, "size": 2, "dropped": 1, "accepted": True})
        rejected = self.store.push("parts", {}, max_items=2, on_full="reject")
        self.assertFalse(rejected["accepted"])
        self.assertEqual(self.store.pop("parts")[0]["values"], {"i": 1})
        self.store.clear("parts")
        self.assertEqual(self.store.push("parts", {})["seq"], 4)

    def test_ttl_and_snapshot_do_not_expire_source_on_fork(self):
        with patch.object(queues.time, "monotonic", return_value=10):
            self.store.push("parts", {}, ttl_s=1)
            self.store.push("parts", {"alive": True})
        with patch.object(queues.time, "monotonic", return_value=12):
            before = copy.deepcopy(self.store._queues)
            overlay = self.store.fork()
            self.assertEqual(overlay.snapshot()[0]["dropped"], 1)
            self.assertEqual(self.store._queues, before)
            self.assertEqual(self.store.pop("parts")[0]["values"], {"alive": True})
            self.assertEqual(self.store.snapshot()[0]["dropped"], 1)

    def test_wait_wakes_for_matching_push_and_clear_keeps_waiter(self):
        waiting = threading.Event()
        original_wait = self.store.condition.wait

        def wait(timeout):
            waiting.set()
            return original_wait(timeout)

        with patch.object(self.store.condition, "wait", side_effect=wait), ThreadPoolExecutor(1) as pool:
            started = time.perf_counter()
            future = pool.submit(self.store.pop, "parts", match="key", key="wanted", wait_ms=2000)
            self.assertTrue(waiting.wait(1))
            self.store.push("parts", {}, key="other")
            self.store.clear("parts")
            self.store.push("parts", {"height": 7}, key="wanted")
            item, _ = future.result(timeout=1)
            self.assertEqual(item["values"], {"height": 7})
            elapsed = (time.perf_counter() - started) * 1000
            self.assertLess(elapsed, 1000)
            print(f"Queue matching waiter woke in {elapsed:.3f} ms")
        start = time.monotonic()
        self.assertIsNone(self.store.pop("empty", wait_ms=30)[0])
        self.assertGreaterEqual(time.monotonic() - start, .025)

    def test_eight_producers_no_loss_or_duplicate(self):
        barrier = threading.Barrier(8)

        def produce(worker):
            barrier.wait()
            return [self.store.push("parts", {"worker": worker, "i": i}, key=f"{worker}:{i}",
                                    max_items=1024, on_full="reject")["seq"] for i in range(100)]

        with ThreadPoolExecutor(8) as pool:
            seqs = sum(list(pool.map(produce, range(8))), [])
        items = [self.store.pop("parts")[0] for _ in range(800)]
        self.assertEqual(set(seqs), set(range(1, 801)))
        self.assertEqual(len({item["key"] for item in items}), 800)
        self.assertEqual(self.store.snapshot()[0]["dropped"], 0)
        print("Queue concurrency: 8 x 100 = 800 items; 800 unique sequences and keys; 0 lost, 0 dropped")

    def test_sandbox_both_directions_and_image_storage(self):
        self.store.push("parts", {"value": 11}, key="production")
        graph = {"nodes": [node("pop", "queue_pop", queue="parts", publish=True),
                           node("push", "queue_push", queue="parts", key="preview", values="value=a")],
                 "edges": [edge("pop", "push", "seq", "a")]}
        before = copy.deepcopy(self.store._queues)
        for flow_id, preview, context in ((1, True, {}), (0, False, {}), (-2, False, {}), (1, False, {"_sandbox": True})):
            result = run(graph, flow_id=flow_id, preview=preview, context=context)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.outputs["value"], 11)
            self.assertEqual(self.store._queues, before)
        self.assertIsNone(self.store.pop("parts", match="key", key="preview")[0])
        context = {}
        with patch.object(images.store, "put", side_effect=AssertionError("Sandbox image escaped")):
            run_tool("queue_push", np.zeros((97, 333), np.uint8), {"key": "local"}, context=context)
            local = run_tool("queue_pop", params={"match": "key", "key": "local"}, context=context)
            self.assertEqual(local.outputs["image"].shape, (97, 333))
        self.assertEqual(self.store._queues, before)

    def test_mapping_templates_missing_and_invalid_data(self):
        ctx = {"serial": 5, "height": 12, "_outputs": {"prior": 8}}
        run_tool("queue_push", params={"key": "{serial:03d}", "values": "h=height\np=prior\nx=a"}, inputs={"a": 7}, context=ctx)
        result = run_tool("queue_pop", params={"match": "key", "key": "005", "publish": True}, context=ctx)
        self.assertEqual(result.outputs["values"], {"h": 12, "p": 8, "x": 7})
        self.assertEqual(result.context["_outputs"]["h"], 12)
        for params in ({"key": "{missing}"}, {"values": "h=missing"}, {"values": "bad"}, {"values": "h=a\nh=a"}):
            with self.subTest(params=params), self.assertRaises(ToolError):
                run_tool("queue_push", params=params, inputs={"a": 1})
        for data in ([1], {"a": np.zeros((1, 1))}, {"a": [np.zeros((1,))]}, {"a": "x" * 65536}, {"a": float("nan")}):
            with self.subTest(data_type=type(data)), self.assertRaises(ToolError):
                run_tool("queue_push", inputs={"data": data})
        self.assertEqual(queues.normalize({"v": np.int64(3)}), {"v": 3})
        with self.assertRaises(ToolError):
            run_tool("queue_push", params={"values": "v=a"}, inputs={"a": np.zeros((2, 2))})
        with self.assertRaises(ToolError):
            run_tool("queue_push", params={"max_items": 1.2})
        for name in ("1bad", "bad\n", "a" * 65):
            with self.assertRaises(queues.QueueError):
                self.store.push(name, {})

    def test_tool_full_missing_branch_and_expired_image_warning(self):
        ctx = {}
        for _ in range(2):
            result = run_tool("queue_push", params={"max_items": 1, "on_full": "reject"}, context=ctx)
        self.assertEqual((result.status, result.branch), ("ng", "full"))
        empty = run_tool("queue_pop", params={"match": "key", "key": "missing"}, context=ctx)
        self.assertEqual(empty.branch, "not_found")
        self.assertEqual(empty.outputs["image"], None)
        self.store.push("images", {}, image_ref="expired")
        graph = {"nodes": [node("pop", "queue_pop", queue="images")], "edges": []}
        result = run(graph)
        self.assertEqual(result.nodes["pop"].logs[0]["level"], "warning")
        self.assertTrue(result.nodes["pop"].detail["warnings"])


class QueueIntegrationTests(TestCase):
    def setUp(self):
        self.replace = patch.object(queues, "store", queues.QueueStore())
        self.replace.start()
        self.addCleanup(self.replace.stop)

    def test_two_flows_five_parts_true_engine_and_no_database(self):
        graph_a = {"nodes": [node("src", "image_source"), node("push", "queue_push", queue="parts", key="{serial}", values="height=height")],
                   "edges": [edge("src", "push", "image", "image")]}
        graph_b = {"nodes": [node("pop", "queue_pop", queue="parts", match="key", key="{serial}"),
                             node("calc", "formula", expression="a['height'] + b", _publish={"value": "combined"}),
                             node("check", "in_range", low=20, high=24)],
                   "edges": [edge("pop", "calc", "values", "a"), edge("pop", "calc", "matched", "_flow"),
                             edge("second", "calc", "mean", "b")]}
        # 第二工位真的取用交接影像量測，不依賴未消費輸出埠的快取。
        graph_b["nodes"].insert(1, node("second", "intensity"))
        graph_b["edges"].append(edge("pop", "second", "image", "image"))
        graph_b["edges"].append(edge("calc", "check", "value", "value"))
        a = Flow.objects.create(name="Station A", graph=validate_graph(graph_a))
        b = Flow.objects.create(name="Station B", graph=validate_graph(graph_b))
        image = np.full((97, 333), 10, np.uint8)
        try:
            with self.assertNumQueries(0):
                for i in range(5):
                    report = run(a.graph, flow_id=a.id, context={"serial": str(i), "height": 10 + i}, image=image)
                    self.assertEqual(report.status, "ok", report.error)
                results = []
                for i in (3, 1, 4, 0, 2):
                    report = run(b.graph, flow_id=b.id, context={"serial": str(i)})
                    self.assertEqual(report.status, "ok", report.error)
                    self.assertEqual(report.outputs["combined"], 20 + i)
                    self.assertEqual(report.nodes["pop"].detail["flow_id"], a.id)
                    ref = report.nodes["pop"].outputs["image"]["ref"]
                    np.testing.assert_array_equal(images.store.get(ref), image)
                    results.append(report.outputs["combined"])
                self.assertEqual(queues.store.snapshot()[0]["size"], 0)
            print(f"Two real flows: A pushed 5; B matched keys 3,1,4,0,2; combined={results}; database queries=0")
        finally:
            for item in list(images.store._runs_by_flow.get(a.id, [])):
                images.store.drop_run(item)

    def test_api_list_clear_audit_and_permissions(self):
        queues.store.push("parts", {"a": 1})
        response = self.client.get("/api/vision/queues")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["size"], 1)
        response = self.client.delete("/api/vision/queues/parts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["removed"], 1)
        self.assertTrue(AuditLog.objects.filter(action="queue.clear", target_id="parts").exists())
        self.assertEqual(self.client.delete("/api/vision/queues/1bad").status_code, 422)
        with patch("apps.accounts.security.Principal.can", return_value=False):
            self.assertEqual(self.client.get("/api/vision/queues").status_code, 403)
            self.assertEqual(self.client.delete("/api/vision/queues/parts").status_code, 403)
        with patch("apps.accounts.security.Principal.can", side_effect=lambda feature: feature == "flows.edit"):
            self.assertEqual(self.client.delete("/api/vision/queues/parts").status_code, 200)
