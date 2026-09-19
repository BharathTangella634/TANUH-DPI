/**
 * DISPLACE MedAI – Results Module
 * Renders transcript segments, topics, and summary
 * in the results panel tabs.
 */

const ResultsModule = (() => {

    /**
     * Render all results (transcript, topics, summary).
     */
    function renderAll(results) {
        renderTranscript(results.transcript);
        renderTopics(results.topics_list, results.topics);
        renderSummary(results.summary);
    }

    /**
     * Render speaker-attributed transcript with colored chat bubbles.
     */
    function renderTranscript(segments) {
        const container = document.getElementById('transcript-container');
        container.innerHTML = '';

        if (!segments || segments.length === 0) {
            container.innerHTML = '<p class="empty-state">No transcript available</p>';
            return;
        }

        segments.forEach(seg => {
            if (!seg.text || seg.text.trim() === '') return;

            const el = document.createElement('div');
            el.className = 'transcript-segment';
            el.dataset.speaker = seg.speaker_id;

            const speakerLabel = formatSpeakerName(seg.speaker_id);
            const timeRange = `${formatTime(seg.start_time)} – ${formatTime(seg.end_time)}`;

            el.innerHTML = `
                <div class="segment-meta">
                    <div class="segment-speaker">${speakerLabel}</div>
                    <div class="segment-time">${timeRange}</div>
                </div>
                <div class="segment-text">${escapeHtml(seg.text)}</div>
            `;

            container.appendChild(el);
        });

        // Setup search
        setupTranscriptSearch(segments);

        // Setup copy/download buttons
        setupTranscriptActions(segments);
    }

    /**
     * Render extracted medical topics as styled pills.
     */
    function renderTopics(topicsList, topicsStr) {
        const container = document.getElementById('topics-container');
        container.innerHTML = '';

        if (!topicsList || topicsList.length === 0) {
            container.innerHTML = '<p class="empty-state">No topics extracted</p>';
            return;
        }

        // Header card
        const header = document.createElement('div');
        header.className = 'glass-card';
        header.style.padding = '16px 20px';
        header.innerHTML = `
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--indigo-light)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
                    <line x1="7" y1="7" x2="7.01" y2="7"/>
                </svg>
                <span style="font-size: 0.85rem; font-weight: 600; color: var(--text-primary);">
                    ${topicsList.length} Medical Topic${topicsList.length !== 1 ? 's' : ''} Identified
                </span>
            </div>
            <p style="font-size: 0.78rem; color: var(--text-tertiary); line-height: 1.5;">
                The following health problems were extracted from the patient conversation using AI analysis.
            </p>
        `;
        container.appendChild(header);

        // Topic pills
        const grid = document.createElement('div');
        grid.className = 'topics-grid';

        topicsList.forEach(topic => {
            const pill = document.createElement('span');
            pill.className = 'topic-pill';
            pill.textContent = topic.charAt(0).toUpperCase() + topic.slice(1);
            grid.appendChild(pill);
        });

        container.appendChild(grid);
    }

    /**
     * Render clinical summary.
     */
    function renderSummary(summary) {
        const container = document.getElementById('summary-container');
        container.innerHTML = '';

        if (!summary || summary.trim() === '') {
            container.innerHTML = '<p class="empty-state">No summary available</p>';
            return;
        }

        const card = document.createElement('div');
        card.className = 'summary-card';

        // Try to format with headers
        let formattedSummary = summary;

        // Highlight medical terms (bold markers from the LLM)
        formattedSummary = formattedSummary
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/Chief Complaint/gi, '<strong>Chief Complaint</strong>')
            .replace(/History of Present Illness/gi, '<strong>History of Present Illness</strong>')
            .replace(/Diagnosis/gi, '<strong>Diagnosis</strong>')
            .replace(/Treatment Plan/gi, '<strong>Treatment Plan</strong>')
            .replace(/Assessment/gi, '<strong>Assessment</strong>')
            .replace(/Medications/gi, '<strong>Medications</strong>');

        card.innerHTML = `
            <div class="summary-text">${formattedSummary}</div>
        `;

        container.appendChild(card);

        // Setup copy button
        const btnCopy = document.getElementById('btn-copy-summary');
        btnCopy.onclick = () => {
            navigator.clipboard.writeText(summary).then(() => {
                App.showToast('Summary copied to clipboard', 'success');
            });
        };
    }

    /**
     * Setup transcript search functionality.
     */
    function setupTranscriptSearch(segments) {
        const searchInput = document.getElementById('transcript-search-input');
        searchInput.oninput = () => {
            const query = searchInput.value.toLowerCase().trim();
            const segmentEls = document.querySelectorAll('.transcript-segment');

            segmentEls.forEach((el, i) => {
                const seg = segments.filter(s => s.text && s.text.trim())[i];
                if (!seg) return;

                if (!query) {
                    el.style.display = 'flex';
                    el.querySelector('.segment-text').innerHTML = escapeHtml(seg.text);
                    return;
                }

                const text = seg.text.toLowerCase();
                if (text.includes(query)) {
                    el.style.display = 'flex';
                    // Highlight matches
                    const escaped = escapeHtml(seg.text);
                    const regex = new RegExp(`(${escapeRegex(query)})`, 'gi');
                    el.querySelector('.segment-text').innerHTML = escaped.replace(regex, '<mark>$1</mark>');
                } else {
                    el.style.display = 'none';
                }
            });
        };
    }

    /**
     * Setup transcript copy and download actions.
     */
    function setupTranscriptActions(segments) {
        const btnCopy = document.getElementById('btn-copy-transcript');
        const btnDownload = document.getElementById('btn-download-transcript');

        const fullText = segments
            .filter(s => s.text && s.text.trim())
            .map(s => `[${formatSpeakerName(s.speaker_id)} ${formatTime(s.start_time)}-${formatTime(s.end_time)}] ${s.text}`)
            .join('\n');

        btnCopy.onclick = () => {
            navigator.clipboard.writeText(fullText).then(() => {
                App.showToast('Transcript copied to clipboard', 'success');
            });
        };

        btnDownload.onclick = () => {
            const blob = new Blob([fullText], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'transcript.txt';
            a.click();
            URL.revokeObjectURL(url);
            App.showToast('Transcript downloaded', 'success');
        };
    }

    // ── Helpers ──

    function formatSpeakerName(speakerId) {
        const num = speakerId.replace(/\D/g, '');
        return `Speaker ${parseInt(num) || 1}`;
    }

    function formatTime(seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function escapeRegex(str) {
        return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    return { renderAll };
})();
