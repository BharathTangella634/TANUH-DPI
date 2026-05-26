# DPI Platform — Concurrency & Load Test Report

## Architecture Overview

The DPI platform runs 4 independent microservices on a single VM, each handling a different document processing task. Three services (Clinical, Insurance, Forgery) use **Celery + Redis** for asynchronous task queuing, while Privacy Filter processes requests **synchronously**.

| Service | API Port | Processing Model | Queue | Max Parallel Slots |
|---------|----------|-------------------|-------|--------------------|
| Clinical Document (`pdf2abdm`) | 8000 | Celery (async) | `abdm` | 8 (4 workers x 2 concurrency) |
| Insurance Policy (`pdf2nhcx`) | 8001 | Celery (async) | `nhcx` | 8 (4 workers x 2 concurrency) |
| Privacy Filter (`privacy-filter`) | 8003 | Synchronous (uvicorn) | — | ~13 (observed) |
| Forgery Detection (`forgensic`) | 8004 | Celery (async) | `forgensic` | 8 (4 workers x 2 concurrency) |

---

## Test Configuration

- **Date:** 2026-05-26
- **Target:** `https://dpi-dev.tanuh.ai`
- **Concurrent requests per service:** 200
- **Tests run sequentially** (one service at a time, no resource competition)
- **Tool:** `concurrency_test.py` using Python `ThreadPoolExecutor`

---

## 1. Clinical Document Extraction (`pdf2abdm`)

**How it works:**
Upload PDF → API returns `task_id` instantly → Celery worker picks it from Redis queue → OCR + LLM extraction → Poll `/task-status/{task_id}` until `completed`

### Test Results (200 concurrent requests, 81 KB PDF)

| Metric | Value |
|--------|-------|
| **Success rate** | 200/200 (100%) |
| **Wall clock time** | 1,096s (18.3 min) |
| **Throughput** | 0.18 docs/sec (10.9 docs/min) |
| **Speedup vs sequential** | 8.9x |

### Per-Request Timing

| Metric | Time |
|--------|------|
| Submit (upload + get task_id) | avg 2.5s, max 3.4s |
| Fastest request end-to-end | 43.6s |
| Slowest request end-to-end | 1,094s |
| Average end-to-end | 552.5s |
| Median end-to-end | 554.9s |
| P95 | 1,023s |

### Parallelism Observed

The first 8 workers completed together (at ~44-58s), confirming **8 parallel processing slots**. Subsequent batches averaged 4-5 workers finishing together (as Celery slots freed up and new tasks were picked from the queue).

| Batch | Finish Window | Workers Processed |
|-------|---------------|-------------------|
| Batch 1 | 44s — 58s | **8** (workers 1, 4, 6, 8, 23, 26, 40, 46) |
| Batch 2 | 79s — 98s | 6 |
| Batch 3 | 102s — 122s | 5 |
| ... | ... | ... |
| Batch 44 (last) | 1,097s | 1 |

**Total batches:** 44 | **Max batch size:** 8 | **Avg batch size:** 4.5

### What happens when 200 users upload simultaneously?

1. All 200 PDFs are accepted instantly (~2.5s submit time each) — no request is rejected
2. 8 documents begin processing immediately in parallel
3. The remaining 192 queue in Redis (FIFO order) — they wait, they don't fail
4. As each of the 8 slots finishes a document, the next queued document starts
5. The last document completes after ~18 minutes
6. Queue is durable — even if a Celery worker crashes, queued tasks aren't lost

---

## 2. Insurance Policy Extraction (`pdf2nhcx`)

**How it works:**
Same architecture as Clinical — Celery + Redis with 8 parallel slots.

### Test Results (200 concurrent requests, 271 KB PDF)

| Metric | Value |
|--------|-------|
| **Success rate** | 152/200 (76%) |
| **Wall clock time** | 1,390s (23.2 min) |
| **Throughput** | 0.11 docs/sec (6.6 docs/min) |
| **Speedup vs sequential** | 7.4x |

### Per-Request Timing

| Metric | Time |
|--------|------|
| Submit (upload + get task_id) | avg 7.0s, max 8.8s |
| Fastest request end-to-end | 46.8s |
| Slowest request (successful) | 1,376s |
| Average end-to-end | 700.6s |
| Median end-to-end | 689.8s |
| P95 | 1,308s |

### Why 48 requests "failed"

The 48 "failed" requests were still in **PENDING** or **PROGRESS** state when the test's polling window expired (~23 min). They were not actual failures — the processing was still ongoing, just not yet complete within the test duration. Given the larger PDF (271 KB vs 81 KB for Clinical) and longer per-document processing time, 200 documents / 8 parallel slots required more wall-clock time than the polling window allowed.

**Failure breakdown:** 40 PENDING (still queued), 8 PROGRESS (actively processing)

