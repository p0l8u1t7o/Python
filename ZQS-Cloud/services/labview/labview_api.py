"""Process control for LabVIEW's Python Node.

LabVIEW calls Python synchronously: the block diagram stops until the function
returns, and the calling VI has no way to interrupt it. Everything here is
therefore written to return in milliseconds and to report progress through
polled state instead of blocking.

Design rules this module follows, all of them forced by the Python Node:

* **Nothing blocks.** Services are started with :class:`subprocess.Popen` and
  never waited on. Stopping signals the child and returns immediately; the
  grace period and the final kill happen on a background daemon thread. Poll
  :func:`get_status` from LabVIEW to see the result.
* **Only LabVIEW-representable types cross the boundary.** Arguments and
  return values are ``int``, ``float``, ``str`` or lists of those. No
  ``None``, no ``bool``, no ``dict``, no objects. State is an ``int`` code;
  anything richer arrives as a JSON ``str``.
* **No exception ever escapes.** Every public function has a catch-all;
  failures come back as a negative ``int``. Call :func:`get_last_error` for
  the message.
* **State lives at module level.** LabVIEW keeps one Python session alive
  across calls, so the handles survive between them. Calling
  :func:`start_server` twice does not start a second copy.

Quick reference, full version in ``docs/labview-integration.html``::

    start_server("")                -> int   0 started, 1 already running, <0 error
    stop_server("", 5.0)            -> int   0 accepted; poll get_status
    get_status("")                  -> int   0 stopped 1 running 2 stopping 3 exited
    get_status_json()               -> str   per-service detail
    get_last_error()                -> str   "" when clean

Service names: ``api``, ``ingestor``, ``worker``, ``scheduler``. An empty
string means all of them.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

__all__ = [
    "start_server",
    "stop_server",
    "get_status",
    "get_status_json",
    "get_last_error",
    "clear_last_error",
    "list_services",
    "get_pid",
    "get_log_path",
    "get_root",
]

# ---------------------------------------------------------------------------
# Codes. Kept as plain module constants so LabVIEW can mirror them in a ring.
# ---------------------------------------------------------------------------

# Status, returned by get_status().
STATUS_STOPPED = 0  # not running: never started, or stopped cleanly
STATUS_RUNNING = 1  # process alive
STATUS_STOPPING = 2  # signalled, inside the grace period or being killed
STATUS_EXITED = 3  # died on its own with a non-zero code - check the log
STATUS_UNKNOWN = -1  # unknown service name

# Return codes, returned by start_server() / stop_server().
RC_OK = 0
RC_ALREADY_RUNNING = 1  # not an error: every requested service was up already
RC_ERROR = -1  # unexpected internal failure
RC_UNKNOWN_SERVICE = -2
RC_NO_INTERPRETER = -3
RC_SPAWN_FAILED = -4
RC_BUSY_STOPPING = -5  # asked to start something mid-shutdown; retry when 0

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "logs" / "labview"

#: Argument vector for each service, appended to the interpreter path. The
#: commands match docker-compose.yml and scripts/dev.ps1, with two changes that
#: only matter when a supervisor owns the process:
#:   * ``--noreload``: Django's autoreloader forks a second process, and
#:     signalling the parent would leave the child holding port 8000.
#:   * the scheduler is one long-running command rather than compose's
#:     ``sh -c "while true; ..."`` loop, which has no Windows equivalent.
_COMMANDS = {
    "api": ["manage.py", "runserver", "--noreload"],
    "ingestor": ["manage.py", "run_ingestor"],
    "worker": ["manage.py", "run_worker"],
    "scheduler": ["manage.py", "run_scheduler"],
}

#: Start order: the API migrates nothing but is the health probe the others are
#: checked against, so it goes first. Stop order is the reverse.
_ORDER = ["api", "ingestor", "worker", "scheduler"]

_API_BIND = os.environ.get("ZQS_API_BIND", "127.0.0.1:8000")

_GRACE_MIN = 0.5
_GRACE_MAX = 120.0
_GRACE_DEFAULT = 5.0

_REAP_INTERVAL = 0.25  # background poll cadence, seconds
_LOG_MAX_BYTES = 5 * 1024 * 1024

# Windows creation flags, spelled out because subprocess only defines them on
# Windows and this module is imported on Linux by the test suite.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_CONSOLE = 0x00000010


# ---------------------------------------------------------------------------
# Module-level state. LabVIEW's Python session outlives every single call, so
# this dict is the supervisor: it is what makes a second start_server() a
# no-op instead of a second copy of the stack.
# ---------------------------------------------------------------------------


class _Service:
    """Bookkeeping for one child process."""

    __slots__ = (
        "name",
        "proc",
        "state",
        "started_at",
        "kill_deadline",
        "exit_code",
        "last_pid",
        "log_file",
        "log_path",
    )

    def __init__(self, name: str) -> None:
        self.name = name
        self.proc: subprocess.Popen | None = None
        self.state: int = STATUS_STOPPED
        self.started_at: float = 0.0
        self.kill_deadline: float = 0.0
        self.exit_code: int = 0
        self.last_pid: int = 0
        self.log_file = None
        self.log_path: str = ""


_LOCK = threading.RLock()
_STATE: dict[str, _Service] = {}
_LAST_ERROR: str = ""
_REAPER: threading.Thread | None = None


def _service(name: str) -> _Service:
    svc = _STATE.get(name)
    if svc is None:
        svc = _Service(name)
        _STATE[name] = svc
    return svc


def _set_error(message: str) -> None:
    global _LAST_ERROR
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with _LOCK:
        _LAST_ERROR = f"[{stamp}] {message}"


# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------


def _resolve(services) -> tuple[list[str], list[str]]:
    """Normalise a LabVIEW argument into service names.

    Accepts ``""`` or ``"all"`` for everything, a comma or space separated
    string, or a list of strings (LabVIEW passes a 1-D string array as a
    Python list). Returns ``(known, unknown)``, ``known`` in start order.
    """
    if services is None:
        raw: list[str] = []
    elif isinstance(services, str):
        raw = [part for part in services.replace(",", " ").split() if part]
    elif isinstance(services, (list, tuple)):
        raw = [str(part).strip() for part in services if str(part).strip()]
    else:
        raw = [str(services).strip()]

    if not raw or [part.lower() for part in raw] == ["all"]:
        return list(_ORDER), []

    known: list[str] = []
    unknown: list[str] = []
    for part in raw:
        key = part.strip().lower()
        if key == "all":
            known = list(_ORDER)
            continue
        if key in _COMMANDS:
            if key not in known:
                known.append(key)
        else:
            unknown.append(part)
    known.sort(key=_ORDER.index)
    return known, unknown


def _interpreter() -> str:
    """The project virtualenv's Python, the same one scripts/dev.ps1 uses.

    Falls back to the interpreter running this module, which under LabVIEW is
    whichever Python the Python Node was configured with. Override with
    ``ZQS_PYTHON`` if the venv lives elsewhere.
    """
    override = os.environ.get("ZQS_PYTHON", "").strip()
    if override:
        return override if Path(override).exists() else ""

    for candidate in (
        ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        ROOT / ".venv" / "bin" / "python",  # POSIX
    ):
        if candidate.exists():
            return str(candidate)

    return sys.executable or ""


def _argv(name: str, python: str) -> list[str]:
    args = [python] + list(_COMMANDS[name])
    if name == "api":
        args.append(_API_BIND)
    return args


def _child_env(batch: list[str]) -> dict[str, str]:
    env = os.environ.copy()
    # Unbuffered, or the log file stays empty until the child exits and the
    # operator watching it thinks the service hung.
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")

    # Same rule as scripts/dev.ps1: the ingestor and the worker are separate
    # processes, so the in-memory bus cannot join them. Only fill this in when
    # the environment has not already chosen a backend.
    running = {n for n, s in _STATE.items() if s.state == STATUS_RUNNING}
    if ({"ingestor", "worker"} & (set(batch) | running)) and "BUS_BACKEND" not in env:
        env["BUS_BACKEND"] = "redis"
    return env


def _creation_flags() -> int:
    """Windows-only Popen flags.

    ``CREATE_NEW_PROCESS_GROUP`` is what makes ``CTRL_BREAK_EVENT`` deliverable
    to the child alone, and stops a Ctrl-C in an operator's console from
    tearing down services LabVIEW owns.

    ``CREATE_NO_WINDOW`` keeps console windows from popping up over the VI.
    The trade-off is real: a child with no console cannot *receive* a console
    control event, so the CTRL_BREAK in :func:`stop_server` is best-effort and
    shutdown usually completes via the grace-period kill instead. Set
    ``ZQS_LABVIEW_CONSOLE=1`` to spawn a visible console per service instead,
    which restores graceful shutdown and makes the logs readable live.
    """
    flags = _CREATE_NEW_PROCESS_GROUP
    if os.environ.get("ZQS_LABVIEW_CONSOLE", "").strip() == "1":
        return flags | _CREATE_NEW_CONSOLE
    return flags | _CREATE_NO_WINDOW


# ---------------------------------------------------------------------------
# Logging: files, never PIPE
# ---------------------------------------------------------------------------


def _open_log(name: str):
    """Open the per-service log file.

    Deliberately not ``subprocess.PIPE``: a pipe nobody drains fills its OS
    buffer (64 KB or so) and the child blocks forever on its next write. A
    file has no such limit, and nothing here is required to read it.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{name}.log"
    try:
        if path.exists() and path.stat().st_size > _LOG_MAX_BYTES:
            backup = LOG_DIR / f"{name}.log.1"
            if backup.exists():
                backup.unlink()
            path.replace(backup)
    except OSError:
        pass  # rotation is a nicety; never let it stop a start

    handle = open(path, "ab")
    header = f"\n--- {name} started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
    try:
        handle.write(header.encode("utf-8"))
        handle.flush()
    except OSError:
        pass
    return handle, str(path)


