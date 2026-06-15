# DPI Platform — Complete Architecture

---

## 1. High-Level System Architecture

```mermaid
graph TB
    subgraph CLIENTS["CLIENTS"]
        BROWSER["Browser (User)"]
        API_CLIENT["API Client (curl/Python/Postman)"]
    end

    subgraph FRONTEND_LAYER["FRONTEND — Apache httpd :8080"]
        FRONTEND["Single Page Application<br/>(HTML/CSS/JS)"]
        PROXY["Apache Reverse Proxy<br/>(mod_proxy)"]
    end

    subgraph API_SERVICES["FASTAPI SERVICES"]
        PDF2ABDM["pdf2abdm :8000<br/>Clinical Document Extraction"]
        PDF2NHCX["pdf2nhcx :8001<br/>Insurance Document Extraction"]
        SESSION_LOGGER["session-logger :8002<br/>Audit & Logging"]
        PRIVACY_FILTER["privacy-filter :8003<br/>PII/PHI Redaction"]
        FORGENSIC["forgensic :8004<br/>Forgery Detection"]
    end

    subgraph CELERY_WORKERS["CELERY WORKERS (4 replicas × concurrency 2 = 8 slots each)"]
        ABDM_WORKER["celery-abdm-worker<br/>Queue: abdm"]
        NHCX_WORKER["celery-nhcx-worker<br/>Queue: nhcx"]
        PRIVACY_WORKER["celery-privacy-worker<br/>Queue: privacy_filter"]
        FORGENSIC_WORKER["celery-forgensic-worker<br/>Queue: forgensic"]
    end

    subgraph MESSAGING["MESSAGE BROKER & CACHE"]
        REDIS["Redis :6379<br/>(Celery Broker + Result Backend<br/>+ Task Status + Result Cache)"]
    end

    subgraph DATABASE["DATABASE"]
        CLOUD_SQL_PROXY["Cloud SQL Proxy :3306"]
        CLOUD_SQL["GCP Cloud SQL (MySQL)<br/>bcd-prototypes:asia-south1:<br/>tanuh-bcd-questionnaire-dev<br/>DB: dpi_session_logger"]
    end

    subgraph CLOUD_SERVICES["GOOGLE CLOUD SERVICES"]
        VERTEX_AI["Vertex AI MaaS<br/>Gemma 4 (26B)<br/>Project: bcd-prototypes"]
        GCS["Google Cloud Storage<br/>Bucket: tanuh-bcd-bucket"]
    end

    subgraph MONITORING_STACK["MONITORING & OBSERVABILITY"]
        PROMETHEUS["Prometheus :9090"]
        GRAFANA["Grafana :3000"]
        LOKI["Loki :3100"]
        PROMTAIL["Promtail"]
        ALERTMANAGER["AlertManager :9093"]
        NODE_EXPORTER["Node Exporter :9100"]
        QUEUE_EXPORTER["Queue Exporter :9101"]
    end

    subgraph LOCAL_STORAGE["LOCAL VOLUMES (Docker Mounts)"]
        PDF_UPLOADS["./pdf_uploads/"]
        FHIR_RESULTS["./fhir_results/"]
        NHCX_RESULTS["./nhcx_results/"]
        PF_DATA["./privacy_filter_data/"]
        FORG_DATA["./forgensic_data/"]
        SL_DATA["./session_logger_data/"]
    end

    %% Client connections
    BROWSER -->|"HTTP :8080"| FRONTEND
    API_CLIENT -->|"HTTP :8000-8004<br/>Bearer JWT"| API_SERVICES

    %% Frontend proxy
    FRONTEND --> PROXY
    PROXY -->|"/pdf2abdm/*"| PDF2ABDM
    PROXY -->|"/pdf2nhcx/*"| PDF2NHCX
    PROXY -->|"/api/*"| PRIVACY_FILTER
    PROXY -->|"/forgensic/*"| FORGENSIC
    PROXY -->|"/logs/*"| SESSION_LOGGER

    %% API → Redis (task queuing)
    PDF2ABDM -->|"Queue task"| REDIS
    PDF2NHCX -->|"Queue task"| REDIS
    PRIVACY_FILTER -->|"Queue task"| REDIS
    FORGENSIC -->|"Queue task"| REDIS

    %% Workers ← Redis (consume tasks)
    REDIS -->|"Consume"| ABDM_WORKER
    REDIS -->|"Consume"| NHCX_WORKER
    REDIS -->|"Consume"| PRIVACY_WORKER
    REDIS -->|"Consume"| FORGENSIC_WORKER

    %% Workers → Redis (store results)
    ABDM_WORKER -->|"Store result<br/>TTL 24h"| REDIS
    NHCX_WORKER -->|"Store result<br/>TTL 24h"| REDIS
    PRIVACY_WORKER -->|"Store result<br/>TTL 24h"| REDIS
    FORGENSIC_WORKER -->|"Store result<br/>TTL 1h"| REDIS

    %% Workers → Cloud
    ABDM_WORKER -->|"LLM Inference<br/>(FHIR extraction)"| VERTEX_AI
    NHCX_WORKER -->|"LLM Inference<br/>(FHIR extraction)"| VERTEX_AI
    PDF2ABDM -->|"LLM Inference<br/>(sync mode)"| VERTEX_AI
    PDF2NHCX -->|"LLM Inference<br/>(sync mode)"| VERTEX_AI

    %% GCS uploads
    PDF2ABDM -->|"Upload PDF+JSON"| GCS
    PDF2NHCX -->|"Upload PDF+JSON"| GCS
    PRIVACY_FILTER -.->|"Upload/Download<br/>(if GCS backend)"| GCS

    %% Session logging
    PDF2ABDM -->|"POST /log"| SESSION_LOGGER
    PDF2NHCX -->|"POST /log"| SESSION_LOGGER
    PRIVACY_FILTER -->|"POST /log"| SESSION_LOGGER
    FORGENSIC -->|"POST /log"| SESSION_LOGGER
    ABDM_WORKER -->|"POST /log"| SESSION_LOGGER
    NHCX_WORKER -->|"POST /log"| SESSION_LOGGER
    PRIVACY_WORKER -->|"POST /log"| SESSION_LOGGER
    FORGENSIC_WORKER -->|"POST /log"| SESSION_LOGGER

    %% Database
    SESSION_LOGGER -->|"SQL"| CLOUD_SQL_PROXY
    CLOUD_SQL_PROXY -->|"TCP :3306"| CLOUD_SQL

    %% Local storage
    PDF2ABDM --- PDF_UPLOADS
    PDF2ABDM --- FHIR_RESULTS
    PDF2NHCX --- PDF_UPLOADS
    PDF2NHCX --- NHCX_RESULTS
    PRIVACY_FILTER --- PF_DATA
    FORGENSIC --- FORG_DATA
    SESSION_LOGGER --- SL_DATA
    ABDM_WORKER --- PDF_UPLOADS
    ABDM_WORKER --- FHIR_RESULTS
    NHCX_WORKER --- PDF_UPLOADS
    NHCX_WORKER --- NHCX_RESULTS
    PRIVACY_WORKER --- PF_DATA
    FORGENSIC_WORKER --- FORG_DATA

    %% Monitoring
    PROMETHEUS -->|"Scrape /metrics"| API_SERVICES
    PROMETHEUS -->|"Scrape :9200"| CELERY_WORKERS
    PROMETHEUS -->|"Scrape"| NODE_EXPORTER
    PROMETHEUS -->|"Scrape"| QUEUE_EXPORTER
    QUEUE_EXPORTER -->|"Read queue depth"| REDIS
    GRAFANA -->|"Query"| PROMETHEUS
    GRAFANA -->|"Query"| LOKI
    PROMTAIL -->|"Ship logs"| LOKI
    PROMETHEUS -->|"Alerts"| ALERTMANAGER

    style CLIENTS fill:#e1f5fe
    style FRONTEND_LAYER fill:#fff3e0
    style API_SERVICES fill:#e8f5e9
    style CELERY_WORKERS fill:#fce4ec
    style MESSAGING fill:#f3e5f5
    style DATABASE fill:#fff9c4
    style CLOUD_SERVICES fill:#e3f2fd
    style MONITORING_STACK fill:#f1f8e9
    style LOCAL_STORAGE fill:#efebe9
```