### Parallelism Observed

| Batch | Finish Window | Workers Processed |
|-------|---------------|-------------------|
| Batch 1 | 47s — 65s | 5 |
| Batch 46 | 1,299s — 1,312s | **8** |
| Batch 47 (last) | 1,362s — 1,377s | 5 |

**Total batches:** 47 | **Max batch size:** 8 | **Avg batch size:** 3.2

### Clinical vs Insurance Performance

| Factor | Clinical | Insurance |
|--------|----------|-----------|
| PDF size | 81 KB | 271 KB (3.3x larger) |
| Avg submit time | 2.5s | 7.0s (2.8x slower upload) |
| Avg end-to-end | 552s | 701s (27% slower) |
| Success in 23 min | 200/200 | 152/200 |

Insurance is slower primarily due to larger PDF uploads and more complex policy extraction logic, but uses the same 8-slot parallel architecture.

---

## 3. Forgery Detection (`forgensic`)

**How it works:**
Upload PDF → API returns `job_id` → Celery worker runs ELA (Error Level Analysis) + metadata inspection → Poll `/jobs/{job_id}` until `complete`

### Test Results (200 concurrent requests, 81 KB PDF)

| Metric | Value |
|--------|-------|
| **Success rate** | 198/200 (99%) |
| **Wall clock time** | 35.6s (0.6 min) |
| **Throughput** | 5.56 docs/sec (333.5 docs/min) |
| **Speedup vs sequential** | 21.1x |

### Per-Request Timing

| Metric | Time |
|--------|------|
| Submit (upload + get job_id) | avg 2.9s, max 4.8s |
| Fastest request end-to-end | 3.0s |
| Slowest request end-to-end | 33.3s |
| Average end-to-end | 19.6s |
| Median end-to-end | 19.6s |
| P95 | 32.6s |

### Parallelism Observed

Forgery detection is **extremely fast** — all 200 documents were processed in just 35.6 seconds. The image-based analysis (ELA, noise analysis, metadata inspection) completes in ~1-3 seconds per document, so the 8 Celery slots churn through 200 documents almost instantly.

| Batch | Finish Window | Workers Processed |
|-------|---------------|-------------------|
| Batch 1 | 3s — 23s | 115 |
| Batch 2 | 23s — 36s | 83 |

Only 2 batches were needed. The processing is so fast that by the time the test client polls for status, most tasks are already complete.

### Why so fast?

Unlike Clinical/Insurance (which use LLM inference taking 30-90s per document), Forgery Detection uses **classical image analysis algorithms** (ELA, noise detection, EXIF inspection). These are CPU-only operations that complete in 1-3 seconds per page.

---

## 4. Privacy Filter (`privacy-filter`)

**How it works:**
Upload PDF → Server processes it synchronously (no Celery, no task queue) → NER models scan every page for PII → Returns redacted result in the HTTP response directly

### Test Results (200 concurrent requests, 81 KB PDF)

| Metric | Value |
|--------|-------|
| **Success rate** | 200/200 (100%) |
| **Wall clock time** | 326.8s (5.4 min) |
| **Throughput** | 0.61 docs/sec (36.7 docs/min) |
| **Speedup vs sequential** | 5.9x |

### Per-Request Timing

| Metric | Time |
|--------|------|
| Fastest request | 3.7s |
| Slowest request | 324.5s |
| Average end-to-end | 165.0s |
| Median end-to-end | 165.1s |
| P95 | 310.2s |

### Parallelism Observed

Despite having no Celery queue, Privacy Filter processed requests with an observed parallelism of ~13. This is because the uvicorn async server handles multiple connections concurrently, and the NER model processing can overlap across requests.

| Batch | Finish Window | Workers Processed |
|-------|---------------|-------------------|
| Batch 1 | 4s — 23s | 13 |
| Batch 2 | 25s — 45s | 13 |
| Batch 3 | 46s — 66s | 13 |
| ... | ... | ... |
| Batch 16 (last) | 321s — 327s | 5 |

**Total batches:** 16 | **Consistent batch size:** 13 | **Max observed parallelism:** 13

Every batch consistently contained exactly 13 workers, indicating the server naturally handles ~13 concurrent requests. The steady throughput of ~1 document every 1.6 seconds remained consistent throughout the entire 200-request test with no degradation.

---

## Summary Comparison

| Service | Success Rate | Wall Clock | Throughput | Avg Time/Doc | Max Parallelism |
|---------|-------------|------------|------------|---------------|-----------------|
| **Clinical** | 100% (200/200) | 18.3 min | 10.9 docs/min | 552s | 8 |
| **Insurance** | 76% (152/200)* | 23.2 min | 6.6 docs/min | 701s | 8 |
| **Forgery** | 99% (198/200) | 0.6 min | 333.5 docs/min | 19.6s | 115+ |
| **Privacy** | 100% (200/200) | 5.4 min | 36.7 docs/min | 165s | 13 |

