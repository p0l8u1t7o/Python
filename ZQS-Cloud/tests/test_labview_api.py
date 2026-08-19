"""LabVIEW process control: state machine, idempotence, error handling.

Real child processes, but stand-in commands instead of the Django services -
the contract under test is the supervisor's, not Django's. Plain
``unittest.TestCase``: nothing here touches the database.

Platform note: the Windows-only branches (``CREATE_NEW_PROCESS_GROUP``,
``CREATE_NO_WINDOW``, ``CTRL_BREAK_EVENT``) cannot execute on POSIX, so
:class:`WindowsFlagTests` asserts on how they are computed rather than on their
effect. Everything else - the state machine, repeat starts, the grace period
and kill, log redirection - runs on either platform.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

from services.labview import labview_api as lv

SLEEPER = "import time; time.sleep(60)"
IGNORES_TERM = (
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "time.sleep(60)"
)
EXITS_CLEAN = "import sys; sys.exit(0)"
CRASHES = "import sys; sys.exit(3)"
# Comfortably past the ~64 KB an undrained OS pipe buffer would hold.
CHATTY = "import sys\nfor _ in range(20000): print('x' * 40)\nsys.exit(0)"


class LabviewTestCase(unittest.TestCase):
    """Isolate the module's global state and point it at throwaway commands."""

    code = SLEEPER

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="zqs-labview-test-")
        self._saved = (
            lv._COMMANDS,
            lv.LOG_DIR,
            lv._STATE,
            lv._LAST_ERROR,
            lv._interpreter,
        )
        lv._COMMANDS = {name: ["-c", self.code] for name in lv._ORDER}
        lv.LOG_DIR = lv.Path(self.tmp)
        lv._STATE = {}
        lv._LAST_ERROR = ""
        lv._interpreter = lambda: sys.executable

    def tearDown(self) -> None:
        for svc in list(lv._STATE.values()):
            if svc.proc is not None:
                try:
                    svc.proc.kill()
                    svc.proc.wait(timeout=5)
                except Exception:
                    pass
                lv._close_log(svc)
        (
            lv._COMMANDS,
            lv.LOG_DIR,
            lv._STATE,
            lv._LAST_ERROR,
            lv._interpreter,
        ) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait_for_status(self, service: str, expected: int, timeout: float = 15.0) -> int:
        """Poll exactly the way a LabVIEW loop is meant to."""
        deadline = time.monotonic() + timeout
        status = lv.get_status(service)
        while status != expected and time.monotonic() < deadline:
            time.sleep(0.05)
            status = lv.get_status(service)
        return status


class ArgumentTests(LabviewTestCase):
    def test_empty_means_every_service(self):
        self.assertEqual(lv._resolve("")[0], lv._ORDER)
        self.assertEqual(lv._resolve("all")[0], lv._ORDER)
        self.assertEqual(lv._resolve(None)[0], lv._ORDER)

    def test_accepts_comma_space_and_list_forms(self):
        for value in ("worker,api", "worker api", ["worker", "api"]):
            names, unknown = lv._resolve(value)
            self.assertEqual(names, ["api", "worker"], value)  # normalised to start order
            self.assertEqual(unknown, [])

    def test_names_are_case_insensitive_and_deduplicated(self):
        names, unknown = lv._resolve("API,api,Worker")
        self.assertEqual(names, ["api", "worker"])
        self.assertEqual(unknown, [])

    def test_unknown_names_are_reported_not_raised(self):
        names, unknown = lv._resolve("api,frontend")
        self.assertEqual(names, ["api"])
        self.assertEqual(unknown, ["frontend"])

    def test_list_services_is_a_list_of_str(self):
        services = lv.list_services()
        self.assertIsInstance(services, list)
        self.assertTrue(all(isinstance(name, str) for name in services))
        self.assertEqual(services, ["api", "ingestor", "worker", "scheduler"])