---

## 2. Complete Request Flow — Input to Output (All Services)

### 2.1 Authentication Flow (Common to All Services)

```mermaid
sequenceDiagram
    participant C as Client
    participant FE as Frontend :8080
    participant SVC as Any Service<br/>(:8000-8004)
    participant SL as Session Logger :8002
    participant DB as Cloud SQL

    C->>FE: Visit website tab
    FE->>SL: POST /logs/visit {page, state, city}
    SL->>DB: INSERT INTO page_visits

    C->>SVC: POST /api/token {name, email}
    SVC->>SVC: Generate HS256 JWT<br/>(1-day expiry)
    SVC-->>C: {access_token, token_type: "bearer"}
    SVC--)SL: POST /logs/auth-token<br/>{name, email, token_hash,<br/>ip_address, user_agent}<br/>(fire-and-forget)
    SL->>DB: INSERT INTO auth_tokens

    Note over C,SVC: All subsequent requests include:<br/>Authorization: Bearer <token>
```

### 2.2 PDF2ABDM — Clinical Document Extraction (Async Flow)

```mermaid
sequenceDiagram
    participant C as Client/Browser
    participant FE as Frontend :8080
    participant API as pdf2abdm :8000
    participant R as Redis :6379
    participant W as celery-abdm-worker
    participant OCR as OCR Engine<br/>(PyPDF→Docling→LightOn)
    participant CLS as Classifier<br/>(Keyword + LLM)
    participant LLM as Vertex AI<br/>Gemma 4 (26B)
    participant GCS as GCS Bucket<br/>tanuh-bcd-bucket
    participant SL as Session Logger :8002
    participant DB as Cloud SQL

    C->>FE: Upload PDF (drag & drop)
    FE->>API: POST /pdf2abdm/submit<br/>multipart: file, model=gemma4

    API->>API: validate_pdf_upload()<br/>≤25MB, ≤100 pages
    API->>API: Save to shared volume<br/>/app/pdf_uploads/tmp/{uuid}_{name}
    API->>R: Queue Celery task<br/>process_abdm_task<br/>queue="abdm"
    API-->>C: 202 Accepted<br/>{task_id, poll_url, result_url}

    loop Poll every 2-3 seconds
        C->>API: GET /pdf2abdm/task-status/{task_id}
        API->>R: Check AsyncResult state
        API-->>C: {status: "PROGRESS",<br/>step: "OCR", progress: 15}
    end

    Note over W: Worker picks up task from "abdm" queue

    W->>W: Step 1: OCR (15%)
    W->>OCR: extract_pdf_to_markdown()
    OCR->>OCR: PyPDF → if <50 chars/page<br/>→ Docling → LightOn
    OCR-->>W: Markdown text + page markers

    W->>W: Multi-patient grouping<br/>(if lab report: group by Age/Sex + Collection Date)

    W->>W: Step 2: Classification (20%)
    W->>CLS: classify_document_text()
    CLS->>CLS: Keyword heuristic (<1ms)
    alt Keyword inconclusive
        CLS->>LLM: LLM classification<br/>temp=0.1, max_tokens=10
        LLM-->>CLS: "CLINICAL" | "INSURANCE" | "INVALID"
    end
    CLS-->>W: "CLINICAL"

    alt Document is INSURANCE or INVALID
        W->>R: Store rejection:<br/>{status: "rejected", error: "Wrong service"}
        W-->>C: Poll returns rejected status
    end

    W->>W: Step 3: Classify doc type
    W->>LLM: classify_document()<br/>→ DischargeSummaryRecord<br/>  or DiagnosticReportRecord
    LLM-->>W: doc_type + must_resources<br/>+ selected_resources

    W->>W: Step 4: FHIR Extraction (20-90%)
    Note over W,LLM: LangGraph Dynamic Workflow

    W->>W: Topological sort resources<br/>by dependencies

    loop For each FHIR resource (Patient, Practitioner, Condition, etc.)
        W->>LLM: run_extraction_agent()<br/>prompt + rulebook JSON<br/>temp=0.3
        LLM-->>W: Resource JSON
        W->>W: extract_json() + sanitize<br/>+ ensure_id() + set profile
    end

    W->>W: assembly_node()<br/>Composition first → resources → DocumentReference last
    W->>W: Inject PDF base64 into DocumentReference
    W->>W: clean_and_reorder_bundle()

    W->>W: Step 5: Store result (95%)
    W->>R: SETEX result:{task_id}<br/>TTL=86400 (24h)
    W->>R: Update state: "complete"

    W--)GCS: Upload PDF → pdf_uploads/abdm/{name}<br/>Upload JSON → json_output/abdm/{name}<br/>(fire-and-forget, non-fatal)

    W--)SL: POST /log<br/>{service: "pdf2abdm",<br/>filename, doc_type,<br/>processing_time, status}
    SL->>DB: INSERT INTO session_logs

    W->>W: Delete temp file

    C->>API: GET /pdf2abdm/task-result/{task_id}
    API->>R: GET result:{task_id}
    API-->>C: 200 {status: "completed",<br/>bundles: [{resourceType: "Bundle",<br/>type: "document", entry: [...]}],<br/>model_used: "gemma4"}
```

### 2.3 PDF2NHCX — Insurance Document Extraction (Async Flow)

```mermaid
sequenceDiagram
    participant C as Client/Browser
    participant API as pdf2nhcx :8001
    participant R as Redis :6379
    participant W as celery-nhcx-worker
    participant OCR as OCR Engine
    participant CLS as Classifier
    participant LLM as Vertex AI<br/>Gemma 4 (26B)
    participant GCS as GCS Bucket
    participant SL as Session Logger :8002

    C->>API: POST /pdf2nhcx/submit<br/>file, model=gemma4
    API->>API: validate_pdf_upload()
    API->>API: Save to /app/pdf_uploads/tmp/
    API->>R: Queue: process_nhcx_task<br/>queue="nhcx"
    API-->>C: 202 {task_id, poll_url}

    W->>OCR: Step 1: OCR (10%)
    OCR-->>W: Raw Markdown text

    W->>CLS: Step 2: Classification Gate (20%)
    CLS-->>W: "INSURANCE"
    Note over W: Rejects CLINICAL & INVALID docs

    W->>LLM: Step 3: Distill Insurance Text (35%)
    Note over W,LLM: Split into 4 chunks (2000-char overlap)<br/>→ 4 parallel LLM calls via ThreadPoolExecutor<br/>→ Condense each chunk to fact sheet

    W->>LLM: Step 4: Select NHCX Resources (50%)
    LLM-->>W: Bundle type + resource list
    Note over W: Bundle types:<br/>InsurancePlanBundle | ClaimBundle |<br/>ClaimResponseBundle | CoverageEligibility*<br/>| TaskBundle

    W->>W: Step 5: LLM Extraction (65%)
    Note over W,LLM: LangGraph Workflow:<br/>Topological resource extraction<br/>with dependency ordering

    loop For each NHCX resource
        W->>LLM: Extraction with rulebook<br/>(StructureDefinition JSON)
        LLM-->>W: Resource JSON
        W->>W: Sanitize + deduplicate +<br/>enforce NRCES profile URLs
    end

    W->>W: assemble_nhcx_collection_bundle()
    W->>W: Strip forbidden resources<br/>+ flatten nested bundles

    W->>R: Step 6: Store (95%)<br/>SETEX result:{task_id} TTL=24h

    W--)GCS: Upload PDF + JSON (fire-and-forget)
    W--)SL: POST /log {service: "pdf2nhcx"}

    C->>API: GET /pdf2nhcx/task-result/{task_id}
    API->>R: GET result:{task_id}
    API-->>C: 200 {bundle: {resourceType: "Bundle",<br/>type: "collection", entry: [...]}}
```

