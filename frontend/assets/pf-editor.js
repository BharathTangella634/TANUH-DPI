/**
 * pf-editor.js — Redaction editor for Privacy Filter.
 *
 * Architecture:
 *   - We maintain TWO independent sets of boxes: original (left) and redacted (right).
 *   - Left Panel (Original): Starts with 0 boxes. Edits are saved to `_boxesLeft`.
 *   - Right Panel (Redacted): Starts with AI boxes. Edits are saved to `_boxesRight`.
 *   - Editor canvas ALWAYS uses the pristine original unredacted image so text remains readable during editing.
 *   - Updates the corresponding main dashboard preview panel immediately upon applying edits.
 *   - Sleek, high-fidelity dark-mode Figma-style UI with grid textures and micro-animations.
 */
(function () {
  "use strict";

  const pfQ = (id) => document.getElementById(id);
  const BASE = () => window._PF_BASE || "/privacy-filter";
  const TOKEN = () => (window._PF_getToken ? window._PF_getToken() : "");
  const AUTH = () => { const t = TOKEN(); return t ? { Authorization: `Bearer ${t}` } : {}; };

  // ── Persistent State (survives editor open/close) ──────────────────────
  let _boxesLeft = [];       // [{id, page, x, y, w, h, label, source}]
  let _boxesRight = [];      // [{id, page, x, y, w, h, label, source}]
  let _boxId = 0;
  let _origPages = null;     // Page data for original image (used as editor canvas)
  let _origKey = null;       // Key for original unredacted file
  let _initialized = false;  // Tracks whether AI boxes have been loaded into right panel

  // ── Editor Session State ───────────────────────────────────────────────
  let _editorMode = null;    // "original" or "redacted"
  let _active = false;
  let _boxes = [];           // Active editing copy of the boxes
  let _zoom = 1;
  let _tool = "draw";
  let _undoStack = [];
  let _drawing = false;
  let _drawStart = null;
  let _drawRect = null;
  let _panState = null;

  // ── Colors ─────────────────────────────────────────────────────────────
  const CLR = {
    accent: "#14868C",
    accentDark: "#0e6a6f",
    green: "#059669",
    greenHover: "#047857",
    red: "#ef4444",
    purple: "#8b5cf6",
    purpleBg: "rgba(139,92,246,0.15)",
    aiBg: "rgba(239,68,68,0.15)",
    aiBorder: "rgba(239,68,68,0.85)",
    userBg: "rgba(139,92,246,0.15)",
    userBorder: "rgba(139,92,246,0.85)",
    toolbar: "#1e293b",
    surface: "#0f172a",
    muted: "#94a3b8",
    dark: "#0f172a",
    border: "#334155",
    lightBorder: "#e2e8f0",
  };

  // ── Reset on new file upload ───────────────────────────────────────────
  window.PF_resetEditorState = function () {
    _boxesLeft = [];
    _boxesRight = [];
    _boxId = 0;
    _origPages = null;
    _origKey = null;
    _initialized = false;
  };

  // ── Load Previews ──────────────────────────────────────────────────────
  window.PF_loadPreview = async function (kind, key) {
    const viewport = pfQ(kind === "original" ? "pfPreviewOriginal" : "pfPreviewRedacted");
    const editBtn = pfQ(kind === "original" ? "pfEditOriginalBtn" : "pfEditRedactedBtn");
    if (!viewport) return;

    viewport.innerHTML = _placeholder("fa-spinner fa-spin", "Rendering preview...");

    try {
      // If it contains __redacted, it is always in the redacted directory
      const apiKind = key.includes("__redacted") ? "redacted" : (kind === "original" ? "uploads" : "redacted");
      const r = await fetch(`${BASE()}/api/render-pages/${apiKind}/${key}`, { headers: AUTH(), signal: AbortSignal.timeout(30000) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();

      if (data.text_only) {
        viewport.innerHTML = `<pre style="width:100%;padding:12px;margin:0;white-space:pre-wrap;font-size:0.82rem;color:#334155;text-align:left;max-height:460px;overflow:auto;">${_esc(data.text || "(empty)")}</pre>`;
        if (editBtn) editBtn.disabled = true;
        return;
      }

      _showPageImages(viewport, data.pages);

      // We only store the original untouched pages as our canvas base
      if (kind === "original" && !_origPages) {
        _origPages = data.pages;
        _origKey = key;
      }

      viewport.dataset.kind = kind;
      if (editBtn) editBtn.disabled = false;
    } catch (e) {
      viewport.innerHTML = _placeholder("fa-exclamation-triangle", `Preview failed: ${_esc(e.message)}`, "#ef4444");
      if (editBtn) editBtn.disabled = true;
    }
  };

  // After apply, update the corresponding preview directly with returned pages
  window.PF_updatePreview = function (kind, pages) {
    const viewport = pfQ(kind === "original" ? "pfPreviewOriginal" : "pfPreviewRedacted");
    if (!viewport || !pages) return;
    _showPageImages(viewport, pages);
    viewport.dataset.kind = kind;
    const editBtn = pfQ(kind === "original" ? "pfEditOriginalBtn" : "pfEditRedactedBtn");
    if (editBtn) editBtn.disabled = false;
  };

  window.PF_updateRedactedPreview = function (pages) {
    window.PF_updatePreview("redacted", pages);
  };

  function _showPageImages(viewport, pages) {
    viewport.innerHTML = "";
    for (const pg of pages) {
      const img = document.createElement("img");
      img.src = `${BASE()}${pg.url}?t=${Date.now()}`;
      img.alt = `Page ${pg.page + 1}`;
      img.loading = "lazy";
      img.style.cssText = "max-width:100%;height:auto;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.12);margin-bottom:12px;display:block;";
      viewport.appendChild(img);
    }
  }

  // ── Open Editor ────────────────────────────────────────────────────────
  window.PF_openEditor = function (kind) {
    if (!_origPages || !_origPages.length) {
      alert("Preview not ready. Please wait for processing to complete.");
      return;
    }

    _active = true;
    _zoom = 1;
    _tool = "draw";
    _undoStack = [];
    _editorMode = kind; // Keep track of the active panel being edited

    if (kind === "original") {
      _boxes = _boxesLeft.map(b => ({ ...b }));
    } else {
      if (!_initialized) {
        _boxesRight = (window._PF_aiBoxes || []).map(b => ({
          ...b,
          id: ++_boxId,
          source: b.source || "ai"
        }));
        _initialized = true;
      }
      _boxes = _boxesRight.map(b => ({ ...b }));
    }

    _buildEditorDOM();
    document.body.style.overflow = "hidden";
  };

  // ── Build Editor DOM ───────────────────────────────────────────────────
  function _buildEditorDOM() {
    let old = pfQ("pfe_root");
    if (old) old.remove();

    const el = document.createElement("div");
    el.id = "pfe_root";
    el.style.cssText = `
      position:fixed; top:0; left:0; width:100vw; height:100vh; z-index:999999;
      background:radial-gradient(circle at center, rgba(15, 23, 42, 0.97) 0%, rgba(8, 12, 24, 0.99) 100%);
      backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
      display:flex; align-items:center; justify-content:center;
      font-family:'Inter','Segoe UI',system-ui,sans-serif;
    `;

    const titleStr = _editorMode === "original" ? "Edit Left (Original)" : "Edit Right (Redacted)";
    const tagColor = _editorMode === "original" ? "#38bdf8" : "#a78bfa";

    el.innerHTML = `
    <div style="width:98vw;height:96vh;background:#ffffff;border-radius:20px;border: 1px solid rgba(255, 255, 255, 0.1);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 40px 120px rgba(0,0,0,0.8);">

      <!-- ═══ TOOLBAR ═══ -->
      <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 24px;background:linear-gradient(to bottom, #1e293b, #0f172a);border-bottom:1px solid #334155;flex-shrink:0;gap:16px;">

        <!-- Left: Title Block -->
        <div style="display:flex;align-items:center;gap:12px;">
          <div style="background:linear-gradient(135deg,#06b6d4,#0891b2);padding:6px 14px;border-radius:10px;display:flex;align-items:center;gap:8px;box-shadow:0 0 12px rgba(6,182,212,0.3);">
            <i class="fas fa-user-shield" style="color:#fff;font-size:0.8rem;"></i>
            <span style="font-weight:800;font-size:0.85rem;color:#fff;letter-spacing:0.5px;text-transform:uppercase;">PII Redactor</span>
          </div>
          <span style="font-size:0.75rem;font-weight:600;color:${tagColor};background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);padding:5px 12px;border-radius:20px;display:inline-flex;align-items:center;gap:6px;">
            <i class="fas fa-edit"></i>${titleStr}
          </span>
        </div>

        <!-- Center: Figma-style Control Clusters -->
        <div style="display:flex;align-items:center;gap:12px;">
          <!-- Zoom cluster -->
          <div style="display:inline-flex;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:3px;align-items:center;">
            ${_tbtn("pfe_zout","fa-minus","Zoom Out")}
            <span id="pfe_zlbl" style="font-size:0.75rem;color:#94a3b8;min-width:48px;text-align:center;font-weight:700;font-variant-numeric:tabular-nums;user-select:none;">100%</span>
            ${_tbtn("pfe_zin","fa-plus","Zoom In")}
            ${_tbtn("pfe_zfit","fa-expand","Fit View")}
          </div>

          <!-- Drawing tools cluster -->
          <div style="display:inline-flex;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:3px;align-items:center;gap:2px;">
            ${_tbtn("pfe_tdraw","fa-vector-square","Draw Mode (D)", true)}
            ${_tbtn("pfe_tpan","fa-hand-paper","Pan Mode (Space)")}
          </div>

          <!-- History / Edit tools cluster -->
          <div style="display:inline-flex;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:3px;align-items:center;gap:2px;">
            ${_tbtn("pfe_undo","fa-undo","Undo (Ctrl+Z)")}
            ${_tbtn("pfe_clear","fa-trash","Clear All")}
          </div>
        </div>

        <!-- Right: Actions with beautiful gradients -->
        <div style="display:flex;align-items:center;gap:8px;">
          <button id="pfe_apply" style="display:inline-flex;align-items:center;gap:6px;padding:9px 24px;border:none;border-radius:10px;background:linear-gradient(135deg,#059669,#10b981);color:#fff;font-family:inherit;font-size:0.82rem;font-weight:700;cursor:pointer;box-shadow:0 4px 14px rgba(16,185,129,0.3);transition:all 0.2s;">
            <i class="fas fa-check-circle"></i> Apply Changes
          </button>
          <button id="pfe_cancel" style="display:inline-flex;align-items:center;gap:5px;padding:9px 18px;border:1px solid #334155;border-radius:10px;background:transparent;color:#94a3b8;font-family:inherit;font-size:0.8rem;font-weight:600;cursor:pointer;transition:all 0.2s;">
            <i class="fas fa-times"></i> Cancel
          </button>
        </div>
      </div>

      <!-- ═══ BODY ═══ -->
      <div style="display:flex;flex:1;overflow:hidden;background:#0f172a;">

        <!-- Grid dot textured canvas area -->
        <div id="pfe_area" style="flex:1;overflow:hidden;position:relative;background-color:#0b0f19;background-image:radial-gradient(rgba(255,255,255,0.06) 1px, transparent 1px);background-size:20px 20px;">
          <!-- overflow:auto + layout-scaled pages → scrollbars span the full
               zoomed extent so high-res images can be panned to every edge.
               width:max-content lets the row grow with zoom; min-width:100% +
               margin auto keeps content centred when smaller than the viewport. -->
          <div id="pfe_scroll" style="width:100%;height:100%;overflow:auto;cursor:crosshair;">
            <div id="pfe_pages" style="display:flex;flex-direction:column;align-items:center;gap:24px;padding:40px;width:max-content;min-width:100%;margin:0 auto;box-sizing:border-box;"></div>
          </div>
        </div>

        <!-- Sidebar Panel -->
        <div style="width:290px;flex-shrink:0;background:#f8fafc;border-left:1px solid ${CLR.lightBorder};display:flex;flex-direction:column;box-shadow:-5px 0 25px rgba(0,0,0,0.03);">
          <div style="padding:16px 20px;border-bottom:1px solid #e2e8f0;background:linear-gradient(135deg,#f0fafb,#e6f7f8);display:flex;align-items:center;gap:10px;flex-shrink:0;">
            <i class="fas fa-layer-group" style="color:${CLR.accent};font-size:0.9rem;"></i>
            <span style="font-size:0.85rem;font-weight:800;color:${CLR.accentDark};letter-spacing:0.3px;">Redaction Layers</span>
            <span id="pfe_cnt" style="margin-left:auto;background:linear-gradient(135deg,#14868C,#0e6a6f);color:#fff;font-size:0.7rem;padding:3px 10px;border-radius:99px;font-weight:800;box-shadow:0 2px 6px rgba(20,134,140,0.25);">0</span>
          </div>
          <div id="pfe_list" style="flex:1;overflow-y:auto;padding:12px 14px;"></div>
          
          <!-- Instructions panel -->
          <div style="padding:14px 18px;border-top:1px solid #e2e8f0;background:#ffffff;flex-shrink:0;">
            <div style="font-size:0.7rem;color:${CLR.muted};line-height:1.6;">
              <div style="margin-bottom:6px;font-weight:700;color:${CLR.accentDark};">Quick Controls:</div>
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${CLR.red};"></span> AI detected redaction</div>
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${CLR.purple};"></span> User added redaction</div>
              <div>• Click on any overlay box or cross button to remove it</div>
              <div>• canvas background shows original text details</div>
            </div>
          </div>
        </div>
      </div>

      <!-- ═══ STATUSBAR ═══ -->
      <div style="padding:10px 24px;background:#f8fafc;border-top:1px solid ${CLR.lightBorder};font-size:0.72rem;color:#64748b;flex-shrink:0;display:flex;gap:24px;align-items:center;">
        ${_kbd("Drag")} Add Box &nbsp; 
        ${_kbd("Click")} Delete Box &nbsp; 
        ${_kbd("Ctrl + Scroll")} Zoom Canvas &nbsp; 
        ${_kbd("Space + Drag")} Pan Image &nbsp; 
        ${_kbd("Ctrl + Z")} Undo Action &nbsp; 
        ${_kbd("Esc")} Exit Editor
      </div>
    </div>`;

    document.body.appendChild(el);

    // Event wires
    pfQ("pfe_zout").onclick = () => _zoom_(Math.max(_zoom / 1.25, 0.1));
    pfQ("pfe_zin").onclick = () => _zoom_(Math.min(_zoom * 1.25, 5));
    pfQ("pfe_zfit").onclick = _fitZ;
    pfQ("pfe_tdraw").onclick = () => _setTool("draw");
    pfQ("pfe_tpan").onclick = () => _setTool("pan");
    pfQ("pfe_undo").onclick = _undo;
    pfQ("pfe_clear").onclick = _clearAll;
    pfQ("pfe_apply").onclick = _apply;
    pfQ("pfe_cancel").onclick = _close;

    // Hover listeners
    el.querySelectorAll("#pfe_tools button, #pfe_cancel").forEach(b => {
      b.onmouseenter = () => { if (!b.dataset.on) b.style.background = "#334155"; };
      b.onmouseleave = () => { if (!b.dataset.on) b.style.background = "transparent"; };
    });

    const applyBtn = pfQ("pfe_apply");
    applyBtn.onmouseenter = () => { applyBtn.style.transform = "translateY(-1px)"; applyBtn.style.boxShadow = "0 6px 20px rgba(16,185,129,0.45)"; applyBtn.style.background = `linear-gradient(135deg, ${CLR.greenHover}, #059669)`; };
    applyBtn.onmouseleave = () => { applyBtn.style.transform = ""; applyBtn.style.boxShadow = "0 4px 14px rgba(16,185,129,0.3)"; applyBtn.style.background = `linear-gradient(135deg, ${CLR.green}, #10b981)`; };

    _renderPages();
    _renderSidebar();
    requestAnimationFrame(_fitZ);

    pfQ("pfe_scroll").onwheel = (e) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const s = pfQ("pfe_scroll");
        const r = s.getBoundingClientRect();
        // Zoom toward the cursor so the point under the pointer stays put.
        _zoom_(_zoom * (e.deltaY > 0 ? 0.9 : 1.1),
               { x: e.clientX - r.left, y: e.clientY - r.top });
      }
      // Plain scroll (no modifier) falls through → normal pan via scrollbars.
    };
  }

  // HTML utilities
  function _tbtn(id, icon, title, active) {
    const bg = active ? "linear-gradient(135deg, #14868C, #0e6a6f)" : "transparent";
    const color = active ? "#ffffff" : "#94a3b8";
    return `<button id="${id}" ${active ? 'data-on="1"' : ''} style="display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border:none;border-radius:6px;background:${bg};color:${color};font-size:0.8rem;cursor:pointer;transition:all 0.15s ease;" title="${title}"><i class="fas ${icon}"></i></button>`;
  }
  
  function _kbd(k) { return `<kbd style="background:#e2e8f0;border:1px solid #cbd5e1;padding:2px 7px;border-radius:4px;font-size:0.66rem;font-family:inherit;font-weight:700;color:#334155;box-shadow:0 1px 1px rgba(0,0,0,0.05);">${k}</kbd>`; }
  
  function _placeholder(icon, text, color) {
    return `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:300px;color:${color || CLR.muted};gap:10px;">
      <i class="fas ${icon}" style="font-size:2rem;"></i><span style="font-size:0.85rem;font-weight:600;">${text}</span></div>`;
  }

  // ── Close Editor ───────────────────────────────────────────────────────
  function _close() {
    const r = pfQ("pfe_root");
    if (r) r.remove();
    document.body.style.overflow = "";
    _active = false;
  }
  window.PF_editorClose = _close;

  // ── Zoom Controls (layout-based — scrollbars track the zoomed size) ──────
  // We resize the actual page/box elements instead of using CSS transform, so
  // the scroll container's scrollable area equals the zoomed content. That lets
  // the user scroll/pan to every edge of a high-resolution image at any zoom.
  function _zoom_(z, anchor) {
    z = Math.max(0.1, Math.min(6, z));
    const s = pfQ("pfe_scroll");

    // Capture the content point currently under the anchor (viewport centre by
    // default) so we can keep it stable across the zoom change.
    let ax = 0.5, ay = 0.5, beforeX = 0, beforeY = 0;
    if (s) {
      ax = anchor ? anchor.x : s.clientWidth / 2;
      ay = anchor ? anchor.y : s.clientHeight / 2;
      beforeX = (s.scrollLeft + ax) / _zoom;   // content coord under anchor
      beforeY = (s.scrollTop + ay) / _zoom;
    }

    _zoom = z;
    _applyZoomLayout();

    const l = pfQ("pfe_zlbl");
    if (l) l.textContent = `${Math.round(_zoom * 100)}%`;

    // Re-anchor the same content point under the cursor/centre after rescale.
    if (s) {
      s.scrollLeft = beforeX * _zoom - ax;
      s.scrollTop = beforeY * _zoom - ay;
    }
  }

  // Resize existing page wrappers, images and box overlays to the current zoom
  // WITHOUT recreating <img> elements (no network re-fetch on every zoom tick).
  function _applyZoomLayout() {
    const c = pfQ("pfe_pages");
    if (!c) return;
    Array.from(c.children).forEach((wrap, idx) => {
      const pg = _origPages && _origPages[idx];
      if (!pg) return;
      const sw = Math.round(pg.width * _zoom);
      const sh = Math.round(pg.height * _zoom);
      wrap.style.width = sw + "px";
      wrap.style.height = sh + "px";
      const img = wrap.querySelector("img");
      if (img) { img.width = sw; img.height = sh; img.style.width = sw + "px"; img.style.height = sh + "px"; }
    });
    _renderBoxes();
  }

  function _fitZ() {
    const a = pfQ("pfe_area");
    if (!a || !_origPages || !_origPages.length) { _zoom_(1); return; }
    // Fit the widest page to the available width (minus padding/scrollbar).
    const maxW = Math.max(..._origPages.map(p => p.width));
    _zoom_(Math.min(2, (a.clientWidth - 96) / maxW));
  }

  // ── Toggle Tool ────────────────────────────────────────────────────────
  function _setTool(t) {
    _tool = t;
    const d = pfQ("pfe_tdraw"), p = pfQ("pfe_tpan"), s = pfQ("pfe_scroll");
    [d, p].forEach(b => { if (b) { b.style.background = "transparent"; b.style.color = "#94a3b8"; b.dataset.on = ""; } });
    const active = t === "draw" ? d : p;
    if (active) { active.style.background = "linear-gradient(135deg, #14868C, #0e6a6f)"; active.style.color = "#ffffff"; active.dataset.on = "1"; }
    if (s) s.style.cursor = t === "pan" ? "grab" : "crosshair";
  }

  // ── Undo Stack ─────────────────────────────────────────────────────────
  function _push() { _undoStack.push(_boxes.map(b => ({ ...b }))); if (_undoStack.length > 50) _undoStack.shift(); }
  
  function _undo() {
    if (!_undoStack.length) return;
    _boxes = _undoStack.pop();
    _renderBoxes();
    _renderSidebar();
  }
  
  function _clearAll() {
    if (!_boxes.length) return;
    _push();
    _boxes = [];
    _renderBoxes();
    _renderSidebar();
  }
  window.PF_editorUndo = _undo;

  // ── Render pages in editor canvas ──────────────────────────────────────
  function _renderPages() {
    const c = pfQ("pfe_pages");
    if (!c || !_origPages) return;
    c.innerHTML = "";

    _origPages.forEach((pg, idx) => {
      const sw = Math.round(pg.width * _zoom);
      const sh = Math.round(pg.height * _zoom);
      const wrap = document.createElement("div");
      wrap.dataset.page = idx;
      wrap.style.cssText = `position:relative;width:${sw}px;height:${sh}px;background:#ffffff;box-shadow:0 12px 40px rgba(0,0,0,0.6);border-radius:8px;overflow:hidden;line-height:0;flex-shrink:0;`;

      const img = document.createElement("img");
      img.src = `${BASE()}${pg.url}`;
      img.width = sw; img.height = sh;
      img.draggable = false;
      img.style.cssText = `display:block;max-width:none;user-select:none;width:${sw}px;height:${sh}px;`;
      wrap.appendChild(img);

      const ov = document.createElement("div");
      ov.style.cssText = "position:absolute;top:0;left:0;right:0;bottom:0;z-index:1;";
      wrap.appendChild(ov);
      _mouse(ov, idx);

      c.appendChild(wrap);
    });
    _renderBoxes();
  }

  // ── Mouse events on editor canvas ──────────────────────────────────────
  function _mouse(ov, pgIdx) {
    const xy = (e) => { const r = ov.parentElement.getBoundingClientRect(); return { x: (e.clientX - r.left) / _zoom, y: (e.clientY - r.top) / _zoom }; };

    ov.onmousedown = (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const { x, y } = xy(e);

      if (_tool === "pan") {
        const s = pfQ("pfe_scroll");
        _panState = { sx: e.clientX, sy: e.clientY, el: s, sl: s.scrollLeft, st: s.scrollTop };
        s.style.cursor = "grabbing";
        return;
      }

      // Check click on box to remove it
      const hit = _hit(pgIdx, x, y);
      if (hit) {
        _push();
        _boxes = _boxes.filter(b => b.id !== hit.id);
        _renderBoxes();
        _renderSidebar();
        return;
      }

      // Draw box start. Coords (x,y) are in natural px; the live rectangle is
      // drawn inside the scaled page wrapper, so multiply by _zoom for display.
      _drawing = true;
      _drawStart = { page: pgIdx, x, y };
      const d = document.createElement("div");
      d.id = "pfe_dr";
      d.style.cssText = `position:absolute;z-index:10;pointer-events:none;border:2.5px dashed ${CLR.purple};background:${CLR.purpleBg};border-radius:3px;left:${x * _zoom}px;top:${y * _zoom}px;width:0;height:0;box-shadow:0 0 12px rgba(139,92,246,0.3);`;
      ov.parentElement.appendChild(d);
      _drawRect = d;
    };

    ov.onmousemove = (e) => {
      if (_panState) { _panState.el.scrollLeft = _panState.sl - (e.clientX - _panState.sx); _panState.el.scrollTop = _panState.st - (e.clientY - _panState.sy); return; }
      if (!_drawing || !_drawRect) return;
      const { x: cx, y: cy } = xy(e);
      const z = _zoom;
      _drawRect.style.left = Math.min(_drawStart.x, cx) * z + "px";
      _drawRect.style.top = Math.min(_drawStart.y, cy) * z + "px";
      _drawRect.style.width = Math.abs(cx - _drawStart.x) * z + "px";
      _drawRect.style.height = Math.abs(cy - _drawStart.y) * z + "px";
    };

    const done = (e) => {
      if (_panState) { const s = pfQ("pfe_scroll"); if (s) s.style.cursor = _tool === "pan" ? "grab" : "crosshair"; _panState = null; return; }
      if (!_drawing) return;
      _drawing = false;
      const { x: cx, y: cy } = xy(e);
      const bx = Math.min(_drawStart.x, cx), by = Math.min(_drawStart.y, cy);
      const bw = Math.abs(cx - _drawStart.x), bh = Math.abs(cy - _drawStart.y);
      if (_drawRect) { _drawRect.remove(); _drawRect = null; }
      if (bw > 5 && bh > 5) {
        _push();
        _boxes.push({ id: ++_boxId, page: _drawStart.page, x: Math.round(bx), y: Math.round(by), w: Math.round(bw), h: Math.round(bh), label: "USER", source: "user" });
        _renderBoxes();
        _renderSidebar();
      }
      _drawStart = null;
    };
    ov.onmouseup = done;
    ov.onmouseleave = done;
  }

  function _hit(pg, x, y) {
    for (let i = _boxes.length - 1; i >= 0; i--) {
      const b = _boxes[i];
      if (b.page === pg && x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) return b;
    }
    return null;
  }

  // ── Render Box Overlays (looks redacted, but transparent on hover) ────
  function _renderBoxes() {
    document.querySelectorAll("[data-pfebox]").forEach(e => e.remove());
    const c = pfQ("pfe_pages");
    if (!c) return;
    const wraps = c.children;

    _boxes.forEach(box => {
      const w = wraps[box.page];
      if (!w) return;
      const isUser = box.source === "user";

      const el = document.createElement("div");
      el.setAttribute("data-pfebox", box.id);
      // Box coords are stored in NATURAL image pixels; scale to the current zoom.
      const z = _zoom;
      el.style.cssText = `
        position:absolute; z-index:2; cursor:pointer;
        left:${box.x * z}px; top:${box.y * z}px; width:${box.w * z}px; height:${box.h * z}px;
        background:rgba(15, 23, 42, 0.92); border:1.5px solid #000;
        border-radius:2px; transition:background 0.15s ease-in-out, border-color 0.15s ease-in-out;
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
      `;
      el.title = "Click to remove redaction";

      // Label (hidden by default, shown on hover/focus)
      const lbl = document.createElement("div");
      lbl.style.cssText = `
        position:absolute; top:-18px; left:-1px; font-size:9px; font-weight:700;
        color:#fff; background:${isUser ? CLR.purple : CLR.accent};
        padding:1px 8px; border-radius:4px 4px 0 0; white-space:nowrap;
        pointer-events:none; letter-spacing:0.4px; opacity: 0;
        transition: opacity 0.15s ease-in-out;
      `;
      lbl.textContent = isUser ? `USER` : (box.label || "AI").toUpperCase();
      el.appendChild(lbl);

      el.onmouseenter = () => {
        el.style.background = "rgba(15, 23, 42, 0.15)";
        el.style.borderColor = isUser ? CLR.purple : CLR.red;
        lbl.style.opacity = "1";
      };
      el.onmouseleave = () => {
        el.style.background = "rgba(15, 23, 42, 0.92)";
        el.style.borderColor = "#000";
        lbl.style.opacity = "0";
      };
      el.onclick = (e) => {
        e.stopPropagation();
        _push();
        _boxes = _boxes.filter(b => b.id !== box.id);
        _renderBoxes();
        _renderSidebar();
      };

      w.appendChild(el);
    });
  }

  // ── Render Sidebar Box List ────────────────────────────────────────────
  function _renderSidebar() {
    const list = pfQ("pfe_list");
    const cnt = pfQ("pfe_cnt");
    if (cnt) cnt.textContent = _boxes.length;
    if (!list) return;

    if (!_boxes.length) {
      list.innerHTML = `<div style="padding:36px 16px;text-align:center;color:${CLR.muted};line-height:1.7;">
        <i class="fas fa-draw-polygon" style="font-size:2.2rem;color:#d1d5db;display:block;margin-bottom:12px;"></i>
        <div style="font-size:0.82rem;font-weight:600;color:#64748b;margin-bottom:4px;">No boxes yet</div>
        <div style="font-size:0.72rem;">Click and drag on the image<br>to draw redaction areas</div></div>`;
      return;
    }

    list.innerHTML = "";
    _boxes.forEach(box => {
      const isUser = box.source === "user";
      const color = isUser ? CLR.purple : CLR.red;
      const row = document.createElement("div");
      row.style.cssText = `
        display:flex; align-items:center; justify-content:space-between;
        padding:10px 14px; margin-bottom:8px; border-radius:10px;
        border:1.5px solid #e2e8f0; border-left:4px solid ${color};
        background:#ffffff; box-shadow:0 2px 4px rgba(0,0,0,0.02);
        transition:all 0.15s ease; cursor:pointer;
      `;

      row.onmouseenter = () => {
        row.style.transform = "translateY(-1px)";
        row.style.boxShadow = "0 4px 10px rgba(0,0,0,0.06)";
        row.style.borderColor = color;
        const b = document.querySelector(`[data-pfebox="${box.id}"]`);
        if (b) { b.style.borderWidth = "3px"; b.style.background = isUser ? "rgba(139,92,246,0.15)" : "rgba(239,68,68,0.15)"; b.style.borderColor = color; }
      };
      
      row.onmouseleave = () => {
        row.style.transform = "";
        row.style.boxShadow = "0 2px 4px rgba(0,0,0,0.02)";
        row.style.borderColor = "#e2e8f0";
        row.style.background = "#ffffff";
        const b = document.querySelector(`[data-pfebox="${box.id}"]`);
        if (b) { b.style.borderWidth = "1.5px"; b.style.background = "rgba(15, 23, 42, 0.92)"; b.style.borderColor = "#000"; }
      };

      row.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:3px;">
          <div style="display:flex;align-items:center;gap:7px;">
            <span style="font-size:0.74rem;font-weight:700;color:${CLR.dark};">#${box.id}</span>
            <span style="font-size:0.6rem;font-weight:700;color:#fff;background:${color};padding:2px 7px;border-radius:4px;text-transform:uppercase;letter-spacing:0.5px;">${isUser ? "User" : "AI"}</span>
          </div>
          <span style="font-size:0.64rem;color:${CLR.muted};font-family:'SF Mono',Consolas,monospace;">P${box.page + 1} · ${box.w}×${box.h} at (${box.x}, ${box.y})</span>
        </div>
        <button style="background:none;border:1px solid transparent;cursor:pointer;color:#cbd5e1;padding:6px 8px;border-radius:6px;font-size:0.8rem;transition:all 0.12s;" title="Remove this box">
          <i class="fas fa-times-circle"></i>
        </button>`;

      const rm = row.querySelector("button");
      rm.onmouseenter = () => { rm.style.color = CLR.red; rm.style.background = "#fee2e2"; rm.style.borderColor = "#fecaca"; };
      rm.onmouseleave = () => { rm.style.color = "#cbd5e1"; rm.style.background = "none"; rm.style.borderColor = "transparent"; };
      rm.onclick = (e) => { e.stopPropagation(); _push(); _boxes = _boxes.filter(b => b.id !== box.id); _renderBoxes(); _renderSidebar(); };

      list.appendChild(row);
    });
  }

  // ── Apply Changes ──────────────────────────────────────────────────────
  async function _apply() {
    const btn = pfQ("pfe_apply");
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Applying...'; btn.style.opacity = "0.7"; }

    try {
      const pg = _origPages[0] || { width: 1, height: 1 };
      const body = {
        job_id: window._PF_jobId || "",
        source_key: _origKey || window._PF_uploadKey || "",
        boxes: _boxes.map(b => ({ page: b.page, x: b.x, y: b.y, w: b.w, h: b.h })),
        image_width: pg.width,
        image_height: pg.height,
        panel: _editorMode,
      };

      const r = await fetch(`${BASE()}/api/apply-redactions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...AUTH() },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(60000),
      });
      if (!r.ok) throw new Error(await r.text().catch(() => `HTTP ${r.status}`));
      const data = await r.json();

      // Update persistent box copy, download URL, and dashboard preview panel
      if (_editorMode === "original") {
        _boxesLeft = _boxes.map(b => ({ ...b }));
        if (data.redacted_url) {
          window._PF_urls = window._PF_urls || {};
          window._PF_urls.original = `${BASE()}${data.redacted_url}`;
        }
        if (data.preview_pages && data.preview_pages.length) {
          window.PF_updatePreview("original", data.preview_pages);
        } else if (data.redacted_key) {
          await window.PF_loadPreview("original", data.redacted_key);
        }
        const dlBtn = pfQ("pfDlOriginal");
        if (dlBtn) dlBtn.disabled = false;
      } else {
        _boxesRight = _boxes.map(b => ({ ...b }));
        if (data.redacted_url) {
          window._PF_urls = window._PF_urls || {};
          window._PF_urls.redacted = `${BASE()}${data.redacted_url}`;
        }
        if (data.preview_pages && data.preview_pages.length) {
          window.PF_updatePreview("redacted", data.preview_pages);
        } else if (data.redacted_key) {
          await window.PF_loadPreview("redacted", data.redacted_key);
        }
        const dlBtn = pfQ("pfDlRedacted");
        if (dlBtn) dlBtn.disabled = false;
      }

      _close();

      if (window.showToast) window.showToast("Applied", `${_boxes.length} redaction${_boxes.length !== 1 ? "s" : ""} applied.`, "info", 3000);
    } catch (e) {
      alert(`Apply failed: ${e.message}`);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-check-circle"></i> Apply Changes'; btn.style.opacity = "1"; }
    }
  }

  // ── Keyboard Listeners ─────────────────────────────────────────────────
  document.addEventListener("keydown", (e) => {
    if (!_active) return;
    if (e.key === "Escape") _close();
    if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); _undo(); }
    if (!e.ctrlKey && !e.metaKey) {
      if (e.key === "d" || e.key === "D") _setTool("draw");
      if (e.key === " ") { e.preventDefault(); _setTool("pan"); }
    }
  });

  function _esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
})();
