// Home Dashboard View Module for CrossWave Hybrid
import { state } from '../core/state.js';
import { showToast, escapeHtml } from '../core/utils.js';
import { navigate } from '../core/router.js';
import { executeSearch } from './search.js';
import { playTrackImmediately } from '../player/player.js';

export async function loadHomeDashboard() {
    initHomeSearch();
    bindNavLinkCards();
    updateHomeBadges();
    renderHomeResume();
    loadForYou();
}

const SOURCE_LABELS = {
    youtube: 'YouTube',
    soundcloud: 'SoundCloud',
    bandcamp: 'Bandcamp',
    mixcloud: 'Mixcloud',
    radio: 'Web Radio',
};

const SOURCE_COLOR_VARS = {
    youtube: 'var(--yt-color)',
    soundcloud: 'var(--sc-color)',
    bandcamp: 'var(--bc-color)',
    mixcloud: 'var(--mc-color)',
    radio: 'var(--accent-cyan)',
};

const FALLBACK_COVER = 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=150';

// --- "Riprendi": ultimo ascolto dalla cronologia ---
function renderHomeResume() {
    const section = document.getElementById('home-resume-section');
    const card = document.getElementById('home-resume-card');
    if (!section || !card) return;

    const track = (state.history && state.history[0]) || null;
    if (!track) {
        section.classList.add('hidden');
        card.innerHTML = '';
        return;
    }

    section.classList.remove('hidden');
    card.innerHTML = `
        <img class="resume-cover" src="${escapeHtml(track.thumbnail || FALLBACK_COVER)}" alt="" onerror="this.src='${FALLBACK_COVER}'">
        <div class="resume-info">
            <div class="resume-title truncate">${escapeHtml(track.title || 'Senza Titolo')}</div>
            <div class="resume-artist truncate">${escapeHtml(track.artist || 'Artista Sconosciuto')}</div>
            <div class="resume-source" style="color: ${SOURCE_COLOR_VARS[track.source] || 'var(--text-muted)'};">
                ${escapeHtml(SOURCE_LABELS[track.source] || 'Web')}
            </div>
        </div>
        <button class="resume-play" title="Riprendi"><i class="fa-solid fa-play"></i></button>
    `;

    card.addEventListener('click', () => playTrackImmediately(track));
}

// --- Top Home Search Bar Handler ---
function initHomeSearch() {
    const searchInput = document.getElementById('home-search-input');
    const searchBtn = document.getElementById('home-search-btn');

    if (!searchInput || searchInput.dataset.boundHomeSearch) return;
    searchInput.dataset.boundHomeSearch = 'true';

    const triggerSearch = () => {
        const query = searchInput.value.trim();
        if (!query) {
            showToast('Inserisci un termine di ricerca', 'warning');
            return;
        }

        // Copy query to main search tab input
        const mainSearchInput = document.getElementById('search-input');
        if (mainSearchInput) mainSearchInput.value = query;

        // Navigate to search tab and execute search
        navigate('search');
        executeSearch(query);
    };

    if (searchBtn) {
        searchBtn.addEventListener('click', triggerSearch);
    }

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            triggerSearch();
        }
    });

    // Platform pill filter toggles on home search
    document.querySelectorAll('.home-search-filters .filter-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            pill.classList.toggle('active');
            const source = pill.getAttribute('data-source');
            const targetChkMap = {
                youtube: 'chk-yt',
                soundcloud: 'chk-sc',
                bandcamp: 'chk-bc',
                mixcloud: 'chk-mc'
            };
            const targetChk = document.getElementById(targetChkMap[source]);
            const isSelected = pill.classList.contains('active');
            if (targetChk) {
                targetChk.checked = isSelected;
            }
            const searchTabPill = document.querySelector(`.search-filters-row .filter-pill[data-source="${source}"]`);
            if (searchTabPill) {
                searchTabPill.classList.toggle('checked', isSelected);
            }
        });
    });
}

