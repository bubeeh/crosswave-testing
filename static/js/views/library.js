import { state } from '../core/state.js';
import { showToast, formatTime, calculateTotalDuration, escapeHtml } from '../core/utils.js';
import { switchTab } from '../core/router.js';
import { playTrackImmediately, renderQueue, removeTrackFromQueue, clearQueue, addToQueue, addPlaylistTracksToQueue } from '../player/player.js';
import { createResultRow } from './search.js';
import { loadPlaylistsCard, refreshHomeFavoritesWidget } from './home.js';

// --- History Management ---
export function addToHistory(track) {
    if (state.history.length > 0 && state.history[0].id === track.id) return;

    state.history.unshift(track);
    if (state.history.length > 100) state.history.pop();

    saveHistoryToStorage();
    renderHistory();
    renderRecentTracksList();
}
window.addToHistory = addToHistory;

export function renderHistory() {
    const list = document.getElementById('history-tracks-list');
    if (!list) return;
    list.innerHTML = '';

    if (state.history.length === 0) {
        list.innerHTML = '<div class="empty-state-text" style="padding: 20px;">Nessuna canzone riprodotta di recente.</div>';
        return;
    }

    state.history.forEach((track, index) => {
        const row = document.createElement('div');
        row.className = 'track-row';

        let sourceIcon = 'fa-solid fa-music';
        if (track.source === 'youtube') sourceIcon = 'fa-brands fa-youtube';
        if (track.source === 'soundcloud') sourceIcon = 'fa-brands fa-soundcloud';
        if (track.source === 'bandcamp') sourceIcon = 'fa-brands fa-bandcamp';
        if (track.source === 'mixcloud') sourceIcon = 'fa-brands fa-mixcloud';

        row.innerHTML = `
            <div class="track-row-index">${index + 1}</div>
            <img class="track-row-thumbnail" src="${track.thumbnail || 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=80'}" alt="Thumb">
            <div class="track-row-details">
                <div class="track-row-title truncate">${escapeHtml(track.title)}</div>
                <div class="track-row-artist truncate">${escapeHtml(track.artist)}</div>
            </div>
            <div class="track-row-source-badge ${track.source}">
                <i class="${sourceIcon}"></i>
            </div>
            <div class="track-row-duration">${formatTime(track.duration)}</div>
            <div class="track-row-actions">
                <button class="track-row-action-btn add-q" title="Aggiungi alla Coda"><i class="fa-solid fa-plus"></i></button>
            </div>
        `;

        row.addEventListener('click', (e) => {
            if (e.target.closest('.track-row-action-btn')) return;
            playTrackImmediately(track);
        });

        row.querySelector('.add-q').addEventListener('click', () => {
            addToQueue(track);
            showToast('Aggiunto alla coda: ' + track.title, 'success');
        });

        list.appendChild(row);
    });
}

export function renderRecentTracksList() {
    const list = document.getElementById('recent-tracks-list');
    if (!list) return;
    list.innerHTML = '';

    if (state.history.length === 0) {
        list.innerHTML = '<div class="empty-state-text">Nessun brano riprodotto di recente.</div>';
        return;
    }

    state.history.slice(0, 5).forEach(track => {
        const item = document.createElement('div');
        item.className = 'playlist-item';
        item.style.padding = '8px 10px';

        let sourceIcon = 'fa-solid fa-music';
        if (track.source === 'youtube') sourceIcon = 'fa-brands fa-youtube';
        if (track.source === 'soundcloud') sourceIcon = 'fa-brands fa-soundcloud';
        if (track.source === 'bandcamp') sourceIcon = 'fa-brands fa-bandcamp';
        if (track.source === 'mixcloud') sourceIcon = 'fa-brands fa-mixcloud';

        item.innerHTML = `
            <div class="playlist-item-name" style="gap: 12px; flex: 1;">
                <i class="${sourceIcon}" style="font-size: 14px;"></i>
                <div style="text-align: left; overflow: hidden; width: 85%;">
                    <div class="truncate" style="font-size: 12.5px; font-weight:600; color:var(--text-primary);">${escapeHtml(track.title)}</div>
                    <div class="truncate" style="font-size: 10.5px; color:var(--text-secondary);">${escapeHtml(track.artist)}</div>
                </div>
            </div>
            <button class="track-row-action-btn" style="width:24px; height:24px;" title="Riproduci"><i class="fa-solid fa-play"></i></button>
        `;

        item.querySelector('button').addEventListener('click', (e) => {
            e.stopPropagation();
            playTrackImmediately(track);
        });

        item.addEventListener('click', () => {
            playTrackImmediately(track);
        });

        list.appendChild(item);
    });
}

