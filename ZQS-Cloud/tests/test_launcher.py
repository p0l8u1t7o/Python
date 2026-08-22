"""The one-command launcher, and the guarantee it is supposed to provide.

``run_device_test.py self-test`` exists to answer one question: *is the harness
itself trustworthy?* That answer is only worth anything if the self-test would
actually go red when the harness stops catching faults. So the tests that
matter most here are the ones that feed :func:`_score_scenario` a harness that
under-reports and check that the self-test refuses to call it healthy.

The end-to-end scenario runs are kept to two - one good, one broken - because
each costs a real socket and a couple of seconds; the full seven-scenario sweep
is what the launcher does when a person runs it.
"""

from __future__ import annotations

import io
import socket
import threading
from types import SimpleNamespace

from django.test import TransactionTestCase

from apps.accounts.models import Organization
from apps.devices.models import Device, EdgeNode, EdgeNodeCredential
from services.harness import checks as conformance
from services.harness import report as reporting
from services.harness import runner
from services.harness.console import Console, EventPrinter
from tests import factories


def _session(checks, message_count: int = 3):
    return SimpleNamespace(checks=checks, messages=[None] * message_count)


def _all_passing(device_id: str = "SCORE-1"):
    checks = conformance.build_checklist("demo", device_id)
    for check in checks.values():
        check.succeed("ok")
    return checks


# ---------------------------------------------------------------------------
# The self-test has to be able to fail
# ---------------------------------------------------------------------------
class ScenarioScoringTests(TransactionTestCase):
    """A green self-test must mean something."""

    def scenario(self, key: str) -> runner.Scenario:
        return next(s for s in runner.SELF_TEST_SCENARIOS if s.key == key)

    def test_a_harness_that_misses_a_fault_is_reported_as_broken(self):
        # The scenario deliberately breaks the last will, but this pretend
        # harness noticed nothing. That is the single most dangerous failure
        # mode - it would wave a broken device through - so it must be loud.
        scenario = self.scenario("no_lwt")
        result = runner._score_scenario(scenario, _session(_all_passing()), [])

        self.assertFalse(result.ok)
        self.assertTrue(
            any("沒有抓到" in problem for problem in result.problems),
            result.problems,
        )
        self.assertIn("NDEATH 已宣告為遺言", " ".join(result.problems))

    def test_a_harness_that_invents_a_fault_is_also_reported(self):
        # Over-reporting sends a device author hunting for a bug that is not
        # there, so it fails the self-test just as under-reporting does.
        scenario = self.scenario("bad_client_id")
        checks = _all_passing()
        checks["client_id_format"].fail("LabVIEW_1")
        checks["publish_qos"].fail("0")  # nothing in this scenario causes it

        result = runner._score_scenario(scenario, _session(checks), [])

        self.assertFalse(result.ok)
        self.assertTrue(any("多報" in problem for problem in result.problems))
        self.assertIn("上行 QoS", " ".join(result.problems))

    def test_exactly_the_expected_failure_is_accepted(self):
        scenario = self.scenario("bad_client_id")
        checks = _all_passing()
        checks["client_id_format"].fail("LabVIEW_1")

        result = runner._score_scenario(scenario, _session(checks), [])

        self.assertTrue(result.ok, result.problems)
        self.assertEqual(result.actual_failures, frozenset({"client_id_format"}))

    def test_a_check_that_should_have_passed_but_is_pending_is_caught(self):
        # "Never observed" is not "fine". The normal scenario sends a command,
        # so a missing ack means the exchange did not happen at all.
        scenario = self.scenario("normal")
        checks = _all_passing()
        checks["command_ack"].status = conformance.PENDING

        result = runner._score_scenario(scenario, _session(checks), [])

        self.assertFalse(result.ok)
        self.assertIn("命令回覆", " ".join(result.problems))

    def test_an_ack_that_never_arrived_must_not_be_scored_as_passing(self):
        scenario = self.scenario("no_ack")
        checks = _all_passing()  # includes command_ack = pass, which is a lie

        result = runner._score_scenario(scenario, _session(checks), [])

        self.assertFalse(result.ok)
        self.assertIn("應該維持「未測」", " ".join(result.problems))

    def test_a_wrong_verdict_is_caught_even_when_the_checks_line_up(self):
        scenario = self.scenario("clean_session")
        checks = _all_passing()
        checks["clean_session"].fail("true")
        # A required failure must make the verdict not_ready; if the report
        # said "ready" anyway, the failure would be cosmetic.
        result = runner._score_scenario(scenario, _session(checks), [])
        self.assertTrue(result.ok, result.problems)

        checks["clean_session"].required = False
        stale = runner._score_scenario(scenario, _session(checks), [])
        self.assertFalse(stale.ok)
        self.assertIn("結論應為", " ".join(stale.problems))

    def test_earlier_problems_are_kept_not_overwritten(self):
        scenario = self.scenario("bad_client_id")
        checks = _all_passing()
        checks["client_id_format"].fail("LabVIEW_1")

        result = runner._score_scenario(scenario, _session(checks), ["連線逾時"])

        self.assertFalse(result.ok)
        self.assertIn("連線逾時", result.problems)


