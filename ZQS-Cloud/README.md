# ZQS Cloud

Server-side control and data plane for distributed energy devices: device
registry, MQTT telemetry ingestion, time-series storage, alerting, downlink
control, and behind-the-meter (BTM) storage management.

Devices are expected to speak the protocol in
[docs/device-protocol.md](docs/device-protocol.md) — a LabVIEW implementation
is the intended first client. LabVIEW can also start and stop the services
themselves; see [docs/labview-integration.md](docs/labview-integration.md).

---

## Architecture

```
                     ┌──────────────┐
   devices  ──MQTT──▶│     EMQX     │◀──MQTT── control commands
   (LabVIEW)         └──────┬───────┘              ▲
                            │ subscribe            │ publish
                            ▼                      │
                     ┌──────────────┐        ┌─────┴──────┐
                     │   ingestor   │        │  Django    │
                     │ validate +   │        │  Ninja API │◀── React console
                     │ enqueue      │        └─────┬──────┘
                     └──────┬───────┘              │
                            │                      │
                     ┌──────▼───────┐              │
                     │ Redis Streams│              │
                     │  (or AMQP)   │              │
                     └──────┬───────┘              │
                            │                      │
                     ┌──────▼───────┐              │
                     │    worker    │              │
                     │ batch write  │              │
                     │ rule engine  │              │
                     │ notify       │              │
                     └──────┬───────┘              │
                            ▼                      ▼
                     ┌───────────────────────────────┐
                     │  SQLite / PostgreSQL(Timescale)│
                     └───────────────────────────────┘
```

The split matters: **the ingestor never touches the database**. A slow or
locked database cannot stall MQTT consumption, and the queue absorbs bursts
that would otherwise be dropped at the broker.

| Component | Entry point | Scale by |
| --- | --- | --- |
| API | `gunicorn config.wsgi` | replicas behind a load balancer |
| Ingestor | `manage.py run_ingestor` | replicas (EMQX shared subscriptions) |
| Worker | `manage.py run_worker` | replicas (one consumer group) |
| Scheduler | `aggregate_energy`, `build_rollups`, `prune_telemetry` | one instance |

---

## Quick start

One command sets everything up and starts it — API, console, demo tenant and
three days of telemetry to look at:

```powershell
.\scripts\dev.ps1 -Setup          # Windows
```

```bash
./scripts/dev.sh --setup          # Linux, macOS, WSL, Git Bash
```

Afterwards `.\scripts\dev.ps1` (or `./scripts/dev.sh`) to start, and
`.\scripts\stop.ps1` (or Ctrl-C) to stop.

| | |
| --- | --- |
| Console | <http://127.0.0.1:5173> |
| API docs | <http://127.0.0.1:8000/api/docs> |
| Sign in | `admin@example.com` / `ChangeMe-2026!` |