export function clearHistory() {
    state.history = [];
    saveHistoryToStorage();
    renderHistory();
    renderRecentTracksList();
    showToast('Cronologia cancellata');
}

// --- Playlists Management ---
export function createNewPlaylist() {
    const input = document.getElementById('new-playlist-name');
    if (!input) return;
    const name = input.value.trim();

    if (!name) return;

    if (state.playlists[name]) {
        showToast('Esiste già una playlist con questo nome!', 'error');
        return;
    }

    state.playlists[name] = [];
    savePlaylistsToStorage();
    renderPlaylists();

    const modal = document.getElementById('create-playlist-modal');
    if (modal) modal.classList.add('hidden');
    showToast(`Playlist "${name}" creata con successo!`, 'success');
}

export function renderPlaylists() {
    const mainGrid = document.getElementById('main-playlists-grid');
    if (mainGrid) {
        mainGrid.innerHTML = '';
        const playlistNames = Object.keys(state.playlists);
        if (playlistNames.length === 0) {
            mainGrid.innerHTML = `
                <div class="empty-card-placeholder p-5 w-100">
                    <i class="fa-solid fa-compact-disc placeholder-icon" style="font-size: 2.5rem;"></i>
                    <p style="font-size: 1.1rem; font-weight: 700; margin-top: 10px;">Nessuna playlist creata</p>
                    <p class="text-secondary" style="font-size: 0.88rem;">Crea la tua prima playlist personale per raccogliere i tuoi brani preferiti.</p>
                </div>
            `;
        } else {
            playlistNames.forEach(name => {
                const tracks = state.playlists[name] || [];
                const card = document.createElement('div');
                card.className = 'glassmorphic-card p-4 rounded-4 d-flex align-items-center justify-content-between gap-3';
                card.style.cssText = 'background: rgba(18, 18, 26, 0.65); border: 1px solid rgba(255,255,255,0.08); cursor: pointer; transition: all 0.2s ease;';

                const coverArt = tracks.length > 0 && tracks[0].thumbnail 
                    ? tracks[0].thumbnail 
                    : 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=150';

                card.innerHTML = `
                    <div class="d-flex align-items-center gap-3" style="min-width: 0;">
                        <img src="${coverArt}" alt="${escapeHtml(name)}" style="width: 56px; height: 56px; border-radius: 12px; object-fit: cover; border: 1px solid var(--accent-purple); flex-shrink: 0;">
                        <div style="min-width: 0;">
                            <h3 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 2px;" class="truncate">${escapeHtml(name)}</h3>
                            <span style="font-size: 0.8rem; color: var(--text-secondary);">${tracks.length} brani &bull; ${calculateTotalDuration(tracks)}</span>
                        </div>
                    </div>
                    <div class="d-flex align-items-center gap-2" style="flex-shrink: 0;">
                        <button class="btn btn-cyan btn-sm btn-play-pl" title="Riproduci Playlist" style="padding: 6px 14px; font-size: 0.8rem;">
                            <i class="fa-solid fa-play me-1"></i> Ascolta
                        </button>
                        <button class="btn btn-secondary btn-sm btn-del-pl" title="Elimina Playlist" style="padding: 6px 10px; font-size: 0.8rem;">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </div>
                `;

                card.addEventListener('click', (e) => {
                    if (e.target.closest('button')) return;
                    openPlaylistDetail(name);
                });

                card.querySelector('.btn-play-pl').addEventListener('click', (e) => {
                    e.stopPropagation();
                    openPlaylistDetail(name);
                });

                card.querySelector('.btn-del-pl').addEventListener('click', (e) => {
                    e.stopPropagation();
                    deletePlaylist(name);
                });

                mainGrid.appendChild(card);
            });
        }
    }
}

export function deletePlaylist(name) {
    if (confirm(`Sei sicuro di voler eliminare la playlist "${name}"?`)) {
        delete state.playlists[name];
        savePlaylistsToStorage();
        renderPlaylists();

        const activeDetailTitle = document.getElementById('playlist-detail-title');
        if (activeDetailTitle && activeDetailTitle.innerText === name) {
            switchTab('home');
        }
        showToast(`Playlist "${name}" eliminata`);
    }
}