# ---------------------------------------------------------------------------
# End to end, through the real socket path
# ---------------------------------------------------------------------------
class SelfTestRunTests(TransactionTestCase):
    """Two scenarios for real, to prove the plumbing works at all."""

    def setUp(self) -> None:
        org = factories.organization("demo")
        device = factories.device(org, "LAUNCH-1")
        credential, password = EdgeNodeCredential.issue(device.edge_node)
        self.credentials = runner.Credentials(
            device.device_id,
            credential.mqtt_username,
            password,
            group_id=device.edge_node.group_id,
            node_id=device.edge_node.node_id,
        )

    def test_the_reference_device_satisfies_the_normal_scenario(self):
        scenario = next(s for s in runner.SELF_TEST_SCENARIOS if s.key == "normal")
        result = runner.run_scenario(scenario, self.credentials)

        self.assertTrue(result.ok, result.problems)
        self.assertEqual(result.verdict, reporting.VERDICT_READY)
        self.assertGreater(result.message_count, 0)

    def test_a_broken_reference_device_trips_exactly_its_own_check(self):
        scenario = next(s for s in runner.SELF_TEST_SCENARIOS if s.key == "bad_payload")
        result = runner.run_scenario(scenario, self.credentials)

        self.assertTrue(result.ok, result.problems)
        self.assertEqual(result.actual_failures, frozenset({"payload_schema"}))

    def test_run_self_test_reports_every_scenario_it_runs(self):
        started: list[str] = []
        done: list[bool] = []

        results = runner.run_self_test(
            self.credentials,
            only="clean_session",
            on_scenario_start=lambda s: started.append(s.key),
            on_scenario_done=lambda r: done.append(r.ok),
        )

        self.assertEqual(started, ["clean_session"])
        self.assertEqual(len(results), 1)
        self.assertEqual(len(done), 1)
        self.assertTrue(results[0].ok, results[0].problems)