Add `-Simulate` / `--simulate` to also run the MQTT ingestor, the queue worker
and simulated hardware — the full live path. That needs Redis and EMQX:

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
docker run -d --name emqx -p 1883:1883 -p 18083:18083 emqx/emqx:5.8
```

Redis is required in that mode: the ingestor and worker are separate processes,
so the in-memory bus cannot connect them.

Full detail, the manual commands and troubleshooting are in
**[docs/running-locally.md](docs/running-locally.md)**.

## Quick start (Docker)

```bash
copy .env.example .env
docker compose up -d
docker compose exec api python manage.py seed_demo
```

Then configure the EMQX auth/ACL webhooks — see
[deploy/emqx/README.md](deploy/emqx/README.md).

---

## Configuration

Everything is environment-driven; see [.env.example](.env.example) for the full
list with defaults. The choices worth knowing about:

| Variable | Options | Notes |
| --- | --- | --- |
| `DB_ENGINE` | `sqlite`, `postgres`, `timescale` | SQLite is the default and runs the whole system; switch for scale |
| `BUS_BACKEND` | `redis`, `rabbitmq`, `memory` | Redis Streams by default; `rabbitmq` needs `requirements-optional.txt` |
| `CACHE_BACKEND` | `locmem`, `redis` | use `redis` once the API runs more than one replica, so rate limits are shared |
| `MQTT_USE_SHARED_SUBSCRIPTION` | `1`, `0` | `1` to scale ingestors, `0` for a single instance with a persistent session |
| `INGEST_AUTO_PROVISION` | `0`, `1` | `1` registers unknown devices on first uplink |
| `EMQX_WEBHOOK_TOKEN` | any secret | empty keeps the broker webhooks disabled |

### Swapping the database

Nothing in the application code is SQLite-specific. All SQL that is not plain
ORM lives in [apps/telemetry/repository.py](apps/telemetry/repository.py), which
branches on `connection.vendor` for the two engine-specific operations
(time-bucketing and the latest-value upsert).

To move to PostgreSQL: set `DB_ENGINE=postgres` plus credentials, install
`requirements-optional.txt`, and run `migrate`. For TimescaleDB additionally
set `TIMESCALE_ENABLED=1` and convert the sample table to a hypertable:

```sql
SELECT create_hypertable('telemetry_sample', 'ts', migrate_data => true);
```

---

## Feature map

| Requirement | Where |
| --- | --- |
| Account and permission management | `apps/accounts` — users, organisations, 4 roles, API keys, JWT with refresh rotation |
| Multi-device status and registered names | `apps/devices` — registry, connection state, `GET /api/devices` |
| Device locations on a map | `GET /api/devices/map` — device-reported GPS, falling back to the site address |
| Choosing which time series to record | `apps/telemetry` — recording policies with per-metric interval, deadband, heartbeat and retention |
| Device alarms and operation records | `apps/devices` events, `apps/alerts` alerts, `apps/audit` operator trail |
| Light / dark theme | stored per user (`PATCH /api/auth/me/preferences`), rendered by the console |
| Multi-language (en / zh-Hant / zh-Hans) | user preference + translated metric labels + `Accept-Language` |
| Behind-the-meter storage management | `apps/ems` — asset roles, storage plan, TOU tariffs, 15-minute energy intervals, savings |

---

## API

Base path `/api`. Full interactive documentation at `/api/docs` in DEBUG.

**Authentication.** Either a user token or a machine key:

```http
Authorization: Bearer <access_token>
Authorization: ApiKey zqs_<prefix>.<secret>
```

A user in several organisations selects one with `X-Organization: <slug>`;
with a single membership it is implied.

**Errors** are uniform, with a stable `code` the console maps to a translated
message:

```json
{"error": {"code": "parameter_out_of_range", "message": "...", "details": {...}}}
```

### Main endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/login`, `/auth/refresh`, `/auth/logout` | session lifecycle |
| `GET` | `/auth/me` | profile, role, effective permissions |
| `PATCH` | `/auth/me/preferences` | theme, language, timezone |
| `GET/POST` | `/sites` | site registry |
| `GET/POST` | `/devices` | device registry (creation returns MQTT credentials once) |
| `GET` | `/devices/map` | map markers with alert severity |
| `GET` | `/devices/{id}` | detail with latest values and available commands |
| `POST` | `/devices/{id}/commands` | **downlink control** |
| `GET` | `/devices/{id}/events` | device-reported operation log |
| `GET` | `/blueprints` | device types and their command catalogues |
| `GET/POST` | `/metrics` | metric catalogue |
| `GET/POST/PUT` | `/recording-policies` | which series to record, and how |
| `POST` | `/telemetry/series` | time-series query, auto-downsampled |
| `GET` | `/telemetry/latest` | current values |
| `GET/POST/PUT` | `/alert-rules` | threshold rules |
| `GET` | `/alerts`, `/alerts/summary` | alert lifecycle |
| `POST` | `/alerts/{id}/acknowledge`, `/resolve` | operator actions |
| `GET` | `/audit` | operator audit trail |
| `GET` | `/ems/sites/{id}/overview` | live BTM power flow + today's energy |
| `GET` | `/ems/sites/{id}/summary` | energy, cost, savings, self-consumption |
| `GET/PUT` | `/ems/sites/{id}/plan` | storage strategy and limits |
| `GET` | `/system/health`, `/system/capabilities` | probes and SPA bootstrap |