export function openPlaylistDetail(name) {
    switchTab('playlist-detail');

    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));

    document.querySelectorAll('.playlist-item').forEach(item => {
        const nameSpan = item.querySelector('.playlist-item-name span');
        if (nameSpan && nameSpan.innerText === name) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    const tracks = state.playlists[name] || [];

    const titleEl = document.getElementById('playlist-detail-title');
    const metaEl = document.getElementById('playlist-detail-meta');
    if (titleEl) titleEl.innerText = name;
    if (metaEl) metaEl.innerText = `${tracks.length} brani • ${calculateTotalDuration(tracks)}`;

    const delBtn = document.getElementById('delete-playlist-btn');
    if (delBtn) delBtn.onclick = () => deletePlaylist(name);

    const playAllBtn = document.getElementById('play-all-playlist-btn');
    if (playAllBtn) {
        playAllBtn.onclick = () => {
            if (tracks.length === 0) {
                showToast('Nessun brano in questa playlist.', 'error');
                return;
            }
            addPlaylistTracksToQueue(tracks, true);
        };
    }

    renderPlaylistSongs(name);
}

export function renderPlaylistSongs(playlistName) {
    const container = document.getElementById('playlist-songs-list');
    if (!container) return;
    container.innerHTML = '';

    const tracks = state.playlists[playlistName] || [];
    if (tracks.length === 0) {
        container.innerHTML = '<div class="empty-state-text" style="padding:40px;">Questa playlist è vuota. Cerca canzoni e aggiungile qui!</div>';
        return;
    }

    tracks.forEach((track, index) => {
        const row = document.createElement('div');
        row.className = 'track-row';

        let sourceIcon = 'fa-solid fa-music';
        if (track.source === 'youtube') sourceIcon = 'fa-brands fa-youtube';
        if (track.source === 'soundcloud') sourceIcon = 'fa-brands fa-soundcloud';
        if (track.source === 'bandcamp') sourceIcon = 'fa-brands fa-bandcamp';
        if (track.source === 'mixcloud') sourceIcon = 'fa-brands fa-mixcloud';

        row.innerHTML = `
            <div class="track-row-index">${index + 1}</div>
            <img class="track-row-thumbnail" src="${track.thumbnail || 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=80'}" alt="Thumb">
            <div class="track-row-details">
                <div class="track-row-title truncate">${escapeHtml(track.title)}</div>
                <div class="track-row-artist truncate">${escapeHtml(track.artist)}</div>
            </div>
            <div class="track-row-source-badge ${track.source}">
                <i class="${sourceIcon}"></i>
            </div>
            <div class="track-row-duration">${formatTime(track.duration)}</div>
            <div class="track-row-actions">
                <button class="track-row-action-btn play" title="Riproduci"><i class="fa-solid fa-play"></i></button>
                <button class="track-row-action-btn add-q" title="Aggiungi in coda"><i class="fa-solid fa-plus"></i></button>
                <button class="track-row-action-btn del" title="Rimuovi dalla playlist"><i class="fa-solid fa-trash"></i></button>
            </div>
        `;

        row.addEventListener('click', (e) => {
            if (e.target.closest('.track-row-action-btn')) return;
            playTrackImmediately(track);
        });

        row.querySelector('.play').addEventListener('click', () => {
            playTrackImmediately(track);
        });

        row.querySelector('.add-q').addEventListener('click', () => {
            addToQueue(track);
            showToast('Aggiunto in coda: ' + track.title, 'success');
        });

        row.querySelector('.del').addEventListener('click', () => {
            removeTrackFromPlaylist(playlistName, index);
        });

        container.appendChild(row);
    });
}

export function removeTrackFromPlaylist(playlistName, index) {
    if (state.playlists[playlistName]) {
        state.playlists[playlistName].splice(index, 1);
        savePlaylistsToStorage();
        openPlaylistDetail(playlistName);
        showToast('Brano rimosso dalla playlist');
    }
}

export function openAddToPlaylistModal(track) {
    state.pendingTrackToPlaylist = track;

    const container = document.getElementById('modal-playlists-list');
    if (!container) return;
    container.innerHTML = '';

    const modal = document.getElementById('add-to-playlist-modal');
    if (modal) modal.classList.remove('hidden');

    const playlistNames = Object.keys(state.playlists);
    if (playlistNames.length === 0) {
        container.innerHTML = '<p>Non hai ancora creato nessuna playlist. Crea una playlist nella barra laterale.</p>';
        return;
    }

    playlistNames.forEach(name => {
        const opt = document.createElement('div');
        opt.className = 'modal-playlist-option';
        opt.innerHTML = `<i class="fa-solid fa-music"></i> <span>${escapeHtml(name)}</span>`;

        opt.addEventListener('click', () => {
            addTrackToPlaylist(name);
            if (modal) modal.classList.add('hidden');
        });

        container.appendChild(opt);
    });
}

export function addTrackToPlaylist(playlistName) {
    if (!state.pendingTrackToPlaylist) return;

    const exists = state.playlists[playlistName] && state.playlists[playlistName].some(t => t.id === state.pendingTrackToPlaylist.id);
    if (exists) {
        showToast('Il brano è già presente in questa playlist.', 'error');
        return;
    }

    if (!state.playlists[playlistName]) {
        state.playlists[playlistName] = [];
    }

    state.playlists[playlistName].push(state.pendingTrackToPlaylist);
    savePlaylistsToStorage();
    showToast(`Aggiunto a "${playlistName}"`, 'success');
    state.pendingTrackToPlaylist = null;
}

export function loadPlaylistsFromStorage() {
    const raw = localStorage.getItem('cw_playlists');
    if (raw) {
        try {
            state.playlists = JSON.parse(raw);
        } catch (e) {
            console.error('Failed to parse playlists from storage', e);
            state.playlists = {};
        }
    } else {
        state.playlists = { 'Preferiti': [] };
    }
    renderPlaylists();
}

export function savePlaylistsToStorage() {
    localStorage.setItem('cw_playlists', JSON.stringify(state.playlists));
}

export function loadHistoryFromStorage() {
    const raw = localStorage.getItem('cw_history');
    if (raw) {
        try {
            state.history = JSON.parse(raw);
            renderHistory();
            renderRecentTracksList();
        } catch (e) {
            console.error('Failed to parse history from storage', e);
            state.history = [];
        }
    }
}

export function saveHistoryToStorage() {
    localStorage.setItem('cw_history', JSON.stringify(state.history));
}

// --- Favorites & Watch Later ---
export async function addFavoriteTrack(track) {
    try {
        const res = await fetch('/api/favorites', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(track)
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Aggiunto ai Preferiti ❤️', 'success');
            loadFavorites();
            refreshHomeFavoritesWidget();
        } else {
            showToast(data.error || 'Errore durante il salvataggio', 'error');
        }
    } catch (e) {
        showToast('Errore di connessione al server', 'error');
    }
}

export async function removeFavoriteTrack(trackId) {
    if (!trackId) return;
    try {
        const res = await fetch(`/api/favorites/${encodeURIComponent(trackId)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Rimosso dai preferiti', 'info');
            loadFavorites();
            refreshHomeFavoritesWidget();
        } else {
            showToast(data.error || 'Errore durante la rimozione', 'error');
        }
    } catch (e) {
        showToast('Errore di connessione al server', 'error');
    }
}

export async function loadFavorites() {
    const list = document.getElementById('favorites-tracks-list');
    const countText = document.getElementById('favorites-count-text');
    if (!list) return;

    try {
        const res = await fetch('/api/favorites');
        const data = await res.json();
        const tracks = data.favorites || [];

        if (countText) countText.innerText = `${tracks.length} brani salvati`;
        list.innerHTML = '';

        if (tracks.length === 0) {
            list.innerHTML = '<div class="search-placeholder-state"><i class="fa-solid fa-heart-crack placeholder-icon"></i><p>Nessun brano nei Preferiti. Clicca il cuore ❤️ su un brano per aggiungerlo!</p></div>';
            return;
        }

        tracks.forEach((track, index) => {
            const trackId = track.track_id || track.id;
            const row = createResultRow(track, index, {
                isFavorite: true,
                onRemove: () => removeFavoriteTrack(trackId)
            });
            list.appendChild(row);
        });
    } catch (e) {
        console.error('Failed to load favorites', e);
    }
}

export async function addWatchLaterTrack(track) {
    try {
        const res = await fetch('/api/watch_later', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(track)
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Aggiunto a Guarda Dopo 🕒', 'success');
            loadWatchLater();
            refreshHomeWatchLaterWidget();
        } else {
            showToast(data.error || 'Errore durante il salvataggio', 'error');
        }
    } catch (e) {
        showToast('Errore di connessione al server', 'error');
    }
}

export async function removeWatchLaterTrack(trackId) {
    if (!trackId) return;
    try {
        const res = await fetch(`/api/watch_later/${encodeURIComponent(trackId)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Rimosso da Guarda Dopo', 'info');
            loadWatchLater();
            refreshHomeWatchLaterWidget();
        } else {
            showToast(data.error || 'Errore durante la rimozione', 'error');
        }
    } catch (e) {
        showToast('Errore di connessione al server', 'error');
    }
}

export async function loadWatchLater() {
    const list = document.getElementById('watch-later-tracks-list');
    const countText = document.getElementById('watch-later-count-text');
    if (!list) return;

    try {
        const res = await fetch('/api/watch_later');
        const data = await res.json();
        const tracks = data.watch_later || [];

        if (countText) countText.innerText = `${tracks.length} brani salvati`;
        list.innerHTML = '';

        if (tracks.length === 0) {
            list.innerHTML = '<div class="search-placeholder-state"><i class="fa-solid fa-clock placeholder-icon"></i><p>Nessun brano in Guarda Dopo. Clicca l\'orologio 🕒 su un brano per accodarlo!</p></div>';
            return;
        }

        tracks.forEach((track, index) => {
            const trackId = track.track_id || track.id;
            const row = createResultRow(track, index, {
                isWatchLater: true,
                onRemove: () => removeWatchLaterTrack(trackId)
            });
            list.appendChild(row);
        });
    } catch (e) {
        console.error('Failed to load watch later', e);
    }
}

export function initLibraryView() {
    loadPlaylistsFromStorage();
    loadHistoryFromStorage();

    const clearQBtn = document.getElementById('clear-queue-btn');
    if (clearQBtn) clearQBtn.addEventListener('click', clearQueue);

    const clearHBtn = document.getElementById('clear-history-btn');
    if (clearHBtn) clearHBtn.addEventListener('click', clearHistory);

    const openCreateBtnMain = document.getElementById('open-create-playlist-btn-main');
    if (openCreateBtnMain) {
        openCreateBtnMain.addEventListener('click', () => {
            const input = document.getElementById('new-playlist-name');
            if (input) input.value = '';
            const modal = document.getElementById('create-playlist-modal');
            if (modal) modal.classList.remove('hidden');
        });
    }

    const openCreateBtn = document.getElementById('open-create-playlist-btn');
    if (openCreateBtn) {
        openCreateBtn.addEventListener('click', () => {
            const input = document.getElementById('new-playlist-name');
            if (input) input.value = '';
            const modal = document.getElementById('create-playlist-modal');
            if (modal) modal.classList.remove('hidden');
        });
    }

    const closeCreateBtn = document.getElementById('close-playlist-modal');
    if (closeCreateBtn) {
        closeCreateBtn.addEventListener('click', () => {
            const modal = document.getElementById('create-playlist-modal');
            if (modal) modal.classList.add('hidden');
        });
    }

    const cancelCreateBtn = document.getElementById('cancel-playlist-btn');
    if (cancelCreateBtn) {
        cancelCreateBtn.addEventListener('click', () => {
            const modal = document.getElementById('create-playlist-modal');
            if (modal) modal.classList.add('hidden');
        });
    }

    const saveCreateBtn = document.getElementById('save-playlist-btn');
    if (saveCreateBtn) saveCreateBtn.addEventListener('click', createNewPlaylist);

    const closeAddBtn = document.getElementById('close-add-playlist-modal');
    if (closeAddBtn) {
        closeAddBtn.addEventListener('click', () => {
            const modal = document.getElementById('add-to-playlist-modal');
            if (modal) modal.classList.add('hidden');
        });
    }

    const closeAlbumModalBtn = document.getElementById('close-album-modal');
    if (closeAlbumModalBtn) {
        closeAlbumModalBtn.addEventListener('click', () => {
            const modal = document.getElementById('album-tracks-modal');
            if (modal) modal.classList.add('hidden');
        });
    }
}

if (document.readyState !== 'loading') {
    initLibraryView();
} else {
    document.addEventListener('DOMContentLoaded', () => {
        initLibraryView();
    });
}
