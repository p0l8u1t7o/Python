#!/usr/bin/env python
"""One command to test a device against the platform's MQTT rules.

    python scripts\\run_device_test.py self-test
    python scripts\\run_device_test.py device --device ZQS-BESS-0001

Two modes, in the order you should use them:

**self-test** proves the tool itself works. It runs a known-good reference
device (must pass everything), then a series of deliberately broken ones (each
must fail exactly the check it breaks). Without this step, a green report from
the device mode means nothing - a harness that always says "pass" is
indistinguishable from a working one until it lets a broken device through.

**device** waits for your real client - LabVIEW or otherwise - shows every
message as it arrives, and prints an acceptance report when you stop it.

Run it with any Python. It re-executes itself with the project virtualenv, so
there is nothing to activate first.

See ``docs/device-test-harness.md``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Set on the re-executed child so it never loops.
_GUARD = "ZQS_DEVICE_TEST_BOOTSTRAPPED"


# ---------------------------------------------------------------------------
# Bootstrap - runs before anything imports Django
# ---------------------------------------------------------------------------
def _venv_python() -> Path | None:
    for relative in ("Scripts/python.exe", "bin/python"):
        candidate = ROOT / ".venv" / relative
        if candidate.exists():
            return candidate
    return None


def _reexec_in_venv() -> None:
    """Re-run this script with the project interpreter, if we are not on it.

    Users should not have to remember to activate anything, and a wrong
    interpreter fails with ``ModuleNotFoundError: django`` - which reads like a
    broken project rather than a missing activation step.
    """
    if os.environ.get(_GUARD):
        return

    python = _venv_python()
    if python is None:
        print(
            "找不到專案的虛擬環境（.venv）。\n"
            "請先執行：  .\\scripts\\dev.ps1 -Setup",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        if Path(sys.executable).resolve() == python.resolve():
            return
    except OSError:
        pass

    environment = dict(os.environ, **{_GUARD: "1"})
    process = subprocess.Popen(
        [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
        cwd=str(ROOT),
        env=environment,
    )
    try:
        raise SystemExit(process.wait())
    except KeyboardInterrupt:
        # Windows delivers Ctrl+C to the whole console group, so the child is
        # already shutting itself down and writing its report. Wait for it and
        # report *its* verdict rather than inventing one here.
        try:
            raise SystemExit(process.wait(timeout=30))
        except subprocess.TimeoutExpired:
            process.kill()
            raise SystemExit(130) from None


_reexec_in_venv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
# The harness runs entirely in this process; nothing is handed to a worker, so
# a real broker would only be another thing to install and start.
os.environ.setdefault("BUS_BACKEND", "memory")
sys.path.insert(0, str(ROOT))

try:
    import django
except ModuleNotFoundError:  # pragma: no cover - environment problem
    print(
        "虛擬環境裡沒有安裝 Django。請執行：\n"
        "  .venv\\Scripts\\python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2) from None

django.setup()

import argparse  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from services.harness import report as reporting  # noqa: E402
from services.harness import runner  # noqa: E402
from services.harness.broker import HarnessServer, HarnessState, send_command  # noqa: E402
from services.harness.console import Console, EventPrinter  # noqa: E402


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------
def command_self_test(args, console: Console) -> int:
    console.rule()
    console.head("  測試工具自我驗證")
    console.rule()
    console.line()
    console.line("先確認這個工具本身是對的，再拿它去測 LabVIEW。")
    console.line("每個情境都會跑一次參考設備：正常的那次必須全過，故意壞掉的")
    console.line("那幾次必須「剛好」被抓到對應的那一項——不多報，也不漏報。")
    console.line()

    provision = (
        _fixed_credentials(args)
        if args.device
        else runner.provision_selftest_device()
    )

    results: list[runner.ScenarioResult] = []
    try:
        with provision as credentials:
            if not args.device:
                console.dim(
                    f"  已建立暫時性測試設備 {credentials.device_id}"
                    "（結束時自動刪除）"
                )
                console.line()

            results = runner.run_self_test(
                credentials,
                only=args.only,
                on_scenario_start=lambda s: console.line(f"→ {s.title} …"),
                on_scenario_done=lambda r: _print_scenario_result(console, r),
            )
    except KeyboardInterrupt:
        console.line()
        console.warn("已中斷。暫時性測試設備已清除。")
        return runner.EXIT_ABORTED
    except Exception as exc:  # noqa: BLE001 - turn a traceback into advice
        console.line()
        console.bad(f"自我驗證無法執行：{exc}")
        console.line()
        console.line("如果訊息看起來與資料庫有關，請先執行：")
        console.line("  .venv\\Scripts\\python manage.py migrate")
        return runner.EXIT_USAGE

    if not results:
        console.bad(f"沒有符合 --only {args.only!r} 的情境。")
        return runner.EXIT_USAGE

    text = _render_self_test_summary(results)
    console.line()
    for line in text.splitlines():
        console.line(line)

    if not args.no_report:
        path = runner.write_report(
            runner.report_path(ROOT, mode="selftest"), text
        )
        console.line()
        console.dim(f"報告已寫入 {path}")

    return runner.EXIT_OK if all(r.ok for r in results) else runner.EXIT_FAILED


def _print_scenario_result(console: Console, result: runner.ScenarioResult) -> None:
    if result.ok:
        detail = (
            "全部通過"
            if not result.actual_failures
            else f"如預期抓到 {len(result.actual_failures)} 項"
        )
        console.ok(f"   ✓ {detail}（收到 {result.message_count} 則訊息）")
    else:
        console.bad("   ✗ 工具的判斷與預期不符")
        for problem in result.problems:
            console.bad(f"       {problem}")
    console.line()


def _render_self_test_summary(results: list[runner.ScenarioResult]) -> str:
    lines = ["=" * 74, "  測試工具自我驗證結果", "=" * 74, ""]

    for result in results:
        mark = "[通過]" if result.ok else "[異常]"
        lines.append(f"{mark} {result.scenario.title}")
        expected = result.scenario.expect_failures
        lines.append(
            "        預期失敗項：" + ("（無，應全過）" if not expected else "、".join(sorted(expected)))
        )
        lines.append(
            "        實際失敗項："
            + ("（無）" if not result.actual_failures else "、".join(sorted(result.actual_failures)))
        )
        for problem in result.problems:
            lines.append(f"        → {problem}")
        lines.append("")

    passed = sum(1 for r in results if r.ok)
    lines.append("-" * 74)
    lines.append(f"{passed} / {len(results)} 個情境符合預期")
    lines.append("")

    if passed == len(results):
        lines.append("結論：測試工具運作正常。")
        lines.append("")
        lines.append("  它會讓正確的設備通過，也會擋下壞掉的設備——兩邊都驗證過了。")
        lines.append("  接下來可以拿它測真實設備：")
        lines.append("      python scripts\\run_device_test.py device --device <你的 device_id>")
    else:
        lines.append("結論：測試工具本身有問題，先不要用它的結果判斷設備。")
        lines.append("")
        lines.append("  上面標示「異常」的情境代表工具漏報或誤報。在修好之前，")
        lines.append("  device 模式印出的報告都不能當作驗收依據。")
    lines.append("=" * 74)
    return "\n".join(lines)


class _FixedCredentials:
    """``--device``/``--password`` supplied by hand, in the same shape."""

    def __init__(self, credentials: runner.Credentials) -> None:
        self._credentials = credentials

    def __enter__(self) -> runner.Credentials:
        return self._credentials

    def __exit__(self, *_exc) -> bool:
        return False


def _fixed_credentials(args) -> _FixedCredentials:
    password = _resolve_password(args)
    username = args.username or _lookup_username(args.device)
    return _FixedCredentials(runner.Credentials(args.device, username, password))


# ---------------------------------------------------------------------------
# device
# ---------------------------------------------------------------------------
def command_device(args, console: Console) -> int:
    if runner.port_in_use(args.host, args.port):
        console.line()
        _print_port_advice(console, args)
        return runner.EXIT_USAGE

    state = HarnessState(on_event=EventPrinter(console))
    try:
        server = HarnessServer((args.host, args.port), state)
    except OSError as exc:
        console.line()
        console.bad(f"無法在 {args.host}:{args.port} 監聽：{exc}")
        console.line()
        _print_port_advice(console, args)
        return runner.EXIT_USAGE

    threading.Thread(target=server.serve_forever, daemon=True).start()
    _print_device_banner(console, args)

    interrupted = False
    try:
        _wait_for_device_session(state, args, console)
    except KeyboardInterrupt:
        interrupted = True
        console.line()
        console.dim("收到 Ctrl+C，正在收尾…")
    finally:
        server.shutdown_harness()
        # Give the connection handler a moment to score the disconnect, which
        # is where the last-will verdict is decided.
        time.sleep(0.4)

    return _finish_device_run(state, args, console, interrupted=interrupted)


def _print_port_advice(console: Console, args) -> None:
    """Say what happened and what to do, instead of a bind traceback."""
    for index, line in enumerate(runner.port_advice(args.host, args.port).splitlines()):
        if index == 0:
            console.bad(line)
        elif line.startswith("      "):
            console.dim(line)
        else:
            console.line(line)


def _print_device_banner(console: Console, args) -> None:
    from django.conf import settings

    from services.mqtt import topics

    console.rule()
    console.head("  ZQS 設備連線測試工具")
    console.rule()
    console.line(f"  監聽             {args.host}:{args.port}")
    console.line(f"  Topic root       {topics.root()}")
    console.line(f"  Client ID        {settings.MQTT['CLIENT_ID_PREFIX']}:<device_id>")
    if args.device:
        console.line(f"  等待設備         {args.device}")
    console.line(f"  逾時             {args.timeout:.0f} 秒未連線就放棄")
    if args.max_messages:
        console.line(f"  收到 {args.max_messages} 則訊息後自動結束")
    console.line()
    console.line("  這不是正式 broker。憑證、ACL 與 payload 都是用正式環境的")
    console.line("  程式檢查的，有四項比正式環境更嚴格（見文件 §5）。")
    console.line()
    if args.interactive:
        console.line('  互動模式：輸入 `名稱 {"參數":值}` 下發命令，輸入 q 結束。')
        console.line()
    console.warn("  等待設備連線…（Ctrl+C 結束並印出報告）")
    console.line()


def _wait_for_device_session(state: HarnessState, args, console: Console) -> None:
    """Block until the run should end. Ctrl+C propagates to the caller."""
    if args.interactive:
        threading.Thread(
            target=_interactive_loop, args=(state, args, console), daemon=True
        ).start()
    elif args.command:
        threading.Thread(
            target=_delayed_command, args=(state, args, console), daemon=True
        ).start()

    deadline = time.monotonic() + args.timeout
    connected = False

    while True:
        session = state.only_session()
        if session is not None and not connected:
            connected = True
            # The connect timeout has done its job; from here the run is
            # bounded by --duration, or by the operator.
            deadline = time.monotonic() + args.duration if args.duration else None

        if args.max_messages and session is not None:
            if len(session.messages) >= args.max_messages:
                console.line()
                console.dim(f"已收到 {args.max_messages} 則訊息，結束測試。")
                return

        if deadline is not None and time.monotonic() > deadline:
            if not connected:
                console.line()
                console.warn(f"等了 {args.timeout:.0f} 秒都沒有設備連進來。")
            else:
                console.line()
                console.dim(f"已達 --duration {args.duration:.0f} 秒，結束測試。")
            return

        time.sleep(0.2)


def _delayed_command(state: HarnessState, args, console: Console) -> None:
    time.sleep(args.command_delay)
    _dispatch(state, args, console, args.command, args.params)


def _interactive_loop(state: HarnessState, args, console: Console) -> None:
    while True:
        try:
            raw = input()
        except (EOFError, KeyboardInterrupt):
            return
        raw = raw.strip()
        if not raw:
            continue
        if raw in ("q", "quit", "exit"):
            # Interrupt the main thread the same way Ctrl+C would, so there is
            # one shutdown path and one place that writes the report.
            _thread_interrupt()
            return
        name, _, params = raw.partition(" ")
        _dispatch(state, args, console, name, params.strip() or "{}")


def _thread_interrupt() -> None:
    import _thread

    _thread.interrupt_main()


def _dispatch(state: HarnessState, args, console: Console, name: str, params: str) -> None:
    try:
        parsed = json.loads(params or "{}")
    except json.JSONDecodeError as exc:
        console.bad(f"!! 參數不是合法 JSON：{exc}")
        console.dim('   範例：set_power_limit {"limit_w": 400000}')
        return
    if not isinstance(parsed, dict):
        console.bad("!! 命令參數必須是 JSON 物件，例如 {\"limit_w\": 400000}")
        return

    session = state.only_session()
    device_id = args.device or (session.device_id if session else "")
    if not device_id:
        console.bad("!! 還沒有設備連線，命令沒有送出。")
        return

    sent, command_id, note = send_command(state, device_id, name, parsed)
    if sent:
        console.warn(f">> 下發命令 {name}  command_id={command_id}")
        if note:
            console.bad(f"   {note}")
    else:
        console.bad(f"!! {note}")


def _finish_device_run(
    state: HarnessState, args, console: Console, *, interrupted: bool
) -> int:
    session = state.only_session()
    console.line()

    if session is None:
        console.warn("沒有任何設備成功連線，因此沒有報告可產生。")
        console.line()
        console.line("檢查清單：")
        console.line(f"  - 設備連的位址與埠號是不是 <這台電腦的 IP>:{args.port}")
        console.line("  - Windows 防火牆是否放行（見文件 §9）")
        console.line("  - 設備是否已在 console 註冊，且憑證正確")
        return runner.EXIT_ABORTED if interrupted else runner.EXIT_INCOMPLETE

    text = reporting.render(
        session.checks,
        device_id=session.device_id,
        message_count=len(session.messages),
    )
    for line in text.splitlines():
        console.line(line)

    if not args.no_report:
        path = runner.write_report(
            runner.report_path(ROOT, mode="device", device_id=session.device_id), text
        )
        console.line()
        console.dim(f"報告已寫入 {path}")

    result = reporting.verdict(session.checks)
    if result == reporting.VERDICT_READY:
        return runner.EXIT_OK
    if result == reporting.VERDICT_NOT_READY:
        return runner.EXIT_FAILED
    return runner.EXIT_INCOMPLETE


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def _resolve_password(args) -> str:
    """Never hard-coded, never echoed, never stored by this script."""
    if args.password:
        return args.password
    from_env = os.environ.get("ZQS_DEVICE_PASSWORD", "")
    if from_env:
        return from_env
    import getpass

    print(
        "需要設備的 MQTT 密碼。它在註冊（或輪替憑證）時只顯示過一次；\n"
        "如果弄丟了，到 console 重新產生一組。\n"
        "也可以改用環境變數 ZQS_DEVICE_PASSWORD，或參數 --password。"
    )
    password = getpass.getpass("MQTT 密碼（輸入時不顯示）：")
    if not password:
        raise SystemExit(runner.EXIT_USAGE)
    return password


def _lookup_username(device_id: str) -> str:
    from apps.devices.models import DeviceCredential

    username = (
        DeviceCredential.objects.filter(device__device_id=device_id)
        .values_list("mqtt_username", flat=True)
        .first()
    )
    if not username:
        print(
            f"找不到 {device_id!r} 的 MQTT 憑證。\n"
            "請先在 console 註冊這台設備並產生憑證，或用 --username 指定。",
            file=sys.stderr,
        )
        raise SystemExit(runner.EXIT_USAGE)
    return username


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_device_test.py",
        description="設備 MQTT 連線測試工具（自我驗證 + 設備驗收）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "結束碼：\n"
            "  0   通過\n"
            "  1   驗收失敗（設備不合格，或工具自我驗證不符預期）\n"
            "  2   無法執行（參數錯誤、埠被占用、找不到憑證）\n"
            "  3   測試未完成（沒有設備連線，或必要項目沒被觀察到）\n"
            "  130 使用者中斷\n"
        ),
    )
    parser.add_argument(
        "--no-color", action="store_true", help="關閉彩色輸出（寫進檔案時比較乾淨）"
    )
    parser.add_argument("--no-report", action="store_true", help="不要寫報告檔")

    # The same two flags on the subcommands, so both orderings work. Argparse
    # would otherwise let a subparser's default overwrite the value parsed at
    # the top level, silently turning `--no-color self-test` back on;
    # SUPPRESS leaves the attribute alone when the flag is not repeated.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--no-color", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )
    shared.add_argument(
        "--no-report", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )

    sub = parser.add_subparsers(dest="mode", required=True)

    self_test = sub.add_parser(
        "self-test",
        parents=[shared],
        help="驗證測試工具本身（先跑這個）",
        description="用參考設備驗證這個工具會通過正確的設備、也會擋下壞掉的設備。",
    )
    self_test.add_argument(
        "--only", default="", help="只跑其中一個情境，例如 --only no_lwt"
    )
    self_test.add_argument(
        "--device",
        default="",
        help="用既有設備的憑證測試。省略時自動建立暫時設備並在結束時刪除。",
    )
    self_test.add_argument("--username", default="", help="搭配 --device 使用")
    self_test.add_argument("--password", default="", help="搭配 --device 使用")
    self_test.set_defaults(func=command_self_test)

    device = sub.add_parser(
        "device",
        parents=[shared],
        help="測試真實設備（LabVIEW）",
        description="啟動測試工具，等待真實設備連線，結束時印出驗收報告。",
    )
    device.add_argument("--host", default="0.0.0.0", help="綁定位址（預設 0.0.0.0）")
    device.add_argument("--port", type=int, default=1883)
    device.add_argument("--device", default="", help="預期的 device_id（下發命令時用）")
    device.add_argument(
        "--timeout", type=float, default=300.0, help="等待設備連線的秒數（預設 300）"
    )
    device.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="設備連上之後再測幾秒。0 表示等 Ctrl+C（預設）",
    )
    device.add_argument(
        "--max-messages", type=int, default=0, help="收到幾則訊息就結束。0 表示不限"
    )
    device.add_argument("--command", default="", help="設備訂閱後自動下發的命令名稱")
    device.add_argument("--params", default="{}", help="命令參數（JSON）")
    device.add_argument("--command-delay", type=float, default=8.0)
    device.add_argument(
        "--interactive", action="store_true", help="從鍵盤逐一下發命令"
    )
    device.set_defaults(func=command_device)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console(colour=False if args.no_color else None)
    try:
        return args.func(args, console)
    except KeyboardInterrupt:
        console.line()
        console.warn("已中斷。")
        return runner.EXIT_ABORTED


if __name__ == "__main__":
    sys.exit(main())
