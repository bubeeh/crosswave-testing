// Orchestrator for Audio Playback, Player Controls & Queue for CrossWave Hybrid
import { state } from '../core/state.js';
import { showToast, formatTime, getPlatformGradient, escapeHtml } from '../core/utils.js';
import { switchTab } from '../core/router.js';
import { initYoutubeAdapter, startYoutubeProgressPolling, stopYoutubeProgressPolling } from './youtube.js';
import { initBcAudio, playBcStream, pauseBc, resumeBc, seekBc, setBcVolume } from './bandcamp.js';
import { initMixcloud, renderMixcloudView, pauseMc, resumeMc, seekMc, setMcVolume } from './mixcloud.js';
import { ensureSCPlayer } from './soundcloud.js';
import { startRadioMetadataPolling, stopRadioMetadataPolling } from './radio.js';

export function initAudioPlayers() {
    initYoutubeAdapter(onYoutubeStateChange);
    initMixcloud(setPlayingState, handleTrackFinished, updateProgressBar);
    initBcAudio(setPlayingState, handleTrackFinished, updateProgressBar);
}

function onYoutubeStateChange(event) {
    if (typeof YT !== 'undefined') {
        if (event.data === YT.PlayerState.PLAYING) {
            setPlayingState(true);
            startYoutubeProgressPolling(updateProgressBar);
        } else if (event.data === YT.PlayerState.PAUSED) {
            setPlayingState(false);
            stopYoutubeProgressPolling();
        } else if (event.data === YT.PlayerState.ENDED) {
            stopYoutubeProgressPolling();
            handleTrackFinished();
        }
    }
}

export function pauseAllPlayers() {
    stopYoutubeProgressPolling();
    stopRadioMetadataPolling();

    const mainIframe = document.getElementById('main-yt-iframe');
    if (mainIframe && mainIframe.contentWindow) {
        try {
            mainIframe.contentWindow.postMessage('{"event":"command","func":"pauseVideo","args":""}', '*');
        } catch (e) {}
    }

    if (state.ytPlayer && typeof state.ytPlayer.pauseVideo === 'function') {
        try { state.ytPlayer.pauseVideo(); } catch (e) {}
    }
    if (state.scWidget && typeof state.scWidget.pause === 'function') {
        try { state.scWidget.pause(); } catch (e) {}
    }
    pauseMc();
    pauseBc();
}

export function togglePlayPause() {
    if (!state.currentTrack) return;

    if (state.isPlaying) {
        pauseActive();
    } else {
        resumeActive();
    }
}

export function pauseActive() {
    if (!state.currentTrack) return;

    if (state.activePlayer === 'youtube') {
        const mainIframe = document.getElementById('main-yt-iframe');
        if (mainIframe && mainIframe.contentWindow) {
            mainIframe.contentWindow.postMessage('{"event":"command","func":"pauseVideo","args":""}', '*');
        }
        if (state.ytPlayer && typeof state.ytPlayer.pauseVideo === 'function') {
            state.ytPlayer.pauseVideo();
        }
    } else if (state.activePlayer === 'soundcloud') {
        pauseBc();
    } else if (state.activePlayer === 'mixcloud') {
        pauseMc();
    } else if (state.activePlayer === 'bandcamp' || state.activePlayer === 'radio' || state.activePlayer === 'local') {
        pauseBc();
    }
    setPlayingState(false);
}

export function resumeActive() {
    if (!state.currentTrack) return;

    if (state.activePlayer === 'youtube') {
        const mainIframe = document.getElementById('main-yt-iframe');
        if (mainIframe && mainIframe.contentWindow) {
            mainIframe.contentWindow.postMessage('{"event":"command","func":"playVideo","args":""}', '*');
        }
        if (state.ytPlayer && typeof state.ytPlayer.playVideo === 'function') {
            state.ytPlayer.playVideo();
        }
    } else if (state.activePlayer === 'soundcloud') {
        resumeBc();
    } else if (state.activePlayer === 'mixcloud') {
        resumeMc();
    } else if (state.activePlayer === 'bandcamp' || state.activePlayer === 'radio' || state.activePlayer === 'local') {
        if (state.activePlayer === 'radio' && state.bcAudio && (!state.bcAudio.src || state.bcAudio.src === '')) {
            state.bcAudio.src = state.currentTrack.url;
        }
        resumeBc();
    }
    setPlayingState(true);
}