class StartTests(LabviewTestCase):
    def test_start_returns_immediately(self):
        started = time.monotonic()
        code = lv.start_server("api")
        elapsed = time.monotonic() - started

        self.assertEqual(code, lv.RC_OK)
        # The child runs for 60 s; anything close to that means we waited on it.
        self.assertLess(elapsed, 2.0, "start_server blocked")
        self.assertEqual(lv.get_status("api"), lv.STATUS_RUNNING)

    def test_second_start_does_not_launch_a_second_copy(self):
        self.assertEqual(lv.start_server("api"), lv.RC_OK)
        first_pid = lv.get_pid("api")

        self.assertEqual(lv.start_server("api"), lv.RC_ALREADY_RUNNING)
        self.assertEqual(lv.get_pid("api"), first_pid)
        self.assertEqual(lv.get_status("api"), lv.STATUS_RUNNING)

    def test_partial_restart_only_starts_what_is_down(self):
        lv.start_server("api")
        first_pid = lv.get_pid("api")

        # api is up, worker is not: OK, because something was actually started.
        self.assertEqual(lv.start_server("api,worker"), lv.RC_OK)
        self.assertEqual(lv.get_pid("api"), first_pid)
        self.assertEqual(lv.get_status("worker"), lv.STATUS_RUNNING)

    def test_starting_everything_is_the_default(self):
        self.assertEqual(lv.start_server(""), lv.RC_OK)
        for name in lv.list_services():
            self.assertEqual(lv.get_status(name), lv.STATUS_RUNNING, name)
        self.assertEqual(lv.get_status(""), lv.STATUS_RUNNING)

    def test_start_while_stopping_is_refused_not_queued(self):
        lv.start_server("api")
        lv._STATE["api"].state = lv.STATUS_STOPPING
        lv._STATE["api"].kill_deadline = time.monotonic() + 30

        self.assertEqual(lv.start_server("api"), lv.RC_BUSY_STOPPING)
        self.assertIn("still stopping", lv.get_last_error())


class StopTests(LabviewTestCase):
    def test_stop_returns_immediately_and_completes_in_background(self):
        lv.start_server("api")

        started = time.monotonic()
        code = lv.stop_server("api", 5.0)
        elapsed = time.monotonic() - started

        self.assertEqual(code, lv.RC_OK)
        self.assertLess(elapsed, 1.0, "stop_server blocked for the grace period")
        # Either already reaped or on its way out - never still 'running'.
        self.assertIn(lv.get_status("api"), (lv.STATUS_STOPPING, lv.STATUS_STOPPED))
        self.assertEqual(self.wait_for_status("api", lv.STATUS_STOPPED), lv.STATUS_STOPPED)

    def test_stop_when_nothing_runs_is_not_an_error(self):
        self.assertEqual(lv.stop_server(""), lv.RC_OK)
        self.assertEqual(lv.get_status(""), lv.STATUS_STOPPED)

    def test_can_start_again_once_stopped(self):
        lv.start_server("api")
        first_pid = lv.get_pid("api")
        lv.stop_server("api", 1.0)
        self.wait_for_status("api", lv.STATUS_STOPPED)

        self.assertEqual(lv.start_server("api"), lv.RC_OK)
        self.assertNotEqual(lv.get_pid("api"), first_pid)


class StubbornChildTests(LabviewTestCase):
    """A child that ignores the polite signal must still go away."""

    code = IGNORES_TERM

    @unittest.skipIf(os.name == "nt", "SIGTERM handling is POSIX-only")
    def test_grace_period_expiry_kills_without_blocking_the_caller(self):
        lv.start_server("api")

        started = time.monotonic()
        lv.stop_server("api", 0.5)
        self.assertLess(time.monotonic() - started, 1.0)
        # Still alive right after the signal: it ignored it, as designed.
        self.assertEqual(lv.get_status("api"), lv.STATUS_STOPPING)

        self.assertEqual(
            self.wait_for_status("api", lv.STATUS_STOPPED, timeout=10.0),
            lv.STATUS_STOPPED,
            "the background reaper never killed the stubborn child",
        )

    def test_repeated_stop_keeps_the_original_deadline(self):
        # A second stop must not extend - or shorten - a shutdown in flight.
        lv.start_server("api")
        lv.stop_server("api", 30.0)
        first_deadline = lv._STATE["api"].kill_deadline

        lv.stop_server("api", 0.5)
        self.assertEqual(lv._STATE["api"].kill_deadline, first_deadline)

    def test_grace_seconds_is_clamped(self):
        lv.start_server("api")
        lv.stop_server("api", -5.0)
        remaining = lv._STATE["api"].kill_deadline - time.monotonic()
        self.assertGreater(remaining, 0.0)
        self.assertLessEqual(remaining, lv._GRACE_MIN + 0.5)

    def test_absurd_grace_is_capped(self):
        lv.start_server("api")
        lv.stop_server("api", 10_000.0)
        remaining = lv._STATE["api"].kill_deadline - time.monotonic()
        self.assertLessEqual(remaining, lv._GRACE_MAX)


