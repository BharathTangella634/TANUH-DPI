/**
 * DISPLACE MedAI – Main Application Controller
 */

document.addEventListener('DOMContentLoaded', () => {
    
    // DOM Elements
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');
    const fileNameDisplay = document.getElementById('file-name');
    const btnProcess = document.getElementById('btn-process');
    const langSelect = document.getElementById('language-select');
    
    const statusBar = document.getElementById('status-bar');
    const statusText = document.getElementById('status-text');
    const outputWrapper = document.getElementById('output-wrapper');
    
    const transcriptBody = document.getElementById('transcript-body');
    const topicContent = document.getElementById('topic-content');
    const summaryContent = document.getElementById('summary-content');
    
    const btnCopyTranscript = document.getElementById('btn-copy-transcript');
    const btnDownloadTranscript = document.getElementById('btn-download-transcript');
    
    const btnCopyTopic = document.getElementById('btn-copy-topic');
    const btnDownloadTopic = document.getElementById('btn-download-topic');
    
    const btnCopySummary = document.getElementById('btn-copy-summary');
    const btnDownloadSummary = document.getElementById('btn-download-summary');
    
    let selectedFile = null;
    let pollInterval = null;
    let lastProcessedResults = null;

    // --- Tab Handling ---
    const navAudioSummary = document.getElementById('nav-audio-summary');
    const navUserGuide = document.getElementById('nav-user-guide');
    const tabAudioSummary = document.getElementById('tab-content-audio-summary');
    const tabUserGuide = document.getElementById('tab-content-user-guide');

    function switchTab(activeNav, inactiveNav, activeTab, inactiveTab) {
        if (!activeNav || !inactiveNav || !activeTab || !inactiveTab) return;
        activeNav.classList.add('active');
        inactiveNav.classList.remove('active');
        activeTab.style.display = 'block';
        inactiveTab.style.display = 'none';
    }

    if (navAudioSummary && navUserGuide) {
        navAudioSummary.addEventListener('click', () => {
            switchTab(navAudioSummary, navUserGuide, tabAudioSummary, tabUserGuide);
        });

        navUserGuide.addEventListener('click', () => {
            switchTab(navUserGuide, navAudioSummary, tabUserGuide, tabAudioSummary);
        });
    }

    // --- File Upload Handling ---
    
    uploadZone.addEventListener('click', () => {
        if (!btnProcess.disabled || btnProcess.textContent === 'Process') {
            fileInput.click();
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            selectedFile = e.target.files[0];
            fileNameDisplay.textContent = selectedFile.name;
            btnProcess.disabled = false;
        }
    });

    // --- Processing Logic ---

    btnProcess.addEventListener('click', async () => {
        if (!selectedFile) {
            showToast('Please select an audio file first.', 'error');
            return;
        }

        // UI updates
        btnProcess.disabled = true;
        btnProcess.textContent = 'Processing...';
        outputWrapper.style.display = 'none';
        statusBar.style.display = 'block';
        logToOutput('Starting process...');
        lastProcessedResults = null;

        try {
            // 1. Upload File
            logToOutput(`Uploading ${selectedFile.name}...`, 'progress-log');
            const formData = new FormData();
            formData.append('file', selectedFile);

            const uploadResp = await fetch('https://v2e.tanuh.ai/api/upload', {
                method: 'POST',
                body: formData,
            });

            if (!uploadResp.ok) throw new Error('Upload failed');
            const uploadData = await uploadResp.json();
            const jobId = uploadData.job_id;
            
            logToOutput(`Upload complete. Job ID: ${jobId}`, 'progress-log');

            // 2. Start Processing
            const lang = langSelect.value;
            const processResp = await fetch(`https://v2e.tanuh.ai/api/process/${jobId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ language: lang }),
            });

            if (!processResp.ok) throw new Error('Failed to start pipeline');
            
            logToOutput(`Pipeline queued for ${lang.toUpperCase()} audio.`, 'progress-log');
            logToOutput(`Waiting for GPU resources...`, 'progress-log');

            // 3. Poll Status
            let lastStatus = '';
            pollInterval = setInterval(async () => {
                try {
                    const statResp = await fetch(`https://v2e.tanuh.ai/api/jobs/${jobId}`);
                    if (!statResp.ok) return;
                    
                    const statData = await statResp.json();
                    
                    if (statData.status && statData.status !== lastStatus) {
                        lastStatus = statData.status;
                        const statusMap = {
                            'UPLOADED': 'Uploaded',
                            'QUEUED': 'Queued',
                            'DIARIZING': 'Diarisation',
                            'TRANSCRIBING': 'ASR and transcription',
                            'TOPIC_EXTRACTION': 'Topic',
                            'SUMMARIZING': 'Summarisation',
                            'COMPLETED': 'Completed',
                            'FAILED': 'Failed'
                        };
                        const displayStatus = statusMap[statData.status] || statData.status;
                        logToOutput(`......${displayStatus}`, 'progress-log');
                    }
                    
                    const progressBarFill = document.getElementById('progress-bar-fill');
                    if (progressBarFill && statData.progress !== undefined) {
                        progressBarFill.style.width = `${statData.progress}%`;
                    }

                    // Fetch partial results if past diarizing phase
                    if (['TRANSCRIBING', 'TOPIC_EXTRACTION', 'SUMMARIZING', 'COMPLETED'].includes(statData.status)) {
                        fetchAndDisplayResults(jobId, statData.status === 'COMPLETED');
                    }

                    if (statData.status === 'COMPLETED') {
                        clearInterval(pollInterval);
                        logToOutput(`......Completed!`, 'progress-log');
                        if (progressBarFill) progressBarFill.style.width = `100%`;
                    } else if (statData.status === 'FAILED') {
                        clearInterval(pollInterval);
                        logToOutput(`Pipeline Failed: ${statData.error_message}`, 'error-log');
                        resetProcessButton();
                    }
                } catch (e) {
                    console.error('Poll error', e);
                }
            }, 2000);

        } catch (err) {
            console.error(err);
            logToOutput(`Error: ${err.message}`, 'error-log');
            showToast(err.message, 'error');
            resetProcessButton();
        }
    });

    async function fetchAndDisplayResults(jobId, isComplete = false) {
        try {
            const resp = await fetch(`https://v2e.tanuh.ai/api/jobs/${jobId}/results`);
            if (!resp.ok) return;
            
            const results = await resp.json();
            lastProcessedResults = results;
            
            if (results.transcript && results.transcript.length > 0) {
                if (isComplete) {
                    statusBar.style.display = 'none';
                }
                outputWrapper.style.display = 'block';
                
                // Render Transcript Table
                transcriptBody.innerHTML = '';
                results.transcript.forEach(seg => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><strong>${seg.speaker_id}</strong></td>
                        <td>${formatTime(seg.start_time)} - ${formatTime(seg.end_time)}</td>
                        <td>${seg.text}</td>
                    `;
                    transcriptBody.appendChild(tr);
                });
                
                // Auto-scroll to bottom as new transcripts are added
                const transcriptContainer = document.querySelector('.output-panel-content.transcript-content');
                if (transcriptContainer && !isComplete) {
                    transcriptContainer.scrollTop = transcriptContainer.scrollHeight;
                }
            }
            
            // Render Topic
            if (results.topics) {
                topicContent.innerHTML = results.topics.replace(/,/g, ', ');
            } else {
                topicContent.innerHTML = isComplete ? 'No topics detected.' : '<i>Generating topics...</i>';
            }
            
            // Render Summary
            if (results.summary) {
                summaryContent.innerHTML = results.summary.replace(/\n/g, '<br>');
            } else {
                summaryContent.innerHTML = isComplete ? 'No summary generated.' : '<i>Generating summary...</i>';
            }
            
            if (isComplete) {
                showToast('Processing complete!', 'success');
                btnProcess.textContent = 'Process Complete';

                const _logUrl = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
                    ? 'http://localhost:8002/log'
                    : `${window.location.origin}/session-logger/log`;
                fetch(_logUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ service: 'audio_asr' }) }).catch(() => {});

                const btnDone = document.getElementById('btn-done');
                if (btnDone) {
                    btnDone.style.display = 'inline-block';
                    btnDone.onclick = () => {
                        window.location.reload();
                    };
                }
            }
            
        } catch (err) {
            console.error(`Error fetching results: ${err.message}`);
            if (isComplete) {
                resetProcessButton();
            }
        }
    }

    function resetProcessButton() {
        btnProcess.textContent = 'Process';
        btnProcess.disabled = false;
    }

    function logToOutput(msg, className = '') {
        statusText.textContent = msg;
    }

    function formatTime(seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    // --- Actions ---

    function setupCopy(btnElement, textGetter, successMsg) {
        btnElement.addEventListener('click', () => {
            if (!lastProcessedResults) return;
            navigator.clipboard.writeText(textGetter()).then(() => {
                showToast(successMsg);
            });
        });
    }

    function setupDownload(btnElement, textGetter, filename) {
        btnElement.addEventListener('click', () => {
            if (!lastProcessedResults) return;
            const dataStr = "data:text/plain;charset=utf-8," + encodeURIComponent(textGetter());
            const a = document.createElement('a');
            a.href = dataStr;
            a.download = filename;
            a.click();
        });
    }

    // Transcript Actions
    const getTranscriptText = () => lastProcessedResults.transcript.map(s => `[${formatTime(s.start_time)} - ${formatTime(s.end_time)}] ${s.speaker_id}: ${s.text}`).join('\n');
    setupCopy(btnCopyTranscript, getTranscriptText, 'Transcript copied!');
    setupDownload(btnDownloadTranscript, getTranscriptText, 'transcript.txt');

    // Topic Actions
    const getTopicText = () => lastProcessedResults.topics || 'No topics detected.';
    setupCopy(btnCopyTopic, getTopicText, 'Topics copied!');
    setupDownload(btnDownloadTopic, getTopicText, 'topics.txt');

    // Summary Actions
    const getSummaryText = () => lastProcessedResults.summary || 'No summary generated.';
    setupCopy(btnCopySummary, getSummaryText, 'Summary copied!');
    setupDownload(btnDownloadSummary, getSummaryText, 'summary.txt');

    // --- Toast UI ---

    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.style.borderLeftColor = type === 'error' ? '#ef4444' : '#2a8f8f';
        toast.textContent = message;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
});
