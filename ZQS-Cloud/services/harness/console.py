"""Terminal output for the harness, in one place.

Both the management command and ``scripts/run_device_test.py`` print the same
traffic, so the formatting lives here rather than being copied. If the two
diverged, a device author comparing a colleague's screenshot with their own
would waste time on a difference that means nothing.

Windows needs three separate things to show Chinese text in colour, and
:func:`prepare_stream` does all three: a UTF-8 console code page, a UTF-8
Python stream, and virtual-terminal processing for ANSI escapes.
"""

from __future__ import annotations

import os
import sys
from typing import Any, TextIO

RESET = "\033[0m"
_CODES = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "grey": "\033[90m",
    "bold": "\033[1m",
}


def prepare_stream(stream: TextIO) -> bool:
    """Make ``stream`` able to carry UTF-8 and ANSI. Returns colour support.

    Safe to call on anything, including a redirected pipe - every step is
    attempted independently and a failure only costs that one capability.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # A pipe that refuses reconfiguration still prints; mojibake in a
            # redirect is better than crashing the run that produced it.
            pass

    if sys.platform != "win32":
        return _tty_wants_colour(stream)

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.SetConsoleOutputCP(65001)

        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False  # redirected to a file: no console, no colour
        enable_vt = 0x0004
        if not kernel32.SetConsoleMode(handle, mode.value | enable_vt):
            return False  # pre-2016 console host
    except Exception:  # noqa: BLE001 - colour is a nicety, never a blocker
        return False

    return _tty_wants_colour(stream)


def _tty_wants_colour(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):  # https://no-color.org
        return False
    if os.environ.get("ZQS_FORCE_COLOR"):
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


class Console:
    """A stream plus optional colour. Never raises on an odd terminal."""

    def __init__(self, stream: TextIO | None = None, *, colour: bool | None = None) -> None:
        self.stream = stream or sys.stdout
        self.colour = prepare_stream(self.stream) if colour is None else colour

    def paint(self, text: str, *styles: str) -> str:
        if not self.colour or not styles:
            return text
        prefix = "".join(_CODES[name] for name in styles if name in _CODES)
        return f"{prefix}{text}{RESET}" if prefix else text

    def line(self, text: str = "", *styles: str) -> None:
        try:
            self.stream.write(self.paint(text, *styles) + "\n")
            self.stream.flush()
        except (OSError, ValueError):
            pass  # the terminal went away; the report file is the record

    # Semantic helpers, so callers never pick colours themselves.
    def head(self, text: str) -> None:
        self.line(text, "bold", "cyan")

    def ok(self, text: str) -> None:
        self.line(text, "green")

    def bad(self, text: str) -> None:
        self.line(text, "red")

    def warn(self, text: str) -> None:
        self.line(text, "yellow")

    def dim(self, text: str) -> None:
        self.line(text, "grey")

    def rule(self, char: str = "=", width: int = 74) -> None:
        self.head(char * width)


class EventPrinter:
    """Renders harness events as they happen.

    Live output exists so a device author sees the rejection *at the moment
    they cause it*, instead of discovering it in a summary and having to guess
    which of the last thirty messages it referred to.
    """

    def __init__(self, console: Console) -> None:
        self.console = console

    def __call__(self, kind: str, payload: dict[str, Any]) -> None:
        handler = getattr(self, f"_on_{kind}", None)
        if handler is not None:
            handler(payload)

    # ---- events ----------------------------------------------------------
    def _on_connection(self, payload: dict) -> None:
        if payload.get("phase") == "opened":
            self.console.dim(f"·· TCP 連線建立 {payload['peer']}")
            return
        how = "正常斷線" if payload.get("graceful") else "非正常斷線"
        self.console.dim(f"·· 連線關閉 {payload['peer']}（{how}）")

    def _on_connect(self, payload: dict) -> None:
        device_id = payload["device_id"]
        if payload["accepted"]:
            self.console.ok(f">> CONNECT {device_id} → 接受")
        else:
            self.console.bad(f">> CONNECT {device_id} → 拒絕")
        self._print_problems(payload["checks"])

    def _on_subscribe(self, payload: dict) -> None:
        for (topic, qos), granted in zip(payload["filters"], payload["granted"]):
            if granted == 0x80:
                self.console.bad(f">> SUBSCRIBE 拒絕  {topic}")
            else:
                self.console.line(f">> SUBSCRIBE {topic}  QoS {qos}")

    def _on_message(self, payload: dict) -> None:
        record = payload["record"]
        flags = f"QoS {record.qos}" + ("  retained" if record.retain else "")
        stamp = record.received_at.strftime("%H:%M:%S")
        header = f"<< {stamp}  {record.topic}  [{flags}]"
        if record.accepted:
            self.console.ok(header)
            self.console.dim(f"       {record.payload_text}")
        else:
            self.console.bad(header)
            self.console.dim(f"       {record.payload_text}")
            self.console.bad(f"       拒絕：{record.reason}")

    def _on_will(self, payload: dict) -> None:
        body = payload["payload"].decode("utf-8", errors="replace")
        self.console.warn(f"** 送出遺言（LWT）  {payload['topic']}")
        self.console.dim(f"       {body}")

    def _on_error(self, payload: dict) -> None:
        self.console.bad(f"!! {payload['message']}")

    # ---- helpers ---------------------------------------------------------
    def _print_problems(self, checks: dict) -> None:
        """Only failures and warnings. A wall of green hides the one red line."""
        from services.harness import checks as conformance

        for check in checks.values():
            if check.status == conformance.FAIL:
                self.console.bad(f"   ✗ {check.title}")
                self.console.line(f"       應為：{check.expected}")
                self.console.line(f"       實際：{check.actual}")
                if check.detail:
                    self.console.dim(f"       → {check.detail}")
            elif check.status == conformance.WARN:
                self.console.warn(f"   ! {check.title}：{check.actual}")
                if check.detail:
                    self.console.dim(f"       → {check.detail}")