// --- Bind Navigation Link Cards ---
function bindNavLinkCards() {
    document.querySelectorAll('.nav-link-card').forEach(card => {
        if (card.dataset.boundLink) return;
        card.dataset.boundLink = 'true';

        card.addEventListener('click', () => {
            const targetTab = card.getAttribute('data-target');
            if (targetTab) {
                navigate(targetTab);
            }
        });
    });
}

// --- Update Badge Counts on Cards ---
async function updateHomeBadges() {
    const playlistPill = document.getElementById('home-playlist-count-pill');
    if (playlistPill) {
        const count = Object.keys(state.playlists || {}).length;
        playlistPill.innerText = `${count} raccolte`;
    }
}

// --- "Per te": raccomandazioni precomputate dal backend ---
function youtubeVideoId(url) {
    const m = String(url || '').match(/[?&]v=([\w-]+)/);
    return m ? m[1] : '';
}

function recToTrack(item) {
    const platform = item.platform;
    const native = platform === 'youtube' ? youtubeVideoId(item.source_url) : '';
    return {
        id: (platform === 'youtube' && native) ? `yt_${native}` : (item.media_id || item.source_url),
        canonical_id: item.media_id,
        title: item.title || 'Senza Titolo',
        artist: item.uploader || 'Artista Sconosciuto',
        source: platform,
        url: item.source_url,
        thumbnail: item.thumbnail || '',
        duration: item.duration || 0,
        type: 'track',
    };
}

function renderForYouCard(item) {
    const platform = item.platform || '';
    const tags = (item.reason_tags || [])
        .filter(t => typeof t === 'string' && !t.startsWith('artist:') && t !== platform)
        .slice(0, 2);

    let sourceIcon = 'fa-solid fa-music';
    if (platform === 'youtube') sourceIcon = 'fa-brands fa-youtube';
    if (platform === 'soundcloud') sourceIcon = 'fa-brands fa-soundcloud';
    if (platform === 'bandcamp') sourceIcon = 'fa-brands fa-bandcamp';
    if (platform === 'mixcloud') sourceIcon = 'fa-brands fa-mixcloud';

    const card = document.createElement('div');
    card.className = 'for-you-card glassmorphic-card';
    card.innerHTML = `
        <div class="for-you-cover">
            <img src="${escapeHtml(item.thumbnail || 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=300')}"
                 alt="${escapeHtml(item.title || '')}"
                 onerror="this.src='https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=300'">
            <span class="for-you-source"><i class="${sourceIcon}"></i></span>
        </div>
        <div class="for-you-info">
            <div class="for-you-title truncate">${escapeHtml(item.title || 'Senza Titolo')}</div>
            <div class="for-you-artist truncate">${escapeHtml(item.uploader || 'Artista Sconosciuto')}</div>
            ${tags.length ? `<div class="for-you-tags truncate">${tags.map(t => escapeHtml(t)).join(' · ')}</div>` : ''}
        </div>
    `;
    card.addEventListener('click', () => playTrackImmediately(recToTrack(item)));
    return card;
}

export async function loadForYou() {
    const grid = document.getElementById('home-for-you-list');
    if (!grid) return;
    try {
        const res = await fetch('/api/recommendations?limit=12');
        const data = await res.json();
        const items = data.items || [];

        if (items.length === 0) {
            grid.innerHTML = '<div class="empty-state-text" style="grid-column: 1/-1; padding: 14px;">Ascolta qualche brano: qui compariranno i suggerimenti personalizzati.</div>';
            return;
        }

        grid.innerHTML = '';
        items.forEach(item => grid.appendChild(renderForYouCard(item)));
    } catch (err) {
        console.error('Failed to load recommendations', err);
        grid.innerHTML = '';
    }
}

export async function clearForYou() {
    if (!confirm('Azzerare la cronologia di ascolto e i suggerimenti "Per te"?')) return;
    try {
        await fetch('/api/recommendations/forget', { method: 'POST' });
    } catch (e) {
        // ignora: la UI si aggiorna comunque
    }
    showToast('Suggerimenti azzerati');
    loadForYou();
}
