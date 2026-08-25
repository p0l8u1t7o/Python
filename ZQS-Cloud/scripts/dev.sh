#!/usr/bin/env bash
#
# Starts the ZQS Cloud development stack (Linux, macOS, WSL, Git Bash).
#
# Everything runs in this one terminal with prefixed, colour-coded output;
# Ctrl-C stops the whole stack.
#
#   ./scripts/dev.sh --setup       first run: install, migrate, seed, backfill
#   ./scripts/dev.sh               API + console only, no broker needed
#   ./scripts/dev.sh --full        also ingestor + worker (needs Redis + EMQX)
#   ./scripts/sim-console.ps1      (Windows) bring registered devices online as MQTT clients
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SETUP=0
FULL=0
NO_BROKER=0
HISTORY_DAYS=3

while [[ $# -gt 0 ]]; do
  case "$1" in
    --setup) SETUP=1 ;;
    --full) FULL=1 ;;
    --no-broker) NO_BROKER=1 ;;
    --history-days) HISTORY_DAYS="$2"; shift ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
CYAN=$'\033[36m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; RESET=$'\033[0m'
step() { printf '%s==> %s%s\n' "$CYAN" "$1" "$RESET"; }
ok()   { printf '    %s%s%s\n' "$GREEN" "$1" "$RESET"; }
warn() { printf '    %s%s%s\n' "$YELLOW" "$1" "$RESET"; }

# Git Bash on Windows uses .venv/Scripts; POSIX venvs use .venv/bin.
if [[ -x .venv/Scripts/python.exe ]]; then
  PYTHON=".venv/Scripts/python.exe"
elif [[ -x .venv/bin/python ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON=""
fi

# A fresh Node install on Windows is not on PATH until the shell restarts.
if ! command -v npm >/dev/null 2>&1 && [[ -d "/c/Program Files/nodejs" ]]; then
  export PATH="$PATH:/c/Program Files/nodejs"
fi

port_open() {
  # bash's /dev/tcp is enough here and avoids depending on nc being installed.
  (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1 && exec 3<&- && exec 3>&- && return 0
  return 1
}

wait_for_http() {
  local url="$1" deadline=$((SECONDS + ${2:-45}))
  while ((SECONDS < deadline)); do
    if curl -fsS -o /dev/null --max-time 3 "$url" 2>/dev/null; then return 0; fi
    sleep 0.5
  done
  return 1
}

PIDS=()
NAMES=()
COLORS=("$GREEN" "$CYAN" "$YELLOW" "$DIM" "$GREEN" "$CYAN")

cleanup() {
  echo
  step 'Stopping'
  for i in "${!PIDS[@]}"; do
    if kill -0 "${PIDS[$i]}" 2>/dev/null; then
      kill "${PIDS[$i]}" 2>/dev/null || true
      ok "${NAMES[$i]} stopped"
    fi
  done
  # npm spawns vite as a child, so killing npm can leave the dev server holding
  # port 5173. Sweep for anything we launched that outlived its parent.
  if command -v pkill >/dev/null 2>&1; then
    pkill -f "$ROOT/frontend.*vite" 2>/dev/null || true
    pkill -f 'manage.py (runserver|run_ingestor|run_worker|run_pipeline|run_scheduler|run_workflows)' 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

start_service() {
  local name="$1"; shift
  local color="${COLORS[${#PIDS[@]} % ${#COLORS[@]}]}"
  # Prefix every line so one terminal stays readable with five services in it.
  # A read loop rather than `sed -u`, which is a GNU extension BSD sed lacks;
  # and process substitution rather than a pipeline, so $! is the service's own
  # PID and not a subshell that could be killed while the service lives on.
  "$@" > >(while IFS= read -r line; do
             printf '%s[%s]%s %s
' "$color" "$name" "$RESET" "$line"
           done) 2>&1 &
  PIDS+=($!)
  NAMES+=("$name")
  ok "$name"
}

# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------
if [[ $SETUP -eq 1 ]]; then
  step 'Setting up the backend'
  # Show the commands' own summaries during setup, not framework INFO logs.
  SETUP_LOG_LEVEL="${LOG_LEVEL:-}"
  export LOG_LEVEL=WARNING
  if [[ -z "$PYTHON" ]]; then
    if command -v py >/dev/null 2>&1; then py -3.12 -m venv .venv; else python3 -m venv .venv; fi
    PYTHON=$([[ -x .venv/Scripts/python.exe ]] && echo ".venv/Scripts/python.exe" || echo ".venv/bin/python")
    ok 'created .venv'
  fi
  # One file: runtime, the development broker, ruff, and the optional backends.
  "$PYTHON" -m pip install --disable-pip-version-check -q -r requirements.txt
  ok 'python dependencies installed'

  [[ -f .env ]] || { cp .env.example .env; ok 'created .env from .env.example'; }

  "$PYTHON" manage.py migrate --noinput >/dev/null
  "$PYTHON" manage.py bootstrap >/dev/null
  "$PYTHON" manage.py seed_demo >/dev/null
  ok 'database migrated, catalogues and demo tenant seeded'

  if [[ "$HISTORY_DAYS" != "0" ]]; then
    step "Generating $HISTORY_DAYS day(s) of telemetry history"
    # --with-faults on purpose: --setup is a demo bootstrap, and without
    # excursions the alerts page and the device logs start out empty.
    "$PYTHON" manage.py generate_history --days "$HISTORY_DAYS" --interval 120 --clear --with-faults
  fi

  if [[ -n "$SETUP_LOG_LEVEL" ]]; then export LOG_LEVEL="$SETUP_LOG_LEVEL"; else unset LOG_LEVEL; fi

  step 'Setting up the front end'
  (cd frontend && npm install --no-audit --no-fund --silent)
  ok 'node dependencies installed'
fi

[[ -n "$PYTHON" ]] || { echo "Virtualenv not found. Run: ./scripts/dev.sh --setup" >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo 'npm not found. Install Node.js 20+.' >&2; exit 1; }

# --------------------------------------------------------------------------
# Preconditions
# --------------------------------------------------------------------------
for port in 8000 5173; do
  if port_open "$port"; then
    echo "Port $port is already in use." >&2
    exit 1
  fi
done

# Default: the bundled development broker plus a combined ingestor+worker
# process, so the whole live path works with nothing to install and nothing to
# run in Docker. --full swaps in real EMQX and Redis; --no-broker drops the
# live path for anyone who only wants the console and the API.
BUS_BACKEND=memory
MQTT_ENABLED=1
MQTT_PROTOCOL_VERSION=311   # the bundled broker speaks 3.1.1 only
MQTT_USE_SHARED_SUBSCRIPTION=0
USE_BUNDLED_BROKER=1

if [[ $FULL -eq 1 || $NO_BROKER -eq 1 ]]; then
  USE_BUNDLED_BROKER=0
fi
if [[ $NO_BROKER -eq 1 ]]; then
  MQTT_ENABLED=0
  warn 'running without a broker (--no-broker): live ingest and commands are off'
fi
if [[ $USE_BUNDLED_BROKER -eq 1 ]] && port_open 1883; then
  # Something is already on 1883 - very likely a real broker started on
  # purpose. Use it rather than failing to bind on top of it.
  USE_BUNDLED_BROKER=0
  MQTT_PROTOCOL_VERSION=5
  MQTT_USE_SHARED_SUBSCRIPTION=1
  ok 'a broker is already listening on 1883 - using it'
fi

if [[ $FULL -eq 1 ]]; then
  missing=0
  port_open 6379 || { warn 'Redis is not running:  docker run -d --name redis -p 6379:6379 redis:7-alpine'; missing=1; }
  port_open 1883 || { warn 'EMQX is not running:   docker run -d --name emqx -p 1883:1883 -p 18083:18083 emqx/emqx:5.8'; missing=1; }
  if [[ $missing -eq 1 ]]; then
    echo 'Start the missing services and try again, or drop --full.' >&2
    exit 1
  fi
  # The ingestor and worker are separate processes, so they need a real broker;
  # the in-memory bus is per-process only.
  BUS_BACKEND=redis
  MQTT_ENABLED=1
  MQTT_PROTOCOL_VERSION=5
  MQTT_USE_SHARED_SUBSCRIPTION=1
  ok 'Redis and EMQX reachable'
fi

export BUS_BACKEND MQTT_ENABLED MQTT_PROTOCOL_VERSION MQTT_USE_SHARED_SUBSCRIPTION

# --------------------------------------------------------------------------
# Launch
# --------------------------------------------------------------------------
step 'Starting services'

if [[ $USE_BUNDLED_BROKER -eq 1 ]]; then
  start_service broker "$PYTHON" manage.py run_broker
  # Let it bind before the ingestor tries to connect. It would retry anyway;
  # this only keeps the first log lines clean.
  sleep 1
fi

start_service api "$PYTHON" manage.py runserver 127.0.0.1:8000

if [[ $FULL -eq 1 ]]; then
  start_service ingestor "$PYTHON" manage.py run_ingestor
  start_service worker "$PYTHON" manage.py run_worker
elif [[ $NO_BROKER -eq 0 ]]; then
  # One process, because the in-memory bus cannot cross a process boundary -
  # see run_pipeline's docstring.
  start_service pipeline "$PYTHON" manage.py run_pipeline
fi

start_service workflows "$PYTHON" manage.py run_workflows
# Energy intervals, rollups, sessions and the dispatch engine. 60 s rather
# than the production 300 s so a strategy decision lands within a minute.
start_service scheduler "$PYTHON" manage.py run_scheduler --interval 60
start_service web npm --prefix frontend run dev

# No simulator is started here: registered devices stay offline until the
# desktop console (scripts/sim_console.py) brings them online.

# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
step 'Waiting for the API'
wait_for_http http://127.0.0.1:8000/healthz && ok 'API is up' || warn 'API did not answer in time'

step 'Waiting for the console'
wait_for_http http://127.0.0.1:5173/ 60 && ok 'console is up' || warn 'Vite did not answer in time'

cat <<EOF

${GREEN}ZQS Cloud is running${RESET}
  console    http://127.0.0.1:5173
  API docs   http://127.0.0.1:8000/api/docs
$([[ $FULL -eq 1 ]] && echo '  EMQX       http://127.0.0.1:18083  (admin / public)')

  sign in    admin@example.com / ChangeMe-2026!
             operator@example.com, viewer@example.com (same password)

  Ctrl-C to stop everything.
EOF

if [[ $USE_BUNDLED_BROKER -eq 1 ]]; then
  ok 'development broker on mqtt://127.0.0.1:1883 - anonymous, no ACL, dev only'
  echo '  Live telemetry is flowing. Use --full for real EMQX + Redis.'
fi
[[ $NO_BROKER -eq 0 ]] || warn 'Live MQTT ingest is not running (--no-broker). MQTT shows as disabled, not failed.'

wait
