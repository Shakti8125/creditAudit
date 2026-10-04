#!/usr/bin/env bash
# Local demo launcher (L-01, D12). Run `scripts/demo.sh help` for the commands.
#
# The supported setup is Docker (Postgres and the backend) plus the Vite dev server on the
# host. DEMO_NATIVE=1 is for a backend you started yourself (docs/LOCAL_DEMO.md, "Without
# Docker"): the commands then act on that backend and on the frontend only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT/.demo"
FRONTEND_PID_FILE="$STATE_DIR/frontend.pid"
FRONTEND_LOG="$STATE_DIR/frontend.log"

API_URL="${DEMO_API_URL:-http://localhost:8001}"
APP_URL="http://localhost:5173"
NATIVE="${DEMO_NATIVE:-0}"
PYTHON="${DEMO_PYTHON:-python3}"
WAIT_SECONDS="${DEMO_WAIT:-300}"

say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "'$1' is not installed. $2"; }

compose() { (cd "$ROOT" && docker compose "$@"); }

check_tools() {
  need curl "Install curl."
  if [ "$NATIVE" != "1" ]; then
    need docker "Install Docker Desktop (or Docker Engine) and start it."
    docker compose version >/dev/null 2>&1 || die "'docker compose' (version 2) is not available."
  fi
}

check_env() {
  [ -f "$ROOT/backend/.env" ] ||
    die "backend/.env is missing. Run: cp backend/.env.example backend/.env, then fill in the keys."
}

backend_healthy() {
  curl -fsS --max-time 3 "$API_URL/health" 2>/dev/null | grep -q '"db":"connected"'
}

wait_for_backend() {
  local waited=0
  printf 'Waiting for the backend at %s (the first start loads the models and can take a few minutes)' "$API_URL"
  until backend_healthy; do
    if [ "$waited" -ge "$WAIT_SECONDS" ]; then
      printf '\n'
      die "the backend was not healthy after ${WAIT_SECONDS}s. Try: docker compose logs --tail 60 backend"
    fi
    printf '.'
    sleep 3
    waited=$((waited + 3))
  done
  printf ' ready.\n'
}

require_backend_container() {
  [ "$NATIVE" = "1" ] && return 0
  compose ps --status running --services 2>/dev/null | grep -qx backend ||
    die "the backend container is not running. Run: scripts/demo.sh up"
}

# Run python in the backend: inside the container, or from backend/ with DEMO_NATIVE=1.
backend_python() {
  if [ "$NATIVE" = "1" ]; then
    (cd "$ROOT/backend" && "$PYTHON" "$@")
  else
    compose exec -T backend python "$@"
  fi
}

frontend_running() {
  [ -f "$FRONTEND_PID_FILE" ] || return 1
  local pid command
  pid="$(cat "$FRONTEND_PID_FILE")"
  kill -0 "$pid" 2>/dev/null || return 1
  # The command check guards against a recycled pid belonging to an unrelated process.
  # (No pipe into `grep -q`: under pipefail, a SIGPIPE to `ps` would report a false "not running".)
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  case "$command" in
    *vite*) return 0 ;;
    *) return 1 ;;
  esac
}

start_frontend() {
  if frontend_running; then
    say "The frontend is already running (pid $(cat "$FRONTEND_PID_FILE"))."
    return 0
  fi
  need node "Install Node.js 20 or newer."
  need npm "Install Node.js 20 or newer."
  mkdir -p "$STATE_DIR"
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    say "Installing the frontend packages (first run only)..."
    (cd "$ROOT/frontend" && npm ci --no-audit --no-fund)
  fi
  (
    cd "$ROOT/frontend"
    nohup node_modules/.bin/vite --host 127.0.0.1 --port 5173 --strictPort >"$FRONTEND_LOG" 2>&1 &
    echo $! >"$FRONTEND_PID_FILE"
  )
  local waited=0
  until curl -fsS --max-time 2 "$APP_URL" >/dev/null 2>&1; do
    if ! frontend_running; then
      rm -f "$FRONTEND_PID_FILE"
      die "the frontend did not start. Is port 5173 in use? See $FRONTEND_LOG"
    fi
    if [ "$waited" -ge 60 ]; then
      die "the frontend did not answer within 60s. See $FRONTEND_LOG"
    fi
    sleep 1
    waited=$((waited + 1))
  done
}

