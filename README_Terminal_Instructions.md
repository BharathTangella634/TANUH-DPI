# TANUH DPI — Terminal / cURL Instructions

Complete terminal reference for all four TANUH DPI services.
Tokens can be obtained in two ways:

- **Via the website** — Sign in at [dpi.tanuh.ai](https://dpi.tanuh.ai), go to any service's **API Access** tab, and click **Generate Token**. Copy the token and use it in the commands below.
- **Via cURL (direct)** — Each service exposes a `POST /api/token` endpoint that returns a demo JWT (no login required). Examples are shown below.

## Important Notes

- Each service has its **own token** — tokens are not interchangeable across services.
- Demo tokens (via `/api/token`) are valid for **1 day** (forgensic) or **7 days** (clinical, insurance).
- Website-generated tokens (via `/auth/token`) require Firebase authentication and are also valid for the configured expiry.
- All endpoints require `Authorization: Bearer <token>` except health checks and token generation.
- Rate limit: **150 requests per minute** per token across all services.

## Common Setup

```bash
NAME="YOUR_NAME"
EMAIL="you@example.com"
BASE="https://dpi.tanuh.ai"
```

---

## 1. Forgery Detection (forgensic)

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/forgensic/api/token` | Get a demo token (1-day) |
| POST | `/forgensic/jobs` | Submit a document for analysis |
| GET | `/forgensic/jobs/{job_id}` | Poll job status |
| GET | `/forgensic/jobs/{job_id}/results` | Fetch analysis results |
| GET | `/forgensic/jobs/{job_id}/files/{file}` | Download preview images |

```bash
FILE="/path/to/document.pdf"   # supports .pdf, .jpg, .png, .tiff
OCR="false"                    # set "true" for scanned documents

# Health check
curl -s "$BASE/forgensic/health" | python3 -m json.tool

# Get token
TOKEN=$(curl -s -X POST "$BASE/forgensic/api/token" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$NAME\",\"email\":\"$EMAIL\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
echo "Token obtained (${#TOKEN} chars)"

# Submit document
JOB_ID=$(curl -s -X POST "$BASE/forgensic/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$FILE" \
  -F "ocr_enabled=$OCR" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["job_id"])')
echo "JOB_ID=$JOB_ID"

# Poll until complete
for i in {1..30}; do
  STATUS_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/forgensic/jobs/$JOB_ID")
  STATUS=$(python3 -c 'import sys, json; print(json.load(sys.stdin).get("status",""))' <<<"$STATUS_JSON")
  PROGRESS=$(python3 -c 'import sys, json; print(json.load(sys.stdin).get("progress",""))' <<<"$STATUS_JSON")
  echo "[$i] status=$STATUS progress=$PROGRESS"
  [ "$STATUS" = "complete" ] || [ "$STATUS" = "error" ] && break
  sleep 2
done

# Fetch results
RESULTS=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/forgensic/jobs/$JOB_ID/results")
echo "$RESULTS" | python3 -m json.tool

# Download preview image (optional)
PREVIEW_URL=$(python3 -c '
import sys, json
d = json.load(sys.stdin)
pages = d.get("pages", [])
print(pages[0].get("preview_url", "") if pages else "")
' <<<"$RESULTS")
if [ -n "$PREVIEW_URL" ]; then
  curl -s -L -H "Authorization: Bearer $TOKEN" "$BASE$PREVIEW_URL" -o forgensic_preview.png
  echo "Saved forgensic_preview.png"
fi
```

---

## 2. Privacy Filter (Anonymization)

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/privacy-filter/api/demo-token` | Get a demo token |
| POST | `/privacy-filter/api/submit` | Submit document (async) |
| GET | `/privacy-filter/api/task-status/{id}` | Poll task status |
| GET | `/privacy-filter/api/task-result/{id}` | Fetch redaction results |
| POST | `/privacy-filter/api/redact` | Redact document (sync, legacy) |
| GET | `/privacy-filter/api/files/{kind}/{key}` | Download original/redacted files |

```bash
FILE="/path/to/document.pdf"   # supports PDF, DICOM, NIfTI, PNG, JPG, TIFF

# Health check
curl -s "$BASE/privacy-filter/api/health" | python3 -m json.tool

# Supported file types
curl -s "$BASE/privacy-filter/api/supported-types" | python3 -m json.tool

# Get token
TOKEN=$(curl -s -X POST "$BASE/privacy-filter/api/demo-token" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$NAME\",\"email\":\"$EMAIL\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
echo "Token obtained (${#TOKEN} chars)"

# Submit document (async — recommended for large files)
TASK_ID=$(curl -s -X POST "$BASE/privacy-filter/api/submit" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$FILE" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["task_id"])')
echo "TASK_ID=$TASK_ID"

# Poll until complete
for i in {1..30}; do
  STATUS_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/privacy-filter/api/task-status/$TASK_ID")
  STATUS=$(python3 -c 'import sys, json; print(json.load(sys.stdin).get("status",""))' <<<"$STATUS_JSON")
  echo "[$i] status=$STATUS"
  [ "$STATUS" = "completed" ] || [ "$STATUS" = "error" ] && break
  sleep 2
done

# Fetch results
RESP=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/privacy-filter/api/task-result/$TASK_ID")
echo "$RESP" | python3 -m json.tool

# Download redacted file (optional)
RED_URL=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("redacted_url",""))' <<<"$RESP")
FILENAME=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("filename","document"))' <<<"$RESP")
if [ -n "$RED_URL" ]; then
  curl -s -L -H "Authorization: Bearer $TOKEN" "$BASE$RED_URL" -o "redacted_$FILENAME"
  echo "Saved redacted_$FILENAME"
fi
```

---

## 3. Insurance Policy (pdf2nhcx)

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/pdf2nhcx/api/token` | Get a demo token (7-day) |
| POST | `/pdf2nhcx/submit` | Submit PDF for conversion |
| GET | `/pdf2nhcx/task-status/{task_id}` | Poll task status |
| GET | `/pdf2nhcx/task-result/{task_id}` | Fetch FHIR bundle result |

```bash
FILE="/path/to/insurance_policy.pdf"

# Health check
curl -s "$BASE/pdf2nhcx/health" | python3 -m json.tool

# Get token
TOKEN=$(curl -s -X POST "$BASE/pdf2nhcx/api/token" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$NAME\",\"email\":\"$EMAIL\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
echo "Token obtained (${#TOKEN} chars)"

# Submit PDF
TASK_ID=$(curl -s -X POST "$BASE/pdf2nhcx/submit" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$FILE" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["task_id"])')
echo "TASK_ID=$TASK_ID"

# Poll until complete (typically 3-5 minutes)
for i in {1..60}; do
  STATUS=$(curl -s "$BASE/pdf2nhcx/task-status/$TASK_ID" \
    | python3 -c 'import sys, json; print(json.load(sys.stdin).get("status",""))')
  echo "[$i] status=$STATUS"
  [ "$STATUS" = "completed" ] || [ "$STATUS" = "error" ] && break
  sleep 5
done

# Fetch FHIR bundle result
curl -s "$BASE/pdf2nhcx/task-result/$TASK_ID" | python3 -m json.tool
```

---

## 4. Clinical Document (pdf2abdm)

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/pdf2abdm/api/token` | Get a demo token (7-day) |
| POST | `/pdf2abdm/submit` | Submit PDF for conversion |
| GET | `/pdf2abdm/task-status/{task_id}` | Poll task status |
| GET | `/pdf2abdm/task-result/{task_id}` | Fetch FHIR bundle result |

```bash
FILE="/path/to/clinical_document.pdf"

# Health check
curl -s "$BASE/pdf2abdm/health" | python3 -m json.tool

# Get token
TOKEN=$(curl -s -X POST "$BASE/pdf2abdm/api/token" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$NAME\",\"email\":\"$EMAIL\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
echo "Token obtained (${#TOKEN} chars)"

# Submit PDF
TASK_ID=$(curl -s -X POST "$BASE/pdf2abdm/submit" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$FILE" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["task_id"])')
echo "TASK_ID=$TASK_ID"

# Poll until complete (typically 3-5 minutes)
for i in {1..60}; do
  STATUS=$(curl -s "$BASE/pdf2abdm/task-status/$TASK_ID" \
    | python3 -c 'import sys, json; print(json.load(sys.stdin).get("status",""))')
  echo "[$i] status=$STATUS"
  [ "$STATUS" = "completed" ] || [ "$STATUS" = "error" ] && break
  sleep 5
done

# Fetch FHIR bundle result
curl -s "$BASE/pdf2abdm/task-result/$TASK_ID" | python3 -m json.tool
```

---

## Error Responses

All services return standard HTTP error codes:

| Code | Meaning |
|------|---------|
| 401 | Token missing, expired, or invalid signature |
| 403 | Account not authorized (role check failed) |
| 413 | File too large (max 25 MB) |
| 429 | Rate limit exceeded (150 RPM per token) |
| 503 | Service unavailable or model warming up |

Cross-service token usage (e.g., using a Clinical token on Insurance) returns `401 Invalid token: Signature verification failed` — each service uses a separate signing key.
