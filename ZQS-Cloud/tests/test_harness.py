"""The conformance harness, and the promise that makes it worth running.

The load-bearing test is
:meth:`HarnessEndToEndTests.test_a_correct_device_passes_every_required_check`
paired with the misbehaviour tests. Together they pin both halves of the
promise: a conforming device passes, and a non-conforming one is caught. A
harness that only ever says "pass" is worse than no harness, because it
converts an unknown into a false assurance.
"""

from __future__ import annotations

import socket
import threading
import time

import orjson
from django.test import TransactionTestCase

from apps.devices.models import DeviceCredential
from services.harness import checks as conformance
from services.harness import packets
from services.harness import report as reporting
from services.harness.broker import HarnessServer, HarnessState, send_command
from services.harness.simulator import ReferenceDevice
from services.mqtt import topics
from tests import factories


# ---------------------------------------------------------------------------
# Packet codec - pure, no sockets
# ---------------------------------------------------------------------------
class PacketCodecTests(TransactionTestCase):
    def test_remaining_length_round_trips(self):
        for value in (0, 1, 127, 128, 16_383, 16_384, 2_097_151, 2_097_152):
            encoded = packets.encode_remaining_length(value)
            stream = iter(encoded)
            decoded = packets.decode_remaining_length(lambda: bytes([next(stream)]))
            self.assertEqual(decoded, value, f"failed at {value}")

    def test_remaining_length_uses_the_documented_widths(self):
        self.assertEqual(len(packets.encode_remaining_length(127)), 1)
        self.assertEqual(len(packets.encode_remaining_length(128)), 2)
        self.assertEqual(len(packets.encode_remaining_length(16_384)), 3)

    def test_connect_round_trips_with_every_optional_field(self):
        original = packets.ConnectPacket(
            protocol_name="MQTT",
            protocol_level=4,
            client_id="zqs:DEV-1",
            clean_session=False,
            keepalive=45,
            username="dev-demo-DEV-1",
            password="secret",
            will_flag=True,
            will_topic="energy/devices/DEV-1/status",
            will_payload=b'{"status":"offline"}',
            will_qos=1,
            will_retain=True,
        )
        frame = packets.encode_connect(original)
        raw = packets.read_packet(_ByteStream(frame))
        decoded = packets.decode_connect(raw.body)

        self.assertEqual(raw.packet_type, packets.CONNECT)
        self.assertEqual(decoded, original)

    def test_connect_without_a_will_decodes(self):
        original = packets.ConnectPacket(
            protocol_name="MQTT",
            protocol_level=4,
            client_id="zqs:DEV-2",
            clean_session=True,
            keepalive=60,
            username="u",
            password="p",
        )
        decoded = packets.decode_connect(
            packets.read_packet(_ByteStream(packets.encode_connect(original))).body
        )
        self.assertFalse(decoded.will_flag)
        self.assertTrue(decoded.clean_session)

    def test_publish_round_trips(self):
        frame = packets.encode_publish(
            "energy/devices/DEV-1/telemetry", b'{"ts":1}', qos=1, retain=True, packet_id=7
        )
        raw = packets.read_packet(_ByteStream(frame))
        decoded = packets.decode_publish(raw.flags, raw.body)
        self.assertEqual(decoded.topic, "energy/devices/DEV-1/telemetry")
        self.assertEqual(decoded.payload, b'{"ts":1}')
        self.assertEqual(decoded.qos, 1)
        self.assertTrue(decoded.retain)
        self.assertEqual(decoded.packet_id, 7)

    def test_qos_zero_publish_has_no_packet_id(self):
        frame = packets.encode_publish("t/a", b"x")
        raw = packets.read_packet(_ByteStream(frame))
        self.assertIsNone(packets.decode_publish(raw.flags, raw.body).packet_id)

    def test_subscribe_decodes_several_filters(self):
        body = b"\x00\x0a" + packets.encode_string("a/b") + b"\x01" + packets.encode_string("c/d") + b"\x00"
        decoded = packets.decode_subscribe(body)
        self.assertEqual(decoded.packet_id, 10)
        self.assertEqual(decoded.filters, [("a/b", 1), ("c/d", 0)])

    def test_a_truncated_packet_is_rejected_not_guessed(self):
        with self.assertRaises(packets.MalformedPacket):
            packets.decode_connect(b"\x00\x04MQ")

    def test_reserved_connect_flag_is_rejected(self):
        body = packets.encode_string("MQTT") + bytes([4, 0x01]) + b"\x00\x2d"
        with self.assertRaises(packets.MalformedPacket):
            packets.decode_connect(body)

    def test_a_closed_stream_reads_as_no_packet(self):
        self.assertIsNone(packets.read_packet(_ByteStream(b"")))


