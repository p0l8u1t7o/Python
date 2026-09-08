"""流程結果回送（apps/vision/reporting.py）：跑完就把結果送給上位機，不必在圖裡接線。

PLC 客戶的第一個問題是「結果怎麼回來」。這裡測的是宣告式的那條路：
流程設定裡選一條連線、寫 OK 與 NG 各要送什麼，跑完就送出去。
"""

from __future__ import annotations

import json
import time

from django.conf import settings
from django.test import TestCase, TransactionTestCase, override_settings

from apps.comm import writers
from apps.vision import reporting
from apps.vision.engine import NodeReport, RunReport
from apps.vision.models import Flow, ImageSource
from apps.vision.runner import runner
from tests.fakes import MEMORY_KIND, MemoryWriter, register_memory_kind


def _report(**kw) -> RunReport:
    base = {
        "id": "run1", "flow_id": 1, "flow_version": 1, "trigger": "api", "status": "ok",
        "duration_ms": 12.345, "outputs": {"judge": "OK", "width": 12.3456}, "context": {"lot": "A17"},
        "station_id": "ST09",
    }
    return RunReport(**{**base, **kw})


class RuleTableTests(TestCase):
    """設定的解析（純函式）。"""

    def test_a_rule_needs_a_connection_and_something_to_say(self):
        self.assertEqual(reporting.sanitize("不是清單"), [])
        self.assertEqual(reporting.sanitize([{"ok": "hi"}]), [])            # 沒有連線
        self.assertEqual(reporting.sanitize([{"connection": "host"}]), [])  # 三種樣板都空
        rules = reporting.sanitize([{"connection": " host ", "ok": "OK,{width:.2f}"}])
        self.assertEqual(len(rules), 1)
        self.assertEqual((rules[0]["connection"], rules[0]["id"], rules[0]["when"]), ("host", "c1", "on_finish"))
        self.assertEqual(len(reporting.sanitize([{"connection": "h", "ok": "x"}] * 30)), reporting.MAX_RULES)

    def test_defaults_and_clamps(self):
        rule = reporting.parse([{"connection": "host", "ok": "x", "when": "INTERVAL", "interval_ms": 5, "node_status": "nope"}])[0]
        self.assertEqual((rule.when, rule.interval_ms, rule.node_status), ("interval", reporting.MIN_INTERVAL_MS, "any"))
        self.assertEqual(reporting.parse([{"connection": "h", "ok": "x", "when": "nope"}])[0].when, "on_finish")
        self.assertEqual(reporting.parse([{"connection": "h", "ok": "x", "enabled": False}]), [])

    def test_which_template_a_result_uses(self):
        rule = reporting.parse([{"connection": "h", "ok": "A", "ng": "B", "failed": "C"}])[0]
        self.assertEqual((rule.template_for("ok"), rule.template_for("ng"), rule.template_for("failed")), ("A", "B", "C"))
        only_ng = reporting.parse([{"connection": "h", "ng": "B"}])[0]
        self.assertFalse(reporting.wanted(only_ng, _report(status="ok")))   # OK 沒有樣板就不送
        self.assertTrue(reporting.wanted(only_ng, _report(status="ng")))

    def test_a_condition_watches_one_step(self):
        rule = reporting.parse([{"connection": "h", "ok": "A", "node": "blob-1", "node_status": "ng"}])[0]
        report = _report(nodes={"blob-1": NodeReport(status="ng")})
        self.assertTrue(reporting.wanted(rule, report))
        self.assertFalse(reporting.wanted(rule, _report(nodes={"blob-1": NodeReport(status="ok")})))
        self.assertFalse(reporting.wanted(rule, _report()))  # 圖裡沒有那一步就不送

    def test_the_names_a_template_can_use(self):
        values = reporting.values_for(_report(), "檢測")
        self.assertEqual(values["judge"], "OK")
        self.assertEqual(values["lot"], "A17")            # 觸發帶進來的引數
        self.assertEqual(values["width"], 12.3456)        # 具名輸出
        self.assertEqual((values["flow"], values["station"], values["run_id"]), ("檢測", "ST09", "run1"))
        self.assertEqual(values["duration_ms"], 12.35)
        # 判定沒有具名輸出時用執行狀態
        self.assertEqual(reporting.values_for(_report(status="ng", outputs={}))["judge"], "NG")


