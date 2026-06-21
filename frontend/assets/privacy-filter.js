/**
 * Privacy Filter — namespaced JS for the NHCX inline tab.
 * All symbols prefixed with PF_ to avoid collisions with NHCX script.js.
 *
 * Backend: privacy-filter container (port 8003)
 * Routed via Apache reverse proxy: /privacy-filter/* → http://privacy-filter:8003/
 *
 * API surface:
 *   GET  /api/health          — { status, model, device, model_loaded }
 *   GET  /api/supported-types — { extensions: [...] }
 *   POST /api/demo-token      — { access_token, token_type, expires_in_days, name, email }
 *   POST /api/submit           — multipart file → 202 { task_id, poll_url, result_url }
 *   GET  /api/task-status/{id}  — poll progress → { status, step, progress }
 *   GET  /api/task-result/{id}  — fetch completed result → { entities, entity_counts, ... }
 *   POST /api/redact            — (legacy sync) multipart file → RedactionResult
 *   GET  /api/files/{kind}/{key} — download original or redacted file
 */

(function () {
  "use strict";

  // ── Config ───────────────────────────────────────────────────────────────
  // Apache proxy path: /privacy-filter/* → http://privacy-filter:8003/
  const PF_LOCAL     = "http://localhost:8003";
  const PF_BASE      = (window.DPI_API_CONFIG && window.DPI_API_CONFIG.pf)
    ? window.DPI_API_CONFIG.pf
    : (window.location.hostname === "localhost" ? PF_LOCAL : "/privacy-filter");
  const PF_TOKEN_KEY = "pf_token";

  // Expose for pf-editor.js
  window._PF_BASE = PF_BASE;

  // ── Auth helpers ─────────────────────────────────────────────────────────
  function PF_getToken() {
    return sessionStorage.getItem(PF_TOKEN_KEY) || "";
  }
  window._PF_getToken = PF_getToken;
  function PF_storeToken(token) {
    sessionStorage.setItem(PF_TOKEN_KEY, token);
  }

  /**
   * Silently obtain a demo token for UI users.
   * Uses /api/demo-token (the endpoint that exists on the live Cloud Run service).
   * Caches in sessionStorage so only one request per session.
   */
  async function PF_ensureToken() {
    const existing = PF_getToken();
    if (existing) return existing;
    try {
      const r = await fetch(`${PF_BASE}/api/demo-token`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ name: "UI User", email: "ui@nhcx.tanuh.ai" }),
        signal:  AbortSignal.timeout(10000),
      });
      if (!r.ok) {
        console.warn("[PF] demo-token request failed:", r.status);
        return "";
      }
      const { access_token } = await r.json();
      PF_storeToken(access_token);
      return access_token;
    } catch (e) {
      console.warn("[PF] demo-token error:", e.message);
      return "";
    }
  }

  async function PF_authFetch(url, opts = {}) {
    const token = await PF_ensureToken();
    if (token) {
      opts.headers = { ...(opts.headers || {}), Authorization: `Bearer ${token}` };
    }
    return fetch(url, opts);
  }

  function PF_decodeJwt(token) {
    try {
      const parts = token.split(".");
      if (parts.length !== 3) return null;
      const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(atob(b64));
    } catch {
      return null;
    }
  }

  // ── DOM helpers ──────────────────────────────────────────────────────────
  function pfQ(id) { return document.getElementById(id); }

  // ── Health ping ──────────────────────────────────────────────────────────
  // GET /api/health → { status, model, device, model_loaded }
  async function PF_pingHealth() {
    const badge  = pfQ("pfHealthBadge");
    const textEl = pfQ("pfHealthText");
    if (!badge || !textEl) return;
    try {
      const r = await fetch(`${PF_BASE}/api/health`, {
        signal: AbortSignal.timeout(10000),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      const ready    = !!j.model_loaded;
      // Format: "OPENAI/PRIVACY-FILTER · CPU READY" (mirrors the Cloud Run UI)
      const modelTag = j.model  ? j.model.toUpperCase()  : "PRIVACY-FILTER";
      const devTag   = j.device ? j.device.toUpperCase() : "";
      const suffix   = devTag ? `${devTag} ` : "";
      textEl.textContent = ready
        ? `${modelTag} · ${suffix}READY`
        : `${modelTag} · ${suffix}WARMING UP…`;
      badge.classList.toggle("ai-badge-off", !ready);
      if (!ready) setTimeout(PF_pingHealth, 3000);
    } catch (e) {
      if (textEl) textEl.textContent = "PRIVACY FILTER · UNREACHABLE";
      badge?.classList.add("ai-badge-off");
      setTimeout(PF_pingHealth, 5000);
    }
  }

  // GET /api/supported-types → { extensions: [".pdf", ".docx", ...] }
  async function PF_loadSupported() {
    try {
      const r = await fetch(`${PF_BASE}/api/supported-types`, {
        signal: AbortSignal.timeout(8000),
      });
      const j = await r.json();
      const el = pfQ("pfSupported");
      if (el) el.textContent = `Accepted: ${j.extensions.join(", ")}`;
      // Also update file input accept attribute
      const input = pfQ("pfFileInput");
      if (input && j.extensions) {
        input.setAttribute("accept", j.extensions.join(","));
      }
    } catch {}
  }

  // ── Status helpers ───────────────────────────────────────────────────────
  function PF_setStatus(msg, isError = false) {
    const el = pfQ("pfStatus");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("hidden");
    el.style.color = isError ? "var(--error-red, #dc2626)" : "var(--primary)";
  }
  function PF_clearStatus() {
    const el = pfQ("pfStatus");
    if (el) { el.classList.add("hidden"); el.textContent = ""; }
  }

  // ── Entity type → colour palette ─────────────────────────────────────────
  const PF_ENTITY_PALETTE = {
    private_person:    { bg: "#fce7f3", color: "#be185d", icon: "fa-user",           accent: "#db2777" },
    private_date:      { bg: "#fef3c7", color: "#b45309", icon: "fa-calendar-alt",   accent: "#d97706" },
    address_location:  { bg: "#dbeafe", color: "#1d4ed8", icon: "fa-map-marker-alt", accent: "#2563eb" },
    org_name:          { bg: "#d1fae5", color: "#065f46", icon: "fa-building",        accent: "#059669" },
    phone_number:      { bg: "#ede9fe", color: "#6d28d9", icon: "fa-phone",           accent: "#7c3aed" },
    email:             { bg: "#e0f2fe", color: "#0369a1", icon: "fa-envelope",        accent: "#0284c7" },
    id_number:         { bg: "#fee2e2", color: "#991b1b", icon: "fa-id-card",         accent: "#dc2626" },
    burned_in_text:    { bg: "#fee2e2", color: "#991b1b", icon: "fa-image",           accent: "#dc2626" },
  };
  function PF_entityStyle(group) {
    const key = (group || "").replace(/^private_/, "");
    return PF_ENTITY_PALETTE[group] || PF_ENTITY_PALETTE[key] || {
      bg: "#f1f5f9", color: "#475569", icon: "fa-shield-alt", accent: "#64748b"
    };
  }

  // ── Render result ─────────────────────────────────────────────────────────
  // GET /api/task-result/{id} response (or legacy POST /api/redact):
  // { job_id, filename, content_type, entities, entity_counts, notes,
  //   original_url, redacted_url, text_preview_original, text_preview_redacted }
  function PF_renderResult(res) {
    const resultsEl = pfQ("pfResults");
    if (!resultsEl) return;
    resultsEl.classList.remove("hidden");

    const teaser = document.getElementById("pfEditorTeaser");
    if (teaser) teaser.style.display = "none";

    // ── 1. Meta bar ──────────────────────────────────────────────────────────
    const setChip = (id, text, show = true) => {
      const chip = pfQ(id);
      if (!chip) return;
      chip.querySelector("span").textContent = text || "—";
      chip.classList.toggle("hidden", !show || !text);
    };
    setChip("pfMetaJobId",  `Job: ${res.job_id || "—"}`);
    setChip("pfMetaFile",    res.filename || "");
    setChip("pfMetaType",    res.content_type || "");
    setChip("pfMetaNotes",   res.notes || "", !!res.notes);

    // ── 2. Download buttons — store URLs and enable ──────────────────────────
    window._PF_urls = {
      original: res.original_url ? `${PF_BASE}${res.original_url}` : null,
      redacted:  res.redacted_url  ? `${PF_BASE}${res.redacted_url}`  : null,
    };
    window._PF_filename = res.filename || "document";
    window._PF_jobId = res.job_id || "";
    window._PF_uploadKey = res.original_url ? res.original_url.split("/").pop() : "";

    const btnOrig = pfQ("pfDlOriginal");
    const btnRed  = pfQ("pfDlRedacted");

    if (btnOrig) btnOrig.disabled = !window._PF_urls.original;
    if (btnRed) btnRed.disabled = !window._PF_urls.redacted;

    // Build AI boxes for the editor from entities that have bounding boxes
    window._PF_aiBoxes = (res.entities || [])
      .filter(e => e.bbox)
      .map(e => ({
        page: e.bbox.page || 0,
        x: e.bbox.x1,
        y: e.bbox.y1,
        w: e.bbox.x2 - e.bbox.x1,
        h: e.bbox.y2 - e.bbox.y1,
        label: e.entity_group || "PHI",
        source: "ai",
      }));

    // ── 2b. Load visual previews ─────────────────────────────────────────────
    const origKey = res.original_url ? res.original_url.split("/").pop() : null;
    const redKey = res.redacted_url ? res.redacted_url.split("/").pop() : null;
    if (origKey && window.PF_loadPreview) window.PF_loadPreview("original", origKey);
    if (redKey && window.PF_loadPreview) window.PF_loadPreview("redacted", redKey);

    // ── 3. Summary cards (one per entity_type) ───────────────────────────────
    const cardsEl = pfQ("pfSummaryCards");
    if (cardsEl) {
      cardsEl.innerHTML = "";
      const counts = res.entity_counts || {};
      const total  = Object.values(counts).reduce((s, v) => s + v, 0);

      // Total card
      const totalCard = document.createElement("div");
      totalCard.className = "pf-summary-card";
      totalCard.style.setProperty("--pf-card-accent", "#14868C");
      totalCard.innerHTML = `
        <div class="pf-summary-card-count">${total}</div>
        <div class="pf-summary-card-label"><i class="fas fa-shield-alt"></i> Total PII Found</div>`;
      cardsEl.appendChild(totalCard);

      // Per-type cards
      const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
      for (const [type, count] of sorted) {
        const style = PF_entityStyle(type);
        const label = type.replace(/^private_/, "").replace(/_/g, " ");
        const card  = document.createElement("div");
        card.className = "pf-summary-card";
        card.style.setProperty("--pf-card-accent", style.accent);
        card.innerHTML = `
          <div class="pf-summary-card-count" style="color:${style.accent}">${count}</div>
          <div class="pf-summary-card-label">
            <i class="fas ${style.icon}" style="color:${style.accent}"></i> ${label}
          </div>`;
        cardsEl.appendChild(card);
      }
    }

    // ── 4. Entity table ───────────────────────────────────────────────────────
    const tbody   = pfQ("pfEntityTbody");
    const totalEl = pfQ("pfEntityTotal");
    const entities = res.entities || [];

    if (totalEl) totalEl.textContent = `${entities.length} entities`;

    if (tbody) {
      tbody.innerHTML = "";
      if (entities.length === 0) {
        tbody.innerHTML = `
          <tr><td colspan="5" style="text-align:center; padding:24px; color:#94a3b8;">
            <i class="fas fa-check-circle" style="margin-right:6px; color:#22c55e;"></i>
            No personal information detected.
          </td></tr>`;
      } else {
        entities.forEach((ent, idx) => {
          const style   = PF_entityStyle(ent.entity_group);
          let label     = (ent.entity_group || "unknown").replace(/^private_/, "").replace(/_/g, " ");
          if (label === "burned in text") {
            label = "image pii";
          }
          const pct     = Math.round((ent.score || 0) * 100);
          const confCls = pct >= 80 ? "pf-conf-high" : pct >= 55 ? "pf-conf-mid" : "pf-conf-low";
          const word    = (ent.word || "").trim();
          const displayWord = word ? escHtml(word) : `<span style="color:#94a3b8; font-style:italic; font-weight:normal;">[Image Region]</span>`;

          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td style="color:#94a3b8; font-size:0.78rem; white-space: nowrap;">${idx + 1}</td>
            <td><span class="pf-entity-word">${displayWord}</span></td>
            <td>
              <span class="pf-entity-badge"
                    style="background:${style.bg}; color:${style.color};">
                <i class="fas ${style.icon}"></i>${label}
              </span>
            </td>
            <td>
              <div class="pf-conf-bar-wrap">
                <div class="pf-conf-bar">
                  <div class="pf-conf-bar-fill ${confCls}" style="width:${pct}%"></div>
                </div>
                <span class="pf-conf-label">${pct}%</span>
              </div>
            </td>`;
          tbody.appendChild(tr);
        });
      }
    }

    // ── 5. Text previews (fallback for text-only formats) ───────────────────
    const prevOrig = pfQ("pfPrevOriginal");
    const prevRed  = pfQ("pfPrevRedacted");
    const textSection = pfQ("pfTextPreviewSection");
    if (prevOrig) prevOrig.textContent = res.text_preview_original || "(no text preview available)";
    if (prevRed)  prevRed.textContent  = res.text_preview_redacted  || "(no text preview available)";
    if (textSection) {
      const ext = (res.filename || "").split(".").pop().toLowerCase();
      const textOnly = ["txt", "md", "log", "csv", "docx"];
      textSection.style.display = textOnly.includes(ext) ? "" : "none";
    }
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Download via fetch+blob ───────────────────────────────────────────────
  // Browser silently ignores the `download` attribute on cross-origin URLs.
  // We fetch the file through PF_authFetch (adds Bearer token) then create
  // a same-origin blob URL so the browser always triggers a Save dialog.
  window.PF_downloadFile = async function (kind) {
    const urls     = window._PF_urls || {};
    const url      = urls[kind];
    const filename = window._PF_filename || "document";
    if (!url) return;

    const btnId  = kind === "original" ? "pfDlOriginal" : "pfDlRedacted";
    const subId  = kind === "original" ? "pfDlOriginalSub" : "pfDlRedactedSub";
    const btn    = pfQ(btnId);
    const subEl  = pfQ(subId);
    const origSub = subEl?.textContent || "";

    // Spinner state
    if (btn) btn.disabled = true;
    if (subEl) subEl.textContent = "Downloading…";

    try {
      const r = await PF_authFetch(url, { signal: AbortSignal.timeout(30000) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);

      const blob    = await r.blob();
      const objUrl  = URL.createObjectURL(blob);
      const suffix  = kind === "redacted" ? "__redacted" : "";
      const dlName  = filename.replace(/(\.[^.]+)$/, `${suffix}$1`);

      // Invisible anchor click — works for any origin
      const a  = document.createElement("a");
      a.href   = objUrl;
      a.download = dlName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);

      // Revoke after a short delay
      setTimeout(() => URL.revokeObjectURL(objUrl), 10000);
      if (subEl) subEl.textContent = "✓ Saved";
      setTimeout(() => { if (subEl) subEl.textContent = origSub; }, 3000);
    } catch (e) {
      if (subEl) subEl.textContent = `Error: ${e.message}`;
      setTimeout(() => { if (subEl) subEl.textContent = origSub; }, 4000);
    } finally {
      if (btn) btn.disabled = false;
    }
  };

  // ── File upload (async submit + poll) ─────────────────────────────────────
  // POST /api/submit → 202 { task_id } → poll /api/task-status/{id} → /api/task-result/{id}

  async function PF_submitFile(file) {
    const fd = new FormData();
    fd.append("file", file);
    return PF_authFetch(`${PF_BASE}/api/submit`, {
      method: "POST",
      body:   fd,
      signal: AbortSignal.timeout(120000),
    });
  }

  function PF_pollTaskStatus(taskId) {
    return new Promise((resolve, reject) => {
      const poll = setInterval(async () => {
        try {
          const r = await PF_authFetch(`${PF_BASE}/api/task-status/${taskId}`);
          if (r.status === 401) {
            clearInterval(poll);
            sessionStorage.removeItem(PF_TOKEN_KEY);
            reject(new Error("Authentication expired. Please reload and try again."));
            return;
          }
          if (!r.ok) return;
          const data = await r.json();

          if (data.status === "PROGRESS") {
            const step = data.step || "Processing";
            const pct = data.progress || 0;
            PF_setStatus(`${step}… (${pct}%)`);
          }

          if (data.status === "completed") {
            clearInterval(poll);
            resolve(taskId);
          }
          if (data.status === "failed") {
            clearInterval(poll);
            reject(new Error(data.error || "Redaction failed"));
          }
        } catch (_) {}
      }, 2000);

      setTimeout(() => {
        clearInterval(poll);
        reject(new Error("Redaction timed out after 10 minutes. Please retry."));
      }, 600000);
    });
  }

  async function PF_fetchTaskResult(taskId) {
    const r = await PF_authFetch(`${PF_BASE}/api/task-result/${taskId}`);
    if (!r.ok) throw new Error(`Failed to fetch result: HTTP ${r.status}`);
    return r.json();
  }

  async function PF_uploadFile(file) {
    PF_clearStatus();
    if (window.PF_resetEditorState) window.PF_resetEditorState();
    const resultsEl = pfQ("pfResults");
    const loader    = pfQ("pfLoader");
    const btnText   = pfQ("pfProcessBtn")?.querySelector("span");
    const teaser    = pfQ("pfEditorTeaser");

    if (resultsEl) resultsEl.classList.add("hidden");
    if (loader)    loader.style.display = "block";
    if (btnText)   btnText.textContent  = "Redacting…";
    if (teaser)    teaser.style.display = "none";

    PF_setStatus(`Uploading ${file.name}…`);

    const pfBase = window._PF_BASE || PF_BASE;
    const isLocalPF = pfBase.includes("localhost") || pfBase.includes("127.0.0.1");

    try {
      let result;

      if (isLocalPF) {
        // Sync path — no Redis/Celery needed
        const fd = new FormData();
        fd.append("file", file);
        PF_setStatus("Processing…");
        const r = await PF_authFetch(`${pfBase}/api/redact`, {
          method: "POST",
          body:   fd,
          signal: AbortSignal.timeout(300000),
        });
        if (r.status === 401) {
          sessionStorage.removeItem(PF_TOKEN_KEY);
          PF_setStatus("Authentication failed. Please reload and try again.", true);
          return;
        }
        if (!r.ok) {
          const err = await r.json().catch(() => ({ detail: r.statusText }));
          throw new Error(err.detail || `HTTP ${r.status}`);
        }
        result = await r.json();
      } else {
        // Async path — production with Redis/Celery workers
        const r = await PF_submitFile(file);

        if (r.status === 401) {
          sessionStorage.removeItem(PF_TOKEN_KEY);
          const retry = await PF_submitFile(file);
          if (retry.status === 401) {
            PF_setStatus("Authentication failed. Please reload and try again.", true);
            return;
          }
          if (!retry.ok && retry.status !== 202) {
            const err = await retry.json().catch(() => ({ detail: retry.statusText }));
            throw new Error(err.detail || `HTTP ${retry.status}`);
          }
          var submitData = await retry.json();
        } else if (!r.ok && r.status !== 202) {
          if (r.status === 500) {
            PF_setStatus(
              "The Privacy Filter (Anonymization) service encountered an internal error. " +
              "The document may be too large, or the service is still initializing. Please try again.",
              true
            );
            return;
          }
          const err = await r.json().catch(() => ({ detail: r.statusText }));
          throw new Error(err.detail || `HTTP ${r.status}`);
        } else {
          var submitData = await r.json();
        }

        PF_setStatus("Queued — waiting for worker…");
        const taskId = submitData.task_id;
        await PF_pollTaskStatus(taskId);

        PF_setStatus("Fetching results…");
        result = await PF_fetchTaskResult(taskId);
      }

      if (result.status === "failed") {
        throw new Error(result.error || "Redaction failed");
      }

      const n = result.entities?.length ?? 0;
      PF_setStatus(`✓ Done — ${n} PII ${n === 1 ? "entity" : "entities"} detected.`);
      PF_renderResult(result);

    } catch (e) {
      if (e.name === "AbortError" || e.name === "TimeoutError") {
        PF_setStatus("Upload timed out. The file may be too large or the connection slow — please retry.", true);
      } else {
        PF_setStatus(`Error: ${e.message}`, true);
      }
    } finally {
      if (loader)  loader.style.display = "none";
      if (btnText) btnText.textContent  = "Redact Document";
    }
  }

  window.PF_updateFileName = function () {
    const input = pfQ("pfFileInput");
    const label = pfQ("pfFileName");
    if (input && label && input.files.length) {
      label.textContent = input.files[0].name;
    }
  };

  window.PF_handleFileChange = function () {
    if (window.PF_updateFileName) PF_updateFileName();
    const input    = document.getElementById('pfFileInput');
    const dropzone = document.getElementById('pfDropzone');
    const card     = document.getElementById('pfFileCard');
    const nameEl   = document.getElementById('pfCardFileName');
    const sizeEl   = document.getElementById('pfCardFileSize');
    const btn      = document.getElementById('pfProcessBtn');
    if (input && input.files && input.files.length > 0) {
      const file = input.files[0];
      if (nameEl) nameEl.textContent = file.name;
      if (sizeEl) sizeEl.textContent = (file.size / 1024).toFixed(1) + ' KB';
      if (dropzone) dropzone.style.display = 'none';
      if (card) card.style.display = 'flex';
      if (btn) btn.removeAttribute('disabled');
    }
  };

  window.PF_removeFile = function (e) {
    if (e) e.stopPropagation();
    const input    = document.getElementById('pfFileInput');
    const dropzone = document.getElementById('pfDropzone');
    const card     = document.getElementById('pfFileCard');
    const btn      = document.getElementById('pfProcessBtn');
    const label    = document.getElementById('pfFileName');
    if (input) input.value = '';
    if (label) label.textContent = 'Choose document to redact...';
    if (dropzone) dropzone.style.display = 'flex';
    if (card) card.style.display = 'none';
    if (btn) btn.setAttribute('disabled', 'true');
    const resultsSec = document.getElementById('pfResults');
    if (resultsSec) resultsSec.classList.add('hidden');
    const teaser = document.getElementById('pfEditorTeaser');
    if (teaser) teaser.style.display = 'flex';
  };

  window.PF_processRedaction = function () {
    const input = pfQ("pfFileInput");
    if (!input || !input.files.length) {
      PF_setStatus("Please choose a file first.", true);
      return;
    }
    PF_uploadFile(input.files[0]);
  };

  // ── Token form (only shown if pfTokenForm exists in the HTML) ────────────
  function PF_initTokenForm() {
    const form     = pfQ("pfTokenForm");
    const submit   = pfQ("pfTokenSubmit");
    const result   = pfQ("pfTokenResult");
    const errEl    = pfQ("pfTokenError");
    const output   = pfQ("pfTokenOutput");
    const copyBtn  = pfQ("pfTokenCopy");
    const greeting = pfQ("pfTokenGreeting");
    const expiryEl = pfQ("pfTokenExpiry");
    const appliedEl = pfQ("pfTokenApplied");
    if (!form) return;

    const existing = PF_getToken();
    if (existing) _showResult(existing, null, null, true);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const name  = pfQ("pfTokenName")?.value.trim();
      const email = pfQ("pfTokenEmail")?.value.trim();
      if (!name || !email) { _showError("Please fill in both name and email."); return; }
      submit.disabled = true;
      submit.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Requesting…';
      errEl?.classList.add("hidden");
      result?.classList.add("hidden");

      try {
        const r = await fetch(`${PF_BASE}/api/demo-token`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ name, email }),
        });
        if (!r.ok) {
          const errJson = await r.json().catch(() => ({}));
          throw new Error(errJson.detail || `HTTP ${r.status}`);
        }
        const data = await r.json();
        PF_storeToken(data.access_token);
        _showResult(data.access_token, data.name, data.expires_in_days, false);
      } catch (err) {
        _showError(`Failed to request token: ${err.message}`);
      } finally {
        submit.disabled = false;
        submit.innerHTML = '<i class="fas fa-bolt"></i> Request Token';
      }
    });

    copyBtn?.addEventListener("click", async () => {
      const token = output?.textContent?.trim();
      if (!token) return;
      try {
        await navigator.clipboard.writeText(token);
        copyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
        copyBtn.classList.add("pf-copied");
        setTimeout(() => {
          copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy';
          copyBtn.classList.remove("pf-copied");
        }, 2000);
      } catch { copyBtn.textContent = "Use Ctrl+C"; }
    });

    function _showResult(token, name, expiresInDays, restored) {
      if (output) output.textContent = token;
      result?.classList.remove("hidden");
      errEl?.classList.add("hidden");
      const payload     = PF_decodeJwt(token);
      const displayName = name || payload?.name || "";
      const expTs       = payload?.exp;
      if (displayName && greeting) {
        greeting.textContent = restored
          ? `Welcome back, ${displayName}!`
          : `🎉 Token issued for ${displayName}`;
      }
      if (expTs && expiryEl) {
        expiryEl.textContent = `Expires ${new Date(expTs * 1000).toLocaleDateString(undefined, { dateStyle: "medium" })}`;
      } else if (expiresInDays && expiryEl) {
        expiryEl.textContent = `Valid for ${expiresInDays} days`;
      }
      if (appliedEl) appliedEl.style.display = "flex";
    }
    function _showError(msg) {
      if (errEl) { errEl.textContent = msg; errEl.classList.remove("hidden"); }
    }
  }

  // ── Public init — called by NHCX openTab() after DOM is ready ────────────
  window.PF_init = function () {
    PF_initTokenForm();
    PF_pingHealth();
    PF_loadSupported();
    // Pre-fetch a token silently so it's ready when the user hits Redact
    PF_ensureToken();

    // Reset view to landing/overview page on tab load
    const landing = document.getElementById('pf-landing-view');
    const interactive = document.getElementById('pf-interactive-view');
    if (landing) landing.style.display = 'block';
    if (interactive) interactive.style.display = 'none';
  };

  window.PF_launchService = function () {
    const landing = document.getElementById('pf-landing-view');
    const interactive = document.getElementById('pf-interactive-view');
    if (landing) landing.style.display = 'none';
    if (interactive) {
      interactive.style.display = 'block';
      const pendingSub = sessionStorage.getItem('pendingLaunchSubTab');
      let targetBtn = null;
      if (pendingSub) {
        sessionStorage.removeItem('pendingLaunchSubTab');
        targetBtn = interactive.querySelector(`.sub-tab-btn[onclick*="${pendingSub}"]`);
      }
      if (!targetBtn) {
        targetBtn = interactive.querySelector('.sub-tab-btn');
      }
      if (targetBtn) {
        targetBtn.click();
      }
    }
  };

})();
