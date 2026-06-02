/**
 * main.js - Core orchestrator and shared helpers
 */
(function() {
    "use strict";

    // ── Per-Service AI Status Badges ────────────────────────────────────────────
    async function checkServiceHealth(badgeId, textId, url, onLabel, offLabel) {
        const badge = document.getElementById(badgeId);
        const textEl = document.getElementById(textId);
        if (!badge || !textEl) return;
        try {
            const r = await fetch(url, { method: 'GET', signal: AbortSignal.timeout(12000) });
            if (r.ok) {
                badge.classList.remove('ai-badge-off');
                textEl.textContent = onLabel;
            } else { throw new Error('Down'); }
        } catch (err) {
            badge.classList.add('ai-badge-off');
            textEl.textContent = offLabel;
        }
    }

    function checkAllServiceBadges() {
        const isLocal = window.location.hostname === 'localhost';
        const abdm = isLocal ? 'http://localhost:8000' : `${window.location.origin}/pdf2abdm`;
        const nhcx = isLocal ? 'http://localhost:8001' : `${window.location.origin}/pdf2nhcx`;
        const pf   = isLocal ? 'http://localhost:8003' : `${window.location.origin}/privacy-filter`;
        checkServiceHealth('clinicalAiBadge', 'clinicalAiText', `${abdm}/health`, 'AI ON', 'AI OFF');
        checkServiceHealth('insuranceAiBadge', 'insuranceAiText', `${nhcx}/health`, 'AI ON', 'AI OFF');
        checkServiceHealth('pfAiBadge', 'pfAiText', `${pf}/api/health`, 'CPU READY', 'OFFLINE');
    }

    // ── Tab Management ──────────────────────────────────────────────────────────
    const loadedTabs = new Set();

    async function openTab(evt, tabName) {
        document.querySelectorAll(".tabcontent").forEach(el => el.style.display = "none");
        document.querySelectorAll(".tablinks").forEach(el => el.classList.remove("active"));

        const contentWrap = document.querySelector('.content-container');
        if (contentWrap) contentWrap.classList.toggle('full-width-home', tabName === 'Home');

        const container = document.getElementById(tabName);
        if (container) {
            container.style.display = "block";
            if (evt && evt.currentTarget) evt.currentTarget.classList.add("active");

            if (!loadedTabs.has(tabName)) {
                await loadTabContent(tabName);
                loadedTabs.add(tabName);
            }

            if (tabName === 'Home' && window.initDashboard) window.initDashboard();
            if (tabName === 'PrivacyFilter' && window.PF_init) window.PF_init();
            if ((tabName === 'PDF2FHIR' || tabName === 'PDF2NHCX' || tabName === 'ForgeryDetection') && window.initApiAccess) {
                window.initApiAccess();
            }
            checkAllServiceBadges();

            const aiBadgeBar = document.querySelector('.header-ai-bar');
            if (aiBadgeBar) {
                aiBadgeBar.style.display = (tabName === 'ForgeryDetection') ? 'none' : '';
            }
        }

        // Smoothly scroll back to the top when navigating to a new tab
        if (evt) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        try { mixpanel.track('Page View', { 'page_title': tabName }); } catch(e) {}
    }

    async function loadTabContent(tabId) {
        const el = document.getElementById(tabId);
        if (!el) return;
        try {
            let fileName = tabId.toLowerCase();
            if (fileName === 'home') fileName = 'home';
            else if (fileName === 'pdf2fhir') fileName = 'clinical';
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

    // ── Guide Sidebar Navigation (show/hide sections) ────────────────────────
    window.guideNav = function(containerId, sectionId, link) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.querySelectorAll('.guide-section').forEach(s => s.classList.remove('active'));
        const section = document.getElementById(sectionId);
        if (section) section.classList.add('active');
        container.querySelectorAll('.guide-sidebar a').forEach(a => a.classList.remove('active'));
        if (link) link.classList.add('active');
        const content = container.querySelector('.guide-content');
        if (content) content.scrollTop = 0;
    };

    // Expose Tab functions
    window.openTab = openTab;

    // Init
    document.addEventListener('DOMContentLoaded', () => {
        openTab(null, 'Home');
        document.getElementById('navHome')?.classList.add('active');
        if (window.initDashboard) window.initDashboard();
        setInterval(checkAllServiceBadges, 30000);
    });

})();
