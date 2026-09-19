/**
 * DISPLACE MedAI – Pipeline Module
 * Handles job status polling, stepper UI updates,
 * and progress ring animation.
 */

const PipelineModule = (() => {
    let pollInterval = null;
    let currentJobId = null;

    // DOM refs
    const welcome = document.getElementById('pipeline-welcome');
    const stepper = document.getElementById('pipeline-stepper');
    const progressRingFill = document.getElementById('progress-ring-fill');
    const progressPct = document.getElementById('progress-pct');
    const timingStats = document.getElementById('timing-stats');

    // Step elements
    const steps = {
        diarization: document.getElementById('step-diarization'),
        asr: document.getElementById('step-asr'),
        topics: document.getElementById('step-topics'),
        summary: document.getElementById('step-summary'),
    };

    const stepDescs = {
        diarization: document.getElementById('step-diarization-desc'),
        asr: document.getElementById('step-asr-desc'),
        topics: document.getElementById('step-topics-desc'),
        summary: document.getElementById('step-summary-desc'),
    };

    const stepBadges = {
        diarization: document.getElementById('step-diarization-badge'),
        asr: document.getElementById('step-asr-badge'),
        topics: document.getElementById('step-topics-badge'),
        summary: document.getElementById('step-summary-badge'),
    };

    // Progress ring circumference
    const CIRCUMFERENCE = 2 * Math.PI * 52; // r=52

    // Status → step mapping
    const STATUS_MAP = {
        'QUEUED': { active: null, completed: [] },
        'DIARIZING': { active: 'diarization', completed: [] },
        'TRANSCRIBING': { active: 'asr', completed: ['diarization'] },
        'TOPIC_EXTRACTION': { active: 'topics', completed: ['diarization', 'asr'] },
        'SUMMARIZING': { active: 'summary', completed: ['diarization', 'asr', 'topics'] },
        'COMPLETED': { active: null, completed: ['diarization', 'asr', 'topics', 'summary'] },
        'FAILED': { active: null, completed: [] },
    };

    /**
     * Start monitoring a job.
     * Shows the stepper and begins polling.
     */
    function startMonitoring(jobId) {
        currentJobId = jobId;

        // Show stepper, hide welcome
        welcome.style.display = 'none';
        stepper.style.display = 'flex';
        timingStats.style.display = 'none';

        // Reset all steps
        Object.values(steps).forEach(el => el.dataset.status = 'pending');
        Object.values(stepDescs).forEach(el => el.textContent = '');
        Object.values(stepBadges).forEach(el => el.textContent = '');

        stepDescs.diarization.textContent = 'Identify who speaks when';
        stepDescs.asr.textContent = 'Convert speech to text';
        stepDescs.topics.textContent = 'Extract medical topics';
        stepDescs.summary.textContent = 'Generate clinical summary';

        setProgress(0);

        // Switch to pipeline tab
        App.switchTab('pipeline');

        // Start polling
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(() => pollStatus(jobId), 1500);
        pollStatus(jobId); // immediate first poll
    }

    /**
     * Poll the job status API.
     */
    async function pollStatus(jobId) {
        try {
            const resp = await fetch(`https://v2e.tanuh.ai/api/jobs/${jobId}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();

            updateUI(data);

            // Stop polling if done
            if (data.status === 'COMPLETED' || data.status === 'FAILED') {
                clearInterval(pollInterval);
                pollInterval = null;

                if (data.status === 'COMPLETED') {
                    onCompleted(jobId);
                } else {
                    onFailed(data);
                }
            }
        } catch (err) {
            console.error('Poll error:', err);
        }
    }

    /**
     * Update the stepper UI based on job status.
     */
    function updateUI(data) {
        const statusInfo = STATUS_MAP[data.status];
        if (!statusInfo) return;

        // Update progress ring
        setProgress(data.progress);

        // Update step states
        const allSteps = ['diarization', 'asr', 'topics', 'summary'];
        allSteps.forEach(step => {
            if (statusInfo.completed.includes(step)) {
                steps[step].dataset.status = 'completed';
            } else if (statusInfo.active === step) {
                steps[step].dataset.status = 'active';
            } else {
                steps[step].dataset.status = 'pending';
            }
        });

        // Update stage message
        if (statusInfo.active && data.stage_message) {
            stepDescs[statusInfo.active].textContent = data.stage_message;
        }

        // Update completed step descriptions
        statusInfo.completed.forEach(step => {
            if (data.stage_message && step === statusInfo.completed[statusInfo.completed.length - 1]) {
                // Latest completed step gets the message
            }
        });

        if (data.status === 'FAILED') {
            // Find the last active/failed step
            const lastStep = statusInfo.active || allSteps[allSteps.length - 1];
            steps[lastStep].dataset.status = 'failed';
            stepDescs[lastStep].textContent = data.error_message || 'Pipeline failed';
        }
    }

    /**
     * Set the progress ring value (0-100).
     */
    function setProgress(pct) {
        const offset = CIRCUMFERENCE - (pct / 100) * CIRCUMFERENCE;
        progressRingFill.style.strokeDashoffset = offset;
        progressPct.textContent = `${pct}%`;
    }

    /**
     * Handle pipeline completion.
     */
    async function onCompleted(jobId) {
        App.showToast('Pipeline completed successfully!', 'success');

        // Update process button
        const btnProcess = document.getElementById('btn-process');
        btnProcess.classList.remove('processing');
        btnProcess.disabled = false;
        btnProcess.innerHTML = `
            <svg class="btn-icon-svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5,3 19,12 5,21"/>
            </svg>
            <span>Process Audio</span>
        `;

        // Fetch results
        try {
            const resp = await fetch(`https://v2e.tanuh.ai/api/jobs/${jobId}/results`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const results = await resp.json();

            // Update badges
            stepBadges.diarization.textContent = `${results.num_speakers} speakers`;
            stepBadges.asr.textContent = `${results.transcript.length} segments`;
            stepBadges.topics.textContent = results.topics_list.length + ' topics';
            stepBadges.summary.textContent = `${results.summary.length} chars`;

            // Show timing
            showTiming(results);

            // Render results
            ResultsModule.renderAll(results);

            // Add to history
            addToHistory(jobId, results);
        } catch (err) {
            console.error('Failed to fetch results:', err);
            App.showToast('Failed to load results', 'error');
        }
    }

    /**
     * Handle pipeline failure.
     */
    function onFailed(data) {
        App.showToast(`Pipeline failed: ${data.error_message || 'Unknown error'}`, 'error');

        const btnProcess = document.getElementById('btn-process');
        btnProcess.classList.remove('processing');
        btnProcess.disabled = false;
        btnProcess.innerHTML = `
            <svg class="btn-icon-svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5,3 19,12 5,21"/>
            </svg>
            <span>Retry Processing</span>
        `;
    }

    /**
     * Show timing statistics.
     */
    function showTiming(results) {
        timingStats.style.display = 'flex';
        document.getElementById('stat-diar-time').textContent = `${results.diarization_time_s.toFixed(1)}s`;
        document.getElementById('stat-asr-time').textContent = `${results.asr_time_s.toFixed(1)}s`;
        document.getElementById('stat-topic-time').textContent = `${results.topic_time_s.toFixed(1)}s`;
        document.getElementById('stat-summary-time').textContent = `${results.summary_time_s.toFixed(1)}s`;
        document.getElementById('stat-total-time').textContent = `${results.total_time_s.toFixed(1)}s`;
    }

    /**
     * Add job to history sidebar.
     */
    function addToHistory(jobId, results) {
        const historyList = document.getElementById('history-list');
        const emptyState = historyList.querySelector('.empty-state');
        if (emptyState) emptyState.remove();

        const item = document.createElement('div');
        item.className = 'history-item';
        item.innerHTML = `
            <span class="history-dot completed"></span>
            <span class="history-name">${results.transcript.length > 0 ? results.transcript[0].text.substring(0, 30) + '...' : 'Audio'}</span>
            <span class="history-time">${results.total_time_s.toFixed(0)}s</span>
        `;
        historyList.prepend(item);
    }

    /** Get current job ID */
    function getCurrentJobId() {
        return currentJobId;
    }

    return { startMonitoring, getCurrentJobId };
})();
