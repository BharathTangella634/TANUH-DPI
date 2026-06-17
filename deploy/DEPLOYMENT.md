# TANUH-DPI — Deployment Reference (`proj-dpi-shared`)

This document captures the **verified, self-contained** production architecture in
`proj-dpi-shared`. Everything runs keyless (ADC via the VM's attached service
account); **no service-account key files and no plaintext secrets live on disk.**

There is **no dependency on the old `bcd-prototypes` project** — storage, Redis,
SQL, and the LLM all live in `proj-dpi-shared`.

---

## 1. GCP Resources

| Resource | Identifier | Notes |
|---|---|---|
| Project | `proj-dpi-shared` | all infra here |
| VM | `tanuh-dpi` (asia-south1-c, n4-standard-8) | internal IP `10.55.32.3`, **no external IP** (SSH via IAP) |
| VM service account | `sa-dpi-app-prod@proj-dpi-shared.iam.gserviceaccount.com` | ADC identity for every container |
| Cloud SQL | `tanuh-dpi-mysql` (MySQL 8.0, asia-south1, db-g1-small) | public IP `35.234.211.91`, **no authorized networks** (reached only via cloud-sql-proxy) |
| → database | `dpi_session_logger` | schema auto-created by session-logger (`Base.metadata.create_all`) |
| → user | `dpi_logger` | password in Secret Manager (`mysql-password`) |
| Memorystore Redis | `dpi-redis` (Basic, REDIS_7_0) | `10.250.123.43:6379`, **AUTH enabled**, TLS disabled |
| GCS bucket (transient) | `gs://dpi-transient-processing` | ABDM/NHCX/Forgensic in+out; deleted after processing |
| GCS bucket (privacy) | `gs://dpi-privacy-temp` | Privacy Filter; 30-min retention (app-swept) |
| Vertex AI LLM | `publishers/google/models/gemma-4-26b-a4b-it-maas` | MaaS publisher model, `location=global`, project `proj-dpi-shared` |

### VM service account IAM (must hold all of these)
```
roles/storage.objectAdmin        on gs://dpi-transient-processing
roles/storage.objectAdmin        on gs://dpi-privacy-temp
roles/cloudsql.client            on proj-dpi-shared
roles/aiplatform.user            on proj-dpi-shared
roles/secretmanager.secretAccessor on proj-dpi-shared
roles/logging.logWriter, roles/monitoring.metricWriter
```
Required APIs enabled: `aiplatform.googleapis.com`, `secretmanager.googleapis.com`,
`sqladmin.googleapis.com`, `storage.googleapis.com`, `redis.googleapis.com`.

---

## 2. Secret Manager

Secret **values** live only in Secret Manager. `.env` holds only **pointers**
(`<NAME>_SECRET=<secret-name>`); `common/secrets.py` resolves them into process
memory at startup via the VM SA (ADC). No plaintext secrets on disk.

| Secret name | Resolves env var | Used by |
|---|---|---|
| `mysql-password` | `MYSQL_PASSWORD` | session-logger → Cloud SQL |
| `app-secret-key` | `SECRET_KEY` | privacy-filter |
| `abdm-secret-key` | `ABDM_SECRET_KEY` | pdf2abdm |
| `nhcx-secret-key` | `NHCX_SECRET_KEY` | pdf2nhcx |
| `forgensic-secret-key` | `FORGENSIC_SECRET_KEY` | forgensic |
| `redis-password` | `REDIS_PASSWORD` → injected into `REDIS_URL` | all services + workers |

Rotate a secret:
```bash
printf '%s' "<new-value>" | gcloud secrets versions add <secret-name> \
  --data-file=- --project=proj-dpi-shared
# then recreate the services:  docker compose up -d
```

---

## 3. Config (NOT secrets — live in `.env` / compose)

`PROJECT_ID=proj-dpi-shared`, `MYSQL_USER=dpi_logger`, `MYSQL_HOST=cloud-sql-proxy`,
`MYSQL_DB=dpi_session_logger`, `REDIS_URL=redis://10.250.123.43:6379/0`
(password injected at runtime), `GCS_BUCKET` defaults (`dpi-transient-processing`),
`PRIVACY_GCS_BUCKET=dpi-privacy-temp`, `*_AUTH_ENABLED`, `*_TOKEN_EXPIRY_DAYS`.

`.env` must contain the secret **pointers**:
```
MYSQL_PASSWORD_SECRET=mysql-password
SECRET_KEY_SECRET=app-secret-key
ABDM_SECRET_KEY_SECRET=abdm-secret-key
NHCX_SECRET_KEY_SECRET=nhcx-secret-key
FORGENSIC_SECRET_KEY_SECRET=forgensic-secret-key
REDIS_PASSWORD_SECRET=redis-password
```

---

## 4. Docker services & ports (host)

| Service | Port | Notes |
|---|---|---|
| frontend | 8080 | static UI |
| pdf2abdm (API) | 8000 | + 4 `celery-abdm-worker` |
| pdf2nhcx (API) | 8001 | + 4 `celery-nhcx-worker` |
| session-logger | 8002 | MySQL via cloud-sql-proxy |
| privacy-filter | 8003 | + 4 `celery-privacy-worker` |
| forgensic | 8004 | + 4 `celery-forgensic-worker` |
| cloud-sql-proxy | 3306 (internal) | keyless ADC → `tanuh-dpi-mysql` |
| redis (local) | 6379 | **unused** — kept by depends_on; all traffic goes to Memorystore |

Bring up: `docker compose up -d`  (the VM's `docker-compose.yml` is keyless and
points Redis at Memorystore — see bootstrap script).

---

## 5. Request flow (per service)

```
upload → API → GCS (keyless ADC) → Celery queue (Memorystore, AUTH)
       → worker (any VM) → process (Gemma for ABDM/NHCX; CV/redaction for others)
       → result in Redis → GCS cleanup → MySQL log (session-logger)
```
Outputs in GCS make the stack horizontally scalable: a worker on any MIG VM can
read inputs and serve outputs.

---

## 6. Reproducing a VM (MIG / golden image)

Use `deploy/bootstrap-vm.sh` as the instance startup-script (or bake it into the
golden image). It installs Docker, fetches the repo, writes a secrets-free `.env`,
and starts the stack. The VM only needs the **attached service account**
(`sa-dpi-app-prod`) with the IAM above — no keys, no plaintext secrets.
