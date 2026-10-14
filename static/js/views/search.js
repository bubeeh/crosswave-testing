// Search View Module for CrossWave Hybrid
import { showToast, formatTime, escapeHtml, PLACEHOLDER_COVER, isCollectionUrl, youtubeVideoId } from '../core/utils.js';
import { playTrackImmediately, addToQueue, playTrackWithVideo, addPlaylistTracksToQueue } from '../player/player.js';
import { openAddToPlaylistModal } from './library.js';
import { loadAndAddAlbumToQueue, openCollectionDetailView } from './album.js';
import { openCatalogView } from './catalog.js';

let currentSearchResults = [];
let currentPage = 1;
const RESULTS_PER_PAGE = 10;

const SOURCE_LABELS = {
    youtube: 'YouTube',
    soundcloud: 'SoundCloud',
    bandcamp: 'Bandcamp',
    mixcloud: 'Mixcloud',
};

const SOURCE_ICONS = {
    youtube: 'fa-brands fa-youtube',
    soundcloud: 'fa-brands fa-soundcloud',
    bandcamp: 'fa-brands fa-bandcamp',
    mixcloud: 'fa-brands fa-mixcloud',
};

// Riconosce un URL di piattaforma incollato nel campo di ricerca.
function parsePlatformUrl(query) {
    const url = query.trim();
    if (!/^https?:\/\//i.test(url)) return null;
    const lower = url.toLowerCase();
    if (lower.includes('youtube.com') || lower.includes('youtu.be')) return { platform: 'youtube', url };
    if (lower.includes('bandcamp.com')) return { platform: 'bandcamp', url };
    if (lower.includes('soundcloud.com')) return { platform: 'soundcloud', url };
    if (lower.includes('mixcloud.com')) return { platform: 'mixcloud', url };
    return null;
}

// Un URL incollato apre la vista giusta invece di essere cercato come testo:
// raccolta → vista album; canale/profilo → catalogo; traccia → riproduzione.
function handleUrlQuery({ platform, url }) {
    if (isCollectionUrl(platform, url)) {
        showToast('Apertura raccolta...');
        openCollectionDetailView({ url, source: platform });
        return true;
    }
    if (platform === 'youtube' && /youtube\.com\/(channel\/|c\/|@)/i.test(url)) {
        showToast('Apertura catalogo...');
        openCatalogView({ url, platform, name: '' });
        return true;
    }
    if (platform === 'bandcamp' && !/\/(album|track)\//i.test(url)) {
        showToast('Apertura catalogo...');
        openCatalogView({ url, platform, name: '' });
        return true;
    }
    // Traccia singola: riproduci subito.
    const native = platform === 'youtube' ? youtubeVideoId(url) : '';
    playTrackImmediately({
        id: native ? `yt_${native}` : url,
        title: 'Riproduzione da URL',
        artist: '',
        source: platform,
        url,
        thumbnail: '',
        duration: 0,
        type: 'track',
    });
    return true;
}

export async function executeSearch() {
    const queryEl = document.getElementById('search-input');
    if (!queryEl) return;
    const query = queryEl.value.trim();
    if (!query) return;

    const urlQuery = parsePlatformUrl(query);
    if (urlQuery) {
        handleUrlQuery(urlQuery);
        return;
    }

    const placeholder = document.getElementById('search-placeholder');
    const loader = document.getElementById('search-loader');
    const metaRow = document.getElementById('results-meta-row');
    const countText = document.getElementById('results-count-text');
    const paginationControls = document.getElementById('search-pagination-controls');

    if (placeholder) placeholder.classList.add('hidden');
    if (loader) loader.classList.remove('hidden');
    if (metaRow) metaRow.classList.remove('hidden');
    if (paginationControls) paginationControls.classList.add('hidden');
    const playAllBtn = document.getElementById('search-play-all-btn');
    if (playAllBtn) playAllBtn.classList.add('hidden');
    if (countText) countText.innerText = `Ricerca in corso per "${query}"...`;
    resetSourceChips();

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
            if (entry.error && entry.error !== 'no_results') {
                errors.push(entry.message || `Errore durante la ricerca su ${src}`);
            }
        });

        // Lista unificata cross-platform (fusa per rilevanza dal backend).
        // Fallback retrocompatibile: concatenazione dei blocchi per sorgente.
        if (Array.isArray(data.items)) {
            results = data.items;
        } else {
            Object.keys(perSource).forEach(src => {
                const entry = perSource[src] || {};
                if (Array.isArray(entry.results)) {
                    results = results.concat(entry.results);
                }
            });
        }

        currentSearchResults = results;
        updateSourceChips(perSource);

        if (countText) {
            countText.innerText = `${results.length} risultati per “${query}”`;
            if (errors.length > 0) {
                errors.forEach(msg => showToast(msg, 'error'));
            }
        }

        if (playAllBtn) {
            playAllBtn.classList.toggle('hidden', results.length === 0);
        }

        if (!list) return;

        if (results.length === 0) {
            const noResultMsg = errors.length > 0
                ? 'Nessun risultato disponibile. Controlla i messaggi di errore delle singole sorgenti.'
                : 'Nessun risultato trovato. Prova con altre parole chiave.';
            list.innerHTML = `<div class="search-placeholder-state"><i class="fa-solid fa-face-frown placeholder-icon"></i><p>${noResultMsg}</p></div>`;
            renderPaginationControls(0, 0);
            return;
        }

        renderSearchResultsPage(1);

    } catch (err) {
        console.error(err);
        if (loader) loader.classList.add('hidden');
        if (countText) countText.innerText = 'Ricerca interrotta o timeout.';
        showToast('La ricerca ha impiegato troppo tempo o la connessione è stata interrotta. Riprova con meno sorgenti spuntate.', 'error');
    }
}

