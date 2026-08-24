// Web Radio Player Adapter & Metadata Polling for CrossWave Hybrid
import { state } from '../core/state.js';

export function stopRadioMetadataPolling() {
    if (state.radioMetadataInterval) {
        clearInterval(state.radioMetadataInterval);
        state.radioMetadataInterval = null;
    }
}

export function startRadioMetadataPolling(track) {
    stopRadioMetadataPolling();
    const updateMeta = async () => {
        if (state.activePlayer !== 'radio' || !state.currentTrack || state.currentTrack.id !== track.id) return;
        try {
            const res = await fetch(`/api/radios/now_playing?url=${encodeURIComponent(track.url)}&name=${encodeURIComponent(track.title)}`);
            const data = await res.json();
            if (data.now_playing) {
                const artistEl = document.getElementById('player-track-artist');
                const titleEl = document.getElementById('player-track-title');
                const sbTitleEl = document.getElementById('sidebar-card-title');
                const sbArtistEl = document.getElementById('sidebar-card-artist');

                if (artistEl) artistEl.innerText = `🟢 LIVE • ${track.title}`;
                if (titleEl) titleEl.innerText = data.now_playing;
                if (sbTitleEl) sbTitleEl.innerText = data.now_playing;
                if (sbArtistEl) sbArtistEl.innerText = `🟢 LIVE • ${track.title}`;
            }
        } catch (e) {}
    };
    updateMeta();
    state.radioMetadataInterval = setInterval(updateMeta, 8000);
}
