(function () {
    "use strict";

    const GATED_TABS = new Set(["PDF2FHIR", "PDF2NHCX", "PrivacyFilter", "ForgeryDetection"]);
    let _pendingTab = null;
    let _authReady = false;
    let _authReadyCallbacks = [];

    // ── Firebase config ───────────────────────────────────────────────────────
    const firebaseConfig = {
        apiKey: "AIzaSyCZ1y022V_90nykCoAj-o7-UTlWA0YvUR4",
        authDomain: "tanuh-dpi.firebaseapp.com",
        projectId: "tanuh-dpi",
    };

    firebase.initializeApp(firebaseConfig);
    const auth = firebase.auth();

    // ── Wait for auth readiness ───────────────────────────────────────────────
    auth.onAuthStateChanged(function (user) {
        _authReady = true;
        _authReadyCallbacks.forEach(function (cb) { cb(user); });
        _authReadyCallbacks = [];
        updateNavAuthState();
        _syncUserToBackend(user);
    });

    function _onAuthReady(cb) {
        if (_authReady) cb(auth.currentUser);
        else _authReadyCallbacks.push(cb);
    }

    // ── Backend helpers ───────────────────────────────────────────────────────

    function _authUrl(path) {
        var isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
        return isLocal ? "http://localhost:8002" + path : window.location.origin + path;
    }

    function _syncUserToBackend(user) {
        if (!user) return;
        user.getIdToken().then(function (token) {
            fetch(_authUrl("/auth/sync"), {
                method: "POST",
                headers: { Authorization: "Bearer " + token },
            }).catch(function () {});
        });
    }

    // ── Auth state ────────────────────────────────────────────────────────────

    function isLoggedIn() {
        var user = auth.currentUser;
        if (!user) return false;
        if (user.providerData && user.providerData.length > 0) {
            var provider = user.providerData[0].providerId;
            if (provider === "google.com") return true;
        }
        return user.emailVerified === true;
    }

    function getUser() {
        var user = auth.currentUser;
        if (!user) return null;
        return { uid: user.uid, name: user.displayName || "", email: user.email || "" };
    }

    function getToken() {
        var user = auth.currentUser;
        if (!user) return null;
        return user.getIdToken();
    }

    function getAuthHeaders() {
        var user = auth.currentUser;
        if (!user) return Promise.resolve({});
        return user.getIdToken().then(function (token) {
            return { Authorization: "Bearer " + token };
        });
    }

    // ── Auth gate ─────────────────────────────────────────────────────────────

    function isGatedTab(tabName) {
        return GATED_TABS.has(tabName);
    }

    function setPendingTab(tabName) {
        _pendingTab = tabName;
    }

    function consumePendingTab() {
        var tab = _pendingTab;
        _pendingTab = null;
        return tab;
    }

    // ── Firebase auth operations ──────────────────────────────────────────────

    function register(name, email, password) {
        return auth.createUserWithEmailAndPassword(email, password)
            .then(function (cred) {
                return cred.user.updateProfile({ displayName: name }).then(function () {
                    return cred.user.sendEmailVerification();
                }).then(function () {
                    return { status: "verification_sent", email: email };
                });
            });
    }

    function login(email, password) {
        return auth.signInWithEmailAndPassword(email, password)
            .then(function (cred) {
                if (!cred.user.emailVerified) {
                    auth.signOut();
                    var err = new Error("Please verify your email before signing in. Check your inbox for the verification link.");
                    err.code = "auth/email-not-verified";
                    throw err;
                }
                return cred.user.getIdToken().then(function () {
                    _syncUserToBackend(cred.user);
                    return { status: "ok" };
                });
            });
    }

    function googleAuth() {
        var provider = new firebase.auth.GoogleAuthProvider();
        return auth.signInWithPopup(provider)
            .then(function (result) {
                _syncUserToBackend(result.user);
                return { status: "ok" };
            });
    }

    function forgotPassword(email) {
        return auth.sendPasswordResetEmail(email);
    }

    function resendVerification() {
        var user = auth.currentUser;
        if (user) return user.sendEmailVerification();
        return Promise.reject(new Error("No user signed in."));
    }

    function logout() {
        auth.signOut().then(function () {
            _pendingTab = null;
            updateNavAuthState();
            if (window.openTab) window.openTab(null, "Home");
        });
    }

    // ── Nav UI ────────────────────────────────────────────────────────────────

    function updateNavAuthState() {
        var loginBtn = document.getElementById("navLoginBtn");
        var userWrap = document.getElementById("navUserWrap");
        var userName = document.getElementById("navUserName");
        var avatar = document.getElementById("navUserAvatar");

        if (!loginBtn || !userWrap) return;

        if (isLoggedIn()) {
            var user = getUser();
            loginBtn.style.setProperty("display", "none", "important");
            userWrap.style.setProperty("display", "flex", "important");
            if (userName && user) {
                var displayName = user.name || user.email || "";
                var shortName = displayName.split(' ')[0]; // Shortcut of name
                if (shortName.length > 12) {
                    shortName = shortName.substring(0, 10) + "...";
                }
                userName.textContent = shortName;
                userName.title = displayName; // Full name on hover
            }
            if (avatar && user && (user.name || user.email)) {
                avatar.textContent = (user.name || user.email).charAt(0).toUpperCase();
            }
        } else {
            loginBtn.style.setProperty("display", "inline-flex", "important");
            userWrap.style.setProperty("display", "none", "important");
        }
    }

    // ── Login page UI logic ─────────────────────────────────────────────────

    function _showError(id, msg) {
        var el = document.getElementById(id);
        if (el) { el.textContent = msg; el.style.display = "block"; }
    }

    function _clearErrors() {
        ["signinError", "registerError", "forgotError"].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) { el.textContent = ""; el.style.display = "none"; }
        });
    }

    function _setBtnLoading(btn, loading) {
        if (!btn) return;
        var text = btn.querySelector(".login-btn-text");
        var spinner = btn.querySelector(".login-btn-spinner");
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

    function _firebaseErrorMsg(err) {
        var map = {
            "auth/email-already-in-use": "An account with this email already exists.",
            "auth/invalid-email": "Please enter a valid email address.",
            "auth/weak-password": "Password must be at least 6 characters.",
            "auth/user-not-found": "No account found with this email.",
            "auth/wrong-password": "Invalid email or password.",
            "auth/invalid-credential": "Invalid email or password.",
            "auth/too-many-requests": "Too many attempts. Please try again later.",
            "auth/popup-closed-by-user": "Google sign-in was cancelled.",
            "auth/email-not-verified": err.message,
        };
        return map[err.code] || err.message || "An error occurred. Please try again.";
    }

    function _onLoginSuccess() {
        updateNavAuthState();
        var pending = consumePendingTab();
        if (pending && window.openTab) {
            window.openTab(null, pending);
        } else if (window.openTab) {
            window.openTab(null, "Home");
        }
    }

    function _showSection(sectionId) {
        ["authSignIn", "authRegister", "authVerifyNotice", "authForgotPassword"].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.style.display = id === sectionId ? "block" : "none";
        });
        var tabs = document.querySelector(".login-tabs");
        if (tabs) tabs.style.display = (sectionId === "authSignIn" || sectionId === "authRegister") ? "flex" : "none";
    }

    function initLoginPage() {
        // no-op — all handlers wired globally below
    }

    window.switchAuthTab = function (tab) {
        var signinTab = document.getElementById("loginTabSignIn");
        var registerTab = document.getElementById("loginTabRegister");
        _clearErrors();

        if (tab === "signin") {
            signinTab.classList.add("active");
            registerTab.classList.remove("active");
            _showSection("authSignIn");
        } else {
            registerTab.classList.add("active");
            signinTab.classList.remove("active");
            _showSection("authRegister");
        }
    };

    window.handleSignIn = function () {
        _clearErrors();
        var email = document.getElementById("signinEmail").value.trim();
        var password = document.getElementById("signinPassword").value;
        if (!email || !password) return _showError("signinError", "Please fill in all fields.");
        var btn = document.getElementById("signinSubmitBtn");
        _setBtnLoading(btn, true);
        login(email, password)
            .then(function () { _onLoginSuccess(); })
            .catch(function (e) { _showError("signinError", _firebaseErrorMsg(e)); })
            .finally(function () { _setBtnLoading(btn, false); });
    };

    window.handleRegister = function () {
        _clearErrors();
        var name = document.getElementById("registerName").value.trim();
        var email = document.getElementById("registerEmail").value.trim();
        var password = document.getElementById("registerPassword").value;
        if (!name || !email || !password) return _showError("registerError", "Please fill in all fields.");
        if (password.length < 6) return _showError("registerError", "Password must be at least 6 characters.");
        var btn = document.getElementById("registerSubmitBtn");
        _setBtnLoading(btn, true);
        register(name, email, password)
            .then(function () {
                var el = document.getElementById("verifyEmailAddr");
                if (el) el.textContent = email;
                _showSection("authVerifyNotice");
            })
            .catch(function (e) { _showError("registerError", _firebaseErrorMsg(e)); })
            .finally(function () { _setBtnLoading(btn, false); });
    };

    window.handleGoogleAuth = function () {
        googleAuth()
            .then(function () { _onLoginSuccess(); })
            .catch(function (e) {
                var activeForm = document.getElementById("authRegister");
                var errId = (activeForm && activeForm.style.display !== "none") ? "registerError" : "signinError";
                _showError(errId, _firebaseErrorMsg(e));
            });
    };

    window.handleForgotPassword = function () {
        _clearErrors();
        _showSection("authForgotPassword");
    };

    window.handleSendReset = function () {
        _clearErrors();
        var email = document.getElementById("forgotEmail").value.trim();
        if (!email) return _showError("forgotError", "Please enter your email address.");
        var btn = document.getElementById("forgotSubmitBtn");
        _setBtnLoading(btn, true);
        forgotPassword(email)
            .then(function () {
                _showError("forgotError", "");
                var successEl = document.getElementById("forgotSuccess");
                if (successEl) successEl.style.display = "block";
            })
            .catch(function (e) { _showError("forgotError", _firebaseErrorMsg(e)); })
            .finally(function () { _setBtnLoading(btn, false); });
    };

    window.handleBackToSignIn = function () {
        _clearErrors();
        var signinTab = document.getElementById("loginTabSignIn");
        var registerTab = document.getElementById("loginTabRegister");
        if (signinTab) signinTab.classList.add("active");
        if (registerTab) registerTab.classList.remove("active");
        _showSection("authSignIn");
        var successEl = document.getElementById("forgotSuccess");
        if (successEl) successEl.style.display = "none";
    };

    window.handleResendVerification = function () {
        resendVerification()
            .then(function () {
                var notice = document.getElementById("verifyResendMsg");
                if (notice) {
                    notice.textContent = "Verification email resent!";
                    notice.style.display = "block";
                    setTimeout(function () { notice.style.display = "none"; }, 4000);
                }
            })
            .catch(function () {});
    };

    document.addEventListener("keydown", function (e) {
        if (e.key !== "Enter") return;
        var signinForm = document.getElementById("authSignIn");
        var registerForm = document.getElementById("authRegister");
        var forgotForm = document.getElementById("authForgotPassword");
        if (signinForm && signinForm.style.display !== "none" && signinForm.contains(e.target)) {
            handleSignIn();
        } else if (registerForm && registerForm.style.display !== "none" && registerForm.contains(e.target)) {
            handleRegister();
        } else if (forgotForm && forgotForm.style.display !== "none" && forgotForm.contains(e.target)) {
            handleSendReset();
        }
    });

    // ── Expose ────────────────────────────────────────────────────────────────

    window.DPI_Auth = {
        isLoggedIn: isLoggedIn,
        getUser: getUser,
        getToken: getToken,
        getAuthHeaders: getAuthHeaders,
        isGatedTab: isGatedTab,
        setPendingTab: setPendingTab,
        consumePendingTab: consumePendingTab,
        register: register,
        login: login,
        googleAuth: googleAuth,
        forgotPassword: forgotPassword,
        resendVerification: resendVerification,
        logout: logout,
        updateNavAuthState: updateNavAuthState,
        initLoginPage: initLoginPage,
        onAuthReady: _onAuthReady,
    };

})();
