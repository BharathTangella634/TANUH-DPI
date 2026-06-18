(function () {
    "use strict";

    // ── Navigation ──────────────────────────────────────────────────────────────
    function initNavigation() {
        const toggle = document.getElementById('navToggle');
        const menu = document.getElementById('navMenu');
        if (toggle && menu) {
            toggle.addEventListener('click', () => {
                const isOpen = menu.classList.toggle('open');
                toggle.querySelector('.toggle-open').style.display = isOpen ? 'none' : 'block';
                toggle.querySelector('.toggle-close').style.display = isOpen ? 'block' : 'none';
            });
        }

        document.querySelectorAll('.nav-dropdown').forEach(dd => {
            const trigger = dd.querySelector('.dropdown-trigger');
            if (!trigger) return;
            trigger.addEventListener('click', (e) => {
                if (window.innerWidth > 768) {
                    e.preventDefault();
                    return;
                }
                e.preventDefault();
                e.stopPropagation();
                document.querySelectorAll('.nav-dropdown').forEach(other => {
                    if (other !== dd) other.classList.remove('open');
                });
                dd.classList.toggle('open');
            });
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.nav-dropdown')) {
                document.querySelectorAll('.nav-dropdown').forEach(dd => dd.classList.remove('open'));
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.nav-dropdown').forEach(dd => dd.classList.remove('open'));
                if (menu) menu.classList.remove('open');
            }
        });

        // Close mobile menu on nav link click
        document.querySelectorAll('.dropdown-item, .nav-link:not(.dropdown-trigger)').forEach(link => {
            link.addEventListener('click', () => {
                if (menu) menu.classList.remove('open');
                document.querySelectorAll('.nav-dropdown').forEach(dd => dd.classList.remove('open'));
                if (toggle) {
                    toggle.querySelector('.toggle-open').style.display = 'block';
                    toggle.querySelector('.toggle-close').style.display = 'none';
                }
            });
        });
    }

    function updateActiveNav(tabName) {
        document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active'));
        const navMap = {
            'Home': 'navHome',
            'PDF2FHIR': 'navClinical',
            'PDF2NHCX': 'navInsurance',
            'PrivacyFilter': 'navPrivacyFilter',
            'ForgeryDetection': 'navForgery',
            'AboutUs': 'navAboutUs'
        };
        const id = navMap[tabName];
        if (id) {
            const el = document.getElementById(id);
            if (el) el.classList.add('active');
        }

        const servicesTrigger = document.getElementById('servicesTrigger');
        const docsTrigger = document.getElementById('docsTrigger');
        if (servicesTrigger) servicesTrigger.classList.remove('active');
        if (docsTrigger) docsTrigger.classList.remove('active');

        const servicesTabs = ['PDF2FHIR', 'PDF2NHCX', 'PrivacyFilter', 'ForgeryDetection'];
        const docsTabs = ['ClinicalDocs', 'InsuranceDocs', 'PrivacyDocs', 'ForgeryDocs'];
        
        if (servicesTabs.includes(tabName)) {
            const parent = document.getElementById(tabName);
            const isDocsActive = parent && (
                parent.querySelector('#clinical-docs')?.style.display === 'block' ||
                parent.querySelector('#insurance-docs')?.style.display === 'block' ||
                parent.querySelector('#pf-sub-docs')?.style.display === 'block' ||
                parent.querySelector('#fg-sub-docs')?.style.display === 'block'
            );

            if (isDocsActive) {
                if (docsTrigger) docsTrigger.classList.add('active');
            } else {
                if (servicesTrigger) servicesTrigger.classList.add('active');
            }
        } else if (docsTabs.includes(tabName)) {
            if (docsTrigger) docsTrigger.classList.add('active');
        }
    }

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
        const pf = isLocal ? 'http://localhost:8003' : `${window.location.origin}/privacy-filter`;
        checkServiceHealth('clinicalAiBadge', 'clinicalAiText', `${abdm}/health`, 'AI ON', 'AI OFF');
        checkServiceHealth('insuranceAiBadge', 'insuranceAiText', `${nhcx}/health`, 'AI ON', 'AI OFF');
        checkServiceHealth('pfAiBadge', 'pfAiText', `${pf}/api/health`, 'CPU READY', 'OFFLINE');
    }

    // ── Tab Management ──────────────────────────────────────────────────────────
    const loadedTabs = new Set();

    async function openTab(evt, tabName) {
        if (evt) evt.preventDefault();

        // Auth gate: redirect unauthenticated users to Login for protected service tabs
        if (window.DPI_Auth && DPI_Auth.isGatedTab(tabName) && !DPI_Auth.isLoggedIn()) {
            DPI_Auth.setPendingTab(tabName);
            tabName = 'Login';
        }

        document.querySelectorAll(".tabcontent").forEach(el => el.style.display = "none");

        const container = document.getElementById(tabName);
        if (container) {
            container.style.display = "block";

            if (!loadedTabs.has(tabName)) {
                await loadTabContent(tabName);
                loadedTabs.add(tabName);
            }

            updateActiveNav(tabName);

            if (tabName === 'Home' && window.initDashboard) window.initDashboard();
            if (tabName === 'Login' && window.DPI_Auth) DPI_Auth.initLoginPage();
            if (tabName === 'PrivacyFilter' && window.PF_init) window.PF_init();
            if (tabName === 'ForgeryDetection' && window.FG_init) window.FG_init();
            if (tabName === 'PDF2NHCX' && window.INS_init) window.INS_init();
            if (tabName === 'PDF2FHIR' && window.CLN_init) window.CLN_init();
            if ((tabName === 'PDF2FHIR' || tabName === 'PDF2NHCX' || tabName === 'ForgeryDetection') && window.initApiAccess) {
                window.initApiAccess();
            }
            checkAllServiceBadges();
        }

        if (evt) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        try { mixpanel.track('Page View', { 'page_title': tabName }); } catch (e) { }
    }

    async function loadTabContent(tabId) {
        const el = document.getElementById(tabId);
        if (!el) return;
        try {
            let fileName = tabId.toLowerCase();
            let isDoc = false;
            let docUrl = '';

            if (fileName === 'home') fileName = 'home';
            else if (fileName === 'pdf2fhir') fileName = 'clinical';
            else if (fileName === 'pdf2nhcx') fileName = 'insurance';
            else if (fileName === 'privacyfilter') fileName = 'privacyfilter';
            else if (fileName === 'forgerydetection') fileName = 'forgery';
            else if (fileName === 'aboutus') fileName = 'about';
            else if (fileName === 'login') fileName = 'login';
            else if (fileName === 'clinicaldocs') { isDoc = true; docUrl = 'docs/clinical.html'; }
            else if (fileName === 'insurancedocs') { isDoc = true; docUrl = 'docs/insurance.html'; }
            else if (fileName === 'privacydocs') { isDoc = true; docUrl = 'docs/privacyfilter.html'; }
            else if (fileName === 'forgerydocs') { isDoc = true; docUrl = 'docs/forgery.html'; }

            if (isDoc) {
                const response = await fetch(docUrl);
                if (response.ok) {
                    const text = await response.text();
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(text, 'text/html');
                    const mainContent = doc.querySelector('.docs-main');
                    if (mainContent) {
                        // Generate TOC
                        const headers = mainContent.querySelectorAll('h1, h2');
                        let tocHtml = '';
                        headers.forEach((header, idx) => {
                            const headerText = header.textContent.trim();
                            // Skip the main page title (h1 that doesn't start with a number like "1.")
                            if (header.tagName === 'H1' && !/^\d+\./.test(headerText)) {
                                return;
                            }
                            // Create standard ID if not exists
                            if (!header.id) {
                                header.id = `section-idx-${idx}-${headerText.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
                            }
                            
                            const isH2 = header.tagName === 'H2';
                            const itemClass = isH2 ? 'docs-toc-item docs-toc-item-h2' : 'docs-toc-item';
                            tocHtml += `
                                <li class="${itemClass}">
                                    <a href="#${header.id}" class="docs-toc-link" data-target="${header.id}">${headerText}</a>
                                </li>
                            `;
                        });

                        el.innerHTML = `
                            <div class="docs-tab-layout">
                                <div class="docs-tab-sidebar">
                                    <div class="docs-brand-header">
                                        <div class="docs-brand-logos">
                                            <img src="assets/tanuh.png" alt="TANUH Logo" class="docs-logo-img">
                                            <img src="assets/MoE_Logo.svg" alt="MoE Logo" class="docs-logo-img">
                                            <img src="assets/IISc_Logo.png" alt="IISc Logo" class="docs-logo-img">
                                        </div>
                                        <div class="docs-brand-title">TANUH DPI Docs</div>
                                        <div class="docs-brand-subtitle">AI Centre of Excellence</div>
                                    </div>
                                    <div class="docs-toc-container">
                                        <div class="docs-toc-title">On This Page</div>
                                        <ul class="docs-toc-list">
                                            ${tocHtml}
                                        </ul>
                                    </div>
                                </div>
                                <main class="docs-tab-main">
                                    <div class="docs-content-inner">
                                        ${mainContent.innerHTML}
                                    </div>
                                </main>
                            </div>
                        `;

                        // Add smooth scrolling click handlers to TOC links
                        const mainPane = el.querySelector('.docs-tab-main');
                        el.querySelectorAll('.docs-toc-link').forEach(link => {
                            link.addEventListener('click', (e) => {
                                e.preventDefault();
                                const targetId = link.getAttribute('data-target');
                                const targetEl = el.querySelector(`#${targetId}`);
                                if (targetEl && mainPane) {
                                    // Calculate target offset relative to mainPane scroll view
                                    const relativeTop = targetEl.getBoundingClientRect().top - mainPane.getBoundingClientRect().top + mainPane.scrollTop;
                                    mainPane.scrollTo({
                                        top: relativeTop - 20,
                                        behavior: 'smooth'
                                    });
                                    
                                    // Highlight link manually on click
                                    el.querySelectorAll('.docs-toc-link').forEach(l => l.classList.remove('active'));
                                    link.classList.add('active');
                                }
                            });
                        });

                        // Set first link active by default
                        const firstLink = el.querySelector('.docs-toc-link');
                        if (firstLink) firstLink.classList.add('active');

                        // Scrollspy implementation
                        if (mainPane) {
                            const tocLinks = el.querySelectorAll('.docs-toc-link');
                            
                            mainPane.addEventListener('scroll', () => {
                                // Query live headings in active DOM instead of detached headers array
                                const headingElements = Array.from(mainPane.querySelectorAll('h1, h2')).filter(h => h.id);
                                const containerTop = mainPane.getBoundingClientRect().top;
                                let currentActiveId = '';
                                
                                headingElements.forEach(header => {
                                    const rect = header.getBoundingClientRect();
                                    if (rect.top - containerTop <= 80) {
                                        currentActiveId = header.id;
                                    }
                                });
                                
                                if (currentActiveId) {
                                    tocLinks.forEach(link => {
                                        if (link.getAttribute('data-target') === currentActiveId) {
                                            link.classList.add('active');
                                        } else {
                                            link.classList.remove('active');
                                        }
                                    });
                                }
                            });
                        }
                    } else {
                        el.innerHTML = text;
                    }
                } else {
                    console.error(`Failed to load doc tab ${tabId}: ${response.status}`);
                }
            } else {
                const response = await fetch(`tabs/${fileName}.html`);
                if (response.ok) {
                    el.innerHTML = await response.text();
                } else {
                    console.error(`Failed to load tab ${tabId}: ${response.status}`);
                }
            }
        } catch (err) {
            console.error(`Error loading tab ${tabId}:`, err);
        }
    }

    // ── Sub-Tab Management ──────────────────────────────────────────────────────
    window.openSubTab = function (parentId, subId, btn) {
        const parent = document.getElementById(parentId);
        if (!parent) return;
        parent.querySelectorAll('.sub-content').forEach(el => el.style.display = 'none');
        parent.querySelectorAll('.sub-tab-btn').forEach(el => el.classList.remove('active'));
        const target = document.getElementById(subId);
        if (target) target.style.display = 'block';
        if (btn) btn.classList.add('active');
        updateActiveNav(parentId);
    };

    // ── Global Helpers ──────────────────────────────────────────────────────────
    window.showToast = function (title, message, type = 'error', duration = 6000) {
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
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    };

    window.updateFileName = function (inputId) {
        const input = document.getElementById(inputId);
        const labelId = inputId === 'fileFHIR' ? 'labelFHIR' : 'labelNHCX';
        const label = document.getElementById(labelId);
        if (input && input.files.length > 0 && label) {
            label.querySelector('.file-text').textContent = input.files[0].name;
        }
    };

    window.copyToClipboard = function (elementId) {
        const text = document.getElementById(elementId).textContent;
        navigator.clipboard.writeText(text).then(() => {
            window.showToast('Copied', 'JSON copied to clipboard', 'info', 2000);
        });
    };

    window.downloadJSON = function (elementId) {
        const text = document.getElementById(elementId).textContent;
        const blob = new Blob([text], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `bundle-${Date.now()}.json`;
        a.click();
    };

    window.copyCodeBlock = function (btn) {
        const pre = btn.closest('.api-code-block').querySelector('pre');
        if (!pre) return;
        navigator.clipboard.writeText(pre.textContent.trim()).then(() => {
            btn.textContent = 'Copied!';
            setTimeout(() => btn.textContent = 'Copy', 1800);
        });
    };

    window.guideNav = function (containerId, sectionId, link) {
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

    // Expose
    window.openTab = openTab;
    window.openDocTab = function (evt, tabName, subTabId) {
        if (evt) {
            evt.preventDefault();
            evt.stopPropagation();
        }
        openTab(null, tabName);
        const parent = document.getElementById(tabName);
        if (parent) {
            const btn = parent.querySelector(`.sub-tab-btn[onclick*="${subTabId}"]`);
            if (btn) {
                openSubTab(tabName, subTabId, btn);
            }
        }
    };
    window.scrollToStats = function () {
        const statsSection = document.querySelector('.stats-band');
        if (statsSection) {
            statsSection.scrollIntoView({ behavior: 'smooth' });
        }
    };

    // ── Feedback Submission ─────────────────────────────────────────────────────
    window.DPI_submitFeedback = async function (btn) {
        const wrap = btn.closest('.dpi-feedback-form-wrap');
        if (!wrap) return;
        const service = wrap.dataset.service || "Unknown";
        const nameEl = wrap.querySelector('.dpi-fb-name');
        const placeEl = wrap.querySelector('.dpi-fb-place');
        const textEl = wrap.querySelector('.dpi-fb-text');
        const feedback = (textEl?.value || "").trim();
        if (!feedback) {
            window.showToast?.("Missing Feedback", "Please write your feedback before submitting.", "error", 4000);
            textEl?.focus();
            return;
        }
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Submitting...';
        const isLocal = window.location.hostname === 'localhost';
        const loggerUrl = isLocal ? 'http://localhost:8002' : `${window.location.origin}/session-logger`;
        try {
            const r = await fetch(`${loggerUrl}/logs/feedback`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    service, name: (nameEl?.value || "").trim() || "Anonymous",
                    place: (placeEl?.value || "").trim() || "Anonymous place",
                    feedback, ip_address: null,
                }),
                signal: AbortSignal.timeout(10000),
            });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            if (nameEl) nameEl.value = "";
            if (placeEl) placeEl.value = "";
            if (textEl) textEl.value = "";
            window.showToast?.("Thank You!", "Your feedback has been submitted successfully.", "info", 5000);
        } catch (e) {
            window.showToast?.("Submission Failed", `Could not submit feedback: ${e.message}`, "error", 5000);
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-paper-plane"></i> Submit Feedback';
        }
    };

    // ── Init ────────────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        initNavigation();
        openTab(null, 'Home');
        setInterval(checkAllServiceBadges, 30000);
        if (window.DPI_Auth) {
            DPI_Auth.updateNavAuthState();
            // Set avatar initial from user name
            const user = DPI_Auth.getUser();
            if (user && user.name) {
                const avatar = document.getElementById('navUserAvatar');
                if (avatar) avatar.textContent = user.name.charAt(0).toUpperCase();
            }
        }
    });

})();