export function seekToPercent(percent) {
    if (!state.currentTrack) return;

    let duration = 0;
    if (state.activePlayer === 'youtube' && state.ytPlayer && typeof state.ytPlayer.getDuration === 'function') {
        duration = state.ytPlayer.getDuration() || 0;
        const targetSeconds = (percent / 100) * duration;
        state.ytPlayer.seekTo(targetSeconds, true);
    } else if ((state.activePlayer === 'bandcamp' || state.activePlayer === 'soundcloud' || state.activePlayer === 'radio' || state.activePlayer === 'local') && state.bcAudio) {
        duration = state.bcAudio.duration || 0;
        const targetSeconds = (percent / 100) * duration;
        seekBc(targetSeconds);
    } else if (state.activePlayer === 'mixcloud' && state.mcWidget && typeof state.mcWidget.getDuration === 'function') {
        state.mcWidget.getDuration().then((dur) => {
            const targetSeconds = (percent / 100) * dur;
            seekMc(targetSeconds);
        });
    }
}

export function setVolume(val) {
    state.currentVolume = val;

    const volumeFill = document.getElementById('player-volume-fill');
    const volumeSlider = document.getElementById('player-volume-slider');
    if (volumeFill) volumeFill.style.width = `${val}%`;
    if (volumeSlider) volumeSlider.value = val;

    const icon = document.getElementById('volume-icon');
    if (icon) {
        if (val === 0) {
            icon.className = 'fa-solid fa-volume-xmark';
        } else if (val < 40) {
            icon.className = 'fa-solid fa-volume-low';
        } else {
            icon.className = 'fa-solid fa-volume-high';
        }
    }

    if (state.ytPlayer && typeof state.ytPlayer.setVolume === 'function') {
        try { state.ytPlayer.setVolume(val); } catch (e) {}
    }
    if (state.scWidget && typeof state.scWidget.setVolume === 'function') {
        try { state.scWidget.setVolume(val / 100); } catch (e) {}
    }
    setMcVolume(val);
    setBcVolume(val);
}

export function toggleMute() {
    if (state.currentVolume > 0) {
        state.preMuteVolume = state.currentVolume;
        setVolume(0);
    } else {
        setVolume(state.preMuteVolume);
    }
}

export function playTrackImmediately(track) {
    if (state.queue.length === 0) {
        state.queue.push(track);
        state.currentIndex = 0;
    } else {
        state.queue.splice(state.currentIndex + 1, 0, track);
        state.currentIndex++;
    }

    renderQueue();
    playTrack(track);
}

// Riproduzione con video: play immediato + apertura della vista video.
// Usata dal bottone 🎬 sulle righe dei risultati YouTube e dal toggle video della player bar.
export function playTrackWithVideo(track) {
    playTrackImmediately(track);
    switchTab('video-view');
}

export function setPlayingState(playing) {
    state.isPlaying = playing;
    const playPauseBtn = document.getElementById('ctrl-play-pause');
    if (!playPauseBtn) return;
    const icon = playPauseBtn.querySelector('i');

    if (playing) {
        playPauseBtn.classList.add('playing');
        if (icon) icon.className = 'fa-solid fa-pause';
    } else {
        playPauseBtn.classList.remove('playing');
        if (icon) icon.className = 'fa-solid fa-play play-icon';
    }
}

