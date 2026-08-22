"""Orchestration for the one-command device test launcher.

Everything here is importable and testable; ``scripts/run_device_test.py`` is
only argument parsing and printing on top of it.

The self-test is the part worth reading. It does not merely check that a
correct device passes - it checks that each *broken* device fails, and fails
**exactly** the check it was built to break. A harness that under-reports gives
false confidence; one that over-reports sends people chasing bugs that are not
there. Both are caught by comparing the failure set for equality rather than
membership.
"""

from __future__ import annotations

import datetime as dt
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from services.harness import checks as conformance
from services.harness import report as reporting
from services.harness.broker import (
    HarnessServer,
    HarnessState,
    request_rebirth,
    send_command,
)
from services.harness.simulator import ReferenceDevice
from services.sparkplug import topics
from services.sparkplug.topics import MessageType

# ---------------------------------------------------------------------------
# Exit codes. Stable, because batch files and CI will branch on them.
# ---------------------------------------------------------------------------
EXIT_OK = 0
#: A real failure: the device did not conform, or the harness missed a fault.
EXIT_FAILED = 1
#: The run never got far enough to judge anything - bad arguments, port taken,
#: missing credentials. Distinct from EXIT_FAILED so CI can tell "the device is
#: broken" from "the test could not run".
EXIT_USAGE = 2
#: Ran, but not enough was observed to reach a verdict.
EXIT_INCOMPLETE = 3
#: Interrupted before a verdict.
EXIT_ABORTED = 130


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
def port_in_use(host: str, port: int, *, timeout: float = 0.7) -> bool:
    """Whether something is already listening.

    Probes with a connect rather than a bind: on Windows ``SO_REUSEADDR``
    lets a second socket bind a port that is already in use, so a bind probe
    would happily succeed and the harness would then receive a random half of
    the traffic. Connecting is the only reliable answer there.
    """
    probe = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    try:
        with socket.create_connection((probe, port), timeout=timeout):
            return True
    except OSError:
        return False


def port_advice(host: str, port: int) -> str:
    """A message that says what to do, not just what went wrong."""
    lines = [
        f"連接埠 {port} 已經被占用了，測試工具無法啟動。",
        "",
        "常見原因：",
        "  - 已經有一個測試工具在跑（檢查其他終端機視窗）",
    ]
    if port == 1883:
        lines.append("  - 本機跑著真正的 EMQX 或 Mosquitto（1883 是 MQTT 預設埠）")
    else:
        lines.append(f"  - 有其他程式正在使用 {port}")
    lines += [
        "",
        "處理方式（擇一）：",
        f"  - 換一個埠：--port {port + 1000}（設備端記得跟著改）",
        "  - 先關掉占用的程式：",
    ]
    lines.append(f'      netstat -ano | findstr ":{port}"   # 找出 PID')
    lines.append("      taskkill /PID <PID> /F")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# A throwaway device for the self-test
# ---------------------------------------------------------------------------
#: Prefix for devices this module creates and removes. Recognisable on sight in
#: the console, so a leftover row is obviously ours and obviously safe to drop.
SELFTEST_PREFIX = "ZQS-SELFTEST-"


@dataclass
class Credentials:
    device_id: str
    username: str
    password: str
    group_id: str = ""
    node_id: str = ""


@contextmanager
def provision_selftest_device() -> Iterator[Credentials]:
    """Create a temporary edge node and device, then remove both.

    The self-test needs credentials that really authenticate, because it runs
    them through the production :func:`authenticate_edge_node`. Reusing a real
    node would mean rotating its password - silently breaking whatever is
    already using it - so a throwaway is created instead and hard-deleted
    afterwards, including if the run is interrupted.
    """
    import secrets

    from apps.accounts.models import Organization
    from apps.devices.models import Device, EdgeNode, EdgeNodeCredential

    # Sweep anything an earlier crash left behind, so ids never collide.
    EdgeNode.objects.filter(node_id__startswith=SELFTEST_PREFIX).delete()
    Device.objects.filter(device_id__startswith=SELFTEST_PREFIX).delete()

    organization = Organization.objects.order_by("created_at").first()
    temporary_org = None
    if organization is None:
        organization = Organization.objects.create(
            name="ZQS self-test", slug=f"zqs-selftest-{secrets.token_hex(3)}"
        )
        temporary_org = organization

    suffix = secrets.token_hex(4).upper()
    node = EdgeNode.objects.create(
        organization=organization,
        node_id=f"{SELFTEST_PREFIX}{suffix}",
        name="測試工具自我驗證用（自動建立、自動刪除）",
        is_enabled=True,
    )
    device = Device.objects.create(
        organization=organization,
        edge_node=node,
        device_id=f"{SELFTEST_PREFIX}DEV-{suffix}",
        name="測試工具自我驗證用設備",
        is_enabled=True,
    )
    credential, password = EdgeNodeCredential.issue(node)

    try:
        yield Credentials(
            device.device_id,
            credential.mqtt_username,
            password,
            group_id=node.group_id,
            node_id=node.node_id,
        )
    finally:
        Device.objects.filter(pk=device.pk).delete()
        EdgeNode.objects.filter(pk=node.pk).delete()
        if temporary_org is not None:
            Organization.objects.filter(pk=temporary_org.pk).delete()


