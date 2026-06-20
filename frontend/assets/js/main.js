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
                if (window.innerWidth > 1150) {
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
        document.querySelectorAll('.dropdown-item, .nav-link:not(.dropdown-trigger), .nav-login, .nav-logout-btn, .nav-brand').forEach(link => {
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

    // ── Global Config & Fallback Router ──────────────────────────────────────────
    const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    window.DPI_API_CONFIG = {
        abdm: isLocal ? 'http://localhost:8000' : `${window.location.origin}/pdf2abdm`,
        nhcx: isLocal ? 'http://localhost:8001' : `${window.location.origin}/pdf2nhcx`,
        logger: isLocal ? 'http://localhost:8002' : `${window.location.origin}/session-logger`,
        pf: isLocal ? 'http://localhost:8003' : `${window.location.origin}/privacy-filter`,
        forgensic: isLocal ? 'http://localhost:8004' : `${window.location.origin}/forgensic`
    };

    let localCheckDone = false;
    async function checkLocalBackend() {
        if (!isLocal || localCheckDone) return;
        try {
            // Check if local abdm is listening
            const r = await fetch('http://localhost:8000/health', { method: 'GET', signal: AbortSignal.timeout(1500) });
            if (r.ok) {
                console.log("Local backend active. Using localhost endpoints.");
            } else {
                throw new Error("Local offline");
            }
        } catch (e) {
            console.log("Local backend offline. Redirecting API requests to dpi.tanuh.ai");
            window.DPI_API_CONFIG.abdm = 'https://dpi.tanuh.ai/pdf2abdm';
            window.DPI_API_CONFIG.nhcx = 'https://dpi.tanuh.ai/pdf2nhcx';
            window.DPI_API_CONFIG.logger = 'https://dpi.tanuh.ai/session-logger';
            window.DPI_API_CONFIG.pf = 'https://dpi.tanuh.ai/privacy-filter';
            window.DPI_API_CONFIG.forgensic = 'https://dpi.tanuh.ai/forgensic';
            
            if (window._PF_BASE !== undefined) window._PF_BASE = window.DPI_API_CONFIG.pf;
        }
        localCheckDone = true;
        checkAllServiceBadges();
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
        const abdm = window.DPI_API_CONFIG.abdm;
        const nhcx = window.DPI_API_CONFIG.nhcx;
        const isCloudAbdm = abdm.includes('dpi.tanuh.ai');
        const isCloudNhcx = nhcx.includes('dpi.tanuh.ai');

        checkServiceHealth('clinicalAiBadge', 'clinicalAiText', `${abdm}/health`, isCloudAbdm ? 'AI CLOUD' : 'AI ON', 'AI OFF');
        checkServiceHealth('insuranceAiBadge', 'insuranceAiText', `${nhcx}/health`, isCloudNhcx ? 'AI CLOUD' : 'AI ON', 'AI OFF');
    }

    // ── Tab Management ──────────────────────────────────────────────────────────
    const loadedTabs = new Set();

    async function openTab(evt, tabName, skipScroll) {
        if (evt) evt.preventDefault();

        document.querySelectorAll(".tabcontent").forEach(el => el.style.display = "none");

        // Hide site footer on the login page to keep it clean and non-scrollable
        const footer = document.getElementById("footer");
        if (footer) {
            footer.style.display = (tabName === 'Login') ? 'none' : 'block';
        }

        const container = document.getElementById(tabName);
        if (container) {
            container.style.display = "block";

            if (!loadedTabs.has(tabName)) {
                await loadTabContent(tabName);
                loadedTabs.add(tabName);
            }

            updateActiveNav(tabName);

            if (tabName === 'Home' && window.initDashboard) window.initDashboard();
            
            // Initialize scroll reveal on all tabs after content has been rendered
            setTimeout(() => {
                initScrollReveal();
                if (tabName === 'Home' && window.initHeroParticles) window.initHeroParticles();
            }, 180);
            if (tabName === 'Login' && window.DPI_Auth) DPI_Auth.initLoginPage();
            if (tabName === 'PrivacyFilter' && window.PF_init) window.PF_init();
            if (tabName === 'ForgeryDetection' && window.FG_init) window.FG_init();
            if (tabName === 'PDF2NHCX' && window.INS_init) window.INS_init();
            if (tabName === 'PDF2FHIR' && window.CLN_init) window.CLN_init();
            if ((tabName === 'PDF2FHIR' || tabName === 'PDF2NHCX' || tabName === 'ForgeryDetection' || tabName === 'PrivacyFilter' || tabName === 'APIAccess') && window.initApiAccess) {
                window.initApiAccess();
            }
            checkAllServiceBadges();
            if (window.DPI_Auth) DPI_Auth.updateNavAuthState();

            // Handle pending direct service launch
            const pendingLaunch = sessionStorage.getItem('pendingLaunchService');
            if (pendingLaunch === tabName) {
                sessionStorage.removeItem('pendingLaunchService');
                setTimeout(() => {
                    if (tabName === 'PDF2FHIR' && window.CLN_launchService) CLN_launchService();
                    else if (tabName === 'PDF2NHCX' && window.INS_launchService) INS_launchService();
                    else if (tabName === 'PrivacyFilter' && window.PF_launchService) PF_launchService();
                    else if (tabName === 'ForgeryDetection' && window.FG_launchService) FG_launchService();
                }, 300);
            }
        }

        if (!skipScroll) {
            window.scrollTo(0, 0);
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
            else if (fileName === 'apiaccess') fileName = 'apiaccess';
            else if (fileName === 'download') fileName = 'download';
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
                const response = await fetch(`tabs/${fileName}.html?v=14`);
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
        const icons = { error: 'fa-circle-xmark', warn: 'fa-triangle-exclamation', info: 'fa-circle-info', success: 'fa-circle-check' };
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
    window.openTabAndScrollTo = async function (tabName, elementId) {
        await openTab(null, tabName, true);
        setTimeout(() => {
            const el = document.getElementById(elementId);
            if (el) {
                const navbar = document.getElementById('mainNav');
                const navbarHeight = navbar ? navbar.offsetHeight : 80;
                const elementPosition = el.getBoundingClientRect().top + window.pageYOffset;
                const offsetPosition = elementPosition - navbarHeight - 20;
                window.scrollTo({
                    top: offsetPosition,
                    behavior: 'smooth'
                });
            }
        }, 50);
    };
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
    window.directLaunchService = function (tabName, subTabId) {
        sessionStorage.setItem('pendingLaunchService', tabName);
        if (subTabId) {
            sessionStorage.setItem('pendingLaunchSubTab', subTabId);
        } else {
            sessionStorage.removeItem('pendingLaunchSubTab');
        }
        
        // Find navbar nav items and activate correct one
        let navId = '';
        if (tabName === 'PDF2FHIR') navId = 'navClinical';
        else if (tabName === 'ForgeryDetection') navId = 'navForgery';
        else if (tabName === 'PDF2NHCX') navId = 'navInsurance';
        else if (tabName === 'PrivacyFilter') navId = 'navPrivacyFilter';
        
        if (navId) {
            document.querySelectorAll('.navbar .nav-link, .navbar .dropdown-item').forEach(el => el.classList.remove('active'));
            const navEl = document.getElementById(navId);
            if (navEl) navEl.classList.add('active');
        }

        if (window.DPI_Auth && !DPI_Auth.isLoggedIn()) {
            DPI_Auth.setPendingTab(tabName);
            openTab(null, 'Login');
        } else {
            openTab(null, tabName);
        }
    };
    window.togglePasswordVisibility = function (inputId, btn) {
        const input = document.getElementById(inputId);
        if (!input) return;
        
        btn.classList.add('toggled');
        setTimeout(() => {
            btn.classList.remove('toggled');
        }, 450);

        // Clean professional fade transition to hide the abrupt character swap
        input.classList.add('is-toggling');
        setTimeout(() => {
            if (input.type === 'password') {
                input.type = 'text';
                btn.classList.add('is-active');
            } else {
                input.type = 'password';
                btn.classList.remove('is-active');
            }
            input.classList.remove('is-toggling');
        }, 100);
    };
    window.scrollToStats = function () {
        const statsSection = document.querySelector('.stats-band');
        if (statsSection) {
            const navbar = document.getElementById('mainNav');
            const navbarHeight = navbar ? navbar.offsetHeight : 90;
            const topOffset = statsSection.getBoundingClientRect().top + window.pageYOffset - navbarHeight - 20;
            window.scrollTo({
                top: topOffset,
                behavior: 'smooth'
            });
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



    // ── Intersection Observer Scroll Reveal ────────────────────────────────────
    function initScrollReveal() {
        const items = document.querySelectorAll('.feature-item, .eco-card, .geo-card, .reveal-on-scroll, .docs-content-inner h1, .docs-content-inner h2, .docs-content-inner h3, .docs-content-inner .table-responsive, .docs-content-inner pre, .fg-team-card');

        // Fail-open: if the observer is unavailable, show everything immediately
        // rather than leaving elements stuck at opacity:0.
        if (!('IntersectionObserver' in window)) {
            items.forEach(el => el.classList.add('reveal-on-scroll', 'revealed'));
            return;
        }

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('revealed');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.01, rootMargin: '0px 0px -20px 0px' });

        items.forEach(el => {
            el.classList.add('reveal-on-scroll');
            observer.observe(el);
        });
    }

    // ── Connected Particles Hero Canvas (MONAI-inspired) ─────────────────────
    window.initHeroParticles = function() {
        const hero = document.querySelector('.hero');
        const canvas = document.querySelector('.hero-particles-canvas');
        if (!hero || !canvas) return;
        
        const ctx = canvas.getContext('2d');
        let width = canvas.width = hero.offsetWidth;
        let height = canvas.height = hero.offsetHeight;
        
        window.addEventListener('resize', () => {
            if (canvas && hero) {
                width = canvas.width = hero.offsetWidth;
                height = canvas.height = hero.offsetHeight;
            }
        });
        
        const particles = [];
        const particleCount = Math.min(50, Math.floor((width * height) / 18000));
        const connectionDistance = 120;
        
        class Particle {
            constructor() {
                this.x = Math.random() * width;
                this.y = Math.random() * height;
                this.vx = (Math.random() - 0.5) * 0.35;
                this.vy = (Math.random() - 0.5) * 0.35;
                this.radius = Math.random() * 1.5 + 1.2;
            }
            update() {
                this.x += this.vx;
                this.y += this.vy;
                
                if (this.x < 0 || this.x > width) this.vx = -this.vx;
                if (this.y < 0 || this.y > height) this.vy = -this.vy;
            }
            draw() {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(20, 134, 140, 0.16)';
                ctx.fill();
            }
        }
        
        for (let i = 0; i < particleCount; i++) {
            particles.push(new Particle());
        }
        
        let frameId;
        function animate() {
            ctx.clearRect(0, 0, width, height);
            
            for (let i = 0; i < particles.length; i++) {
                particles[i].update();
                particles[i].draw();
                
                for (let j = i + 1; j < particles.length; j++) {
                    const dx = particles[i].x - particles[j].x;
                    const dy = particles[i].y - particles[j].y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    
                    if (dist < connectionDistance) {
                        const alpha = (1 - dist / connectionDistance) * 0.12;
                        ctx.beginPath();
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.strokeStyle = `rgba(20, 134, 140, ${alpha})`;
                        ctx.lineWidth = 0.7;
                        ctx.stroke();
                    }
                }
            }
            frameId = requestAnimationFrame(animate);
        }
        
        animate();
    };

    // ── Navbar Scroll Class Toggle (Light/Translucent styling) ─────────────────
    function handleNavbarScroll() {
        const nav = document.getElementById('mainNav');
        if (!nav) return;
        if (window.scrollY > 20) {
            nav.classList.add('navbar-scrolled');
            nav.classList.remove('navbar-transparent');
        } else {
            nav.classList.add('navbar-transparent');
            nav.classList.remove('navbar-scrolled');
        }
    }

    // ── Init ────────────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        initNavigation();
        checkLocalBackend(); // silent fallback router check
        
        // Setup scrolled navbar toggler
        handleNavbarScroll();
        window.addEventListener('scroll', handleNavbarScroll);
        
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