def _close_log(svc: _Service) -> None:
    if svc.log_file is not None:
        try:
            svc.log_file.close()
        except OSError:
            pass
        svc.log_file = None


# ---------------------------------------------------------------------------
# Background reaper: everything that would otherwise need a wait()
# ---------------------------------------------------------------------------


def _ensure_reaper() -> None:
    global _REAPER
    with _LOCK:
        if _REAPER is not None and _REAPER.is_alive():
            return
        _REAPER = threading.Thread(
            target=_reaper_loop, name="zqs-labview-reaper", daemon=True
        )
        # Daemon: LabVIEW closing its Python session must not be held up by us.
        _REAPER.start()


def _reaper_loop() -> None:
    while True:
        try:
            _reap_once()
        except Exception as exc:  # the thread must outlive any single failure
            _set_error(f"reaper: {exc!r}")
        time.sleep(_REAP_INTERVAL)


def _reap_once() -> None:
    """Collect exits and enforce stop deadlines. Cheap; safe to call anywhere."""
    now = time.monotonic()
    with _LOCK:
        for svc in _STATE.values():
            proc = svc.proc
            if proc is None:
                continue

            code = proc.poll()
            if code is None:
                if svc.state == STATUS_STOPPING and now >= svc.kill_deadline:
                    _force_kill(svc)
                continue

            # Exited. A stop we asked for is clean whatever the exit code -
            # SIGTERM and TerminateProcess both report non-zero.
            svc.exit_code = int(code)
            if svc.state == STATUS_STOPPING or code == 0:
                svc.state = STATUS_STOPPED
            else:
                svc.state = STATUS_EXITED
            svc.proc = None
            svc.kill_deadline = 0.0
            _close_log(svc)