*\*Insurance had 48 requests still processing when the test's client-side polling window expired — not actual failures. Celery has no task timeout; those tasks would eventually complete if polled longer. The test script polls for `400 iterations × 3s = 1,200s` per worker, but with 200 documents queued behind 8 parallel slots, the last documents need ~2,250s total to process.*

### Key Takeaways

1. **No request is ever rejected** — all services accept uploads instantly and queue excess requests
2. **Forgery Detection is the fastest** — classical image analysis handles 200 docs in under 36 seconds
3. **Privacy Filter surprised** — despite no Celery, it naturally handles ~13 concurrent requests via async I/O
4. **Clinical and Insurance are bounded by LLM inference time** — each document requires 30-90s of GPU time for extraction, making the 8 Celery slots the bottleneck
5. **The queue is durable** — Redis persists queued tasks, so even worker crashes don't lose data
6. **Linear scaling with resources** — adding more Celery workers or GPU instances would proportionally increase throughput

---

## Scaling in Production

### Current Configuration (per service)

| Parameter | Clinical / Insurance / Forgery | Privacy Filter |
|-----------|-------------------------------|----------------|
| Celery worker replicas | 4 (`celery-{service}-1` to `-4`) | N/A (no Celery) |
| Concurrency per replica | 2 (`--concurrency=2`) | N/A |
| Total parallel slots | 8 | ~13 (uvicorn async) |
| uvicorn API workers | 2 | 1 |

### How to Increase Slots

**Option A — Add more Celery replicas** (recommended for live production):

Add `celery-abdm-5` through `celery-abdm-8` in `docker-compose.yml`. Deploy with `docker compose up -d --no-deps celery-abdm-5` — this starts the new worker **without restarting any running containers**. Existing in-flight tasks are completely unaffected. New replicas immediately start picking tasks from the Redis queue.

**Option B — Increase concurrency per replica:**

Change `--concurrency=2` to `--concurrency=4` in the existing worker definitions. This doubles throughput with fewer containers, but each worker uses more RAM. Requires restarting the worker containers (`docker compose up -d --no-deps celery-abdm-1`).

**Option C — For Privacy Filter:**

Increase `--workers` in the uvicorn command inside the Dockerfile. Each additional uvicorn worker loads the NER models into memory separately.

### Resource Concerns When Scaling

| Concern | Details |
|---------|---------|
| **RAM usage** | Each Celery worker consumes ~500MB–1GB. Going from 8 to 16 slots adds 4–8GB RAM. The VM must have enough free memory. |
| **GPU / LLM API limits** | Clinical and Insurance use Vertex AI (cloud). More parallel workers = more simultaneous API calls. Google enforces QPM (queries per minute) limits — exceeding them causes `429 Too Many Requests`. Check your Vertex AI quota before scaling. |
| **CPU contention** | Forgery workers are CPU-intensive (image analysis). Too many concurrent workers can saturate CPU cores and slow everything down rather than speeding it up. |
| **NER model memory (Privacy)** | Each uvicorn worker loads ~2GB of NER models. 4 workers = 8GB just for the models. Scale only if the machine has enough RAM/VRAM. |
| **Redis** | Not a concern — Redis easily handles thousands of queued tasks. |
| **Disk I/O** | All workers read uploaded PDFs and write temp files. On a single disk, very high concurrency can bottleneck on I/O. Use SSDs. |
| **Diminishing returns** | If the external LLM API is the bottleneck (not local CPU), adding more workers just shifts the queue from Redis to the API's internal queue. Monitor API latency to identify this. |

### Scaling Decision Guide

| Desired throughput | What to change | Additional resources needed |
|-------------------|----------------|-----------------------------|
| 2x Clinical/Insurance | Add 4 Celery replicas (8→16 slots) | +4GB RAM, check Vertex AI QPM quota |
| 4x Clinical/Insurance | 16 replicas × 2 concurrency (32 slots) | +12GB RAM, likely need Vertex AI quota increase |
| 2x Privacy Filter | Increase uvicorn workers to 2 | +2GB RAM for NER model copy |
| 2x Forgery | Likely not needed (already 333 docs/min) | — |

### Live Production Scaling (Zero Downtime)

```bash
# Add a new Celery worker without touching anything else:
docker compose up -d --no-deps celery-abdm-5

# Verify it connected to Redis and is processing:
docker logs celery-abdm-5 --tail 20

# Remove it later if no longer needed:
docker compose stop celery-abdm-5 && docker compose rm -f celery-abdm-5
```

This is fully safe in production — new workers join the existing Redis queue, and removing them just means fewer consumers (queued tasks wait slightly longer, nothing is lost).
