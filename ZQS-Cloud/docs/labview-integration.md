# Controlling the services from LabVIEW

[`services/labview/labview_api.py`](../services/labview/labview_api.py) starts
and stops the ZQS Cloud services from a LabVIEW VI through the Python Node.

The Python Node is a synchronous call: the block diagram waits for the function
to return and cannot interrupt it. Every function here therefore returns in
milliseconds and reports progress through state you poll, never by blocking.

---

## Before the first call

The module supervises processes; it does not run Django itself. Set the project
up once so there is something to start:

```powershell
.\scripts\dev.ps1 -Setup -NoBrowser
.\scripts\stop.ps1
```

That creates `.venv`, installs dependencies, migrates and seeds. `labview_api`
then launches the services with `.venv\Scripts\python.exe` — the same
interpreter `dev.ps1` uses.

---

## LabVIEW setup

| Field on the Python Node | Value |
| --- | --- |
| Python Version | whichever version your LabVIEW build supports |
| Module Path | `D:\Working Space\Python\ZQS-Cloud\services\labview\labview_api.py` |
| Function Name | one of the names below |

The two interpreters do not have to match. `labview_api` imports nothing but
the standard library — no Django, no `requirements.txt` — so LabVIEW can load
it on the Python it supports while the services run on the project's 3.12
virtualenv underneath.

Wire the *session* through the whole VI. LabVIEW keeps that Python session
alive between calls, which is exactly what lets the module remember the
process handles it started.

---

## Functions

| Function | Arguments | Returns | Notes |
| --- | --- | --- | --- |
| `start_server` | `services` (str) | int return code | launches and returns; does not wait for readiness |
| `stop_server` | `services` (str), `grace_seconds` (float) | int return code | signals and returns; the grace period runs in the background |
| `get_status` | `service` (str) | int status | the function to poll |
| `get_status_json` | — | str (JSON) | per-service pid, exit code, uptime, log path |
| `get_last_error` | — | str | `""` when clean; read it after any negative code |
| `clear_last_error` | — | int (always 0) | |
| `list_services` | — | str array | `api`, `ingestor`, `worker`, `scheduler` |
| `get_pid` | `service` (str) | int | 0 when not running |
| `get_log_path` | `service` (str) | str | absolute path, `""` on a bad name |
| `get_root` | — | str | project root, for a sanity check |

`services` accepts `""` or `"all"` for everything, or a comma-separated list
such as `"api,worker"` (spaces work too, case does not matter). A 1-D string
array from LabVIEW is accepted as well. `grace_seconds` is clamped to
0.5–120 s; the default is 5.

Types are limited to what the Python Node can represent: `int`, `float`, `str`
and arrays of those. No function returns `None`, a boolean, a dictionary or an
object, and none of them raises — a failure is a negative return code plus a
message in `get_last_error`.

### Services

| Name | Command | Needs |
| --- | --- | --- |
| `api` | `manage.py runserver --noreload 127.0.0.1:8000` | nothing |
| `ingestor` | `manage.py run_ingestor` | EMQX 1883, Redis 6379 |
| `worker` | `manage.py run_worker` | Redis 6379 |
| `scheduler` | `manage.py run_scheduler` | nothing |

`--noreload` is deliberate: Django's autoreloader forks a second process, and
signalling the parent would leave the child holding port 8000.

Starting `ingestor` or `worker` sets `BUS_BACKEND=redis` for the children
unless the environment already names a backend — same rule as `dev.ps1`,
because separate processes cannot share the in-memory bus.

---

## Status codes — `get_status`

| Code | Meaning |
| --- | --- |
| `0` | STOPPED — not running: never started, or stopped cleanly |
| `1` | RUNNING — the process is alive |
| `2` | STOPPING — signalled; inside the grace period or being killed |
| `3` | EXITED — died on its own with a non-zero code; read the log |
| `-1` | UNKNOWN — unknown service name |

With `""`, the answer covers all four services, by precedence: any stopping
gives 2, then any unexpected exit gives 3, then any running gives 1, otherwise
0. Use `get_status_json` when you need to know *which* one.

`1` means the process is alive, not that the API is answering. For readiness,
poll `http://127.0.0.1:8000/healthz` from LabVIEW's HTTP client after the
status turns 1.

## Return codes — `start_server`, `stop_server`

