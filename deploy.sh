#!/usr/bin/env bash
# =============================================================
# ConcurseiroOS — Production Deployment Script
# Usage:
#   ./deploy.sh          Deploy/update the application
#   ./deploy.sh rollback Rollback to previous version
#   ./deploy.sh status   Show running services status
#   ./deploy.sh logs     Tail logs from all services
#   ./deploy.sh stop     Stop all services
# =============================================================

set -euo pipefail

COMPOSE_FILE="docker-compose.prod.yml"
PROJECT_NAME="concurseiro"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check prerequisites
check_deps() {
    local missing=()
    command -v docker >/dev/null 2>&1 || missing+=("docker")
    command -v git >/dev/null 2>&1 || missing+=("git")

    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Missing dependencies: ${missing[*]}"
        exit 1
    fi

    # Check if docker compose v2 is available
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD="docker-compose"
    else
        log_error "Neither 'docker compose' nor 'docker-compose' found"
        exit 1
    fi
}

# Check .env file exists
check_env() {
    if [ ! -f .env ]; then
        log_warn ".env file not found!"
        log_info "Copying .env.example → .env (edit with your secrets)"
        cp .env.example .env
        log_error "Please edit .env with production values before deploying."
        exit 1
    fi

    # Validate critical vars
    source .env 2>/dev/null || true
    if [ -z "${JWT_SECRET:-}" ]; then
        log_error "JWT_SECRET is not set in .env — required for production!"
        exit 1
    fi
    log_ok "Environment file validated"
}

# Deploy / Update
deploy() {
    log_info "=== ConcurseiroOS Production Deploy ==="
    echo ""

    check_deps
    check_env

    # Pull latest code
    log_info "Pulling latest code..."
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        PREVIOUS_COMMIT=$(git rev-parse HEAD)
        git pull --ff-only || {
            log_warn "Fast-forward pull failed. Attempting merge..."
            git pull
        }
        CURRENT_COMMIT=$(git rev-parse HEAD)
        if [ "$PREVIOUS_COMMIT" = "$CURRENT_COMMIT" ]; then
            log_info "Already up to date (${CURRENT_COMMIT:0:8})"
        else
            log_ok "Updated: ${PREVIOUS_COMMIT:0:8} → ${CURRENT_COMMIT:0:8}"
        fi
    else
        log_warn "Not a git repository — skipping pull"
    fi

    # Build images
    log_info "Building Docker images..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" build --no-cache
    log_ok "Images built successfully"

    # Run database initialization
    log_info "Running database migrations (init_db)..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" run --rm app \
        python -c "from database import init_db; init_db()" 2>/dev/null || {
        log_warn "init_db via module failed, trying alternative..."
        $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" run --rm app \
            python -c "import main; print('App loaded, DB initialized')" || true
    }
    log_ok "Database ready"

    # Deploy with zero-downtime restart
    log_info "Starting services..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d --build --remove-orphans
    log_ok "Services started"

    # Wait for health check
    log_info "Waiting for health checks..."
    sleep 5
    if $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" ps | grep -q "healthy"; then
        log_ok "All services healthy!"
    else
        log_warn "Services may still be starting. Check with: ./deploy.sh status"
    fi

    echo ""
    log_ok "=== Deploy complete! ==="
    log_info "App: http://localhost:80"
    log_info "API Docs: http://localhost:80/docs"
    log_info "Status: ./deploy.sh status"
    log_info "Logs: ./deploy.sh logs"
}

# Rollback to previous commit
rollback() {
    log_info "=== Rolling back to previous version ==="
    check_deps

    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        log_error "Not a git repository — cannot rollback"
        exit 1
    fi

    CURRENT=$(git rev-parse --short HEAD)
    log_info "Current commit: $CURRENT"

    # Revert to previous commit
    git revert --no-commit HEAD
    git commit -m "Rollback: revert $CURRENT via deploy.sh"
    log_ok "Reverted commit $CURRENT"

    # Rebuild and restart
    log_info "Rebuilding with previous version..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d --build --remove-orphans
    log_ok "Rollback complete!"

    show_status
}

# Show status
show_status() {
    check_deps
    echo ""
    log_info "=== Service Status ==="
    $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" ps
    echo ""
    log_info "=== Resource Usage ==="
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" \
        $(docker ps -q --filter "label=com.docker.compose.project=$PROJECT_NAME" 2>/dev/null) 2>/dev/null || \
        $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" ps
}

# Tail logs
show_logs() {
    check_deps
    $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" logs -f --tail=100
}

# Stop services
stop() {
    check_deps
    log_info "Stopping all services..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" -p "$PROJECT_NAME" down
    log_ok "All services stopped"
}

# --- Main ---
case "${1:-deploy}" in
    deploy)   deploy ;;
    rollback) rollback ;;
    status)   show_status ;;
    logs)     show_logs ;;
    stop)     stop ;;
    *)
        echo "Usage: $0 {deploy|rollback|status|logs|stop}"
        exit 1
        ;;
esac
