// Bandcamp & HTML5 Audio Adapter for CrossWave Hybrid
import { state } from '../core/state.js';
import { showToast } from '../core/utils.js';

export function initBcAudio(setPlayingStateCallback, handleTrackFinishedCallback, updateProgressBarCallback) {
    state.bcAudio = document.getElementById('bc-audio-player');
    if (!state.bcAudio) return;

    state.bcAudio.volume = state.currentVolume / 100;

    state.bcAudio.addEventListener('play', () => {
        if (setPlayingStateCallback) setPlayingStateCallback(true);
    });

    state.bcAudio.addEventListener('pause', () => {
        if (setPlayingStateCallback) setPlayingStateCallback(false);
    });

    state.bcAudio.addEventListener('ended', () => {
        if (handleTrackFinishedCallback) handleTrackFinishedCallback();
    });

    state.bcAudio.addEventListener('timeupdate', () => {
        if (state.activePlayer === 'bandcamp' || state.activePlayer === 'soundcloud' || state.activePlayer === 'radio' || state.activePlayer === 'local') {
            if (updateProgressBarCallback) {
                updateProgressBarCallback(state.bcAudio.currentTime, state.bcAudio.duration || 0);
            }
        }
    });

    state.bcAudio.addEventListener('error', (e) => {
        console.error('HTML5 audio error', e);
        if (state.activePlayer === 'bandcamp' || state.activePlayer === 'soundcloud' || state.activePlayer === 'local') {
            showToast('Errore di riproduzione audio. Salto al successivo.', 'error');
            if (handleTrackFinishedCallback) handleTrackFinishedCallback();
        }
    });
}

export function playBcStream(streamUrl) {
    if (!state.bcAudio) return;
    state.bcAudio.src = streamUrl;
    state.bcAudio.volume = state.currentVolume / 100;
    state.bcAudio.play();
}

export function pauseBc() {
    if (state.bcAudio) {
        state.bcAudio.pause();
    }
}

export function resumeBc() {
    if (state.bcAudio) {
        state.bcAudio.play();
    }
}

export function seekBc(seconds) {
    if (state.bcAudio && !isNaN(seconds)) {
        state.bcAudio.currentTime = seconds;
    }
}

export function setBcVolume(volume) {
    if (state.bcAudio) {
        state.bcAudio.volume = volume / 100;
    }
}
