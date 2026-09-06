"""WP-14 量測值 SPC：管制界限手算對照、Nelson 法則、規格綁定、persister 寫入 MeasurementLog、保留清理、API、告警、purge／doctor。"""

from __future__ import annotations

import datetime as dt
import io
import json
import math
import time
import uuid

import numpy as np
from django.conf import settings
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.vision import engine, spc
from apps.vision.models import Flow, FlowRun, MeasurementLog
from apps.vision.runner import _Persister


def _graph_with_tolerance(nominal: float = 12.0, upper: float = 0.05, lower: float = -0.05) -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "label": "src", "enabled": True, "params": {}, "position": {"x": 0, "y": 0}},
            {"id": "fc", "type": "find_circle", "label": "fc", "enabled": True, "params": {}, "position": {"x": 200, "y": 0}},
            {"id": "tj", "type": "tolerance_judge", "label": "diameter", "enabled": True, "params": {"nominal": nominal, "upper_tol": upper, "lower_tol": lower, "unit": "mm", "name": "diameter"}, "position": {"x": 400, "y": 0}},
            {"id": "out", "type": "output", "label": "out", "enabled": True, "params": {"name": "diameter"}, "position": {"x": 400, "y": 100}},
            {"id": "out2", "type": "output", "label": "out2", "enabled": True, "params": {"name": "radius"}, "position": {"x": 400, "y": 200}},
        ],
        "edges": [
            {"id": "e1", "source": "src", "target": "fc", "source_handle": "image", "target_handle": "image"},
            {"id": "e2", "source": "fc", "target": "tj", "source_handle": "r", "target_handle": "value"},
            {"id": "e3", "source": "fc", "target": "out", "source_handle": "r", "target_handle": "value"},
            {"id": "e4", "source": "fc", "target": "out2", "source_handle": "r", "target_handle": "value"},
        ],
    }


def _report(flow_id: int, outputs: dict, started: float | None = None) -> engine.RunReport:
    now = started if started is not None else time.time()
    return engine.RunReport(id=uuid.uuid4().hex, flow_id=flow_id, flow_version=1, trigger="api", status="ok", started_at=now, finished_at=now + 0.01, duration_ms=10.0, outputs=outputs)