class ExitTests(LabviewTestCase):
    code = CRASHES

    def test_unexpected_exit_is_reported_as_exited(self):
        lv.start_server("api")
        self.assertEqual(
            self.wait_for_status("api", lv.STATUS_EXITED), lv.STATUS_EXITED
        )

        detail = json.loads(lv.get_status_json())
        api = next(item for item in detail["services"] if item["name"] == "api")
        self.assertEqual(api["exit_code"], 3)
        self.assertEqual(api["pid"], 0)

    def test_aggregate_status_surfaces_a_crash(self):
        lv.start_server("api")
        self.wait_for_status("api", lv.STATUS_EXITED)
        self.assertEqual(lv.get_status(""), lv.STATUS_EXITED)

    def test_a_crashed_service_can_be_started_again(self):
        lv.start_server("api")
        self.wait_for_status("api", lv.STATUS_EXITED)
        self.assertEqual(lv.start_server("api"), lv.RC_OK)


class CleanExitTests(LabviewTestCase):
    code = EXITS_CLEAN

    def test_exit_zero_is_stopped_not_exited(self):
        lv.start_server("api")
        self.assertEqual(
            self.wait_for_status("api", lv.STATUS_STOPPED), lv.STATUS_STOPPED
        )


class LogRedirectionTests(LabviewTestCase):
    code = CHATTY

    def test_a_noisy_child_is_not_blocked_by_an_undrained_pipe(self):
        lv.start_server("api")
        # With stdout=PIPE and no reader this deadlocks at ~64 KB and the child
        # never exits; with a file it runs to completion.
        self.assertEqual(
            self.wait_for_status("api", lv.STATUS_STOPPED, timeout=30.0),
            lv.STATUS_STOPPED,
        )

        log = lv.Path(lv.get_log_path("api"))
        self.assertTrue(log.exists())
        self.assertGreater(log.stat().st_size, 100_000)

    def test_log_path_is_reported_for_a_valid_service(self):
        self.assertTrue(lv.get_log_path("worker").endswith("worker.log"))
        self.assertEqual(lv.get_log_path("nope"), "")
        self.assertEqual(lv.get_log_path("api,worker"), "")


class ErrorHandlingTests(LabviewTestCase):
    def test_unknown_service_returns_a_code_and_a_message(self):
        self.assertEqual(lv.start_server("frontend"), lv.RC_UNKNOWN_SERVICE)
        self.assertIn("frontend", lv.get_last_error())
        self.assertEqual(lv.stop_server("frontend"), lv.RC_UNKNOWN_SERVICE)
        self.assertEqual(lv.get_status("frontend"), lv.STATUS_UNKNOWN)

    def test_missing_interpreter_returns_a_code(self):
        lv._interpreter = lambda: ""
        self.assertEqual(lv.start_server("api"), lv.RC_NO_INTERPRETER)
        self.assertIn("interpreter", lv.get_last_error())

    def test_spawn_failure_returns_a_code(self):
        lv._interpreter = lambda: str(lv.Path(self.tmp) / "no-such-python")
        self.assertEqual(lv.start_server("api"), lv.RC_SPAWN_FAILED)
        self.assertIn("spawn failed", lv.get_last_error())
        self.assertEqual(lv.get_status("api"), lv.STATUS_STOPPED)

    def test_last_error_starts_empty_and_can_be_cleared(self):
        self.assertEqual(lv.get_last_error(), "")
        lv.start_server("frontend")
        self.assertNotEqual(lv.get_last_error(), "")
        self.assertEqual(lv.clear_last_error(), 0)
        self.assertEqual(lv.get_last_error(), "")

    def test_nothing_raises_on_junk_arguments(self):
        for value in (123, 4.5, object(), ["api", 7], {"api": 1}):
            for call in (lv.start_server, lv.stop_server, lv.get_status, lv.get_pid):
                try:
                    result = call(value)
                except Exception as exc:  # noqa: BLE001 - that is the assertion
                    self.fail(f"{call.__name__}({value!r}) raised {exc!r}")
                self.assertIsInstance(result, int)

    def test_reaper_thread_survives_a_failing_pass(self):
        calls = []

        def explode():
            calls.append(1)
            raise RuntimeError("boom")

        original = lv._reap_once
        lv._reap_once = explode
        try:
            lv._ensure_reaper()
            deadline = time.monotonic() + 3.0
            while len(calls) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            lv._reap_once = original

        self.assertGreaterEqual(len(calls), 2, "the reaper died on the first error")
        self.assertIn("boom", lv.get_last_error())