### 2.4 Privacy Filter — PII/PHI Redaction (Async Flow)

```mermaid
sequenceDiagram
    participant C as Client/Browser
    participant API as privacy-filter :8003
    participant R as Redis :6379
    participant W as celery-privacy-worker
    participant ENG as MedDeID Engine
    participant DET as Detectors<br/>(Metadata+TextRegion<br/>+OCR+PHI)
    participant RED as Redactors<br/>(Mask/Crop/Inpaint)
    participant VAL as Validator
    participant STORE as Storage<br/>(Local or GCS)
    participant SL as Session Logger :8002

    C->>API: POST /api/submit<br/>file (DICOM/NIfTI/PDF/Image)
    API->>API: Validate format<br/>(DICOM, NIfTI, PNG, JPG,<br/>TIFF, BMP, PDF, DOCX, TXT)
    API->>STORE: Save upload<br/>uploads/{job_id}__{filename}
    API->>R: Queue: process_redaction_task<br/>queue="privacy_filter"
    API-->>C: 202 {task_id}

    W->>STORE: Load file to temp path

    alt PDF File
        W->>ENG: PDFRedactor path
        ENG->>ENG: Extract native text (PyMuPDF)
        ENG->>ENG: Safe Harbor Detector<br/>(18 HIPAA categories)
        ENG->>ENG: Map char spans → word rects
        ENG->>ENG: Detect QR codes (AR 0.8-1.25)<br/>+ Barcodes (AR >2.5)
        ENG->>ENG: Global repeat pass<br/>(known PHI across all pages)
        ENG->>ENG: Scrub PDF metadata<br/>(author, title, creator, dates)
    else Image / DICOM / NIfTI
        W->>ENG: Medical Image path

        ENG->>DET: 1. MetadataDetector
        DET->>DET: Scan DICOM tags / EXIF / NIfTI headers
        DET-->>ENG: PHI entities from metadata

        ENG->>ENG: 2. MetadataCleaner
        Note over ENG: DICOM: strip 15+ PHI tags,<br/>regenerate UIDs, remove private tags<br/>NIfTI: clear descrip, aux_file, db_name<br/>Image: strip EXIF, IPTC, XMP, PNG text

        ENG->>DET: 3. OverlayDetector
        DET->>DET: Modality-specific edge band heuristics
        DET-->>ENG: Overlay regions

        ENG->>DET: 4. TextRegionDetector
        DET->>DET: Connected-component analysis<br/>on corner crops (top 5-15%)
        DET->>DET: Character blob grouping<br/>(4-60px height, 2-120px width)
        DET-->>ENG: All detected text regions

        ENG->>DET: 5. OCRDetector (Tesseract/PaddleOCR)
        DET-->>ENG: Word-level bboxes + text

        ENG->>DET: 6. PHIDetector
        DET->>DET: Regex + keyword classification<br/>(NAME, DATE, IDENTIFIER,<br/>AADHAAR, PAN, SSN, EMAIL)
        DET-->>ENG: Labeled PHI entities

        ENG->>RED: 7. Redact detected regions
        Note over RED: Mask: black rectangle (default)<br/>Crop: remove PHI-heavy borders<br/>Inpaint: OpenCV appearance-preserving
        RED-->>ENG: Redacted image/volume

        ENG->>VAL: 8. Post-Redaction Validation
        VAL->>VAL: Re-scan via OCR + PHI classify
        VAL->>VAL: Risk score = min(residual×5, 100)
        VAL-->>ENG: {passed, risk_score, residual_phi}
    end

    ENG-->>W: {entities, counts, validation}
    W->>STORE: Save redacted output<br/>redacted/{job_id}__redacted.{ext}

    W->>R: SETEX result:{task_id}<br/>TTL=86400 (24h)

    W--)SL: POST /log<br/>{service: "privacy_filter"}

    C->>API: GET /api/task-result/{task_id}
    API->>R: GET result:{task_id}
    API-->>C: 200 {entities: [...],<br/>entity_counts: {...},<br/>original_url, redacted_url}

    C->>API: GET /api/files/redacted/{key}
    API->>STORE: Fetch redacted file
    API-->>C: FileResponse (redacted file)

    opt Manual Editing
        C->>API: GET /api/render-pages/original/{key}
        API-->>C: Page preview images
        C->>API: POST /api/apply-redactions<br/>{key, boxes: [{x,y,w,h},...]}
        API-->>C: Edited output URL
    end
```

### 2.5 Forgensic — Document Forgery Detection (Async Flow)

```mermaid
sequenceDiagram
    participant C as Client/Browser
    participant API as forgensic :8004
    participant R as Redis :6379
    participant W as celery-forgensic-worker
    participant CV as CV Pipeline<br/>(10 Detectors)
    participant OCR_F as Tesseract OCR
    participant SL as Session Logger :8002

    C->>API: POST /forgensic/jobs<br/>file (PDF/Image)
    API->>API: Validate format + size (≤25MB)
    API->>API: Save to DATA_DIR/{job_id}/input/
    API->>R: SET forgensic:job:{job_id}<br/>{status: "queued"} TTL=3600
    API->>R: Queue: process_forgensic_job<br/>queue="forgensic"
    API-->>C: {job_id, status: "queued"}

    loop Poll
        C->>API: GET /forgensic/jobs/{job_id}
        API->>R: GET forgensic:job:{job_id}
        API-->>C: {status, progress, message}
    end

    W->>W: PDF → render pages to JPEG<br/>(PyMuPDF)

    loop For each page
        W->>W: Assess page quality<br/>(blur, edge density, contrast, text density)

        W->>CV: C1: Copy-Move Detection
        CV->>CV: ORB keypoints (5000 features)<br/>→ BFMatcher ratio test 0.75<br/>→ Spatial clustering (bin=14px)

        W->>CV: C2: Overwriting Detection
        CV->>CV: Canny edges (40-140)<br/>→ Texture maps (residual, variance, gradient)<br/>→ Z-score anomalies

        W->>CV: C3: Added Content
        CV->>CV: Connected components<br/>→ Shape classify (stamps, signatures, text)

        W->>CV: C4: Erased Content
        CV->>CV: OCR token gaps + smooth region detection

        W->>CV: C5: Merged Content
        CV->>CV: Row/col density discontinuities<br/>+ header/body profile diff

        W->>CV: C6: Watermark Removal
        CV->>CV: Hough diagonal lines +<br/>FFT periodicity detection

        W->>CV: C7: Irregular Spacing
        CV->>CV: Token gap z-scores<br/>(median, MAD thresholding)

        W->>CV: C8: AI-Generated (Full Page)
        CV->>CV: FFT spectrum: flatness,<br/>peak_ratio, highfreq_ratio

        W->>CV: C9: AI-Generated (Partial)
        CV->>CV: Region-level FFT +<br/>edge/gradient z-score

        W->>W: Postprocess regions<br/>(clip, filter <200px², npv_focus filter)
        W->>W: Render annotated preview
    end

    W->>W: Generate findings summary (85%)
    W->>OCR_F: OCR text from flagged regions
    OCR_F-->>W: Snippet text per region
    W->>W: Merge overlapping regions<br/>Sort by text/area, limit 5/page

    W->>W: Export outputs:
    Note over W: • submission.json<br/>• submission_preview.xlsx<br/>• YAML annotations per page<br/>• Annotated preview images

    W->>R: SET forgensic:job:{job_id}<br/>{status: "complete", result: {...},<br/>file_map: {...}} TTL=3600
    W->>R: INCR forgensic:total_analyzed

    W--)SL: POST /log {service: "forgensic"}

    C->>API: GET /forgensic/jobs/{job_id}/results
    API->>R: GET forgensic:job:{job_id}
    API-->>C: 200 JobResultResponse<br/>{pages: [{categories, regions}],<br/>category_summary: {C1:2, C3:1},<br/>findings_summary, export_urls}

    C->>API: GET /forgensic/jobs/{job_id}/files/{name}
    API-->>C: FileResponse (preview/JSON/Excel/YAML)
```

