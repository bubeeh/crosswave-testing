// Mix Random & Channels View Module for CrossWave Hybrid
import { state } from '../core/state.js';
import { showToast, formatTime, escapeHtml } from '../core/utils.js';
import { playTrack, addToQueue } from '../player/player.js';
import { addFavoriteTrack } from './library.js';
import { switchTab } from '../core/router.js';

export async function fetchRandomMix(channelId = null) {
    const spinner = document.getElementById('random-mix-loading-spinner');
    if (spinner) spinner.classList.remove('hidden');

    try {
        const url = channelId ? `/api/random_mix?channel_id=${channelId}` : '/api/random_mix';
        const res = await fetch(url);
        const data = await res.json();

        if (spinner) spinner.classList.add('hidden');

        if (data.error) {
            showToast(data.error, 'error');
            return null;
        }

        const track = data.track;
        state.currentRandomMixTrack = track;

        const cover = document.getElementById('random-mix-cover');
        const badge = document.getElementById('random-mix-badge');
        const title = document.getElementById('random-mix-title');
        const artist = document.getElementById('random-mix-artist');
        const duration = document.getElementById('random-mix-duration');
        const channelTag = document.getElementById('random-mix-channel-tag');

        if (cover) cover.src = track.thumbnail || 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=500';
        if (title) title.innerText = track.title;
        if (artist) artist.innerText = `${track.artist} (${track.channel_label})`;
        if (duration) duration.innerText = track.duration_string || formatTime(track.duration);

        if (channelTag) {
            channelTag.innerHTML = `<i class="fa-solid fa-tv"></i> ${escapeHtml(track.channel_label)}`;
        }

        if (badge) {
            let iconClass = 'fa-youtube';
            if (track.source === 'soundcloud') iconClass = 'fa-soundcloud';
            else if (track.source === 'mixcloud') iconClass = 'fa-mixcloud';
            else if (track.source === 'bandcamp') iconClass = 'fa-bandcamp';

            badge.innerHTML = `<i class="fa-brands ${iconClass}"></i> ${track.source.toUpperCase()}`;
        }

        return track;
    } catch (err) {
        if (spinner) spinner.classList.add('hidden');
        console.error('Failed to fetch random mix:', err);
        showToast('Errore durante l\'estrazione del Mix Random', 'error');
        return null;
    }
}

export async function loadRandomMixIfNeeded() {
    if (!state.currentRandomMixTrack) {
        await fetchRandomMix();
    }
    loadChannelsList();
}

export async function loadHomeMixRandom() {
    const container = document.getElementById('home-mix-random-list');
    if (!container) return;

    try {
        const res = await fetch('/api/random_mix');
        const data = await res.json();
        if (data.error || !data.track) {
            container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Nessun mix casuale disponibile.</div>';
            return;
        }

        const track = data.track;
        state.currentRandomMixTrack = track;
        container.innerHTML = '';

        const card = document.createElement('div');
        card.className = 'glassmorphic-card p-3 rounded-3 d-flex align-items-center justify-content-between gap-3 w-100';
        card.style.background = 'var(--bg-glass)';

        const defaultThumb = 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=200';

        card.innerHTML = `
            <img src="${escapeHtml(track.thumbnail || defaultThumb)}" alt="${escapeHtml(track.title)}" style="width: 76px; height: 76px; object-fit: cover; border-radius: 10px; border: 1px solid var(--border-color); flex-shrink: 0;" onerror="this.src='${defaultThumb}'">
            <div class="d-flex flex-column gap-2" style="width: 125px; flex-shrink: 0;">
                <button class="btn btn-cyan btn-sm btn-play-home-mix" style="font-size: 0.8rem; padding: 5px 8px;">
                    <i class="fa-solid fa-play me-1"></i> Play
                </button>
                <button class="btn btn-outline-secondary btn-sm btn-next-home-mix" style="font-size: 0.75rem; padding: 5px 8px;">
                    <i class="fa-solid fa-dice me-1"></i> Prossimo Mix
                </button>
            </div>
            <div style="min-width: 0; flex: 1;">
                <span class="badge bg-danger bg-opacity-75 text-light mb-1" style="font-size: 0.65rem;">
                    <i class="fa-solid fa-shuffle me-1"></i>${escapeHtml(track.channel_label || 'Mix Random')}
                </span>
                <div style="font-weight: 700; font-size: 0.88rem;" class="truncate text-light">${escapeHtml(track.title || 'Mix Casuale')}</div>
                <div style="font-size: 0.76rem; color: var(--text-muted);" class="truncate">${escapeHtml(track.artist || 'Artista')}</div>
            </div>
        `;

        const btnPlay = card.querySelector('.btn-play-home-mix');
        if (btnPlay) {
            btnPlay.addEventListener('click', (e) => {
                e.stopPropagation();
                playTrack(track);
                showToast(`In riproduzione: ${track.title}`);
            });
        }

        const btnNext = card.querySelector('.btn-next-home-mix');
        if (btnNext) {
            btnNext.addEventListener('click', (e) => {
                e.stopPropagation();
                loadHomeMixRandom();
                showToast('Estrazione nuovo Mix Random...');
            });
        }

        container.appendChild(card);
    } catch (err) {
        console.error('Errore caricamento Mix Random in Home:', err);
        container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Errore durante il caricamento del Mix.</div>';
    }
}

