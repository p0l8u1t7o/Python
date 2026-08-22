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

from apps.devices.models import EdgeNodeCredential
from services.harness import checks as conformance
from services.harness import packets
from services.harness import report as reporting
from services.harness.broker import HarnessServer, HarnessState, send_command
from services.harness.simulator import ReferenceDevice
from services.sparkplug import payload as sp
from services.sparkplug import topics
from services.sparkplug.datatypes import DataType
from services.sparkplug.topics import MessageType
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
            will_topic="spBv1.0/demo/NDEATH/DEV-1",
            will_payload=b"\x08\x01",
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
def _will_payload(bd_seq: int = 1) -> bytes:
    """A minimal, valid NDEATH: a bdSeq metric and nothing else."""
    message = sp.new_payload()
    sp.add_metric(message, sp.BDSEQ_METRIC, bd_seq, datatype=DataType.Int64)
    return sp.encode(message)


class ConnectCheckTests(TransactionTestCase):
    def setUp(self) -> None:
        self.group_id = "demo"
        self.device_id = "CHK-1"
        self.checks = conformance.build_checklist(self.group_id, self.device_id)

    def connect(self, **overrides) -> packets.ConnectPacket:
        defaults = dict(
            protocol_name="MQTT",
            protocol_level=4,
            client_id=f"zqs:{self.device_id}",
            # Sparkplug requires a clean session, the opposite of the old
            # JSON protocol - see services/harness/checks.py.
            clean_session=True,
            keepalive=45,
            username=f"node-{self.group_id}-{self.device_id}",
            password="pw",
            will_flag=True,
            will_topic=topics.build(
                self.group_id, MessageType.NDEATH, self.device_id
            ),
            will_payload=_will_payload(),
            will_qos=1,
            # A retained will would outlive the session it describes.
            will_retain=False,
        )
        defaults.update(overrides)
        return packets.ConnectPacket(**defaults)

    def run_checks(self, **overrides):
        conformance.check_connect(
            self.checks, self.connect(**overrides), self.group_id, self.device_id
        )
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

    def test_a_persistent_session_fails_with_the_reason(self):
        check = self.run_checks(clean_session=False)["clean_session"]
        self.assertEqual(check.status, conformance.FAIL)
        self.assertIn("clean session", check.detail)

    def test_a_missing_will_fails_every_will_check(self):
        checks = self.run_checks(will_flag=False)
        for key in ("lwt_declared", "lwt_topic", "lwt_qos", "lwt_retain", "lwt_payload"):
            self.assertEqual(checks[key].status, conformance.FAIL, key)

    def test_a_will_on_the_wrong_topic_is_caught(self):
        check = self.run_checks(will_topic="spBv1.0/demo/NDEATH/OTHER")["lwt_topic"]
        self.assertEqual(check.status, conformance.FAIL)
        self.assertIn("OTHER", check.actual)

    def test_a_will_at_qos_zero_is_caught(self):
        self.assertEqual(self.run_checks(will_qos=0)["lwt_qos"].status, conformance.FAIL)

    def test_a_retained_will_is_caught(self):
        """It would outlive the session it describes."""
        check = self.run_checks(will_retain=True)["lwt_retain"]
        self.assertEqual(check.status, conformance.FAIL)
        self.assertIn("retained", check.detail)

    def test_a_will_without_bdseq_is_caught(self):
        """Without it, a late death cannot be told from a current one."""
        check = self.run_checks(will_payload=sp.encode(sp.new_payload()))["lwt_payload"]
        self.assertEqual(check.status, conformance.FAIL)
        self.assertIn("bdSeq", check.detail)

    def test_a_will_that_is_not_protobuf_is_caught(self):
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

    GROUP = "demo"
    NODE = "DEV-1"

    def allowed(self, topic: str, action: str = "publish"):
        return conformance.topic_allowed(topic, action, self.GROUP, self.NODE)

    def test_a_node_may_publish_its_own_message_types(self):
        for message_type in (
            MessageType.NBIRTH,
            MessageType.NDEATH,
            MessageType.NDATA,
        ):
            allowed, _ = self.allowed(
                topics.build(self.GROUP, message_type, self.NODE)
            )
            self.assertTrue(allowed, message_type)

        for message_type in (
            MessageType.DBIRTH,
            MessageType.DDEATH,
            MessageType.DDATA,
        ):
            allowed, _ = self.allowed(
                topics.build(self.GROUP, message_type, self.NODE, "METER-1")
            )
            self.assertTrue(allowed, message_type)

    def test_a_node_may_not_publish_commands(self):
        """A node that could publish NCMD could command its neighbours."""
        allowed, reason = self.allowed(
            topics.build(self.GROUP, MessageType.NCMD, self.NODE)
        )
        self.assertFalse(allowed)
        self.assertIn("NCMD", reason)

    def test_a_node_may_subscribe_only_to_its_commands(self):
        allowed, _ = self.allowed(
            topics.build(self.GROUP, MessageType.NCMD, self.NODE), "subscribe"
        )
        self.assertTrue(allowed)

        # The wildcard form a real gateway uses for its devices.
        allowed, _ = self.allowed(
            f"{topics.build(self.GROUP, MessageType.DCMD, self.NODE)}/+", "subscribe"
        )
        self.assertTrue(allowed)

        denied, reason = self.allowed(
            topics.build(self.GROUP, MessageType.NDATA, self.NODE), "subscribe"
        )
        self.assertFalse(denied)
        self.assertIn("NDATA", reason)

    def test_a_node_may_not_touch_another_nodes_subtree(self):
        allowed, reason = self.allowed(
            topics.build(self.GROUP, MessageType.NDATA, "OTHER")
        )
        self.assertFalse(allowed)
        self.assertIn("OTHER", reason)

    def test_a_node_may_not_reach_into_another_group(self):
        allowed, reason = self.allowed(
            topics.build("other-tenant", MessageType.NDATA, self.NODE)
        )
        self.assertFalse(allowed)
        self.assertIn("other-tenant", reason)

    def test_a_wildcard_above_the_device_level_is_refused(self):
        """Otherwise one node subscribes to every command on the broker."""
        allowed, _ = self.allowed(
            f"spBv1.0/{self.GROUP}/DCMD/+/#", "subscribe"
        )
        self.assertFalse(allowed)

    def test_a_topic_outside_the_namespace_is_refused(self):
        allowed, reason = self.allowed("random/topic")
        self.assertFalse(allowed)
        self.assertIn(topics.NAMESPACE, reason)