export function updateProgressBar(currentSeconds, totalSeconds) {
    const progressSlider = document.getElementById('player-progress-slider');
    if (!progressSlider) return;

    const percentage = totalSeconds > 0 ? (currentSeconds / totalSeconds) * 100 : 0;

    progressSlider.value = percentage;
    updateProgressFill(percentage);

    const currentTimeEl = document.getElementById('player-time-current');
    const totalTimeEl = document.getElementById('player-time-total');
    if (currentTimeEl) currentTimeEl.innerText = formatTime(currentSeconds);
    if (totalTimeEl) totalTimeEl.innerText = formatTime(totalSeconds);
}

export function updateProgressFill(percentage) {
    const fill = document.getElementById('player-progress-fill');
    if (fill) fill.style.width = `${percentage}%`;
}

export function addToQueue(track) {
    state.queue.push(track);
    renderQueue();
}

export function addPlaylistTracksToQueue(tracks, playImmediately = false) {
    if (tracks.length === 0) return;

    const insertPos = state.currentIndex + 1;
    if (playImmediately) {
        state.queue.splice(insertPos, 0, ...tracks);
        state.currentIndex = insertPos;
        renderQueue();
        playTrack(state.queue[state.currentIndex]);
    } else {
        state.queue.push(...tracks);
        renderQueue();
    }
}

export function renderQueue() {
    const list = document.getElementById('queue-tracks-list');
    if (!list) return;
    list.innerHTML = '';

    if (state.queue.length === 0) {
        list.innerHTML = '<div class="empty-state-text" style="padding: 20px;">Nessun brano in coda. Cerca canzoni per aggiungerle.</div>';
        return;
    }

    state.queue.forEach((track, index) => {
        const isActive = index === state.currentIndex;
        const row = document.createElement('div');
        row.className = `track-row ${isActive ? 'active' : ''}`;
        row.setAttribute('data-queue-idx', index);

        let sourceIcon = 'fa-solid fa-music';
        if (track.source === 'youtube') sourceIcon = 'fa-brands fa-youtube';
        if (track.source === 'soundcloud') sourceIcon = 'fa-brands fa-soundcloud';
        if (track.source === 'bandcamp') sourceIcon = 'fa-brands fa-bandcamp';
        if (track.source === 'mixcloud') sourceIcon = 'fa-brands fa-mixcloud';

        row.innerHTML = `
            <div class="track-row-index">${isActive ? '<i class="fa-solid fa-volume-high spinner-slow"></i>' : index + 1}</div>
            <img class="track-row-thumbnail" src="${track.thumbnail || 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=80'}" alt="Thumb">
            <div class="track-row-details">
                <div class="track-row-title truncate">${escapeHtml(track.title)}</div>
                <div class="track-row-artist truncate">${escapeHtml(track.artist)}</div>
            </div>
            <div class="track-row-source-badge ${track.source}">
                <i class="${sourceIcon}"></i>
            </div>
            <div class="track-row-duration">${formatTime(track.duration)}</div>
            <div class="track-row-actions">
                <button class="track-row-action-btn del" title="Rimuovi dalla Coda"><i class="fa-solid fa-xmark"></i></button>
            </div>
        `;

        row.addEventListener('click', (e) => {
            if (e.target.closest('.track-row-action-btn')) return;
            state.currentIndex = index;
            playTrack(track);
        });

        row.querySelector('.del').addEventListener('click', () => {
            removeTrackFromQueue(index);
        });

        list.appendChild(row);
    });
}

export function removeTrackFromQueue(index) {
    if (index === state.currentIndex) {
        pauseAllPlayers();
        state.queue.splice(index, 1);
        if (state.queue.length === 0) {
            state.currentIndex = -1;
            state.currentTrack = null;
            const header = document.getElementById('player-track-info-header');
            if (header) header.classList.add('hidden');
            const badge = document.getElementById('player-track-badge');
            if (badge) badge.classList.add('hidden');
            const sidebarCard = document.getElementById('sidebar-track-card');
            if (sidebarCard) sidebarCard.classList.add('hidden');
        } else {
            if (state.currentIndex >= state.queue.length) state.currentIndex = state.queue.length - 1;
            playTrack(state.queue[state.currentIndex]);
        }
    } else {
        state.queue.splice(index, 1);
        if (index < state.currentIndex) {
            state.currentIndex--;
        }
    }
    renderQueue();
}

