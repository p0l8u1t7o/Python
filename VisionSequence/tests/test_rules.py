"""觸發規則表的動作與站台接收規則（apps/comm/rules.py）。

比對本身是純函式，測在 `tests/test_comm.py`；這裡測「真的動手」的部分：跑流程、換配方、
寫變數、鎖引擎，以及 TCP 指令埠收到「不是指令」的一行時走規則表。
"""

from __future__ import annotations

import json

from django.conf import settings
from django.test import TestCase, TransactionTestCase, override_settings

from apps.accounts.models import EngineLock
from apps.comm import rules
from apps.comm.models import StationRules
from apps.vision import variables
from apps.vision.models import Flow, FlowRecipe, ImageSource
from apps.vision.tcp_server import Session

GRAPH = {
    "nodes": [
        {"id": "src", "type": "image_source", "params": {}},
        {"id": "i", "type": "intensity", "params": {}},
        {"id": "j", "type": "judge", "params": {"verdict": "ok"}},
    ],
    "edges": [{"source": "src", "target": "i"}],
}


def _rule(**kw) -> rules.Rule:
    return rules.parse([kw])[0]


class RuleActionTests(TestCase):
    """不跑流程的三種動作：換配方、寫變數、鎖定。"""

    def setUp(self):
        self.flow = Flow.objects.create(name="檢測", graph=GRAPH)
        self.addCleanup(variables.store.clear)

    def test_activate_recipe_changes_the_default(self):
        a = FlowRecipe.objects.create(flow=self.flow, name="A 料號", is_default=True)
        b = FlowRecipe.objects.create(flow=self.flow, name="B 料號")
        out = rules.fire(_rule(address="hr:1", action="activate_recipe", flow="檢測", recipe="B 料號"))
        self.assertTrue(out["ok"])
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((a.is_default, b.is_default), (False, True))
        with self.assertRaisesMessage(LookupError, "does not exist"):
            rules.fire(_rule(address="hr:1", action="activate_recipe", flow="檢測", recipe="沒這個配方"))

    def test_set_variable_in_both_scopes_and_from_the_captured_text(self):
        rules.fire(_rule(address="hr:2", action="set_variable", flow="檢測", variable="parts", set_value="0"))
        self.assertEqual(variables.store.get(self.flow.id, "parts"), 0)
        rules.fire(_rule(address="hr:3", action="set_variable", scope="station", variable="shift", set_value="night"))
        self.assertEqual(variables.store.get(None, "shift"), "night")
        # set_value 可以取觸發帶進來的引數：文字規則抓到的料號直接存成變數
        rules.fire(_rule(source="text", pattern="x", action="set_variable", flow="檢測", variable="lot", set_value="{lot}"),
                   {"lot": "A17"})
        self.assertEqual(variables.store.get(self.flow.id, "lot"), "A17")

    def test_lock_and_unlock(self):
        rules.fire(_rule(address="coil:9", action="lock", reason="維修", ttl=600))
        lock = EngineLock.current()
        self.assertTrue(lock.locked)
        self.assertEqual((lock.holder, lock.reason), ("integrator", "維修"))
        self.assertIsNotNone(lock.expires_at)
        rules.fire(_rule(address="coil:8", action="unlock"))
        self.assertFalse(EngineLock.current().locked)

    def test_a_disabled_flow_is_a_lookup_error_not_a_crash(self):
        Flow.objects.filter(pk=self.flow.pk).update(is_enabled=False)
        with self.assertRaisesMessage(LookupError, "does not exist or is disabled"):
            rules.fire(_rule(address="coil:0", action="run_flow", flow="檢測"))


