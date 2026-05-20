(function () {
    "use strict";

    const FG_CATEGORY_COLORS = {
        C1: "#f97316", C2: "#f59e0b", C3: "#22c55e", C4: "#ef4444",
        C5: "#0ea5e9", C6: "#6366f1", C7: "#14b8a6", C8: "#1f2937",
        C9: "#e11d48", C10: "#9ca3af"
    };
    const FG_MAX_UPLOAD = 25 * 1024 * 1024;
    const FG_LOCAL = "http://localhost:8004";
    const FG_BASE = window.location.hostname === "localhost"
        ? FG_LOCAL
        : "/forgensic";

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

    function renderPreview(pageData) {
        var img = $("fgPreviewImage");
        var empty = $("fgPreviewEmpty");
        var overlay = $("fgPreviewOverlay");
        if (!img || !pageData) return;

        var url = pageData.image_url || pageData.preview_url;
        if (!url) return;
        var resolved = url.startsWith("http") ? url : FG_BASE + url;

        img.onload = function () {
            if (empty) empty.style.display = "none";
            img.style.display = "block";
            renderOverlay(pageData, img, overlay);
        };
        img.onerror = function () {
            if (empty) { empty.textContent = "Preview failed to load."; empty.style.display = "block"; }
        };
        img.src = resolved;
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

    function openFgCrop(pageNum, box, catId) {
        var modal = $("fgCropModal");
        var cropImg = $("fgCropImage");
        var meta = $("fgCropMeta");
        if (!modal || !cropImg || !fgResults) return;

        var pageData = (fgResults.pages || []).find(function (p) { return p.page_number === pageNum; });
        var imgUrl = pageData?.image_url || pageData?.preview_url;
        if (!imgUrl) return;
        var resolved = imgUrl.startsWith("http") ? imgUrl : FG_BASE + imgUrl;

        var tmp = new Image();
        tmp.crossOrigin = "anonymous";
        tmp.onload = function () {
            var canvas = document.createElement("canvas");
            canvas.width = box.w;
            canvas.height = box.h;
            var ctx = canvas.getContext("2d");
            ctx.drawImage(tmp, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
            cropImg.src = canvas.toDataURL("image/png");
            if (meta) meta.textContent = "Page " + pageNum + " · " + box.w + "×" + box.h + "px · " + (catId || "");
            modal.style.display = "flex";
        };
        tmp.onerror = function () {
            if (window.showToast) window.showToast("Preview Error", "Failed to load region preview", "error");
        };
        tmp.src = resolved;
    }

    function uploadXHR(formData, onProgress) {
        return new Promise(function (resolve, reject) {
            var xhr = new XMLHttpRequest();
            xhr.open("POST", FG_BASE + "/jobs");
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
                var res = await fetch(FG_BASE + "/jobs/" + jobId);
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
            var res = await fetch(FG_BASE + "/jobs/" + jobId + "/results");
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
        if (!input || !input.files.length) return;
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

        try {
            var data = await uploadXHR(form, function (p) {
                setProgress("Uploading " + Math.round(p * 100) + "%", Math.min(85, p * 85));
            });
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

})();
