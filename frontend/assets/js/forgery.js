(function () {
    "use strict";

    const FG_CATEGORY_COLORS = {
        C1: "#f97316", C2: "#f59e0b", C3: "#22c55e", C4: "#ef4444",
        C5: "#0ea5e9", C6: "#6366f1", C7: "#14b8a6", C8: "#1f2937",
        C9: "#e11d48", C10: "#9ca3af"
    };
    const FG_TOKEN_KEY = "forgensic_token";
    const FG_MAX_UPLOAD = 25 * 1024 * 1024;
    const FG_LOCAL = "http://localhost:8004";
    const FG_IS_LOCAL = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    const FG_BASE = (window.DPI_API_CONFIG && window.DPI_API_CONFIG.forgensic)
        ? window.DPI_API_CONFIG.forgensic
        : (FG_IS_LOCAL ? FG_LOCAL : `${window.location.origin}/forgensic`);

    let fgFile = null;
    let fgJobId = null;
    let fgResults = null;
    let fgFindingsAll = [];
    let fgFindingsText = "";
    let fgFindingsFileName = "";
    let fgBusy = false;
    let fgShowAllFindings = false;
    let fgPreviewVisible = true;
    let fgFocusedFinding = null;
    let fgSelectedFinding = null;
    let fgPendingPage = null;
    var FG_DEFAULT_LIMIT = 5;

    function $(id) { return document.getElementById(id); }

    function fgGetToken() {
        return sessionStorage.getItem(FG_TOKEN_KEY) || "";
    }

    function fgStoreToken(token) {
        sessionStorage.setItem(FG_TOKEN_KEY, token);
    }

    async function fgEnsureToken() {
        const existing = fgGetToken();
        if (existing) return existing;
        try {
            const r = await fetch(`${FG_BASE}/api/token`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: "UI User", email: "ui@nhcx.tanuh.ai" }),
                signal: AbortSignal.timeout(10000),
            });
            if (!r.ok) return "";
            const { access_token } = await r.json();
            if (access_token) fgStoreToken(access_token);
            return access_token || "";
        } catch (_) {
            return "";
        }
    }

    async function fgAuthFetch(url, opts = {}) {
        const token = fgGetToken();
        if (token) {
            opts.headers = { ...(opts.headers || {}), Authorization: `Bearer ${token}` };
        }
        return fetch(url, opts);
    }

    async function fgFetchObjectUrl(url) {
        const res = await fgAuthFetch(url, { method: "GET" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        return URL.createObjectURL(blob);
    }

    function fmtBytes(b) {
        if (!b) return "0 MB";
        return (b / (1024 * 1024)).toFixed(2) + " MB";
    }
    function fmtSec(v) {
        if (v == null || isNaN(v)) return "--";
        if (v < 1) return Math.round(v * 1000) + " ms";
        return v.toFixed(v < 10 ? 2 : 1) + " s";
    }

    function setProgress(label, pct) {
        var sec = $("fgProgressSection");
        if (sec) sec.style.display = "block";
        var bar = $("fgProgressBar");
        if (bar) bar.style.width = Math.max(0, Math.min(pct, 100)) + "%";
        var lbl = $("fgProgressLabel");
        if (lbl) lbl.textContent = label;
    }

    function setInference(total, avg) {
        var el = $("fgInferenceTime");
        if (!el) return;
        if (total == null || isNaN(total)) { el.textContent = ""; return; }
        var s = "Inference: " + fmtSec(total);
        if (avg != null && !isNaN(avg)) s += " (avg " + fmtSec(avg) + " / page)";
        el.textContent = s;
    }

    function showGrid(show) {
        var g = $("fgResultsGrid");
        if (g) g.style.display = show ? "grid" : "none";
    }

    function setTamperedNeutral(message) {
        var el = $("fgTamperedFlag");
        if (!el) return;
        el.classList.remove("fg-tampered-yes", "fg-tampered-no");
        el.classList.add("fg-tampered-neutral");
        el.innerHTML = '<i class="fas fa-hourglass-half"></i> Tampered: <strong>—</strong> ' + message;
    }

    function setTampered(summary) {
        var el = $("fgTamperedFlag");
        if (!el) return;
        if (!summary) {
            setTamperedNeutral("Awaiting analysis.");
            return;
        }
        var keys = Object.keys(summary || {}).filter(function (k) { return summary[k]; });
        var clean = keys.length === 0 || (keys.length === 1 && keys[0] === "C10");
        el.classList.remove("fg-tampered-neutral", "fg-tampered-yes", "fg-tampered-no");
        if (clean) {
            el.classList.add("fg-tampered-no");
            el.innerHTML = '<i class="fas fa-check-circle"></i> Tampered: <strong>No</strong> — Document appears clean.';
        } else {
            el.classList.add("fg-tampered-yes");
            el.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Tampered: <strong>Yes</strong> — Suspicious regions detected.';
        }
    }

    function buildFindingsText(payload) {
        var fn = payload?.file_name || "document";
        var ts = new Date().toISOString();
        var findings = payload?.findings_summary?.findings_all || payload?.findings_summary?.findings || [];
        var summaryTxt = payload?.findings_summary?.summary_text || "No findings.";
        var lines = ["File: " + fn, "Generated: " + ts, "", "Findings:"];
        if (findings.length) {
            findings.forEach(function (f) { lines.push("- " + (f.summary || "Finding")); });
        } else {
            lines.push(summaryTxt);
        }
        return lines.join("\n");
    }

    function setFindingsMeta(payload) {
        var el = $("fgFindingsMeta");
        if (!el) return;
        if (!payload) { el.textContent = "No document processed yet."; return; }
        var fn = payload.file_name || "Document";
        var updated = payload.updated_at ? "Updated " + payload.updated_at : "";
        el.textContent = updated ? fn + " · " + updated : fn;
    }

    function renderFindings(payload) {
        var list = $("fgFindingsList");
        if (!list) return;
        fgFindingsAll = payload?.findings_summary?.findings_all || payload?.findings_summary?.findings || [];
        var summaryTxt = payload?.findings_summary?.summary_text || "No findings.";
        fgShowAllFindings = false;
        list.innerHTML = "";

        setFindingsMeta(payload);

        if (!fgFindingsAll.length) {
            list.textContent = summaryTxt;
            updateFindingsToggle();
            return;
        }

        var items = fgFindingsAll.slice(0, FG_DEFAULT_LIMIT);
        renderFindingsList(items);
        updateFindingsToggle();
    }

    function renderFindingsList(items) {
        var list = $("fgFindingsList");
        if (!list) return;
        list.innerHTML = "";

        items.forEach(function (item) {
            var row = document.createElement("div");
            row.className = "fg-finding-row";

            var txt = document.createElement("span");
            txt.textContent = item.summary || "Finding";
            row.appendChild(txt);

            if (item.box) {
                var btn = document.createElement("button");
                btn.textContent = "View area";
                btn.className = "fg-view-area-btn";
                btn.onclick = function () {
                    fgSelectedFinding = { page: item.page, categoryId: item.category_id, box: item.box };
                    updateShowInDocBtn();
                    openFgCrop(item.page, item.box, item.category_id);
                };
                row.appendChild(btn);
            }
            list.appendChild(row);
        });
    }

    function updateFindingsToggle() {
        var btn = $("fgToggleFindings");
        if (!btn) return;
        var hasMore = fgFindingsAll.length > FG_DEFAULT_LIMIT;
        btn.style.display = hasMore ? "inline-flex" : "none";
        btn.textContent = fgShowAllFindings ? "Show top 5" : "View all";
    }

    function updateShowInDocBtn() {
        var btn = $("fgShowInDoc");
        if (btn) btn.disabled = !fgSelectedFinding;
    }

    async function renderPreview(pageData) {
        var img = $("fgPreviewImage");
        var empty = $("fgPreviewEmpty");
        var overlay = $("fgPreviewOverlay");
        if (!img || !pageData) return;

        var url = pageData.image_url || pageData.preview_url;
        if (!url) return;
        var resolved = url.startsWith("http") ? url : FG_BASE + url;
        try {
            var objectUrl = await fgFetchObjectUrl(resolved);
            var prevUrl = img.dataset.fgObjectUrl;
            if (prevUrl) URL.revokeObjectURL(prevUrl);
            img.dataset.fgObjectUrl = objectUrl;

            img.onload = function () {
                if (empty) empty.style.display = "none";
                img.style.display = "block";
                renderOverlay(pageData, img, overlay);
            };
            img.onerror = function () {
                if (empty) { empty.textContent = "Preview failed to load."; empty.style.display = "block"; }
            };
            img.src = objectUrl;
        } catch (_) {
            if (empty) { empty.textContent = "Preview failed to load."; empty.style.display = "block"; }
        }
    }

    function renderOverlay(pageData, img, overlay) {
        if (!overlay || !img) return;
        overlay.innerHTML = "";
        var imgW = pageData.image_width || img.naturalWidth;
        var imgH = pageData.image_height || img.naturalHeight;
        if (!imgW || !imgH) return;

        var rect = img.getBoundingClientRect();
        var parent = img.parentElement.getBoundingClientRect();
        overlay.style.width = rect.width + "px";
        overlay.style.height = rect.height + "px";
        overlay.style.left = (rect.left - parent.left) + "px";
        overlay.style.top = (rect.top - parent.top) + "px";

        var focus = fgFocusedFinding && fgFocusedFinding.page === pageData.page_number ? fgFocusedFinding : null;

        function addBox(r, catId, isFocused) {
            var color = FG_CATEGORY_COLORS[catId] || "#f97316";
            var box = document.createElement("div");
            var borderW = isFocused ? "3px" : "2px";
            var bg = isFocused ? color + "44" : color + "22";
            box.style.cssText = "position:absolute; border:" + borderW + " solid " + color + "; background:" + bg + "; border-radius:2px;";
            box.style.left = (r.x / imgW * 100) + "%";
            box.style.top = (r.y / imgH * 100) + "%";
            box.style.width = (r.w / imgW * 100) + "%";
            box.style.height = (r.h / imgH * 100) + "%";
            overlay.appendChild(box);
        }

        if (focus && focus.box) {
            addBox(focus.box, focus.categoryId, true);
            return;
        }

        (pageData.regions || []).forEach(function (r) {
            addBox(r, r.category_id, false);
        });
    }

    async function openFgCrop(pageNum, box, catId) {
        var modal = $("fgCropModal");
        var cropImg = $("fgCropImage");
        var meta = $("fgCropMeta");
        if (!modal || !cropImg || !fgResults) return;

        var pageData = (fgResults.pages || []).find(function (p) { return p.page_number === pageNum; });
        var imgUrl = pageData?.image_url || pageData?.preview_url;
        if (!imgUrl) return;
        var resolved = imgUrl.startsWith("http") ? imgUrl : FG_BASE + imgUrl;

        try {
            var objectUrl = await fgFetchObjectUrl(resolved);
            var tmp = new Image();
            tmp.onload = function () {
                var canvas = document.createElement("canvas");
                canvas.width = box.w;
                canvas.height = box.h;
                var ctx = canvas.getContext("2d");
                ctx.drawImage(tmp, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
                cropImg.src = canvas.toDataURL("image/png");
                if (meta) meta.textContent = "Page " + pageNum + " · " + box.w + "×" + box.h + "px · " + (catId || "");
                modal.style.display = "flex";
                URL.revokeObjectURL(objectUrl);
            };
            tmp.onerror = function () {
                URL.revokeObjectURL(objectUrl);
                if (window.showToast) window.showToast("Preview Error", "Failed to load region preview", "error");
            };
            tmp.src = objectUrl;
        } catch (_) {
            if (window.showToast) window.showToast("Preview Error", "Failed to load region preview", "error");
        }
    }

    function uploadXHR(formData, onProgress, token) {
        return new Promise(function (resolve, reject) {
            var xhr = new XMLHttpRequest();
            xhr.open("POST", FG_BASE + "/jobs");
            if (token) {
                xhr.setRequestHeader("Authorization", "Bearer " + token);
            }
            xhr.upload.addEventListener("progress", function (e) {
                if (onProgress && e.lengthComputable) onProgress(e.loaded / e.total);
            });
            xhr.addEventListener("load", function () {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try { resolve(JSON.parse(xhr.responseText)); } catch (_) { reject(new Error("Invalid response")); }
                } else {
                    reject(new Error(xhr.responseText || "Upload failed"));
                }
            });
            xhr.addEventListener("error", function () { reject(new Error("Upload failed")); });
            xhr.send(formData);
        });
    }

    async function pollJob(jobId) {
        setProgress("Queued…", 10);
        var poll = setInterval(async function () {
            try {
                var res = await fgAuthFetch(FG_BASE + "/jobs/" + jobId);
                if (res.status === 401) {
                    clearInterval(poll);
                    setProgress("Token expired. Refresh and request a new token.", 0);
                    setBusy(false);
                    return;
                }
                if (!res.ok) return;
                var data = await res.json();
                var pct = (data.progress || 0.2) * 100;
                setProgress(data.status === "processing" ? "Analyzing…" : data.status, pct);

                if (data.status === "complete") {
                    clearInterval(poll);
                    setProgress("Complete", 100);
                    await loadResults(jobId);
                    setBusy(false);
                }
                if (data.status === "error") {
                    clearInterval(poll);
                    setProgress("Error: " + (data.message || "Pipeline error"), 0);
                    setBusy(false);
                }
            } catch (_) {}
        }, 2000);
    }

    async function loadResults(jobId) {
        try {
            var res = await fgAuthFetch(FG_BASE + "/jobs/" + jobId + "/results");
            if (res.status === 401) {
                setProgress("Token expired. Refresh and request a new token.", 0);
                return;
            }
            if (!res.ok) { setProgress("Failed to load results", 0); return; }
            fgResults = await res.json();
            fgResults.job_id = fgResults.job_id || jobId;
        } catch (_) {
            setProgress("Error fetching results", 0);
            return;
        }

        var total = fgResults.inference_seconds ?? null;
        var avg = fgResults.avg_inference_seconds ?? null;
        if (total == null && fgResults.result) total = fgResults.result.inference_seconds;
        if (avg == null && fgResults.result) avg = fgResults.result.avg_inference_seconds;
        setInference(total, avg);

        var summary = fgResults.category_summary || {};
        setTampered(summary);
        renderFindings(fgResults);
        showGrid(true);

        fgFindingsText = buildFindingsText(fgResults);
        var base = (fgResults.file_name || "document").replace(/\.[^/.]+$/, "");
        fgFindingsFileName = base + "_findings_" + new Date().toISOString().replace(/[:.]/g, "-") + ".txt";

        fgFocusedFinding = null;
        fgSelectedFinding = null;
        updateShowInDocBtn();

        var pages = fgResults.pages || [];
        if (pages.length) {
            fgPendingPage = pages[0];
            var toggleBtn = $("fgTogglePreview");
            if (toggleBtn) toggleBtn.textContent = fgPreviewVisible ? "Hide annotated document" : "Show annotated document";
            var overlayBtn = $("fgShowAllOverlays");
            if (overlayBtn) overlayBtn.disabled = true;
            if (fgPreviewVisible && fgPendingPage) {
                renderPreview(fgPendingPage);
            }
        }
    }

    function setBusy(busy) {
        fgBusy = busy;
        var btn = $("fgProcessBtn");
        if (btn) btn.disabled = busy;
        var loader = $("fgLoader");
        if (loader) loader.style.display = busy ? "inline-block" : "none";
    }

    // ── Window-exposed handlers ────────────────────────────────────────────────

    window.FG_fileChanged = function () {
        var input = $("fileForgery");
        if (!input) return;
        if (!input.files.length) {
            fgFile = null;
            return;
        }
        fgFile = input.files[0];
        var label = $("labelForgery");
        if (label) {
            var span = label.querySelector(".file-text");
            if (span) span.textContent = fgFile.name + " (" + fmtBytes(fgFile.size) + ")";
        }
    };

    window.FG_process = async function () {
        if (fgBusy) return;
        if (!fgFile) {
            if (window.showToast) window.showToast("No File", "Please select a document first.", "warn");
            return;
        }
        if (fgFile.size > FG_MAX_UPLOAD) {
            if (window.showToast) window.showToast("Too Large", "File exceeds 25 MB limit.", "error");
            return;
        }

        setBusy(true);
        fgResults = null;
        showGrid(true);
        setTamperedNeutral("Analyzing document...");
        setInference(null);
        setProgress("Uploading…", 2);
        var findings = $("fgFindingsList");
        if (findings) findings.textContent = "Processing...";
        var empty = $("fgPreviewEmpty");
        if (empty) empty.textContent = "Annotated preview will appear here.";
        var img = $("fgPreviewImage");
        if (img) img.style.display = "none";

        var form = new FormData();
        form.append("file", fgFile);
        form.append("ocr_enabled", "true");

        var token = await fgEnsureToken();
        if (!token) {
            setProgress("Authentication failed", 0);
            setBusy(false);
            if (window.showToast) window.showToast("Auth Error", "Could not obtain a demo token.", "error");
            return;
        }

        try {
            var data = await uploadXHR(form, function (p) {
                setProgress("Uploading " + Math.round(p * 100) + "%", Math.min(85, p * 85));
            }, token);
            fgJobId = data.job_id;
            setProgress("Queued", 90);
            pollJob(fgJobId);
        } catch (err) {
            setProgress("Upload failed", 0);
            setBusy(false);
            if (window.showToast) window.showToast("Upload Failed", err.message || "Could not upload file.", "error");
        }
    };

    window.FG_copyFindings = async function () {
        if (!fgFindingsText) return;
        try {
            await navigator.clipboard.writeText(fgFindingsText);
            if (window.showToast) window.showToast("Copied", "Findings copied to clipboard.", "info", 2000);
        } catch (_) {
            if (window.showToast) window.showToast("Copy Failed", "Could not copy to clipboard.", "error");
        }
    };

    window.FG_downloadFindings = function () {
        if (!fgFindingsText) return;
        var blob = new Blob([fgFindingsText], { type: "text/plain" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = fgFindingsFileName || "findings.txt";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    };

    window.FG_toggleFindings = function () {
        if (!fgFindingsAll.length) return;
        fgShowAllFindings = !fgShowAllFindings;
        var items = fgShowAllFindings ? fgFindingsAll : fgFindingsAll.slice(0, FG_DEFAULT_LIMIT);
        renderFindingsList(items);
        updateFindingsToggle();
    };

    window.FG_togglePreview = function () {
        var viewer = $("fgPreviewViewer");
        var btn = $("fgTogglePreview");
        if (!viewer) return;
        fgPreviewVisible = !fgPreviewVisible;
        viewer.style.display = fgPreviewVisible ? "block" : "none";
        if (btn) btn.textContent = fgPreviewVisible ? "Hide annotated document" : "Show annotated document";
        if (fgPreviewVisible && fgPendingPage) {
            renderPreview(fgPendingPage);
        }
    };

    window.FG_showAllOverlays = function () {
        if (!fgFocusedFinding) return;
        fgFocusedFinding = null;
        if (fgPendingPage) {
            renderOverlay(fgPendingPage, $("fgPreviewImage"), $("fgPreviewOverlay"));
        }
        var btn = $("fgShowAllOverlays");
        if (btn) btn.disabled = true;
        if (window.showToast) window.showToast("Overlays", "Showing all overlays", "info", 2000);
    };

    window.FG_showInDocument = function () {
        if (!fgSelectedFinding || !fgResults) return;
        var pageData = (fgResults.pages || []).find(function (p) { return p.page_number === fgSelectedFinding.page; });
        if (!pageData) return;
        fgFocusedFinding = fgSelectedFinding;
        fgPendingPage = pageData;
        var overlayBtn = $("fgShowAllOverlays");
        if (overlayBtn) overlayBtn.disabled = false;

        if (!fgPreviewVisible) {
            window.FG_togglePreview();
        } else {
            renderPreview(pageData);
        }

        window.FG_closeCropModal();
        if (window.showToast) window.showToast("Focus", "Showing selected area in document", "info", 2000);
    };

    window.FG_closeCropModal = function () {
        var modal = $("fgCropModal");
        if (modal) modal.style.display = "none";
        var cropImg = $("fgCropImage");
        if (cropImg) cropImg.removeAttribute("src");
        fgSelectedFinding = null;
        updateShowInDocBtn();
    };

    window.FG_init = function () {
        const landing = document.getElementById('fg-landing-view');
        const interactive = document.getElementById('fg-interactive-view');
        if (landing) landing.style.display = 'block';
        if (interactive) interactive.style.display = 'none';
    };

    window.FG_launchService = function () {
        const landing = document.getElementById('fg-landing-view');
        const interactive = document.getElementById('fg-interactive-view');
        if (landing) landing.style.display = 'none';
        if (interactive) {
            interactive.style.display = 'block';
            const firstBtn = interactive.querySelector('.sub-tab-btn');
            if (firstBtn) {
                firstBtn.click();
            }
        }
    };

    window.FG_handleFileChange = function () {
        if (window.FG_fileChanged) {
            window.FG_fileChanged();
        }
        const input = document.getElementById('fileForgery');
        const dropzone = document.getElementById('fgDropzone');
        const card = document.getElementById('fgFileCard');
        const nameEl = document.getElementById('fgCardFileName');
        const sizeEl = document.getElementById('fgCardFileSize');
        const btn = document.getElementById('fgProcessBtn');
        const fileIcon = document.getElementById('fgFileIcon');
        
        if (input && input.files && input.files.length > 0) {
            const file = input.files[0];
            if (nameEl) nameEl.textContent = file.name;
            if (sizeEl) {
                const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
                sizeEl.textContent = sizeMB + " MB";
            }
            if (fileIcon) {
                const ext = file.name.split('.').pop().toLowerCase();
                if (ext === 'pdf') {
                    fileIcon.className = 'far fa-file-pdf fg-file-icon';
                } else if (['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'webp'].includes(ext)) {
                    fileIcon.className = 'far fa-file-image fg-file-icon';
                } else {
                    fileIcon.className = 'far fa-file fg-file-icon';
                }
            }
            if (dropzone) dropzone.style.display = 'none';
            if (card) card.style.display = 'flex';
            if (btn) btn.removeAttribute('disabled');
        }
    };

    window.FG_removeFile = function (e) {
        if (e) e.stopPropagation();
        const input = document.getElementById('fileForgery');
        const dropzone = document.getElementById('fgDropzone');
        const card = document.getElementById('fgFileCard');
        const btn = document.getElementById('fgProcessBtn');
        
        if (input) {
            input.value = '';
            if (window.FG_fileChanged) {
                window.FG_fileChanged();
            }
        }
        if (dropzone) dropzone.style.display = 'flex';
        if (card) card.style.display = 'none';
        if (btn) btn.setAttribute('disabled', 'true');
        
        const resultsSec = document.getElementById('fgResultsGrid');
        if (resultsSec) resultsSec.style.display = 'none';
        const tamperedFlag = document.getElementById('fgTamperedFlag');
        if (tamperedFlag) {
            tamperedFlag.className = 'fg-tampered-flag fg-tampered-neutral';
            tamperedFlag.innerHTML = '<i class="fas fa-hourglass-half"></i> Tampered: <strong>-</strong> Awaiting analysis.';
        }
        const progressSection = document.getElementById('fgProgressSection');
        if (progressSection) progressSection.style.display = 'none';
    };

})();
