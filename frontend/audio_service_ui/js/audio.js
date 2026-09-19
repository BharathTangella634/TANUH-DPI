/**
 * DISPLACE MedAI – Audio Module
 * Handles file upload, drag-and-drop, waveform visualization,
 * and audio playback using Web Audio API.
 */

const AudioModule = (() => {
    // State
    let audioFile = null;
    let audioContext = null;
    let audioBuffer = null;
    let audioSource = null;
    let isPlaying = false;
    let startTime = 0;
    let pauseOffset = 0;
    let animationFrame = null;

    // DOM refs
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');
    const fileInfo = document.getElementById('file-info');
    const fileName = document.getElementById('file-name');
    const fileSize = document.getElementById('file-size');
    const btnRemove = document.getElementById('btn-remove');
    const audioPlayer = document.getElementById('audio-player');
    const waveformCanvas = document.getElementById('waveform-canvas');
    const playhead = document.getElementById('playhead');
    const btnPlay = document.getElementById('btn-play');
    const playIcon = document.getElementById('play-icon');
    const pauseIcon = document.getElementById('pause-icon');
    const playerTime = document.getElementById('player-time');
    const btnProcess = document.getElementById('btn-process');

    /** Initialize event listeners */
    function init() {
        // Click to upload
        uploadZone.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', handleFileSelect);

        // Drag and drop
        uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadZone.classList.add('drag-over');
        });
        uploadZone.addEventListener('dragleave', () => {
            uploadZone.classList.remove('drag-over');
        });
        uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadZone.classList.remove('drag-over');
            const files = e.dataTransfer.files;
            if (files.length > 0) loadFile(files[0]);
        });

        // Remove file
        btnRemove.addEventListener('click', removeFile);

        // Play/pause
        btnPlay.addEventListener('click', togglePlay);

        // Click on waveform to seek
        const waveformContainer = document.getElementById('waveform-container');
        waveformContainer.addEventListener('click', (e) => {
            if (!audioBuffer) return;
            const rect = waveformContainer.getBoundingClientRect();
            const pct = (e.clientX - rect.left) / rect.width;
            seekTo(pct * audioBuffer.duration);
        });
    }

    /** Handle file input change */
    function handleFileSelect(e) {
        if (e.target.files.length > 0) {
            loadFile(e.target.files[0]);
        }
    }

    /** Load and decode an audio file */
    async function loadFile(file) {
        // Validate
        const validTypes = ['audio/wav', 'audio/mpeg', 'audio/flac', 'audio/ogg', 'audio/x-m4a', 'audio/mp4'];
        const ext = file.name.split('.').pop().toLowerCase();
        const validExts = ['wav', 'mp3', 'flac', 'ogg', 'm4a'];

        if (!validExts.includes(ext)) {
            App.showToast('Unsupported file format. Please upload .wav, .mp3, .flac, .ogg, or .m4a', 'error');
            return;
        }

        audioFile = file;

        // Show file info
        fileName.textContent = file.name;
        fileSize.textContent = formatSize(file.size);
        uploadZone.classList.add('has-file');
        fileInfo.style.display = 'flex';

        // Decode audio for waveform
        try {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const arrayBuffer = await file.arrayBuffer();
            audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

            // Show player
            audioPlayer.style.display = 'block';
            drawWaveform();
            updateTime();
            btnProcess.disabled = false;
        } catch (err) {
            console.error('Audio decode error:', err);
            App.showToast('Failed to decode audio file', 'error');
        }
    }

    /** Draw waveform on canvas */
    function drawWaveform() {
        const canvas = waveformCanvas;
        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;

        canvas.width = canvas.clientWidth * dpr;
        canvas.height = canvas.clientHeight * dpr;
        ctx.scale(dpr, dpr);

        const width = canvas.clientWidth;
        const height = canvas.clientHeight;
        const data = audioBuffer.getChannelData(0);
        const step = Math.ceil(data.length / width);
        const mid = height / 2;

        ctx.clearRect(0, 0, width, height);

        // Draw bars
        for (let i = 0; i < width; i++) {
            let min = 1.0, max = -1.0;
            for (let j = 0; j < step; j++) {
                const idx = i * step + j;
                if (idx < data.length) {
                    if (data[idx] < min) min = data[idx];
                    if (data[idx] > max) max = data[idx];
                }
            }

            const barHeight = Math.max((max - min) * mid, 1);
            const y = mid - barHeight / 2;

            // Gradient effect
            const gradient = ctx.createLinearGradient(0, y, 0, y + barHeight);
            gradient.addColorStop(0, 'rgba(99, 102, 241, 0.7)');
            gradient.addColorStop(0.5, 'rgba(129, 140, 248, 0.9)');
            gradient.addColorStop(1, 'rgba(99, 102, 241, 0.7)');

            ctx.fillStyle = gradient;
            ctx.fillRect(i, y, 1, barHeight);
        }
    }

    /** Toggle play/pause */
    function togglePlay() {
        if (isPlaying) {
            pause();
        } else {
            play();
        }
    }

    /** Play audio */
    function play() {
        if (!audioBuffer || !audioContext) return;

        audioSource = audioContext.createBufferSource();
        audioSource.buffer = audioBuffer;
        audioSource.connect(audioContext.destination);

        startTime = audioContext.currentTime - pauseOffset;
        audioSource.start(0, pauseOffset);

        audioSource.onended = () => {
            if (isPlaying) {
                isPlaying = false;
                pauseOffset = 0;
                updatePlayButton();
                updateTime();
                playhead.style.left = '0%';
                cancelAnimationFrame(animationFrame);
            }
        };

        isPlaying = true;
        updatePlayButton();
        updatePlayhead();
    }

    /** Pause audio */
    function pause() {
        if (!audioSource) return;
        audioSource.stop();
        pauseOffset = audioContext.currentTime - startTime;
        isPlaying = false;
        updatePlayButton();
        cancelAnimationFrame(animationFrame);
    }

    /** Seek to time */
    function seekTo(time) {
        const wasPlaying = isPlaying;
        if (isPlaying) {
            audioSource.stop();
            isPlaying = false;
            cancelAnimationFrame(animationFrame);
        }
        pauseOffset = Math.max(0, Math.min(time, audioBuffer.duration));
        updateTime();
        updatePlayheadPosition();
        if (wasPlaying) play();
    }

    /** Update playhead position with animation */
    function updatePlayhead() {
        if (!isPlaying) return;
        updatePlayheadPosition();
        updateTime();
        animationFrame = requestAnimationFrame(updatePlayhead);
    }

    function updatePlayheadPosition() {
        if (!audioBuffer) return;
        const currentTime = isPlaying ? audioContext.currentTime - startTime : pauseOffset;
        const pct = (currentTime / audioBuffer.duration) * 100;
        playhead.style.left = `${Math.min(pct, 100)}%`;
    }

    /** Update play/pause icon */
    function updatePlayButton() {
        playIcon.style.display = isPlaying ? 'none' : 'block';
        pauseIcon.style.display = isPlaying ? 'block' : 'none';
    }

    /** Update time display */
    function updateTime() {
        if (!audioBuffer) return;
        const current = isPlaying ? audioContext.currentTime - startTime : pauseOffset;
        const total = audioBuffer.duration;
        playerTime.textContent = `${formatTime(current)} / ${formatTime(total)}`;
    }

    /** Remove uploaded file */
    function removeFile() {
        if (isPlaying) pause();

        audioFile = null;
        audioBuffer = null;
        audioSource = null;
        pauseOffset = 0;

        uploadZone.classList.remove('has-file');
        fileInfo.style.display = 'none';
        audioPlayer.style.display = 'none';
        fileInput.value = '';
        btnProcess.disabled = true;

        playhead.style.left = '0%';
        playerTime.textContent = '0:00 / 0:00';
    }

    /** Format bytes to human readable */
    function formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    /** Format seconds to mm:ss */
    function formatTime(seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    /** Get the current audio file */
    function getFile() {
        return audioFile;
    }

    return { init, getFile, removeFile };
})();
