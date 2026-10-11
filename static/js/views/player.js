// Desktop Now Playing / Player View: fonte, album, suggeriti.
import { state } from '../core/state.js';
import { showToast, escapeHtml, formatTime, PLACEHOLDER_COVER } from '../core/utils.js';
import { togglePlayPause, prevTrack, nextTrack, playTrackImmediately, addToQueue } from '../player/player.js';
import { openCollectionDetailView } from './album.js';

const SOURCE_LABELS = {
    youtube: 'YouTube',
    soundcloud: 'SoundCloud',
    bandcamp: 'Bandcamp',
    mixcloud: 'Mixcloud',
    radio: 'Web Radio',
    local: 'Locale',
};

const SOURCE_ICONS = {
    youtube: 'fa-brands fa-youtube',
    soundcloud: 'fa-brands fa-soundcloud',
    bandcamp: 'fa-brands fa-bandcamp',
    mixcloud: 'fa-brands fa-mixcloud',
    radio: 'fa-solid fa-radio',
    local: 'fa-solid fa-hard-drive',
};

const FALLBACK_COVER = PLACEHOLDER_COVER;
let lastSuggestionKey = null;

export function initPlayerView() {
    const playBtn = document.getElementById('np-play');
    if (playBtn && !playBtn.dataset.bound) {
        playBtn.dataset.bound = '1';
        playBtn.addEventListener('click', togglePlayPause);
    }
    const prevBtn = document.getElementById('np-prev');
    if (prevBtn && !prevBtn.dataset.bound) {
        prevBtn.dataset.bound = '1';
        prevBtn.addEventListener('click', prevTrack);
    }
    const nextBtn = document.getElementById('np-next');
    if (nextBtn && !nextBtn.dataset.bound) {
        nextBtn.dataset.bound = '1';
        nextBtn.addEventListener('click', nextTrack);
    }
    // Hook globale chiamato dal player ad ogni cambio brano/stato.
    window.updateNowPlayingView = renderNowPlaying;
}

export function renderNowPlaying() {
    const track = state.currentTrack;
    const cover = document.getElementById('np-cover');
    const title = document.getElementById('np-title');
    const artist = document.getElementById('np-artist');
    const sourceEl = document.getElementById('np-source');
    const playIcon = document.querySelector('#np-play i');
    const albumLink = document.getElementById('np-album-link');
    const extLink = document.getElementById('np-ext-link');

    if (playIcon) playIcon.className = state.isPlaying ? 'fa-solid fa-pause' : 'fa-solid fa-play';

    if (!track) {
        if (title) title.innerText = 'Nessun brano in riproduzione';
        if (artist) artist.innerText = 'Avvia la riproduzione o cerca un brano';
        if (sourceEl) sourceEl.innerHTML = '';
        if (cover) cover.src = FALLBACK_COVER;
        if (albumLink) albumLink.classList.add('hidden');
        if (extLink) extLink.classList.add('hidden');
        renderSuggestions([]);
        lastSuggestionKey = null;
        return;
    }

    const platform = track.source || '';
    if (title) title.innerText = track.title || 'Senza Titolo';
    if (artist) artist.innerText = track.artist || 'Artista Sconosciuto';
    if (cover) cover.src = track.thumbnail || FALLBACK_COVER;
    if (sourceEl) {
        sourceEl.innerHTML = `<i class="${SOURCE_ICONS[platform] || 'fa-solid fa-music'}"></i> ${escapeHtml(SOURCE_LABELS[platform] || platform.toUpperCase())}`;
    }

    // "Apri album" se il brano fa parte di una raccolta.
    if (albumLink) {
        if (track.album_url) {
            albumLink.classList.remove('hidden');
            albumLink.href = track.album_url;
            albumLink.onclick = (e) => {
                e.preventDefault();
                openCollectionDetailView({
                    url: track.album_url,
                    source: track.album_source || platform,
                    title: track.album_title || '',
                    thumbnail: track.album_thumbnail || '',
                });
            };
        } else {
            albumLink.classList.add('hidden');
        }
    }

    if (extLink) {
        if (track.url) {
            extLink.classList.remove('hidden');
            extLink.href = track.url;
        } else {
            extLink.classList.add('hidden');
        }
    }

    loadSuggestions(track);
}

async function loadSuggestions(track) {
    const key = track.id || track.url;
    if (key === lastSuggestionKey) return;
    lastSuggestionKey = key;

    const list = document.getElementById('np-suggestions-list');
    if (!list) return;
    list.innerHTML = '<div class="loader-spinner"><div class="double-bounce1"></div><div class="double-bounce2"></div></div>';

    try {
        const qs = new URLSearchParams({
            url: track.url || '',
            source: track.source || '',
            title: track.title || '',
            artist: track.artist || '',
            limit: '10',
        });
        const res = await fetch(`/api/related?${qs.toString()}`);
        const data = await res.json();
        renderSuggestions(data.items || []);
    } catch (err) {
        console.error('Failed to load suggestions', err);
        renderSuggestions([]);
    }
}

function renderSuggestions(items) {
    const list = document.getElementById('np-suggestions-list');
    if (!list) return;
    if (!items.length) {
        list.innerHTML = '<div class="empty-state-text" style="padding: 14px;">Nessun suggerimento disponibile.</div>';
        return;
    }
    list.innerHTML = '';
    items.forEach(track => {
        const row = document.createElement('div');
        row.className = 'np-sugg-row';
        const platform = track.source || '';
        row.innerHTML = `
            <img class="np-sugg-thumb" src="${escapeHtml(track.thumbnail || FALLBACK_COVER)}" alt="" onerror="this.onerror=null;this.src='${FALLBACK_COVER}'">
            <div class="np-sugg-info">
                <div class="np-sugg-name truncate">${escapeHtml(track.title || 'Senza Titolo')}</div>
                <div class="np-sugg-sub truncate">
                    <i class="${SOURCE_ICONS[platform] || 'fa-solid fa-music'}"></i>
                    ${escapeHtml(track.artist || '')}${track.duration ? ' · ' + formatTime(track.duration) : ''}
                </div>
            </div>
            <button class="np-sugg-add" title="Aggiungi alla coda"><i class="fa-solid fa-plus"></i></button>
        `;
        row.addEventListener('click', (e) => {
            if (e.target.closest('.np-sugg-add')) return;
            playTrackImmediately(track);
        });
        row.querySelector('.np-sugg-add').addEventListener('click', (e) => {
            e.stopPropagation();
            addToQueue(track);
            showToast('Aggiunto alla coda: ' + (track.title || ''), 'success');
        });
        list.appendChild(row);
    });
}
