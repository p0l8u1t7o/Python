"""Run the device conformance harness.

Accepts an MQTT connection, checks it against the platform's own rules, shows
every message as it arrives, and prints an acceptance report on exit.

    python manage.py run_test_broker
    python manage.py run_test_broker --port 1883 --command set_power_limit

For most people ``scripts/run_device_test.py`` is the better entry point: it
picks the virtualenv, self-tests the harness first, writes the report to a
file, and returns a meaningful exit code. This command is the plumbing
underneath, kept because it is occasionally useful on its own.

See ``docs/device-test-harness.md``.
"""

from __future__ import annotations

import json
import threading
import time

from django.core.management.base import BaseCommand

from services.harness import report as reporting
from services.harness import runner
from services.harness.broker import HarnessServer, HarnessState, send_command
from services.harness.console import Console, EventPrinter


class Command(BaseCommand):
    help = "Start the MQTT conformance harness for device-side development."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="0.0.0.0", help="Bind address.")
        parser.add_argument("--port", type=int, default=1883)
        parser.add_argument(
            "--command",
            default="",
            help=(
                "Send this command once the device has subscribed, to exercise "
                "the downlink path. Example: set_power_limit"
            ),
        )
        parser.add_argument(
            "--params",
            default="{}",
            help='JSON parameters for --command, e.g. \'{"limit_w": 400000}\'',
        )
        parser.add_argument(
            "--command-delay",
            type=float,
            default=8.0,
            help="Seconds to wait before sending --command.",
        )
        parser.add_argument(
            "--duration",
            type=float,
            default=0.0,
            help="Stop automatically after this many seconds. 0 runs until Ctrl-C.",
        )
        parser.add_argument(
            "--report-file",
            default="",
            help="Also write the final report to this path.",
        )

    def handle(self, *args, **options):
        self.console = Console(self.stdout)
        host, port = options["host"], options["port"]

        if runner.port_in_use(host, port):
            self.console.line()
            for line in runner.port_advice(host, port).splitlines():
                self.console.line(line)
            return

        state = HarnessState(on_event=EventPrinter(self.console))
        server = HarnessServer((host, port), state)

        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._banner(options)

        if options["command"]:
            threading.Thread(
                target=self._delayed_command, args=(state, options), daemon=True
            ).start()

        deadline = (
            time.monotonic() + options["duration"] if options["duration"] > 0 else None
        )
        try:
            while deadline is None or time.monotonic() < deadline:
                time.sleep(0.25)
        except KeyboardInterrupt:
            self.console.line()
        finally:
            server.shutdown_harness()
            time.sleep(0.4)  # let the handler score the disconnect
            self._final_report(state, options["report_file"])

    # ---- output ----------------------------------------------------------
    def _banner(self, options) -> None:
        from django.conf import settings

        from services.mqtt import topics

        self.console.rule()
        self.console.head("  ZQS 設備連線測試工具（MQTT 驗收 harness）")
        self.console.rule()
        self.console.line(f"  監聽             {options['host']}:{options['port']}")
        self.console.line(f"  Topic root       {topics.root()}")
        self.console.line(
            f"  Client ID 前綴   {settings.MQTT['CLIENT_ID_PREFIX']}:<device_id>"
        )
        self.console.line()
        self.console.line("  這不是正式 broker，只是驗收工具。它用與正式環境相同的")
        self.console.line("  程式檢查憑證、ACL 與 payload，某些項目比正式環境更嚴格。")
        self.console.line()
        self.console.warn("  等待設備連線…（Ctrl-C 結束並印出報告）")
        self.console.line()

    # ---- downlink --------------------------------------------------------
    def _delayed_command(self, state: HarnessState, options) -> None:
        time.sleep(options["command_delay"])
        session = state.only_session()
        if session is None:
            self.console.warn("!! 尚無設備連線，略過測試命令。")
            return

        try:
            params = json.loads(options["params"])
        except json.JSONDecodeError as exc:
            self.console.bad(f"!! --params 不是合法 JSON：{exc}")
            return

        sent, command_id, note = send_command(
            state, session.device_id, options["command"], params
        )
        if sent:
            self.console.warn(
                f">> 下發命令 {options['command']}  command_id={command_id}"
            )
            if note:
                self.console.bad(f"   {note}")
        else:
            self.console.bad(f"!! {note}")

    # ---- report ----------------------------------------------------------
    def _final_report(self, state: HarnessState, report_file: str) -> None:
        session = state.only_session()
        self.console.line()
        if session is None:
            self.console.warn("沒有任何設備成功連線，因此沒有報告可產生。")
            self.console.line("請確認設備指向的位址與埠號正確，且防火牆允許連入。")
            return

        text = reporting.render(
            session.checks,
            device_id=session.device_id,
            message_count=len(session.messages),
        )
        for line in text.splitlines():
            self.console.line(line)

        if report_file:
            from pathlib import Path

            path = runner.write_report(Path(report_file), text)
            self.console.dim(f"\n報告已寫入 {path}")