class ProvisioningTests(TransactionTestCase):
    """The throwaway device must be genuinely throwaway."""

    def setUp(self) -> None:
        factories.organization("demo")

    def test_credentials_authenticate_against_production_code(self):
        from apps.devices.edge_nodes import authenticate_edge_node

        with runner.provision_selftest_device() as credentials:
            node = authenticate_edge_node(credentials.username, credentials.password)
            self.assertIsNotNone(node)
            self.assertEqual(node.node_id, credentials.node_id)

    def test_the_device_is_removed_afterwards(self):
        with runner.provision_selftest_device() as credentials:
            device_id = credentials.device_id
            self.assertTrue(Device.objects.filter(device_id=device_id).exists())

        self.assertFalse(Device.objects.filter(device_id=device_id).exists())

    def test_it_is_removed_even_when_the_run_blows_up(self):
        # An interrupted self-test must not leave a working set of MQTT
        # credentials lying around in the operator's database.
        with self.assertRaises(RuntimeError):
            with runner.provision_selftest_device() as credentials:
                device_id = credentials.device_id
                raise RuntimeError("boom")

        self.assertFalse(Device.objects.filter(device_id=device_id).exists())

    def test_an_existing_organisation_is_reused_rather_than_multiplied(self):
        before = Organization.objects.count()
        with runner.provision_selftest_device():
            pass
        self.assertEqual(Organization.objects.count(), before)

    def test_leftovers_from_a_crashed_run_are_swept_up(self):
        org = Organization.objects.first()
        node = EdgeNode.objects.create(
            organization=org,
            node_id=f"{runner.SELFTEST_PREFIX}STALE001",
            name="stale",
        )
        Device.objects.create(
            organization=org,
            edge_node=node,
            device_id=f"{runner.SELFTEST_PREFIX}STALE001",
            name="stale",
        )

        with runner.provision_selftest_device():
            pass

        self.assertFalse(
            Device.objects.filter(device_id__startswith=runner.SELFTEST_PREFIX).exists()
        )
        self.assertFalse(
            EdgeNode.objects.filter(node_id__startswith=runner.SELFTEST_PREFIX).exists()
        )


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
class PortTests(TransactionTestCase):
    def test_a_listening_port_is_detected(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            self.assertTrue(runner.port_in_use("127.0.0.1", port))
        finally:
            listener.close()

    def test_a_free_port_is_not_reported_as_in_use(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.assertFalse(runner.port_in_use("127.0.0.1", port))

    def test_a_wildcard_bind_is_probed_on_loopback(self):
        # Connecting to 0.0.0.0 is not meaningful; the probe has to translate.
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            self.assertTrue(runner.port_in_use("0.0.0.0", port))
        finally:
            listener.close()

    def test_the_advice_offers_a_way_out(self):
        advice = runner.port_advice("0.0.0.0", 1883)
        self.assertIn("1883", advice)
        self.assertIn("--port 2883", advice)  # a concrete alternative
        self.assertIn("netstat", advice)
        self.assertIn("EMQX", advice)

    def test_the_advice_does_not_claim_a_custom_port_is_the_mqtt_default(self):
        self.assertNotIn("預設埠", runner.port_advice("0.0.0.0", 18830))


# ---------------------------------------------------------------------------
# Report files
# ---------------------------------------------------------------------------
class ReportFileTests(TransactionTestCase):
    def test_the_filename_carries_mode_device_and_timestamp(self):
        from pathlib import Path

        path = runner.report_path(Path("/tmp"), mode="device", device_id="ZQS-BESS-0001")
        self.assertEqual(path.parent.name, "logs")
        self.assertTrue(path.name.startswith("device-test-device-ZQS-BESS-0001-"))
        self.assertTrue(path.name.endswith(".txt"))

    def test_a_device_id_cannot_escape_the_logs_directory(self):
        from pathlib import Path

        path = runner.report_path(Path("/tmp"), mode="device", device_id="../../etc/passwd")
        self.assertEqual(path.parent, Path("/tmp/logs"))
        self.assertNotIn("..", path.name)

    def test_chinese_survives_the_round_trip(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temporary:
            path = runner.write_report(
                Path(temporary) / "報告.txt", "結論：可以接正式環境了。"
            )
            # utf-8-sig on the way in, so Notepad and Excel guess right.
            self.assertEqual(
                path.read_text(encoding="utf-8-sig").strip(), "結論：可以接正式環境了。"
            )
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_the_logs_directory_is_created_on_demand(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temporary:
            path = runner.write_report(Path(temporary) / "deep" / "nested" / "r.txt", "x")
            self.assertTrue(path.exists())


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------
class ConsoleTests(TransactionTestCase):
    def test_no_escape_codes_when_colour_is_off(self):
        buffer = io.StringIO()
        console = Console(buffer, colour=False)
        console.bad("失敗")
        self.assertEqual(buffer.getvalue(), "失敗\n")

    def test_escape_codes_when_colour_is_on(self):
        buffer = io.StringIO()
        console = Console(buffer, colour=True)
        console.ok("通過")
        self.assertIn("\033[32m", buffer.getvalue())
        self.assertIn("通過", buffer.getvalue())

    def test_a_closed_stream_does_not_take_the_run_down(self):
        # The report file is the record; losing the terminal must not lose it.
        buffer = io.StringIO()
        console = Console(buffer, colour=False)
        buffer.close()
        console.line("anything")  # must not raise

    def test_the_printer_shows_failures_and_hides_the_passes(self):
        buffer = io.StringIO()
        printer = EventPrinter(Console(buffer, colour=False))
        checks = _all_passing("PRINT-1")
        checks["lwt_declared"].fail("未宣告", "CONNECT 沒有設 will flag。")

        printer("connect", {"device_id": "PRINT-1", "accepted": True, "checks": checks})
        output = buffer.getvalue()

        self.assertIn("NDEATH 已宣告為遺言", output)
        self.assertIn("CONNECT 沒有設 will flag。", output)
        # A wall of green would bury the one line that matters.
        self.assertNotIn("MQTT 協定版本", output)

    def test_an_unknown_event_is_ignored_rather_than_crashing(self):
        buffer = io.StringIO()
        printer = EventPrinter(Console(buffer, colour=False))
        printer("something_new", {"whatever": 1})
        self.assertEqual(buffer.getvalue(), "")

    def test_a_bad_display_never_stops_ingest(self):
        # HarnessState.emit swallows display errors on purpose: a formatting
        # bug must not cost the device author their test run.
        from services.harness.broker import HarnessState

        def explode(_kind, _payload):
            raise ValueError("bad format string")

        state = HarnessState(on_event=explode)
        state.emit("connection", {"peer": "1.2.3.4:5", "phase": "opened"})

    def test_a_will_event_prints_the_payload(self):
        buffer = io.StringIO()
        printer = EventPrinter(Console(buffer, colour=False))
        printer(
            "will",
            {"topic": "energy/devices/A/status", "payload": b'{"status":"offline"}'},
        )
        self.assertIn("遺言", buffer.getvalue())
        self.assertIn("offline", buffer.getvalue())


class ExitCodeTests(TransactionTestCase):
    """The codes are a public interface: batch files will branch on them."""

    def test_they_are_distinct(self):
        codes = [
            runner.EXIT_OK,
            runner.EXIT_FAILED,
            runner.EXIT_USAGE,
            runner.EXIT_INCOMPLETE,
            runner.EXIT_ABORTED,
        ]
        self.assertEqual(len(set(codes)), len(codes))

    def test_only_success_is_zero(self):
        self.assertEqual(runner.EXIT_OK, 0)
        for code in (
            runner.EXIT_FAILED,
            runner.EXIT_USAGE,
            runner.EXIT_INCOMPLETE,
            runner.EXIT_ABORTED,
        ):
            self.assertNotEqual(code, 0)


class ThreadHygieneTests(TransactionTestCase):
    """A finished scenario must not leave anything running."""

    def test_no_harness_threads_survive_a_scenario(self):
        org = factories.organization("demo")
        device = factories.device(org, "THREAD-1")
        credential, password = EdgeNodeCredential.issue(device.edge_node)
        credentials = runner.Credentials(
            device.device_id,
            credential.mqtt_username,
            password,
            group_id=device.edge_node.group_id,
            node_id=device.edge_node.node_id,
        )

        before = threading.active_count()
        scenario = next(s for s in runner.SELF_TEST_SCENARIOS if s.key == "clean_session")
        runner.run_scenario(scenario, credentials)

        # Daemon threads unwind after the socket closes; allow a little slack
        # rather than asserting an exact count and inviting a flaky test.
        import time

        for _ in range(40):
            if threading.active_count() <= before + 1:
                break
            time.sleep(0.1)
        self.assertLessEqual(threading.active_count(), before + 1)
