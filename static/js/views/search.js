// Search View Module for CrossWave Hybrid
import { showToast, formatTime, escapeHtml } from '../core/utils.js';
import { playTrackImmediately, addToQueue, playTrackWithVideo } from '../player/player.js';
import { addFavoriteTrack, addWatchLaterTrack, openAddToPlaylistModal } from './library.js';
import { loadAndAddAlbumToQueue, openBandcampAlbumDetailView } from './album.js';
import { sendToSoundload } from './soundload.js';

export async function executeSearch() {
    const queryEl = document.getElementById('search-input');
    if (!queryEl) return;
    const query = queryEl.value.trim();
    if (!query) return;

    const placeholder = document.getElementById('search-placeholder');
    const loader = document.getElementById('search-loader');
    const metaRow = document.getElementById('results-meta-row');
    const countText = document.getElementById('results-count-text');

    if (placeholder) placeholder.classList.add('hidden');
    if (loader) loader.classList.remove('hidden');
    if (metaRow) metaRow.classList.remove('hidden');
    if (countText) countText.innerText = `Ricerca in corso per "${query}"...`;

    const list = document.getElementById('search-results-list');
    if (list) list.innerHTML = '';

    const sources = [];
    const chkYt = document.getElementById('chk-yt');
    const chkSc = document.getElementById('chk-sc');
    const chkBc = document.getElementById('chk-bc');
    const chkMc = document.getElementById('chk-mc');

    if (chkYt && chkYt.checked) sources.push('youtube');
    if (chkSc && chkSc.checked) sources.push('soundcloud');
    if (chkBc && chkBc.checked) sources.push('bandcamp');
    if (chkMc && chkMc.checked) sources.push('mixcloud');

    if (sources.length === 0) {
        sources.push('youtube', 'soundcloud', 'bandcamp', 'mixcloud');
    }

    try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&sources=${sources.join(',')}`);
        const data = await response.json();

        if (loader) loader.classList.add('hidden');

        let results = [];
        const errors = [];
        const perSource = (data.results && typeof data.results === 'object') ? data.results : {};
        Object.keys(perSource).forEach(src => {
            const entry = perSource[src] || {};
            if (Array.isArray(entry.results)) {
                results = results.concat(entry.results);
            }
            if (entry.error) {
                errors.push(entry.message || `Errore durante la ricerca su ${src}`);
            }
        });

        if (countText) {
            if (errors.length > 0) {
                countText.innerText = `${results.length} risultati trovati per "${query}" — ${errors.length} sorgente/i con problemi`;
                errors.forEach(msg => showToast(msg, 'error'));
            } else {
                countText.innerText = `${results.length} risultati trovati per "${query}"`;
            }
        }

        if (!list) return;

        if (results.length === 0) {
            const noResultMsg = errors.length > 0
                ? 'Nessun risultato disponibile. Controlla i messaggi di errore delle singole sorgenti.'
                : 'Nessun risultato trovato. Prova con altre parole chiave.';
            list.innerHTML = `<div class="search-placeholder-state"><i class="fa-solid fa-face-frown placeholder-icon"></i><p>${noResultMsg}</p></div>`;
            return;
        }

        results.forEach((track, index) => {
            const row = createResultRow(track, index);
            list.appendChild(row);
        });

    } catch (err) {
        console.error(err);
        if (loader) loader.classList.add('hidden');
        if (countText) countText.innerText = 'Errore durante la ricerca.';
        showToast('Errore nel contattare il server.', 'error');
    }
}

export function createResultRow(track, index) {
    const row = document.createElement('div');
    row.className = 'track-row';

    let sourceIcon = 'fa-solid fa-music';
    if (track.source === 'youtube') sourceIcon = 'fa-brands fa-youtube';
    if (track.source === 'soundcloud') sourceIcon = 'fa-brands fa-soundcloud';
    if (track.source === 'bandcamp') sourceIcon = 'fa-brands fa-bandcamp';
    if (track.source === 'mixcloud') sourceIcon = 'fa-brands fa-mixcloud';

    const typeBadge = track.type === 'album' ? '<span class="card-type-badge">Album</span>' : '';

    // Bottone 🎬 per riprodurre con video: solo sorgenti YouTube (tracce singole)
    const videoBtnHtml = (track.source === 'youtube' && track.type !== 'album')
        ? '<button class="track-row-action-btn vd-s" title="Riproduci con video"><i class="fa-solid fa-tv"></i></button>'
        : '';

    row.innerHTML = `
        <div class="track-row-index">
            <button class="track-row-play-btn" title="Riproduci"><i class="fa-solid fa-play"></i></button>
        </div>
        <img class="track-row-thumbnail" src="${track.thumbnail || 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=80'}" alt="Thumb">
        <div class="track-row-details">
            <div class="track-row-title truncate">${escapeHtml(track.title)} ${typeBadge}</div>
            <div class="track-row-artist truncate">${escapeHtml(track.artist)}</div>
        </div>
        <div class="track-row-source-badge ${track.source}">
            <i class="${sourceIcon}"></i>
        </div>
        <div class="track-row-duration">${track.duration > 0 ? formatTime(track.duration) : '--:--'}</div>
        <div class="track-row-actions">
            ${videoBtnHtml}
            <button class="track-row-action-btn add-f" title="Aggiungi ai Preferiti"><i class="fa-solid fa-heart"></i></button>
            <button class="track-row-action-btn add-wl" title="Aggiungi a Guarda Dopo"><i class="fa-solid fa-clock"></i></button>
            <button class="track-row-action-btn add-q" title="Aggiungi alla coda"><i class="fa-solid fa-plus"></i></button>
            <button class="track-row-action-btn add-p" title="Aggiungi alla playlist"><i class="fa-solid fa-folder-plus"></i></button>
            <button class="track-row-action-btn dl-s" title="Scarica con Soundload"><i class="fa-solid fa-cloud-arrow-down"></i></button>
        </div>
    `;

    row.addEventListener('click', (e) => {
        if (e.target.closest('.track-row-action-btn') || e.target.closest('.track-row-play-btn')) return;
        handlePlayAction(track);
    });

    const playBtn = row.querySelector('.track-row-play-btn');
    if (playBtn) {
        playBtn.addEventListener('click', () => {
            handlePlayAction(track);
        });
    }

    // Bottone 🎬 (solo YouTube): riproduci con video (play + switch a video-view)
    const vdS = row.querySelector('.vd-s');
    if (vdS) {
        vdS.addEventListener('click', () => {
            playTrackWithVideo(track);
        });
    }

    const addF = row.querySelector('.add-f');
    if (addF) addF.addEventListener('click', () => addFavoriteTrack(track));

    const addWl = row.querySelector('.add-wl');
    if (addWl) addWl.addEventListener('click', () => addWatchLaterTrack(track));

    const addQ = row.querySelector('.add-q');
    if (addQ) {
        addQ.addEventListener('click', () => {
            if (track.type === 'album') {
                loadAndAddAlbumToQueue(track, false);
            } else {
                addToQueue(track);
                showToast('Aggiunto in coda: ' + track.title, 'success');
            }
        });
    }

    const addP = row.querySelector('.add-p');
    if (addP) {
        addP.addEventListener('click', () => {
            if (track.type === 'album') {
                showToast('Le playlist supportano solo tracce individuali.', 'error');
                return;
            }
            openAddToPlaylistModal(track);
        });
    }

    const dlS = row.querySelector('.dl-s');
    if (dlS) dlS.addEventListener('click', () => sendToSoundload(track));

    return row;
}

export function handlePlayAction(track) {
    if (track.type === 'album') {
        openBandcampAlbumDetailView(track);
    } else {
        playTrackImmediately(track);
    }
}

export function initSearchView() {
    const searchBtn = document.getElementById('search-btn');
    const searchInput = document.getElementById('search-input');

    if (searchBtn) searchBtn.addEventListener('click', executeSearch);
    if (searchInput) {
        searchInput.addEventListener('keyup', (e) => {
            if (e.key === 'Enter') executeSearch();
        });
    }

    document.querySelectorAll('.filter-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            const chk = pill.querySelector('input[type="checkbox"]');
            if (chk) {
                chk.checked = !chk.checked;
                if (chk.checked) {
                    pill.classList.add('checked');
                } else {
                    pill.classList.remove('checked');
                }
            }

            const queryInput = document.getElementById('search-input');
            if (queryInput && queryInput.value.trim().length > 0) {
                executeSearch();
            }
        });
    });
}

if (document.readyState !== 'loading') {
    initSearchView();
} else {
    document.addEventListener('DOMContentLoaded', () => {
        initSearchView();
    });
}
