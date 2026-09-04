"""主動輸出（Modbus TCP）：writers（dio_sim / tcp_client / modbus_tcp）、write_modbus 工具降級、連線 API。"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from pymodbus.client import ModbusTcpClient

from apps.comm import triggers, writers
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


class TriggerConfigTests(SimpleTestCase):
    """觸發設定的解析（純函式，不起執行緒）。"""

    def test_off_unless_both_address_and_flow(self):
        self.assertIsNone(triggers.config_of({}))
        self.assertIsNone(triggers.config_of({"trigger_address": "coil:0"}))
        self.assertIsNone(triggers.config_of({"trigger_flow": "檢測"}))

    def test_defaults_and_clamps(self):
        cfg = triggers.config_of({"trigger_address": " coil:0 ", "trigger_flow": " 檢測 "})
        self.assertEqual((cfg["address"], cfg["flow"]), ("coil:0", "檢測"))
        self.assertEqual((cfg["mode"], cfg["clear"], cfg["done"]), ("rising", True, ""))
        self.assertEqual(cfg["interval_ms"], triggers.DEFAULT_INTERVAL_MS)
        fast = triggers.config_of({"trigger_address": "a", "trigger_flow": "b", "trigger_interval_ms": 1})
        self.assertEqual(fast["interval_ms"], triggers.MIN_INTERVAL_MS)
        bad = triggers.config_of({"trigger_address": "a", "trigger_flow": "b", "trigger_interval_ms": "很快"})
        self.assertEqual(bad["interval_ms"], triggers.DEFAULT_INTERVAL_MS)
        nz = triggers.config_of({"trigger_address": "a", "trigger_flow": "b", "trigger_mode": "NONZERO", "trigger_clear": False})
        self.assertEqual((nz["mode"], nz["clear"]), ("nonzero", False))


class TriggerLoopTests(SimpleTestCase):
    """PLC 寫旗標 → 平台跑流程。用假 writer 驗迴圈的握手，不碰真的 Modbus。"""

    class FakeWriter:
        kind = "fake"
        name = "fake"

        def __init__(self, values=None):
            self.values = dict(values or {})
            self.written = []
            self.fail_reads = 0
            self.lock = threading.Lock()

        def read(self, addresses, quiet=False):
            with self.lock:
                if self.fail_reads > 0:
                    self.fail_reads -= 1
                    raise writers.CommError("PLC 沒回應")
                return {a: self.values.get(a, 0) for a in addresses}

        def write(self, values, timeout=None):
            with self.lock:
                self.values.update(values)
                self.written.append(dict(values))
            return {"written": len(values)}

    def _loop(self, writer, **cfg):
        settings = triggers.config_of({"trigger_address": "coil:0", "trigger_flow": "x", "trigger_interval_ms": 10, **cfg})
        loop = triggers.TriggerLoop(writer, settings)
        loop._run = lambda flow: SimpleNamespace(id="run1", status="ok", outputs={"judge": "OK"}, error="")  # noqa: SLF001
        loop._resolve_flow = lambda: SimpleNamespace(name="x")  # noqa: SLF001
        self.addCleanup(loop.stop)
        return loop

    def _wait(self, cond, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_rising_edge_fires_once_and_does_the_handshake(self):
        w = self.FakeWriter({"coil:0": 1})
        loop = self._loop(w, trigger_done_address="coil:1")
        loop.start()
        self.assertTrue(self._wait(lambda: loop.fired >= 1), "旗標寫進來卻沒有觸發")
        self.assertEqual(w.values["coil:0"], 0)  # 先清旗標
        self.assertEqual(w.values["coil:1"], 1)  # 跑完設完成
        time.sleep(0.1)
        self.assertEqual(loop.fired, 1)  # 旗標已清，不會重複觸發
        w.values["coil:0"] = 1
        self.assertTrue(self._wait(lambda: loop.fired >= 2), "PLC 再寫一次應該再觸發")

    def test_nonzero_mode_keeps_firing(self):
        w = self.FakeWriter({"coil:0": 1})
        loop = self._loop(w, trigger_mode="nonzero", trigger_clear=False)
        loop.start()
        self.assertTrue(self._wait(lambda: loop.fired >= 3), "nonzero 模式應該持續觸發")
        self.assertEqual(w.written, [])  # 沒有 clear、沒有 done 就不該寫任何東西

    def test_read_failure_backs_off_and_recovers(self):
        w = self.FakeWriter({"coil:0": 1})
        w.fail_reads = 3
        loop = self._loop(w)
        loop.start()
        self.assertTrue(self._wait(lambda: loop.errors >= 3), "讀取失敗要記下來")
        self.assertIn("沒回應", loop.last_error)
        self.assertTrue(self._wait(lambda: loop.fired >= 1), "PLC 回來之後要繼續工作")

    def test_missing_flow_is_recorded_not_raised(self):
        w = self.FakeWriter({"coil:0": 1})
        settings = triggers.config_of({"trigger_address": "coil:0", "trigger_flow": "沒這個流程", "trigger_interval_ms": 10})
        loop = triggers.TriggerLoop(w, settings)
        loop._resolve_flow = lambda: None  # noqa: SLF001
        self.addCleanup(loop.stop)
        loop.start()
        self.assertTrue(self._wait(lambda: loop.errors >= 1))
        self.assertIn("不存在", loop.last_error)
        self.assertEqual(loop.fired, 0)

    def test_polling_does_not_flood_the_trace(self):
        """輪詢每秒幾十次，記進追蹤只會把真正的命令沖掉；失敗仍要記。"""
        trace.clear()
        self.addCleanup(trace.clear)
        trace.watch()
        w = self.FakeWriter({"coil:0": 0})
        loop = self._loop(w)
        loop.start()
        self.assertTrue(self._wait(lambda: loop.settings and time.time() > 0))
        time.sleep(0.2)  # 至少輪詢十幾次
        self.assertEqual(trace.entries("modbus"), [])
        w.values["coil:0"] = 1
        self.assertTrue(self._wait(lambda: loop.fired >= 1))
        summaries = [e["summary"] for e in trace.entries("modbus")]
        self.assertTrue(any("觸發" in s for s in summaries), summaries)
        self.assertFalse(any(s.startswith("讀取") for s in summaries), summaries)

    def test_status_and_registry(self):
        w = self.FakeWriter()
        self.addCleanup(triggers.stop_all)
        loop = triggers.sync(4242, w, {"trigger_address": "coil:9", "trigger_flow": "f", "trigger_interval_ms": 50})
        self.assertIsNotNone(loop)
        self.assertEqual(triggers.sync(4242, w, {"trigger_address": "coil:9", "trigger_flow": "f", "trigger_interval_ms": 50}), loop)  # 設定沒變就沿用
        st = triggers.status(4242)
        self.assertEqual((st["address"], st["flow"], st["running"]), ("coil:9", "f", True))
        self.assertIsNone(triggers.sync(4242, w, {}))  # 拿掉設定就停掉
        self.assertIsNone(triggers.status(4242))
        self.assertFalse(loop.is_alive() and not loop._halt.is_set())  # noqa: SLF001


class AutostartTests(TestCase):
    """從站要在啟動時就開埠，不能等有人按「測試」。"""

    def test_listener_opens_on_create_and_autostart(self):
        from apps.comm.models import Connection

        port = free_port()
        conn = Connection.objects.create(name="自動從站", kind="modbus_server", config={"host": "127.0.0.1", "port": port, "size": 32})
        self.addCleanup(writers.close_all)
        writers.ensure_started(conn)
        client = ModbusTcpClient("127.0.0.1", port=port, timeout=2)
        self.assertTrue(client.connect(), "建立連線後 PLC 就該連得上")
        client.close()
        writers.close_all()  # 模擬伺服器重開
        self.assertEqual(writers.autostart(), ["自動從站"])
        client = ModbusTcpClient("127.0.0.1", port=port, timeout=2)
        self.assertTrue(client.connect(), "重開後要自己回來聽")
        client.close()

    def test_start_failure_shows_the_reason(self):
        """埠被別的程式佔走時，狀態要說得出原因（不然只看到「未開啟」，PLC 連不上卻查不到）。"""
        from apps.comm.models import Connection

        port = free_port()
        conn = Connection.objects.create(name="被佔用", kind="modbus_server", config={"host": "127.0.0.1", "port": port, "size": 32})
        self.addCleanup(writers.close_all)
        boom = writers.CommError(f"Modbus 從站無法在 127.0.0.1:{port} 啟動（埠已被使用）；請確認這個埠沒有被其他程式佔用")
        with mock.patch.object(writers.ModbusServerWriter, "_open", side_effect=boom):
            writers.ensure_started(conn)  # 不該拋，但要留下原因
        status = writers.connection_info(conn)
        self.assertFalse(status["open"])
        self.assertIn("無法在", status["error"])
        self.assertIn(str(port), status["error"])
        r = self.client.post(f"/api/vision/connections/{conn.id}/test")  # 「測試」也要回同一個原因
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])  # 佔用解除後就開得起來
        self.assertEqual(writers.connection_info(conn)["open"], True)

    def test_plain_client_connection_is_not_autostarted(self):
        from apps.comm.models import Connection

        conn = Connection.objects.create(name="純主站", kind="modbus_tcp", config={"host": "127.0.0.1", "port": 502})
        self.assertFalse(writers.should_autostart(conn))
        conn.config = {**conn.config, "trigger_address": "coil:0", "trigger_flow": "f"}
        self.assertTrue(writers.should_autostart(conn), "設了觸發位址的主站也要自己活起來")
        conn.is_enabled = False
        self.assertFalse(writers.should_autostart(conn))


class PrefetchTests(SimpleTestCase):
    """只讀不寫的流程也要拿得到連線（以前只掃 write_modbus，read_modbus 靜默降級）。"""

    def test_scans_every_tool_that_declares_a_connection_param(self):
        from apps.vision.tools import base as tools_base

        for key in ("write_modbus", "read_modbus"):
            self.assertEqual(tools_base.get(key).connection_params, ("connection",), key)

    def test_prefetch_collects_names_from_both_tools(self):
        from apps.vision.graph import compile_graph, validate_graph

        graph = {
            "nodes": [
                {"id": "r", "type": "read_modbus", "params": {"connection": "讀取用", "mapping": []}},
                {"id": "w", "type": "write_modbus", "params": {"connection": "寫入用", "mapping": []}},
            ],
            "edges": [],
        }
        compiled = compile_graph(validate_graph(graph))
        seen = []
        with mock.patch.object(writers, "open_connection", side_effect=lambda conn: seen.append(conn.name)), \
             mock.patch("apps.comm.models.Connection.objects") as objects:
            objects.filter.return_value = []
            writers.prefetch_connections(compiled)
            names = set(objects.filter.call_args.args[0].children[0][1])
        self.assertEqual(names, {"讀取用", "寫入用"})


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