# ---------------------------------------------------------------------------
# Self-test scenarios
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Scenario:
    """One run of the reference device, and what the harness must say about it."""

    key: str
    title: str
    #: ``misbehave`` value passed to :class:`ReferenceDevice`.
    misbehave: str
    #: Checks that must be FAIL - compared for **equality**, not containment.
    expect_failures: frozenset[str] = frozenset()
    #: Checks that must have passed.
    expect_pass: frozenset[str] = frozenset()
    #: Checks that must still be PENDING, i.e. the behaviour never happened.
    expect_pending: frozenset[str] = frozenset()
    expect_verdict: str = reporting.VERDICT_NOT_READY
    send_command: bool = False
    abrupt_exit: bool = True
    duration: float = 1.2


SELF_TEST_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="normal",
        title="正常設備（應該全部通過）",
        misbehave="",
        expect_failures=frozenset(),
        # The ones only a live exchange can prove.
        expect_pass=frozenset(
            {
                "command_ack",
                "lwt_delivered",
                "ddata_seen",
                "nbirth_seen",
                "dbirth_seen",
                "nbirth_seq",
                "nbirth_bdseq",
                "seq_monotonic",
            }
        ),
        expect_verdict=reporting.VERDICT_READY,
        send_command=True,
        duration=2.0,
    ),
    Scenario(
        key="bad_client_id",
        title="Client ID 用 LabVIEW_1",
        misbehave="bad_client_id",
        expect_failures=frozenset({"client_id_format"}),
        # Must NOT cascade: production only pins the client id when
        # allowed_client_id is set, so authentication still has to succeed.
        expect_pass=frozenset({"credentials"}),
    ),
    Scenario(
        key="no_lwt",
        title="不宣告遺言（LWT）",
        misbehave="no_lwt",
        expect_failures=frozenset(
            {"lwt_declared", "lwt_topic", "lwt_qos", "lwt_retain", "lwt_payload"}
        ),
        expect_pending=frozenset({"lwt_delivered"}),
    ),
    Scenario(
        key="clean_session",
        title="clean_session = false（Sparkplug 不允許保留 session）",
        misbehave="clean_session",
        expect_failures=frozenset({"clean_session"}),
    ),
    Scenario(
        key="retained_will",
        title="遺言設了 retain",
        misbehave="retained_will",
        expect_failures=frozenset({"lwt_retain"}),
        # The will is otherwise perfectly formed, so nothing else may spill.
        expect_pass=frozenset({"lwt_topic", "lwt_qos", "lwt_payload"}),
    ),
    Scenario(
        key="bad_payload",
        title="DDATA 不是合法的 protobuf",
        misbehave="bad_payload",
        expect_failures=frozenset({"payload_schema"}),
        # Rejected payloads must not be counted as data received.
        expect_pending=frozenset({"ddata_seen"}),
    ),
    Scenario(
        key="ignore_rebirth",
        title="收到 Rebirth 要求但不重新宣告",
        misbehave="ignore_rebirth",
        expect_failures=frozenset(),
        # Optional check, so the verdict stays clean - but it must not be
        # reported as passing when the node never re-announced.
        expect_pending=frozenset({"rebirth_honoured"}),
        expect_verdict=reporting.VERDICT_READY,
        send_command=True,
        duration=2.0,
    ),
    Scenario(
        key="no_ack",
        title="收到命令但不回覆 ack",
        misbehave="no_ack",
        expect_failures=frozenset(),
        # Optional check, so the verdict stays clean - but it must not be
        # reported as passing when no ack ever arrived.
        expect_pending=frozenset({"command_ack"}),
        expect_verdict=reporting.VERDICT_READY,
        send_command=True,
        duration=2.0,
    ),
)