class ReturnTypeTests(LabviewTestCase):
    """LabVIEW's Python Node accepts int, float, str and lists of those only."""

    def test_every_public_function_returns_a_labview_type(self):
        lv.start_server("api")
        results = {
            "start_server": lv.start_server("api"),
            "stop_server": lv.stop_server("api"),
            "get_status": lv.get_status(""),
            "get_status_named": lv.get_status("api"),
            "get_status_json": lv.get_status_json(),
            "get_last_error": lv.get_last_error(),
            "clear_last_error": lv.clear_last_error(),
            "get_pid": lv.get_pid("api"),
            "get_log_path": lv.get_log_path("api"),
            "get_root": lv.get_root(),
            "list_services": lv.list_services(),
        }
        for name, value in results.items():
            with self.subTest(function=name):
                self.assertNotIsInstance(value, bool, "bool is not representable")
                if isinstance(value, list):
                    self.assertTrue(
                        all(isinstance(item, (int, float, str)) for item in value)
                    )
                else:
                    self.assertIsInstance(value, (int, float, str))

    def test_status_json_parses_and_describes_every_service(self):
        payload = json.loads(lv.get_status_json())
        self.assertEqual(
            [item["name"] for item in payload["services"]], lv.list_services()
        )
        for item in payload["services"]:
            self.assertIsInstance(item["status"], int)
            self.assertIsInstance(item["pid"], int)
            self.assertIsInstance(item["command"], str)
        self.assertIsInstance(payload["overall"], int)
        self.assertIsInstance(payload["error"], str)


class WindowsFlagTests(LabviewTestCase):
    """The flags cannot be exercised on POSIX; assert on how they are chosen."""

    def test_default_flags_are_new_process_group_plus_no_window(self):
        os.environ.pop("ZQS_LABVIEW_CONSOLE", None)
        flags = lv._creation_flags()
        self.assertTrue(flags & lv._CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(flags & lv._CREATE_NO_WINDOW)
        self.assertFalse(flags & lv._CREATE_NEW_CONSOLE)

    def test_console_opt_in_swaps_no_window_for_a_visible_console(self):
        os.environ["ZQS_LABVIEW_CONSOLE"] = "1"
        try:
            flags = lv._creation_flags()
        finally:
            os.environ.pop("ZQS_LABVIEW_CONSOLE", None)
        self.assertTrue(flags & lv._CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(flags & lv._CREATE_NEW_CONSOLE)
        self.assertFalse(flags & lv._CREATE_NO_WINDOW)

    def test_flag_values_match_the_win32_constants(self):
        self.assertEqual(lv._CREATE_NEW_PROCESS_GROUP, 0x00000200)
        self.assertEqual(lv._CREATE_NO_WINDOW, 0x08000000)
        self.assertEqual(lv._CREATE_NEW_CONSOLE, 0x00000010)


class CommandTests(LabviewTestCase):
    """The argv handed to Popen, checked against the real service table."""

    def setUp(self) -> None:
        super().setUp()
        lv._COMMANDS = self._saved[0]  # the genuine table, not the stubs

    def test_api_runs_with_noreload(self):
        argv = lv._argv("api", "python")
        self.assertEqual(argv[:4], ["python", "manage.py", "runserver", "--noreload"])
        self.assertEqual(argv[-1], lv._API_BIND)

    def test_every_service_maps_to_a_management_command(self):
        for name in lv.list_services():
            argv = lv._argv(name, "python")
            self.assertEqual(argv[1], "manage.py")
            self.assertTrue(argv[2])

    def test_bus_backend_defaults_to_redis_for_multi_process_services(self):
        os.environ.pop("BUS_BACKEND", None)
        self.assertEqual(lv._child_env(["worker"]).get("BUS_BACKEND"), "redis")
        self.assertNotIn("BUS_BACKEND", lv._child_env(["api"]))

    def test_an_explicit_bus_backend_is_left_alone(self):
        os.environ["BUS_BACKEND"] = "rabbitmq"
        try:
            self.assertEqual(lv._child_env(["worker"])["BUS_BACKEND"], "rabbitmq")
        finally:
            os.environ.pop("BUS_BACKEND", None)


if __name__ == "__main__":
    unittest.main()
