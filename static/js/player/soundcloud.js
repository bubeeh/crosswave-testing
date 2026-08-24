// SoundCloud Player Adapter for CrossWave Hybrid
import { state } from '../core/state.js';

export function ensureSCPlayer(setPlayingStateCallback, handleTrackFinishedCallback, updateProgressBarCallback) {
    return new Promise((resolve) => {
        if (state.scWidget || typeof SC === 'undefined') { resolve(); return; }
        const iframe = document.getElementById('sc-player-iframe');
        if (!iframe) { resolve(); return; }
        if (!iframe.src) {
            iframe.src = 'https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/49931161&show_artwork=false&visual=false&auto_play=false';
        }
        state.scWidget = SC.Widget(iframe);

        state.scWidget.bind(SC.Widget.Events.READY, () => {
            if (state.scWidget && typeof state.scWidget.setVolume === 'function') {
                state.scWidget.setVolume(state.currentVolume / 100);
            }
        });
        if (setPlayingStateCallback) {
            state.scWidget.bind(SC.Widget.Events.PLAY, () => setPlayingStateCallback(true));
            state.scWidget.bind(SC.Widget.Events.PAUSE, () => setPlayingStateCallback(false));
        }
        if (handleTrackFinishedCallback) {
            state.scWidget.bind(SC.Widget.Events.FINISH, () => handleTrackFinishedCallback());
        }
        if (updateProgressBarCallback) {
            state.scWidget.bind(SC.Widget.Events.PLAY_PROGRESS, (progress) => {
                if (state.activePlayer === 'soundcloud') {
                    const currentSeconds = progress.currentPosition / 1000;
                    const totalSeconds = progress.relativePosition * currentSeconds / (progress.relativePosition || 1) / 1000 || (state.currentTrack ? state.currentTrack.duration : 0) || 0;
                    updateProgressBarCallback(currentSeconds, totalSeconds);
                }
            });
        }

        const readyHandler = () => {
            state.scWidget.unbind(SC.Widget.Events.READY, readyHandler);
            if (state.scWidget && typeof state.scWidget.setVolume === 'function') {
                state.scWidget.setVolume(state.currentVolume / 100);
            }
            resolve();
        };
        state.scWidget.bind(SC.Widget.Events.READY, readyHandler);
        setTimeout(resolve, 8000);
    });
}
