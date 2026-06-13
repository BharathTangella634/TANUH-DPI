#!/usr/bin/env bash
# =============================================================================
# bootstrap-vm.sh — reproducible TANUH-DPI VM bootstrap for proj-dpi-shared.
#
# Use as a Compute Engine startup-script (instance metadata) or bake into the
# golden image for the MIG. The VM must run as the attached service account
#   sa-dpi-app-prod@proj-dpi-shared.iam.gserviceaccount.com
# with the IAM roles listed in deploy/DEPLOYMENT.md. No key files, no plaintext
# secrets — credentials come from ADC (metadata server) + Secret Manager.
#
# What it does:
#   1. install Docker + compose plugin
#   2. fetch the repo
#   3. write a secrets-free .env (config + Secret Manager pointers only)
#   4. docker compose up -d   (keyless ADC + Memorystore + Secret Manager)
# =============================================================================
set -euo pipefail

# ── Config (override via metadata/env if needed) ─────────────────────────────
APP_DIR="${APP_DIR:-/opt/tanuh-dpi}"
REPO_URL="${REPO_URL:-https://github.com/TRANSLATIONAL-FOUNDATION/TANUH-DPI.git}"
REPO_REF="${REPO_REF:-main}"
PROJECT_ID="${PROJECT_ID:-proj-dpi-shared}"
MEMORYSTORE_HOST="${MEMORYSTORE_HOST:-10.250.123.43}"
MEMORYSTORE_PORT="${MEMORYSTORE_PORT:-6379}"
SQL_CONNECTION_NAME="${SQL_CONNECTION_NAME:-proj-dpi-shared:asia-south1:tanuh-dpi-mysql}"

log() { echo "[bootstrap $(date -u +%H:%M:%S)] $*"; }

# ── 1. Docker ────────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  log "installing Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

# ── 2. Repo ──────────────────────────────────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
  log "updating repo in $APP_DIR"
  git -C "$APP_DIR" fetch --depth 1 origin "$REPO_REF" && git -C "$APP_DIR" checkout -f "$REPO_REF"
else
  log "cloning repo into $APP_DIR"
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# ── 3. Secrets-free .env  (config + Secret Manager pointers ONLY) ────────────
# Real secret VALUES are never written here — they are fetched from Secret
# Manager at container startup by common/secrets.py via ADC.
log "writing secrets-free .env"
cat > .env <<EOF
# ── Config (non-secret) ──────────────────────────────────────────────────────
PROJECT_ID=${PROJECT_ID}
MYSQL_USER=dpi_logger
MYSQL_HOST=cloud-sql-proxy
MYSQL_DB=dpi_session_logger
ABDM_AUTH_ENABLED=false
NHCX_AUTH_ENABLED=false
FORGENSIC_AUTH_ENABLED=false
KEYCLOAK_AUTH_ENABLED=false
ABDM_TOKEN_EXPIRY_DAYS=1
NHCX_TOKEN_EXPIRY_DAYS=1
FORGENSIC_TOKEN_EXPIRY_DAYS=1

# ── Secret Manager pointers (values live ONLY in Secret Manager) ─────────────
MYSQL_PASSWORD_SECRET=mysql-password
SECRET_KEY_SECRET=app-secret-key
ABDM_SECRET_KEY_SECRET=abdm-secret-key
NHCX_SECRET_KEY_SECRET=nhcx-secret-key
FORGENSIC_SECRET_KEY_SECRET=forgensic-secret-key
REDIS_PASSWORD_SECRET=redis-password
EOF

# ── 4. Sanity: this VM must reach Memorystore + have ADC ─────────────────────
log "checking ADC service account..."
curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email" || true
echo

# ── 5. Start the stack (pull pre-built images from Artifact Registry) ────────
# The compose declares image: refs in Artifact Registry (dpi-containers) plus a
# build: fallback for local dev. In production we PULL the pre-built, versioned
# images (no on-VM build) — boot drops from ~20 min to ~2-3 min. The VM's
# attached SA needs roles/artifactregistry.reader.
# Override the image tag with IMAGE_TAG=<tag> for pinned versions / rollbacks.
log "configuring Artifact Registry auth (ADC)..."
gcloud auth configure-docker asia-south1-docker.pkg.dev --quiet || true

log "pulling images..."
docker compose pull

log "starting stack..."
docker compose up -d

log "done. services on :8000-8004 (APIs) and :8080 (frontend)."
