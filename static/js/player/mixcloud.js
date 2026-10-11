// Mixcloud Player Adapter for CrossWave Hybrid (SDK caricato LAZY)
import { state } from '../core/state.js';
import { switchTab } from '../core/router.js';
import { loadScriptOnce } from '../core/utils.js';

const MIXCLOUD_SDK_URL = 'https://widget.mixcloud.com/media/js/widgetApi.js';
let _callbacks = { onState: null, onFinish: null, onProgress: null };

// Registra i callback globali; NON carica l'SDK (avviene al primo play).
export function initMixcloud(setPlayingStateCallback, handleTrackFinishedCallback, updateProgressBarCallback) {
    _callbacks = {
        onState: setPlayingStateCallback,
        onFinish: handleTrackFinishedCallback,
        onProgress: updateProgressBarCallback,
    };
    if (window.Mixcloud && typeof Mixcloud.PlayerWidget === 'function') {
        _createWidget();
    }
}

function _createWidget() {
    try {
        const mcIframe = document.getElementById('mc-player-iframe');
        if (!mcIframe || !window.Mixcloud || typeof Mixcloud.PlayerWidget !== 'function') return;
        if (state.mcWidget) return;
        state.mcWidget = Mixcloud.PlayerWidget(mcIframe);
        if (state.mcWidget && state.mcWidget.ready) {
            state.mcWidget.ready.then(() => {
                if (typeof state.mcWidget.setVolume === 'function') {
                    state.mcWidget.setVolume(state.currentVolume / 100);
                }
                const ev = state.mcWidget.events;
                if (!ev) return;
                if (ev.play && _callbacks.onState) ev.play.on(() => _callbacks.onState(true));
                if (ev.pause && _callbacks.onState) ev.pause.on(() => _callbacks.onState(false));
                if (ev.ended && _callbacks.onFinish) ev.ended.on(() => _callbacks.onFinish());
                if (ev.progress && _callbacks.onProgress) {
                    ev.progress.on((seconds, duration) => {
                        if (state.activePlayer === 'mixcloud') _callbacks.onProgress(seconds, duration);
                    });
                }
            }).catch(e => console.error('Mixcloud ready error', e));
        }
    } catch (e) {
        console.warn('Mixcloud SDK unavailable or restricted', e);
    }
}

export async function renderMixcloudView(track, setPlayingStateCallback) {
    let path = track.url || '';
    if (path.includes('mixcloud.com')) {
        const parts = path.split('mixcloud.com');
        path = parts[1] || '';
    }
    path = path.split('?')[0].split('#')[0];
    if (!path.startsWith('/')) path = '/' + path;
    if (!path.endsWith('/')) path = path + '/';

    const titleEl = document.getElementById('mc-view-title');
    const artistEl = document.getElementById('mc-view-artist');
    const iframe = document.getElementById('mc-player-iframe');

    if (titleEl) titleEl.innerText = track.title || 'Mixcloud DJ Set';
    if (artistEl) artistEl.innerText = track.artist || 'Mixcloud';

    if (iframe) {
        iframe.src = `https://www.mixcloud.com/widget/iframe/?hide_cover=0&mini=0&autoplay=1&feed=${path}`;
    }

    switchTab('mixcloud-view');
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    if (setPlayingStateCallback) setPlayingStateCallback(true);

    try {
        await loadScriptOnce(MIXCLOUD_SDK_URL, 'Mixcloud');
        _createWidget();
    } catch (e) {
        console.warn('Mixcloud SDK non caricato', e);
    }
}

export function pauseMc() {
    if (state.mcWidget && typeof state.mcWidget.pause === 'function') {
        try { state.mcWidget.pause(); } catch (e) {}
    }
}

export function resumeMc() {
    if (state.mcWidget && typeof state.mcWidget.play === 'function') {
        try { state.mcWidget.play(); } catch (e) {}
    }
}

export function seekMc(seconds) {
    if (state.mcWidget && typeof state.mcWidget.seek === 'function') {
        try { state.mcWidget.seek(seconds); } catch (e) {}
    }
}

export function setMcVolume(volume) {
    if (state.mcWidget && typeof state.mcWidget.setVolume === 'function') {
        try { state.mcWidget.setVolume(volume / 100); } catch (e) {}
    }
}
