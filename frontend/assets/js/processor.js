/**
 * processor.js - Shared logic for PDF to FHIR/NHCX conversion
 *
 * Tokens are fetched silently before each upload if not already cached.
 * UI users never need to visit the API Access tab.
 */
(function() {
    "use strict";

    // ── Silent token fetch ─────────────────────────────────────────────────────
    // Fetches a token in the background using a generic guest identity.
    // Stores it in sessionStorage so subsequent uploads reuse it.
    async function ensureToken(isClinical, base) {
        const storageKey = isClinical ? 'abdm_token' : 'nhcx_token';
        const existing   = sessionStorage.getItem(storageKey);
        if (existing) return existing;

        // Try to reuse the developer token generated in the API Access tab
        const centralKey = isClinical ? 'dpi_token_pdf2abdm' : 'dpi_token_pdf2nhcx';
        const central = localStorage.getItem(centralKey);
        if (central) {
            sessionStorage.setItem(storageKey, central);
            return central;
        }

        // Silent centralized token fetch using logged-in Firebase session
        if (window.DPI_Auth && window.DPI_Auth.isLoggedIn()) {
            const firebaseToken = window.DPI_Auth.getToken();
            const serviceId = isClinical ? 'pdf2abdm' : 'pdf2nhcx';
            const loggerBase = window.DPI_API_CONFIG ? window.DPI_API_CONFIG.logger : 'http://localhost:8002';
            try {
                const r = await fetch(`${loggerBase}/auth/token`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${firebaseToken}`
                    },
                    body: JSON.stringify({ service: serviceId })
                });
                if (r.ok) {
                    const data = await r.json();
                    sessionStorage.setItem(storageKey, data.access_token);
                    localStorage.setItem(centralKey, data.access_token);
                    localStorage.setItem(`dpi_token_expires_${serviceId}`, data.expires_at);
                    localStorage.setItem(`dpi_token_status_${serviceId}`, data.status);
                    return data.access_token;
                }
            } catch (err) {
                console.error("Silent token retrieval failed:", err);
            }
        }
        return null;
    }

    // ── Main upload entry point ────────────────────────────────────────────────
    async function processFile(taskType) {
        const isClinical = (taskType === 'PDF2FHIR');
        const fileInput  = document.getElementById(isClinical ? 'fileFHIR'           : 'fileNHCX');
        const outputEl   = document.getElementById(isClinical ? 'outputFHIR'         : 'outputNHCX');
        const loader     = document.getElementById(isClinical ? 'loaderFHIR'         : 'loaderNHCX');
        const btn        = document.getElementById(isClinical ? 'btnFHIR'            : 'btnNHCX');
        const logo       = document.getElementById(isClinical ? 'processingLogoFHIR' : 'processingLogoNHCX');

        if (!fileInput.files.length) {
            window.showToast('No File', 'Please select a PDF file.', 'warn');
            return;
        }

        const formData = new FormData();
        formData.append("file",       fileInput.files[0]);
        formData.append("model",      'gemma4');
        formData.append("ocr_engine", 'auto');

        if (window.getDash) {
            const d = window.getDash();
            if (d.last_state) formData.append("state", d.last_state);
            if (d.last_city)  formData.append("city",  d.last_city);
        }

        // UI feedback
        if (logo)   logo.style.display = "block";
        if (outputEl && outputEl.parentElement) outputEl.parentElement.style.display = "none";
        if (loader) loader.style.display = "inline-block";
        if (btn)    btn.disabled = true;
        outputEl.textContent = "Processing...";

        const base = window.DPI_API_CONFIG
            ? (isClinical ? window.DPI_API_CONFIG.abdm : window.DPI_API_CONFIG.nhcx)
            : (window.location.hostname === "localhost"
                ? (isClinical ? "http://localhost:8000" : "http://localhost:8001")
                : window.location.origin);

        // Silently obtain or reuse a token — user never needs to do this manually
        const token   = await ensureToken(isClinical, base);
        const headers = token ? { 'Authorization': `Bearer ${token}` } : {};

        const isLocal = base.includes('localhost') || base.includes('127.0.0.1');

        try {
            if (isLocal) {
                // Sync path for local dev — no GCS / Redis / Celery needed
                const syncUrl = isClinical ? `${base}/pdf2abdm` : `${base}/pdf2nhcx`;
                const r = await fetch(syncUrl, {
                    method: 'POST',
                    body:   formData,
                    headers
                });
                if (r.status === 401) throw new Error("Token rejected by server. Please refresh and try again.");
                if (!r.ok) throw new Error(await _extractErrorMessage(r, `${isClinical ? 'Clinical' : 'Insurance'} processing failed`));
                const data = await r.json();
                renderResult(data, taskType, outputEl, fileInput);
            } else if (!isClinical) {
                // Async path for NHCX (production — uses GCS + Celery)
                const r = await fetch(`${base}/pdf2nhcx/submit`, {
                    method: 'POST',
                    body:   formData,
                    headers
                });
                if (r.status === 401) throw new Error("Token rejected by server. Please refresh and try again.");
                if (!r.ok) throw new Error(await _extractErrorMessage(r, 'Insurance Policy upload failed'));
                const { task_id } = await r.json();
                const data = await pollTask(task_id, base, headers);
                if (data && (data.status === 'rejected' || data.status === 'failed')) {
                    throw new Error(data.error || 'Processing failed');
                }
                renderResult(data, taskType, outputEl, fileInput);
            } else {
                // Async path for ABDM (production — uses GCS + Celery)
                const r = await fetch(`${base}/pdf2abdm/submit`, {
                    method: 'POST',
                    body:   formData,
                    headers
                });
                if (r.status === 401) throw new Error("Token rejected by server. Please refresh and try again.");
                if (!r.ok) throw new Error(await _extractErrorMessage(r, 'Clinical Document processing failed'));
                const { task_id } = await r.json();
                const data = await pollAbdmTask(task_id, base, headers);
                if (data && (data.status === 'rejected' || data.status === 'failed')) {
                    throw new Error(data.error || 'Processing failed');
                }
                renderResult(data, taskType, outputEl, fileInput);
            }

            if (window.trackInference) window.trackInference();
        } catch (err) {
            outputEl.textContent = `Error: ${err.message}`;
            if (outputEl.parentElement) outputEl.parentElement.style.display = "block";
            window.showToast('Error', err.message, 'error');
        } finally {
            if (logo)   logo.style.display = "none";
            if (loader) loader.style.display = "none";
            if (btn)    btn.disabled = false;
        }
    }

    /**
     * Extract a human-readable error message from a non-OK HTTP response.
     * Reads the JSON body and prefers detail.message > detail > error > fallback.
     */
    async function _extractErrorMessage(response, fallback) {
        try {
            const body = await response.json();
            // FastAPI structured error: { detail: { title, message } }
            if (body && body.detail) {
                const d = body.detail;
                if (typeof d === 'object' && d.message) {
                    const prefix = d.title ? `${d.title}: ` : '';
                    return `${prefix}${d.message}`;
                }
                if (typeof d === 'string') return d;
            }
            // Generic error field
            if (body && body.error)   return body.error;
            if (body && body.message) return body.message;
        } catch (_) { /* body wasn't JSON */ }
        return `${fallback} (${response.status})`;
    }

    async function _fetchTaskResult(taskId, resultPath, base, headers) {
        const resultUrl = resultPath.startsWith('http') ? resultPath : `${base}${resultPath}`;
        const rr = await fetch(resultUrl, { headers });
        if (!rr.ok) throw new Error(`Failed to fetch result (${rr.status})`);
        const bundle = await rr.json();
        if (bundle.status === 'rejected' || bundle.status === 'failed') {
            throw new Error(bundle.error || 'Processing failed');
        }
        return bundle;
    }

    async function pollTask(taskId, base, headers) {
        const statusUrl = `${base}/pdf2nhcx/task-status/${taskId}`;
        while (true) {
            const r = await fetch(statusUrl, { headers });
            const j = await r.json();

            if (j.status === 'completed' || j.status === 'SUCCESS') {
                return await _fetchTaskResult(
                    taskId,
                    j.result_url || `/pdf2nhcx/task-result/${taskId}`,
                    base, headers
                );
            }

            if (j.status === 'rejected') throw new Error(j.error || 'Document type rejected');
            if (j.status === 'FAILURE'  || j.status === 'failed') throw new Error(j.error || 'Task failed');

            await new Promise(res => setTimeout(res, 6000));
        }
    }

    async function pollAbdmTask(taskId, base, headers) {
        const statusUrl = `${base}/pdf2abdm/task-status/${taskId}`;
        while (true) {
            const r = await fetch(statusUrl, { headers });
            const j = await r.json();

            if (j.status === 'completed' || j.status === 'SUCCESS') {
                return await _fetchTaskResult(
                    taskId,
                    j.result_url || `/pdf2abdm/task-result/${taskId}`,
                    base, headers
                );
            }

            if (j.status === 'rejected') throw new Error(j.error || 'Document type rejected');
            if (j.status === 'FAILURE'  || j.status === 'failed') throw new Error(j.error || 'Task failed');

            await new Promise(res => setTimeout(res, 6000));
        }
    }


    function renderResult(data, type, outputEl, fileInput) {
        if (outputEl.parentElement) outputEl.parentElement.style.display = "block";

        // Both NHCX and ABDM return a task-result wrapper — unwrap to show bare FHIR.
        // NHCX:  { status, task_id, doc_type, bundle: {...}, ... }
        // ABDM:  { status, task_id, doc_types, bundles: [...], ... }
        let display = data;
        if (data && data.bundle) {
            // NHCX: single bundle stored under "bundle" key
            display = data.bundle;
        } else if (data && data.bundles && Array.isArray(data.bundles)) {
            // ABDM: one bundle per patient; show array or unwrap if single
            display = data.bundles.length === 1 ? data.bundles[0] : data.bundles;
        }

        outputEl.textContent = JSON.stringify(display, null, 2);
        if (window.Prism) Prism.highlightElement(outputEl);
    }



    window.processFile       = processFile;
    window.runFhirValidation = async function(type) {
        window.showToast('Validation', 'Starting FHIR R4 validation...', 'info');
    };

    window.INS_init = function () {
        const landing = document.getElementById('insurance-landing-view');
        const interactive = document.getElementById('insurance-interactive-view');
        if (landing) landing.style.display = 'block';
        if (interactive) interactive.style.display = 'none';
    };

    window.INS_launchService = function () {
        const landing = document.getElementById('insurance-landing-view');
        const interactive = document.getElementById('insurance-interactive-view');
        if (landing) landing.style.display = 'none';
        if (interactive) {
            interactive.style.display = 'block';
            const firstBtn = interactive.querySelector('.sub-tab-btn');
            if (firstBtn) {
                firstBtn.click();
            }
        }
    };

    window.INS_handleFileChange = function () {
        if (window.updateFileName) {
            window.updateFileName('fileNHCX');
        }
        const input = document.getElementById('fileNHCX');
        const dropzone = document.getElementById('insDropzone');
        const card = document.getElementById('insFileCard');
        const nameEl = document.getElementById('insCardFileName');
        const sizeEl = document.getElementById('insCardFileSize');
        const btn = document.getElementById('btnNHCX');
        
        if (input && input.files && input.files.length > 0) {
            const file = input.files[0];
            if (nameEl) nameEl.textContent = file.name;
            if (sizeEl) {
                const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
                sizeEl.textContent = sizeMB + " MB";
            }
            if (dropzone) dropzone.style.display = 'none';
            if (card) card.style.display = 'flex';
            if (btn) btn.removeAttribute('disabled');
        }
    };

    window.INS_removeFile = function (e) {
        if (e) e.stopPropagation();
        const input = document.getElementById('fileNHCX');
        const dropzone = document.getElementById('insDropzone');
        const card = document.getElementById('insFileCard');
        const btn = document.getElementById('btnNHCX');
        
        if (input) {
            input.value = '';
            const span = document.querySelector('#labelNHCX .file-text');
            if (span) span.textContent = 'Choose PDF file...';
        }
        if (dropzone) dropzone.style.display = 'flex';
        if (card) card.style.display = 'none';
        if (btn) btn.setAttribute('disabled', 'true');
        
        const outputEl = document.getElementById('outputNHCX');
        if (outputEl) outputEl.textContent = 'Output will appear here...';
        const info = document.getElementById('infoNHCX');
        if (info) info.style.display = 'none';
        const bundleSelect = document.getElementById('bundleSelectorContainerNHCX');
        if (bundleSelect) bundleSelect.style.display = 'none';
        const logo = document.getElementById('processingLogoNHCX');
        if (logo) logo.style.display = 'none';
        const valReport = document.getElementById('validationReportNHCX');
        if (valReport) valReport.textContent = '';
    };

    window.CLN_init = function () {
        const landing = document.getElementById('clinical-landing-view');
        const interactive = document.getElementById('clinical-interactive-view');
        if (landing) landing.style.display = 'block';
        if (interactive) interactive.style.display = 'none';
    };

    window.CLN_launchService = function () {
        const landing = document.getElementById('clinical-landing-view');
        const interactive = document.getElementById('clinical-interactive-view');
        if (landing) landing.style.display = 'none';
        if (interactive) {
            interactive.style.display = 'block';
            const firstBtn = interactive.querySelector('.sub-tab-btn');
            if (firstBtn) {
                firstBtn.click();
            }
        }
    };

    window.CLN_handleFileChange = function () {
        if (window.updateFileName) {
            window.updateFileName('fileFHIR');
        }
        const input = document.getElementById('fileFHIR');
        const dropzone = document.getElementById('clnDropzone');
        const card = document.getElementById('clnFileCard');
        const nameEl = document.getElementById('clnCardFileName');
        const sizeEl = document.getElementById('clnCardFileSize');
        const btn = document.getElementById('btnFHIR');
        
        if (input && input.files && input.files.length > 0) {
            const file = input.files[0];
            if (nameEl) nameEl.textContent = file.name;
            if (sizeEl) {
                const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
                sizeEl.textContent = sizeMB + " MB";
            }
            if (dropzone) dropzone.style.display = 'none';
            if (card) card.style.display = 'flex';
            if (btn) btn.removeAttribute('disabled');
        }
    };

    window.CLN_removeFile = function (e) {
        if (e) e.stopPropagation();
        const input = document.getElementById('fileFHIR');
        const dropzone = document.getElementById('clnDropzone');
        const card = document.getElementById('clnFileCard');
        const btn = document.getElementById('btnFHIR');
        
        if (input) {
            input.value = '';
            const span = document.querySelector('#labelFHIR .file-text');
            if (span) span.textContent = 'Choose PDF file...';
        }
        if (dropzone) dropzone.style.display = 'flex';
        if (card) card.style.display = 'none';
        if (btn) btn.setAttribute('disabled', 'true');
        
        const outputEl = document.getElementById('outputFHIR');
        if (outputEl) outputEl.textContent = 'Output will appear here...';
        const info = document.getElementById('infoFHIR');
        if (info) info.style.display = 'none';
        const bundleSelect = document.getElementById('bundleSelectorContainerFHIR');
        if (bundleSelect) bundleSelect.style.display = 'none';
        const logo = document.getElementById('processingLogoFHIR');
        if (logo) logo.style.display = 'none';
        const valReport = document.getElementById('validationReportFHIR');
        if (valReport) valReport.textContent = '';
    };

})();
