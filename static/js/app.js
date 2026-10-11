// Application Entry Point for CrossWave Hybrid (Modular ES SPA)
import { state } from './core/state.js';
import { showToast } from './core/utils.js';
import { initRouter, registerTab, navigate, switchTab } from './core/router.js';
import {
    initAudioPlayers, togglePlayPause, prevTrack, nextTrack,
    seekToPercent, setVolume, toggleMute, renderQueue, updateProgressFill
} from './player/player.js';
import './player/youtube.js';
import './player/bandcamp.js';
import './player/mixcloud.js';
import './player/soundcloud.js';
import './player/radio.js';
import { loadHomeDashboard } from './views/home.js';
import './views/search.js';
import { openAddToPlaylistModal, renderPlaylists, renderHistory } from './views/library.js';
import './views/album.js';
import { loadWebRadios } from './views/radios.js';
import { loadRandomMixIfNeeded } from './views/mixrandom.js';
import { loadTelegramFeed } from './views/telegram.js';
import { startDownloadsPolling, stopDownloadsPolling } from './views/downloads.js';
import './views/soundload.js';

function onDOMReady(fn) {
    if (document.readyState !== 'loading') {
        fn();
    } else {
        document.addEventListener('DOMContentLoaded', fn);
    }
}

onDOMReady(() => {
    // 1. Register Tab Lifecycle Handlers in Router
    registerTab('home', { onEnter: loadHomeDashboard });
    registerTab('downloads', { onEnter: startDownloadsPolling, onLeave: stopDownloadsPolling });
    registerTab('web-radio', { onEnter: loadWebRadios });
    registerTab('mix-random', { onEnter: loadRandomMixIfNeeded });
    registerTab('playlists', { onEnter: renderPlaylists });
    registerTab('telegram', { onEnter: loadTelegramFeed });
    registerTab('queue-history', {
        onEnter: () => {
            renderQueue();
            renderHistory();
        }
    });

    // 2. Initialize Audio Players & Adapters
    initAudioPlayers();

    // 3. Bind Global Player Bar Controls
    const playPauseBtn = document.getElementById('ctrl-play-pause');
    if (playPauseBtn) playPauseBtn.addEventListener('click', togglePlayPause);

    const prevBtn = document.getElementById('ctrl-prev');
    if (prevBtn) prevBtn.addEventListener('click', prevTrack);

    const nextBtn = document.getElementById('ctrl-next');
    if (nextBtn) nextBtn.addEventListener('click', nextTrack);

    const shuffleBtn = document.getElementById('ctrl-shuffle');
    if (shuffleBtn) {
        shuffleBtn.addEventListener('click', () => {
            state.shuffleMode = !state.shuffleMode;
            shuffleBtn.classList.toggle('active', state.shuffleMode);
            showToast(state.shuffleMode ? 'Modalità casuale attiva' : 'Modalità casuale disattivata');
        });
    }

    const repeatBtn = document.getElementById('ctrl-repeat');
    if (repeatBtn) {
        repeatBtn.addEventListener('click', () => {
            if (state.repeatMode === 'none') {
                state.repeatMode = 'all';
                repeatBtn.classList.add('active');
                repeatBtn.querySelector('i').className = 'fa-solid fa-repeat';
                showToast('Ripeti tutti i brani');
            } else if (state.repeatMode === 'all') {
                state.repeatMode = 'one';
                repeatBtn.classList.add('active');
                repeatBtn.querySelector('i').className = 'fa-solid fa-square-1';
                showToast('Ripeti brano corrente');
            } else {
                state.repeatMode = 'none';
                repeatBtn.classList.remove('active');
                repeatBtn.querySelector('i').className = 'fa-solid fa-repeat';
                showToast('Ripetizione disattivata');
            }
        });
    }

    const progressSlider = document.getElementById('player-progress-slider');
    if (progressSlider) {
        progressSlider.addEventListener('input', (e) => {
            const val = parseFloat(e.target.value);
            updateProgressFill(val);
        });
        progressSlider.addEventListener('change', (e) => {
            const percent = parseFloat(e.target.value);
            seekToPercent(percent);
        });
    }

    const volumeSlider = document.getElementById('player-volume-slider');
    if (volumeSlider) {
        volumeSlider.addEventListener('input', (e) => {
            const val = parseInt(e.target.value);
            setVolume(val);
        });
    }

    const muteBtn = document.getElementById('btn-mute');
    if (muteBtn) muteBtn.addEventListener('click', toggleMute);

    const toggleQueueBtn = document.getElementById('btn-toggle-queue');
    if (toggleQueueBtn) {
        toggleQueueBtn.addEventListener('click', () => {
            navigate('queue-history');
        });
    }

    const btnPlayerPlaylist = document.getElementById('btn-player-playlist');
    if (btnPlayerPlaylist) {
        btnPlayerPlaylist.addEventListener('click', () => {
            if (!state.currentTrack) {
                showToast('Nessun brano in riproduzione da aggiungere alla Playlist.', 'error');
                return;
            }
            if (state.currentTrack.type === 'album') {
                showToast('Le playlist supportano solo tracce individuali.', 'error');
                return;
            }
            openAddToPlaylistModal(state.currentTrack);
        });
    }

    const btnToggleVideo = document.getElementById('btn-toggle-video');
    if (btnToggleVideo) {
        btnToggleVideo.addEventListener('click', () => {
            switchTab('video-view');
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            const navVid = document.getElementById('nav-btn-video');
            if (navVid) navVid.classList.add('active');
        });
    }

    // 4. Initialize Core Router & Hash Navigation
    initRouter();

    // 5. Mobile app-style UI (bottom sheet + full-screen player)
    initMobileUI();
});

