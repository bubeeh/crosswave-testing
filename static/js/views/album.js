// Collection (album / playlist / set) Detail View Module for CrossWave Hybrid
import { showToast, calculateTotalDuration, formatTime, escapeHtml, PLACEHOLDER_COVER } from '../core/utils.js';
import { switchTab } from '../core/router.js';
import { openAddTracksToPlaylistModal } from './library.js';
import { addPlaylistTracksToQueue, playTrackImmediately } from '../player/player.js';

const COLLECTION_BADGES = {
    bandcamp: { icon: 'fa-brands fa-bandcamp', label: 'ALBUM · BANDCAMP' },
    youtube: { icon: 'fa-brands fa-youtube', label: 'PLAYLIST · YOUTUBE' },
    soundcloud: { icon: 'fa-brands fa-soundcloud', label: 'SET · SOUNDCLOUD' },
    mixcloud: { icon: 'fa-brands fa-mixcloud', label: 'SET · MIXCLOUD' },
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

// I titoli delle tracce di alcune piattaforme (es. Bandcamp) arrivano come
// "Artista - Nome brano": nella vista album si deve vedere solo il nome brano.
const TITLE_SEPARATORS = [' - ', ' – ', ' — ', ' | '];

function cleanTrackTitle(track) {
    const title = String(track.title || '');
    const artist = String(track.artist || '').trim();
    if (!title || !artist) return track;
    if (title.toLowerCase().startsWith(artist.toLowerCase())) {
        const rest = title.slice(artist.length);
        for (const sep of TITLE_SEPARATORS) {
            if (rest.startsWith(sep)) {
                const cleaned = rest.slice(sep.length).trim();
                if (cleaned) return { ...track, title: cleaned };
            }
        }
    }
    return track;
}

// Alle tracce di una raccolta alleghiamo il contesto album: il player
// desktop mostra "Apri album" quando il brano corrente ne fa parte.
function cleanTracks(tracks, album = null) {
    return (tracks || []).map(t => {
        const cleaned = cleanTrackTitle(t);
        if (!album || !album.url) return cleaned;
        return {
            ...cleaned,
            album_url: album.url,
            album_title: album.title || '',
            album_thumbnail: album.thumbnail || '',
            album_source: album.source || '',
        };
    });
}

function albumMeta(url, data, fallbackSource) {
    return {
        url,
        title: data.album_title || '',
        thumbnail: data.thumbnail || '',
        source: data.platform || fallbackSource || '',
    };
}

// Riga traccia album: numero, titolo, durata (l'artista è già nell'header).
function createAlbumTrackRow(track, index) {
    const row = document.createElement('div');
    row.className = 'track-row album-track-row';
    if (track.id) row.dataset.trackId = track.id;

    const hasDuration = typeof track.duration === 'number' && isFinite(track.duration) && track.duration > 0;
    const durationLabel = hasDuration ? formatTime(track.duration) : '';

    row.innerHTML = `
        <div class="album-track-num">${index + 1}</div>
        <div class="album-track-main">
            <div class="album-track-title truncate">${escapeHtml(track.title)}</div>
        </div>
        <div class="album-track-duration">${durationLabel}</div>
        <button class="album-track-play" title="Riproduci"><i class="fa-solid fa-play"></i></button>
    `;

    row.addEventListener('click', (e) => {
        if (e.target.closest('.album-track-play')) return;
        playTrackImmediately(track);
    });
    row.querySelector('.album-track-play').addEventListener('click', () => playTrackImmediately(track));

    return row;
}

// I crediti Bandcamp sono testo libero "Etichetta: valore" → coppie etichetta/valore.
function parseCredits(text) {
    return String(text || '')
        .split(/\r?\n/)
        .map(line => line.trim())
        .filter(Boolean)
        .map(line => {
            const idx = line.indexOf(':');
            if (idx > 0 && idx < 40) {
                return { label: line.slice(0, idx).trim(), value: line.slice(idx + 1).trim() };
            }
            return { label: '', value: line };
        });
}

function renderCredits(container, creditsText) {
    if (!container) return;
    const pairs = parseCredits(creditsText);
    if (pairs.length === 0) {
        container.innerHTML = '<div class="credit-row"><span class="credit-value">Nessun credito specificato.</span></div>';
        return;
    }
    container.innerHTML = pairs.map(p => p.label
        ? `<div class="credit-row"><span class="credit-label">${escapeHtml(p.label)}</span><span class="credit-value">${escapeHtml(p.value)}</span></div>`
        : `<div class="credit-row"><span class="credit-value">${escapeHtml(p.value)}</span></div>`
    ).join('');
}

let backButtonBound = false;

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
    const title = document.getElementById('album-view-title');
    const artist = document.getElementById('album-view-artist');
    const countText = document.getElementById('album-view-count');
    const durationText = document.getElementById('album-view-duration');
    const dateText = document.getElementById('album-view-date');
    const dateSep = document.getElementById('album-view-date-sep');
    const list = document.getElementById('album-view-tracks-list');
    const infoBox = document.getElementById('album-info-box');
    const notesBlock = document.getElementById('album-notes-block');
    const creditsBlock = document.getElementById('album-credits-block');
    const description = document.getElementById('album-view-description');
    const credits = document.getElementById('album-view-credits');
    const badgeEl = document.getElementById('album-view-badge');
    const readMoreBtn = document.getElementById('album-read-more');

    if (badgeEl) {
        badgeEl.className = `album-source-label album-badge-${source}`;
        badgeEl.innerHTML = `<i class="${badge.icon}"></i> ${badge.label}`;
    }
    if (cover) cover.src = collection.thumbnail || PLACEHOLDER_COVER;
    if (title) title.innerText = collection.title || 'Caricamento raccolta...';
    if (artist) artist.innerText = collection.artist || 'Caricamento artista...';
    if (countText) countText.innerText = 'Caricamento tracce...';
    if (durationText) durationText.innerText = '-- min';
    if (dateText && dateSep) { dateText.classList.add('hidden'); dateSep.classList.add('hidden'); }
    if (list) list.innerHTML = '<div class="loader-spinner"><div class="double-bounce1"></div><div class="double-bounce2"></div></div>';

    // Link "← Risultati"
    const backBtn = document.getElementById('album-back-btn');
    if (backBtn && !backButtonBound) {
        backBtn.addEventListener('click', () => switchTab('search'));
        backButtonBound = true;
    }

    try {
        const data = await fetchCollection(url);

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        const tracks = cleanTracks(data.tracks, albumMeta(url, data, source));
        if (title) title.innerText = data.album_title || collection.title;
        // Il server mappa "Artista Sconosciuto" quando non ricava l'artista:
        // in quel caso manteniamo l'artista del risultato di ricerca (bug fix).
        const resolvedArtist = (data.artist && data.artist !== 'Artista Sconosciuto')
            ? data.artist
            : (collection.artist || data.artist || 'Artista Sconosciuto');
        if (artist) artist.innerText = resolvedArtist;
        if (data.thumbnail && cover) cover.src = data.thumbnail;
        if (countText) countText.innerText = `${tracks.length} ${tracks.length === 1 ? 'traccia' : 'tracce'}`;
        if (durationText) durationText.innerText = calculateTotalDuration(tracks);

        if (data.release_date && dateText && dateSep) {
            dateText.innerText = data.release_date;
            dateText.classList.remove('hidden');
            dateSep.classList.remove('hidden');
        }

        if (list) {
            list.innerHTML = '';
            tracks.forEach((t, idx) => {
                list.appendChild(createAlbumTrackRow(t, idx));
            });
        }

        // Info & crediti
        const hasCredits = !!(data.credits && data.credits.trim());
        renderCredits(credits, data.credits);
        if (creditsBlock) creditsBlock.classList.toggle('hidden', !hasCredits);

        const notes = (data.description || '').trim();
        if (notesBlock) notesBlock.classList.toggle('hidden', !notes);
        if (description) {
            description.innerText = notes;
            description.classList.remove('expanded', 'clamped');
            if (readMoreBtn) {
                readMoreBtn.classList.add('hidden');
                if (notes.length > 280) {
                    description.classList.add('clamped');
                    readMoreBtn.classList.remove('hidden');
                    readMoreBtn.innerText = 'Leggi tutto';
                    readMoreBtn.onclick = () => {
                        const expanded = description.classList.toggle('expanded');
                        description.classList.toggle('clamped', !expanded);
                        readMoreBtn.innerText = expanded ? 'Mostra meno' : 'Leggi tutto';
                    };
                }
            }
        }

        if (infoBox && (notes || hasCredits)) {
            infoBox.classList.remove('hidden');
        } else if (infoBox) {
            infoBox.classList.add('hidden');
        }

        const btnPlayAll = document.getElementById('btn-album-play-all');
        if (btnPlayAll) {
            btnPlayAll.onclick = () => {
                if (tracks.length > 0) addPlaylistTracksToQueue(tracks, true);
            };
        }

        const btnAddPlaylist = document.getElementById('btn-album-add-playlist');
        if (btnAddPlaylist) {
            btnAddPlaylist.onclick = () => {
                if (tracks.length === 0) {
                    showToast('Nessuna traccia da aggiungere.', 'error');
                    return;
                }
                openAddTracksToPlaylistModal(tracks);
            };
        }

        const btnExtSource = document.getElementById('btn-album-external-source');
        if (btnExtSource) {
            btnExtSource.href = url;
            const platformLabel = PLATFORM_LABELS[data.platform] || 'piattaforma';
            btnExtSource.innerHTML = `<i class="fa-solid fa-arrow-up-right-from-square"></i> Apri su ${platformLabel}`;
            btnExtSource.classList.remove('hidden');
        }

        // Esplora catalogo (Bandcamp: artista + rileva etichetta dalla release).
        const btnCatalog = document.getElementById('btn-album-catalog');
        if (btnCatalog) {
            if (data.platform === 'bandcamp') {
                btnCatalog.classList.remove('hidden');
                btnCatalog.onclick = async () => {
                    const { openCatalogView } = await import('./catalog.js');
                    openCatalogView({ url, platform: data.platform, name: data.artist });
                };
            } else {
                btnCatalog.classList.add('hidden');
            }
        }

    } catch (err) {
        console.error('Failed to load collection view', err);
        showToast('Errore nel caricamento della raccolta', 'error');
    }
}

export async function loadAndAddAlbumToQueue(collection, playImmediately = false) {
    const url = collectionUrl(collection);
    if (!url) {
        showToast('URL della raccolta non trovato.', 'error');
        return;
    }

    showToast('Caricamento della raccolta...');
    try {
        const data = await fetchCollection(url);
        const tracks = cleanTracks(data.tracks, albumMeta(url, data));
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