@dataclass
class ScenarioResult:
    scenario: Scenario
    ok: bool
    #: Human-readable reasons the scenario did not behave as required.
    problems: list[str] = field(default_factory=list)
    actual_failures: frozenset[str] = frozenset()
    verdict: str = ""
    message_count: int = 0
    checks: dict[str, conformance.Check] = field(default_factory=dict)


def run_scenario(scenario: Scenario, credentials: Credentials) -> ScenarioResult:
    """Run one scenario against a private harness on an ephemeral port.

    Port 0 on purpose: the self-test must never fight with a broker the user
    already has running, and must never need a firewall rule.
    """
    state = HarnessState()
    server = HarnessServer(("127.0.0.1", 0), state)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    device = ReferenceDevice(
        device_id=credentials.device_id,
        username=credentials.username,
        password=credentials.password,
        group_id=credentials.group_id,
        node_id=credentials.node_id,
        host="127.0.0.1",
        port=port,
        interval=0.3,
        misbehave=scenario.misbehave,
    )

    problems: list[str] = []
    try:
        runner = threading.Thread(
            target=_run_device_quietly,
            args=(device, scenario, problems),
            daemon=True,
        )
        runner.start()

        if scenario.send_command:
            _send_when_subscribed(state, credentials, problems)

        runner.join(timeout=scenario.duration + 15)
        if runner.is_alive():
            problems.append("參考設備沒有在時限內結束，可能卡住了。")
            device.stop()

        _wait_for_session_end(state, credentials.node_id)
        session = state.only_session()
    finally:
        server.shutdown_harness()

    if session is None:
        problems.append("參考設備完全沒有連上 harness，無法判定。")
        return ScenarioResult(scenario, ok=False, problems=problems)

    return _score_scenario(scenario, session, problems)


def _run_device_quietly(device: ReferenceDevice, scenario: Scenario, problems: list[str]) -> None:
    try:
        device.run(duration=scenario.duration, abrupt_exit=scenario.abrupt_exit)
    except Exception as exc:  # noqa: BLE001 - report, never kill the self-test
        problems.append(f"參考設備執行時丟出例外：{exc!r}")


