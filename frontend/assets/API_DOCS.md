# API Documentation

> **Version 3.0** — OpenAPI 3.0 compliant. All services upgraded to bearer-token authentication.
> Last updated: May 2026

---

## Overview

The NHCX platform exposes **four independent API services**. Each service requires its own bearer token; tokens are **not interchangeable** across services.

| Service | Base URL | Port | Token Endpoint |
|---------|----------|------|----------------|
| ABDM FHIR Extraction | `/pdf2abdm` | 8000 | `POST /api/token` |
| NHCX Insurance Extraction | `/pdf2nhcx` | 8001 | `POST /api/token` |
| Privacy Filter | `/privacy-filter` | 8003 (→ 8080) | `POST /api/token` |
| Forgery Detection | `/forgensic` | 8004 | `POST /api/token` |

---

## Authentication

All services use **HS256 JWT bearer tokens**. The tokens are **independent** — each service issues and validates its own tokens using its own `SECRET_KEY`.

### Getting a Token

```bash
# ABDM token
curl -X POST https://nhcxhackathon.tanuh.ai/pdf2abdm/api/token \
  -H "Content-Type: application/json" \
  -d '{"name": "Your Name", "email": "you@example.com"}'

# NHCX token
curl -X POST https://nhcxhackathon.tanuh.ai/pdf2nhcx/api/token \
  -H "Content-Type: application/json" \
  -d '{"name": "Your Name", "email": "you@example.com"}'

# Privacy Filter token
curl -X POST https://nhcxhackathon.tanuh.ai/privacy-filter/api/token \
  -H "Content-Type: application/json" \
  -d '{"name": "Your Name", "email": "you@example.com"}'

# Forgery token
curl -X POST https://dpi-dev.tanuh.ai/forgensic/api/token \
  -H "Content-Type: application/json" \
  -d '{"name": "Your Name", "email": "you@example.com"}'
```

**Response**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in_days": 1,
  "name": "Your Name",
  "email": "you@example.com",
  "service": "pdf2abdm"
}
```

### Using the Token

```bash
# Pass token as Authorization header on all protected endpoints
curl -X POST .../pdf2abdm \
  -H "Authorization: Bearer <your-token>" \
  -F "file=@document.pdf"
```

### Token Expiry

- Demo tokens are valid for **24 hours**.
- Tokens are signed with HS256 using a service-specific `SECRET_KEY`.
- For production Keycloak integration, configure `KEYCLOAK_REALM_URL` and `KEYCLOAK_AUDIENCE`.

---

## 1. ABDM FHIR Extraction API (`/pdf2abdm`)

> Clinical document → ABDM-compliant FHIR DocumentBundle

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/pdf2abdm/health` | None | Service liveness check |
| `POST` | `/api/token` | None | Issue a 1-day demo JWT |
| `POST` | `/pdf2abdm` | ✅ Bearer | Sync: Upload PDF → FHIR bundle (returns immediately) |
| `POST` | `/pdf2abdm/submit` | ✅ Bearer | Async: Submit PDF → returns `task_id` (202) |
| `GET` | `/pdf2abdm/task-status/{task_id}` | None | Poll async task status |
| `GET` | `/pdf2abdm/task-result/{task_id}` | None | Retrieve completed result |

### `POST /pdf2abdm` — Sync Extraction

```bash
TOKEN=$(curl -s -X POST https://nhcxhackathon.tanuh.ai/pdf2abdm/api/token \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","email":"test@example.com"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST https://nhcxhackathon.tanuh.ai/pdf2abdm \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@clinical_record.pdf" \
  -F "model=gemma4" \
  -F "ocr_engine=auto"
```

**Form fields**:
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | File | required | PDF file (max 25 MB) |
| `model` | string | `gemma4` | LLM model identifier |
| `ocr_engine` | string | `auto` | OCR engine: `auto`, `docling`, `pymupdf` |
| `state` | string | optional | Patient's state (for geo analytics) |
| `city` | string | optional | Patient's city |

**Response**:
```json
{
  "bundles": [...],
  "bundle_names": ["DocumentBundle"],
  "document_type": "OPConsultRecord",
  "processing_time": "47.2s"
}
```