stop_frontend() {
  if frontend_running; then
    kill "$(cat "$FRONTEND_PID_FILE")" 2>/dev/null || true
    say "Stopped the frontend."
  fi
  rm -f "$FRONTEND_PID_FILE"
}

cmd_up() {
  check_tools
  check_env
  if [ "$NATIVE" != "1" ]; then
    compose up -d --build
  fi
  wait_for_backend
  start_frontend
  say ""
  say "The demo is up."
  say "  App:      $APP_URL"
  say "  Backend:  $API_URL/health"
  say ""
  say "Next:"
  say "  scripts/demo.sh preflight   are the providers reachable right now?"
  say "  scripts/demo.sh seed        first time only: demo account and synthetic models"
}

cmd_down() {
  stop_frontend
  if [ "$NATIVE" != "1" ]; then
    check_tools
    compose down
  fi
  say "Stopped. Your data is kept; \`scripts/demo.sh reset\` deletes it."
}

cmd_status() {
  say "Backend:  $API_URL"
  if backend_healthy; then say "  healthy (database connected)"; else say "  not reachable"; fi
  say "Frontend: $APP_URL"
  if frontend_running; then say "  running (pid $(cat "$FRONTEND_PID_FILE"))"; else say "  not running"; fi
  if [ "$NATIVE" != "1" ] && command -v docker >/dev/null 2>&1; then
    say "Containers:"
    compose ps 2>/dev/null || true
  fi
}

cmd_seed() {
  check_tools
  check_env
  require_backend_container
  local api="http://localhost:8001"
  [ "$NATIVE" = "1" ] && api="$API_URL"
  backend_python -m scripts.demo.seed --api "$api" --app-url "$APP_URL"
}

cmd_preflight() {
  check_tools
  check_env
  require_backend_container
  backend_python -m scripts.demo.preflight "$@"
}

cmd_fixtures() {
  check_tools
  require_backend_container
  local out="$ROOT/demo-data"
  if [ "$NATIVE" = "1" ]; then
    backend_python -m scripts.demo.fixtures "$out"
  else
    compose exec -T backend python -m scripts.demo.fixtures /tmp/demo-data >/dev/null
    mkdir -p "$out"
    compose cp backend:/tmp/demo-data/. "$out/"
  fi
  say "Wrote the synthetic reports to demo-data/ (upload one in the UI during the demo):"
  ls -1 "$out"
}

cmd_reset() {
  if [ "${1:-}" != "--yes" ]; then
    printf 'This stops the demo and DELETES the demo database (accounts, models, documents). Continue? [y/N] '
    local answer
    read -r answer
    case "$answer" in
      y | Y | yes | YES) ;;
      *) say "Cancelled."; return 0 ;;
    esac
  fi
  stop_frontend
  if [ "$NATIVE" = "1" ]; then
    say "Native mode: drop and recreate your own database (docs/LOCAL_DEMO.md)."
  else
    check_tools
    compose down -v --remove-orphans
  fi
  rm -rf "${STATE_DIR:?}"
  say "Reset. Run: scripts/demo.sh up && scripts/demo.sh seed"
}

cmd_help() {
  cat <<'EOF'
Usage: scripts/demo.sh <command>

  up          Start Postgres and the backend (Docker) and the frontend, and wait until healthy.
  down        Stop everything. The data is kept.
  status      Show whether the backend and frontend answer.
  preflight   Check that the LLM, embedding and Pinecone calls work right now (run it 10 minutes
              before an interview).
  seed        First time only: create a demo account (password shown once) and the synthetic
              model with its two validation reports.
  fixtures    Write the two synthetic reports to demo-data/, to upload one live in the UI.
  reset       Delete the demo database and start clean (asks first; --yes skips the question).
  help        This text.

Settings (environment variables):
  DEMO_NATIVE=1   You started the backend yourself; act on it and the frontend only.
  DEMO_API_URL    Backend URL (default http://localhost:8001).
  DEMO_PYTHON     Python for native mode (default python3).
  DEMO_WAIT       Seconds to wait for the backend (default 300).
EOF
}

case "${1:-help}" in
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  seed) cmd_seed ;;
  preflight) shift; cmd_preflight "$@" ;;
  fixtures) cmd_fixtures ;;
  reset) shift; cmd_reset "${1:-}" ;;
  help | -h | --help) cmd_help ;;
  *) cmd_help >&2; exit 2 ;;
esac
