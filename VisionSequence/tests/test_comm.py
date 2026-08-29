"""主動輸出到 PLC：writers（dio_sim / tcp_client / modbus_tcp）、write_plc 工具降級、連線 API。"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from apps.comm import writers
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
        w = ModbusTcpWriter({"host": "127.0.0.1", "port": self.server.port, "unit_id": 1, "timeout_s": 2}, name="plc")
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
        w = ModbusTcpWriter({"host": "127.0.0.1", "port": self.server.port}, name="plc")
        with self.assertRaises(CommError):
            w.write({"input:1": 5})
        w.close()

    def test_unreachable_raises(self):
        with self.assertRaises(CommError):
            ModbusTcpWriter({"host": "127.0.0.1", "port": free_port(), "timeout_s": 0.3}, name="plc")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
class WritePlcToolTests(SimpleTestCase):
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
        r = run_tool("write_plc", params={"connection": "sim", "mapping": mapping}, inputs={"values": [5, 1.5]},
                     context={"_judge": "ng", "_outputs": {"judge": "NG", "width_px": 123.4}})
        self.assertEqual(r.status, "ok", r.message)
        self.assertEqual(r.outputs, {"written": 5, "ok": True})
        self.assertEqual(sim.state, {"ok_bit": False, "width": 12, "first": 5, "second": 3.0, "const": 7})
        self.assertEqual(len(r.detail["missing"]), 1)

    def test_judge_ok_is_one(self):
        sim = DioSimWriter({}, name="sim")
        writers.register_writer("sim", sim)
        r = run_tool("write_plc", params={"connection": "sim", "mapping": [{"src": "judge", "address": "ok"}]}, context={"_judge": "ok"})
        self.assertEqual(r.status, "ok")
        self.assertEqual(sim.state["ok"], 1)

    def test_failure_degrades_by_default(self):
        writers.register_writer("sim", DioSimWriter({"channels": ["a"]}, name="sim"))
        r = run_tool("write_plc", params={"connection": "sim", "mapping": [{"src": "judge", "address": "zzz"}]}, context={"_judge": "ok"})
        self.assertEqual(r.status, "ok")
        self.assertIn("降級", r.message)
        self.assertEqual(r.outputs, {"written": 0, "ok": False})
        self.assertIn("zzz", r.detail["error"])

    def test_failure_with_on_error_fail(self):
        writers.register_writer("sim", DioSimWriter({"channels": ["a"]}, name="sim"))
        r = run_tool("write_plc", params={"connection": "sim", "mapping": [{"src": "judge", "address": "zzz"}], "on_error": "fail"}, context={"_judge": "ok"})
        self.assertEqual(r.status, "error")
        self.assertNotIn("降級", r.message)

    def test_unknown_connection_degrades(self):
        r = run_tool("write_plc", params={"connection": "nope", "mapping": [{"src": "judge", "address": "a"}]}, context={"_judge": "ok"})
        self.assertEqual(r.status, "ok")
        self.assertIn("降級", r.message)
        r = run_tool("write_plc", params={"connection": "nope", "mapping": [{"src": "judge", "address": "a"}], "on_error": "fail"}, context={"_judge": "ok"})
        self.assertEqual(r.status, "error")

    def test_modbus_unreachable_degrades(self):
        port = free_port()
        with self.assertRaises(CommError):
            ModbusTcpWriter({"host": "127.0.0.1", "port": port, "timeout_s": 0.3}, name="plc")
        # 連線曾開成功但 PLC 之後消失：用假伺服器開、關掉、再寫
        srv = ModbusServer().start()
        w = ModbusTcpWriter({"host": "127.0.0.1", "port": srv.port, "timeout_s": 0.5}, name="plc")
        srv.stop()
        writers.register_writer("plc", w)
        r = run_tool("write_plc", params={"connection": "plc", "mapping": [{"src": "judge", "address": "coil:0"}]}, context={"_judge": "ok"})
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
                {"id": "plc", "type": "write_plc", "params": {"connection": "sim", "mapping": mapping, "on_error": on_error}},
            ],
            "edges": [{"source": "j", "source_handle": "verdict", "target": "plc", "target_handle": "values"}],
        }

    def test_prefetch_opens_connection_and_tool_writes(self):
        flow = Flow.objects.create(name="f", graph=self.graph([{"src": "judge", "address": "ok"}, {"address": "done", "value": 1}]))
        report = runner.run_sync(flow)
        self.assertEqual(report.status, "ok", report.error)
        self.assertIn("已寫入 2 筆", report.nodes["plc"].message)
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
        self.assertIn("降級", report.nodes["plc"].message)
        self.assertEqual(report.nodes["plc"].logs[0]["level"], "warning")
        flow2 = Flow.objects.create(name="f2", graph=self.graph([{"src": "judge", "address": "nope"}], on_error="fail"))
        report = runner.run_sync(flow2)
        self.assertEqual(report.status, "failed")

    def test_disabled_connection_not_opened(self):
        self.conn.is_enabled = False
        self.conn.save()
        flow = Flow.objects.create(name="f", graph=self.graph([{"src": "judge", "address": "ok"}]))
        report = runner.run_sync(flow)
        self.assertEqual(report.status, "ok")
        self.assertIn("降級", report.nodes["plc"].message)
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
        r = self.post("/api/vision/connections", {"name": "plc", "kind": "modbus_tcp", "config": {"host": "127.0.0.1", "port": free_port(), "timeout_s": 0.3}})
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