---

## 3. Service Port Map & API Endpoints

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PORT MAP                                         │
├──────────┬──────────────────────────────────────────────────────────────┤
│ :8080    │ Frontend (Apache httpd + Reverse Proxy + SPA)               │
│ :8000    │ pdf2abdm (Clinical Document → ABDM FHIR Bundle)            │
│ :8001    │ pdf2nhcx (Insurance Document → NHCX FHIR Bundle)           │
│ :8002    │ session-logger (Audit Logging + Stats)                      │
│ :8003    │ privacy-filter (PII/PHI Detection & Redaction)             │
│ :8004    │ forgensic (Document Forgery Detection)                      │
│ :6379    │ Redis (Celery Broker + Result Backend)                      │
│ :3306    │ Cloud SQL Proxy → GCP MySQL                                 │
│ :9090    │ Prometheus (Metrics)                                        │
│ :3000    │ Grafana (Dashboards)                                        │
│ :3100    │ Loki (Log Aggregation)                                      │
│ :9093    │ AlertManager (Alert Routing)                                 │
│ :9100    │ Node Exporter (Host Metrics)                                │
│ :9101    │ Queue Exporter (Redis Queue Depth)                          │
│ :9200    │ Celery Worker Metrics (Prometheus multiproc)                │
└──────────┴──────────────────────────────────────────────────────────────┘
```

### All API Endpoints

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ pdf2abdm :8000                                                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│ POST /pdf2abdm/api/token ............ Issue JWT (name + email)                  │
│ POST /pdf2abdm ...................... Sync: upload PDF → FHIR Bundle            │
│ POST /pdf2abdmurl ................... Sync: local file path → FHIR Bundle      │
│ POST /pdf2abdm/submit ............... Async: upload PDF → task_id (202)        │
│ POST /pdf2abdm/submit-url ........... Async: local path → task_id (202)       │
│ GET  /pdf2abdm/task-status/{id} ..... Poll task progress                       │
│ GET  /pdf2abdm/task-result/{id} ..... Fetch completed FHIR Bundle              │
│ POST /validate ...................... Validate FHIR JSON (HL7 validator)        │
│ GET  /health ........................ Liveness probe                             │
│ GET  /model-health .................. LLM model availability                    │
│ GET  /ocr-health .................... OCR engine availability                   │
│ GET  /metrics ....................... Prometheus metrics                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│ pdf2nhcx :8001                                                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│ POST /pdf2nhcx/api/token ............ Issue JWT (name + email)                  │
│ POST /pdf2nhcx ...................... Sync: upload PDF → NHCX Bundle            │
│ POST /pdf2nhcxurl ................... Sync: local path → NHCX Bundle           │
│ POST /pdf2nhcx/submit ............... Async: upload PDF → task_id (202)        │
│ POST /pdf2nhcx/submit-url ........... Async: local path → task_id (202)       │
│ GET  /pdf2nhcx/task-status/{id} ..... Poll task progress                       │
│ GET  /pdf2nhcx/task-result/{id} ..... Fetch completed NHCX Bundle              │
│ POST /validate ...................... Validate FHIR JSON (HL7 validator)        │
│ GET  /health ........................ Liveness probe                             │
│ GET  /model-health .................. LLM model availability                    │
│ GET  /ocr-health .................... OCR engine availability                   │
│ GET  /metrics ....................... Prometheus metrics                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│ session-logger :8002                                                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│ POST /log ........................... Log a processing session                   │
│ POST /logs/auth-token ............... Record JWT issuance event                 │
│ GET  /logs .......................... List session logs (paginated)              │
│ GET  /logs/stats .................... Aggregated platform stats                 │
│ GET  /logs/pf-stats ................. Privacy filter stats                      │
│ GET  /logs/forgensic-stats .......... Forgery detection stats                  │
│ GET  /logs/auth-tokens .............. List issued tokens                        │
│ GET  /logs/auth-tokens/stats ........ Token issuance statistics                │
│ POST /logs/visit .................... Record page visit                         │
│ GET  /logs/visit/stats .............. Visit analytics                          │
│ POST /logs/feedback ................. Submit user feedback                      │
│ GET  /logs/feedback ................. List feedback entries                     │
│ GET  /health ........................ Liveness probe                             │
│ GET  /metrics ....................... Prometheus metrics                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│ privacy-filter :8003                                                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│ POST /api/demo-token ................ Issue JWT (name + email)                  │
│ POST /api/redact .................... Sync: upload file → entities + URLs       │
│ POST /api/submit .................... Async: upload file → task_id (202)       │
│ GET  /api/task-status/{id} .......... Poll task progress                       │
│ GET  /api/task-result/{id} .......... Fetch completed redaction result          │
│ GET  /api/files/{kind}/{key} ........ Download original/redacted file          │
│ GET  /api/render-pages/{kind}/{key} . Render doc to page preview images        │
│ GET  /api/page-image/{key}/{page} ... Serve individual page PNG                │
│ POST /api/apply-redactions .......... Apply manual redaction boxes              │
│ GET  /api/supported-types ........... List supported file formats               │
│ GET  /api/health .................... Liveness probe + engine status            │
│ GET  /api/stats ..................... Usage counters                             │
│ GET  /metrics ....................... Prometheus metrics                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│ forgensic :8004                                                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│ POST /forgensic/api/token ........... Issue JWT (name + email)                  │
│ POST /forgensic/jobs ................ Upload doc → job_id                       │
│ GET  /forgensic/jobs/{id} ........... Poll job status + progress               │
│ GET  /forgensic/jobs/{id}/results ... Fetch analysis findings                  │
│ GET  /forgensic/jobs/{id}/files/{f} . Download output file                    │
│ GET  /health ........................ Liveness probe                             │
│ GET  /stats ......................... Active jobs + docs analyzed               │
│ GET  /metrics ....................... Prometheus metrics                         │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Data Flow Diagram — Storage & Cloud Interactions

```mermaid
flowchart LR
    subgraph INPUT["INPUT"]
        PDF_IN["PDF Upload<br/>(≤25MB, ≤100 pages)"]
        IMG_IN["Image Upload<br/>(DICOM/NIfTI/PNG/<br/>JPG/TIFF/BMP)"]
    end

    subgraph SHARED_VOL["SHARED DOCKER VOLUMES"]
        PU["./pdf_uploads/tmp/<br/>{uuid}_{filename}"]
        FD["./forgensic_data/<br/>{job_id}/input/"]
        PFD["./privacy_filter_data/<br/>uploads/{job_id}__{file}"]
    end

    subgraph PROCESSING["PROCESSING PIPELINES"]
        subgraph ABDM_PIPE["ABDM Pipeline"]
            OCR_A["OCR Waterfall<br/>(PyPDF→Docling→LightOn)"]
            CLASS_A["Classifier<br/>(Keyword→LLM)"]
            GROUP["Multi-Patient<br/>Grouping"]
            LANG_A["LangGraph Workflow<br/>(Resource Extraction)"]
            ASSEM_A["Bundle Assembly<br/>(Document Bundle)"]
        end
        subgraph NHCX_PIPE["NHCX Pipeline"]
            OCR_N["OCR"]
            CLASS_N["Classifier"]
            DISTILL["Text Distillation<br/>(4 parallel LLM chunks)"]
            SELECT["Resource Selection<br/>(6 bundle types)"]
            LANG_N["LangGraph Workflow"]
            ASSEM_N["Collection Bundle<br/>Assembly"]
        end
        subgraph PF_PIPE["Privacy Filter Pipeline"]
            LOAD["Loader Registry<br/>(DICOM/NIfTI/PDF/Image)"]
            META_CLEAN["Metadata Cleaner<br/>(DICOM tags/EXIF/<br/>NIfTI headers)"]
            DETECT["Detection Stack<br/>(TextRegion+OCR+PHI<br/>+Metadata+Overlay)"]
            REDACT["Redactor<br/>(Mask/Crop/Inpaint)"]
            VALIDATE["Post-Redaction<br/>Validator"]
        end
        subgraph FORG_PIPE["Forgensic Pipeline"]
            RENDER["PDF → Page Images<br/>(PyMuPDF)"]
            QUALITY["Page Quality<br/>Assessment"]
            CV_DET["10 CV Detectors<br/>(C1-C10)"]
            ANNOTATE["Annotated Preview<br/>Generation"]
            FINDINGS["Findings Summary<br/>(OCR + merge + limit)"]
        end
    end

    subgraph CLOUD["GOOGLE CLOUD"]
        VERTEX["Vertex AI MaaS<br/>Gemma 4 26B<br/>(Project: bcd-prototypes)"]
        GCS_B["GCS: tanuh-bcd-bucket"]
        subgraph GCS_LAYOUT["GCS Bucket Layout"]
            GCS_PDF_A["pdf_uploads/abdm/{name}.pdf"]
            GCS_PDF_N["pdf_uploads/nhcx/{name}.pdf"]
            GCS_JSON_A["json_output/abdm/{name}.json"]
            GCS_JSON_N["json_output/nhcx/{name}.json"]
            GCS_PF["privacy-app/{kind}/{key}"]
        end
        CLOUD_SQL_DB["Cloud SQL MySQL<br/>DB: dpi_session_logger<br/>Tables: session_logs,<br/>auth_tokens, feedbacks,<br/>page_visits"]
    end

    subgraph REDIS_STORE["REDIS :6379"]
        TASK_Q["Task Queues<br/>(abdm, nhcx,<br/>privacy_filter, forgensic)"]
        RESULT_K["Result Cache<br/>result:{task_id}<br/>TTL: 24h"]
        FORG_K["forgensic:job:{job_id}<br/>TTL: 1h"]
        COUNTER["forgensic:total_analyzed"]
    end

    subgraph OUTPUT_VOL["OUTPUT VOLUMES"]
        FHIR_OUT["./fhir_results/<br/>ABDM FHIR Bundles"]
        NHCX_OUT["./nhcx_results/<br/>NHCX FHIR Bundles"]
        PF_OUT["./privacy_filter_data/<br/>redacted/{job}__redacted.{ext}"]
        FORG_OUT["./forgensic_data/{job_id}/output/<br/>preview/ annotations/<br/>submission.json<br/>submission_preview.xlsx"]
    end

    subgraph RESPONSE["RESPONSE TO CLIENT"]
        FHIR_JSON["FHIR Bundle JSON<br/>(Document or Collection)"]
        ENTITIES["Entity List +<br/>Redacted File URL"]
        FORGERY["Findings + Categories<br/>+ Annotated Previews<br/>+ Export Files"]
    end

    %% Input flows
    PDF_IN --> PU
    PDF_IN --> FD
    IMG_IN --> PFD
    PDF_IN --> PFD

    %% Processing
    PU --> OCR_A --> CLASS_A --> GROUP --> LANG_A --> ASSEM_A
    PU --> OCR_N --> CLASS_N --> DISTILL --> SELECT --> LANG_N --> ASSEM_N
    PFD --> LOAD --> META_CLEAN --> DETECT --> REDACT --> VALIDATE
    FD --> RENDER --> QUALITY --> CV_DET --> ANNOTATE --> FINDINGS

    %% LLM calls
    LANG_A -.->|"LLM calls<br/>(per resource)"| VERTEX
    LANG_N -.->|"LLM calls<br/>(distill + extract)"| VERTEX
    CLASS_A -.->|"LLM fallback"| VERTEX
    CLASS_N -.->|"LLM fallback"| VERTEX
    DISTILL -.->|"4 parallel calls"| VERTEX

    %% Cloud storage
    ASSEM_A -.->|"fire-and-forget"| GCS_PDF_A
    ASSEM_A -.->|"fire-and-forget"| GCS_JSON_A
    ASSEM_N -.->|"fire-and-forget"| GCS_PDF_N
    ASSEM_N -.->|"fire-and-forget"| GCS_JSON_N
    VALIDATE -.->|"if GCS backend"| GCS_PF

    %% Redis
    ASSEM_A --> RESULT_K
    ASSEM_N --> RESULT_K
    VALIDATE --> RESULT_K
    FINDINGS --> FORG_K

    %% Output volumes
    ASSEM_A --> FHIR_OUT
    ASSEM_N --> NHCX_OUT
    REDACT --> PF_OUT
    ANNOTATE --> FORG_OUT

    %% Response
    RESULT_K --> FHIR_JSON
    RESULT_K --> ENTITIES
    FORG_K --> FORGERY