def _force_kill(svc: _Service) -> None:
    proc = svc.proc
    if proc is None:
        return
    try:
        if os.name == "nt":
            proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except OSError:
            pass
    # Re-arm: if the kill did not land, try again on the next pass rather than
    # spinning on it now.
    svc.kill_deadline = time.monotonic() + 2.0


def _signal_stop(svc: _Service) -> None:
    """Ask a child to shut down. Never waits for it."""
    proc = svc.proc
    if proc is None:
        return
    if os.name == "nt":
        try:
            # Goes to the whole process group, which is the child's own thanks
            # to CREATE_NEW_PROCESS_GROUP. Silently does nothing when the child
            # was started with CREATE_NO_WINDOW and has no console to receive
            # it - the grace timer covers that case.
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        except (OSError, AttributeError, ValueError):
            try:
                proc.terminate()
            except OSError:
                pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                proc.terminate()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_server(services: str = "") -> int:
    """Start services in the background and return at once.

    ``services``: ``""`` (or ``"all"``) for every service, otherwise a comma
    separated list such as ``"api,worker"``.

    Returns ``RC_OK`` (0) when at least one service was launched,
    ``RC_ALREADY_RUNNING`` (1) when everything requested was already up, or a
    negative code on failure - see :func:`get_last_error` for the reason.

    The call does not wait for the services to become ready. Poll
    :func:`get_status` until it returns ``STATUS_RUNNING``, then poll the API's
    ``/healthz`` if you need readiness rather than liveness.
    """
    try:
        names, unknown = _resolve(services)
        if unknown:
            _set_error(
                f"unknown service(s): {', '.join(unknown)}; "
                f"valid names are {', '.join(_ORDER)}"
            )
            return RC_UNKNOWN_SERVICE

        python = _interpreter()
        if not python:
            _set_error(
                "no Python interpreter found. Expected .venv/Scripts/python.exe "
                "(run scripts\\dev.ps1 -Setup) or set ZQS_PYTHON."
            )
            return RC_NO_INTERPRETER

        _ensure_reaper()
        _reap_once()

        started = 0
        already = 0
        first_error = 0

        with _LOCK:
            env = _child_env(names)
            for name in names:
                svc = _service(name)

                if svc.state == STATUS_RUNNING:
                    already += 1
                    continue
                if svc.state == STATUS_STOPPING:
                    _set_error(f"{name} is still stopping; retry once status is 0")
                    first_error = first_error or RC_BUSY_STOPPING
                    continue

                try:
                    handle, path = _open_log(name)
                except OSError as exc:
                    _set_error(f"{name}: cannot open log file: {exc}")
                    first_error = first_error or RC_SPAWN_FAILED
                    continue

                kwargs = {
                    "cwd": str(ROOT),
                    "env": env,
                    # stdin closed: a child that reads it must fail fast rather
                    # than inherit LabVIEW's and hang.
                    "stdin": subprocess.DEVNULL,
                    "stdout": handle,
                    "stderr": subprocess.STDOUT,
                    "close_fds": True,
                }
                if os.name == "nt":
                    kwargs["creationflags"] = _creation_flags()
                else:
                    # POSIX equivalent of a new process group, so killpg only
                    # reaches the service and not LabVIEW itself.
                    kwargs["start_new_session"] = True

                try:
                    proc = subprocess.Popen(_argv(name, python), **kwargs)
                except (OSError, ValueError) as exc:
                    try:
                        handle.close()
                    except OSError:
                        pass
                    _set_error(f"{name}: spawn failed: {exc}")
                    first_error = first_error or RC_SPAWN_FAILED
                    continue

                svc.proc = proc
                svc.state = STATUS_RUNNING
                svc.started_at = time.time()
                svc.kill_deadline = 0.0
                svc.exit_code = 0
                svc.last_pid = proc.pid
                svc.log_file = handle
                svc.log_path = path
                started += 1

        if first_error:
            return first_error
        if started:
            return RC_OK
        if already:
            return RC_ALREADY_RUNNING
        return RC_OK
    except Exception as exc:  # nothing may reach the Python Node
        _set_error(f"start_server: {exc!r}")
        return RC_ERROR


