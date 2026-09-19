"""Self-contained HTML template for the Privacy Filter GUI.

All CSS and JS are inlined so the page works without any external file
dependencies. Font Awesome icons are replaced with inline SVG where needed.
"""

_HTML = None


def get_html() -> str:
    global _HTML
    if _HTML is not None:
        return _HTML

    _HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Privacy Filter — TANUH DPI</title>

<!-- Inter font with offline fallback -->
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
</style>

<!-- Font Awesome 6 Free (Local Offline Asset) -->
<link rel="stylesheet" href="/static/css/all.min.css">

<style>
/* ══ Design System Variables ══ */
:root {
    --brand-primary: #14868C;
    --brand-accent: #0fa4a0;
    --brand-dark: #0c6468;
    --brand-light: #d8eeee;
    --brand-teal: #107a7f;
    --text-900: #111827;
    --text-800: #1f2937;
    --text-700: #374151;
    --text-600: #4b5563;
    --text-500: #6b7280;
    --text-400: #9ca3af;
    --gray-50: #f9fafb;
    --gray-100: #f3f4f6;
    --gray-200: #e5e7eb;
    --gray-300: #d1d5db;
    --white: #ffffff;
    --primary: var(--brand-primary);
    --primary-hover: var(--brand-dark);
    --text-dark: var(--text-900);
    --text-light: var(--text-500);
    --border: var(--gray-200);
    --error-red: #ef4444;
    --success: #10b981;
}

*, *::before, *::after { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
    font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    margin: 0; padding: 0;
    background: #f8fafc;
    color: #1e293b;
    -webkit-font-smoothing: antialiased;
}

.hidden { display: none !important; }

@keyframes spin { to { transform: rotate(360deg); } }

/* ══ Privacy Filter CSS (from privacy-filter.css) ══ */
.pf-panel { max-width: 900px; margin: 0 auto; padding: 0 20px 40px; }