```

---

## 5. Infrastructure & Deployment Topology

```mermaid
graph TB
    subgraph GCP_VM["GCP VM (Compute Engine)"]
        subgraph DOCKER_COMPOSE["Docker Compose Stack"]
            subgraph TIER_1["Tier 1: Entry"]
                FE["frontend :8080<br/>(Apache httpd)"]
            end

            subgraph TIER_2["Tier 2: API Services"]
                A1["pdf2abdm :8000"]
                A2["pdf2nhcx :8001"]
                A3["session-logger :8002"]
                A4["privacy-filter :8003"]
                A5["forgensic :8004"]
            end

            subgraph TIER_3["Tier 3: Workers (16 containers)"]
                W1["abdm-worker ×4<br/>(concurrency 2 = 8 slots)"]
                W2["nhcx-worker ×4<br/>(concurrency 2 = 8 slots)"]
                W3["privacy-worker ×4<br/>(concurrency 2 = 8 slots)"]
                W4["forgensic-worker ×4<br/>(concurrency 2 = 8 slots)"]
            end

            subgraph TIER_4["Tier 4: Data"]
                RED["Redis :6379"]
                PROXY["Cloud SQL Proxy :3306"]
            end
        end

        subgraph MONITORING_COMPOSE["Monitoring Stack (Separate Compose)"]
            PROM["Prometheus :9090"]
            GRAF["Grafana :3000"]
            LOK["Loki :3100"]
            PTAIL["Promtail"]
            AM["AlertManager :9093"]
            NE["Node Exporter :9100"]
            QE["Queue Exporter :9101"]
        end

        DISK["Persistent Disk Volumes<br/>pdf_uploads/ fhir_results/<br/>nhcx_results/ privacy_filter_data/<br/>forgensic_data/ session_logger_data/"]
    end

    subgraph GCP_SERVICES["GCP Managed Services"]
        SQL["Cloud SQL (MySQL)<br/>asia-south1<br/>tanuh-bcd-questionnaire-dev"]
        VAI["Vertex AI MaaS<br/>Gemma 4 26B<br/>us-central1"]
        GCSB["Cloud Storage<br/>tanuh-bcd-bucket"]
    end

    subgraph AUTH_OPTIONAL["Optional: Keycloak"]
        KC["Keycloak Server<br/>(RS256 JWKS)"]
    end

    %% Internal connections
    FE --> TIER_2
    TIER_2 --> RED
    RED --> TIER_3
    TIER_3 --> RED
    A3 --> PROXY
    PROXY --> SQL
    TIER_2 --> A3
    TIER_3 --> A3

    %% External connections
    TIER_3 -->|"LLM API"| VAI
    TIER_2 -->|"LLM API"| VAI
    TIER_2 -.->|"Upload"| GCSB
    TIER_3 -.->|"Upload"| GCSB
    TIER_2 -.->|"JWKS validate"| KC

    %% Monitoring
    PROM -->|"Scrape"| TIER_2
    PROM -->|"Scrape :9200"| TIER_3
    PROM --> NE
    PROM --> QE
    QE --> RED
    GRAF --> PROM
    GRAF --> LOK
    PTAIL --> LOK
    PROM --> AM

    %% Disk
    TIER_2 --- DISK
    TIER_3 --- DISK

    style GCP_VM fill:#e8f5e9
    style GCP_SERVICES fill:#e3f2fd
    style MONITORING_COMPOSE fill:#f1f8e9
