// Soundload Integration Module for CrossWave Hybrid
import { showToast } from '../core/utils.js';
import { state } from '../core/state.js';

export async function sendToSoundload(track) {
    if (!track || !track.url) {
        showToast('Impossibile scaricare: URL mancante.', 'error');
        return;
    }
    showToast('Invio download a Soundload ☁️...');

    try {
        const res = await fetch('/api/soundload/enqueue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: track.url,
                title: track.title || 'Brano Audio',
                artist: track.artist || ''
            })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message || 'Download avviato su Soundload ☁️', 'success');
        } else {
            showToast(data.error || 'Errore nell\'avvio del download', 'error');
        }
    } catch (err) {
        console.error('Failed to enqueue Soundload download', err);
        showToast('Errore di connessione a Soundload', 'error');
    }
}

export function initSoundloadBindings() {
    const btnPlayerDl = document.getElementById('btn-player-soundload');
    if (btnPlayerDl) {
        btnPlayerDl.addEventListener('click', () => {
            if (state.currentTrack) {
                sendToSoundload(state.currentTrack);
            } else {
                showToast('Nessun brano in riproduzione da scaricare.', 'error');
            }
        });
    }

    const btnTheaterDl = document.getElementById('btn-theater-download');
    if (btnTheaterDl) {
        btnTheaterDl.addEventListener('click', () => {
            if (state.currentTrack) {
                sendToSoundload(state.currentTrack);
            } else {
                showToast('Nessun brano in riproduzione da scaricare.', 'error');
            }
        });
    }
}

if (document.readyState !== 'loading') {
    initSoundloadBindings();
} else {
    document.addEventListener('DOMContentLoaded', () => {
        initSoundloadBindings();
    });
}