class ReportTests(TransactionTestCase):
    def setUp(self) -> None:
        self.checks = conformance.build_checklist("demo", "REP-1")

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
        self.checks["publish_retain"].fail("true")
        self.assertEqual(reporting.verdict(self.checks), reporting.VERDICT_NOT_READY)

    def test_an_optional_check_left_pending_does_not_block(self):
        self.pass_all_required()  # optional ones stay pending
        self.assertEqual(reporting.verdict(self.checks), reporting.VERDICT_READY)

    def test_the_report_names_the_failures(self):
        self.pass_all_required()
        self.checks["lwt_declared"].fail("未宣告", "沒有設 will flag")
        text = reporting.render(self.checks, device_id="REP-1")
        self.assertIn("還不能接正式環境", text)
        self.assertIn("NDEATH 已宣告為遺言", text)

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
        self.node = self.device.edge_node
        self.credential, self.password = EdgeNodeCredential.issue(self.node)

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
            group_id=self.node.group_id,
            node_id=self.node.node_id,
            host="127.0.0.1",
            port=self.port,
            interval=0.2,
            misbehave=misbehave,
        )
        device.run(duration=0.5, abrupt_exit=abrupt)
        # Let the handler thread finish scoring the disconnect.
        for _ in range(50):
            session = self.state.only_session()
            if session is not None and self.state.handler_for(self.node.node_id) is None:
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

    def test_a_device_keeping_its_session_is_caught(self):
        self.run_device(misbehave="clean_session")
        self.assertEqual(self.session().checks["clean_session"].status, conformance.FAIL)

    def test_a_malformed_payload_is_caught(self):
        self.run_device(misbehave="bad_payload")
        check = self.session().checks["payload_schema"]
        self.assertEqual(check.status, conformance.FAIL)
        # The reason has to say what was wrong, not just "invalid".
        self.assertIn("protobuf", check.detail.lower())

    def test_a_retained_will_is_caught(self):
        self.run_device(misbehave="retained_will")
        self.assertEqual(self.session().checks["lwt_retain"].status, conformance.FAIL)

    def test_data_at_the_wrong_qos_is_warned_about(self):
        """The platform accepts it; other Sparkplug hosts may not."""
        self.run_device(misbehave="bad_qos")
        self.assertEqual(self.session().checks["publish_qos"].status, conformance.WARN)

    # ---- observed traffic ------------------------------------------------
    def test_the_births_are_recorded(self):
        self.run_device()
        checks = self.session().checks
        self.assertEqual(checks["nbirth_seen"].status, conformance.PASS)
        self.assertEqual(checks["dbirth_seen"].status, conformance.PASS)
        self.assertEqual(checks["nbirth_seq"].status, conformance.PASS)
        self.assertEqual(checks["nbirth_bdseq"].status, conformance.PASS)

    def test_data_and_subscription_are_observed(self):
        self.run_device()
        session = self.session()
        self.assertEqual(session.checks["ddata_seen"].status, conformance.PASS)
        self.assertEqual(session.checks["subscribe_ncmd"].status, conformance.PASS)
        self.assertIn(
            topics.node_command(self.node.group_id, self.node.node_id),
            session.subscriptions,
        )

    def test_the_birth_assigns_aliases(self):
        """Without them every later message repeats the full metric names."""
        self.run_device()
        self.assertEqual(self.session().checks["birth_aliases"].status, conformance.PASS)

    def test_the_sequence_is_continuous(self):
        self.run_device()
        self.assertEqual(
            self.session().checks["seq_monotonic"].status, conformance.PASS
        )

    def test_every_message_is_logged_with_its_flags(self):
        self.run_device()
        session = self.session()
        self.assertTrue(session.messages)
        record = session.messages[0]
        self.assertTrue(record.topic.startswith(topics.NAMESPACE))
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
            group_id=self.node.group_id,
            node_id=self.node.node_id,
            host="127.0.0.1",
            port=self.port,
            interval=0.2,
        )
        thread = threading.Thread(
            target=lambda: device.run(duration=2.0, abrupt_exit=True), daemon=True
        )
        thread.start()

        dcmd_prefix = topics.build(
            self.node.group_id, MessageType.DCMD, self.node.node_id
        )
        for _ in range(60):
            session = self.state.only_session()
            if session and any(
                f.startswith(dcmd_prefix) for f in session.subscriptions
            ):
                break
            time.sleep(0.05)

        sent, command_id, note = send_command(
            self.state,
            self.node.node_id,
            "set_power_limit",
            {"limit_w": 400_000},
            target_device=self.device.device_id,
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
        self.credential, _password = EdgeNodeCredential.issue(self.device.edge_node)

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
            clean_session=True,
            keepalive=45,
            username=self.credential.mqtt_username,
            password="definitely-not-the-password",
            will_flag=True,
            will_topic=topics.build(
                self.device.edge_node.group_id,
                MessageType.NDEATH,
                self.device.device_id,
            ),
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