```

---

## 6. Celery Task Queue Architecture

```mermaid
graph LR
    subgraph API_LAYER["API Services (Task Producers)"]
        P1["pdf2abdm :8000"]
        P2["pdf2nhcx :8001"]
        P3["privacy-filter :8003"]
        P4["forgensic :8004"]
    end

    subgraph REDIS_BROKER["Redis :6379 (Broker)"]
        Q1["Queue: abdm"]
        Q2["Queue: nhcx"]
        Q3["Queue: privacy_filter"]
        Q4["Queue: forgensic"]
    end

    subgraph WORKERS["Celery Workers (Consumers)"]
        subgraph ABDM_W["abdm-workers (4 replicas)"]
            AW1["worker-1 (concurrency=2)"]
            AW2["worker-2 (concurrency=2)"]
            AW3["worker-3 (concurrency=2)"]
            AW4["worker-4 (concurrency=2)"]
        end
        subgraph NHCX_W["nhcx-workers (4 replicas)"]
            NW1["worker-1"]
            NW2["worker-2"]
            NW3["worker-3"]
            NW4["worker-4"]
        end
        subgraph PF_W["privacy-workers (4 replicas)"]
            PW1["worker-1"]
            PW2["worker-2"]
            PW3["worker-3"]
            PW4["worker-4"]
        end
        subgraph FG_W["forgensic-workers (4 replicas)"]
            FW1["worker-1"]
            FW2["worker-2"]
            FW3["worker-3"]
            FW4["worker-4"]
        end
    end

    subgraph REDIS_RESULTS["Redis :6379 (Result Backend)"]
        R1["result:{task_id}<br/>TTL: 24h"]
        R2["forgensic:job:{job_id}<br/>TTL: 1h"]
    end

    P1 -->|"process_abdm_task"| Q1
    P2 -->|"process_nhcx_task"| Q2
    P3 -->|"process_redaction_task"| Q3
    P4 -->|"process_forgensic_job"| Q4

    Q1 --> ABDM_W
    Q2 --> NHCX_W
    Q3 --> PF_W
    Q4 --> FG_W

    ABDM_W -->|"SETEX"| R1
    NHCX_W -->|"SETEX"| R1
    PF_W -->|"SETEX"| R1
    FG_W -->|"SET"| R2

    style API_LAYER fill:#e8f5e9
    style REDIS_BROKER fill:#f3e5f5
    style WORKERS fill:#fce4ec
    style REDIS_RESULTS fill:#fff9c4
```

### Task Configuration Summary

| Service | Task Name | Queue | Soft Limit | Hard Limit | Retries | Result TTL |
|---------|-----------|-------|-----------|-----------|---------|------------|
| pdf2abdm | `pdf2abdm.tasks.process_abdm_task` | `abdm` | 29 min | 30 min | 0 | 24h (Redis) |
| pdf2nhcx | `pdf2nhcx.tasks.process_nhcx_task` | `nhcx` | 29 min | 30 min | 0 | 24h (Redis) |
| privacy_filter | `privacy_filter.tasks.process_redaction_task` | `privacy_filter` | 9 min | 10 min | 0 | 24h (Redis) |
| forgensic | `forgensic.tasks.process_forgensic_job` | `forgensic` | 55 min | 60 min | 0 | 1h (Redis) |

---

## 7. OCR Engine Waterfall (Shared by ABDM & NHCX)

```mermaid
flowchart TD
    PDF["Input PDF"] --> PYPDF["PyPDF<br/>(fast, native text)"]
    PYPDF --> CHECK{"Avg chars/page<br/>≥ 50?"}
    CHECK -->|"Yes"| DONE["Return Markdown"]
    CHECK -->|"No (scanned PDF)"| DOCLING["Docling<br/>(LaTeX-based layout)"]
    DOCLING --> CHECK2{"Extraction<br/>succeeded?"}
    CHECK2 -->|"Yes"| DONE
    CHECK2 -->|"No"| LIGHTON["LightOn<br/>(fast OCR)"]
    LIGHTON --> DONE

    DONE --> NORMALIZE["Normaliser:<br/>YAML front-matter +<br/>PAGE N markers"]
    NORMALIZE --> MARKDOWN["AI-ready Markdown<br/>with page structure"]

    style PYPDF fill:#c8e6c9
    style DOCLING fill:#bbdefb
    style LIGHTON fill:#ffe0b2
```

---

## 8. Authentication Architecture (Common Pattern)

```mermaid
flowchart TD
    REQ["Incoming Request"] --> HDR{"Authorization<br/>header present?"}
    HDR -->|"No"| ENABLED{"Auth enabled?<br/>(env: *_AUTH_ENABLED)"}
    ENABLED -->|"false"| BYPASS["Return anonymous claims<br/>{sub: 'anonymous', type: 'bypass'}"]
    ENABLED -->|"true"| REJECT_401["HTTP 401 Unauthorized"]
    HDR -->|"Yes"| EXTRACT["Extract Bearer token"]

    EXTRACT --> ALG{"JWT alg header?"}
    ALG -->|"HS256"| DEMO["Validate Demo Token<br/>Secret: *_SECRET_KEY<br/>Check exp claim"]
    ALG -->|"RS256"| KC_CHECK{"KEYCLOAK_REALM_URL<br/>configured?"}
    KC_CHECK -->|"No"| DEMO
    KC_CHECK -->|"Yes"| KC["Validate Keycloak Token<br/>Fetch JWKS (cached 1h)<br/>Verify RS256 signature<br/>Check exp + audience"]

    DEMO -->|"Valid"| CLAIMS["Return claims dict"]
    DEMO -->|"Invalid/Expired"| REJECT_401
    KC -->|"Valid"| CLAIMS
    KC -->|"Invalid"| REJECT_401
    KC -->|"Keycloak unreachable"| REJECT_503["HTTP 503<br/>Service Unavailable"]

    subgraph TOKEN_ISSUANCE["Token Issuance (POST /api/token)"]
        INPUT["name + email"] --> SIGN["Sign HS256 JWT<br/>{sub, name, email,<br/>type: 'demo',<br/>service: '...',<br/>exp: now + N days}"]
        SIGN --> RETURN["Return access_token"]
        SIGN --> LOG_SL["Fire-and-forget →<br/>session-logger<br/>POST /logs/auth-token"]
    end

    style BYPASS fill:#fff9c4
    style REJECT_401 fill:#ffcdd2
    style REJECT_503 fill:#ffcdd2
    style CLAIMS fill:#c8e6c9