export function renderSearchResultsPage(page = 1) {
    currentPage = page;
    const list = document.getElementById('search-results-list');
    if (!list) return;

    list.innerHTML = '';
    const totalResults = currentSearchResults.length;
    const totalPages = Math.ceil(totalResults / RESULTS_PER_PAGE);

    if (totalResults === 0) {
        renderPaginationControls(0, 0);
        return;
    }

    const startIndex = (page - 1) * RESULTS_PER_PAGE;
    const pageTracks = currentSearchResults.slice(startIndex, startIndex + RESULTS_PER_PAGE);

    pageTracks.forEach((track, idx) => {
        const globalIndex = startIndex + idx;
        const row = createResultRow(track, globalIndex);
        list.appendChild(row);
    });

    renderPaginationControls(page, totalPages);
}

function renderPaginationControls(page, totalPages) {
    const controlsContainer = document.getElementById('search-pagination-controls');
    if (!controlsContainer) return;

    if (totalPages <= 1) {
        controlsContainer.classList.add('hidden');
        controlsContainer.innerHTML = '';
        return;
    }

    controlsContainer.classList.remove('hidden');
    controlsContainer.innerHTML = '';

    // Bottone Precedente <
    const prevBtn = document.createElement('button');
    prevBtn.className = 'page-btn page-prev';
    prevBtn.innerHTML = '<i class="fa-solid fa-chevron-left"></i>';
    if (page === 1) {
        prevBtn.style.opacity = '0.4';
        prevBtn.style.cursor = 'default';
    } else {
        prevBtn.addEventListener('click', () => {
            renderSearchResultsPage(page - 1);
            scrollToSearchResults();
        });
    }
    controlsContainer.appendChild(prevBtn);

    // Indicatore compatto "1 / n" (visibile solo su mobile)
    const indicator = document.createElement('span');
    indicator.className = 'page-indicator';
    indicator.innerText = `${page} / ${totalPages}`;
    controlsContainer.appendChild(indicator);

    // Bottoni numeri di pagina (1, 2, 3...) — nascosti su mobile
    for (let p = 1; p <= totalPages; p++) {
        const pageBtn = document.createElement('button');
        pageBtn.className = `page-btn page-num ${p === page ? 'active' : ''}`;
        pageBtn.innerText = p;
        pageBtn.addEventListener('click', () => {
            renderSearchResultsPage(p);
            scrollToSearchResults();
        });
        controlsContainer.appendChild(pageBtn);
    }

    // Bottone Successivo >
    const nextBtn = document.createElement('button');
    nextBtn.className = 'page-btn page-next';
    nextBtn.innerHTML = '<i class="fa-solid fa-chevron-right"></i>';
    if (page === totalPages) {
        nextBtn.style.opacity = '0.4';
        nextBtn.style.cursor = 'default';
    } else {
        nextBtn.addEventListener('click', () => {
            renderSearchResultsPage(page + 1);
            scrollToSearchResults();
        });
    }
    controlsContainer.appendChild(nextBtn);
}

