// Mixcloud Player Adapter for CrossWave Hybrid
import { state } from '../core/state.js';
import { switchTab } from '../core/router.js';

export function initMixcloud(setPlayingStateCallback, handleTrackFinishedCallback, updateProgressBarCallback) {
    try {
        const mcIframe = document.getElementById('mc-player-iframe');
        if (mcIframe && window.Mixcloud && typeof Mixcloud.PlayerWidget === 'function') {
            state.mcWidget = Mixcloud.PlayerWidget(mcIframe);
            if (state.mcWidget && state.mcWidget.ready) {
                state.mcWidget.ready.then(() => {
                    console.log('Mixcloud Player Pronto');
                    if (state.mcWidget && typeof state.mcWidget.setVolume === 'function') {
                        state.mcWidget.setVolume(state.currentVolume / 100);
                    }
                    if (state.mcWidget.events) {
                        if (state.mcWidget.events.play && setPlayingStateCallback) {
                            state.mcWidget.events.play.on(() => setPlayingStateCallback(true));
                        }
                        if (state.mcWidget.events.pause && setPlayingStateCallback) {
                            state.mcWidget.events.pause.on(() => setPlayingStateCallback(false));
                        }
                        if (state.mcWidget.events.ended && handleTrackFinishedCallback) {
                            state.mcWidget.events.ended.on(() => handleTrackFinishedCallback());
                        }
                        if (state.mcWidget.events.progress && updateProgressBarCallback) {
                            state.mcWidget.events.progress.on((seconds, duration) => {
                                if (state.activePlayer === 'mixcloud') {
                                    updateProgressBarCallback(seconds, duration);
                                }
                            });
                        }
                    }
                }).catch(e => console.error('Mixcloud ready error', e));
            }
        }
    } catch (e) {
        console.warn('Mixcloud SDK unavailable or restricted', e);
    }
}

export function renderMixcloudView(track, setPlayingStateCallback) {
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