class StationRuleStorageTests(TestCase):
    """站台接收規則存在單列上，讀進記憶體快取（指令埠每一行都要比對）。"""

    def setUp(self):
        self.addCleanup(rules.invalidate)

    def test_only_text_rules_are_kept_and_the_cache_refreshes(self):
        self.assertEqual(rules.station_rules(), [])
        saved = rules.save_station_rules([
            {"source": "text", "match": "prefix", "pattern": "SCAN ", "capture": "lot", "action": "run_flow", "flow": "檢測"},
            {"source": "value", "address": "coil:0", "action": "unlock"},  # 指令埠沒有位址可以讀
            {"source": "text", "pattern": "STOP", "action": "lock", "enabled": False},
        ])
        self.assertEqual([r["pattern"] for r in saved], ["SCAN ", "STOP"])
        live = rules.station_rules()
        self.assertEqual([r.pattern for r in live], ["SCAN "])  # 停用的不進快取
        self.assertEqual(StationRules.objects.get(pk=1).rules, saved)
        rules.save_station_rules([])
        self.assertEqual(rules.station_rules(), [])

    def test_the_api_reads_and_writes_the_table(self):
        r = self.client.get("/api/vision/integration/rules")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["items"], [])
        body = {"rules": [{"source": "text", "pattern": "GO", "action": "lock"}, {"source": "text", "action": "lock"}]}
        r = self.client.patch("/api/vision/integration/rules", data=json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        items = r.json()["items"]
        self.assertEqual(len(items), 1)  # 沒有樣式的那一列丟掉
        self.assertEqual((items[0]["pattern"], items[0]["id"]), ("GO", "r1"))
        self.assertEqual(self.client.get("/api/vision/integration/rules").json()["items"], items)


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class StationRuleOverTcpTests(TransactionTestCase):
    """條碼槍把一行料號送進 TCP 埠：不是指令，但規則表認得它。跨執行緒跑 run 用 TransactionTestCase。"""

    def setUp(self):
        source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        graph = {**GRAPH, "nodes": [{**n, "params": {"source_id": source.id}} if n["id"] == "src" else n for n in GRAPH["nodes"]]}
        self.flow = Flow.objects.create(name="檢測", graph=graph)
        self.addCleanup(rules.invalidate)
        self.addCleanup(variables.store.clear)

    def test_a_scanned_line_runs_the_flow_and_answers_plain_text(self):
        rules.save_station_rules([{
            "source": "text", "match": "prefix", "pattern": "SCAN ", "capture": "lot",
            "action": "run_flow", "flow": "檢測", "reply": "{judge},{lot}" + chr(92) + "r" + chr(92) + "n",
        }])
        response, _ = Session(secret="").command("SCAN A17")
        self.assertIn("_raw", response, response)
        self.assertEqual(response["_raw"], "OK,A17\r\n")

    def test_without_a_reply_the_answer_says_what_happened(self):
        rules.save_station_rules([{"source": "text", "match": "contains", "pattern": "GO", "action": "run_flow", "flow": "檢測"}])
        response, _ = Session(secret="").command("PLEASE GO NOW")
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["status"], "ok")
        self.assertTrue(response["run_id"])

    def test_lines_nothing_matches_still_say_unknown_command(self):
        rules.save_station_rules([{"source": "text", "match": "exact", "pattern": "GO", "action": "lock"}])
        response, _ = Session(secret="").command("WOBBLE")
        self.assertEqual(response["code"], "unknown_command")

    def test_a_rule_that_points_at_nothing_says_so(self):
        rules.save_station_rules([{"source": "text", "pattern": "GO", "action": "run_flow", "flow": "沒這個流程"}])
        response, _ = Session(secret="").command("GO")
        self.assertEqual(response["code"], "rule_failed")
        self.assertIn("does not exist", response["error"])

    def test_rules_do_not_run_before_the_key(self):
        rules.save_station_rules([{"source": "text", "pattern": "GO", "action": "run_flow", "flow": "檢測"}])
        response, _ = Session(secret="s3cret").command("GO")
        self.assertEqual(response["code"], "unauthorized")

    def test_a_real_command_still_wins(self):
        rules.save_station_rules([{"source": "text", "match": "contains", "pattern": "PING", "action": "lock"}])
        response, _ = Session(secret="").command("PING")
        self.assertTrue(response["pong"])
        self.assertFalse(EngineLock.current().locked)