export function clearQueue() {
    pauseAllPlayers();
    state.queue = [];
    state.currentIndex = -1;
    state.currentTrack = null;
    const header = document.getElementById('player-track-info-header');
    if (header) header.classList.add('hidden');
    const badge = document.getElementById('player-track-badge');
    if (badge) badge.classList.add('hidden');
    const sidebarCard = document.getElementById('sidebar-track-card');
    if (sidebarCard) sidebarCard.classList.add('hidden');
    renderQueue();
    showToast('Coda svuotata');
}

export function updateActiveQueueItemRow() {
    document.querySelectorAll('.track-row').forEach(row => {
        row.classList.remove('active');
        const index = parseInt(row.getAttribute('data-queue-idx'));
        if (index === state.currentIndex) {
            row.classList.add('active');
            const idxDiv = row.querySelector('.track-row-index');
            if (idxDiv) {
                idxDiv.innerHTML = '<i class="fa-solid fa-volume-high"></i>';
            }
        } else {
            const idxDiv = row.querySelector('.track-row-index');
            if (idxDiv && !isNaN(index)) {
                idxDiv.innerText = index + 1;
            }
        }
    });
}

export function handleTrackFinished() {
    if (state.repeatMode === 'one') {
        playTrack(state.currentTrack);
    } else {
        nextTrack();
    }
}

export function nextTrack() {
    if (state.queue.length === 0) return;

    if (state.shuffleMode) {
        if (state.queue.length > 1) {
            let nextIndex = state.currentIndex;
            while (nextIndex === state.currentIndex) {
                nextIndex = Math.floor(Math.random() * state.queue.length);
            }
            state.currentIndex = nextIndex;
        } else {
            state.currentIndex = 0;
        }
    } else {
        state.currentIndex++;
        if (state.currentIndex >= state.queue.length) {
            if (state.repeatMode === 'all') {
                state.currentIndex = 0;
            } else {
                state.currentIndex = state.queue.length;
                pauseAllPlayers();
                setPlayingState(false);
                showToast('Fine della coda di riproduzione');
                return;
            }
        }
    }

    playTrack(state.queue[state.currentIndex]);
}

export function prevTrack() {
    if (state.queue.length === 0) return;

    state.currentIndex--;
    if (state.currentIndex < 0) {
        if (state.repeatMode === 'all') {
            state.currentIndex = state.queue.length - 1;
        } else {
            state.currentIndex = 0;
        }
    }

    playTrack(state.queue[state.currentIndex]);
}

