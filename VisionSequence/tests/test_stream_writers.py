"""串流型通訊連線：serial/UDP/TCP server 共用收行、編碼與回覆規則。"""

from __future__ import annotations

import socket
import time
from unittest import mock

from django.test import SimpleTestCase

from apps.comm import writers


LF = bytes([10])
CR = bytes([13])


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(pred, timeout: float = 3.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


class SerialStreamWriterTests(SimpleTestCase):
    def test_loop_url_receives_hex_line_and_rule_reply(self):
        calls: list[str] = []

        def match(line: str):
            calls.append(line)
            return {"_raw": "4F 4B"} if line == "4142" else None

        with mock.patch("apps.vision.tcp_server.match_rules", side_effect=match):
            writer = writers.SerialStreamWriter({"port": "loop://", "encoding": "hex", "end_char": "\\n", "timeout_s": 0.5}, name="loop")
            self.addCleanup(writer.close)
            out = writer.send_text("41 42")
            self.assertEqual(out["bytes"], 3)
            self.assertTrue(wait_for(lambda: "4142" in calls))
            self.assertTrue(wait_for(lambda: "4F4B" in calls))
            info = writer.info()
            self.assertEqual(info["last_line"], "4F4B")
            self.assertGreaterEqual(info["lines_received"], 2)

    def test_custom_end_and_closed_errors_are_explicit(self):
        writer = writers.SerialStreamWriter({"port": "loop://", "end_char": "custom", "end_custom": "\\t"}, name="loop")
        self.addCleanup(writer.close)
        writer.close()
        with self.assertRaises(writers.CommError) as cm:
            writer.send_text("PING")
        self.assertIn("closed", str(cm.exception))


class UdpStreamWriterTests(SimpleTestCase):
    def test_send_and_receive_line(self):
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver.bind(("127.0.0.1", 0))
        self.addCleanup(receiver.close)
        writer = writers.UdpStreamWriter({"host": "127.0.0.1", "port": receiver.getsockname()[1], "timeout_s": 0.5}, name="udp-out")
        self.addCleanup(writer.close)
        writer.send_text("PING")
        data, _ = receiver.recvfrom(1024)
        self.assertEqual(data, b"PING\n")

        calls: list[str] = []
        bind_port = free_port()
        with mock.patch("apps.vision.tcp_server.match_rules", side_effect=lambda line: calls.append(line) or None):
            listener = writers.UdpStreamWriter({"host": "127.0.0.1", "port": receiver.getsockname()[1], "bind_port": bind_port}, name="udp-in")
            self.addCleanup(listener.close)
            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.addCleanup(sender.close)
            sender.sendto(b"SCAN A17\r\n", ("127.0.0.1", bind_port))
            self.assertTrue(wait_for(lambda: calls == ["SCAN A17"]))
            self.assertEqual(listener.info()["last_line"], "SCAN A17")


class TcpServerTextWriterTests(SimpleTestCase):
    def test_broadcasts_to_all_clients_and_receives_rules(self):
        calls: list[str] = []
        with mock.patch("apps.vision.tcp_server.match_rules", side_effect=lambda line: calls.append(line) or None):
            writer = writers.TcpServerTextWriter({"host": "127.0.0.1", "port": free_port(), "max_clients": 2}, name="tcp-dev")
            self.addCleanup(writer.close)
            a = socket.create_connection(("127.0.0.1", writer.port), timeout=2)
            b = socket.create_connection(("127.0.0.1", writer.port), timeout=2)
            self.addCleanup(a.close)
            self.addCleanup(b.close)
            self.assertTrue(wait_for(lambda: writer.info()["clients"] == 2))
            writer.send_text("READY")
            self.assertEqual(a.recv(1024), b"READY\n")
            self.assertEqual(b.recv(1024), b"READY\n")
            a.sendall(b"GO 1\n")
            self.assertTrue(wait_for(lambda: calls == ["GO 1"]))

    def test_overflowing_line_is_dropped_whole_and_the_next_line_stays_clean(self):
        """設備送了一行超過 64 KB 又沒有結尾字元時，殘餘不能黏到下一行去。"""
        got: list[str] = []
        port = free_port()
        with mock.patch("apps.vision.tcp_server.match_rules", side_effect=lambda line: got.append(line) or None):
            writer = writers.TcpServerTextWriter({"host": "127.0.0.1", "port": port, "max_clients": 2}, name="tcp-flood")
            self.addCleanup(writer.close)
            client = socket.create_connection(("127.0.0.1", port), timeout=2)
            self.addCleanup(client.close)
            self.assertTrue(wait_for(lambda: writer.info()["clients"] == 1))
            client.sendall(b"X" * 70000 + LF)       # 這一整行（含結尾）就是被灌爆的那一行
            self.assertTrue(wait_for(lambda: writer._buffer_warnings >= 1))  # noqa: SLF001
            client.sendall(b"AFTER" + LF)           # 之後真正的下一行
            self.assertTrue(wait_for(lambda: got == ["AFTER"]))

    def test_a_device_sending_crlf_while_the_setting_says_lf(self):
        """終止字元設 LF、設備照樣送 CRLF：行尾那個 CR 是框線不是內容。"""
        got: list[str] = []
        with mock.patch("apps.vision.tcp_server.match_rules", side_effect=lambda line: got.append(line) or None):
            writer = writers.SerialStreamWriter({"port": "loop://", "end_char": "\n", "timeout_s": 0.5}, name="crlf-dev")
            self.addCleanup(writer.close)
            writer.send_text("SCAN A17" + CR.decode())
            self.assertTrue(wait_for(lambda: got == ["SCAN A17"]))

    def test_connections_that_receive_start_on_their_own(self):
        """條碼槍只送不收命令：連線沒有自動開起來就永遠收不到東西。"""

        class _Conn:
            def __init__(self, kind, config):
                self.id, self.kind, self.config, self.is_enabled = 1, kind, config, True

        self.assertTrue(writers.should_autostart(_Conn("serial", {"port": "loop://"})))
        self.assertTrue(writers.should_autostart(_Conn("tcp_server_text", {"host": "127.0.0.1", "port": 5002})))
        self.assertTrue(writers.should_autostart(_Conn("udp", {"host": "127.0.0.1", "port": 5000, "bind_port": 5001})))
        # 只送不收的 UDP 沒必要一直開著；既有的種類也不能被這條改到。
        self.assertFalse(writers.should_autostart(_Conn("udp", {"host": "127.0.0.1", "port": 5000})))
        self.assertFalse(writers.should_autostart(_Conn("modbus_tcp", {"host": "127.0.0.1", "port": 502})))
        self.assertFalse(writers.should_autostart(_Conn("tcp_client", {"host": "127.0.0.1", "port": 5003})))

    def test_kind_catalogue_puts_streams_on_devices_page(self):
        kinds = {item["kind"]: item for item in writers.kinds()}
        self.assertEqual(kinds["serial"]["section"], "devices")
        self.assertEqual(kinds["udp"]["section"], "devices")
        self.assertEqual(kinds["tcp_server_text"]["section"], "devices")
        self.assertEqual(kinds["light"]["section"], "devices")
        self.assertIn("end_char", kinds["serial"]["fields"])
        self.assertIn("bind_port", kinds["udp"]["fields"])
        self.assertIn("max_clients", kinds["tcp_server_text"]["fields"])
        self.assertIn("brightness_template", kinds["light"]["fields"])
