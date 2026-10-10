// Collection (album / playlist / set) Detail View Module for CrossWave Hybrid
import { showToast, calculateTotalDuration } from '../core/utils.js';
import { switchTab } from '../core/router.js';
import { createResultRow } from './search.js';
import { addPlaylistTracksToQueue } from '../player/player.js';
import { sendToSoundload } from './soundload.js';

const COLLECTION_BADGES = {
    bandcamp: { icon: 'fa-brands fa-bandcamp', label: 'ALBUM RELEASE' },
    youtube: { icon: 'fa-brands fa-youtube', label: 'PLAYLIST YOUTUBE' },
    soundcloud: { icon: 'fa-brands fa-soundcloud', label: 'SET SOUNDCLOUD' },
};

const PLATFORM_LABELS = {
    bandcamp: 'Bandcamp',
    youtube: 'YouTube',
    soundcloud: 'SoundCloud',
    mixcloud: 'Mixcloud',
};

function collectionUrl(collection) {
    if (typeof collection === 'string') return collection;
    return collection?.url || collection?.webpage_url || collection?.permalink_url;
}

function collectionSource(collection, fallback) {
    if (collection && typeof collection === 'object' && collection.source) return collection.source;
    return fallback;
}

async function fetchCollection(url) {
    const response = await fetch(`/api/collection?url=${encodeURIComponent(url)}`);
    return response.json();
}

// Apre la vista dettaglio di una raccolta (album Bandcamp, playlist YouTube,
// set SoundCloud): stesso layout, tracklist e play-all con avanzamento auto.
export async function openCollectionDetailView(collection) {
    switchTab('album-detail');
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

    const url = collectionUrl(collection);
    if (!url) {
        showToast('URL della raccolta non trovato.', 'error');
        return;
    }

    const source = collectionSource(collection, 'bandcamp');
    const badge = COLLECTION_BADGES[source] || COLLECTION_BADGES.bandcamp;

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
    const badgeEl = document.getElementById('album-view-badge');

    if (badgeEl) badgeEl.innerHTML = `<i class="${badge.icon}"></i> ${badge.label}`;
    if (cover) cover.src = collection.thumbnail || 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=300';
    if (glow) glow.style.background = `radial-gradient(circle, rgba(0, 242, 254, 0.35) 0%, rgba(0,0,0,0) 70%)`;
    if (title) title.innerText = collection.title || 'Caricamento raccolta...';
    if (artist) artist.innerText = collection.artist || 'Caricamento artista...';
    if (countText) countText.innerText = 'Caricamento tracce...';
    if (durationText) durationText.innerText = '-- min';
    if (list) list.innerHTML = '<div class="loader-spinner"><div class="double-bounce1"></div><div class="double-bounce2"></div></div>';
    if (infoBox) infoBox.classList.add('hidden');

    try {
        const data = await fetchCollection(url);

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        const tracks = data.tracks || [];
        if (title) title.innerText = data.album_title || collection.title;
        if (artist) artist.innerText = data.artist || collection.artist;
        if (data.thumbnail && cover) cover.src = data.thumbnail;
        if (countText) countText.innerText = `${tracks.length} tracce`;
        if (durationText) durationText.innerText = calculateTotalDuration(tracks);

        const hasInfo = !!(data.description || data.credits);
        if (hasInfo && infoBox) {
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
                sendToSoundload(collection);
            };
        }

        const btnExtSource = document.getElementById('btn-album-external-source');
        if (btnExtSource) {
            btnExtSource.href = url;
            const platformLabel = PLATFORM_LABELS[data.platform] || 'piattaforma';
            btnExtSource.innerHTML = `<i class="fa-solid fa-arrow-up-right-from-square"></i> Apri su ${platformLabel}`;
            btnExtSource.classList.remove('hidden');
        }

    } catch (err) {
        console.error('Failed to load collection view', err);
        showToast('Errore nel caricamento della raccolta', 'error');
    }
}

// Retro-compatibilità: il vecchio nome puntava solo agli album Bandcamp.
export const openBandcampAlbumDetailView = openCollectionDetailView;

export async function loadAndAddAlbumToQueue(collection, playImmediately = false) {
    const url = collectionUrl(collection);
    if (!url) {
        showToast('URL della raccolta non trovato.', 'error');
        return;
    }

    showToast('Caricamento della raccolta...');
    try {
        const data = await fetchCollection(url);
        const tracks = data.tracks || [];
        if (tracks.length > 0) {
            addPlaylistTracksToQueue(tracks, playImmediately);
            showToast(`Aggiunta la raccolta "${data.album_title}" alla coda.`, 'success');
        } else {
            showToast('Nessuna traccia trovata nella raccolta.', 'error');
        }
    } catch (err) {
        console.error(err);
        showToast('Errore nel caricamento della raccolta.', 'error');
    }
}

export async function playAllAlbumTracks() {
    const modal = document.getElementById('album-tracks-modal');
    if (!modal) return;
    const url = modal.getAttribute('data-album-url');
    if (!url) return;

    modal.classList.add('hidden');
    showToast('Caricamento raccolta...');

    try {
        const data = await fetchCollection(url);
        const tracks = data.tracks || [];
        if (tracks.length > 0) {
            addPlaylistTracksToQueue(tracks, true);
        } else {
            showToast('Nessuna traccia da riprodurre.', 'error');
        }
    } catch (err) {
        console.error(err);
        showToast('Errore nel caricamento della raccolta.', 'error');
    }
}