.pf-meta-chip {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 0.78rem; font-weight: 500; color: #0e6a6f;
    background: white; border: 1px solid rgba(20,134,140,0.25);
    padding: 4px 10px; border-radius: 999px; white-space: nowrap;
    overflow: hidden; max-width: 260px; text-overflow: ellipsis;
}
.pf-meta-chip i { color: #14868C; flex-shrink: 0; }
.pf-meta-chip span { overflow: hidden; text-overflow: ellipsis; }

.pf-summary-card {
    flex: 1; min-width: 130px; background: white;
    border: 1px solid #e2e8f0; border-top: 3px solid var(--pf-card-accent, #14868C);
    border-radius: 10px; padding: 12px 14px;
    display: flex; flex-direction: column; gap: 4px; transition: box-shadow 0.2s;
}
.pf-summary-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.08); }
.pf-summary-card-count { font-size: 1.6rem; font-weight: 700; color: var(--pf-card-accent, #14868C); line-height: 1; }
.pf-summary-card-label { font-size: 0.72rem; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }

.pf-entity-badge {
    display: inline-flex; align-items: center; justify-content: center; gap: 5px;
    font-size: 0.73rem; font-weight: 600; padding: 3px 9px; border-radius: 999px;
    white-space: normal; text-align: center; text-transform: uppercase;
    letter-spacing: 0.04em; line-height: 1.1; word-break: break-word;
}

.pf-conf-bar-wrap { display: flex; align-items: center; gap: 6px; min-width: 0; width: 100%; }
.pf-conf-bar { flex: 1; height: 5px; border-radius: 999px; background: #e2e8f0; overflow: hidden; min-width: 15px; }
.pf-conf-bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #14868C, #0e6a6f); transition: width 0.4s ease; }
.pf-conf-bar-fill.pf-conf-low { background: #f59e0b; }
.pf-conf-bar-fill.pf-conf-mid { background: #14868C; }
.pf-conf-bar-fill.pf-conf-high { background: #059669; }
.pf-conf-label { font-size: 0.72rem; font-weight: 600; color: #64748b; min-width: 34px; text-align: right; }

.pf-entity-word { font-weight: 600; color: #1e293b; font-size: 0.88rem; }

/* ══ Inline Style Overrides (from privacyfilter.html) ══ */
.pf-container { max-width: 1000px; margin: 0 auto; padding: 20px; font-family: 'Inter', system-ui, -apple-system, sans-serif; }

.pf-workspace-card {
    background: #ffffff; border: 1px solid rgba(20, 134, 140, 0.08);
    border-radius: 12px; padding: 20px;
    box-shadow: 0 10px 40px rgba(15, 23, 42, 0.015); margin-bottom: 16px;
}

.pf-dropzone-modern {
    border: 2px dashed rgba(20, 134, 140, 0.25); background: #fcfefe;
    border-radius: 10px; padding: 28px 16px; text-align: center; cursor: pointer;
    transition: all 250ms ease; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 10px;
}
.pf-dropzone-modern:hover {
    border-color: var(--primary); background: #f0fafb;
    box-shadow: 0 0 0 4px rgba(20, 134, 140, 0.06);
}

.pf-upload-icon-wrap {
    width: 48px; height: 48px; border-radius: 50%;
    background: rgba(20, 134, 140, 0.06); color: var(--primary);
    display: flex; align-items: center; justify-content: center; font-size: 1.25rem;
    transition: transform 0.2s ease;
}
.pf-dropzone-modern:hover .pf-upload-icon-wrap { transform: translateY(-2px); background: rgba(20, 134, 140, 0.1); }

.pf-dropzone-title { font-size: 0.9rem; font-weight: 600; color: #0f172a; margin: 0; }
.pf-dropzone-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }

.pf-selected-card {
    display: flex; align-items: center; gap: 12px;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 12px 16px; margin-bottom: 14px; box-sizing: border-box;
}
.pf-file-icon { font-size: 1.25rem; color: var(--primary); }
.pf-file-details { flex: 1; }
.pf-file-name { font-size: 0.84rem; font-weight: 600; color: #0f172a; word-break: break-all; }
.pf-file-size { font-size: 0.7rem; color: #64748b; margin-top: 2px; }

.pf-remove-file-btn {
    border: none; background: transparent; color: #ef4444; cursor: pointer;
    font-size: 0.85rem; padding: 4px; border-radius: 6px; transition: background-color 0.2s;
}
.pf-remove-file-btn:hover { background: #fee2e2; }

.pf-btn-modern {
    background: var(--primary) !important; color: #ffffff !important;
    font-size: 0.85rem !important; font-weight: 600 !important;
    padding: 8px 20px !important; border: none !important; border-radius: 6px !important;
    box-shadow: 0 4px 14px rgba(20, 134, 140, 0.25) !important;
    cursor: pointer !important; display: inline-flex !important;
    align-items: center !important; justify-content: center !important;
    gap: 8px !important; transition: all 200ms ease !important;
}
.pf-btn-modern:hover { background: var(--brand-dark) !important; box-shadow: 0 6px 20px rgba(20, 134, 140, 0.35) !important; transform: translateY(-1px) !important; }
.pf-btn-modern:disabled { opacity: 0.6 !important; cursor: not-allowed !important; transform: none !important; box-shadow: none !important; }

.pf-dashboard-grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
@media (min-width: 1024px) { .pf-dashboard-grid { grid-template-columns: 55fr 45fr; height: 750px; } }

.pf-dashboard-panel {
    background: #ffffff; border: 1px solid rgba(20, 134, 140, 0.08);
    border-radius: 12px; padding: 16px;
    box-shadow: 0 10px 30px rgba(15, 23, 42, 0.015);
    box-sizing: border-box; min-width: 0; overflow: hidden;
}

.pf-panel-header { border-bottom: 1px solid #f1f5f9; padding-bottom: 10px; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }
.pf-panel-title { font-size: 0.92rem; font-weight: 700; color: #0f172a; margin: 0; display: flex; align-items: center; gap: 8px; }
.pf-panel-title i { color: var(--primary); }

.pf-table { width: 100%; border-collapse: collapse; }
.pf-table th { padding: 8px 12px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; color: #64748b; background: #f8fafc; border-bottom: 1.5px solid #e2e8f0; text-align: left; }
.pf-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; font-size: 0.78rem; color: #334155; vertical-align: middle; word-break: break-word; overflow-wrap: break-word; }
.pf-table tr:hover { background: #fcfefe; }
.pf-table tr:last-child td { border-bottom: none; }

.pf-summary-card { padding: 8px 12px !important; min-width: 100px !important; border-radius: 8px !important; gap: 2px !important; }
.pf-summary-card-count { font-size: 1.25rem !important; }
.pf-summary-card-label { font-size: 0.68rem !important; }
.pf-meta-chip { padding: 3px 8px !important; font-size: 0.72rem !important; max-width: 200px !important; }
.pf-entity-word { font-size: 0.78rem !important; }
.pf-entity-badge { font-size: 0.68rem !important; padding: 2px 7px !important; white-space: normal !important; word-break: break-word; max-width: 100%; }
.pf-conf-label { font-size: 0.68rem !important; }

/* ══ App Header Bar ══ */
.pf-app-header {
    background: #ffffff;
    padding: 12px 24px; display: flex; align-items: center; justify-content: space-between;
    border-bottom: 2px solid #14868C; position: relative;
    box-shadow: 0 2px 10px rgba(0,0,0,0.05);
}
.pf-header-brand-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    z-index: 2;
}
.pf-header-logo-img {
    height: 34px;
    width: auto;
}
.pf-header-logo-moe {
    height: 32px;
    width: auto;
    border-left: 1px solid rgba(15, 23, 42, 0.12);
    padding-left: 8px;
    margin-left: 4px;
}
.pf-header-logo-iisc {
    height: 30px;
    width: auto;
    border-left: 1px solid rgba(15, 23, 42, 0.12);
    padding-left: 8px;
    margin-left: 4px;
}
.pf-header-brand-text {
    display: flex;
    flex-direction: column;
    margin-left: 4px;
}
.pf-header-brand-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: #0f172a;
    line-height: 1.2;
}
.pf-header-brand-subtitle {
    font-size: 0.62rem;
    color: #14868C;
    letter-spacing: 0.02em;
}
.pf-app-header-title {
    font-size: 1rem;
    font-weight: 700;
    color: #0f172a;
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    z-index: 1;
    white-space: nowrap;
}
.pf-app-header-badge {
    font-size: 0.7rem; font-weight: 700;
    color: #475569; background: rgba(15,23,42,0.06);
    border: 1px solid rgba(15,23,42,0.1); padding: 5px 12px; border-radius: 20px;
    transition: all 0.3s ease;
    z-index: 2;
}
.pf-app-header-badge.ai-badge-on {
    color: #047857; background: rgba(16,185,129,0.12);
    border-color: rgba(16,185,129,0.3);
}
.pf-app-header-badge.ai-badge-off {
    color: #b45309; background: rgba(245,158,11,0.12);
    border-color: rgba(245,158,11,0.3);
}
.pf-meta-warn {
    background: #fffbeb; border-color: #f59e0b; color: #92400e;
}
.pf-meta-warn i { color: #f59e0b; }

@media (max-width: 900px) {
    .pf-app-header-title {
        position: static;
        transform: none;
        font-size: 0.85rem;
        margin: 0 auto;
    }
}
@media (max-width: 768px) {
    .pf-header-logo-moe, .pf-header-logo-iisc {
        display: none;
    }
}
@media (max-width: 600px) {
    .pf-app-header-title {
        display: none;
    }
}

.pf-preview-container-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 12px;
}

/* Toast notification */
.pf-toast {
    position: fixed; bottom: 24px; right: 24px; z-index: 999998;
    background: #0f172a; color: #fff; padding: 12px 20px; border-radius: 10px;
    font-size: 0.82rem; font-weight: 600; display: flex; align-items: center; gap: 8px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3); opacity: 0; transform: translateY(12px);
    transition: opacity 0.3s ease, transform 0.3s ease; pointer-events: none;
}
.pf-toast.pf-toast-show { opacity: 1; transform: translateY(0); }
.pf-toast.pf-toast-success { border-left: 4px solid #10b981; }
.pf-toast.pf-toast-error { border-left: 4px solid #ef4444; }
</style>
</head>

<body>

<!-- App Header -->
<div class="pf-app-header">
    <div class="pf-header-brand-wrap">
        <img src="/static/images/tanuh.png" alt="TANUH AI" class="pf-header-logo-img">
        <img src="/static/images/MoE_Logo.svg" alt="Ministry of Education" class="pf-header-logo-moe">
        <img src="/static/images/IISc_Logo.png" alt="IISc Logo" class="pf-header-logo-iisc">
        <div class="pf-header-brand-text">
            <span class="pf-header-brand-title">TANUH DPI</span>
            <span class="pf-header-brand-subtitle">The AI-CoE in Healthcare</span>
        </div>
    </div>
    <span class="pf-app-header-title">Privacy Filter (Anonymization)</span>
    <span class="pf-app-header-badge" id="pfHealthBadge">
        <span id="pfHealthText">INITIALIZING...</span>
    </span>
</div>

<!-- Main Content -->
<div class="pf-container">
    <div style="margin-bottom: 16px;">
        <h2 style="font-size: 1.25rem; font-weight: 700; color: #0f172a; display: flex; align-items: center; gap: 8px; margin: 16px 0 6px;">
            <i class="fas fa-user-shield" style="color:var(--primary)"></i> Privacy Filter (Anonymization) Tool
        </h2>
        <p style="font-size: 0.82rem; color: #64748b; margin: 0;">
            Upload clinical documents/images, medical reports, or claim forms to anonymize and sanitize patient PII/PHI.
        </p>
    </div>

    <!-- Info banner -->
    <div style="margin-bottom: 16px; padding: 10px 14px; border-left: 4px solid #14868C; background-color: #f0fdfa; border-radius: 6px;">
        <p style="margin: 0 0 6px 0; color: #0f766e; font-size: 0.78rem; line-height: 1.4;">
            <strong><i class="fas fa-clock"></i> Note:</strong> Processing time is typically <strong>10 to 30 seconds per document/image.</strong>
        </p>
        <p style="margin: 0 0 6px 0; color: #0f766e; font-size: 0.78rem; line-height: 1.4;">
            <strong><i class="fas fa-user-shield"></i> Privacy Protocol:</strong> All processing happens locally on your machine. No data leaves this application.
        </p>
        <p style="margin: 0 0 6px 0; color: #0f766e; font-size: 0.78rem; line-height: 1.4;">
            <strong><i class="fas fa-file-pdf"></i> Limit:</strong> Maximum allowed file size is <strong>75 MB</strong>. Supported: PDF, DICOM, NIfTI, and PNG/JPG images.
        </p>
        <p style="margin: 0; color: #0f766e; font-size: 0.78rem; line-height: 1.4;">
            <strong><i class="fas fa-check-circle"></i> Verification:</strong> You can edit original/redacted items in the preview window to correct any omissions and undo any redactions.
        </p>
    </div>

    <span id="pfFileName" style="display:none;">Choose document to redact...</span>

    <!-- Upload Workspace Card -->
    <div class="pf-workspace-card">
        <div class="pf-dropzone-modern" id="pfDropzone" onclick="document.getElementById('pfFileInput').click()">
            <input type="file" id="pfFileInput" onchange="PF_handleFileChange()" style="display:none">
            <div class="pf-upload-icon-wrap">
                <i class="fas fa-cloud-upload-alt"></i>
            </div>
            <div>
                <p class="pf-dropzone-title">Drag &amp; drop document here, or <span style="color:var(--primary); text-decoration:underline; font-weight:700;">browse files</span></p>
                <p class="pf-dropzone-subtitle" style="margin-top: 4px;">Supports DICOM, NIfTI, PDF, and PNG/JPG images (Max 75 MB)</p>
            </div>
        </div>

        <div class="pf-selected-card" id="pfFileCard" style="display:none;">
            <div class="pf-file-icon"><i class="far fa-file-pdf"></i></div>
            <div class="pf-file-details">
                <div class="pf-file-name" id="pfCardFileName">Selected_document.pdf</div>
                <div class="pf-file-size" id="pfCardFileSize">0.0 KB</div>
            </div>
            <button class="pf-remove-file-btn" onclick="PF_removeFile(event)" title="Remove selected file">
                <i class="fas fa-trash-alt"></i>
            </button>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 14px;">
            <button onclick="PF_processRedaction()" id="pfProcessBtn" class="pf-btn-modern" disabled>
                <span>Redact Document</span>
                <div class="loader" id="pfLoader" style="display:none; width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
            </button>
        </div>
    </div>

    <!-- Interactive Editor Teaser -->
    <div id="pfEditorTeaser" style="margin-top: 18px; padding: 14px 18px; background: linear-gradient(135deg, #f0f9ff 0%, #f0fdfa 100%); border: 1.5px dashed #99d5d9; border-radius: 10px; display: flex; align-items: center; gap: 14px;">
        <div style="flex-shrink: 0; width: 38px; height: 38px; background: #e0f2fe; border-radius: 10px; display: flex; align-items: center; justify-content: center;">
            <i class="fas fa-pen-fancy" style="font-size: 1rem; color: #0e6a6f;"></i>
        </div>
        <div>
            <p style="margin: 0 0 2px; font-size: 0.82rem; font-weight: 700; color: #0f766e;">Interactive Editor</p>
            <p style="margin: 0; font-size: 0.74rem; color: #64748b; line-height: 1.45;">Once processed, click "Edit" on any preview to manually draw or remove redaction boxes.</p>
        </div>
    </div>

    <!-- Processing status -->
    <div id="pfStatus" class="hidden" style="margin: 16px 0; font-size: 0.9rem; color: var(--primary); font-weight: 600;"></div>

    <!-- Results Area -->
    <div>
        <section id="pfResults" class="hidden">
            <div id="pfEditorHint" style="margin-bottom: 14px; padding: 10px 14px; background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; display: flex; align-items: center; gap: 10px;">
                <i class="fas fa-lightbulb" style="color: #0ea5e9; font-size: 0.9rem; flex-shrink: 0;"></i>
                <p style="margin: 0; font-size: 0.76rem; color: #475569; line-height: 1.45;">
                    <strong>Editor Tip:</strong> Click <strong>Edit</strong> on any preview to open the interactive editor. Draw bounding boxes to redact missed PII, or click existing redactions to remove them.
                </p>
            </div>

            <div id="pfMetaBar" style="display: flex; flex-wrap: wrap; gap: 10px; align-items: center; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px; margin-bottom: 16px;">
                <span id="pfMetaJobId" class="pf-meta-chip"><i class="fas fa-fingerprint"></i> <span></span></span>
                <span id="pfMetaFile" class="pf-meta-chip"><i class="fas fa-file-alt"></i> <span></span></span>
                <span id="pfMetaType" class="pf-meta-chip"><i class="fas fa-tag"></i> <span></span></span>
                <span id="pfMetaNotes" class="pf-meta-chip pf-meta-warn hidden"><i class="fas fa-exclamation-triangle"></i> <span></span></span>
            </div>

            <div id="pfSummaryCards" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px; margin-bottom: 16px;"></div>

            <div class="pf-dashboard-grid" style="margin-bottom: 16px;">
                <div class="pf-dashboard-panel" style="display: flex; flex-direction: column; gap: 12px;">
                    <div class="pf-panel-header" style="margin: 0; padding-bottom: 8px;">
                        <h4 class="pf-panel-title"><i class="fas fa-columns"></i> Preview Workspace</h4>
                    </div>
                    <div class="pf-preview-container-grid">
                        <div style="border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; display: flex; flex-direction: column;">
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
                                <span style="font-size: 0.76rem; font-weight: 700; color: #475569; text-transform: uppercase;"><i class="fas fa-file-alt" style="margin-right: 4px;"></i> Original</span>
                                <div style="display: flex; gap: 6px;">
                                    <button style="display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border: 1.5px solid #ddd6fe; border-radius: 5px; background: white; font-family: inherit; font-size: 0.7rem; font-weight: 600; cursor: pointer; color: #7c3aed;" onclick="PF_openEditor('original')" id="pfEditOriginalBtn" disabled>
                                        <i class="fas fa-pen"></i> Edit
                                    </button>
                                    <button style="display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border: 1.5px solid #b2dfdb; border-radius: 5px; background: white; font-family: inherit; font-size: 0.7rem; font-weight: 600; cursor: pointer; color: #0e6a6f;" onclick="PF_downloadFile('original')" id="pfDlOriginal" disabled>
                                        <i class="fas fa-download"></i> <span>Save</span>
                                        <span id="pfDlOriginalSub" style="font-size:0.6rem; font-weight:500; color:#64748b; display:none;"></span>
                                    </button>
                                </div>
                            </div>
                            <div id="pfPreviewOriginal" style="height: 400px; overflow: auto; padding: 6px; display: flex; flex-direction: column; align-items: center; gap: 6px; background: #f8fafc;">
                                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 180px; color: #94a3b8; gap: 6px;">
                                    <i class="fas fa-image" style="font-size: 1.8rem;"></i><span style="font-size: 0.75rem;">Original document</span>
                                </div>
                            </div>
                        </div>

                        <div style="border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; display: flex; flex-direction: column;">
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
                                <span style="font-size: 0.76rem; font-weight: 700; color: #475569; text-transform: uppercase;"><i class="fas fa-eye-slash" style="color:var(--primary); margin-right: 4px;"></i> Redacted Output</span>
                                <div style="display: flex; gap: 6px;">
                                    <button style="display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border: 1.5px solid #ddd6fe; border-radius: 5px; background: white; font-family: inherit; font-size: 0.7rem; font-weight: 600; cursor: pointer; color: #7c3aed;" onclick="PF_openEditor('redacted')" id="pfEditRedactedBtn" disabled>
                                        <i class="fas fa-pen"></i> Edit
                                    </button>
                                    <button style="display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border: 1.5px solid #b2dfdb; border-radius: 5px; background: white; font-family: inherit; font-size: 0.7rem; font-weight: 600; cursor: pointer; color: #0e6a6f;" onclick="PF_downloadFile('redacted')" id="pfDlRedacted" disabled>
                                        <i class="fas fa-download"></i> <span>Save</span>
                                        <span id="pfDlRedactedSub" style="font-size:0.6rem; font-weight:500; color:#64748b; display:none;"></span>
                                    </button>
                                </div>
                            </div>
                            <div id="pfPreviewRedacted" style="height: 400px; overflow: auto; padding: 6px; display: flex; flex-direction: column; align-items: center; gap: 6px; background: #f8fafc;">
                                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 180px; color: #94a3b8; gap: 6px;">
                                    <i class="fas fa-shield-alt" style="font-size: 1.8rem;"></i><span style="font-size: 0.75rem;">Redacted document</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="pf-dashboard-panel" style="display: flex; flex-direction: column; overflow: hidden;">
                    <div class="pf-panel-header" style="margin: 0; padding-bottom: 8px; flex-shrink: 0;">
                        <h4 class="pf-panel-title"><i class="fas fa-shield-virus"></i> Detected PII Entities</h4>
                        <span id="pfEntityTotal" style="font-size:0.7rem; font-weight:700; color:var(--primary); background:#e6f7f8; padding:2px 8px; border-radius:999px;">0</span>
                    </div>
                    <div style="flex: 1; overflow-y: auto; overflow-x: hidden;">
                        <table class="pf-table" style="table-layout: fixed; width: 100%;">
                            <thead>
                                <tr style="position: sticky; top:0; z-index:1;">
                                    <th style="width: 10%;">#</th>
                                    <th style="width: 36%; word-break: break-word;">Entity Value</th>
                                    <th style="width: 32%;">PII Category</th>
                                    <th style="width: 22%;">Confidence</th>
                                </tr>
                            </thead>
                            <tbody id="pfEntityTbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

            <div id="pfTextPreviewSection" class="pf-dashboard-panel" style="display:none; margin-bottom: 16px;">
                <div class="pf-panel-header" style="margin: 0; padding-bottom: 8px;">
                    <h4 class="pf-panel-title"><i class="fas fa-file-signature"></i> Text Content Redaction Summary</h4>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                    <div>
                        <h5 style="font-size:0.75rem; color:var(--text-light); margin-bottom:8px; text-transform:uppercase; letter-spacing:0.05em;"><i class="fas fa-file-alt" style="margin-right:5px;"></i>Original Text</h5>
                        <pre id="pfPrevOriginal" style="height:220px; background:#f8fafc; color:#334155; border:1px solid #e2e8f0; padding:8px 12px; border-radius:8px; overflow:auto; white-space:pre-wrap; font-size:0.76rem; line-height:1.55; margin:0;"></pre>
                    </div>
                    <div>
                        <h5 style="font-size:0.75rem; color:var(--text-light); margin-bottom:8px; text-transform:uppercase; letter-spacing:0.05em;"><i class="fas fa-eye-slash" style="margin-right:5px; color:var(--primary);"></i>Redacted Text</h5>
                        <pre id="pfPrevRedacted" style="height:220px; background:#fff8f0; color:#334155; border:1px solid #fbbf24; padding:8px 12px; border-radius:8px; overflow:auto; white-space:pre-wrap; font-size:0.76rem; line-height:1.55; margin:0;"></pre>
                    </div>
                </div>
            </div>
        </section>
    </div>
</div>

<script>
/* ══════════════════════════════════════════════════════════════════════════
   Privacy Filter JS — modified for local GUI (no auth, no polling)
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  const PF_BASE = "";

  window._PF_BASE = PF_BASE;
  window._PF_getToken = function() { return ""; };

  function pfQ(id) { return document.getElementById(id); }

  async function PF_pingHealth() {
    const badge = pfQ("pfHealthBadge");
    const textEl = pfQ("pfHealthText");
    if (!badge || !textEl) return;
    try {
      const r = await fetch(`${PF_BASE}/api/health`, { signal: AbortSignal.timeout(10000) });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      const ready = !!j.model_loaded;
      var modelTag = j.model ? j.model.toUpperCase() : "PRIVACY FILTER";
      var devTag = j.device ? j.device.toUpperCase() : "CPU";
      textEl.textContent = ready ? modelTag + " · " + devTag + " READY" : modelTag + " · WARMING UP…";
      badge.classList.toggle("ai-badge-on", ready);
      badge.classList.toggle("ai-badge-off", !ready);
      if (!ready) setTimeout(PF_pingHealth, 3000);
    } catch (e) {
      textEl.textContent = "PRIVACY FILTER · STARTING…";
      badge.classList.add("ai-badge-off");
      badge.classList.remove("ai-badge-on");
      setTimeout(PF_pingHealth, 3000);
    }
  }

  async function PF_loadSupported() {
    try {
      const r = await fetch(`${PF_BASE}/api/supported-types`, { signal: AbortSignal.timeout(8000) });
      const j = await r.json();
      const input = pfQ("pfFileInput");
      if (input && j.extensions) input.setAttribute("accept", j.extensions.join(","));
    } catch {}
  }

  function PF_setStatus(msg, isError) {
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

  window.showToast = function(msg, type) {
    var existing = document.querySelector(".pf-toast");
    if (existing) existing.remove();
    var t = document.createElement("div");
    t.className = "pf-toast pf-toast-" + (type || "success");
    t.innerHTML = '<i class="fas ' + (type === "error" ? "fa-times-circle" : "fa-check-circle") + '"></i> ' + msg;
    document.body.appendChild(t);
    requestAnimationFrame(function() { t.classList.add("pf-toast-show"); });
    setTimeout(function() { t.classList.remove("pf-toast-show"); setTimeout(function() { t.remove(); }, 300); }, 3000);
  };

  const PF_ENTITY_PALETTE = {
    private_person:   { bg: "#fce7f3", color: "#be185d", icon: "fa-user",           accent: "#db2777" },
    private_date:     { bg: "#fef3c7", color: "#b45309", icon: "fa-calendar-alt",   accent: "#d97706" },
    address_location: { bg: "#dbeafe", color: "#1d4ed8", icon: "fa-map-marker-alt", accent: "#2563eb" },
    org_name:         { bg: "#d1fae5", color: "#065f46", icon: "fa-building",        accent: "#059669" },
    phone_number:     { bg: "#ede9fe", color: "#6d28d9", icon: "fa-phone",           accent: "#7c3aed" },
    email:            { bg: "#e0f2fe", color: "#0369a1", icon: "fa-envelope",        accent: "#0284c7" },
    id_number:        { bg: "#fee2e2", color: "#991b1b", icon: "fa-id-card",         accent: "#dc2626" },
    burned_in_text:   { bg: "#fee2e2", color: "#991b1b", icon: "fa-image",           accent: "#dc2626" },
  };
  function PF_entityStyle(group) {
    var key = (group || "").replace(/^private_/, "");
    return PF_ENTITY_PALETTE[group] || PF_ENTITY_PALETTE[key] || {
      bg: "#f1f5f9", color: "#475569", icon: "fa-shield-alt", accent: "#64748b"
    };
  }

  function PF_formatCategory(cat) {
    if (!cat) return "";
    var s = cat.replace(/^private_/, "").toUpperCase();
    var mapping = {
      "PERFORMINGPHYSICIANNAME": "PERFORMING PHYSICIAN NAME",
      "REFERRINGPHYSICIANNAME": "REFERRING PHYSICIAN NAME",
      "DEVICESERIALNUMBER": "DEVICE SERIAL NUMBER",
      "ISSUEROFPATIENTID": "ISSUER OF PATIENT ID",
      "PATIENTBIRTHDATE": "PATIENT BIRTH DATE",
      "ACCESSIONNUMBER": "ACCESSION NUMBER",
      "INSTITUTIONNAME": "INSTITUTION NAME",
      "OPERATORSNAME": "OPERATORS NAME",
      "STATIONNAME": "STATION NAME",
      "PATIENTNAME": "PATIENT NAME",
      "PATIENTID": "PATIENT ID",
      "PATIENTSEX": "PATIENT SEX",
      "STUDYID": "STUDY ID",
      "TOTALPIIFOUND": "TOTAL PII FOUND",
      "BURNEDINTEXT": "IMAGE PII"
    };
    if (mapping[s]) return mapping[s];
    return s.replace(/_/g, " ");
  }

  function PF_renderResult(res) {
    var resultsEl = pfQ("pfResults");
    if (!resultsEl) return;
    resultsEl.classList.remove("hidden");

    var teaser = pfQ("pfEditorTeaser");
    if (teaser) teaser.style.display = "none";

    var setChip = function(id, text, show) {
      var chip = pfQ(id);
      if (!chip) return;
      chip.querySelector("span").textContent = text || "—";
      chip.classList.toggle("hidden", show === false || !text);
    };
    setChip("pfMetaJobId",  "Job: " + (res.job_id || "—"));
    setChip("pfMetaFile",    res.filename || "");
    setChip("pfMetaType",    res.content_type || "");
    setChip("pfMetaNotes",   res.notes || "", !!res.notes);

    window._PF_urls = {
      original: res.original_url || null,
      redacted: res.redacted_url || null,
    };
    window._PF_filename = res.filename || "document";
    window._PF_jobId = res.job_id || "";
    window._PF_uploadKey = res.original_url ? res.original_url.split("/").pop() : "";

    var btnOrig = pfQ("pfDlOriginal");
    var btnRed = pfQ("pfDlRedacted");
    if (btnOrig) btnOrig.disabled = !window._PF_urls.original;
    if (btnRed) btnRed.disabled = !window._PF_urls.redacted;

    window._PF_aiBoxes = (res.entities || [])
      .filter(function(e) { return e.bbox; })
      .map(function(e) { return {
        page: e.bbox.page || 0, x: e.bbox.x1, y: e.bbox.y1,
        w: e.bbox.x2 - e.bbox.x1, h: e.bbox.y2 - e.bbox.y1,
        label: e.entity_group || "PHI", source: "ai",
      }; });

    var origKey = res.original_url ? res.original_url.split("/").pop() : null;
    var redKey = res.redacted_url ? res.redacted_url.split("/").pop() : null;
    if (origKey && window.PF_loadPreview) window.PF_loadPreview("original", origKey);
    if (redKey && window.PF_loadPreview) window.PF_loadPreview("redacted", redKey);

    var cardsEl = pfQ("pfSummaryCards");
    if (cardsEl) {
      cardsEl.innerHTML = "";
      var counts = res.entity_counts || {};
      var total = Object.values(counts).reduce(function(s, v) { return s + v; }, 0);
      var totalCard = document.createElement("div");
      totalCard.className = "pf-summary-card";
      totalCard.style.setProperty("--pf-card-accent", "#14868C");
      totalCard.innerHTML = '<div class="pf-summary-card-count">' + total + '</div><div class="pf-summary-card-label"><i class="fas fa-shield-alt"></i> Total PII Found</div>';
      cardsEl.appendChild(totalCard);

      var sorted = Object.entries(counts).sort(function(a, b) { return b[1] - a[1]; });
      for (var i = 0; i < sorted.length; i++) {
        var type = sorted[i][0], count = sorted[i][1];
        var style = PF_entityStyle(type);
        var label = PF_formatCategory(type);
        var card = document.createElement("div");
        card.className = "pf-summary-card";
        card.style.setProperty("--pf-card-accent", style.accent);
        card.innerHTML = '<div class="pf-summary-card-count" style="color:' + style.accent + '">' + count + '</div><div class="pf-summary-card-label"><i class="fas ' + style.icon + '" style="color:' + style.accent + '"></i> ' + label + '</div>';
        cardsEl.appendChild(card);
      }
    }

    var tbody = pfQ("pfEntityTbody");
    var totalEl = pfQ("pfEntityTotal");
    var entities = res.entities || [];
    if (totalEl) totalEl.textContent = entities.length + " entities";
    if (tbody) {
      tbody.innerHTML = "";
      if (entities.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:24px; color:#94a3b8;"><i class="fas fa-check-circle" style="margin-right:6px; color:#22c55e;"></i>No personal information detected.</td></tr>';
      } else {
        entities.forEach(function(ent, idx) {
          var style = PF_entityStyle(ent.entity_group);
          var label = PF_formatCategory(ent.entity_group);
          var pct = Math.round((ent.score || 0) * 100);
          var confCls = pct >= 80 ? "pf-conf-high" : pct >= 55 ? "pf-conf-mid" : "pf-conf-low";
          var word = (ent.word || "").trim();
          var displayWord = word ? escHtml(word) : '<span style="color:#94a3b8; font-style:italic; font-weight:normal;">[Image Region]</span>';
          var tr = document.createElement("tr");
          tr.innerHTML = '<td style="color:#94a3b8; font-size:0.78rem; white-space: nowrap;">' + (idx + 1) + '</td><td><span class="pf-entity-word">' + displayWord + '</span></td><td><span class="pf-entity-badge" style="background:' + style.bg + '; color:' + style.color + ';"><i class="fas ' + style.icon + '"></i>' + label + '</span></td><td><div class="pf-conf-bar-wrap"><div class="pf-conf-bar"><div class="pf-conf-bar-fill ' + confCls + '" style="width:' + pct + '%"></div></div><span class="pf-conf-label">' + pct + '%</span></div></td>';
          tbody.appendChild(tr);
        });
      }
    }

    var prevOrig = pfQ("pfPrevOriginal");
    var prevRed = pfQ("pfPrevRedacted");
    var textSection = pfQ("pfTextPreviewSection");
    if (prevOrig) prevOrig.textContent = res.text_preview_original || "(no text preview available)";
    if (prevRed) prevRed.textContent = res.text_preview_redacted || "(no text preview available)";
    if (textSection) {
      var ext = (res.filename || "").split(".").pop().toLowerCase();
      var textOnly = ["txt", "md", "log", "csv", "docx"];
      textSection.style.display = textOnly.indexOf(ext) >= 0 ? "" : "none";
    }
  }

  function escHtml(str) {
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  window.PF_downloadFile = async function (kind) {
    var urls = window._PF_urls || {};
    var url = urls[kind];
    var filename = window._PF_filename || "document";
    if (!url) return;

    var encodedUrl = encodeURI(url);

    var btnId = kind === "original" ? "pfDlOriginal" : "pfDlRedacted";
    var subId = kind === "original" ? "pfDlOriginalSub" : "pfDlRedactedSub";
    var btn = pfQ(btnId);
    var sub = pfQ(subId);
    if (btn) btn.disabled = true;
    if (sub) { sub.textContent = "Downloading…"; sub.style.display = "inline"; }

    var suffix = kind === "redacted" ? "__redacted" : "";
    var dlName = filename.replace(/(\.[^.]+)$/, suffix + "$1");

    try {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.save_file) {
        var savedPath = await window.pywebview.api.save_file(url, dlName);
        if (sub) { sub.textContent = "Saved"; sub.style.color = "#10b981"; }
        if (window.showToast) window.showToast("Saved to Downloads: " + dlName, "success");
      } else {
        var r = await fetch(encodedUrl, { signal: AbortSignal.timeout(30000) });
        if (!r.ok) throw new Error("HTTP " + r.status);
        var blob = await r.blob();
        var objUrl = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = objUrl;
        a.download = dlName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function() { URL.revokeObjectURL(objUrl); }, 10000);
        if (sub) { sub.textContent = "Saved"; sub.style.color = "#10b981"; }
        if (window.showToast) window.showToast("File saved: " + dlName, "success");
      }
      setTimeout(function() { if (sub) { sub.style.display = "none"; sub.style.color = "#64748b"; } }, 3000);
    } catch (e) {
      if (sub) { sub.textContent = "Error"; sub.style.color = "#ef4444"; }
      if (window.showToast) window.showToast("Download failed: " + e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  };

  async function PF_uploadFile(file) {
    PF_clearStatus();
    if (window.PF_resetEditorState) window.PF_resetEditorState();
    var resultsEl = pfQ("pfResults");
    var loader = pfQ("pfLoader");
    var btnText = pfQ("pfProcessBtn") ? pfQ("pfProcessBtn").querySelector("span") : null;
    var teaser = pfQ("pfEditorTeaser");

    if (resultsEl) resultsEl.classList.add("hidden");
    if (loader) loader.style.display = "block";
    if (btnText) btnText.textContent = "Redacting…";
    if (teaser) teaser.style.display = "none";

    PF_setStatus("Processing " + file.name + "…");

    try {
      var fd = new FormData();
      fd.append("file", file);
      var r = await fetch(PF_BASE + "/api/redact", {
        method: "POST",
        body: fd,
        signal: AbortSignal.timeout(600000),
      });
      if (!r.ok) {
        var err = await r.json().catch(function() { return { detail: r.statusText }; });
        throw new Error(err.detail || "HTTP " + r.status);
      }
      var result = await r.json();

      if (result.status === "failed") throw new Error(result.error || "Redaction failed");
      var n = result.entities ? result.entities.length : 0;
      PF_setStatus("✓ Done — " + n + " PII " + (n === 1 ? "entity" : "entities") + " detected.");
      PF_renderResult(result);
    } catch (e) {
      if (e.name === "AbortError" || e.name === "TimeoutError") {
        PF_setStatus("Processing timed out. The file may be too large — please retry.", true);
      } else {
        PF_setStatus("Error: " + e.message, true);
      }
    } finally {
      if (loader) loader.style.display = "none";
      if (btnText) btnText.textContent = "Redact Document";
    }
  }

  window.PF_updateFileName = function () {
    var input = pfQ("pfFileInput");
    var label = pfQ("pfFileName");
    if (input && label && input.files.length) label.textContent = input.files[0].name;
  };

  window.PF_handleFileChange = function () {
    if (window.PF_updateFileName) PF_updateFileName();
    var input = pfQ("pfFileInput");
    var dropzone = pfQ("pfDropzone");
    var card = pfQ("pfFileCard");
    var nameEl = pfQ("pfCardFileName");
    var sizeEl = pfQ("pfCardFileSize");
    var btn = pfQ("pfProcessBtn");
    if (input && input.files && input.files.length > 0) {
      var file = input.files[0];
      if (nameEl) nameEl.textContent = file.name;
      if (sizeEl) sizeEl.textContent = (file.size / 1024).toFixed(1) + ' KB';
      if (dropzone) dropzone.style.display = 'none';
      if (card) card.style.display = 'flex';
      if (btn) btn.removeAttribute('disabled');
    }
  };

  window.PF_removeFile = function (e) {
    if (e) e.stopPropagation();
    var input = pfQ("pfFileInput");
    var dropzone = pfQ("pfDropzone");
    var card = pfQ("pfFileCard");
    var btn = pfQ("pfProcessBtn");
    var label = pfQ("pfFileName");
    if (input) input.value = '';
    if (label) label.textContent = 'Choose document to redact...';
    if (dropzone) dropzone.style.display = 'flex';
    if (card) card.style.display = 'none';
    if (btn) btn.setAttribute('disabled', 'true');
    var resultsSec = pfQ("pfResults");
    if (resultsSec) resultsSec.classList.add('hidden');
    var teaser = pfQ("pfEditorTeaser");
    if (teaser) teaser.style.display = 'flex';
  };

  window.PF_processRedaction = function () {
    var input = pfQ("pfFileInput");
    if (!input || !input.files.length) {
      PF_setStatus("Please choose a file first.", true);
      return;
    }
    PF_uploadFile(input.files[0]);
  };

  // Drag & drop support
  var dropzone = document.getElementById("pfDropzone");
  if (dropzone) {
    ["dragenter", "dragover"].forEach(function(evt) {
      dropzone.addEventListener(evt, function(e) {
        e.preventDefault(); e.stopPropagation();
        dropzone.style.borderColor = "var(--primary)";
        dropzone.style.background = "#f0fafb";
      });
    });
    ["dragleave", "drop"].forEach(function(evt) {
      dropzone.addEventListener(evt, function(e) {
        e.preventDefault(); e.stopPropagation();
        dropzone.style.borderColor = "";
        dropzone.style.background = "";
      });
    });
    dropzone.addEventListener("drop", function(e) {
      var files = e.dataTransfer.files;
      if (files.length) {
        var input = document.getElementById("pfFileInput");
        input.files = files;
        PF_handleFileChange();
      }
    });
  }

  // Init on page load
  PF_pingHealth();
  PF_loadSupported();
})();
</script>

<script>
/* ══════════════════════════════════════════════════════════════════════════
   pf-editor.js — Redaction editor (modified for local GUI: no auth)
   ══════════════════════════════════════════════════════════════════════════ */
""" + _get_editor_js() + r"""
</script>

<script>
/* Browser-mode heartbeat + quit button (skipped when pywebview is active) */
(function () {
  if (window.pywebview) return;

  setInterval(function () {
    fetch("/api/heartbeat", { method: "GET" }).catch(function () {});
  }, 5000);

  var footer = document.createElement("div");
  footer.style.cssText = "text-align:center; padding:12px 0 18px; background:#f8fafc;";
  footer.innerHTML = '<button onclick="if(confirm(\'Quit Privacy Filter?\'))fetch(\'/api/shutdown\',{method:\'POST\'}).then(function(){document.title=\'Closed\';document.body.innerHTML=\'<div style=padding:80px;text-align:center;font-family:sans-serif><h2>Privacy Filter stopped.</h2><p style=color:#64748b>You can close this tab.</p></div>\'})" style="display:inline-flex;align-items:center;gap:6px;padding:7px 18px;border:1px solid #e2e8f0;border-radius:8px;background:#fff;color:#64748b;font-family:inherit;font-size:0.78rem;font-weight:600;cursor:pointer;transition:all 0.2s;"><i class="fas fa-power-off"></i> Quit Application</button>';
  document.body.appendChild(footer);
})();
</script>

</body>
</html>"""

    return _HTML


def _get_editor_js() -> str:
    return r"""
(function () {
  "use strict";

  var pfQ = function(id) { return document.getElementById(id); };
  var BASE = function() { return window._PF_BASE || ""; };
  var AUTH = function() { return {}; };

  var _boxesLeft = [];
  var _boxesRight = [];
  var _boxId = 0;
  var _origPages = null;
  var _origKey = null;
  var _initialized = false;

  var _editorMode = null;
  var _active = false;
  var _boxes = [];
  var _zoom = 1;
  var _tool = "draw";
  var _undoStack = [];
  var _drawing = false;
  var _drawStart = null;
  var _drawRect = null;
  var _panState = null;

  var CLR = {
    accent: "#14868C", accentDark: "#0e6a6f",
    green: "#059669", greenHover: "#047857",
    red: "#ef4444", purple: "#8b5cf6",
    purpleBg: "rgba(139,92,246,0.15)",
    toolBg: "rgba(239,68,68,0.15)", toolBorder: "rgba(239,68,68,0.85)",
    userBg: "rgba(139,92,246,0.15)", userBorder: "rgba(139,92,246,0.85)",
    toolbar: "#1e293b", surface: "#0f172a", muted: "#94a3b8",
    dark: "#0f172a", border: "#334155", lightBorder: "#e2e8f0",
  };

  window.PF_resetEditorState = function () {
    _boxesLeft = []; _boxesRight = []; _boxId = 0;
    _origPages = null; _origKey = null; _initialized = false;
  };

  window.PF_loadPreview = async function (kind, key) {
    var viewport = pfQ(kind === "original" ? "pfPreviewOriginal" : "pfPreviewRedacted");
    var editBtn = pfQ(kind === "original" ? "pfEditOriginalBtn" : "pfEditRedactedBtn");
    if (!viewport) return;
    viewport.innerHTML = _placeholder("fa-spinner fa-spin", "Rendering preview...");
    try {
      var apiKind = key.indexOf("__redacted") >= 0 ? "redacted" : (kind === "original" ? "uploads" : "redacted");
      var r = await fetch(BASE() + "/api/render-pages/" + apiKind + "/" + encodeURIComponent(key), { headers: AUTH(), signal: AbortSignal.timeout(120000) });
      if (!r.ok) throw new Error("HTTP " + r.status);
      var data = await r.json();
      if (data.text_only) {
        viewport.innerHTML = '<pre style="width:100%;padding:12px;margin:0;white-space:pre-wrap;font-size:0.82rem;color:#334155;text-align:left;max-height:460px;overflow:auto;">' + _esc(data.text || "(empty)") + '</pre>';
        if (editBtn) editBtn.disabled = true;
        return;
      }
      _showPageImages(viewport, data.pages);
      if (kind === "original" && !_origPages) { _origPages = data.pages; _origKey = key; }
      viewport.dataset.kind = kind;
      if (editBtn) editBtn.disabled = false;
    } catch (e) {
      viewport.innerHTML = _placeholder("fa-exclamation-triangle", "Preview failed: " + _esc(e.message), "#ef4444");
      if (editBtn) editBtn.disabled = true;
    }
  };

  window.PF_updatePreview = function (kind, pages) {
    var viewport = pfQ(kind === "original" ? "pfPreviewOriginal" : "pfPreviewRedacted");
    if (!viewport || !pages) return;
    _showPageImages(viewport, pages);
    viewport.dataset.kind = kind;
    var editBtn = pfQ(kind === "original" ? "pfEditOriginalBtn" : "pfEditRedactedBtn");
    if (editBtn) editBtn.disabled = false;
  };

  window.PF_updateRedactedPreview = function (pages) { window.PF_updatePreview("redacted", pages); };

  function _showPageImages(viewport, pages) {
    viewport.innerHTML = "";
    for (var i = 0; i < pages.length; i++) {
      var pg = pages[i];
      var img = document.createElement("img");
      img.src = BASE() + pg.url + "?t=" + Date.now();
      img.alt = "Page " + (pg.page + 1);
      img.loading = "lazy";
      img.style.cssText = "max-width:100%;height:auto;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.12);margin-bottom:12px;display:block;";
      viewport.appendChild(img);
    }
  }

  window.PF_openEditor = function (kind) {
    if (!_origPages || !_origPages.length) { alert("Preview not ready. Please wait for processing to complete."); return; }
    _active = true; _zoom = 1; _tool = "draw"; _undoStack = []; _editorMode = kind;
    if (kind === "original") {
      _boxes = _boxesLeft.map(function(b) { return Object.assign({}, b); });
    } else {
      if (!_initialized) {
        _boxesRight = (window._PF_aiBoxes || []).map(function(b) { return Object.assign({}, b, { id: ++_boxId, source: b.source || "ai" }); });
        _initialized = true;
      }
      _boxes = _boxesRight.map(function(b) { return Object.assign({}, b); });
    }
    _buildEditorDOM();
    document.body.style.overflow = "hidden";
  };

  function _buildEditorDOM() {
    var old = pfQ("pfe_root");
    if (old) old.remove();
    var el = document.createElement("div");
    el.id = "pfe_root";
    el.style.cssText = "position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:999999;background:radial-gradient(circle at center, rgba(15, 23, 42, 0.97) 0%, rgba(8, 12, 24, 0.99) 100%);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);display:flex;align-items:center;justify-content:center;font-family:'Inter','Segoe UI',system-ui,sans-serif;";

    var titleStr = _editorMode === "original" ? "Edit Left (Original)" : "Edit Right (Redacted)";
    var tagColor = _editorMode === "original" ? "#38bdf8" : "#a78bfa";

    el.innerHTML = '<div style="width:98vw;height:96vh;background:#ffffff;border-radius:20px;border:1px solid rgba(255,255,255,0.1);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 40px 120px rgba(0,0,0,0.8);"><div style="display:flex;align-items:center;justify-content:space-between;padding:12px 24px;background:linear-gradient(to bottom, #1e293b, #0f172a);border-bottom:1px solid #334155;flex-shrink:0;gap:16px;"><div style="display:flex;align-items:center;gap:12px;"><div style="background:linear-gradient(135deg,#06b6d4,#0891b2);padding:6px 14px;border-radius:10px;display:flex;align-items:center;gap:8px;box-shadow:0 0 12px rgba(6,182,212,0.3);"><i class="fas fa-user-shield" style="color:#fff;font-size:0.8rem;"></i><span style="font-weight:800;font-size:0.85rem;color:#fff;letter-spacing:0.5px;text-transform:uppercase;">PII Redactor</span></div><span style="font-size:0.75rem;font-weight:600;color:' + tagColor + ';background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);padding:5px 12px;border-radius:20px;display:inline-flex;align-items:center;gap:6px;"><i class="fas fa-edit"></i>' + titleStr + '</span></div><div style="display:flex;align-items:center;gap:12px;"><div style="display:inline-flex;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:3px;align-items:center;">' + _tbtn("pfe_zout","fa-minus","Zoom Out") + '<span id="pfe_zlbl" style="font-size:0.75rem;color:#94a3b8;min-width:48px;text-align:center;font-weight:700;font-variant-numeric:tabular-nums;user-select:none;">100%</span>' + _tbtn("pfe_zin","fa-plus","Zoom In") + _tbtn("pfe_zfit","fa-expand","Fit View") + '</div><div style="display:inline-flex;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:3px;align-items:center;gap:2px;">' + _tbtn("pfe_tdraw","fa-vector-square","Draw Mode (D)",true) + _tbtn("pfe_tpan","fa-hand-paper","Pan Mode (Space)") + '</div><div style="display:inline-flex;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:3px;align-items:center;gap:2px;">' + _tbtn("pfe_undo","fa-undo","Undo (Ctrl+Z)") + _tbtn("pfe_clear","fa-trash","Clear All") + '</div></div><div style="display:flex;align-items:center;gap:8px;"><button id="pfe_apply" style="display:inline-flex;align-items:center;gap:6px;padding:9px 24px;border:none;border-radius:10px;background:linear-gradient(135deg,#059669,#10b981);color:#fff;font-family:inherit;font-size:0.82rem;font-weight:700;cursor:pointer;box-shadow:0 4px 14px rgba(16,185,129,0.3);transition:all 0.2s;"><i class="fas fa-check-circle"></i> Apply Changes</button><button id="pfe_cancel" style="display:inline-flex;align-items:center;gap:5px;padding:9px 18px;border:1px solid #334155;border-radius:10px;background:transparent;color:#94a3b8;font-family:inherit;font-size:0.8rem;font-weight:600;cursor:pointer;transition:all 0.2s;"><i class="fas fa-times"></i> Cancel</button></div></div><div style="display:flex;flex:1;overflow:hidden;background:#0f172a;"><div id="pfe_area" style="flex:1;overflow:hidden;position:relative;background-color:#0b0f19;background-image:radial-gradient(rgba(255,255,255,0.06) 1px, transparent 1px);background-size:20px 20px;"><div id="pfe_scroll" style="width:100%;height:100%;overflow:auto;cursor:crosshair;"><div id="pfe_pages" style="display:flex;flex-direction:column;align-items:center;gap:24px;padding:40px;width:max-content;min-width:100%;margin:0 auto;box-sizing:border-box;"></div></div></div><div style="width:290px;flex-shrink:0;background:#f8fafc;border-left:1px solid ' + CLR.lightBorder + ';display:flex;flex-direction:column;box-shadow:-5px 0 25px rgba(0,0,0,0.03);"><div style="padding:16px 20px;border-bottom:1px solid #e2e8f0;background:linear-gradient(135deg,#f0fafb,#e6f7f8);display:flex;align-items:center;gap:10px;flex-shrink:0;"><i class="fas fa-layer-group" style="color:' + CLR.accent + ';font-size:0.9rem;"></i><span style="font-size:0.85rem;font-weight:800;color:' + CLR.accentDark + ';letter-spacing:0.3px;">Redaction Layers</span><span id="pfe_cnt" style="margin-left:auto;background:linear-gradient(135deg,#14868C,#0e6a6f);color:#fff;font-size:0.7rem;padding:3px 10px;border-radius:99px;font-weight:800;box-shadow:0 2px 6px rgba(20,134,140,0.25);">0</span></div><div id="pfe_list" style="flex:1;overflow-y:auto;padding:12px 14px;"></div><div style="padding:14px 18px;border-top:1px solid #e2e8f0;background:#ffffff;flex-shrink:0;"><div style="font-size:0.7rem;color:' + CLR.muted + ';line-height:1.6;"><div style="margin-bottom:6px;font-weight:700;color:' + CLR.accentDark + ';">Quick Controls:</div><div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + CLR.red + ';"></span> TOOL detected redaction</div><div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + CLR.purple + ';"></span> User added redaction</div><div>• Click on any overlay box or cross button to remove it</div><div>• Canvas background shows original text details</div></div></div></div></div><div style="padding:10px 24px;background:#f8fafc;border-top:1px solid ' + CLR.lightBorder + ';font-size:0.72rem;color:#64748b;flex-shrink:0;display:flex;gap:24px;align-items:center;">' + _kbd("Drag") + ' Add Box &nbsp; ' + _kbd("Click") + ' Delete Box &nbsp; ' + _kbd("Ctrl + Scroll") + ' Zoom Canvas &nbsp; ' + _kbd("Space + Drag") + ' Pan Image &nbsp; ' + _kbd("Ctrl + Z") + ' Undo Action &nbsp; ' + _kbd("Esc") + ' Exit Editor</div></div>';

    document.body.appendChild(el);

    pfQ("pfe_zout").onclick = function() { _zoom_(Math.max(_zoom / 1.25, 0.1)); };
    pfQ("pfe_zin").onclick = function() { _zoom_(Math.min(_zoom * 1.25, 5)); };
    pfQ("pfe_zfit").onclick = _fitZ;
    pfQ("pfe_tdraw").onclick = function() { _setTool("draw"); };
    pfQ("pfe_tpan").onclick = function() { _setTool("pan"); };
    pfQ("pfe_undo").onclick = _undo;
    pfQ("pfe_clear").onclick = _clearAll;
    pfQ("pfe_apply").onclick = _apply;
    pfQ("pfe_cancel").onclick = _close;

    _renderPages();
    _renderSidebar();
    requestAnimationFrame(_fitZ);

    pfQ("pfe_scroll").onwheel = function(e) {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        var s = pfQ("pfe_scroll");
        var r = s.getBoundingClientRect();
        _zoom_(_zoom * (e.deltaY > 0 ? 0.9 : 1.1), { x: e.clientX - r.left, y: e.clientY - r.top });
      }
    };
  }

  function _tbtn(id, icon, title, active) {
    var bg = active ? "linear-gradient(135deg, #14868C, #0e6a6f)" : "transparent";
    var color = active ? "#ffffff" : "#94a3b8";
    return '<button id="' + id + '" ' + (active ? 'data-on="1"' : '') + ' style="display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border:none;border-radius:6px;background:' + bg + ';color:' + color + ';font-size:0.8rem;cursor:pointer;transition:all 0.15s ease;" title="' + title + '"><i class="fas ' + icon + '"></i></button>';
  }

  function _kbd(k) { return '<kbd style="background:#e2e8f0;border:1px solid #cbd5e1;padding:2px 7px;border-radius:4px;font-size:0.66rem;font-family:inherit;font-weight:700;color:#334155;box-shadow:0 1px 1px rgba(0,0,0,0.05);">' + k + '</kbd>'; }

  function _placeholder(icon, text, color) {
    return '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:300px;color:' + (color || CLR.muted) + ';gap:10px;"><i class="fas ' + icon + '" style="font-size:2rem;"></i><span style="font-size:0.85rem;font-weight:600;">' + text + '</span></div>';
  }

  var LBL_MAP = {
    private_person:"PERSON NAME", private_date:"DATE", address_location:"ADDRESS",
    org_name:"ORGANIZATION", phone_number:"PHONE NUMBER", email:"EMAIL",
    id_number:"IDENTIFIER", burned_in_text:"BURN IN TEXT",
    person:"PERSON NAME", date:"DATE", address:"ADDRESS", organization:"ORGANIZATION",
    phone:"PHONE NUMBER", identifier:"IDENTIFIER", phi:"PHI"
  };

  function _formatBoxLabel(box) {
    if (box.source === "user") return "USER ADDED";
    var directKey = (box.label || "").trim().toLowerCase();
    var key = directKey.replace(/^private_/, "").replace(/_/g, " ");
    if (LBL_MAP[box.label]) return LBL_MAP[box.label];
    if (LBL_MAP[directKey]) return LBL_MAP[directKey];
    if (LBL_MAP[key]) return LBL_MAP[key];
    if (!key || key === "ai" || key === "unknown") return "REDACTED";
    return key.toUpperCase();
  }

  function _close() {
    var r = pfQ("pfe_root");
    if (r) r.remove();
    document.body.style.overflow = "";
    _active = false;
  }
  window.PF_editorClose = _close;

  function _zoom_(z, anchor) {
    z = Math.max(0.1, Math.min(6, z));
    var s = pfQ("pfe_scroll");
    var ax = 0.5, ay = 0.5;
    if (s) {
      ax = anchor ? anchor.x : s.clientWidth / 2;
      ay = anchor ? anchor.y : s.clientHeight / 2;
      var beforeX = (s.scrollLeft + ax) / _zoom;
      var beforeY = (s.scrollTop + ay) / _zoom;
    }
    _zoom = z;
    _applyZoomLayout();
    var l = pfQ("pfe_zlbl");
    if (l) l.textContent = Math.round(_zoom * 100) + "%";
    if (s) {
      s.scrollLeft = beforeX * _zoom - ax;
      s.scrollTop = beforeY * _zoom - ay;
    }
  }

  function _applyZoomLayout() {
    var c = pfQ("pfe_pages");
    if (!c) return;
    Array.from(c.children).forEach(function(wrap, idx) {
      var pg = _origPages && _origPages[idx];
      if (!pg) return;
      var sw = Math.round(pg.width * _zoom);
      var sh = Math.round(pg.height * _zoom);
      wrap.style.width = sw + "px";
      wrap.style.height = sh + "px";
      var img = wrap.querySelector("img");
      if (img) { img.width = sw; img.height = sh; img.style.width = sw + "px"; img.style.height = sh + "px"; }
    });
    _renderBoxes();
  }

  function _fitZ() {
    var a = pfQ("pfe_area");
    if (!a || !_origPages || !_origPages.length) { _zoom_(1); return; }
    var maxW = Math.max.apply(null, _origPages.map(function(p) { return p.width; }));
    _zoom_(Math.min(2, (a.clientWidth - 96) / maxW));
  }

  function _setTool(t) {
    _tool = t;
    var d = pfQ("pfe_tdraw"), p = pfQ("pfe_tpan"), s = pfQ("pfe_scroll");
    [d, p].forEach(function(b) { if (b) { b.style.background = "transparent"; b.style.color = "#94a3b8"; b.dataset.on = ""; } });
    var active = t === "draw" ? d : p;
    if (active) { active.style.background = "linear-gradient(135deg, #14868C, #0e6a6f)"; active.style.color = "#ffffff"; active.dataset.on = "1"; }
    if (s) s.style.cursor = t === "pan" ? "grab" : "crosshair";
  }

  function _push() { _undoStack.push(_boxes.map(function(b) { return Object.assign({}, b); })); if (_undoStack.length > 50) _undoStack.shift(); }
  function _undo() { if (!_undoStack.length) return; _boxes = _undoStack.pop(); _renderBoxes(); _renderSidebar(); }
  function _clearAll() { if (!_boxes.length) return; _push(); _boxes = []; _renderBoxes(); _renderSidebar(); }
  window.PF_editorUndo = _undo;

  function _renderPages() {
    var c = pfQ("pfe_pages");
    if (!c || !_origPages) return;
    c.innerHTML = "";
    _origPages.forEach(function(pg, idx) {
      var sw = Math.round(pg.width * _zoom);
      var sh = Math.round(pg.height * _zoom);
      var wrap = document.createElement("div");
      wrap.dataset.page = idx;
      wrap.style.cssText = "position:relative;width:" + sw + "px;height:" + sh + "px;background:#ffffff;box-shadow:0 12px 40px rgba(0,0,0,0.6);border-radius:8px;overflow:hidden;line-height:0;flex-shrink:0;";
      var img = document.createElement("img");
      img.src = BASE() + pg.url;
      img.width = sw; img.height = sh;
      img.draggable = false;
      img.style.cssText = "display:block;max-width:none;user-select:none;width:" + sw + "px;height:" + sh + "px;";
      wrap.appendChild(img);
      var ov = document.createElement("div");
      ov.style.cssText = "position:absolute;top:0;left:0;right:0;bottom:0;z-index:1;";
      wrap.appendChild(ov);
      _mouse(ov, idx);
      c.appendChild(wrap);
    });
    _renderBoxes();
  }

  function _mouse(ov, pgIdx) {
    var xy = function(e) { var r = ov.parentElement.getBoundingClientRect(); return { x: (e.clientX - r.left) / _zoom, y: (e.clientY - r.top) / _zoom }; };
    ov.onmousedown = function(e) {
      if (e.button !== 0) return;
      e.preventDefault();
      var pos = xy(e);
      if (_tool === "pan") {
        var s = pfQ("pfe_scroll");
        _panState = { sx: e.clientX, sy: e.clientY, el: s, sl: s.scrollLeft, st: s.scrollTop };
        s.style.cursor = "grabbing"; return;
      }
      var hit = _hit(pgIdx, pos.x, pos.y);
      if (hit) { _push(); _boxes = _boxes.filter(function(b) { return b.id !== hit.id; }); _renderBoxes(); _renderSidebar(); return; }
      _drawing = true; _drawStart = { page: pgIdx, x: pos.x, y: pos.y };
      var d = document.createElement("div");
      d.id = "pfe_dr";
      d.style.cssText = "position:absolute;z-index:10;pointer-events:none;border:2.5px dashed " + CLR.purple + ";background:" + CLR.purpleBg + ";border-radius:3px;left:" + (pos.x * _zoom) + "px;top:" + (pos.y * _zoom) + "px;width:0;height:0;box-shadow:0 0 12px rgba(139,92,246,0.3);";
      ov.parentElement.appendChild(d);
      _drawRect = d;
    };
    ov.onmousemove = function(e) {
      if (_panState) { _panState.el.scrollLeft = _panState.sl - (e.clientX - _panState.sx); _panState.el.scrollTop = _panState.st - (e.clientY - _panState.sy); return; }
      if (!_drawing || !_drawRect) return;
      var pos = xy(e);
      var z = _zoom;
      _drawRect.style.left = Math.min(_drawStart.x, pos.x) * z + "px";
      _drawRect.style.top = Math.min(_drawStart.y, pos.y) * z + "px";
      _drawRect.style.width = Math.abs(pos.x - _drawStart.x) * z + "px";
      _drawRect.style.height = Math.abs(pos.y - _drawStart.y) * z + "px";
    };
    var done = function(e) {
      if (_panState) { var s = pfQ("pfe_scroll"); if (s) s.style.cursor = _tool === "pan" ? "grab" : "crosshair"; _panState = null; return; }
      if (!_drawing) return;
      _drawing = false;
      var pos = xy(e);
      var bx = Math.min(_drawStart.x, pos.x), by = Math.min(_drawStart.y, pos.y);
      var bw = Math.abs(pos.x - _drawStart.x), bh = Math.abs(pos.y - _drawStart.y);
      if (_drawRect) { _drawRect.remove(); _drawRect = null; }
      if (bw > 5 && bh > 5) {
        _push();
        _boxes.push({ id: ++_boxId, page: _drawStart.page, x: Math.round(bx), y: Math.round(by), w: Math.round(bw), h: Math.round(bh), label: "USER", source: "user" });
        _renderBoxes(); _renderSidebar();
      }
      _drawStart = null;
    };
    ov.onmouseup = done;
    ov.onmouseleave = done;
  }

  function _hit(pg, x, y) {
    for (var i = _boxes.length - 1; i >= 0; i--) {
      var b = _boxes[i];
      if (b.page === pg && x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) return b;
    }
    return null;
  }

  function _renderBoxes() {
    document.querySelectorAll("[data-pfebox]").forEach(function(e) { e.remove(); });
    var c = pfQ("pfe_pages");
    if (!c) return;
    var wraps = c.children;
    _boxes.forEach(function(box) {
      var w = wraps[box.page];
      if (!w) return;
      var isUser = box.source === "user";
      var el = document.createElement("div");
      el.setAttribute("data-pfebox", box.id);
      var z = _zoom;
      el.style.cssText = "position:absolute;z-index:2;cursor:pointer;left:" + (box.x * z) + "px;top:" + (box.y * z) + "px;width:" + (box.w * z) + "px;height:" + (box.h * z) + "px;background:rgba(15,23,42,0.92);border:1.5px solid #000;border-radius:2px;transition:background 0.15s ease-in-out,border-color 0.15s ease-in-out;box-shadow:0 1px 3px rgba(0,0,0,0.2);";
      el.title = "Click to remove redaction";
      var lbl = document.createElement("div");
      lbl.style.cssText = "position:absolute;top:-18px;left:-1px;font-size:9px;font-weight:700;color:#fff;background:" + (isUser ? CLR.purple : CLR.accent) + ";padding:1px 8px;border-radius:4px 4px 0 0;white-space:nowrap;pointer-events:none;letter-spacing:0.4px;opacity:0;transition:opacity 0.15s ease-in-out;";
      lbl.textContent = isUser ? "USER" : _formatBoxLabel(box);
      el.appendChild(lbl);
      el.onmouseenter = function() { el.style.background = "rgba(15,23,42,0.15)"; el.style.borderColor = isUser ? CLR.purple : CLR.red; lbl.style.opacity = "1"; };
      el.onmouseleave = function() { el.style.background = "rgba(15,23,42,0.92)"; el.style.borderColor = "#000"; lbl.style.opacity = "0"; };
      el.onclick = function(e) { e.stopPropagation(); _push(); _boxes = _boxes.filter(function(b) { return b.id !== box.id; }); _renderBoxes(); _renderSidebar(); };
      w.appendChild(el);
    });
  }

  function _renderSidebar() {
    var list = pfQ("pfe_list");
    var cnt = pfQ("pfe_cnt");
    if (cnt) cnt.textContent = _boxes.length;
    if (!list) return;
    if (!_boxes.length) {
      list.innerHTML = '<div style="padding:36px 16px;text-align:center;color:' + CLR.muted + ';line-height:1.7;"><i class="fas fa-draw-polygon" style="font-size:2.2rem;color:#d1d5db;display:block;margin-bottom:12px;"></i><div style="font-size:0.82rem;font-weight:600;color:#64748b;margin-bottom:4px;">No boxes yet</div><div style="font-size:0.72rem;">Click and drag on the image<br>to draw redaction areas</div></div>';
      return;
    }
    list.innerHTML = "";
    _boxes.forEach(function(box) {
      var isUser = box.source === "user";
      var color = isUser ? CLR.purple : CLR.red;
      var row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;justify-content:space-between;padding:10px 14px;margin-bottom:8px;border-radius:10px;border:1.5px solid #e2e8f0;border-left:4px solid " + color + ";background:#ffffff;box-shadow:0 2px 4px rgba(0,0,0,0.02);transition:border-color 0.15s ease,box-shadow 0.15s ease;cursor:pointer;";
      row.onmouseenter = function() { row.style.boxShadow = "0 4px 10px rgba(0,0,0,0.06)"; row.style.borderColor = color; var b = document.querySelector('[data-pfebox="' + box.id + '"]'); if (b) { b.style.background = isUser ? CLR.userBg : CLR.toolBg; b.style.borderColor = color; } };
      row.onmouseleave = function() { row.style.boxShadow = "0 2px 4px rgba(0,0,0,0.02)"; row.style.borderColor = "#e2e8f0"; row.style.background = "#ffffff"; var b = document.querySelector('[data-pfebox="' + box.id + '"]'); if (b) { b.style.background = "rgba(15,23,42,0.92)"; b.style.borderColor = "#000"; } };
      var labelText = _formatBoxLabel(box);
      row.innerHTML = '<div style="display:flex;flex-direction:column;gap:3px;flex:1;min-width:0;padding-right:8px;"><div style="display:flex;align-items:center;gap:7px;"><span style="font-size:0.74rem;font-weight:700;color:' + CLR.dark + ';">#' + box.id + '</span><span style="font-size:0.6rem;font-weight:700;color:#fff;background:' + color + ';padding:2px 7px;border-radius:4px;text-transform:uppercase;letter-spacing:0.5px;">' + (isUser ? "USER" : "TOOL") + '</span></div><span style="font-size:0.68rem;color:' + CLR.muted + ';font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="P' + (box.page + 1) + ' · ' + labelText + '">P' + (box.page + 1) + ' · ' + labelText + '</span></div><button style="flex-shrink:0;background:none;border:1px solid transparent;cursor:pointer;color:#cbd5e1;padding:6px 8px;border-radius:6px;font-size:0.85rem;display:inline-flex;align-items:center;justify-content:center;transition:all 0.12s;" title="Remove this box"><i class="fas fa-times-circle"></i></button>';
      var rm = row.querySelector("button");
      rm.onmouseenter = function() { rm.style.color = CLR.red; rm.style.background = "#fee2e2"; rm.style.borderColor = "#fecaca"; };
      rm.onmouseleave = function() { rm.style.color = "#cbd5e1"; rm.style.background = "none"; rm.style.borderColor = "transparent"; };
      rm.onclick = function(e) { e.stopPropagation(); _push(); _boxes = _boxes.filter(function(b) { return b.id !== box.id; }); _renderBoxes(); _renderSidebar(); };
      list.appendChild(row);
    });
  }

  async function _apply() {
    var btn = pfQ("pfe_apply");
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Applying...'; btn.style.opacity = "0.7"; }
    try {
      var pg = _origPages[0] || { width: 1, height: 1 };
      var body = {
        job_id: window._PF_jobId || "",
        source_key: _origKey || window._PF_uploadKey || "",
        boxes: _boxes.map(function(b) { return { page: b.page, x: b.x, y: b.y, w: b.w, h: b.h }; }),
        image_width: pg.width, image_height: pg.height, panel: _editorMode,
      };
      var r = await fetch(BASE() + "/api/apply-redactions", {
        method: "POST",
        headers: Object.assign({ "Content-Type": "application/json" }, AUTH()),
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(60000),
      });
      if (!r.ok) throw new Error(await r.text().catch(function() { return "HTTP " + r.status; }));
      var data = await r.json();

      if (_editorMode === "original") {
        _boxesLeft = _boxes.map(function(b) { return Object.assign({}, b); });
        if (data.redacted_url) { window._PF_urls = window._PF_urls || {}; window._PF_urls.original = data.redacted_url; }
        if (data.preview_pages && data.preview_pages.length) { window.PF_updatePreview("original", data.preview_pages); }
        else if (data.redacted_key) { await window.PF_loadPreview("original", data.redacted_key); }
        var dlBtn = pfQ("pfDlOriginal"); if (dlBtn) dlBtn.disabled = false;
      } else {
        _boxesRight = _boxes.map(function(b) { return Object.assign({}, b); });
        if (data.redacted_url) { window._PF_urls = window._PF_urls || {}; window._PF_urls.redacted = data.redacted_url; }
        if (data.preview_pages && data.preview_pages.length) { window.PF_updatePreview("redacted", data.preview_pages); }
        else if (data.redacted_key) { await window.PF_loadPreview("redacted", data.redacted_key); }
        var dlBtn2 = pfQ("pfDlRedacted"); if (dlBtn2) dlBtn2.disabled = false;
      }
      _close();
      if (window.showToast) window.showToast("Redactions applied successfully", "success");
    } catch (e) {
      if (window.showToast) window.showToast("Apply failed: " + e.message, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-check-circle"></i> Apply Changes'; btn.style.opacity = "1"; }
    }
  }

  document.addEventListener("keydown", function(e) {
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
"""
