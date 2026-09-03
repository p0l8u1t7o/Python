"""AI 助手評測基準的門檻測試：規則引擎在全部案例上的意圖／判定準確率不得退步。

門檻寫成常數；能力提升後往上調。失敗訊息列出未通過的案例 key，方便定位。
"""

from __future__ import annotations

from django.test import TestCase

from apps.vision.agent import bench

INTENT_ACC_MIN = 0.9
STATUS_ACC_MIN = 0.8


class AgentBenchTests(TestCase):
    def test_rule_engine_meets_thresholds(self):
        out = bench.run_bench(use_llm=False)
        s = out["summary"]
        detail = {r["key"]: {"intent": r.get("intent"), "statuses": r.get("statuses"), "expected": r.get("expected"), "error": r.get("error"), "error_nodes": r.get("error_nodes")}
                  for r in out["cases"] if r["key"] in s["failed"]}
        self.assertEqual(s["valid_rate"], 1.0, f"有案例出現 error 節點或例外：{detail}")
        self.assertGreaterEqual(s["intent_acc"], INTENT_ACC_MIN, f"意圖準確率 {s['intent_acc']}：{detail}")
        self.assertGreaterEqual(s["status_acc"], STATUS_ACC_MIN, f"判定準確率 {s['status_acc']}：{detail}")

    def test_case_keys_unique_and_expectations_shaped(self):
        keys = [c.key for c in bench.CASES]
        self.assertEqual(len(keys), len(set(keys)))
        for c in bench.CASES:
            self.assertTrue(all(s in ("ok", "ng", "any") for s in c.expect_status), c.key)