class SpcMathTests(TestCase):
    def test_imr_limits_hand_calculation(self):
        values = [10.0, 10.2, 9.9, 10.1, 10.0, 10.3, 9.8, 10.1]
        lim = spc.imr_limits(values)
        mr = np.abs(np.diff(values))
        mr_bar = float(mr.mean())
        self.assertAlmostEqual(lim["cl"], float(np.mean(values)))
        self.assertAlmostEqual(lim["ucl"], float(np.mean(values)) + 2.66 * mr_bar)
        self.assertAlmostEqual(lim["lcl"], float(np.mean(values)) - 2.66 * mr_bar)
        self.assertAlmostEqual(lim["mr_ucl"], 3.267 * mr_bar)
        self.assertAlmostEqual(lim["sigma"], mr_bar / 1.128)
        self.assertEqual(lim["moving_range"][0], None)
        self.assertEqual(spc.imr_limits([])["n"], 0)
        self.assertIsNone(spc.imr_limits([5.0])["ucl"])

    def test_xbar_r_limits_hand_calculation(self):
        values = [10, 11, 9, 10, 12, 10, 9, 11, 10, 10]  # n=5 → 兩組：[10,11,9,10,12] x̄=10.4 R=3；[10,9,11,10,10] x̄=10 R=2
        lim = spc.xbar_r_limits(values, 5)
        self.assertEqual(lim["n"], 2)
        self.assertAlmostEqual(lim["cl"], 10.2)
        self.assertAlmostEqual(lim["r_bar"], 2.5)
        self.assertAlmostEqual(lim["ucl"], 10.2 + 0.577 * 2.5)
        self.assertAlmostEqual(lim["lcl"], 10.2 - 0.577 * 2.5)
        self.assertAlmostEqual(lim["r_ucl"], 2.114 * 2.5)
        self.assertAlmostEqual(lim["sigma"], 2.5 / 2.326)
        self.assertEqual(lim["xbar"], [10.4, 10.0])
        self.assertEqual(spc.xbar_r_limits([1.0, 2.0], 5)["n"], 0)

    def test_capability(self):
        values = [12.0, 12.01, 11.99, 12.02, 11.98]
        cap = spc.capability(values, 0.01, 12.05, 11.95)
        self.assertAlmostEqual(cap["cp"], 0.1 / 0.06)
        self.assertAlmostEqual(cap["cpu"], (12.05 - 12.0) / 0.03)
        self.assertAlmostEqual(cap["cpk"], min(cap["cpu"], cap["cpl"]))
        self.assertEqual(cap["out_of_spec"], 0)
        one = spc.capability(values, 0.01, 12.05, None)
        self.assertEqual(one["cpk"], one["cpu"])
        self.assertNotIn("cp", one)
        self.assertEqual(spc.capability(values, None, 12.05, 11.95), {"usl": 12.05, "lsl": 11.95})

    def test_nelson_rules_on_synthetic_sequences(self):
        base = [0.0] * 30
        # 1：一點超出 3σ
        r = spc.nelson(base[:10] + [4.0] + base[:10], 0.0, 1.0)
        self.assertEqual(r[1], [10])
        # 2：連續 9 點同側
        r = spc.nelson([0.5] * 9 + [-0.5] * 3, 0.0, 1.0)
        self.assertEqual(r[2], list(range(9)))
        # 3：連續 6 點單調上升
        r = spc.nelson([0.1 * i for i in range(6)] + [0.0, 0.2], 0.0, 1.0)
        self.assertEqual(r[3], list(range(6)))
        # 4：連續 14 點交替
        r = spc.nelson([(-1) ** i * 0.5 for i in range(14)], 0.0, 1.0)
        self.assertEqual(r[4], list(range(14)))
        # 5：3 點中 2 點超出 2σ 同側
        r = spc.nelson([2.5, 0.0, 2.5], 0.0, 1.0)
        self.assertEqual(r[5], [0, 1, 2])
        # 6：5 點中 4 點超出 1σ 同側
        r = spc.nelson([1.5, 1.5, 0.0, 1.5, 1.5], 0.0, 1.0)
        self.assertEqual(r[6], [0, 1, 2, 3, 4])
        # 7：連續 15 點在 1σ 內
        r = spc.nelson([0.2 * (-1) ** i for i in range(15)], 0.0, 1.0)
        self.assertEqual(r[7], list(range(15)))
        # 8：連續 8 點都在 1σ 外、兩側都有
        r = spc.nelson([1.5, -1.5, 1.5, -1.5, 1.5, -1.5, 1.5, -1.5], 0.0, 1.0)
        self.assertEqual(r[8], list(range(8)))
        # σ 不可用：全部空
        self.assertTrue(all(not v for v in spc.nelson([1.0, 2.0], 0.0, None).values()))

    def test_spec_limits_from_graph(self):
        g = _graph_with_tolerance()
        spec = spc.spec_limits_from_graph(g, "diameter")
        self.assertAlmostEqual(spec["usl"], 12.05)
        self.assertAlmostEqual(spec["lsl"], 11.95)
        self.assertEqual(spec["unit"], "mm")
        # 同來源埠也綁得到（radius 與 tolerance_judge 都吃 fc.r）
        self.assertAlmostEqual(spc.spec_limits_from_graph(g, "radius")["usl"], 12.05)
        self.assertEqual(spc.spec_limits_from_graph(g, "nothing"), {})
        self.assertEqual(spc.spec_limits_from_graph({}, "diameter"), {})

    def test_analyse_and_alerts(self):
        # 固定的乾淨序列（隨機資料本來就會偶爾誤觸判異法則，那是法則的誤報率，不是 bug）
        seq = [0.3, 0.6, -0.4, -0.2, 0.5, 0.1, -0.7, -0.3, 0.2, -0.5, 0.4, -0.1]
        stable = [12 + 0.01 * v for v in seq * 4]
        a = spc.analyse(stable, "imr", 5, 12.05, 11.95)
        self.assertEqual(a["flagged"], [], a["rules"])
        self.assertGreater(a["capability"]["cpk"], 1.0)
        self.assertEqual(spc.alerts_for(stable, 12.05, 11.95), [])
        drift = stable + [12.0 + 0.01 * k for k in range(1, 12)]  # 往上漂：規則 2／3 會亮
        al = spc.alerts_for(drift, 12.05, 11.95)
        self.assertTrue(any(x["rule"] in (2, 3) for x in al), al)
        oos = stable + [12.2, 12.3]
        al = spc.alerts_for(oos, 12.05, 11.95)
        self.assertTrue(any(x["rule"] == 0 for x in al), al)
        xb = spc.analyse(stable, "xbar_r", 4)
        self.assertEqual(xb["limits"]["chart"], "xbar_r")
        self.assertEqual(xb["limits"]["n"], 12)  # 48 點 ÷ 子組 4
        self.assertTrue(spc.is_number(1.5) and not spc.is_number(True) and not spc.is_number("x") and not spc.is_number(math.nan))


