// Album View Module for CrossWave Hybrid
import { showToast, calculateTotalDuration } from '../core/utils.js';
import { switchTab } from '../core/router.js';
import { createResultRow } from './search.js';
import { addPlaylistTracksToQueue } from '../player/player.js';
import { sendToSoundload } from './soundload.js';

export async function openBandcampAlbumDetailView(albumTrack) {
    switchTab('album-detail');
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

    const albumUrl = (typeof albumTrack === 'string') ? albumTrack : (albumTrack?.url || albumTrack?.webpage_url || albumTrack?.permalink_url);
    if (!albumUrl) {
        showToast('URL dell\'album non trovato.', 'error');
        return;
    }

    const cover = document.getElementById('album-view-cover');
    const glow = document.getElementById('album-view-glow');
    const title = document.getElementById('album-view-title');
    const artist = document.getElementById('album-view-artist');
    const countText = document.getElementById('album-view-count');
    const durationText = document.getElementById('album-view-duration');
    const list = document.getElementById('album-view-tracks-list');
    const infoBox = document.getElementById('album-info-box');
    const description = document.getElementById('album-view-description');
    const credits = document.getElementById('album-view-credits');

    if (cover) cover.src = albumTrack.thumbnail || 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=300';
    if (glow) glow.style.background = `radial-gradient(circle, rgba(0, 242, 254, 0.35) 0%, rgba(0,0,0,0) 70%)`;
    if (title) title.innerText = albumTrack.title || 'Caricamento Album...';
    if (artist) artist.innerText = albumTrack.artist || 'Caricamento Artista...';
    if (countText) countText.innerText = 'Caricamento tracce...';
    if (durationText) durationText.innerText = '-- min';
    if (list) list.innerHTML = '<div class="loader-spinner"><div class="double-bounce1"></div><div class="double-bounce2"></div></div>';
    if (infoBox) infoBox.classList.add('hidden');

    try {
        const response = await fetch(`/api/bandcamp/album?url=${encodeURIComponent(albumUrl)}`);
        const data = await response.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        const tracks = data.tracks || [];
        if (title) title.innerText = data.album_title || albumTrack.title;
        if (artist) artist.innerText = data.artist || albumTrack.artist;
        if (data.thumbnail && cover) cover.src = data.thumbnail;
        if (countText) countText.innerText = `${tracks.length} tracce`;
        if (durationText) durationText.innerText = calculateTotalDuration(tracks);

        if ((data.description || data.credits) && infoBox) {
            if (description) description.innerText = data.description || 'Nessuna nota aggiuntiva.';
            if (credits) credits.innerText = data.credits || 'Nessun credito specificato.';
            infoBox.classList.remove('hidden');
        } else if (infoBox) {
            infoBox.classList.add('hidden');
        }

        if (list) {
            list.innerHTML = '';
            tracks.forEach((t, idx) => {
                const row = createResultRow(t, idx);
                list.appendChild(row);
            });
        }

        const btnPlayAll = document.getElementById('btn-album-play-all');
        if (btnPlayAll) {
            btnPlayAll.onclick = () => {
                if (tracks.length > 0) addPlaylistTracksToQueue(tracks, true);
            };
        }

        const btnDlAll = document.getElementById('btn-album-download-all');
        if (btnDlAll) {
            btnDlAll.onclick = () => {
                sendToSoundload(albumTrack);
            };
        }

        const btnExtSource = document.getElementById('btn-album-external-source');
        if (btnExtSource) {
            btnExtSource.href = albumUrl;
            btnExtSource.classList.remove('hidden');
        }

    } catch (err) {
        console.error('Failed to load Bandcamp album view', err);
        showToast('Errore nel caricamento dell\'album Bandcamp', 'error');
    }
}

export async function loadAndAddAlbumToQueue(albumTrack, playImmediately = false) {
    const albumUrl = (typeof albumTrack === 'string') ? albumTrack : (albumTrack?.url || albumTrack?.webpage_url || albumTrack?.permalink_url);
    if (!albumUrl) {
        showToast('URL dell\'album non trovato.', 'error');
        return;
    }

    showToast('Caricamento dell\'album...');
    try {
        const response = await fetch(`/api/bandcamp/album?url=${encodeURIComponent(albumUrl)}`);
        const data = await response.json();
        const tracks = data.tracks || [];
        if (tracks.length > 0) {
            addPlaylistTracksToQueue(tracks, playImmediately);
            showToast(`Aggiunto l'album "${data.album_title}" alla coda.`, 'success');
        } else {
            showToast('Nessuna traccia trovata nell\'album.', 'error');
        }
    } catch (err) {
        console.error(err);
        showToast('Errore nel caricamento dell\'album.', 'error');
    }
}

export async function playAllAlbumTracks() {
    const modal = document.getElementById('album-tracks-modal');
    if (!modal) return;
    const url = modal.getAttribute('data-album-url');
    if (!url) return;

    modal.classList.add('hidden');
    showToast('Caricamento album...');

    try {
        const response = await fetch(`/api/bandcamp/album?url=${encodeURIComponent(url)}`);
        const data = await response.json();
        const tracks = data.tracks || [];
        if (tracks.length > 0) {
            addPlaylistTracksToQueue(tracks, true);
        } else {
            showToast('Nessuna traccia da riprodurre.', 'error');
        }
    } catch (err) {
        console.error(err);
        showToast('Errore nel caricamento dell\'album.', 'error');
    }
}
