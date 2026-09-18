#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# deploy-on-vm.sh — Runs on each MIG VM during CI/CD deployment.
# Called by .github/workflows/deploy.yml via SSH AFTER git pull is done.
# Expects the code to already be at the latest commit.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/opt/tanuh-dpi"
cd "$APP_DIR"

echo "▸ Rebuilding changed images..."
docker compose build

echo "▸ Restarting app services..."
docker compose up -d --remove-orphans

MONITORING_COMPOSE="${APP_DIR}/monitoring/monitoring/docker-compose.monitoring.yml"
if [ -f "$MONITORING_COMPOSE" ]; then
  echo "▸ Rebuilding monitoring stack..."
  docker compose -f "$MONITORING_COMPOSE" build 2>/dev/null || true
  docker compose -f "$MONITORING_COMPOSE" up -d --remove-orphans
  echo "  Monitoring stack restarted."
else
  echo "  Monitoring compose not found — skipping."
fi

echo "▸ Cleaning up dangling images..."
docker image prune -f > /dev/null 2>&1 || true

echo "✓ Deploy complete on $(hostname)"
