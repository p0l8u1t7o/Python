# Running ZQS Cloud locally

Two ways to start: a launcher script that does everything, or the individual
commands if you would rather see each moving part.

---

## 1. One command

### Windows (PowerShell)

```powershell
cd "D:\Working Space\Python\ZQS-Cloud"
.\scripts\dev.ps1 -Setup
```

That installs Python and Node dependencies, migrates the database, seeds a demo
tenant, backfills three days of telemetry, then starts the API and the console
and opens a browser.

Afterwards, day to day:

```powershell
.\scripts\dev.ps1          # start
.\scripts\stop.ps1         # stop
```

Each service runs in its own titled PowerShell window (`zqs-api`,
`zqs-frontend`, …) so its log is easy to read. `stop.ps1` kills them by the PID
file written at launch, and sweeps up any strays.

> If PowerShell refuses to run the script, allow local scripts for this user
> once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### Linux, macOS, WSL, Git Bash

```bash
./scripts/dev.sh --setup   # first run
./scripts/dev.sh           # afterwards
```

Everything runs in the one terminal with prefixed output; Ctrl-C stops the
whole stack.

### Flags

| Flag | Effect |
| --- | --- |
| `-Setup` / `--setup` | install, migrate, seed, backfill history. Safe to re-run |
| `-Full` / `--full` | also start the ingestor and worker (needs Redis + EMQX) |
| `-Simulate` / `--simulate` | as `-Full`, plus simulated devices publishing over MQTT |
| `-HistoryDays` / `--history-days` | days of backfill during setup (default 3) |
| `-NoBrowser` | do not open a browser |

### What you get

| | |
| --- | --- |
| Console | <http://127.0.0.1:5173> |
| API docs | <http://127.0.0.1:8000/api/docs> |
| EMQX dashboard (`-Full`) | <http://127.0.0.1:18083> — admin / public |

Sign in as `admin@example.com` / `ChangeMe-2026!`. `operator@example.com` and
`viewer@example.com` use the same password and are useful for seeing how the UI
changes with role: an operator can send commands but not register devices; a
viewer can do neither.

---

## 2. The modes, and why there are three

**Default — API + console.** No broker, no queue. The API reads and writes
SQLite directly, so every page works: device registry, history charts, the
storage dashboard, alerts, configuration. What is *not* running is live
ingestion, so nothing new arrives while you watch.

This is the right mode for building UI or exploring the data model.

**`-Full` — plus ingestor and worker.** This exercises the real data path:
MQTT → ingestor → queue → worker → database. It needs Redis and EMQX:

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
docker run -d --name emqx -p 1883:1883 -p 18083:18083 emqx/emqx:5.8
```

Redis is not optional here. The ingestor and the worker are separate processes,
and `BUS_BACKEND=memory` is a queue inside one process — they would not see each
other's messages. The launcher switches to `BUS_BACKEND=redis` automatically in
this mode and refuses to start if either service is missing.

**`-Simulate` — plus fake hardware.** Three simulators publish battery, meter
and PV telemetry on the real topics, so values move on screen and the whole
chain is under load. This is the closest thing to hardware without hardware.

---

## 3. Demo data

### Backfilled history

```bash
python manage.py generate_history --days 3 --interval 120 --clear --with-faults
```

Writes telemetry straight to the database for the past N days — no broker
involved — then aggregates it into energy intervals. Without this the storage
page and every chart start out empty, because `simulate_device` only produces
data going *forward*.

The generated site follows the seeded storage plan: an office load peaking near
480 kW, 400 kW of rooftop PV, and a 500 kW / 1 MWh battery shaving demand to the
250 kW target and topping up off-peak. So the numbers on the dashboard are the
result of the same aggregator that would run against real hardware, not
hard-coded figures.

| Flag | Effect |
| --- | --- |
| `--days N` | how far back to generate (default 3) |
| `--interval N` | seconds between samples (default 60) |
| `--clear` | delete samples, intervals, events and alerts in the window first |
| `--with-faults` | inject excursions so alert rules fire and device logs fill |
| `--no-alerts` | skip replaying the rule engine |
| `--site CODE` | limit to one site |

`--with-faults` also leaves one excursion running up to "now", so the alerts
page has an open alert rather than only resolved history.

Backfilling also does the two things the worker normally would: it marks the
devices as having reported (otherwise the fleet shows everything offline) and
replays the alert rules over the generated readings.

### Live simulation

```bash
python manage.py simulate_device --device ZQS-BESS-0001 --profile battery --interval 5
python manage.py simulate_device --device ZQS-METER-0001 --profile meter  --interval 5
python manage.py simulate_device --device ZQS-PV-0001    --profile pv     --interval 10
```

Publishes over MQTT using exactly the payloads in
[device-protocol.md](device-protocol.md), so it doubles as a reference for the
LabVIEW implementation. Requires the broker and, to reach the database, the
ingestor and worker.

---

## 4. Doing it by hand

```bash
python -m venv .venv
.venv\Scripts\activate                     # PowerShell
pip install -r requirements.txt
copy .env.example .env

python manage.py migrate
python manage.py bootstrap                 # built-in metrics + blueprints
python manage.py seed_demo                 # tenant, site, devices, rules, tariff
python manage.py generate_history --days 3 --with-faults

python manage.py runserver                 # terminal 1
cd frontend && npm install && npm run dev  # terminal 2
```

Add the live path when you want it:

```bash
python manage.py run_ingestor              # terminal 3
python manage.py run_worker                # terminal 4
```

---

## 5. Troubleshooting

**Port 8000 or 5173 already in use.** A previous stack is still running.
`.\scripts\stop.ps1`, or Ctrl-C in the `dev.sh` terminal.

**`npm` not found right after installing Node.** The PATH is only picked up by
new shells. Open a fresh terminal; the launcher scripts also look in
`C:\Program Files\nodejs` themselves.

**Console loads but every request fails.** The API is not running, or is on a
different port. Check <http://127.0.0.1:8000/healthz>, and
`VITE_PROXY_TARGET` if you moved it.

**The storage page says the data is stale.** The live power flow is marked
stale after five minutes without a sample. Expected with backfilled data alone —
run the simulators, or just read the charts, which are historical anyway.

**Everything shows offline after a while.** The worker marks a device offline
after `DEVICE_OFFLINE_GRACE_SECONDS` (180 s) of silence. That is correct: the
backfill is history, not a live connection.

**Devices are offline and no data arrives in `-Full` mode.** Check the
`zqs-ingestor` window. Unregistered device ids are dropped by design — register
the device, or set `INGEST_AUTO_PROVISION=1` in `.env`.

**Alerts page is empty.** With clean generated data no rule is breached, which
is the honest outcome. Use `--with-faults` to inject excursions.

**Start over.** Delete `data/zqs_cloud.sqlite3` and re-run setup. Nothing else
holds state locally.