export async function playTrack(track) {
    if (!track) return;

    pauseAllPlayers();

    state.activePlayer = track.source;
    state.currentTrack = track;

    // Update bottom player bar UI
    const header = document.getElementById('player-track-info-header');
    if (header) header.classList.remove('hidden');

    const title = document.getElementById('player-track-title');
    const artist = document.getElementById('player-track-artist');
    const art = document.getElementById('player-track-art');
    const artGlow = document.getElementById('player-track-art-glow');
    const badge = document.getElementById('player-track-badge');

    if (title) title.innerText = track.title || 'Senza Titolo';
    if (artist) artist.innerText = track.artist || 'Artista Sconosciuto';
    if (art) art.src = track.thumbnail || 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=80';
    if (artGlow) artGlow.style.background = getPlatformGradient(track.source);

    if (badge) {
        badge.classList.remove('hidden', 'youtube', 'soundcloud', 'bandcamp', 'mixcloud');
        badge.classList.add(track.source);
        const tag = badge.querySelector('.badge-tag');
        if (tag) {
            let label = 'YT';
            if (track.source === 'soundcloud') label = 'SC';
            if (track.source === 'bandcamp') label = 'BC';
            if (track.source === 'mixcloud') label = 'MC';
            if (track.source === 'radio') label = 'LIVE';
            if (track.source === 'local') label = 'LOCAL';
            tag.innerText = label;
        }
    }

    // Update sidebar mini-card UI
    const sidebarCard = document.getElementById('sidebar-track-card');
    const sidebarArt = document.getElementById('sidebar-card-art');
    const sidebarTitle = document.getElementById('sidebar-card-title');
    const sidebarArtist = document.getElementById('sidebar-card-artist');

    if (sidebarCard) sidebarCard.classList.remove('hidden');
    if (sidebarArt) sidebarArt.src = track.thumbnail || 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=80';
    if (sidebarTitle) sidebarTitle.innerText = track.title || 'Senza Titolo';
    if (sidebarArtist) sidebarArtist.innerText = track.artist || 'Artista Sconosciuto';

    updateProgressBar(0, track.duration || 0);

    // Call addToHistory dynamically imported from views/library.js
    if (window.addToHistory) {
        window.addToHistory(track);
    }

    updateActiveQueueItemRow();

    try {
        if (track.source === 'youtube') {
            const rawId = String(track.track_id || track.id || '');
            const videoId = rawId.replace('yt_', '');

            const mainIframe = document.getElementById('main-yt-iframe');
            const placeholder = document.getElementById('video-placeholder');
            const titleDisplay = document.getElementById('video-title-display');
            const artistDisplay = document.getElementById('video-artist-display');

            if (mainIframe) {
                mainIframe.src = `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&enablejsapi=1&rel=0`;
                mainIframe.classList.remove('hidden');
                if (placeholder) placeholder.classList.add('hidden');
            }
            if (titleDisplay) titleDisplay.innerText = track.title;
            if (artistDisplay) artistDisplay.innerText = track.artist;

            // NIENTE switch automatico a video-view: la riproduzione YT resta in background
            // (audio). L'utente decide se aprire il player video con il bottone TV della
            // player bar o col bottone 🎬 sulla riga (playTrackWithVideo).

        } else if (track.source === 'soundcloud') {
            showToast('Risoluzione streaming SoundCloud...');
            try {
                const res = await fetch(`/api/resolve_track?url=${encodeURIComponent(track.url)}`);
                const data = await res.json();
                if (data.yt_id) {
                    showToast('Riproduzione traccia completa via YouTube...');
                    track.source = 'youtube';
                    track.id = `yt_${data.yt_id}`;
                    if (data.duration) track.duration = data.duration;
                    playTrack(track);
                    return;
                } else if (data.stream_url) {
                    if (data.duration) updateProgressBar(0, data.duration);
                    playBcStream(`/api/proxy_audio?url=${encodeURIComponent(track.url)}`);
                } else {
                    throw new Error(data.error || 'Impossibile estrarre lo stream');
                }
            } catch (e) {
                console.error('SoundCloud resolve failed', e);
                showToast('Errore di riproduzione audio.', 'error');
                handleTrackFinished();
            }
        } else if (track.source === 'mixcloud') {
            renderMixcloudView(track, setPlayingState);
        } else if (track.source === 'radio') {
            playBcStream(track.url);
            startRadioMetadataPolling(track);
        } else if (track.source === 'bandcamp') {
            showToast('Estrazione streaming Bandcamp...');
            const response = await fetch(`/api/bandcamp/track?url=${encodeURIComponent(track.url)}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            if (!track.duration && data.duration) {
                track.duration = data.duration;
            }

            const streamUrl = `/api/proxy_audio?url=${encodeURIComponent(data.stream_url)}&ref=${encodeURIComponent(track.url)}`;
            playBcStream(streamUrl);
        } else if (track.source === 'local') {
            showToast('Riproduzione traccia locale...');
            playBcStream(track.url);
        }

        setPlayingState(true);
    } catch (err) {
        console.error('Play track failed', err);
        showToast(err.message || 'Errore nella riproduzione.', 'error');
        handleTrackFinished();
    }
}
