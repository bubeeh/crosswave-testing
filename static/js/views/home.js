// Home Dashboard View Module for CrossWave Hybrid
import { state } from '../core/state.js';
import { showToast, escapeHtml, PLACEHOLDER_COVER, youtubeVideoId } from '../core/utils.js';
import { navigate } from '../core/router.js';
import { executeSearch } from './search.js';
import { playTrackImmediately } from '../player/player.js';

export async function loadHomeDashboard() {
    initHomeSearch();
    bindNavLinkCards();
    updateHomeBadges();
    renderHomeResume();
    initForYouControls();
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

const FALLBACK_COVER = PLACEHOLDER_COVER;

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
        <img class="resume-cover" src="${escapeHtml(track.thumbnail || FALLBACK_COVER)}" alt="" onerror="this.onerror=null;this.src='${FALLBACK_COVER}'">
        <div class="resume-info">
            <div class="resume-title truncate">${escapeHtml(track.title || 'Senza Titolo')}</div>
            <div class="resume-artist truncate">${escapeHtml(track.artist || 'Artista Sconosciuto')}</div>
            <div class="resume-source" style="color: ${SOURCE_COLOR_VARS[track.source] || 'var(--text-muted)'};">
                ${escapeHtml(SOURCE_LABELS[track.source] || 'Web')}
            </div>
        </div>
        <button class="resume-play" title="Riprendi"><i class="fa-solid fa-play"></i></button>
    `;

    card.onclick = () => playTrackImmediately(track);
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

// --- "Per te": raccomandazioni per ARTISTI (close/scene/mixed) ---
const REC_MODE_KEY = 'cw_rec_mode';
const FALLBACK_ART = PLACEHOLDER_COVER;

function getRecMode() {
    const m = localStorage.getItem(REC_MODE_KEY);
    return (m === 'close' || m === 'scene' || m === 'mixed') ? m : 'mixed';
}

function setRecMode(mode) {
    localStorage.setItem(REC_MODE_KEY, mode);
    document.querySelectorAll('.for-you-mode').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-mode') === mode);
    });
}

// Clicca una card: se c'è un elemento riproducibile suona, altrimenti cerca l'artista.
function openForYouArtist(item) {
    const playable = item.playable;
    if (playable && playable.url) {
        const platform = playable.platform;
        const native = platform === 'youtube' ? youtubeVideoId(playable.url) : '';
        playTrackImmediately({
            id: native ? `yt_${native}` : playable.url,
            title: item.name,
            artist: item.name,
            source: platform,
            url: playable.url,
            thumbnail: '',
            duration: 0,
            type: 'track',
        });
        return;
    }
    const mainSearchInput = document.getElementById('search-input');
    if (mainSearchInput) mainSearchInput.value = item.name;
    navigate('search');
    executeSearch(item.name);
}

function renderForYouCard(item) {
    const mode = getRecMode();
    const reason = (item.reasons && item.reasons[0] && item.reasons[0].text) || '';
    const sourceLabels = (item.sources || []).map(s => s.source === 'lastfm' ? 'Last.fm' : s.source)
        .filter((v, i, a) => a.indexOf(v) === i).join(' · ');

    const card = document.createElement('div');
    card.className = 'for-you-card glassmorphic-card';
    card.innerHTML = `
        <div class="for-you-cover">
            <img src="${FALLBACK_ART}" alt="${escapeHtml(item.name || '')}" onerror="this.onerror=null;this.src='${FALLBACK_ART}'">
            <span class="for-you-source"><i class="fa-solid fa-user-music"></i></span>
        </div>
        <div class="for-you-info">
            <div class="for-you-title truncate">${escapeHtml(item.name || 'Artista')}</div>
            ${reason ? `<div class="for-you-tags truncate" title="${escapeHtml(reason)}">${escapeHtml(reason)}</div>` : ''}
            ${sourceLabels ? `<div class="for-you-artist truncate">${escapeHtml(sourceLabels)}</div>` : ''}
        </div>
        <div class="for-you-actions">
            <button class="for-you-action" data-action="like" title="Mi piace"><i class="fa-solid fa-thumbs-up"></i></button>
            <button class="for-you-action" data-action="dislike" title="Non mi piace"><i class="fa-solid fa-thumbs-down"></i></button>
            <button class="for-you-action" data-action="hide" title="Nascondi"><i class="fa-solid fa-eye-slash"></i></button>
        </div>
    `;
    card.classList.add(`mode-${mode}`);

    card.addEventListener('click', (e) => {
        if (e.target.closest('.for-you-action')) return;
        openForYouArtist(item);
    });
    card.querySelectorAll('.for-you-action').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            sendFeedback(item.name, btn.getAttribute('data-action'), card);
        });
    });
    return card;
}

async function sendFeedback(artist, action, cardEl) {
    try {
        await fetch('/api/recommendations/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ artist, action }),
        });
        if (cardEl) cardEl.remove();
        const labels = { like: 'Aggiunto ai preferiti', dislike: 'Segnalato', hide: 'Nascosto' };
        showToast(labels[action] || 'Feedback salvato');
    } catch (err) {
        showToast('Errore nel salvataggio del feedback', 'error');
    }
}

export async function loadForYou() {
    const grid = document.getElementById('home-for-you-list');
    if (!grid) return;
    const forgetBtn = document.getElementById('home-for-you-forget');
    const seedsBtn = document.getElementById('for-you-seeds');
    const mode = getRecMode();
    setRecMode(mode);

    try {
        const res = await fetch(`/api/recommendations?mode=${mode}&explore=0.3&limit=12`);
        const data = await res.json();
        const items = data.items || [];

        if (items.length === 0) {
            grid.innerHTML = '<div class="empty-state-text" style="grid-column: 1/-1; padding: 14px;">Ascolta qualche brano o imposta dei seed: qui compariranno gli artisti consigliati.</div>';
            if (forgetBtn) forgetBtn.classList.add('hidden');
            if (seedsBtn) seedsBtn.classList.remove('hidden');
            return;
        }

        if (forgetBtn) {
            forgetBtn.classList.remove('hidden');
            forgetBtn.onclick = clearForYou;
        }
        if (seedsBtn) {
            seedsBtn.classList.remove('hidden');
            seedsBtn.onclick = openSeedsPrompt;
        }

        grid.innerHTML = '';
        items.forEach(item => grid.appendChild(renderForYouCard(item)));
    } catch (err) {
        console.error('Failed to load recommendations', err);
        grid.innerHTML = '';
    }
}

export function initForYouControls() {
    const modesBox = document.getElementById('for-you-modes');
    if (modesBox && !modesBox.dataset.bound) {
        modesBox.dataset.bound = 'true';
        modesBox.querySelectorAll('.for-you-mode').forEach(btn => {
            btn.addEventListener('click', () => {
                setRecMode(btn.getAttribute('data-mode'));
                loadForYou();
            });
        });
    }
    setRecMode(getRecMode());
}

function openSeedsPrompt() {
    const raw = window.prompt('Artisti di partenza (separati da virgola):');
    if (!raw) return;
    const artists = raw.split(',').map(s => s.trim()).filter(Boolean);
    if (artists.length === 0) return;
    fetch('/api/recommendations/seeds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artists }),
    }).then(() => {
        showToast('Seed salvati');
        loadForYou();
    }).catch(() => showToast('Errore nel salvataggio dei seed', 'error'));
}

export async function clearForYou() {
    if (!confirm('Azzerare la cronologia di ascolto, i feedback e i suggerimenti "Per te"?')) return;
    try {
        await fetch('/api/recommendations/forget', { method: 'POST' });
    } catch (e) {
        // ignora: la UI si aggiorna comunque
    }
    showToast('Suggerimenti azzerati');
    loadForYou();
}
