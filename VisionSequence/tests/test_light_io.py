"""光源控制器與 I/O 輸出工具：全程使用虛擬串口、本機 socket 或記憶體假設備。"""

from __future__ import annotations

import socket
import threading
import time

from django.test import SimpleTestCase

from apps.comm import writers
from apps.vision.tools import base as tools_base
from tests._helpers import run_tool
from tests.fakes import MemoryWriter


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(pred, timeout: float = 2.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


class LightSocketServer(threading.Thread):
    """收光源控制器 TCP 命令的本機假設備。"""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.port = free_port()
        self.data = bytearray()
        self.ready = threading.Event()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port))
        self.sock.listen(1)
        self.sock.settimeout(2.0)

    def run(self) -> None:
        try:
            conn, _peer = self.sock.accept()
            self.ready.set()
            with conn:
                conn.settimeout(0.5)
                while True:
                    try:
                        chunk = conn.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        return
                    self.data.extend(chunk)
        except OSError:
            pass

    def stop(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class LightControllerWriterTests(SimpleTestCase):
    def test_loop_url_renders_hikrobot_template_and_info(self):
        writer = writers.LightControllerWriter(
            {"transport": "serial", "port": "loop://", "preset": "hikrobot_digital", "timeout_s": 0.5},
            name="light",
        )
        self.addCleanup(writer.close)
        out = writer.set_light(1, 7, "brightness")
        self.assertEqual(out["command"], "SLA0007#")
        self.assertEqual(writer.info()["channel_values"], {1: 7})
        self.assertEqual(writer.info()["last_command"], "SLA0007#")

    def test_tcp_transport_sends_to_local_socket(self):
        server = LightSocketServer()
        server.start()
        self.addCleanup(server.stop)
        writer = writers.LightControllerWriter(
            {
                "transport": "tcp",
                "host": "127.0.0.1",
                "port": server.port,
                "end_char": "\\n",
                "brightness_template": "L{channel}:{value:03d}",
                "channels": 2,
            },
            name="tcp-light",
        )
        self.addCleanup(writer.close)
        writer.set_light(2, 42)
        self.assertTrue(wait_for(lambda: bytes(server.data) == b"L2:042\n"))

    def test_ccs_checksum_placeholder(self):
        writer = writers.LightControllerWriter({"transport": "serial", "port": "loop://", "preset": "ccs_pd3", "timeout_s": 0.5}, name="ccs")
        self.addCleanup(writer.close)
        self.assertEqual(writer.render_light(1, 12), "@00F01279")


class LightAndIoToolTests(SimpleTestCase):
    def tearDown(self):
        writers.close_all()

    def test_connection_params_are_declared(self):
        self.assertEqual(tools_base.get("set_light").connection_params, ("connection",))
        self.assertEqual(tools_base.get("io_output").connection_params, ("connection",))
        teach = {p.key for p in tools_base.get("set_light").params if p.teach}
        self.assertEqual(teach, {"value"})
        teach = {p.key for p in tools_base.get("io_output").params if p.teach}
        self.assertEqual(teach, {"address", "pulse_ms"})

    def test_set_light_uses_registered_light_and_degrades(self):
        light = writers.LightControllerWriter({"transport": "serial", "port": "loop://", "end_char": "none", "channels": 2}, name="light")
        self.addCleanup(light.close)
        writers.register_writer("light", light)
        result = run_tool("set_light", params={"connection": "light", "channel": 2, "value": 77})
        self.assertEqual(result.status, "ok", result.message)
        self.assertEqual(result.outputs, {"ok": True})
        self.assertEqual(light.info()["channel_values"], {2: 77})

        result = run_tool("set_light", params={"connection": "missing", "channel": 1, "value": 10})
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.outputs, {"ok": False})
        self.assertIn("degraded", result.message)
        result = run_tool("set_light", params={"connection": "missing", "required": True})
        self.assertEqual(result.status, "error")

    def test_io_output_pulse_returns_without_sleep_and_resets_memory_writer(self):
        sim = MemoryWriter({}, name="sim")
        writers.register_writer("sim", sim)
        started = time.perf_counter()
        result = run_tool("io_output", params={"connection": "sim", "address": "coil:7", "on_when": "ng", "pulse_ms": 50}, context={"_judge": "ng"})
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertLess(elapsed_ms, 30)
        self.assertEqual(result.outputs, {"ok": True, "active": True})
        self.assertIs(sim.state["coil:7"], True)
        self.assertTrue(wait_for(lambda: sim.state.get("coil:7") is False))
        self.assertGreaterEqual(len(sim.history), 2)

    def test_io_output_can_drive_light_channel_from_verdict_input(self):
        light = writers.LightControllerWriter({"transport": "serial", "port": "loop://", "end_char": "none", "channels": 2}, name="light")
        self.addCleanup(light.close)
        writers.register_writer("light", light)
        result = run_tool("io_output", params={"connection": "light", "address": "1", "on_when": "ok"}, inputs={"status": True})
        self.assertEqual(result.outputs, {"ok": True, "active": True})
        self.assertEqual(light.info()["channel_values"], {1: 255})