| Code | Meaning |
| --- | --- |
| `0` | OK — the request was accepted |
| `1` | ALREADY RUNNING — every service asked for was already up; nothing was restarted |
| `-1` | internal error |
| `-2` | unknown service name |
| `-3` | no Python interpreter found — run `dev.ps1 -Setup`, or set `ZQS_PYTHON` |
| `-4` | spawn failed — bad path, permissions, or no room for the log file |
| `-5` | busy stopping — retry once the status is 0 |

`0` and `1` are both success. Treat anything negative as a failure and read
`get_last_error`.

---

## Polling patterns

### Start

```
start_server("")            →  code
  code < 0                  →  get_last_error, show it, stop
  code = 0 or 1             →  continue
loop, every 250-500 ms:
    get_status("")          →  1  ready to work
                            →  3  a service died   → get_status_json, log it
                            →  0  still nothing up → give up after ~30 s
```

A start that "fails" late — bad settings, port in use, Redis down — shows up as
status 3 with a non-zero `exit_code` in `get_status_json`, usually within a
second or two. Do not treat the first 0 as failure; give it a timeout.

### Stop

```
stop_server("", 5.0)        →  0
loop, every 250-500 ms:
    get_status("")          →  2  still shutting down, keep polling
                            →  0  done
```

The loop is guaranteed to finish: when the grace period expires the background
thread kills whatever is left, so the status reaches 0 without further calls
from LabVIEW. Allow `grace_seconds + 5 s` before declaring a problem.

### Restart

There is no `restart_server`. Call `stop_server`, poll until 0, then
`start_server`. Starting during a shutdown returns `-5` rather than racing it.

### If the VI aborts

The services are separate processes and outlive the VI, and the module's state
lives in LabVIEW's Python session. Reopening the session gives you a supervisor
with no handles: `get_status` reports 0 while the old processes are still
running, and `start_server` will then fail on the port. Recover with
`scripts\stop.ps1`, which finds them by command line.

---

## Logs

Each service appends to `logs\labview\<service>.log`, rotated to `.log.1` past
5 MB. `get_log_path` returns the path so the VI can show it.

Output goes to a file rather than a pipe on purpose: an OS pipe nobody drains
fills after roughly 64 KB and the child then blocks forever on its next write.
Nothing in this module reads the children's output, so a pipe would eventually
hang the whole stack. There is a regression test for this.

---

## Environment overrides

| Variable | Effect |
| --- | --- |
| `ZQS_PYTHON` | interpreter to launch the services with, instead of `.venv` |
| `ZQS_API_BIND` | API bind address; default `127.0.0.1:8000` |
| `ZQS_LABVIEW_CONSOLE` | `1` gives each service a visible console window |
| `BUS_BACKEND` | set explicitly to override the automatic `redis` choice |

---

## Windows behaviour, and one honest caveat

Children are created with `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`, plus
`stdin` closed and output redirected to the log file. The new process group
means a Ctrl-C in some operator's console cannot reach services LabVIEW owns,
and it makes `CTRL_BREAK_EVENT` deliverable to one service alone.

The caveat: `CREATE_NO_WINDOW` leaves the child with no console, and a process
with no console cannot *receive* a console control event. So the polite
`CTRL_BREAK_EVENT` that `stop_server` sends is best-effort — under the default
flags it will usually do nothing and shutdown completes when the grace period
expires and the process is terminated. That is abrupt: no Django shutdown
hooks, no final flush.

If graceful shutdown matters more than a tidy screen, set
`ZQS_LABVIEW_CONSOLE=1`. Each service then gets its own console window,
`CTRL_BREAK_EVENT` is delivered, and `run_ingestor`, `run_worker` and
`run_scheduler` exit cleanly on it — `run_scheduler` handles `SIGBREAK`
explicitly for this. The kill remains as the backstop.

On Linux and macOS the equivalent path is used instead: a new session,
`SIGTERM` to the process group, `SIGKILL` after the grace period. That path is
covered by tests; the Windows flags are not testable off Windows, so
`tests/test_labview_api.py` asserts on how the flags are chosen and leaves
their effect to be confirmed on a Windows machine.

---

## Tests

```bash
python manage.py test tests.test_labview_api
```

38 tests, no database, about a second. They cover the state machine, repeated
starts, the non-blocking guarantee (a stop of a 60-second child returns in
under a second), the grace-period kill for a child that ignores `SIGTERM`,
crash versus clean-exit reporting, log redirection under 800 KB of output, and
that no argument — including junk types — can make a function raise.
