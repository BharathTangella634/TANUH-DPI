#!/bin/bash
set -e

# Ensure git submodules (e.g. privacy-filter-app) are present
echo "Initialising git submodules..."
git submodule update --init --recursive

# Build and start the docker containers in detached mode
echo "Starting docker-compose build and up..."
docker compose build && docker compose up -d

echo "Docker containers started successfully!"

# ── Start monitoring stack ────────────────────────────────────────────────────
# The monitoring stack (Prometheus, Grafana, Loki, Promtail, Node Exporter,
# Queue Exporter, Alertmanager) lives in a separate compose file.
# It must be started explicitly — it is NOT part of the main docker-compose.yml.
# All monitoring services use restart: unless-stopped, so after this initial
# start they will auto-restart on Docker daemon restart (VM reboot).
echo ""
echo "Starting monitoring stack..."
MONITORING_COMPOSE="$(dirname "$0")/monitoring/monitoring/docker-compose.monitoring.yml"

if [ -f "$MONITORING_COMPOSE" ]; then
    docker compose -f "$MONITORING_COMPOSE" up -d
    echo "Monitoring stack started successfully!"
else
    echo "Warning: monitoring compose not found at $MONITORING_COMPOSE — skipping."
fi

# ── Configure host Apache2 reverse proxy ─────────────────────────────────────
PROXY_SCRIPT="$(dirname "$0")/scripts/setup_apache_proxy.sh"

if [ -f "$PROXY_SCRIPT" ]; then
    echo ""
    echo "Configuring Apache2 reverse proxy..."
    bash "$PROXY_SCRIPT"
else
    echo "Warning: proxy script not found at $PROXY_SCRIPT — skipping Apache2 configuration."
fi