---

## Operations

```bash
python manage.py bootstrap --update-existing   # refresh built-in catalogues
python manage.py generate_history --days 3     # backfill demo telemetry
python manage.py aggregate_energy --hours 2    # rebuild BTM intervals
python manage.py build_rollups --interval 900  # chart aggregates
python manage.py prune_telemetry --dry-run     # retention preview
python manage.py createsuperuser               # platform administrator
```

Schedule `aggregate_energy` and `build_rollups` every ~5 minutes, and
`prune_telemetry` daily. The `scheduler` service in `docker-compose.yml`
already does this; `python manage.py run_scheduler` is the same loop as a
single long-lived process, for hosts without cron or a shell.

### From LabVIEW

`services/labview/labview_api.py` supervises the four services from LabVIEW's
Python Node: non-blocking start and stop, integer status codes to poll, output
to log files. See [docs/labview-integration.md](docs/labview-integration.md).

### Health

`GET /healthz` is a liveness probe that deliberately avoids the database.
`GET /api/system/health` is the readiness probe and reports each dependency
(database, message bus, MQTT) separately.

---

## Testing

```bash
python manage.py test tests
```

140 tests covering the ingest pipeline end to end (payload → bus → worker →
database), the alert engine's timing and hysteresis behaviour, recording
policy resolution and the deadband gate, EMS energy integration and tariff
resolution, the API's authentication, RBAC, tenant isolation and audit trail,
and the LabVIEW supervisor's process state machine.

---

## Project layout

```
apps/
  accounts/    users, organisations, roles, API keys, JWT
  core/        base models, errors, logging, throttling, time handling
  devices/     sites, blueprints, devices, credentials, commands, EMQX webhooks
  telemetry/   metric catalogue, recording policy, samples, rollups, queries
  alerts/      threshold rules, alert lifecycle, notification channels
  audit/       operator audit trail
  ems/         behind-the-meter assets, storage plan, tariffs, energy intervals
services/
  bus/         message bus abstraction (Redis Streams / RabbitMQ / in-memory)
  mqtt/        topic grammar, reconnecting client, downlink publisher
  ingestor/    MQTT subscriber: validate and enqueue
  worker/      queue consumer: persist, evaluate, notify, maintain
  labview/     non-blocking process control for LabVIEW's Python Node
config/        settings, API assembly, URLs
frontend/      React console (see frontend/README.md)
scripts/       dev.ps1 / dev.sh launchers, stop.ps1
docs/          device protocol, local development, LabVIEW integration
deploy/        EMQX configuration notes
tests/         test suite
```

---

## Front end

The React console lives in [frontend/](frontend/) and has its own
[README](frontend/README.md).

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173, proxies /api to :8000
```

Vite 6 + React 19 + TypeScript (strict), TanStack Query for server state,
Tailwind 4 for styling, Recharts for time series and the energy balance,
Leaflet for the map, i18next for English / 繁體中文 / 简体中文.

| Route | What it does |
| --- | --- |
| `/` | fleet counts, open alerts, site rollup, dependency health |
| `/devices`, `/devices/:id` | registry, live values, history, commands, device log, connection history |
| `/map` | device markers coloured by status and worst open alert |
| `/alerts` | severity filters, bulk acknowledge, alert timeline |
| `/storage` | behind-the-meter: live power flow, energy balance, SOC, cost and savings |
| `/telemetry` | pick devices × metrics, chart, CSV export, metric catalogue |
| `/sites`, `/recording`, `/rules` | site, recording-policy and alert-rule editors |
| `/audit`, `/settings` | audit trail; profile, appearance, members, API keys |
