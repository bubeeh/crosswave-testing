// YouTube Player Adapter for CrossWave Hybrid
import { state } from '../core/state.js';
import { showToast } from '../core/utils.js';

export function startYoutubeProgressPolling(updateProgressBarCallback) {
    stopYoutubeProgressPolling();
    state.ytProgressInterval = setInterval(() => {
        if (state.activePlayer === 'youtube' && state.ytPlayer && state.isPlaying && typeof state.ytPlayer.getCurrentTime === 'function') {
            const current = state.ytPlayer.getCurrentTime();
            const duration = state.ytPlayer.getDuration() || 0;
            if (updateProgressBarCallback) {
                updateProgressBarCallback(current, duration);
            }
        }
    }, 500);
}

export function stopYoutubeProgressPolling() {
    if (state.ytProgressInterval) {
        clearInterval(state.ytProgressInterval);
        state.ytProgressInterval = null;
    }
}

export function initYoutubeAdapter(onStateChangeHandler) {
    window.onYouTubeIframeAPIReady = function() {
        if (typeof YT !== 'undefined' && YT.Player) {
            state.ytPlayer = new YT.Player('yt-player-placeholder', {
                height: '100%',
                width: '100%',
                videoId: '',
                host: 'https://www.youtube.com',
                playerVars: {
                    'autoplay': 1,
                    'controls': 1,
                    'enablejsapi': 1,
                    'origin': window.location.origin,
                    'playsinline': 1,
                    'rel': 0,
                    'modestbranding': 1
                },
                events: {
                    'onReady': (event) => {
                        console.log('YouTube Player Pronto');
                        if (state.ytPlayer && typeof state.ytPlayer.setVolume === 'function') {
                            state.ytPlayer.setVolume(state.currentVolume);
                        }
                    },
                    'onStateChange': onStateChangeHandler,
                    'onError': (e) => {
                        console.error('YouTube Player Error Code:', e.data);
                        if (e.data === 150 || e.data === 101) {
                            showToast('Questo video non consente l\'incorporamento esterno.', 'error');
                        }
                    }
                }
            });
        }
    };

    // IIFE loader for YT Iframe API
    if (!window.YT) {
        const tag = document.createElement('script');
        tag.src = "https://www.youtube.com/iframe_api";
        const firstScriptTag = document.getElementsByTagName('script')[0];
        if (firstScriptTag && firstScriptTag.parentNode) {
            firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);
        } else {
            document.head.appendChild(tag);
        }
    }
}