def stop_server(services: str = "", grace_seconds: float = _GRACE_DEFAULT) -> int:
    """Signal services to stop and return at once.

    ``grace_seconds`` is how long a child may take to exit on its own before it
    is killed; it is clamped to 0.5-120 s. **The wait happens on a background
    thread**, not in this call: the function returns as soon as the signals are
    out, with the affected services in ``STATUS_STOPPING`` (2). Poll
    :func:`get_status` until it returns ``STATUS_STOPPED`` (0).

    Returns ``RC_OK`` (0) when the request was accepted, including when nothing
    was running. Negative on failure.
    """
    try:
        names, unknown = _resolve(services)
        if unknown:
            _set_error(
                f"unknown service(s): {', '.join(unknown)}; "
                f"valid names are {', '.join(_ORDER)}"
            )
            return RC_UNKNOWN_SERVICE

        try:
            grace = float(grace_seconds)
        except (TypeError, ValueError):
            grace = _GRACE_DEFAULT
        if grace != grace or grace < _GRACE_MIN:  # NaN or too small
            grace = _GRACE_MIN
        grace = min(grace, _GRACE_MAX)

        _ensure_reaper()
        _reap_once()

        with _LOCK:
            # Reverse start order: the API last, so it can still answer while
            # the pipeline behind it winds down.
            for name in sorted(names, key=_ORDER.index, reverse=True):
                svc = _service(name)
                if svc.proc is None or svc.state in (STATUS_STOPPED, STATUS_EXITED):
                    continue
                if svc.state == STATUS_STOPPING:
                    continue  # already on its way out; leave the deadline alone
                svc.state = STATUS_STOPPING
                svc.kill_deadline = time.monotonic() + grace
                _signal_stop(svc)
        return RC_OK
    except Exception as exc:
        _set_error(f"stop_server: {exc!r}")
        return RC_ERROR


