/**
 * main.js - Core orchestrator and shared helpers
 */
(function() {
    "use strict";

    // ── AI Status Badge ─────────────────────────────────────────────────────────
    async function checkAiStatus() {
        const badge  = document.getElementById('aiBadge');
        const textEl = document.getElementById('aiBadgeText');
        if (!badge || !textEl) return;

        const isLocal = window.location.hostname === 'localhost';
        const base1 = isLocal ? 'http://localhost:8000' : `${window.location.origin}/pdf2abdm`;
        const base2 = isLocal ? 'http://localhost:8001' : `${window.location.origin}/pdf2nhcx`;

        try {
            const [r1, r2] = await Promise.all([
                fetch(`${base1}/health`, { method: 'GET', signal: AbortSignal.timeout(12000) }),
                fetch(`${base2}/health`, { method: 'GET', signal: AbortSignal.timeout(12000) })
            ]);

            if (r1.ok && r2.ok) {
                badge.classList.remove('ai-badge-off');
                textEl.textContent = 'AI ON';
            } else {
                throw new Error('Down');
            }
        } catch (err) {
            badge.classList.add('ai-badge-off');
            textEl.textContent = 'AI OFF';
        }
    }

    // ── Tab Management ──────────────────────────────────────────────────────────
    const loadedTabs = new Set();

    async function openTab(evt, tabName) {
        document.querySelectorAll(".tabcontent").forEach(el => el.style.display = "none");
        document.querySelectorAll(".tablinks").forEach(el => el.classList.remove("active"));

        const container = document.getElementById(tabName);
        if (container) {
            container.style.display = "block";
            if (evt && evt.currentTarget) evt.currentTarget.classList.add("active");

            if (!loadedTabs.has(tabName)) {
                await loadTabContent(tabName);
                loadedTabs.add(tabName);
            }

            if (tabName === 'Dashboard' && window.initDashboard) window.initDashboard();
            if (tabName === 'PrivacyFilter' && window.PF_init) window.PF_init();
            if ((tabName === 'PDF2FHIR' || tabName === 'PDF2NHCX') && window.initApiAccess) window.initApiAccess();
        }

        try { mixpanel.track('Page View', { 'page_title': tabName }); } catch(e) {}
    }

    async function loadTabContent(tabId) {
        const el = document.getElementById(tabId);
        if (!el) return;
        try {
            let fileName = tabId.toLowerCase();
            if (fileName === 'pdf2fhir') fileName = 'clinical';
            else if (fileName === 'pdf2nhcx') fileName = 'insurance';
            else if (fileName === 'privacyfilter') fileName = 'privacyfilter';
            else if (fileName === 'forgerydetection') fileName = 'forgery';
            else if (fileName === 'aboutus') fileName = 'about';

            const response = await fetch(`tabs/${fileName}.html`);
            if (response.ok) {
                el.innerHTML = await response.text();
            } else {
                console.error(`Failed to load tab ${tabId}: ${response.status}`);
            }
        } catch (err) {
            console.error(`Error loading tab ${tabId}:`, err);
        }
    }

    // ── Sub-Tab Management ──────────────────────────────────────────────────────
    window.openSubTab = function(parentId, subId, btn) {
        const parent = document.getElementById(parentId);
        if (!parent) return;
        parent.querySelectorAll('.sub-content').forEach(el => el.style.display = 'none');
        parent.querySelectorAll('.sub-tab-btn').forEach(el => el.classList.remove('active'));
        const target = document.getElementById(subId);
        if (target) target.style.display = 'block';
        if (btn) btn.classList.add('active');

    };

    // ── Global Helpers ──────────────────────────────────────────────────────────
    window.showToast = function(title, message, type = 'error', duration = 6000) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const icons = { error: 'fa-circle-xmark', warn: 'fa-triangle-exclamation', info: 'fa-circle-info' };
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <i class="fas ${icons[type] || icons.error} toast-icon"></i>
            <div class="toast-body">
                <div class="toast-title">${title}</div>
                <div class="toast-msg">${message}</div>
            </div>`;
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('toast-hide');
            toast.addEventListener('animationend', () => toast.remove());
        }, duration);
    };

    window.updateFileName = function(inputId) {
        const input = document.getElementById(inputId);
        const labelId = inputId === 'fileFHIR' ? 'labelFHIR' : 'labelNHCX';
        const label = document.getElementById(labelId);
        if (input && input.files.length > 0 && label) {
            label.querySelector('.file-text').textContent = input.files[0].name;
        }
    };

    window.copyToClipboard = function(elementId) {
        const text = document.getElementById(elementId).textContent;
        navigator.clipboard.writeText(text).then(() => {
            window.showToast('Copied', 'JSON copied to clipboard', 'info', 2000);
        });
    };

    window.downloadJSON = function(elementId) {
        const text = document.getElementById(elementId).textContent;
        const blob = new Blob([text], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `bundle-${Date.now()}.json`;
        a.click();
    };

    window.copyCodeBlock = function(btn) {
        const pre = btn.closest('.api-code-block').querySelector('pre');
        if (!pre) return;
        navigator.clipboard.writeText(pre.textContent.trim()).then(() => {
            btn.textContent = 'Copied!';
            setTimeout(() => btn.textContent = 'Copy', 1800);
        });
    };

    // Expose Tab functions
    window.openTab = openTab;

    // Init
    document.addEventListener('DOMContentLoaded', () => {
        checkAiStatus();
        setInterval(checkAiStatus, 30000);
        openTab(null, 'PDF2FHIR');
        document.getElementById('navClinical')?.classList.add('active');
        if (window.initDashboard) window.initDashboard();
    });

})();