### `POST /pdf2abdm/submit` — Async Extraction

```bash
curl -X POST https://nhcxhackathon.tanuh.ai/pdf2abdm/submit \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@document.pdf" \
  -F "model=gemma4"
# Returns: {"task_id": "abc123..."}
```

Poll with `GET /pdf2abdm/task-status/{task_id}` → when `status == "completed"`, fetch with `GET /pdf2abdm/task-result/{task_id}`.

---

## 2. NHCX Insurance Extraction API (`/pdf2nhcx`)

> Insurance policy PDF → NHCX-compliant FHIR bundle

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/pdf2nhcx/health` | None | Service liveness check |
| `POST` | `/api/token` | None | Issue a 1-day demo JWT |
| `POST` | `/pdf2nhcx` | ✅ Bearer | Sync extraction |
| `POST` | `/pdf2nhcx/submit` | ✅ Bearer | Async submission (202) |
| `GET` | `/pdf2nhcx/task-status/{task_id}` | None | Poll async task |
| `GET` | `/pdf2nhcx/task-result/{task_id}` | None | Retrieve result |

### `POST /pdf2nhcx/submit` — Async (Recommended)

```bash
TOKEN=$(curl -s -X POST https://nhcxhackathon.tanuh.ai/pdf2nhcx/api/token \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","email":"test@example.com"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Submit
TASK=$(curl -s -X POST https://nhcxhackathon.tanuh.ai/pdf2nhcx/submit \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@policy.pdf" | python3 -c "import sys,json; print(json.load(sys.stdin)['task_id'])")

# Poll
curl https://nhcxhackathon.tanuh.ai/pdf2nhcx/task-status/$TASK
```

---

## 3. Privacy Filter API (`/privacy-filter`)

> Upload any document → detect & redact PII using `openai/privacy-filter`

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/privacy-filter/api/health` | None | Model + service liveness |
| `GET` | `/privacy-filter/api/supported-types` | None | Accepted file extensions |
| `POST` | `/privacy-filter/api/token` | None | Issue a 1-day demo JWT (also: `/api/demo-token`) |
| `POST` | `/privacy-filter/api/redact` | ✅ Bearer | Upload → redacted file + entity list |
| `GET` | `/privacy-filter/api/files/{kind}/{key}` | ✅ Bearer | Download `uploads` or `redacted` files |
| `GET` | `/privacy-filter/api/stats` | None | Live usage counters |
| `GET` | `/privacy-filter/api/postman-collection` | None | Download Postman collection |

### `POST /privacy-filter/api/redact`

```bash
TOKEN=$(curl -s -X POST https://nhcxhackathon.tanuh.ai/privacy-filter/api/token \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","email":"test@example.com"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST https://nhcxhackathon.tanuh.ai/privacy-filter/api/redact \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@document.pdf"
```

**Response**:
```json
{
  "job_id": "a1b2c3d4e5f6",
  "filename": "document.pdf",
  "entity_counts": {"private_person": 2, "private_email": 1},
  "entities": [{"entity_group": "private_person", "word": "...", "start": 42, "end": 53, "score": 0.99}],
  "original_url": "/api/files/uploads/...",
  "redacted_url": "/api/files/redacted/...",
  "text_preview_original": "...",
  "text_preview_redacted": "..."
}
```

**Supported file types**: `.txt`, `.md`, `.log`, `.csv`, `.pdf`, `.docx`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.dcm`, `.dicom`

### Detection Layers

Three detection layers run on every request:
1. **`openai/privacy-filter`** — personal PII (names, emails, phone numbers)
2. **`dslim/bert-base-NER`** — organisations, locations, people (optional; `ENABLE_NER_MODEL=true`)
3. **Deterministic regex** — tax IDs, IFSC, IBAN, SSN, EIN, Aadhaar, emails, URLs, labeled fields

---

---

## 4. Forgery Detection API (`/forgensic`)

> Document forgery detection with explainable bounding-box overlays.

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/forgensic/health` | None | Service liveness check |
| `GET` | `/forgensic/stats` | None | Usage counters for the dashboard |
| `POST` | `/forgensic/api/token` | None | Issue a 1-day demo JWT |
| `POST` | `/forgensic/jobs` | ✅ Bearer | Upload document and create processing job |
| `GET` | `/forgensic/jobs/{job_id}` | ✅ Bearer | Poll job status and progress |
| `GET` | `/forgensic/jobs/{job_id}/results` | ✅ Bearer | Fetch forgery analysis results |
| `GET` | `/forgensic/jobs/{job_id}/files/{file_name}` | ✅ Bearer | Fetch annotated preview or page image |

### `POST /forgensic/jobs` — Create Job

```bash
TOKEN=$(curl -s -X POST https://dpi-dev.tanuh.ai/forgensic/api/token \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","email":"test@example.com"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST https://dpi-dev.tanuh.ai/forgensic/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@document.pdf" \
  -F "ocr_enabled=true"
```

---

## Python SDK Example (All 4 Services)

```python
import requests

BASE = "https://nhcxhackathon.tanuh.ai"

# 1. Get tokens for each service independently
def get_token(service_prefix):
    r = requests.post(
        f"{BASE}/{service_prefix}/api/token",
        json={"name": "Your Name", "email": "you@example.com"},
    )
    return r.json()["access_token"]

abdm_token = get_token("pdf2abdm")
nhcx_token = get_token("pdf2nhcx")
pf_token   = get_token("privacy-filter")

# 2. Submit a clinical PDF (ABDM)
with open("clinical.pdf", "rb") as f:
    r = requests.post(
        f"{BASE}/pdf2abdm",
        headers={"Authorization": f"Bearer {abdm_token}"},
        files={"file": ("clinical.pdf", f, "application/pdf")},
        data={"model": "gemma4", "ocr_engine": "auto"},
        timeout=600,
    )
    abdm_result = r.json()

# 3. Redact a document (Privacy Filter)
with open("document.pdf", "rb") as f:
    r = requests.post(
        f"{BASE}/privacy-filter/api/redact",
        headers={"Authorization": f"Bearer {pf_token}"},
        files={"file": ("document.pdf", f, "application/pdf")},
        timeout=600,
    )
    pf_result = r.json()
    print("Redacted URL:", BASE + pf_result["redacted_url"])
```

---

## Error Responses

All services return RFC 7807-style error details:

| Status | Meaning |
|--------|---------|
| `401 Unauthorized` | Missing or invalid bearer token. Call `/api/token` to get a new one. |
| `422 Unprocessable Entity` | Missing or malformed request body / form fields. |
| `503 Service Unavailable` | Model is loading or upstream dependency unreachable — retry with backoff. |
| `504 Gateway Timeout` | Apache proxy timeout — large documents can take up to 15 min. |

---

## Limits and Behaviour

| Limit | Value |
|-------|-------|
| Max file size | **25 MB** |
| Proxy timeout | **900 s** (Apache) |
| Demo token expiry | **24 hours** |
| NHCX async max poll | **12 min** |
| Privacy Filter OCR DPI | 200 DPI (configurable via `PRIVACY_FILTER_OCR_DPI`) |

---

## OpenAPI / Swagger UI

Interactive docs available at:
- `GET /pdf2abdm/docs` — ABDM FHIR Extraction (version 3.0.0)
- `GET /pdf2nhcx/docs` — NHCX Insurance Extraction (version 3.0.0)
- `GET /privacy-filter/docs` — Privacy Filter (version 3.0.0)

All three UIs include the **Authorize** button (🔒) for testing bearer-protected endpoints directly.

---

## Env Vars Reference

| Env Var | Service | Description |
|---------|---------|-------------|
| `ABDM_SECRET_KEY` | pdf2abdm | HS256 signing secret (generate with `openssl rand -hex 32`) |
| `NHCX_SECRET_KEY` | pdf2nhcx | Same as above for NHCX service |
| `SECRET_KEY` | privacy-filter | HS256 signing secret for PF |
| `KEYCLOAK_AUTH_ENABLED` | privacy-filter | Enable Keycloak RS256 validation |
| `KEYCLOAK_REALM_URL` | all services | Keycloak realm URL for production |
| `KEYCLOAK_AUDIENCE` | all services | Expected audience in Keycloak JWT |

---

*© 2026 Tanuh AI. All rights reserved. This API is provided for evaluation purposes only.*
