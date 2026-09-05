"""TCP 介面金鑰：設了 VISION_TCP_AUTH 就要先 AUTH（PING 例外）；金鑰為空＝舊行為；追蹤裡的金鑰遮掉。"""

from __future__ import annotations

from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

from apps.vision import tcp_server


class TcpAuthTests(TestCase):
    @override_settings(VISION={**settings.VISION, "TCP_AUTH": "s3cret"})
    def test_requires_auth_before_other_commands(self):
        with mock.patch.object(tcp_server.time, "sleep"):  # 猜錯金鑰的節流不用真的等
            s = tcp_server.Session()
            self.assertFalse(s.authed)
            self.assertTrue(s.command("PING")[0]["pong"])  # 心跳不用認證
            res, shown = s.command("LIST")
            self.assertEqual(res["code"], "unauthorized")
            self.assertEqual(shown, "LIST")
            res, shown = s.command("AUTH wrong")
            self.assertEqual(res["code"], "unauthorized")
            self.assertEqual(shown, "AUTH ***")  # 追蹤不留金鑰
            self.assertFalse(s.authed)
            res, shown = s.command("AUTH s3cret")
            self.assertTrue(res["authenticated"])
            self.assertEqual(shown, "AUTH ***")
            self.assertTrue(s.authed)
            self.assertIn("flows", s.command("LIST")[0])
            # 之後再送錯的 AUTH 會把這條連線降回未認證
            self.assertEqual(s.command("AUTH nope")[0]["code"], "unauthorized")
            self.assertEqual(s.command("LIST")[0]["code"], "unauthorized")

    @override_settings(VISION={**settings.VISION, "TCP_AUTH": ""})
    def test_no_key_means_open(self):
        s = tcp_server.Session()
        self.assertTrue(s.authed)
        self.assertIn("flows", s.command("LIST")[0])
        with mock.patch.object(tcp_server.time, "sleep"):
            res, _ = s.command("AUTH anything")
        self.assertEqual(res["code"], "unauthorized")
        self.assertIn("No TCP key", res["error"])
        self.assertIn("flows", s.command("LIST")[0])  # 沒設金鑰時 AUTH 失敗也不影響

    def test_over_the_wire(self):
        import socket

        from tests.test_comm import free_port

        port = free_port()
        server = tcp_server._Server(("127.0.0.1", port), tcp_server._Handler)
        import threading

        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        with override_settings(VISION={**settings.VISION, "TCP_AUTH": "k"}), mock.patch.object(tcp_server.time, "sleep"):
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                f = sock.makefile("rwb")
                for line, expect in (("LIST", "unauthorized"), ("AUTH k", "authenticated"), ("PING", "pong")):
                    f.write((line + "\n").encode())
                    f.flush()
                    self.assertIn(expect, f.readline().decode())
