/**
 * apiaccess.js - Secure Centralized API Access Experience (Session 2)
 * Manages token requests, view/hide toggles, storage persistence, and visual expiry highlighting.
 */
(function() {
    "use strict";

    // ── Configuration for all four services ─────────────────────────────────
    const SERVICES = [
        {
            id:         "pdf2abdm",
            formId:     "apiAbdmTokenForm",
            submitId:   "apiAbdmTokenSubmit",
            resultId:   "apiAbdmTokenResult",
            outputId:   "apiAbdmTokenOutput",
            greetingId: "apiAbdmTokenGreeting",
            expiryId:   "apiAbdmTokenExpiry",
            errorId:    "apiAbdmTokenError",
            viewId:     "apiAbdmTokenView",
            copyId:     "apiAbdmTokenCopy",
            storageKey: "dpi_token_pdf2abdm",
            expiresKey: "dpi_token_expires_pdf2abdm",
            statusKey:  "dpi_token_status_pdf2abdm"
        },
        {
            id:         "pdf2nhcx",
            formId:     "apiNhcxTokenForm",
            submitId:   "apiNhcxTokenSubmit",
            resultId:   "apiNhcxTokenResult",
            outputId:   "apiNhcxTokenOutput",
            greetingId: "apiNhcxTokenGreeting",
            expiryId:   "apiNhcxTokenExpiry",
            errorId:    "apiNhcxTokenError",
            viewId:     "apiNhcxTokenView",
            copyId:     "apiNhcxTokenCopy",
            storageKey: "dpi_token_pdf2nhcx",
            expiresKey: "dpi_token_expires_pdf2nhcx",
            statusKey:  "dpi_token_status_pdf2nhcx"
        },
        {
            id:         "privacy_filter",
            formId:     "apiPrivacyTokenForm",
            submitId:   "apiPrivacyTokenSubmit",
            resultId:   "apiPrivacyTokenResult",
            outputId:   "apiPrivacyTokenOutput",
            greetingId: "apiPrivacyTokenGreeting",
            expiryId:   "apiPrivacyTokenExpiry",
            errorId:    "apiPrivacyTokenError",
            viewId:     "apiPrivacyTokenView",
            copyId:     "apiPrivacyTokenCopy",
            storageKey: "dpi_token_privacy_filter",
            expiresKey: "dpi_token_expires_privacy_filter",
            statusKey:  "dpi_token_status_privacy_filter"
        },
        {
            id:         "forgensic",
            formId:     "apiForgeryTokenForm",
            submitId:   "apiForgeryTokenSubmit",
            resultId:   "apiForgeryTokenResult",
            outputId:   "apiForgeryTokenOutput",
            greetingId: "apiForgeryTokenGreeting",
            expiryId:   "apiForgeryTokenExpiry",
            errorId:    "apiForgeryTokenError",
            viewId:     "apiForgeryTokenView",
            copyId:     "apiForgeryTokenCopy",
            storageKey: "dpi_token_forgensic",
            expiresKey: "dpi_token_expires_forgensic",
            statusKey:  "dpi_token_status_forgensic"
        }
    ];

    // ── Expiry Formatter with Color Highlights ──────────────────────────────
    function formatExpiry(expiryStr) {
        const d = new Date(expiryStr);
        if (isNaN(d.getTime())) return { text: "Unknown Expiry", color: "#64748b" };

        const now = new Date();
        const diffMs = d - now;
        const diffHrs = diffMs / (1000 * 60 * 60);

        let color = "#10b981"; // green
        if (diffMs <= 0) {
            color = "#ef4444"; // red
        } else if (diffHrs < 6) {
            color = "#f97316"; // orange
        }

        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const dd = d.getDate();
        const mon = months[d.getMonth()];
        const yyyy = d.getFullYear();
        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        
        let tz = "";
        try {
            tz = " " + d.toLocaleDateString('en-US', { day: 'numeric', timeZoneName: 'short' }).split(', ').pop().split(' ').pop();
        } catch {
            tz = " UTC";
        }

        const formatted = `${dd} ${mon} ${yyyy} ${hh}:${mm}${tz}`;
        return { text: formatted, color: color, expired: diffMs <= 0 };
    }

    // ── Local Resolve logger url helper ─────────────────────────────────────
    function _resolveLoggerBase() {
        if (window.DPI_API_CONFIG && window.DPI_API_CONFIG.logger) {
            return window.DPI_API_CONFIG.logger;
        }
        const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
        return isLocal ? 'http://localhost:8002' : window.location.origin;
    }

    // ── Core Service Access Manager ─────────────────────────────────────────
    function manageServiceCard(cfg) {
        const form = document.getElementById(cfg.formId);
        const resultEl = document.getElementById(cfg.resultId);
        const outputEl = document.getElementById(cfg.outputId);
        const greetingEl = document.getElementById(cfg.greetingId);
        const expiryEl = document.getElementById(cfg.expiryId);
        const errorEl = document.getElementById(cfg.errorId);
        const viewBtn = document.getElementById(cfg.viewId);
        const copyBtn = document.getElementById(cfg.copyId);

        if (!form) return;

        let activeToken = localStorage.getItem(cfg.storageKey);
        let activeExpires = localStorage.getItem(cfg.expiresKey);
        let activeStatus = localStorage.getItem(cfg.statusKey);
        let isMasked = true;

        // Masking helper
        function updateMaskState() {
            if (!outputEl) return;
            if (isMasked) {
                outputEl.textContent = "••••••••••••••••••••••••••••••••";
                if (viewBtn) viewBtn.innerHTML = '<i class="fas fa-eye"></i> View';
            } else {
                outputEl.textContent = activeToken;
                if (viewBtn) viewBtn.innerHTML = '<i class="fas fa-eye-slash"></i> Hide';
            }
        }

        // Render card results state
        function renderResult(token, expires, status) {
            activeToken = token;
            activeExpires = expires;
            activeStatus = status;

            // Save variables to survive page refreshes
            localStorage.setItem(cfg.storageKey, token);
            localStorage.setItem(cfg.expiresKey, expires);
            localStorage.setItem(cfg.statusKey, status);

            isMasked = true;
            updateMaskState();

            // Handle greeting
            if (greetingEl) {
                if (status === "existing_token_returned" || status === "restored") {
                    greetingEl.textContent = "Token already generated today.";
                    greetingEl.style.color = "#0e6a6f";
                } else {
                    greetingEl.textContent = "Token is generated successfully!";
                    greetingEl.style.color = "var(--primary)";
                }
            }

            if (expiryEl && expires) {
                const info = formatExpiry(expires);
                expiryEl.innerHTML = '<i class="fas fa-clock" style="margin-right:4px;"></i>Expires: ' + info.text;
                expiryEl.style.color = info.color;
            }

            // Hide the Request form and "Generate Token" button completely so no duplicate submission/regeneration is possible
            form.style.display = "none";
            resultEl?.classList.remove('hidden');
            errorEl?.classList.add('hidden');
        }

        // Check if there is already an unexpired token in local storage on page refresh
        if (activeToken && activeExpires) {
            const expTime = new Date(activeExpires).getTime();
            if (expTime > Date.now()) {
                renderResult(activeToken, activeExpires, "restored");
            } else {
                // Expired — clear values
                localStorage.removeItem(cfg.storageKey);
                localStorage.removeItem(cfg.expiresKey);
                localStorage.removeItem(cfg.statusKey);
                form.style.display = "block";
                resultEl?.classList.add('hidden');
            }
        } else {
            form.style.display = "block";
            resultEl?.classList.add('hidden');
        }

        // View/Hide button listener
        if (viewBtn) {
            viewBtn.replaceWith(viewBtn.cloneNode(true)); // remove duplicate listeners
            const newViewBtn = document.getElementById(cfg.viewId);
            newViewBtn.addEventListener('click', () => {
                isMasked = !isMasked;
                updateMaskState();
            });
        }

        // Copy button listener
        if (copyBtn) {
            copyBtn.replaceWith(copyBtn.cloneNode(true));
            const newCopyBtn = document.getElementById(cfg.copyId);
            newCopyBtn.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(activeToken);
                    newCopyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
                    setTimeout(() => { newCopyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy'; }, 2000);
                } catch {
                    alert("Copy failed. Please manually select the token.");
                }
            });
        }

        // Form Submit Handler (Generate Token)
        form.replaceWith(form.cloneNode(true));
        const newForm = document.getElementById(cfg.formId);
        newForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = newForm.querySelector('button[type="submit"]');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Requesting…';
            errorEl?.classList.add('hidden');

            try {
                const firebaseToken = window.DPI_Auth ? await DPI_Auth.getToken() : null;
                if (!firebaseToken) {
                    throw new Error("No active Firebase session found. Please sign in again.");
                }

                const base = _resolveLoggerBase();
                const r = await fetch(`${base}/auth/token`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${firebaseToken}`
                    },
                    body: JSON.stringify({ service: cfg.id })
                });

                if (r.status === 401) {
                    throw new Error("Authentication failed: invalid or expired Firebase session.");
                }
                if (r.status === 403) {
                    throw new Error("Authorization failed: Account is not authorized to generate API developer tokens.");
                }

                const data = await r.json();
                if (!r.ok) {
                    throw new Error(data.detail || `HTTP Error ${r.status}`);
                }

                renderResult(data.access_token, data.expires_at, data.status);
                window.showToast('Token Securely Issued', 'Save or copy your token below.', 'success');

            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message;
                    errorEl.classList.remove('hidden');
                }
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-bolt"></i> Generate Token';
            }
        });
    }

    // ── Public global initialization hook ───────────────────────────────────
    window.initApiAccess = function() {
        const isLoggedIn = window.DPI_Auth && window.DPI_Auth.isLoggedIn();
        const gate = document.getElementById("apiAccessAuthGate");
        const content = document.getElementById("apiAccessGatedContent");

        if (isLoggedIn) {
            gate?.classList.add("hidden");
            content?.classList.remove("hidden");
            
            // Manage and bootstrap all 4 service cards securely
            SERVICES.forEach(manageServiceCard);
        } else {
            gate?.classList.remove("hidden");
            content?.classList.add("hidden");
        }
    };


})();
