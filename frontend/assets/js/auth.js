/**
 * auth.js — Centralized user authentication for TANUH DPI
 *
 * Manages login/register state, JWT persistence in localStorage,
 * and the auth gate that redirects unauthenticated users to the login page
 * when they try to access protected service tabs.
 */
(function () {
    "use strict";

    const TOKEN_KEY = "dpi_auth_token";
    const GATED_TABS = new Set(["PDF2FHIR", "PDF2NHCX", "PrivacyFilter", "ForgeryDetection"]);

    let _pendingTab = null;

    function _base() {
        if (window.DPI_API_CONFIG && window.DPI_API_CONFIG.logger) return window.DPI_API_CONFIG.logger;
        const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
        return isLocal ? "http://localhost:8002" : window.location.origin;
    }

    function _authUrl(path) {
        if (window.DPI_API_CONFIG && window.DPI_API_CONFIG.logger) return `${window.DPI_API_CONFIG.logger}${path}`;
        const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
        return isLocal ? `http://localhost:8002${path}` : `${window.location.origin}${path}`;
    }

    // ── JWT helpers ────────────────────────────────────────────────────────

    function _decodePayload(token) {
        try {
            const parts = token.split(".");
            if (parts.length !== 3) return null;
            const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
            return payload;
        } catch { return null; }
    }

    function getToken() {
        return localStorage.getItem(TOKEN_KEY);
    }

    function isLoggedIn() {
        const token = getToken();
        if (!token) return false;
        const payload = _decodePayload(token);
        if (!payload || !payload.exp) return false;
        return payload.exp * 1000 > Date.now();
    }

    function getUser() {
        const token = getToken();
        if (!token) return null;
        const payload = _decodePayload(token);
        if (!payload) return null;
        return { id: payload.sub, name: payload.name, email: payload.email };
    }

    function getAuthHeaders() {
        const token = getToken();
        return token ? { Authorization: `Bearer ${token}` } : {};
    }

    // ── Auth gate ──────────────────────────────────────────────────────────

    function isGatedTab(tabName) {
        return GATED_TABS.has(tabName);
    }

    function setPendingTab(tabName) {
        _pendingTab = tabName;
    }

    function consumePendingTab() {
        const tab = _pendingTab;
        _pendingTab = null;
        return tab;
    }

    // ── API calls ──────────────────────────────────────────────────────────

    async function register(name, email, password) {
        const r = await fetch(_authUrl("/auth/register"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, email, password }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || data.message || `Registration failed (${r.status})`);
        return data;
    }

    async function verifyOtp(email, otp) {
        const r = await fetch(_authUrl("/auth/verify-otp"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, otp }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || data.message || `Verification failed (${r.status})`);
        if (data.access_token) {
            localStorage.setItem(TOKEN_KEY, data.access_token);
        }
        return data;
    }

    async function resendOtp(email) {
        const r = await fetch(_authUrl("/auth/resend-otp"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, otp: "" }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || data.message || `Resend failed (${r.status})`);
        return data;
    }

    async function login(email, password) {
        const r = await fetch(_authUrl("/auth/login"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || data.message || `Login failed (${r.status})`);
        if (data.access_token) {
            localStorage.setItem(TOKEN_KEY, data.access_token);
        }
        return data;
    }

    async function googleAuth(credential) {
        const r = await fetch(_authUrl("/auth/google"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ credential }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || data.message || `Google auth failed (${r.status})`);
        if (data.access_token) {
            localStorage.setItem(TOKEN_KEY, data.access_token);
        }
        return data;
    }

    function logout() {
        localStorage.removeItem(TOKEN_KEY);
        _pendingTab = null;
        updateNavAuthState();
        if (window.openTab) window.openTab(null, "Home");
    }

    // ── Nav UI ─────────────────────────────────────────────────────────────

    function updateNavAuthState() {
        const loginBtn = document.getElementById("navLoginBtn");
        const userWrap = document.getElementById("navUserWrap");
        const userName = document.getElementById("navUserName");
        const avatar = document.getElementById("navUserAvatar");

        if (!loginBtn || !userWrap) return;

        if (isLoggedIn()) {
            const user = getUser();
            loginBtn.style.display = "none";
            userWrap.style.display = "flex";
            if (userName && user) userName.textContent = user.name;
            if (avatar && user && user.name) avatar.textContent = user.name.charAt(0).toUpperCase();
        } else {
            loginBtn.style.display = "flex";
            userWrap.style.display = "none";
        }
    }

    // ── Login page UI logic ──────────────────────────────────────────────
    // (lives here because login.html is loaded via innerHTML, which won't run <script> tags)

    let _regEmail = "";

    function _showError(id, msg) {
        const el = document.getElementById(id);
        if (el) { el.textContent = msg; el.style.display = "block"; }
    }

    function _clearErrors() {
        ["signinError", "registerError", "otpError"].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.textContent = ""; el.style.display = "none"; }
        });
    }

    function _setBtnLoading(btn, loading) {
        if (!btn) return;
        const text = btn.querySelector(".login-btn-text");
        const spinner = btn.querySelector(".login-btn-spinner");
        if (loading) {
            btn.disabled = true;
            if (text) text.style.display = "none";
            if (spinner) spinner.style.display = "inline-flex";
        } else {
            btn.disabled = false;
            if (text) text.style.display = "inline";
            if (spinner) spinner.style.display = "none";
        }
    }

    function _onLoginSuccess() {
        updateNavAuthState();
        const pending = consumePendingTab();
        if (pending && window.openTab) {
            window.openTab(null, pending);
        } else if (window.openTab) {
            window.openTab(null, "Home");
        }
    }

    function _initOtpInputs() {
        const boxes = document.querySelectorAll("#otpInputGroup .otp-box");
        boxes.forEach((box, i) => {
            box.addEventListener("input", function () {
                this.value = this.value.replace(/\D/g, "").slice(0, 1);
                if (this.value && i < boxes.length - 1) boxes[i + 1].focus();
            });
            box.addEventListener("keydown", function (e) {
                if (e.key === "Backspace" && !this.value && i > 0) {
                    boxes[i - 1].focus();
                    boxes[i - 1].value = "";
                }
            });
            box.addEventListener("paste", function (e) {
                e.preventDefault();
                const data = (e.clipboardData || window.clipboardData).getData("text").replace(/\D/g, "").slice(0, 6);
                for (let j = 0; j < data.length && j < boxes.length; j++) {
                    boxes[j].value = data[j];
                }
                if (data.length > 0) boxes[Math.min(data.length, boxes.length) - 1].focus();
            });
        });
    }

    function _focusFirstOtp() {
        setTimeout(() => {
            const first = document.querySelector("#otpInputGroup .otp-box[data-idx='0']");
            if (first) first.focus();
        }, 100);
    }

    function _startResendTimer() {
        const link = document.getElementById("otpResendLink");
        const timer = document.getElementById("otpResendTimer");
        link.classList.add("disabled");
        link.style.display = "none";
        timer.style.display = "inline";
        let secs = 30;
        timer.textContent = `Resend in ${secs}s`;
        const iv = setInterval(() => {
            secs--;
            timer.textContent = `Resend in ${secs}s`;
            if (secs <= 0) {
                clearInterval(iv);
                link.classList.remove("disabled");
                link.style.display = "inline";
                timer.style.display = "none";
            }
        }, 1000);
    }

    function initLoginPage() {
        _initOtpInputs();
    }

    window.switchAuthTab = function (tab) {
        const signinTab = document.getElementById("loginTabSignIn");
        const registerTab = document.getElementById("loginTabRegister");
        const signinForm = document.getElementById("authSignIn");
        const registerForm = document.getElementById("authRegister");
        const otpForm = document.getElementById("authOtp");

        if (tab === "signin") {
            signinTab.classList.add("active");
            registerTab.classList.remove("active");
            signinForm.style.display = "block";
            registerForm.style.display = "none";
            otpForm.style.display = "none";
        } else {
            registerTab.classList.add("active");
            signinTab.classList.remove("active");
            signinForm.style.display = "none";
            registerForm.style.display = "block";
            otpForm.style.display = "none";
        }
        _clearErrors();
    };

    window.handleSignIn = async function () {
        _clearErrors();
        const email = document.getElementById("signinEmail").value.trim();
        const password = document.getElementById("signinPassword").value;
        if (!email || !password) return _showError("signinError", "Please fill in all fields.");
        const btn = document.getElementById("signinSubmitBtn");
        _setBtnLoading(btn, true);
        try {
            await login(email, password);
            _onLoginSuccess();
        } catch (e) {
            _showError("signinError", e.message);
        } finally {
            _setBtnLoading(btn, false);
        }
    };

    window.handleRegister = async function () {
        _clearErrors();
        const name = document.getElementById("registerName").value.trim();
        const email = document.getElementById("registerEmail").value.trim();
        const password = document.getElementById("registerPassword").value;
        const confirm = document.getElementById("registerConfirm").value;
        if (!name || !email || !password || !confirm) return _showError("registerError", "Please fill in all fields.");
        if (password.length < 8) return _showError("registerError", "Password must be at least 8 characters.");
        if (password !== confirm) return _showError("registerError", "Passwords do not match.");
        const btn = document.getElementById("registerSubmitBtn");
        _setBtnLoading(btn, true);
        try {
            const result = await register(name, email, password);
            _regEmail = email;
            if (result.dev_otp) {
                document.getElementById("devOtpCode").textContent = result.dev_otp;
                document.getElementById("devOtpBanner").style.display = "flex";
            } else {
                document.getElementById("devOtpBanner").style.display = "none";
            }
            document.getElementById("otpEmailDisplay").textContent = email;
            document.getElementById("authRegister").style.display = "none";
            document.getElementById("authOtp").style.display = "block";
            document.getElementById("loginTabSignIn").style.display = "none";
            document.getElementById("loginTabRegister").style.display = "none";
            _startResendTimer();
            _focusFirstOtp();
        } catch (e) {
            _showError("registerError", e.message);
        } finally {
            _setBtnLoading(btn, false);
        }
    };

    window.handleVerifyOtp = async function () {
        _clearErrors();
        const boxes = document.querySelectorAll("#otpInputGroup .otp-box");
        let otp = "";
        boxes.forEach(b => otp += b.value);
        if (otp.length !== 6) return _showError("otpError", "Please enter the complete 6-digit code.");
        const btn = document.getElementById("otpSubmitBtn");
        _setBtnLoading(btn, true);
        try {
            await verifyOtp(_regEmail, otp);
            _onLoginSuccess();
        } catch (e) {
            _showError("otpError", e.message);
        } finally {
            _setBtnLoading(btn, false);
        }
    };

    window.handleResendOtp = async function () {
        const link = document.getElementById("otpResendLink");
        if (link.classList.contains("disabled")) return;
        try {
            const result = await resendOtp(_regEmail);
            if (result.dev_otp) {
                document.getElementById("devOtpCode").textContent = result.dev_otp;
                document.getElementById("devOtpBanner").style.display = "flex";
            }
            _startResendTimer();
        } catch (e) {
            _showError("otpError", e.message);
        }
    };

    window.handleGoogleAuth = function () {
        alert("Google OAuth is not configured yet. Please use email registration.");
    };

    document.addEventListener("keydown", function (e) {
        if (e.key !== "Enter") return;
        const signinForm = document.getElementById("authSignIn");
        const registerForm = document.getElementById("authRegister");
        const otpForm = document.getElementById("authOtp");
        if (signinForm && signinForm.style.display !== "none" && signinForm.contains(e.target)) {
            handleSignIn();
        } else if (registerForm && registerForm.style.display !== "none" && registerForm.contains(e.target)) {
            handleRegister();
        } else if (otpForm && otpForm.style.display !== "none" && otpForm.contains(e.target)) {
            handleVerifyOtp();
        }
    });

    // ── Expose ─────────────────────────────────────────────────────────────

    window.DPI_Auth = {
        isLoggedIn,
        getUser,
        getToken,
        getAuthHeaders,
        isGatedTab,
        setPendingTab,
        consumePendingTab,
        register,
        verifyOtp,
        resendOtp,
        login,
        googleAuth,
        logout,
        updateNavAuthState,
        initLoginPage,
    };

})();