def get_status(service: str = "") -> int:
    """Current state as an ``int``. The one function LabVIEW should poll.

    With a service name: that service's status. With ``""``: an aggregate over
    all four, in this precedence - any stopping wins (2), then any unexpected
    exit (3), then any running (1), otherwise stopped (0). Unknown name gives
    ``STATUS_UNKNOWN`` (-1).
    """
    try:
        names, unknown = _resolve(service)
        if unknown:
            _set_error(f"unknown service(s): {', '.join(unknown)}")
            return STATUS_UNKNOWN

        # Poll here too, so status is authoritative even in the unlikely case
        # that the reaper thread was never started or has died.
        _reap_once()

        with _LOCK:
            states = [_service(name).state for name in names]

        if len(states) == 1:
            return states[0]
        if STATUS_STOPPING in states:
            return STATUS_STOPPING
        if STATUS_EXITED in states:
            return STATUS_EXITED
        if STATUS_RUNNING in states:
            return STATUS_RUNNING
        return STATUS_STOPPED
    except Exception as exc:
        _set_error(f"get_status: {exc!r}")
        return STATUS_UNKNOWN


def get_status_json() -> str:
    """Everything :func:`get_status` cannot express, as a JSON string.

    ``{"overall": int, "error": str, "services": [{"name", "status", "pid",
    "exit_code", "uptime_seconds", "log", "command"}, ...]}``. Parse it in
    LabVIEW with *Unflatten From JSON*. Always returns a string.
    """
    try:
        _reap_once()
        python = _interpreter()
        now = time.time()
        payload: dict = {"overall": get_status(""), "services": []}
        with _LOCK:
            for name in _ORDER:
                svc = _service(name)
                payload["services"].append(
                    {
                        "name": name,
                        "status": svc.state,
                        "pid": svc.last_pid if svc.state == STATUS_RUNNING else 0,
                        "exit_code": svc.exit_code,
                        "uptime_seconds": (
                            round(now - svc.started_at, 1)
                            if svc.state == STATUS_RUNNING and svc.started_at
                            else 0.0
                        ),
                        "log": svc.log_path,
                        "command": " ".join(_argv(name, python or "python")),
                    }
                )
            payload["error"] = _LAST_ERROR
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"overall": STATUS_UNKNOWN, "error": f"{exc!r}", "services": []})


def get_last_error() -> str:
    """The most recent error message, or ``""`` if there has not been one.

    Read this whenever a function returns a negative code. The message is
    timestamped and survives until :func:`clear_last_error`.
    """
    try:
        with _LOCK:
            return _LAST_ERROR
    except Exception:
        return "get_last_error failed"


def clear_last_error() -> int:
    """Forget the stored error. Always returns 0."""
    global _LAST_ERROR
    try:
        with _LOCK:
            _LAST_ERROR = ""
    except Exception:
        pass
    return RC_OK


def list_services() -> list[str]:
    """Valid service names, in start order."""
    try:
        return list(_ORDER)
    except Exception:
        return []


def get_pid(service: str) -> int:
    """OS process id of a running service, or 0 if it is not running."""
    try:
        names, unknown = _resolve(service)
        if unknown or len(names) != 1:
            _set_error(f"get_pid expects one service name, got {service!r}")
            return 0
        _reap_once()
        with _LOCK:
            svc = _service(names[0])
            return svc.last_pid if svc.state == STATUS_RUNNING else 0
    except Exception as exc:
        _set_error(f"get_pid: {exc!r}")
        return 0


def get_log_path(service: str) -> str:
    """Absolute path of a service's log file, or ``""`` on a bad name."""
    try:
        names, unknown = _resolve(service)
        if unknown or len(names) != 1:
            _set_error(f"get_log_path expects one service name, got {service!r}")
            return ""
        return str(LOG_DIR / f"{names[0]}.log")
    except Exception as exc:
        _set_error(f"get_log_path: {exc!r}")
        return ""


def get_root() -> str:
    """Project root this module is controlling. Useful for a sanity check."""
    try:
        return str(ROOT)
    except Exception:
        return ""