```

### Per-Service Auth Configuration

| Service | Secret Key Env Var | Auth Toggle Env Var | Token Expiry Env Var | Default Expiry |
|---------|-------------------|--------------------|--------------------|----------------|
| pdf2abdm | `ABDM_SECRET_KEY` | `ABDM_AUTH_ENABLED` | `ABDM_TOKEN_EXPIRY_DAYS` | 1 day |
| pdf2nhcx | `NHCX_SECRET_KEY` | `NHCX_AUTH_ENABLED` | `NHCX_TOKEN_EXPIRY_DAYS` | 1 day |
| privacy-filter | `SECRET_KEY` | `KEYCLOAK_AUTH_ENABLED` | `DEMO_TOKEN_EXPIRY_DAYS` | 1 day |
| forgensic | `FORGENSIC_SECRET_KEY` | `FORGENSIC_AUTH_ENABLED` | `FORGENSIC_TOKEN_EXPIRY_DAYS` | 1 day |

---

## 9. Session Logger — Audit Trail Architecture

```mermaid
flowchart TD
    subgraph PRODUCERS["Event Producers (fire-and-forget)"]
        A["pdf2abdm"]
        B["pdf2nhcx"]
        C["privacy-filter"]
        D["forgensic"]
        E["Frontend (JS)"]
    end

    subgraph SL["Session Logger :8002"]
        EP1["POST /log<br/>(processing session)"]
        EP2["POST /logs/auth-token<br/>(JWT issuance)"]
        EP3["POST /logs/visit<br/>(page visit)"]
        EP4["POST /logs/feedback<br/>(user feedback)"]
    end

    subgraph DB["Cloud SQL (MySQL) / SQLite Fallback"]
        T1["session_logs<br/>─────────────────<br/>session_id, service,<br/>filename, document_type,<br/>model_used, ocr_engine_used,<br/>processing_time, gcs_uri,<br/>bundle_count, status,<br/>error_message, client_ip,<br/>created_at"]
        T2["auth_tokens<br/>─────────────────<br/>name, email, service,<br/>token_hash (SHA-256),<br/>access_granted_at,<br/>access_expires_at,<br/>expiry_days, ip_address,<br/>user_agent, revoked"]
        T3["page_visits<br/>─────────────────<br/>page, state, city,<br/>visited_at"]
        T4["feedbacks<br/>─────────────────<br/>service, name, place,<br/>feedback, ip_address"]
    end

    subgraph STATS["Stats Endpoints (read by Frontend)"]
        S1["GET /logs/stats<br/>→ total sessions, clinical/<br/>insurance docs, unique IPs,<br/>states, districts"]
        S2["GET /logs/pf-stats<br/>→ docs_redacted"]
        S3["GET /logs/forgensic-stats<br/>→ docs_analyzed"]
        S4["GET /logs/visit/stats<br/>→ visit counts over time"]
        S5["GET /logs/auth-tokens/stats<br/>→ token issuance counts"]
    end

    A -->|"POST /log"| EP1
    B -->|"POST /log"| EP1
    C -->|"POST /log"| EP1
    D -->|"POST /log"| EP1
    A -->|"POST /logs/auth-token"| EP2
    B -->|"POST /logs/auth-token"| EP2
    C -->|"POST /logs/auth-token"| EP2
    D -->|"POST /logs/auth-token"| EP2
    E -->|"POST /logs/visit"| EP3
    E -->|"POST /logs/feedback"| EP4

    EP1 --> T1
    EP2 --> T2
    EP3 --> T3
    EP4 --> T4

    T1 --> S1
    T1 --> S2
    T1 --> S3
    T3 --> S4
    T2 --> S5

    E -->|"Fetch stats"| STATS
```

---

## 10. Monitoring & Observability Stack

```mermaid
flowchart TD
    subgraph TARGETS["Scrape Targets"]
        API_M["/metrics on :8000-8004<br/>(FastAPI middleware)"]
        WORKER_M[":9200 on each worker<br/>(Prometheus multiproc)"]
        NODE["Node Exporter :9100<br/>(CPU, memory, disk, net)"]
        QUEUE["Queue Exporter :9101<br/>(Redis queue depth)"]
    end

    subgraph METRICS["Prometheus Metrics Collected"]
        M1["dpi_http_requests_total<br/>{service, method, status_code}"]
        M2["dpi_http_request_duration_seconds<br/>{service, method}"]
        M3["dpi_tasks_started/completed/failed_total<br/>{service}"]
        M4["dpi_task_duration_seconds<br/>{service}"]
        M5["dpi_documents_processed/failed_total<br/>{service}"]
        M6["dpi_exceptions_total<br/>{service, exception_type, severity}"]
        M7["dpi_queue_depth<br/>{queue}"]
    end

    subgraph PROM["Prometheus :9090"]
        SCRAPE["Scrape every 15s"]
        RULES["Alert Rules:<br/>• application.rules.yml<br/>• infrastructure.rules.yml<br/>• queue.rules.yml<br/>• errors.rules.yml<br/>• health_score.yml"]
        STORE_P["Retention: 15d / 4GB"]
    end

    subgraph ALERT["AlertManager :9093"]
        ROUTE["Route to email<br/>(SMTP configured)"]
    end

    subgraph VIZ["Grafana :3000"]
        D1["01: Platform Overview"]
        D2["02: Service Operations"]
        D3["03: Worker Pipeline"]
        D4["04: Infrastructure Reliability"]
        D5["05: Alerts & Incidents"]
        D6["06: Log Explorer"]
        D7["07: Ops Command Center"]
    end

    subgraph LOGS["Log Pipeline"]
        CONTAINERS["Docker Container Logs"]
        PTAIL["Promtail<br/>(log shipper)"]
        LOKI["Loki :3100<br/>(log aggregation)"]
    end

    TARGETS --> SCRAPE
    SCRAPE --> METRICS
    METRICS --> STORE_P
    RULES -->|"Firing"| ALERT
    ALERT --> ROUTE
    STORE_P --> VIZ
    CONTAINERS --> PTAIL
    PTAIL --> LOKI
    LOKI --> VIZ