// --- Mobile helpers ---
function initMobileUI() {
    const playerBar = document.querySelector('.player-bar');
    const expandBtn = document.getElementById('player-expand-btn');
    const collapseBtn = document.getElementById('player-collapse-btn');
    const trackInfoHeader = document.getElementById('player-track-info-header');

    const expandPlayer = () => {
        if (!playerBar || !state.currentTrack) return;
        playerBar.classList.add('expanded');
        document.body.classList.add('player-expanded');
    };
    const collapsePlayer = () => {
        if (!playerBar) return;
        playerBar.classList.remove('expanded');
        document.body.classList.remove('player-expanded');
    };

    if (expandBtn) expandBtn.addEventListener('click', (e) => { e.stopPropagation(); expandPlayer(); });
    if (trackInfoHeader) trackInfoHeader.addEventListener('click', expandPlayer);
    if (collapseBtn) collapseBtn.addEventListener('click', (e) => { e.stopPropagation(); collapsePlayer(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') collapsePlayer(); });

    // "Altro" bottom sheet
    const sheet = document.getElementById('mobile-more-sheet');
    const backdrop = document.getElementById('mobile-sheet-backdrop');
    let sheetCloseTimer = null;

    const openSheet = () => {
        if (!sheet || !backdrop) return;
        clearTimeout(sheetCloseTimer);
        backdrop.classList.remove('hidden');
        sheet.classList.remove('hidden');
        requestAnimationFrame(() => sheet.classList.add('open'));
    };
    const closeSheet = () => {
        if (!sheet || !backdrop) return;
        sheet.classList.remove('open');
        sheetCloseTimer = setTimeout(() => {
            sheet.classList.add('hidden');
            backdrop.classList.add('hidden');
        }, 250);
    };

    document.addEventListener('click', (e) => {
        const moreBtn = e.target.closest('[data-sheet="more"]');
        if (moreBtn) {
            e.preventDefault();
            if (sheet && sheet.classList.contains('open')) closeSheet();
            else openSheet();
            return;
        }
        if (e.target.closest('#mobile-sheet-backdrop')) {
            closeSheet();
            return;
        }
        // Chiudi lo sheet dopo aver scelto una voce
        if (e.target.closest('#mobile-more-sheet .nav-btn')) {
            closeSheet();
        }
    });

    // Evidenzia "Altro" quando la tab attiva è dentro lo sheet
    const syncMoreActive = () => {
        const moreBtn = document.getElementById('mtab-more');
        if (!moreBtn || !sheet) return;
        const hasActiveItem = !!sheet.querySelector('.mobile-sheet-item.active');
        moreBtn.classList.toggle('active', hasActiveItem);
    };
    window.addEventListener('hashchange', () => setTimeout(syncMoreActive, 0));
    syncMoreActive();
}

// --- PWA: registrazione Service Worker ---
if ('serviceWorker' in navigator) {
    // Quando arriva una nuova versione del SW (deploy), ricarica una volta per
    // applicare subito nuovi HTML/CSS/JS senza hard refresh manuale.
    let refreshing = false;
    const hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (!hadController || refreshing) return;
        refreshing = true;
        window.location.reload();
    });

    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch((err) => {
            console.warn('Service Worker non registrato:', err);
        });
    });
}