class DeliveryTests(TestCase):
    """真的送出去（用記憶體假設備，不碰網路）。"""

    def setUp(self):
        register_memory_kind()
        self.writer = MemoryWriter({}, name="host")
        writers.register_writer("host", self.writer)
        self.addCleanup(reporting.forget, 1)
        self.addCleanup(reporting.stop_ticker)

    def test_on_finish_sends_one_line_per_part(self):
        reporting.set_rules(1, [{"connection": "host", "ok": "OK,{width:.2f},{lot}", "ng": "NG,{lot}"}], "檢測")
        self.assertEqual(reporting.deliver(_report()), 1)
        self.assertEqual(self.writer.lines, ["OK,12.35,A17"])
        reporting.deliver(_report(status="ng"))
        self.assertEqual(self.writer.lines[1], "NG,A17")
        reporting.deliver(_report(status="failed"))  # 沒有 failed 樣板就不送
        self.assertEqual(len(self.writer.lines), 2)

    def test_line_endings_are_written_the_way_the_protocol_needs_them(self):
        reporting.set_rules(1, [{"connection": "host", "ok": "OK" + chr(92) + "r" + chr(92) + "n"}])
        reporting.deliver(_report())
        self.assertEqual(self.writer.lines, ["OK\r\n"])

    def test_a_host_that_is_not_there_does_not_stop_the_line(self):
        reporting.set_rules(1, [{"connection": "沒這條連線", "ok": "OK"}])
        self.assertEqual(reporting.deliver(_report()), 1)  # 不丟例外
        state = reporting.status(1)[0]
        self.assertEqual(state["errors"], 1)
        self.assertIn("not open", state["last_error"])
        # 退避：接下來幾片不再每片都試（不然每片都要等連線逾時，節拍會垮）
        reporting.deliver(_report())
        self.assertEqual(reporting.status(1)[0]["errors"], 1)

    def test_a_modbus_connection_is_told_to_use_the_write_step(self):
        plain = MemoryWriter({}, name="plc")
        plain.texts = False
        writers.register_writer("plc", plain)
        reporting.set_rules(1, [{"connection": "plc", "ok": "OK"}])
        reporting.deliver(_report())
        self.assertIn("Write Modbus", reporting.status(1)[0]["last_error"])

    def test_interval_sends_the_latest_result_on_a_beat(self):
        reporting.set_rules(1, [{"connection": "host", "when": "interval", "interval_ms": 200, "ok": "TICK,{width:.1f}"}], "檢測")
        reporting.stop_ticker()  # 這個測試自己驅動節拍（此時還沒有結果，背景計時器送不出東西）
        self.assertEqual(reporting.deliver(_report()), 0)  # 逐片不送，只記下來
        self.assertEqual(self.writer.lines, [])
        self.assertEqual(reporting.tick(), 1)
        self.assertEqual(self.writer.lines, ["TICK,12.3"])
        self.assertEqual(reporting.tick(), 0)  # 還沒到下一拍
        time.sleep(0.22)
        self.assertEqual(reporting.tick(), 1)

    def test_nothing_is_sent_before_the_first_run(self):
        reporting.set_rules(1, [{"connection": "host", "when": "interval", "ok": "TICK"}])
        self.assertEqual(reporting.tick(), 0)
        self.assertEqual(self.writer.lines, [])


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class EndToEndTests(TransactionTestCase):
    """流程真的跑一次，結果就出現在上位機那一端。跨執行緒跑 run 用 TransactionTestCase。"""

    def setUp(self):
        register_memory_kind()
        self.writer = MemoryWriter({}, name="host")
        writers.register_writer("host", self.writer)
        source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": source.id}},
                {"id": "i", "type": "intensity", "params": {}},
                {"id": "j", "type": "judge", "params": {"verdict": "ok"}},
            ],
            "edges": [{"source": "src", "target": "i"}],
        }
        self.flow = Flow.objects.create(name="回送", graph=graph,
                                        comm=[{"connection": "host", "ok": "{judge};{lot};{flow}"}])
        runner.forget(self.flow.id)
        self.addCleanup(runner.forget, self.flow.id)
        self.addCleanup(reporting.stop_ticker)

    def test_a_run_reaches_the_host(self):
        runner.run_sync(self.flow, trigger="api", context={"lot": "B7"})
        self.assertEqual(self.writer.lines, ["OK;B7;回送"])

    def test_a_preview_does_not(self):
        """試執行是工程師在調參，不該讓上位機以為又檢測了一片。"""
        runner.run_sync(self.flow, trigger="preview")
        self.assertEqual(self.writer.lines, [])

    def test_the_settings_are_reachable_over_the_api(self):
        body = {"comm": [{"connection": "host", "ok": "A", "junk": 1}, {"ok": "沒有連線"}]}
        r = self.client.patch(f"/api/vision/flows/{self.flow.id}", data=json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        saved = r.json()["comm"]
        self.assertEqual(len(saved), 1)  # 壞掉的那一列丟掉
        self.assertEqual((saved[0]["connection"], saved[0]["ok"]), ("host", "A"))
        self.assertNotIn("junk", saved[0])
        self.assertEqual(self.client.get(f"/api/vision/flows/{self.flow.id}").json()["comm"], saved)

    def test_the_kind_is_registered_for_the_form(self):
        self.assertIn(MEMORY_KIND, [k["kind"] for k in writers.kinds()])
