/**
 * apiaccess.js - Logic for the API Access tab
 * Each service (ABDM, NHCX, Forgery) has its own form and token.
 */
(function() {
    "use strict";

    // ── Generic token request handler ─────────────────────────────────────────
    async function handleTokenRequest(config) {
        const { formId, endpoint, storageKey, resultId, greetingId, expiryId, outputId, errorId, copyId } = config;

        const form = document.getElementById(formId);
        if (!form) return;

        // If we already have a token stored, show it as "active"
        const existing = sessionStorage.getItem(storageKey);
        if (existing) {
            _showResult(config, existing, null, null, true);
        }

        // Wire up copy button
        const copyBtn = document.getElementById(copyId);
        if (copyBtn) {
            copyBtn.addEventListener('click', async () => {
                const output = document.getElementById(outputId);
                if (!output) return;
                try {
                    await navigator.clipboard.writeText(output.textContent.trim());
                    copyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
                    setTimeout(() => { copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy'; }, 2000);
                } catch {
                    copyBtn.textContent = 'Use Ctrl+C';
                }
            });
        }

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name  = form.querySelector('input[type="text"]')?.value?.trim();
            const email = form.querySelector('input[type="email"]')?.value?.trim();
            if (!name || !email) {
                _showError(errorId, 'Please fill in both your name and email.');
                return;
            }

            const btn = form.querySelector('button[type="submit"]');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Requesting…';
            document.getElementById(errorId)?.classList.add('hidden');
            document.getElementById(resultId)?.classList.add('hidden');

            try {
                const isLocal = window.location.hostname === 'localhost';
                const endpointPath = isLocal
                    ? endpoint.replace(/^\/forgensic(?=\/)/, '')
                    : endpoint;
                const base = _resolveBase(endpoint);
                const r = await fetch(`${base}${endpointPath}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, email })
                });
                if (!r.ok) {
                    const errJson = await r.json().catch(() => ({}));
                    throw new Error(errJson.detail || `HTTP ${r.status}`);
                }
                const data = await r.json();
                sessionStorage.setItem(storageKey, data.access_token);
                _showResult(config, data.access_token, name, data.expires_in_days, false);
                window.showToast('Token Issued', `${storageKey} saved to your session.`, 'success');
            } catch (err) {
                _showError(errorId, `Failed: ${err.message}`);
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-bolt"></i> ' + btn.dataset.label;
            }
        });

        // Store original label for restore
        const btn = form.querySelector('button[type="submit"]');
        if (btn) btn.dataset.label = btn.textContent.trim();
    }

    function _resolveBase(endpoint) {
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            if (endpoint.includes('privacy'))   return 'http://localhost:8003';
            if (endpoint.includes('abdm'))      return 'http://localhost:8000';
            if (endpoint.includes('nhcx'))      return 'http://localhost:8001';
            if (endpoint.includes('forgensic')) return 'http://localhost:8004';
        }
        return window.location.origin;
    }

    function _showResult(config, token, name, expiresInDays, restored) {
        const resultEl   = document.getElementById(config.resultId);
        const outputEl   = document.getElementById(config.outputId);
        const greetingEl = document.getElementById(config.greetingId);
        const expiryEl   = document.getElementById(config.expiryId);

        if (outputEl)   outputEl.textContent = token;
        resultEl?.classList.remove('hidden');
        document.getElementById(config.errorId)?.classList.add('hidden');

        // Decode expiry from JWT if available
        let expTs = null;
        let displayName = name || '';
        try {
            const parts = token.split('.');
            if (parts.length === 3) {
                const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
                expTs = payload.exp;
                displayName = displayName || payload.name || '';
            }
        } catch {}

        if (greetingEl && displayName) {
            greetingEl.textContent = restored ? `Welcome back, ${displayName}!` : `🎉 Token issued for ${displayName}`;
        }
        if (expiryEl) {
            if (expTs) {
                expiryEl.textContent = `Expires ${new Date(expTs * 1000).toLocaleDateString(undefined, { dateStyle: 'medium' })}`;
            } else if (expiresInDays) {
                expiryEl.textContent = `Valid for ${expiresInDays} days`;
            }
        }
    }

    function _showError(errorId, msg) {
        const el = document.getElementById(errorId);
        if (el) { el.textContent = msg; el.classList.remove('hidden'); }
    }

    // ── Public init ───────────────────────────────────────────────────────────
    window.initApiAccess = function() {
        // Clinical Document — ABDM
        handleTokenRequest({
            formId:     'apiAbdmTokenForm',
            endpoint:   '/pdf2abdm/api/token',
            storageKey: 'abdm_token',
            resultId:   'apiAbdmTokenResult',
            greetingId: 'apiAbdmTokenGreeting',
            expiryId:   'apiAbdmTokenExpiry',
            outputId:   'apiAbdmTokenOutput',
            errorId:    'apiAbdmTokenError',
            copyId:     'apiAbdmTokenCopy',
        });

        // Insurance Policy — NHCX
        handleTokenRequest({
            formId:     'apiNhcxTokenForm',
            endpoint:   '/pdf2nhcx/api/token',
            storageKey: 'nhcx_token',
            resultId:   'apiNhcxTokenResult',
            greetingId: 'apiNhcxTokenGreeting',
            expiryId:   'apiNhcxTokenExpiry',
            outputId:   'apiNhcxTokenOutput',
            errorId:    'apiNhcxTokenError',
            copyId:     'apiNhcxTokenCopy',
        });

        // Forgery Detection — Forgensic
        handleTokenRequest({
            formId:     'apiForgeryTokenForm',
            endpoint:   '/forgensic/api/token',
            storageKey: 'forgensic_token',
            resultId:   'apiForgeryTokenResult',
            greetingId: 'apiForgeryTokenGreeting',
            expiryId:   'apiForgeryTokenExpiry',
            outputId:   'apiForgeryTokenOutput',
            errorId:    'apiForgeryTokenError',
            copyId:     'apiForgeryTokenCopy',
        });

        // Privacy Filter runs as a local Docker container (port 8003) with its own UI and token system.
        // Token generation is handled at: /privacy-filter/api/demo-token
    };

    window.API_downloadPostman = function() {
        window.location.href = 'assets/nhcx_postman_collection.json';
    };

})();