function scrollToSearchResults() {
    const metaRow = document.getElementById('results-meta-row');
    if (metaRow) metaRow.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export function createResultRow(track, index, options = {}) {
    const row = document.createElement('div');
    row.className = 'track-row result-row';
    if (track.id) row.dataset.trackId = track.id;

    const sourceLabel = SOURCE_LABELS[track.source] || 'Web';
    const sourceIcon = SOURCE_ICONS[track.source] || 'fa-solid fa-music';

    const collectionLabel = { youtube: 'PLAYLIST', soundcloud: 'SET' }[track.source] || 'ALBUM';
    const typeBadge = (track.type === 'album')
        ? `<span class="badge-album" title="Raccolta (album / playlist / set)"><i class="fa-solid fa-compact-disc"></i> ${collectionLabel}</span>`
        : '';

    const topicBadge = track.is_topic
        ? `<span class="card-type-badge topic-badge" title="Canale auto-generato dell'artista">TOPIC</span>`
        : '';
    const verifiedBadge = (track.verified && !track.is_topic)
        ? `<i class="fa-solid fa-circle-check verified-badge" title="Canale ufficiale verificato"></i>`
        : '';

    const artistHtml = track.catalog_url
        ? `<span class="artist-catalog-link" title="Esplora il catalogo di ${escapeHtml(track.artist)}">${escapeHtml(track.artist || '')}</span>`
        : escapeHtml(track.artist || '');

    const webUrl = track.url || track.webpage_url || track.permalink_url;

    const extLinkHtml = webUrl
        ? `<a href="${escapeHtml(webUrl)}" target="_blank" rel="noopener noreferrer" class="result-action ext-link" title="Apri pagina fonte"><i class="fa-solid fa-arrow-up-right-from-square"></i><span class="result-action-label">Apri link</span></a>`
        : '';

    const videoBtnHtml = (track.source === 'youtube' && track.type !== 'album')
        ? `<button class="result-action vd-s" title="Riproduci con video"><i class="fa-solid fa-film"></i><span class="result-action-label">Video</span></button>`
        : '';

    const sourceInner = `<i class="${sourceIcon}"></i> <span>${escapeHtml(sourceLabel)}</span>`;
    const sourceHtml = webUrl
        ? `<a href="${escapeHtml(webUrl)}" target="_blank" rel="noopener noreferrer" class="result-source ${track.source}" title="Apri pagina web originale">${sourceInner}</a>`
        : `<span class="result-source ${track.source}">${sourceInner}</span>`;

    const coverSrc = track.thumbnail
        ? escapeHtml(track.thumbnail)
        : PLACEHOLDER_COVER;

    // Durata: mostrata solo se valida, altrimenti il campo è omesso (niente "--:--").
    const hasDuration = typeof track.duration === 'number' && isFinite(track.duration) && track.duration > 0;
    const durationLabel = hasDuration ? formatTime(track.duration) : '';

    row.innerHTML = `
        <button class="result-play" title="Riproduci"><i class="fa-solid fa-play"></i></button>
        <img class="result-cover"
             src="${coverSrc}"
             alt=""
             loading="lazy"
             onerror="this.onerror=null;this.src='${PLACEHOLDER_COVER}'">
        <div class="result-main">
            <div class="result-title truncate">${escapeHtml(track.title)} ${typeBadge}${topicBadge}</div>
            <div class="result-artist truncate">${artistHtml} ${verifiedBadge}${durationLabel ? `<span class="result-artist-meta"> &middot; ${durationLabel}</span>` : ''}</div>
        </div>
        ${sourceHtml}
        ${durationLabel ? `<div class="result-duration">${durationLabel}</div>` : ''}
        <button class="result-menu-btn" title="Altre azioni" aria-label="Altre azioni"><i class="fa-solid fa-ellipsis"></i></button>
        <div class="result-actions">
            <button class="result-action add-p" title="Aggiungi alla playlist"><i class="fa-solid fa-folder-plus"></i> Playlist</button>
            <button class="result-action add-q" title="Aggiungi alla coda"><i class="fa-solid fa-plus"></i> Coda</button>
            ${videoBtnHtml}
            ${extLinkHtml}
        </div>
    `;

    row.addEventListener('click', (e) => {
        if (e.target.closest('.result-action') || e.target.closest('.result-play') || e.target.closest('.result-source') || e.target.closest('.result-menu-btn') || e.target.closest('.artist-catalog-link')) return;
        handlePlayAction(track);
    });

    const artistLink = row.querySelector('.artist-catalog-link');
    if (artistLink) {
        artistLink.addEventListener('click', (e) => {
            e.stopPropagation();
            openCatalogView({ url: track.catalog_url, platform: track.source, name: track.artist, isTopic: track.is_topic });
        });
    }

    const playBtn = row.querySelector('.result-play');
    if (playBtn) {
        playBtn.addEventListener('click', () => {
            handlePlayAction(track);
        });
    }

    const vdS = row.querySelector('.vd-s');
    if (vdS) {
        vdS.addEventListener('click', () => {
            playTrackWithVideo(track);
        });
    }

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

    return row;
}

// --- Chip sorgenti: reset e conteggi per sorgente ---
function resetSourceChips() {
    document.querySelectorAll('.search-filters-row .filter-pill').forEach(pill => {
        const text = pill.querySelector('.chip-text');
        if (text) text.innerText = pill.dataset.label || pill.dataset.source;
    });
}

function updateSourceChips(perSource) {
    document.querySelectorAll('.search-filters-row .filter-pill').forEach(pill => {
        const source = pill.dataset.source;
        const label = pill.dataset.label || source;
        const text = pill.querySelector('.chip-text');
        if (!text) return;
        const entry = perSource ? perSource[source] : null;
        const count = entry && Array.isArray(entry.results) ? entry.results.length : 0;
        text.innerText = count > 0 ? `${label} · ${count}` : label;
    });
}

// --- Riproduci tutti i risultati (le raccolte vengono aperte) ---
export function playAllSearchResults() {
    const tracks = currentSearchResults.filter(t => t.type !== 'album');
    const albums = currentSearchResults.filter(t => t.type === 'album');

    if (tracks.length > 0) {
        addPlaylistTracksToQueue(tracks, true);
        showToast(`Riproduzione di ${tracks.length} brani`, 'success');
        return;
    }
    if (albums.length > 0) {
        loadAndAddAlbumToQueue(albums[0], true);
        return;
    }
    showToast('Nessun brano da riprodurre', 'error');
}

export function handlePlayAction(track) {
    if (track.type === 'album') {
        openCollectionDetailView(track);
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

    const playAllBtn = document.getElementById('search-play-all-btn');
    if (playAllBtn) playAllBtn.addEventListener('click', playAllSearchResults);

    // Menu "⋯" delle righe risultato (mobile): Playlist / Coda / Apri link
    document.addEventListener('click', (e) => {
        const menuBtn = e.target.closest('.result-menu-btn');
        if (menuBtn) {
            e.preventDefault();
            e.stopPropagation();
            const row = menuBtn.closest('.result-row');
            if (!row) return;
            const willOpen = !row.classList.contains('menu-open');
            document.querySelectorAll('.result-row.menu-open').forEach(r => r.classList.remove('menu-open'));
            row.classList.toggle('menu-open', willOpen);
            return;
        }
        // Qualunque altro click chiude i menu aperti
        document.querySelectorAll('.result-row.menu-open').forEach(r => r.classList.remove('menu-open'));
    }, true);

    // Default: tutte le sorgenti attive (chip con conteggio risultati)
    document.querySelectorAll('.search-filters-row .filter-pill').forEach(pill => {
        const chk = pill.querySelector('input[type="checkbox"]');
        if (chk && !pill.dataset.initialized) {
            chk.checked = true;
            pill.classList.add('checked');
            const source = pill.getAttribute('data-source');
            const homePill = document.querySelector(`.home-search-filters .filter-pill[data-source="${source}"]`);
            if (homePill) homePill.classList.add('active');
            pill.dataset.initialized = '1';
        }
    });

    document.querySelectorAll('.search-filters-row .filter-pill').forEach(pill => {
        pill.addEventListener('click', (e) => {
            e.preventDefault();
            const chk = pill.querySelector('input[type="checkbox"]');
            if (chk) {
                chk.checked = !chk.checked;
                pill.classList.toggle('checked', chk.checked);
                const source = pill.getAttribute('data-source');
                const homePill = document.querySelector(`.home-search-filters .filter-pill[data-source="${source}"]`);
                if (homePill) {
                    homePill.classList.toggle('active', chk.checked);
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
