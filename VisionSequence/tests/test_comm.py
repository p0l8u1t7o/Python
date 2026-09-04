"""主動輸出（Modbus TCP）：writers（dio_sim / tcp_client / modbus_tcp）、write_modbus 工具降級、連線 API。"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from pymodbus.client import ModbusTcpClient

from apps.comm import writers
from apps.vision import trace
from apps.comm.models import Connection
from apps.comm.writers import CommError, DioSimWriter, ModbusTcpWriter, TcpClientWriter, parse_address
from apps.vision.models import Flow, ImageSource
from apps.vision.runner import runner
from tests._helpers import run_tool

logging.getLogger("pymodbus.logging").setLevel(logging.WARNING)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# 測試用伺服器
# ---------------------------------------------------------------------------
class LineServer(threading.Thread):
    """收一行文字的假上位機；reply 不為 None 時回一行。"""

    def __init__(self, reply: str | None = None) -> None:
        super().__init__(daemon=True)
        self.port = free_port()
        self.reply = reply
        self.lines: list[str] = []
        self.got = threading.Event()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port))
        self.sock.listen(2)
        self.sock.settimeout(5)

    def run(self) -> None:
        try:
            while True:
                conn, _ = self.sock.accept()
                conn.settimeout(5)
                buf = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        self.lines.append(line.decode("utf-8"))
                        if self.reply is not None:
                            conn.sendall((self.reply + "\n").encode())
                        self.got.set()
                conn.close()
        except OSError:
            pass

    def stop(self) -> None:
        self.sock.close()


class ModbusServer:
    """pymodbus 的 asyncio TCP server 跑在執行緒裡；線圈與保持暫存器各 1000 個（從 0 起）。"""

    def __init__(self) -> None:
        self.port = free_port()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.server = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "ModbusServer":
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError("Modbus 測試伺服器沒起來")
        return self

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
        from pymodbus.server import ModbusTcpServer

        device = ModbusDeviceContext(co=ModbusSequentialDataBlock(1, [False] * 1000), hr=ModbusSequentialDataBlock(1, [0] * 1000))
        self.loop = asyncio.get_running_loop()
        self.server = ModbusTcpServer(ModbusServerContext(devices=device, single=True), address=("127.0.0.1", self.port))
        await self.server.serve_forever(background=True)
        self.ready.set()
        await self.server.serving

    def stop(self) -> None:
        if self.loop and self.server:
            fut = asyncio.run_coroutine_threadsafe(self.server.shutdown(), self.loop)
            fut.result(5)
        self.thread.join(5)


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------
class AddressTests(SimpleTestCase):
    def test_parse(self):
        self.assertEqual(parse_address("coil:10"), ("coil", 10, "bool"))
        self.assertEqual(parse_address("holding:100"), ("holding", 100, "uint16"))
        self.assertEqual(parse_address("holding:0x100:float32"), ("holding", 256, "float32"))
        self.assertEqual(parse_address("HR:5:int32"), ("holding", 5, "int32"))
        for bad in ("", "coil", "foo:1", "holding:x", "holding:1:int8"):
            with self.assertRaises(CommError):
                parse_address(bad)


class DioSimTests(SimpleTestCase):
    def test_write_and_read(self):
        w = DioSimWriter({"channels": ["ok", "ng"]}, name="sim")
        self.assertEqual(w.write({"ok": 1, "ng": 0})["written"], 2)
        self.assertEqual(w.read(["ok", "ng"]), {"ok": 1, "ng": 0})
        self.assertEqual(w.info()["state"], {"ok": 1, "ng": 0})
        self.assertEqual(w.info()["writes"], 1)

    def test_unknown_channel_fails(self):
        w = DioSimWriter({"channels": ["ok"]}, name="sim")
        with self.assertRaises(CommError) as cm:
            w.write({"nope": 1})
        self.assertIn("nope", str(cm.exception))
        self.assertEqual(w.info()["errors"], 1)

    def test_channels_by_count(self):
        w = DioSimWriter({"channels": 4}, name="sim")
        self.assertEqual(w.channels, ["DO0", "DO1", "DO2", "DO3"])
        w.write({"DO3": True})
        self.assertTrue(w.read(["DO3"])["DO3"])


class TcpClientTests(SimpleTestCase):
    def test_template_line(self):
        srv = LineServer()
        srv.start()
        try:
            w = TcpClientWriter({"host": "127.0.0.1", "port": srv.port, "template": "RESULT {judge} {width_px}"}, name="host")
            out = w.write({"judge": "OK", "width_px": 12.5})
            self.assertEqual(out["payload"], "RESULT OK 12.5\n")
            self.assertTrue(srv.got.wait(2))
            self.assertEqual(srv.lines, ["RESULT OK 12.5"])
            # 缺欄位不炸，補空字串
            self.assertEqual(w.render({"judge": "NG"}), "RESULT NG \n")
            w.close()
        finally:
            srv.stop()

    def test_json_line_and_reply(self):
        srv = LineServer(reply="ACK")
        srv.start()
        try:
            w = TcpClientWriter({"host": "127.0.0.1", "port": srv.port, "wait_reply": True}, name="host")
            out = w.write({"judge": "NG", "n": 3})
            self.assertEqual(out["reply"], "ACK")
            self.assertTrue(srv.got.wait(2))
            self.assertEqual(json.loads(srv.lines[0]), {"judge": "NG", "n": 3})
            w.close()
        finally:
            srv.stop()

    def test_reconnect_once_after_server_drop(self):
        srv = LineServer()
        srv.start()
        try:
            w = TcpClientWriter({"host": "127.0.0.1", "port": srv.port}, name="host")
            w.write({"a": 1})
            self.assertTrue(srv.got.wait(2))
            # 客戶端這邊把 socket 弄壞：下一次寫入應自動重連並成功
            w.sock.close()
            srv.got.clear()
            w.write({"a": 2})
            self.assertTrue(srv.got.wait(2))
            self.assertEqual(w.info()["reconnects"], 1)
            w.close()
        finally:
            srv.stop()

    def test_unreachable(self):
        with self.assertRaises(CommError):
            TcpClientWriter({"host": "127.0.0.1", "port": free_port(), "timeout_s": 0.5}, name="host")


class ModbusTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = ModbusServer().start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        super().tearDownClass()

    def test_write_coil_holding_float32_int32(self):
        w = ModbusTcpWriter({"host": "127.0.0.1", "port": self.server.port, "unit_id": 1, "timeout_s": 2}, name="mb")
        out = w.write({"coil:5": 1, "holding:100": 1234, "holding:200:float32": 3.5, "holding:300:int32": -70000, "holding:400:int16": -3})
        self.assertEqual(out["written"], 5)
        back = w.read(["coil:5", "coil:6", "holding:100", "holding:200:float32", "holding:300:int32", "holding:400:int16"])
        self.assertTrue(back["coil:5"])
        self.assertFalse(back["coil:6"])
        self.assertEqual(back["holding:100"], 1234)
        self.assertAlmostEqual(back["holding:200:float32"], 3.5)
        self.assertEqual(back["holding:300:int32"], -70000)
        self.assertEqual(back["holding:400:int16"], -3)
        # 浮點寫進 uint16 會四捨五入
        w.write({"holding:101": 7.6})
        self.assertEqual(w.read(["holding:101"])["holding:101"], 8)
        self.assertTrue(w.info()["connected"])
        w.close()

    def test_readonly_area_rejected(self):
        w = ModbusTcpWriter({"host": "127.0.0.1", "port": self.server.port}, name="mb")
        with self.assertRaises(CommError):
            w.write({"input:1": 5})
        w.close()

    def test_unreachable_raises(self):
        with self.assertRaises(CommError):
            ModbusTcpWriter({"host": "127.0.0.1", "port": free_port(), "timeout_s": 0.3}, name="mb")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
class ModbusServerTests(SimpleTestCase):
    """本平台當 Modbus 從站：主站讀得到我們寫的值，我們也讀得到主站寫進來的值。"""

    def setUp(self):
        self.port = free_port()
        self.writer = writers.ModbusServerWriter({"host": "127.0.0.1", "port": self.port, "unit_id": 1, "size": 128}, name="slave")
        self.addCleanup(self.writer.close)
        self.client = ModbusTcpClient("127.0.0.1", port=self.port, timeout=2)
        self.assertTrue(self.client.connect())
        self.addCleanup(self.client.close)

    def test_master_reads_what_the_flow_writes(self):
        info = self.writer.info()
        self.assertEqual((info["kind"], info["listening"], info["role"], info["port"]), ("modbus_server", True, "server", self.port))
        self.writer.write({"coil:0": True, "holding:10": 1234, "holding:20:float32": 3.5, "holding:30:int32": -7})
        self.assertTrue(self.client.read_coils(0, count=1, device_id=1).bits[0])
        self.assertEqual(self.client.read_holding_registers(10, count=1, device_id=1).registers, [1234])
        self.assertAlmostEqual(ModbusTcpClient.convert_from_registers(self.client.read_holding_registers(20, count=2, device_id=1).registers, ModbusTcpClient.DATATYPE.FLOAT32), 3.5, places=3)
        self.assertEqual(ModbusTcpClient.convert_from_registers(self.client.read_holding_registers(30, count=2, device_id=1).registers, ModbusTcpClient.DATATYPE.INT32), -7)

    def test_flow_reads_what_the_master_writes(self):
        self.client.write_register(5, 42, device_id=1)
        self.client.write_coil(6, True, device_id=1)
        self.assertEqual(self.writer.read(["holding:5", "coil:6"]), {"holding:5": 42, "coil:6": True})

    def test_word_order_little(self):
        port = free_port()
        w = writers.ModbusServerWriter({"host": "127.0.0.1", "port": port, "size": 32, "word_order": "little"}, name="le")
        self.addCleanup(w.close)
        w.write({"holding:0:int32": 70000})
        self.assertEqual(w.read(["holding:0:int32"]), {"holding:0:int32": 70000})
        c = ModbusTcpClient("127.0.0.1", port=port, timeout=2)
        self.assertTrue(c.connect())
        self.addCleanup(c.close)
        regs = c.read_holding_registers(0, count=2, device_id=1).registers
        self.assertEqual(ModbusTcpClient.convert_from_registers(regs, ModbusTcpClient.DATATYPE.INT32, word_order="little"), 70000)

    def test_kind_is_listed_and_closes_cleanly(self):
        kinds = {k["kind"]: k for k in writers.kinds()}
        self.assertIn("modbus_server", kinds)
        self.assertIn("size", kinds["modbus_server"]["fields"])
        self.assertIn("從站", kinds["modbus_server"]["label"])
        self.writer.close()
        self.assertFalse(self.writer.info()["listening"])
        with self.assertRaises(writers.CommError):
            self.writer._read(["holding:0"])  # noqa: SLF001 — 關閉後直接讀應該明確失敗


class ReadModbusToolTests(SimpleTestCase):
    """讀取 Modbus 工具：把暫存器的值讀進流程，可選擇同時放進具名輸出。"""

    def tearDown(self):
        writers.close_all()

    def test_reads_values_and_publishes(self):
        port = free_port()
        server = writers.ModbusServerWriter({"host": "127.0.0.1", "port": port, "size": 64}, name="plc")
        self.addCleanup(server.close)
        writers.register_writer("plc", server)
        client = ModbusTcpClient("127.0.0.1", port=port, timeout=2)
        self.assertTrue(client.connect())
        self.addCleanup(client.close)
        client.write_register(0, 42, device_id=1)
        client.write_coil(1, True, device_id=1)
        client.write_register(10, 250, device_id=1)

        mapping = [{"name": "recipe", "address": "holding:0"}, {"name": "trigger", "address": "coil:1"}, {"name": "temp", "address": "holding:10", "scale": 0.1}]
        r = run_tool("read_modbus", params={"connection": "plc", "mapping": mapping, "publish": True})
        self.assertEqual(r.status, "ok", r.message)
        self.assertEqual(r.outputs["values"], [42, True, 25.0])
        self.assertEqual(r.outputs["value"], 42.0)
        self.assertTrue(r.outputs["ok"])
        self.assertEqual(r.context["_outputs"], {"recipe": 42, "trigger": True, "temp": 25.0})
        self.assertEqual(r.detail["values"]["temp"], 25.0)
        # 不勾 publish 就不進具名輸出
        r2 = run_tool("read_modbus", params={"connection": "plc", "mapping": mapping})
        self.assertIsNone(r2.context)

    def test_unknown_connection_degrades_and_can_fail(self):
        r = run_tool("read_modbus", params={"connection": "nope", "mapping": [{"name": "a", "address": "holding:0"}]})
        self.assertEqual(r.status, "ok")
        self.assertFalse(r.outputs["ok"])
        self.assertIn("未開啟", r.detail["error"])
        r2 = run_tool("read_modbus", params={"connection": "nope", "mapping": [{"name": "a", "address": "holding:0"}], "on_error": "fail"})
        self.assertEqual(r2.status, "error")

    def test_empty_mapping_is_ok(self):
        r = run_tool("read_modbus", params={"connection": "whatever", "mapping": []})
        self.assertEqual((r.status, r.outputs["values"]), ("ok", []))


class TraceTests(SimpleTestCase):
    """整合追蹤：命令與結果進環形緩衝，沒人在看時只留錯誤。"""

    def setUp(self):
        trace.clear()
        self.addCleanup(trace.clear)

    def test_records_only_when_watched_but_always_on_error(self):
        trace._watch_until = 0.0  # noqa: SLF001 — 沒人在看
        self.assertEqual(trace.record("tcp", "RUN 1"), 0)
        self.assertEqual(trace.entries("tcp"), [])
        self.assertGreater(trace.record("tcp", "RUN 9", ok=False), 0)  # 錯誤永遠記
        trace._watch_until = 0.0  # noqa: SLF001
        self.assertGreater(trace.record("tcp", "RUN 1", force=True), 0)
        trace.watch()
        self.assertGreater(trace.record("tcp", "RUN 2"), 0)
        items = trace.entries("tcp")
        self.assertEqual([e["summary"] for e in items], ["RUN 9", "RUN 1", "RUN 2"])
        self.assertEqual([e["ok"] for e in items], [False, True, True])

    def test_since_channels_and_ring(self):
        trace.watch()
        first = trace.record("http", "第一筆")
        trace.record("modbus", "寫入")
        self.assertEqual([e["summary"] for e in trace.entries("http")], ["第一筆"])
        self.assertEqual([e["summary"] for e in trace.entries(since=first)], ["寫入"])
        self.assertEqual(len(trace.entries()), 2)  # 不指定頻道＝全部
        for i in range(trace.KEEP + 20):
            trace.record("tcp", f"#{i}")
        self.assertEqual(len(trace.entries("tcp", limit=trace.KEEP)), trace.KEEP)
        self.assertEqual(trace.stats()["channels"]["tcp"], trace.KEEP)
        trace.clear("tcp")
        self.assertEqual(trace.entries("tcp"), [])
        self.assertEqual(len(trace.entries("http")), 1)

    def test_detail_is_clipped(self):
        trace.watch()
        trace.record("http", "大 detail", detail={"text": "x" * 5000, "items": list(range(200)), "obj": object()})
        entry = trace.entries("http")[-1]
        self.assertLessEqual(len(entry["detail"]["text"]), trace.MAX_DETAIL_CHARS + 1)
        self.assertEqual(len(entry["detail"]["items"]), 40)
        self.assertIsInstance(entry["detail"]["obj"], str)

    def test_writer_records_command_and_result(self):
        trace.watch()
        sim = DioSimWriter({"channels": ["DO0"]}, name="sim")
        sim.write({"DO0": True})
        entry = trace.entries("modbus")[-1]
        self.assertEqual((entry["name"], entry["ok"], entry["direction"]), ("sim", True, "out"))
        self.assertIn("寫入", entry["summary"])
        self.assertEqual(entry["detail"]["request"], {"DO0": True})
        with self.assertRaises(writers.CommError):
            sim.write({"NOPE": 1})
        self.assertFalse(trace.entries("modbus")[-1]["ok"])


class WriteModbusToolTests(SimpleTestCase):
    def tearDown(self):
        writers.close_all()

    def test_mapping_sources_and_scale(self):
        sim = DioSimWriter({}, name="sim")
        writers.register_writer("sim", sim)
        mapping = [
            {"src": "judge", "address": "ok_bit", "dtype": "bool"},
            {"src": "width_px", "address": "width", "scale": 0.1, "dtype": "int"},
            {"src": "v0", "address": "first"},
            {"src": "v1", "address": "second", "scale": 2.0},
            {"address": "const", "value": 7},
            {"src": "missing", "address": "nothing"},
        ]
        r = run_tool("write_modbus", params={"connection": "sim", "mapping": mapping}, inputs={"values": [5, 1.5]},
                     context={"_judge": "ng", "_outputs": {"judge": "NG", "width_px": 123.4}})
        self.assertEqual(r.status, "ok", r.message)
        self.assertEqual(r.outputs, {"written": 5, "ok": True})
        self.assertEqual(sim.state, {"ok_bit": False, "width": 12, "first": 5, "second": 3.0, "const": 7})
        self.assertEqual(len(r.detail["missing"]), 1)

    def test_judge_ok_is_one(self):
        sim = DioSimWriter({}, name="sim")
        writers.register_writer("sim", sim)
        r = run_tool("write_modbus", params={"connection": "sim", "mapping": [{"src": "judge", "address": "ok"}]}, context={"_judge": "ok"})
        self.assertEqual(r.status, "ok")
        self.assertEqual(sim.state["ok"], 1)

    def test_failure_degrades_by_default(self):
        writers.register_writer("sim", DioSimWriter({"channels": ["a"]}, name="sim"))
        r = run_tool("write_modbus", params={"connection": "sim", "mapping": [{"src": "judge", "address": "zzz"}]}, context={"_judge": "ok"})
        self.assertEqual(r.status, "ok")
        self.assertIn("降級", r.message)
        self.assertEqual(r.outputs, {"written": 0, "ok": False})
        self.assertIn("zzz", r.detail["error"])

    def test_failure_with_on_error_fail(self):
        writers.register_writer("sim", DioSimWriter({"channels": ["a"]}, name="sim"))
        r = run_tool("write_modbus", params={"connection": "sim", "mapping": [{"src": "judge", "address": "zzz"}], "on_error": "fail"}, context={"_judge": "ok"})
        self.assertEqual(r.status, "error")
        self.assertNotIn("降級", r.message)

    def test_unknown_connection_degrades(self):
        r = run_tool("write_modbus", params={"connection": "nope", "mapping": [{"src": "judge", "address": "a"}]}, context={"_judge": "ok"})
        self.assertEqual(r.status, "ok")
        self.assertIn("降級", r.message)
        r = run_tool("write_modbus", params={"connection": "nope", "mapping": [{"src": "judge", "address": "a"}], "on_error": "fail"}, context={"_judge": "ok"})
        self.assertEqual(r.status, "error")

    def test_modbus_unreachable_degrades(self):
        port = free_port()
        with self.assertRaises(CommError):
            ModbusTcpWriter({"host": "127.0.0.1", "port": port, "timeout_s": 0.3}, name="mb")
        # 連線曾開成功但設備之後消失：用假伺服器開、關掉、再寫
        srv = ModbusServer().start()
        w = ModbusTcpWriter({"host": "127.0.0.1", "port": srv.port, "timeout_s": 0.5}, name="mb")
        srv.stop()
        writers.register_writer("mb", w)
        r = run_tool("write_modbus", params={"connection": "mb", "mapping": [{"src": "judge", "address": "coil:0"}]}, context={"_judge": "ok"})
        self.assertEqual(r.status, "ok")
        self.assertIn("降級", r.message)
        self.assertGreaterEqual(w.info()["reconnects"], 1)


# ---------------------------------------------------------------------------
# Runner prefetch + API
# ---------------------------------------------------------------------------
@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class RunnerIntegrationTests(TestCase):
    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        writers.close_all()
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 160, "height": 120})
        self.conn = Connection.objects.create(name="sim", kind="dio_sim", config={"channels": ["done", "ok"]})

    def tearDown(self):
        writers.close_all()

    def graph(self, mapping, on_error="warn"):
        return {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": self.source.id}},
                {"id": "j", "type": "judge", "params": {"verdict": "ok"}},
                {"id": "mb", "type": "write_modbus", "params": {"connection": "sim", "mapping": mapping, "on_error": on_error}},
            ],
            "edges": [{"source": "j", "source_handle": "verdict", "target": "mb", "target_handle": "values"}],
        }

    def test_prefetch_opens_connection_and_tool_writes(self):
        flow = Flow.objects.create(name="f", graph=self.graph([{"src": "judge", "address": "ok"}, {"address": "done", "value": 1}]))
        report = runner.run_sync(flow)
        self.assertEqual(report.status, "ok", report.error)
        self.assertIn("已寫入 2 筆", report.nodes["mb"].message)
        w = writers.get_writer("sim")
        self.assertIsNotNone(w)
        self.assertEqual(w.state, {"done": 1, "ok": 1})
        # 再跑一次：同一個 writer（快取），不重開
        runner.run_sync(flow)
        self.assertIs(writers.get_writer("sim"), w)
        self.assertEqual(w.info()["writes"], 2)

    def test_write_failure_degrades_run_or_fails(self):
        flow = Flow.objects.create(name="f", graph=self.graph([{"src": "judge", "address": "nope"}]))
        report = runner.run_sync(flow)
        self.assertEqual(report.status, "ok")
        self.assertIn("降級", report.nodes["mb"].message)
        self.assertEqual(report.nodes["mb"].logs[0]["level"], "warning")
        flow2 = Flow.objects.create(name="f2", graph=self.graph([{"src": "judge", "address": "nope"}], on_error="fail"))
        report = runner.run_sync(flow2)
        self.assertEqual(report.status, "failed")

    def test_disabled_connection_not_opened(self):
        self.conn.is_enabled = False
        self.conn.save()
        flow = Flow.objects.create(name="f", graph=self.graph([{"src": "judge", "address": "ok"}]))
        report = runner.run_sync(flow)
        self.assertEqual(report.status, "ok")
        self.assertIn("降級", report.nodes["mb"].message)
        self.assertIsNone(writers.get_writer("sim"))


class ConnectionApiTests(TestCase):
    def setUp(self):
        writers.close_all()

    def tearDown(self):
        writers.close_all()

    def post(self, path, body=None, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(path, data=json.dumps(body or {}), content_type="application/json", **headers)

    def test_kinds(self):
        r = self.client.get("/api/vision/connections/kinds")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({k["kind"] for k in r.json()["items"]} >= {"modbus_tcp", "tcp_client", "dio_sim", "plugin"}, True)

    def test_crud_test_write_state(self):
        r = self.post("/api/vision/connections", {"name": "sim", "kind": "dio_sim", "config": {"channels": ["a", "b"]}})
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["id"]
        self.assertFalse(r.json()["status"]["open"])
        self.assertEqual(self.post("/api/vision/connections", {"name": "sim", "kind": "dio_sim"}).status_code, 409)
        self.assertEqual(self.post("/api/vision/connections", {"name": "x", "kind": "what"}).status_code, 422)

        r = self.post(f"/api/vision/connections/{cid}/test")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"], r.content)
        self.assertEqual(r.json()["info"]["kind"], "dio_sim")

        r = self.post(f"/api/vision/connections/{cid}/write", {"values": {"a": 1, "b": 0}})
        self.assertTrue(r.json()["ok"], r.content)
        r = self.client.get(f"/api/vision/connections/{cid}/state")
        self.assertEqual(r.json()["values"], {"a": 1, "b": 0})
        r = self.client.get(f"/api/vision/connections/{cid}/state?addresses=a")
        self.assertEqual(r.json()["values"], {"a": 1})
        r = self.post(f"/api/vision/connections/{cid}/write", {"values": {"zz": 1}})
        self.assertFalse(r.json()["ok"])

        r = self.client.get("/api/vision/connections")
        self.assertEqual(len(r.json()["items"]), 1)
        self.assertTrue(r.json()["items"][0]["status"]["open"])

        # PATCH 設定 → 連線關閉、下次重開
        r = self.client.patch(f"/api/vision/connections/{cid}", data=json.dumps({"config": {"channels": ["c"]}}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["status"]["open"])
        r = self.client.get(f"/api/vision/connections/{cid}/state")
        self.assertEqual(r.json()["values"], {"c": 0})

        self.assertEqual(self.client.delete(f"/api/vision/connections/{cid}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/vision/connections/{cid}").status_code, 404)

    def test_test_endpoint_reports_error(self):
        r = self.post("/api/vision/connections", {"name": "mb", "kind": "modbus_tcp", "config": {"host": "127.0.0.1", "port": free_port(), "timeout_s": 0.3}})
        cid = r.json()["id"]
        r = self.post(f"/api/vision/connections/{cid}/test")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertIn("連不上", r.json()["error"])

    def test_non_admin_can_read_not_write(self):
        admin = self.post("/api/auth/setup", {"username": "admin", "password": "secret1"}).json()["token"]
        self.post("/api/users", {"username": "bob", "password": "pass123", "is_staff": False}, token=admin)
        bob = self.post("/api/auth/login", {"username": "bob", "password": "pass123"}).json()["token"]
        r = self.post("/api/vision/connections", {"name": "sim", "kind": "dio_sim"}, token=bob)
        self.assertEqual(r.status_code, 403)
        r = self.post("/api/vision/connections", {"name": "sim", "kind": "dio_sim"}, token=admin)
        self.assertEqual(r.status_code, 201)
        cid = r.json()["id"]
        self.assertEqual(self.client.get("/api/vision/connections", HTTP_AUTHORIZATION=f"Bearer {bob}").status_code, 200)
        self.assertEqual(self.post(f"/api/vision/connections/{cid}/write", {"values": {"a": 1}}, token=bob).status_code, 403)
        self.assertEqual(self.client.get("/api/vision/connections").status_code, 401)