export async function loadChannelsList() {
    const container = document.getElementById('channels-list-container');
    if (!container) return;

    try {
        const res = await fetch('/api/channels');
        const data = await res.json();
        const channels = data.channels || [];

        container.innerHTML = '';
        if (channels.length === 0) {
            container.innerHTML = '<div style="grid-column: 1/-1; color: var(--text-secondary); font-size: 0.85rem;">Nessun canale personalizzato. Aggiungine uno col form sopra!</div>';
            return;
        }

        channels.forEach(ch => {
            const card = document.createElement('div');
            card.className = 'glassmorphic-card';
            card.style.padding = '12px 14px';
            card.style.borderRadius = '14px';
            card.style.display = 'flex';
            card.style.alignItems = 'center';
            card.style.justifyContent = 'space-between';
            card.style.gap = '10px';

            let icon = 'fa-youtube';
            if (ch.platform === 'soundcloud') icon = 'fa-soundcloud';
            else if (ch.platform === 'mixcloud') icon = 'fa-mixcloud';
            else if (ch.platform === 'bandcamp') icon = 'fa-bandcamp';

            card.innerHTML = `
                <div style="display: flex; align-items: center; gap: 10px; min-width: 0;">
                    <i class="fa-brands ${icon}" style="font-size: 1.2rem; color: var(--accent-cyan);"></i>
                    <div style="min-width: 0;">
                        <div style="font-weight: 700; font-size: 0.88rem;" class="truncate">${escapeHtml(ch.label)}</div>
                        <div style="font-size: 0.75rem; color: var(--text-secondary);" class="truncate">${escapeHtml(ch.platform.toUpperCase())}</div>
                    </div>
                </div>
                <div style="display: flex; gap: 6px;">
                    <button class="btn btn-sm btn-outline btn-draw-channel" title="Estrai Mix da questo canale" style="padding: 4px 8px; font-size: 0.75rem;"><i class="fa-solid fa-shuffle"></i></button>
                    <button class="btn btn-sm btn-outline btn-del-channel" title="Elimina canale" style="padding: 4px 8px; font-size: 0.75rem; color: var(--accent-pink);"><i class="fa-solid fa-trash"></i></button>
                </div>
            `;

            card.querySelector('.btn-draw-channel').addEventListener('click', () => {
                fetchRandomMix(ch.id);
            });

            card.querySelector('.btn-del-channel').addEventListener('click', async () => {
                if (confirm(`Eliminare il canale '${ch.label}'?`)) {
                    try {
                        const delRes = await fetch(`/api/channels/${ch.id}`, { method: 'DELETE' });
                        if (delRes.ok) {
                            showToast(`Canale '${ch.label}' rimosso`);
                            loadChannelsList();
                        }
                    } catch (e) {
                        showToast('Errore durante l\'eliminazione del canale', 'error');
                    }
                }
            });

            container.appendChild(card);
        });
    } catch (err) {
        console.error('Failed to load channels:', err);
    }
}

export function scrollToChannelsPanel() {
    const panel = document.getElementById('channels-management-panel');
    if (panel) {
        panel.scrollIntoView({ behavior: 'smooth' });
    }
}

window.scrollToChannelsPanel = scrollToChannelsPanel;
window.toggleChannelsPanel = scrollToChannelsPanel;

export function initMixRandomView() {
    const btnNextRandom = document.getElementById('btn-next-random-mix');
    if (btnNextRandom) {
        btnNextRandom.addEventListener('click', () => fetchRandomMix());
    }

    const btnPlayRandom = document.getElementById('btn-play-random-mix');
    if (btnPlayRandom) {
        btnPlayRandom.addEventListener('click', () => {
            if (state.currentRandomMixTrack) {
                playTrack(state.currentRandomMixTrack);
            } else {
                fetchRandomMix().then(tr => { if (tr) playTrack(tr); });
            }
        });
    }

    const btnQueueRandom = document.getElementById('btn-queue-random-mix');
    if (btnQueueRandom) {
        btnQueueRandom.addEventListener('click', () => {
            if (state.currentRandomMixTrack) {
                addToQueue(state.currentRandomMixTrack);
                showToast(`Aggiunto in coda: ${state.currentRandomMixTrack.title}`);
            }
        });
    }

    const btnFavRandom = document.getElementById('btn-fav-random-mix');
    if (btnFavRandom) {
        btnFavRandom.addEventListener('click', () => {
            if (state.currentRandomMixTrack) {
                addFavoriteTrack(state.currentRandomMixTrack);
            }
        });
    }

    const toggleChannelsBtn = document.getElementById('toggle-channels-panel-btn');
    if (toggleChannelsBtn) {
        toggleChannelsBtn.addEventListener('click', () => {
            scrollToChannelsPanel();
        });
    }

    const addChannelForm = document.getElementById('add-channel-form');
    if (addChannelForm) {
        addChannelForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const urlEl = document.getElementById('channel-url-input');
            const labelEl = document.getElementById('channel-label-input');
            const platformEl = document.getElementById('channel-platform-select');

            const url = urlEl ? urlEl.value.trim() : '';
            const label = labelEl ? labelEl.value.trim() : '';
            const platform = platformEl ? platformEl.value : '';

            if (!url) return;

            try {
                const res = await fetch('/api/channels', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url, label, platform })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast(data.message || 'Canale aggiunto');
                    if (urlEl) urlEl.value = '';
                    if (labelEl) labelEl.value = '';
                    loadChannelsList();
                } else {
                    showToast(data.error || 'Errore durante l\'aggiunta', 'error');
                }
            } catch (err) {
                showToast('Errore di connessione col server', 'error');
            }
        });
    }
}

if (document.readyState !== 'loading') {
    initMixRandomView();
} else {
    document.addEventListener('DOMContentLoaded', () => {
        initMixRandomView();
    });
}