```

---

## 11. Frontend SPA Tab Structure

```
┌─────────────────────────────────────────────────────────────────────┐
│  DPI Platform Frontend (:8080)                                       │
│  Apache httpd + Reverse Proxy + SPA                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────┬────────────┬────────────┬──────────────┬─────────┐    │
│  │  Home   │  Clinical  │ Insurance  │ Privacy      │ Forgery │    │
│  │         │  Document  │ Policy     │ Filter       │ Detect  │    │
│  └────┬────┴─────┬──────┴─────┬──────┴──────┬───────┴────┬────┘    │
│       │          │            │             │            │          │
│  ┌────▼────┐ ┌───▼────────┐ ┌▼──────────┐ ┌▼─────────┐ ┌▼───────┐ │
│  │Dashboard│ │• Upload    │ │• Upload   │ │• Upload  │ │• Upload│ │
│  │Stats    │ │• API Access│ │• API Acc. │ │• Entities│ │• Poll  │ │
│  │Geo Map  │ │• Run Local │ │• Run Loc. │ │• Preview │ │• Find- │ │
│  │Features │ │• User Guide│ │• User Gd. │ │• Edit    │ │  ings  │ │
│  │         │ │• Team      │ │• Team     │ │• Download│ │• Annot.│ │
│  │         │ │            │ │           │ │• API Acc.│ │• Export│ │
│  └─────────┘ └────────────┘ └───────────┘ └──────────┘ └────────┘ │
│                                                                      │
│  Apache Reverse Proxy Rules:                                         │
│  /pdf2abdm/*  → :8000    /pdf2nhcx/*  → :8001                      │
│  /api/*       → :8003    /forgensic/* → :8004                       │
│  /logs/*      → :8002    /health      → :8000                       │
│                                                                      │
│  JS Modules: main.js, dashboard.js, processor.js,                    │
│              apiaccess.js, fhir-validator.js, forgery.js             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 12. GCS Bucket Layout

```
gs://tanuh-bcd-bucket/
├── pdf_uploads/
│   ├── abdm/
│   │   └── {filename}.pdf          ← Clinical PDFs (fire-and-forget upload)
│   └── nhcx/
│       └── {filename}.pdf          ← Insurance PDFs (fire-and-forget upload)
├── json_output/
│   ├── abdm/
│   │   └── {filename}.json         ← ABDM FHIR Document Bundles
│   └── nhcx/
│       └── {filename}.json         ← NHCX FHIR Collection Bundles
└── privacy-app/
    ├── uploads/
    │   └── {job_id}__{filename}    ← Original uploaded files
    ├── redacted/
    │   └── {job_id}__redacted.ext  ← Redacted output files
    └── stats/
        ├── counters.json           ← Usage counters
        └── visitor_hashes.json     ← Unique visitor hashes
```

---

## 13. Environment Variables Summary

| Category | Variable | Default | Used By |
|----------|----------|---------|---------|
| **Redis** | `REDIS_URL` | `redis://localhost:6379/0` | All services + workers |
| **GCP** | `GOOGLE_APPLICATION_CREDENTIALS` | — | All (shared SA) |
| | `GCS_BUCKET` | `tanuh-bcd-bucket` | pdf2abdm, pdf2nhcx, privacy_filter |
| | `GCS_CREDENTIALS_JSON` | — | GCS-specific SA |
| | `PROJECT_ID` / `LLM_PROJECT_ID` | `bcd-prototypes` | Vertex AI |
| | `LLM_LOCATION` | `us-central1` | Vertex AI |
| | `LLM_MODEL` | `gemma-4-26b-a4b-it-maas` | pdf2abdm, pdf2nhcx |
| **Auth** | `ABDM_SECRET_KEY` | — | pdf2abdm |
| | `NHCX_SECRET_KEY` | — | pdf2nhcx |
| | `SECRET_KEY` | — | privacy-filter |
| | `FORGENSIC_SECRET_KEY` | — | forgensic |
| | `*_AUTH_ENABLED` | `true` | All (per-service toggle) |
| | `*_TOKEN_EXPIRY_DAYS` | `1` | All (per-service) |
| | `KEYCLOAK_REALM_URL` | — | All (optional RS256) |
| **Database** | `MYSQL_USER` | — | session-logger |
| | `MYSQL_PASSWORD` | — | session-logger |
| | `MYSQL_HOST` | `cloud-sql-proxy` | session-logger |
| | `MYSQL_DB` | `dpi_session_logger` | session-logger |
| **Storage** | `STORAGE_BACKEND` | `local` | privacy-filter |
| | `LOCAL_DATA_DIR` | `./data` | privacy-filter |
| | `DATA_DIR` | `/app/forgensic_data` | forgensic |
| | `PDF_UPLOAD_DIR` | `/app/pdf_uploads/tmp` | pdf2abdm, pdf2nhcx |
| **Tasks** | `TASK_RESULT_TTL` | `86400` (24h) | All |
| | `JOB_TTL_SECONDS` | `3600` (1h) | forgensic |
| **Pipeline** | `PIPELINE_PRESET` | `npv_focus` | forgensic |
| | `OCR_ENABLED` | `true` | forgensic |
| | `MAX_UPLOAD_BYTES` | `26214400` (25MB) | forgensic |
| **Monitoring** | `WORKER_METRICS_PORT` | `9200` | Workers |
| | `PROMETHEUS_MULTIPROC_DIR` | `/tmp/prometheus_multiproc` | Workers |
| **Session** | `SESSION_LOGGER_URL` | `http://session-logger:8002` | All |

---

## 14. Docker Compose Container Summary

| # | Container | Image | Replicas | Ports | Depends On |
|---|-----------|-------|----------|-------|------------|
| 1 | redis | redis:7-alpine | 1 | 6379 | — |
| 2 | cloud-sql-proxy | gcr.io/cloud-sql-connectors/cloud-sql-proxy:2 | 1 | 3306 | — |
| 3 | session-logger | ./session_logger/Dockerfile | 1 | 8002 | cloud-sql-proxy |
| 4 | pdf2abdm | ./pdf2abdm/Dockerfile | 1 | 8000 | redis, session-logger |
| 5 | pdf2nhcx | ./pdf2nhcx/Dockerfile | 1 | 8001 | redis, session-logger |
| 6 | privacy-filter | ./privacy_filter/Dockerfile | 1 | 8003 | redis, session-logger |
| 7 | forgensic | ./forgensic/Dockerfile | 1 | 8004 | redis |
| 8 | frontend | ./frontend/Dockerfile | 1 | 8080 | pdf2abdm, pdf2nhcx |
| 9 | celery-abdm-worker | ./worker/Dockerfile | **4** | — | redis |
| 10 | celery-nhcx-worker | ./worker/Dockerfile | **4** | — | redis |
| 11 | celery-privacy-worker | ./privacy_filter/Dockerfile | **4** | — | redis |
| 12 | celery-forgensic-worker | ./forgensic/Dockerfile | **4** | — | redis |

**Total containers: 24** (8 singletons + 16 worker replicas)
**Total parallel processing slots: 32** (4 queues × 4 replicas × 2 concurrency)

---

## 15. End-to-End Processing Timeline

```
Clinical Document (pdf2abdm) — Typical: 30-120 seconds
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 0s      Upload + Queue
 1-5s    OCR (PyPDF → Docling → LightOn waterfall)
 5-6s    Document Classification (keyword < 1ms; LLM fallback ~2s)
 6-8s    Doc Type Classification + Resource Selection
 8-90s   LangGraph FHIR Extraction (per-resource LLM calls, sequential)
 90-95s  Bundle Assembly + Sanitization
 95-100s Store to Redis + GCS upload (fire-and-forget)
 100s+   Result available for polling

Insurance Document (pdf2nhcx) — Typical: 60-180 seconds
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 0s      Upload + Queue
 1-5s    OCR
 5-6s    Classification Gate
 6-70s   Text Distillation (4 parallel LLM chunks, ~60s)
 70-75s  NHCX Resource Selection
 75-150s LangGraph FHIR Extraction
 150-160s Collection Bundle Assembly
 160-165s Store to Redis + GCS
 165s+   Result available

Privacy Filter — Typical: 5-30 seconds
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 0s      Upload + Queue
 1-2s    Load file (DICOM/NIfTI/PDF/Image)
 2-5s    Metadata detection + cleaning
 5-10s   TextRegion detection (connected components)
 10-15s  OCR detection (Tesseract)
 15-18s  PHI classification (regex + keywords)
 18-22s  Redaction (mask/crop/inpaint)
 22-25s  Post-redaction validation
 25-28s  Save output + store result
 28s+    Result available

Forgery Detection (forgensic) — Typical: 10-60 seconds per page
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 0s      Upload + Queue
 1-3s    PDF → page image rendering
 Per page:
  3-5s   Page quality assessment
  5-8s   C1: Copy-move (ORB keypoints)
  8-10s  C2: Overwriting (edge analysis)
  10-12s C3: Added content (component shapes)
  12-14s C4: Erased content (gap analysis)
  14-16s C5: Merge detection (density profiles)
  16-18s C6: Watermark removal (Hough + FFT)
  18-20s C7: Irregular spacing (token gaps)
  20-22s C8-C9: AI generation (FFT spectrum)
  22-25s Postprocess + annotated preview
 Last:
  +3s    Findings summary (OCR snippets)
  +2s    Export files (JSON/Excel/YAML)
  +1s    Store to Redis
```