class _ByteStream:
    """Minimal read()-only stream over a bytes buffer."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def read(self, size: int) -> bytes:
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


# ---------------------------------------------------------------------------
# Checks - the rules, without a socket
# ---------------------------------------------------------------------------
class ConnectCheckTests(TransactionTestCase):
    def setUp(self) -> None:
        self.device_id = "CHK-1"
        self.checks = conformance.build_checklist(self.device_id)

    def connect(self, **overrides) -> packets.ConnectPacket:
        defaults = dict(
            protocol_name="MQTT",
            protocol_level=4,
            client_id=f"zqs:{self.device_id}",
            clean_session=False,
            keepalive=45,
            username=f"dev-demo-{self.device_id}",
            password="pw",
            will_flag=True,
            will_topic=f"{topics.root()}/{self.device_id}/status",
            will_payload=orjson.dumps({"status": "offline", "reason": "lwt"}),
            will_qos=1,
            will_retain=True,
        )
        defaults.update(overrides)
        return packets.ConnectPacket(**defaults)

    def run_checks(self, **overrides):
        conformance.check_connect(self.checks, self.connect(**overrides), self.device_id)
        return self.checks

    def test_a_correct_connect_passes_all_connect_checks(self):
        checks = self.run_checks()
        for key in (
            "mqtt_version",
            "client_id_format",
            "username_format",
            "clean_session",
            "lwt_declared",
            "lwt_topic",
            "lwt_qos",
            "lwt_retain",
            "lwt_payload",
        ):
            self.assertEqual(checks[key].status, conformance.PASS, key)

    def test_a_wrong_client_id_reports_both_sides(self):
        checks = self.run_checks(client_id="LabVIEW_1")
        check = checks["client_id_format"]
        self.assertEqual(check.status, conformance.FAIL)
        self.assertEqual(check.actual, "LabVIEW_1")
        self.assertIn(f"zqs:{self.device_id}", check.expected)
        # The message names both values, not just "connection refused".
        self.assertIn("LabVIEW_1", check.detail)

    def test_clean_session_true_fails_with_the_reason(self):
        check = self.run_checks(clean_session=True)["clean_session"]
        self.assertEqual(check.status, conformance.FAIL)
        self.assertIn("下行命令", check.detail)

    def test_a_missing_will_fails_every_will_check(self):
        checks = self.run_checks(will_flag=False)
        for key in ("lwt_declared", "lwt_topic", "lwt_qos", "lwt_retain", "lwt_payload"):
            self.assertEqual(checks[key].status, conformance.FAIL, key)

    def test_a_will_on_the_wrong_topic_is_caught(self):
        check = self.run_checks(will_topic="energy/devices/OTHER/status")["lwt_topic"]
        self.assertEqual(check.status, conformance.FAIL)
        self.assertIn("OTHER", check.actual)

    def test_a_will_at_qos_zero_is_caught(self):
        self.assertEqual(self.run_checks(will_qos=0)["lwt_qos"].status, conformance.FAIL)

    def test_an_unretained_will_is_caught(self):
        self.assertEqual(
            self.run_checks(will_retain=False)["lwt_retain"].status, conformance.FAIL
        )

    def test_a_will_that_does_not_say_offline_is_caught(self):
        check = self.run_checks(will_payload=orjson.dumps({"status": "online"}))["lwt_payload"]
        self.assertEqual(check.status, conformance.FAIL)
        self.assertIn("offline", check.detail)

    def test_a_non_json_will_is_caught(self):
        check = self.run_checks(will_payload=b"offline")["lwt_payload"]
        self.assertEqual(check.status, conformance.FAIL)

    def test_an_old_protocol_version_is_caught(self):
        check = self.run_checks(protocol_level=3)["mqtt_version"]
        self.assertEqual(check.status, conformance.FAIL)
        self.assertIn("3", check.actual)

    def test_keepalive_zero_warns_rather_than_fails(self):
        check = self.run_checks(keepalive=0)["keepalive_range"]
        self.assertEqual(check.status, conformance.WARN)

    def test_a_bad_username_shape_is_caught(self):
        check = self.run_checks(username="admin")["username_format"]
        self.assertEqual(check.status, conformance.FAIL)


class AclCheckTests(TransactionTestCase):
    """The ACL predicate must agree with the production webhook."""

    def test_a_device_may_publish_its_own_topics(self):
        for suffix in ("telemetry", "status", "event", "alarm", "control/ack"):
            allowed, _ = conformance.topic_allowed(
                f"{topics.root()}/DEV-1/{suffix}", "publish", "DEV-1"
            )
            self.assertTrue(allowed, suffix)

    def test_a_device_may_not_publish_to_its_control_topic(self):
        allowed, reason = conformance.topic_allowed(
            f"{topics.root()}/DEV-1/control", "publish", "DEV-1"
        )
        self.assertFalse(allowed)
        self.assertIn("control", reason)

    def test_a_device_may_subscribe_only_to_control(self):
        allowed, _ = conformance.topic_allowed(
            f"{topics.root()}/DEV-1/control", "subscribe", "DEV-1"
        )
        self.assertTrue(allowed)
        denied, reason = conformance.topic_allowed(
            f"{topics.root()}/DEV-1/telemetry", "subscribe", "DEV-1"
        )
        self.assertFalse(denied)
        self.assertIn("telemetry", reason)

    def test_a_device_may_not_touch_another_devices_subtree(self):
        allowed, reason = conformance.topic_allowed(
            f"{topics.root()}/OTHER/telemetry", "publish", "DEV-1"
        )
        self.assertFalse(allowed)
        self.assertIn("OTHER", reason)

    def test_a_topic_outside_the_root_is_refused(self):
        allowed, reason = conformance.topic_allowed("random/topic", "publish", "DEV-1")
        self.assertFalse(allowed)
        self.assertIn(topics.root(), reason)


class ReportTests(TransactionTestCase):
    def setUp(self) -> None:
        self.checks = conformance.build_checklist("REP-1")

    def pass_all_required(self) -> None:
        for check in self.checks.values():
            if check.required:
                check.succeed("ok")

    def test_verdict_is_incomplete_before_anything_runs(self):
        self.assertEqual(reporting.verdict(self.checks), reporting.VERDICT_INCOMPLETE)

    def test_verdict_is_ready_only_when_every_required_check_passed(self):
        self.pass_all_required()
        self.assertEqual(reporting.verdict(self.checks), reporting.VERDICT_READY)

    def test_one_failure_blocks_the_verdict(self):
        self.pass_all_required()
        self.checks["publish_qos"].fail("0")
        self.assertEqual(reporting.verdict(self.checks), reporting.VERDICT_NOT_READY)

    def test_an_optional_check_left_pending_does_not_block(self):
        self.pass_all_required()  # optional ones stay pending
        self.assertEqual(reporting.verdict(self.checks), reporting.VERDICT_READY)

    def test_the_report_names_the_failures(self):
        self.pass_all_required()
        self.checks["lwt_declared"].fail("未宣告", "沒有設 will flag")
        text = reporting.render(self.checks, device_id="REP-1")
        self.assertIn("還不能接正式環境", text)
        self.assertIn("LWT 已宣告", text)

    def test_the_ready_report_still_warns_about_real_emqx(self):
        self.pass_all_required()
        text = reporting.render(self.checks, device_id="REP-1")
        self.assertIn("可以接正式環境了", text)
        # Honesty: the harness cannot prove these.
        self.assertIn("EMQX", text)
        self.assertIn("retained", text)


# ---------------------------------------------------------------------------
# End to end: the reference device against the real harness
# ---------------------------------------------------------------------------
class HarnessEndToEndTests(TransactionTestCase):
    """Both halves of the promise: correct passes, incorrect is caught."""

    def setUp(self) -> None:
        self.org = factories.organization("demo")
        self.device = factories.device(self.org, "HARNESS-1")
        self.credential, self.password = DeviceCredential.issue(self.device)

        self.state = HarnessState()
        self.server = HarnessServer(("127.0.0.1", 0), self.state)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown_harness()

    def run_device(self, *, misbehave: str = "", abrupt: bool = False) -> None:
        device = ReferenceDevice(
            device_id=self.device.device_id,
            username=self.credential.mqtt_username,
            password=self.password,
            host="127.0.0.1",
            port=self.port,
            interval=0.2,
            misbehave=misbehave,
        )
        device.run(duration=0.5, abrupt_exit=abrupt)
        # Let the handler thread finish scoring the disconnect.
        for _ in range(50):
            session = self.state.only_session()
            if session is not None and self.state.handler_for(self.device.device_id) is None:
                return
            time.sleep(0.05)

    def session(self):
        session = self.state.only_session()
        self.assertIsNotNone(session, "設備沒有成功連上 harness")
        return session

    # ---- the headline pair ----------------------------------------------
    def test_a_correct_device_passes_every_required_check(self):
        self.run_device(abrupt=True)
        checks = self.session().checks

        failures = {
            key: (check.actual, check.detail)
            for key, check in checks.items()
            if check.status == conformance.FAIL
        }
        self.assertEqual(failures, {}, f"參考設備不該有任何失敗項：{failures}")
        self.assertEqual(reporting.verdict(checks), reporting.VERDICT_READY)

    def test_a_device_with_a_wrong_client_id_is_caught(self):
        self.run_device(misbehave="bad_client_id")
        self.assertEqual(
            self.session().checks["client_id_format"].status, conformance.FAIL
        )

    def test_a_device_without_a_will_is_caught(self):
        self.run_device(misbehave="no_lwt")
        self.assertEqual(self.session().checks["lwt_declared"].status, conformance.FAIL)

    def test_a_device_using_clean_session_is_caught(self):
        self.run_device(misbehave="clean_session")
        self.assertEqual(self.session().checks["clean_session"].status, conformance.FAIL)

    def test_a_malformed_telemetry_payload_is_caught(self):
        self.run_device(misbehave="bad_payload")
        check = self.session().checks["payload_schema"]
        self.assertEqual(check.status, conformance.FAIL)
        # The reason has to name the field, not just say "invalid".
        self.assertIn("ts", check.detail)

    def test_telemetry_at_qos_zero_is_caught(self):
        self.run_device(misbehave="bad_qos")
        self.assertEqual(self.session().checks["publish_qos"].status, conformance.FAIL)

    # ---- observed traffic ------------------------------------------------
    def test_the_birth_message_is_recorded_as_retained(self):
        self.run_device()
        checks = self.session().checks
        self.assertEqual(checks["birth_status"].status, conformance.PASS)
        self.assertEqual(checks["birth_retained"].status, conformance.PASS)

    def test_telemetry_and_subscription_are_observed(self):
        self.run_device()
        session = self.session()
        self.assertEqual(session.checks["telemetry_seen"].status, conformance.PASS)
        self.assertEqual(session.checks["subscribe_control"].status, conformance.PASS)
        self.assertIn(
            topics.control_topic(self.device.device_id), session.subscriptions
        )

    def test_every_message_is_logged_with_its_flags(self):
        self.run_device()
        session = self.session()
        self.assertTrue(session.messages)
        record = session.messages[0]
        self.assertTrue(record.topic.startswith(topics.root()))
        self.assertIn(record.qos, (0, 1))
        self.assertTrue(record.payload_text)

    # ---- the will --------------------------------------------------------
    def test_an_abrupt_disconnect_delivers_the_will(self):
        self.run_device(abrupt=True)
        session = self.session()
        self.assertTrue(session.will_published)
        self.assertEqual(session.checks["lwt_delivered"].status, conformance.PASS)

    def test_a_polite_disconnect_does_not_deliver_the_will(self):
        # MQTT says a clean DISCONNECT discards the will. Reporting that as a
        # failure would send the device author chasing a non-bug.
        self.run_device(abrupt=False)
        session = self.session()
        self.assertFalse(session.will_published)
        self.assertEqual(session.checks["lwt_delivered"].status, conformance.WARN)

    # ---- downlink --------------------------------------------------------
    def test_a_command_reaches_a_subscribed_device_and_is_acknowledged(self):
        device = ReferenceDevice(
            device_id=self.device.device_id,
            username=self.credential.mqtt_username,
            password=self.password,
            host="127.0.0.1",
            port=self.port,
            interval=0.2,
        )
        thread = threading.Thread(
            target=lambda: device.run(duration=2.0, abrupt_exit=True), daemon=True
        )
        thread.start()

        for _ in range(60):
            session = self.state.only_session()
            if session and topics.control_topic(self.device.device_id) in session.subscriptions:
                break
            time.sleep(0.05)

        sent, command_id, note = send_command(
            self.state, self.device.device_id, "set_power_limit", {"limit_w": 400_000}
        )
        self.assertTrue(sent, note)
        self.assertEqual(note, "", "設備應該已經訂閱 control topic")

        thread.join(timeout=5)
        checks = self.session().checks
        self.assertEqual(checks["command_ack"].status, conformance.PASS)
        self.assertIn(command_id, checks["command_ack"].actual)

    def test_a_command_to_an_absent_device_is_reported_not_swallowed(self):
        sent, _command_id, note = send_command(self.state, "NOT-CONNECTED", "reboot")
        self.assertFalse(sent)
        self.assertIn("沒有連線", note)


class CredentialRejectionTests(TransactionTestCase):
    """A wrong password must be refused with a usable explanation."""

    def setUp(self) -> None:
        self.org = factories.organization("demo")
        self.device = factories.device(self.org, "HARNESS-2")
        self.credential, _password = DeviceCredential.issue(self.device)

        self.state = HarnessState()
        self.server = HarnessServer(("127.0.0.1", 0), self.state)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.server.shutdown_harness()

    def test_a_bad_password_is_refused_with_a_connack_code(self):
        connect = packets.ConnectPacket(
            protocol_name="MQTT",
            protocol_level=4,
            client_id=f"zqs:{self.device.device_id}",
            clean_session=False,
            keepalive=45,
            username=self.credential.mqtt_username,
            password="definitely-not-the-password",
            will_flag=True,
            will_topic=f"{topics.root()}/{self.device.device_id}/status",
            will_payload=orjson.dumps({"status": "offline"}),
            will_qos=1,
            will_retain=True,
        )
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(packets.encode_connect(connect))
            response = sock.recv(4)

        self.assertEqual(response[0] >> 4, packets.CONNACK)
        self.assertEqual(response[3], packets.CONNACK_BAD_CREDENTIALS)

        session = self.state.only_session()
        self.assertIsNotNone(session)
        check = session.checks["credentials"]
        self.assertEqual(check.status, conformance.FAIL)
        # Everything else still got checked, so one bad password does not hide
        # the other problems.
        self.assertEqual(session.checks["lwt_declared"].status, conformance.PASS)