class MeasurementLogTests(TestCase):
    def setUp(self) -> None:
        self.flow = Flow.objects.create(name="spc flow", graph=_graph_with_tolerance())
        self.p = _Persister()

    def test_persister_logs_numeric_outputs_only(self):
        batch = [_report(self.flow.id, {"diameter": 12.01, "ok": True, "label": "A", "count": 3, "nan": float("nan")}) for _ in range(3)]
        self.p._write(batch)
        self.assertEqual(FlowRun.objects.count(), 3)
        logs = MeasurementLog.objects.filter(flow=self.flow)
        self.assertEqual(logs.count(), 6)  # diameter ＋ count，每 run 兩列；bool／字串／NaN 不進
        self.assertEqual(set(logs.values_list("name", flat=True)), {"diameter", "count"})
        row = logs.filter(name="diameter").first()
        self.assertEqual(row.value, 12.01)
        self.assertEqual(row.station_id, FlowRun.objects.first().station_id)
        self.assertTrue(FlowRun.objects.filter(id=row.run_id).exists())
        self.assertIsNone(FlowRun.objects.first().outputs["nan"])  # NaN 進資料庫變 null，run 記錄不會因此消失

    def test_measurement_log_can_be_switched_off(self):
        with override_settings(VISION={**settings.VISION, "MEASUREMENT_LOG": False}):
            self.p._write([_report(self.flow.id, {"diameter": 12.0})])
        self.assertEqual(MeasurementLog.objects.count(), 0)
        self.assertEqual(FlowRun.objects.count(), 1)

    def test_retention_prunes_old_measurements(self):
        old = time.time() - 400 * 86400
        with override_settings(VISION={**settings.VISION, "MEASUREMENT_DAYS": 365, "KEEP_RUN_DAYS": 0}):
            self.p._write([_report(self.flow.id, {"diameter": 12.0}, started=old)])
            self.assertEqual(MeasurementLog.objects.count(), 1)
            self.p._prune_counter = 499
            self.p._write([_report(self.flow.id, {"diameter": 12.0})])
        self.assertEqual(MeasurementLog.objects.count(), 1)  # 400 天前的那筆被清掉
        self.assertTrue(MeasurementLog.objects.filter(ts__gte=timezone.now() - dt.timedelta(days=1)).exists())
        # purge --dry-run 會報、真跑會刪；doctor 有一行 measurements
        with override_settings(VISION={**settings.VISION, "MEASUREMENT_DAYS": 365, "KEEP_RUN_DAYS": 0}):
            self.p._write([_report(self.flow.id, {"diameter": 12.0}, started=old)])
            out = io.StringIO()
            call_command("purge", "--dry-run", stdout=out)
            self.assertIn("measurements older than 365d: 1", out.getvalue())
            self.assertEqual(MeasurementLog.objects.count(), 2)
            out = io.StringIO()
            call_command("purge", stdout=out)
            self.assertEqual(MeasurementLog.objects.count(), 1)
        out = io.StringIO()
        try:
            call_command("doctor", stdout=out)
        except SystemExit:  # doctor 有任何 FAIL（例如測試環境沒開埠）就離開碼 1，這裡只看它有沒有報量測值那一行
            pass
        self.assertIn("measurements", out.getvalue())

    @override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
    def test_spc_endpoint_and_alerts(self):
        client = Client()
        rng = np.random.default_rng(1)
        t0 = time.time() - 7200
        batch = [_report(self.flow.id, {"diameter": float(12 + rng.normal(0, 0.01)), "radius": 6.0}, started=t0 + k * 10) for k in range(40)]
        batch += [_report(self.flow.id, {"diameter": 12.0 + 0.01 * k, "radius": 6.0}, started=t0 + (40 + k) * 10) for k in range(1, 12)]
        self.p._write(batch)
        r = client.get(f"/api/vision/flows/{self.flow.id}/spc", {"output": "diameter", "hours": 24})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["outputs"], ["diameter", "radius"])
        self.assertEqual(len(body["series"]), 51)
        self.assertEqual(body["series"][0]["ts"] < body["series"][-1]["ts"], True)
        self.assertAlmostEqual(body["spec"]["usl"], 12.05)
        self.assertIn("cpk", body["analysis"]["capability"])
        self.assertTrue(body["alerts"], body["alerts"])
        self.assertTrue(body["analysis"]["flagged"])
        self.assertTrue(body["enabled"])
        # 預設輸出＝第一個；X̄-R；hours 太小 → 空序列；壞 chart → 422
        self.assertEqual(client.get(f"/api/vision/flows/{self.flow.id}/spc").json()["output"], "diameter")
        xb = client.get(f"/api/vision/flows/{self.flow.id}/spc", {"output": "diameter", "chart": "xbar_r", "subgroup": 5}).json()
        self.assertEqual(xb["analysis"]["limits"]["chart"], "xbar_r")
        self.assertEqual(xb["analysis"]["limits"]["n"], 10)
        self.assertEqual(client.get(f"/api/vision/flows/{self.flow.id}/spc", {"output": "diameter", "chart": "pie"}).status_code, 422)
        empty = client.get(f"/api/vision/flows/{self.flow.id}/spc", {"output": "radius", "hours": 1}).json()
        self.assertEqual(empty["series"], [])
        self.assertEqual(client.get("/api/vision/flows/999999/spc").status_code, 404)
        # 總覽告警：diameter 在漂、radius 恆定 → 只有 diameter
        al = client.get("/api/vision/spc/alerts").json()
        self.assertEqual([(i["flow_id"], i["output"]) for i in al["items"]], [(self.flow.id, "diameter")])
        self.assertFalse(al["cached"])
        self.assertTrue(client.get("/api/vision/spc/alerts").json()["cached"])
        # 從 GET 端點掃描清單看：smoke 用
        self.assertIn("diameter", json.dumps(al))
