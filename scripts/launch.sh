#!/usr/bin/env bash
# Launch the connector for local use: backend (uvicorn, :8001) + frontend dev server (vite, :5173).
# Usage: scripts/launch.sh [start|stop|restart|status|logs] [--docker]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/.run"
BACKEND_PORT="${BACKEND_PORT:-8001}" # 8000 is commonly taken by other local dev containers
export VITE_BACKEND_URL="${VITE_BACKEND_URL:-http://localhost:$BACKEND_PORT}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

cmd="${1:-start}"
mode="local"
[[ "${2:-}" == "--docker" || "${1:-}" == "--docker" ]] && mode="docker"
[[ "$cmd" == "--docker" ]] && cmd="start"

mkdir -p "$RUN_DIR"

is_running() {
  local pidfile="$RUN_DIR/$1.pid"
  [[ -f "$pidfile" ]] && kill -0 "$(<"$pidfile")" 2>/dev/null
}

wait_for() { # name url
  for _ in $(seq 1 40); do
    curl -fsS -o /dev/null "$2" 2>/dev/null && { echo "  $1 up: $2"; return 0; }
    sleep 0.5
  done
  echo "  $1 did not answer at $2 -- see: scripts/launch.sh logs" >&2
  return 1
}

start_one() { # name workdir command...
  local name="$1" dir="$2"; shift 2
  if is_running "$name"; then echo "  $name already running (pid $(<"$RUN_DIR/$name.pid"))"; return 0; fi
  # setsid may fork, so $! is not the group leader: the leader records its own pid, then execs the command
  (cd "$dir" && setsid nohup bash -c 'echo $$ >"$0"; exec "$@"' "$RUN_DIR/$name.pid" "$@" >"$RUN_DIR/$name.log" 2>&1 &)
}

stop_one() {
  local name="$1" pidfile="$RUN_DIR/$1.pid"
  if is_running "$name"; then
    local pid; pid="$(<"$pidfile")"
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    echo "  $name stopped"
  fi
  rm -f "$pidfile"
}

do_start() {
  if [[ "$mode" == "docker" ]]; then
    (cd "$ROOT" && docker compose up -d --build)
    wait_for "app" "http://localhost:${CONNECTOR_PORT:-8000}/health" || true
    echo "UI: http://localhost:${CONNECTOR_PORT:-8000}/"
    return
  fi

  if [[ ! -f "$ROOT/.env" ]]; then
    echo "Missing .env. Run: cp .env.example .env  (set ENCRYPTION_KEY and ADMIN_BOOTSTRAP_*)" >&2
    exit 1
  fi
  command -v uv >/dev/null || { echo "uv not found" >&2; exit 1; }
  command -v npm >/dev/null || { echo "npm not found" >&2; exit 1; }

  [[ -d "$ROOT/.venv" ]] || (cd "$ROOT" && uv sync)
  [[ -d "$ROOT/frontend/node_modules" ]] || (cd "$ROOT/frontend" && npm ci)

  echo "Starting..."
  start_one backend "$ROOT" uv run uvicorn conector_odoo.main:create_app --factory --host 0.0.0.0 --port "$BACKEND_PORT"
  start_one frontend "$ROOT/frontend" npm run dev -- --port "$FRONTEND_PORT"

  wait_for backend "http://localhost:$BACKEND_PORT/docs" || true
  wait_for frontend "http://localhost:$FRONTEND_PORT/" || true
  echo "UI:  http://localhost:$FRONTEND_PORT/   (hot reload)"
  echo "API: http://localhost:$BACKEND_PORT/docs"
  echo "Stop: scripts/launch.sh stop"
}

do_stop() {
  if [[ "$mode" == "docker" ]]; then (cd "$ROOT" && docker compose down); return; fi
  stop_one frontend
  stop_one backend
}

do_status() {
  for n in backend frontend; do
    if is_running "$n"; then echo "$n: running (pid $(<"$RUN_DIR/$n.pid"))"; else echo "$n: stopped"; fi
  done
}

do_logs() {
  if [[ "$mode" == "docker" ]]; then (cd "$ROOT" && docker compose logs --tail 50 connector); return; fi
  for n in backend frontend; do
    echo "== $n =="; tail -n 25 "$RUN_DIR/$n.log" 2>/dev/null || echo "(no log)"
  done
}

case "$cmd" in
  start) do_start ;;
  stop) do_stop ;;
  restart) do_stop; do_start ;;
  status) do_status ;;
  logs) do_logs ;;
  *) echo "Usage: $0 [start|stop|restart|status|logs] [--docker]" >&2; exit 2 ;;
esac