def _send_when_subscribed(
    state: HarnessState, credentials, problems: list[str], *, timeout: float = 6.0
) -> None:
    """Wait for the SUBSCRIBE, then send a command and a rebirth request.

    Sending before the node has subscribed would test nothing: the bytes go
    out, nobody is listening, and the missing ack would look like a device bug.
    """
    dcmd_prefix = topics.build(
        credentials.group_id, MessageType.DCMD, credentials.node_id
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = state.session_for(credentials.node_id)
        if session is not None and any(
            f.startswith(dcmd_prefix) for f in session.subscriptions
        ):
            break
        time.sleep(0.05)
    else:
        problems.append(
            f"設備在 {timeout} 秒內沒有訂閱 {dcmd_prefix}/+，命令無法測試。"
        )
        return

    sent, _command_id, note = send_command(
        state,
        credentials.node_id,
        "set_power_limit",
        {"limit_w": 400_000},
        target_device=credentials.device_id,
    )
    if not sent:
        problems.append(f"命令下發失敗：{note}")

    # Rebirth is the specification's only recovery path, so a device that
    # ignores it is broken in a way nothing else in the run would reveal.
    before = _nbirth_count(state, credentials.node_id)
    request_rebirth(state, credentials.node_id)
    rebirth_deadline = time.monotonic() + 3.0
    while time.monotonic() < rebirth_deadline:
        if _nbirth_count(state, credentials.node_id) > before:
            session = state.session_for(credentials.node_id)
            if session is not None:
                session.checks["rebirth_honoured"].succeed("重新發布了 NBIRTH")
            return
        time.sleep(0.05)


def _nbirth_count(state: HarnessState, node_id: str) -> int:
    session = state.session_for(node_id)
    if session is None:
        return 0
    return sum(1 for record in session.messages if record.kind == MessageType.NBIRTH)


def _wait_for_session_end(state: HarnessState, device_id: str, *, timeout: float = 8.0) -> None:
    """Block until the connection handler has finished scoring the disconnect.

    Reading the checks earlier would race the will delivery, which is decided
    in the handler's teardown.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if state.session_for(device_id) is not None and state.handler_for(device_id) is None:
            return
        time.sleep(0.05)


def _score_scenario(scenario: Scenario, session, problems: list[str]) -> ScenarioResult:
    checks = session.checks
    actual_failures = frozenset(
        key for key, check in checks.items() if check.status == conformance.FAIL
    )

    missed = scenario.expect_failures - actual_failures
    if missed:
        problems.append(
            "工具沒有抓到應該失敗的項目："
            + "、".join(_titles(checks, missed))
            + "。這代表測試工具會放行有問題的設備。"
        )

    spurious = actual_failures - scenario.expect_failures
    if spurious:
        problems.append(
            "工具多報了不該失敗的項目："
            + "、".join(_titles(checks, spurious))
            + "。這會讓設備開發者去追不存在的問題。"
        )

    for key in sorted(scenario.expect_pass):
        status = checks[key].status
        if status != conformance.PASS:
            problems.append(
                f"「{checks[key].title}」應該通過，實際是 {_status_word(status)}。"
            )

    for key in sorted(scenario.expect_pending):
        status = checks[key].status
        if status != conformance.PENDING:
            problems.append(
                f"「{checks[key].title}」應該維持「未測」，實際是 {_status_word(status)}。"
            )

    result_verdict = reporting.verdict(checks)
    if result_verdict != scenario.expect_verdict:
        problems.append(
            f"結論應為 {scenario.expect_verdict}，實際是 {result_verdict}。"
        )

    return ScenarioResult(
        scenario=scenario,
        ok=not problems,
        problems=problems,
        actual_failures=actual_failures,
        verdict=result_verdict,
        message_count=len(session.messages),
        checks=checks,
    )


def _titles(checks: dict[str, conformance.Check], keys) -> list[str]:
    return [checks[key].title if key in checks else key for key in sorted(keys)]


def _status_word(status: str) -> str:
    return {
        conformance.PASS: "通過",
        conformance.FAIL: "失敗",
        conformance.WARN: "注意",
        conformance.PENDING: "未測",
    }.get(status, status)


def run_self_test(
    credentials: Credentials,
    *,
    on_scenario_start: Callable[[Scenario], None] | None = None,
    on_scenario_done: Callable[[ScenarioResult], None] | None = None,
    only: str = "",
) -> list[ScenarioResult]:
    """Run every scenario. Returns one result per scenario, in order."""
    results: list[ScenarioResult] = []
    for scenario in SELF_TEST_SCENARIOS:
        if only and scenario.key != only:
            continue
        if on_scenario_start is not None:
            on_scenario_start(scenario)
        result = run_scenario(scenario, credentials)
        results.append(result)
        if on_scenario_done is not None:
            on_scenario_done(result)
    return results


# ---------------------------------------------------------------------------
# Report files
# ---------------------------------------------------------------------------
def report_path(root: Path, *, mode: str, device_id: str = "") -> Path:
    """``logs/device-test-<mode>[-<device>]-<timestamp>.txt``."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    parts = ["device-test", mode]
    if device_id:
        parts.append(_safe_filename(device_id))
    parts.append(stamp)
    return root / "logs" / ("-".join(parts) + ".txt")


def write_report(path: Path, text: str) -> Path:
    """Write a report a Windows user can double-click without seeing mojibake.

    ``utf-8-sig`` deliberately: Notepad and Excel still guess the encoding of a
    plain UTF-8 file and often guess wrong on Chinese, and this file exists to
    be opened and pasted into a ticket.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8-sig")
    return path


def _safe_filename(value: str) -> str:
    """A device id is an MQTT topic segment, not a vetted filename.

    Dots are legal in a device id, so they are kept - but ``..`` never reaches
    the filesystem, and separators become underscores. The report goes where
    this code says it goes, whatever the device calls itself.
    """
    cleaned = "".join(
        char if char.isalnum() or char in "-_." else "_" for char in value
    )
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "_")
    return cleaned.lstrip(".")[:60] or "device"
