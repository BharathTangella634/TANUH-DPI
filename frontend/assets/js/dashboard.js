/**
 * dashboard.js - Analytics and Dashboard logic
 *
 * Stats sources:
 *   1. Session Logger  (/session-logger/logs/stats)          — NHCX inference counts, geo, token holders
 *   2. Privacy Filter  (/privacy-filter/api/stats)           — page_visits, docs_redacted, unique_visitors
 *      Fallback:       (/session-logger/logs/pf-stats)       — GCS-backed proxy (60s cache)
 *
 * Visit tracking:
 *   On page load, fires ONE POST /session-logger/logs/visit per browser session
 *   so NHCX website visits are counted over time.
 */
(function() {
    "use strict";

    const DASH_KEY   = 'tanuh_dash';
    const VISIT_KEY  = 'tanuh_visit_sent';  // sessionStorage flag — one visit per session
    let _refreshInterval = null;

    function getDash() {
        try { return JSON.parse(localStorage.getItem(DASH_KEY)) || {}; } catch(e) { return {}; }
    }
    function saveDash(d) { localStorage.setItem(DASH_KEY, JSON.stringify(d)); }

    // ── URL helpers ──────────────────────────────────────────────────────────
    function getStatsUrl() {
        const isLocal = window.location.hostname === 'localhost';
        return isLocal
            ? 'http://localhost:8002/logs/stats'
            : `${window.location.origin}/session-logger/logs/stats`;
    }

    function getPfStatsDirectUrl() {
        const isLocal = window.location.hostname === 'localhost';
        return isLocal
            ? 'http://localhost:8003/api/stats'
            : `${window.location.origin}/privacy-filter/api/stats`;
    }

    // Fallback PF source: GCS-backed session-logger proxy (60s cache)
    function getPfStatsFallbackUrl() {
        const isLocal = window.location.hostname === 'localhost';
        return isLocal
            ? 'http://localhost:8002/logs/pf-stats'
            : `${window.location.origin}/session-logger/logs/pf-stats`;
    }

    function getVisitStatsUrl() {
        const isLocal = window.location.hostname === 'localhost';
        return isLocal
            ? 'http://localhost:8002/logs/visit/stats'
            : `${window.location.origin}/session-logger/logs/visit/stats`;
    }

    function getForgeryStatsUrl() {
        const isLocal = window.location.hostname === 'localhost';
        return isLocal
            ? 'http://localhost:8004/stats'
            : `${window.location.origin}/forgensic/stats`;
    }

    function getVisitUrl() {
        const isLocal = window.location.hostname === 'localhost';
        return isLocal
            ? 'http://localhost:8002/logs/visit'
            : `${window.location.origin}/session-logger/logs/visit`;
    }

    // ── Geo helper ───────────────────────────────────────────────────────────
    async function fetchGeoLocation() {
        const d = getDash();
        if (d.last_state && d.last_city) return;
        try {
            const geo = await fetch('https://ipapi.co/json/', { signal: AbortSignal.timeout(5000) }).then(r => r.json());
            d.last_state = geo.region || '';
            d.last_city  = geo.city   || '';
            saveDash(d);
        } catch(e) {}
    }

    // ── Visit tracking ───────────────────────────────────────────────────────
    /**
     * Fire-and-forget visit ping — one POST per browser session.
     * Records this visit in the session-logger so NHCX page views are
     * tracked over time and visible in the dashboard / DB.
     */
    async function trackPageVisit() {
        if (sessionStorage.getItem(VISIT_KEY)) return;  // already sent this session
        sessionStorage.setItem(VISIT_KEY, '1');          // mark immediately to prevent race

        const d = getDash();
        try {
            await fetch(getVisitUrl(), {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    page:  'nhcx-hackathon',
                    state: d.last_state || null,
                    city:  d.last_city  || null,
                }),
                signal: AbortSignal.timeout(5000),
            });
        } catch(e) {
            console.debug('[dashboard] visit tracking silently failed:', e.message);
        }
    }

    // ── Animation helpers ────────────────────────────────────────────────────
    const animate = (id, val) => {
        const el = document.getElementById(id);
        if (!el) return;
        const end = val || 0;
        let current = parseInt(el.textContent.replace(/,/g, '')) || 0;
        if (current === end) { el.textContent = end.toLocaleString(); return; }
        const step = Math.max(1, Math.ceil(Math.abs(end - current) / 30));
        const dir  = end > current ? 1 : -1;
        const timer = setInterval(() => {
            current = dir > 0 ? Math.min(current + step, end) : Math.max(current - step, end);
            el.textContent = current.toLocaleString();
            if (current === end) clearInterval(timer);
        }, 30);
    };

    const setCount = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = (val || 0).toLocaleString();
    };

    // ── PF stats with primary + fallback ────────────────────────────────────
    async function fetchPfStats() {
        // Try direct Cloud Run endpoint first (real-time, most accurate)
        try {
            const r = await fetch(getPfStatsDirectUrl(), { signal: AbortSignal.timeout(6000) });
            if (r.ok) {
                const j = await r.json();
                console.debug('[dashboard] PF stats from Cloud Run:', j);
                return j;
            }
        } catch(e) {
            console.debug('[dashboard] PF direct fetch failed, trying GCS fallback:', e.message);
        }

        // Fallback: GCS-backed session-logger proxy (60 s cache)
        try {
            const r = await fetch(getPfStatsFallbackUrl(), { signal: AbortSignal.timeout(6000) });
            if (r.ok) {
                const j = await r.json();
                console.debug('[dashboard] PF stats from GCS fallback:', j);
                return j;
            }
        } catch(e) {
            console.debug('[dashboard] PF fallback also failed:', e.message);
        }

        return null;
    }

    // ── Main render ──────────────────────────────────────────────────────────
    async function renderDashboard() {
        let clinical = 0, insurance = 0;
        let states = [], districts = [];
        let docsRedacted = 0, pageVisits = 0, forgeryDocs = 0;

        const [statsRes, pfStatsRes, visitRes, forgeryRes] = await Promise.allSettled([
            fetch(getStatsUrl(), { signal: AbortSignal.timeout(8000) }),
            fetchPfStats(),
            fetch(getVisitStatsUrl(), { signal: AbortSignal.timeout(6000) }),
            fetch(getForgeryStatsUrl(), { signal: AbortSignal.timeout(6000) }),
        ]);

        if (statsRes.status === 'fulfilled' && statsRes.value.ok) {
            try {
                const stats    = await statsRes.value.json();
                clinical       = stats.clinical_documents  || 0;
                insurance      = stats.insurance_policies  || 0;
                states         = stats.states               || [];
                districts      = stats.districts            || [];
            } catch(e) {
                console.warn('[dashboard] Session Logger parse error', e);
            }
        }

        if (pfStatsRes.status === 'fulfilled' && pfStatsRes.value) {
            docsRedacted = pfStatsRes.value.docs_redacted || 0;
        }

        if (visitRes.status === 'fulfilled' && visitRes.value.ok) {
            try {
                const v = await visitRes.value.json();
                pageVisits = v.nhcx_page_visits || 0;
                const visitStates = v.states || [];
                const visitCities = v.cities || [];
                states = [...new Set([...states, ...visitStates])];
                districts = [...new Set([...districts, ...visitCities])];
            } catch(e) {}
        }

        if (forgeryRes.status === 'fulfilled' && forgeryRes.value.ok) {
            try {
                const f = await forgeryRes.value.json();
                forgeryDocs = f.docs_analyzed || 0;
            } catch(e) {}
        }

        // Cards
        animate('statPageVisitors',    pageVisits);
        animate('statClinical',        clinical);
        animate('statInsurance',       insurance);
        animate('statDocsRedacted',    docsRedacted);
        animate('statForgery',         forgeryDocs);

        // Geo coverage
        const sCount = document.getElementById('stateCount');
        const sList  = document.getElementById('stateList');
        const dCount = document.getElementById('districtCount');
        const dList  = document.getElementById('districtList');

        if (sCount) sCount.textContent = states.length;
        if (sList)  sList.innerHTML    = states.map(s => `<span class="dash-geo-tag">${s}</span>`).join('');
        if (dCount) dCount.textContent = districts.length;
        if (dList)  dList.innerHTML    = districts.map(d => `<span class="dash-geo-tag">${d}</span>`).join('');
    }

    // ── Public init ──────────────────────────────────────────────────────────
    window.initDashboard = async function() {
        await fetchGeoLocation();
        trackPageVisit();

        renderDashboard();

        if (_refreshInterval) clearInterval(_refreshInterval);
        _refreshInterval = setInterval(renderDashboard, 30000);
    };

    window.getDash        = getDash;
    window.trackInference = () => setTimeout(renderDashboard, 2000);

})();
