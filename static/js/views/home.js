// Home View Module for CrossWave Hybrid
import { state } from '../core/state.js';
import { showToast, escapeHtml } from '../core/utils.js';
import { navigate, switchTab } from '../core/router.js';
import { loadHomeMixRandom } from './mixrandom.js';
import { createResultRow, executeSearch } from './search.js';
import { openRadioDetailModal } from './radios.js';
import { openBandcampAlbumDetailView } from './album.js';
import { playTrack } from '../player/player.js';

export async function loadHomeDashboard() {
    const hour = new Date().getHours();
    let greeting = 'Buon ascolto';
    if (hour >= 5 && hour < 12) greeting = 'Buongiorno ☀️';
    else if (hour >= 12 && hour < 18) greeting = 'Buon pomeriggio 🎧';
    else greeting = 'Buonasera 🌙';

    const timeTag = document.getElementById('home-greeting-time');
    if (timeTag) timeTag.innerText = greeting;

    await loadHomeMixRandom();

    // Caricamento Gruppo Ascolto (Telegram Shared Music) sulla Home
    const homeTelegramList = document.getElementById('home-telegram-list');
    if (homeTelegramList) {
        try {
            const res = await fetch('/api/telegram/feed');
            const data = await res.json();
            const shares = data.shares || [];
            homeTelegramList.innerHTML = '';
            if (shares.length === 0) {
                homeTelegramList.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Nessun brano condiviso dagli amici finora.</div>';
            } else {
                let currentTgIdx = 0;

                const renderTgCard = (index) => {
                    homeTelegramList.innerHTML = '';
                    const share = shares[index];
                    if (!share) return;

                    const card = document.createElement('div');
                    card.className = 'glassmorphic-card p-3 rounded-3 d-flex align-items-center justify-content-between gap-3 w-100';
                    card.style.background = 'var(--bg-glass)';

                    const defaultThumb = 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=200';
                    const sender = share.sender_username ? `@${escapeHtml(share.sender_username)}` : escapeHtml(share.sender_name || 'Amico');

                    card.innerHTML = `
                        <img src="${escapeHtml(share.thumbnail || defaultThumb)}" alt="${escapeHtml(share.title)}" style="width: 76px; height: 76px; object-fit: cover; border-radius: 10px; border: 1px solid var(--border-color); flex-shrink: 0;" onerror="this.src='${defaultThumb}'">
                        <div class="d-flex flex-column gap-2" style="width: 125px; flex-shrink: 0;">
                            <button class="btn btn-cyan btn-sm btn-play-home-tg" style="font-size: 0.8rem; padding: 5px 8px;">
                                <i class="fa-solid fa-play me-1"></i> Play
                            </button>
                            <button class="btn btn-outline-secondary btn-sm btn-next-home-tg" style="font-size: 0.75rem; padding: 5px 8px;">
                                <i class="fa-solid fa-forward me-1"></i> Prossimo Disco
                            </button>
                        </div>
                        <div style="min-width: 0; flex: 1;">
                            <div class="d-flex align-items-center gap-2 mb-1 flex-wrap">
                                <span class="badge bg-primary bg-opacity-75 text-light" style="font-size: 0.65rem;">
                                    <i class="fa-solid fa-user me-1"></i>${sender}
                                </span>
                                <span class="badge bg-dark border border-secondary text-light" style="font-size: 0.65rem;">
                                    🏷️ ${escapeHtml(share.label || 'Self-Released')}
                                </span>
                            </div>
                            <div style="font-weight: 700; font-size: 0.88rem;" class="truncate text-light">${escapeHtml(share.title || 'Senza Titolo')}</div>
                            <div style="font-size: 0.76rem; color: var(--text-muted);" class="truncate">${escapeHtml(share.artist || 'Artista Sconosciuto')}</div>
                        </div>
                    `;

                    const btnPlay = card.querySelector('.btn-play-home-tg');
                    if (btnPlay) {
                        btnPlay.addEventListener('click', (e) => {
                            e.stopPropagation();
                            openBandcampAlbumDetailView({
                                url: share.url,
                                title: share.title,
                                artist: share.artist,
                                thumbnail: share.thumbnail
                            });
                        });
                    }

                    const btnNext = card.querySelector('.btn-next-home-tg');
                    if (btnNext) {
                        btnNext.addEventListener('click', (e) => {
                            e.stopPropagation();
                            currentTgIdx = (currentTgIdx + 1) % shares.length;
                            renderTgCard(currentTgIdx);
                        });
                    }

                    homeTelegramList.appendChild(card);
                };

                renderTgCard(0);
            }
        } catch (e) {
            console.error('Errore caricamento Gruppo Ascolto in Home:', e);
        }
    }

    const favList = document.getElementById('home-favorites-list');
    if (favList) {
        try {
            const res = await fetch('/api/favorites');
            const data = await res.json();
            const tracks = data.favorites || [];
            favList.innerHTML = '';
            if (tracks.length === 0) {
                favList.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Nessun preferito salvato. Clicca ❤️ sui brani!</div>';
            } else {
                tracks.slice(0, 5).forEach((t, idx) => {
                    favList.appendChild(createResultRow(t, idx));
                });
            }
        } catch (e) {}
    }

    const wlList = document.getElementById('home-watch-later-list');
    if (wlList) {
        try {
            const res = await fetch('/api/watch_later');
            const data = await res.json();
            const tracks = data.watch_later || [];
            wlList.innerHTML = '';
            if (tracks.length === 0) {
                wlList.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Nessun brano in coda. Clicca su Guarda Dopo!</div>';
            } else {
                tracks.slice(0, 5).forEach((t, idx) => {
                    wlList.appendChild(createResultRow(t, idx));
                });
            }
        } catch (e) {}
    }

    const homeRadiosList = document.getElementById('home-radios-list');
    if (homeRadiosList) {
        try {
            const res = await fetch('/api/radios');
            const data = await res.json();
            const radios = data.radios || [];
            homeRadiosList.innerHTML = '';
            if (radios.length === 0) {
                homeRadiosList.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Nessuna stazione web radio disponibile.</div>';
            } else {
                radios.forEach(radio => {
                    const card = document.createElement('div');
                    card.className = 'glassmorphic-card';
                    card.style.minWidth = '250px';
                    card.style.width = '250px';
                    card.style.padding = '12px 14px';
                    card.style.borderRadius = '14px';
                    card.style.display = 'flex';
                    card.style.flexDirection = 'row';
                    card.style.alignItems = 'center';
                    card.style.justifyContent = 'space-between';
                    card.style.gap = '10px';
                    card.style.flex = '0 0 auto';
                    card.style.background = 'var(--bg-glass)';

                    card.innerHTML = `
                        <img src="${radio.logo || 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=150'}" alt="${escapeHtml(radio.name)}" style="width: 44px; height: 44px; border-radius: 10px; object-fit: cover; border: 2px solid var(--accent-cyan); flex-shrink: 0;">
                        <div style="flex: 1; min-width: 0; text-align: left;">
                            <div style="font-weight: 700; font-size: 0.85rem; margin-bottom: 2px;" class="truncate">${escapeHtml(radio.name)}</div>
                            <div style="font-size: 0.75rem; color: var(--accent-cyan);" class="truncate">${escapeHtml(radio.genre || 'Web Radio')}</div>
                        </div>
                        <div style="display: flex; gap: 6px; align-items: center; flex-shrink: 0;">
                            <button class="btn btn-secondary btn-sm btn-info-radio" title="Info" style="padding: 6px 8px; font-size: 0.75rem;"><i class="fa-solid fa-circle-info"></i></button>
                            <button class="btn btn-cyan btn-sm btn-play-radio" title="Ascolta Live" style="padding: 6px 10px; font-size: 0.75rem;"><i class="fa-solid fa-play"></i></button>
                        </div>
                    `;

                    const btnInfo = card.querySelector('.btn-info-radio');
                    if (btnInfo) {
                        btnInfo.addEventListener('click', () => {
                            openRadioDetailModal(radio.id);
                        });
                    }

                    const btnPlay = card.querySelector('.btn-play-radio');
                    if (btnPlay) {
                        btnPlay.addEventListener('click', () => {
                            const radioTrack = {
                                id: `radio_${radio.id}`,
                                title: radio.name,
                                artist: radio.genre || 'Web Radio Live',
                                source: 'radio',
                                url: radio.stream_url,
                                thumbnail: radio.logo,
                                duration: 0
                            };
                            playTrack(radioTrack);
                            showToast(`In riproduzione: ${radio.name}`);
                        });
                    }

                    homeRadiosList.appendChild(card);
                });
            }
        } catch (e) {}
    }
}

export function initHomeView() {
    const homeSearchBtn = document.getElementById('home-search-btn');
    const homeSearchInput = document.getElementById('home-search-input');
    if (homeSearchBtn && homeSearchInput) {
        const triggerHomeSearch = () => {
            const val = homeSearchInput.value.trim();
            if (!val) return;
            const searchInput = document.getElementById('search-input');
            if (searchInput) searchInput.value = val;
            navigate('search');
            executeSearch();
        };
        homeSearchBtn.addEventListener('click', triggerHomeSearch);
        homeSearchInput.addEventListener('keyup', (e) => {
            if (e.key === 'Enter') triggerHomeSearch();
        });
    }

    const quickFavBtn = document.getElementById('quick-play-favorites-btn');
    if (quickFavBtn) {
        quickFavBtn.addEventListener('click', () => {
            fetch('/api/favorites')
                .then(res => res.json())
                .then(data => {
                    const favs = data.favorites || [];
                    if (favs.length > 0) {
                        state.queue = [...favs];
                        state.currentIndex = 0;
                        playTrack(state.queue[0]);
                        showToast('Riproduzione preferiti avviata');
                    } else {
                        showToast('Nessun brano nei preferiti');
                    }
                })
                .catch(() => showToast('Errore di connessione', 'error'));
        });
    }

    const quickRadioBtn = document.getElementById('quick-radio-btn');
    if (quickRadioBtn) {
        quickRadioBtn.addEventListener('click', () => {
            fetch('/api/favorites')
                .then(res => res.json())
                .then(data => {
                    const favs = data.favorites || [];
                    if (favs.length > 0) {
                        state.queue = [...favs].sort(() => Math.random() - 0.5);
                        state.currentIndex = 0;
                        playTrack(state.queue[0]);
                        showToast('Radio avviata dai preferiti');
                    } else {
                        navigate('web-radio');
                    }
                })
                .catch(() => navigate('web-radio'));
        });
    }

    const quickFocusBtn = document.getElementById('quick-focus-room-btn');
    if (quickFocusBtn) {
        quickFocusBtn.addEventListener('click', () => {
            const searchInput = document.getElementById('search-input');
            if (searchInput) searchInput.value = 'Lofi beats study chill';
            navigate('search');
            executeSearch();
        });
    }

    const quickDjBtn = document.getElementById('quick-djsets-btn');
    if (quickDjBtn) {
        quickDjBtn.addEventListener('click', () => {
            const searchInput = document.getElementById('search-input');
            if (searchInput) searchInput.value = 'DJ set mix live 2026';
            navigate('search');
            executeSearch();
        });
    }

    const homeViewAllRadiosBtn = document.getElementById('home-view-all-radios-btn');
    if (homeViewAllRadiosBtn) {
        homeViewAllRadiosBtn.addEventListener('click', () => {
            navigate('web-radio');
        });
    }

    const homeMixBtn = document.getElementById('home-mix-random-btn');
    if (homeMixBtn) {
        homeMixBtn.addEventListener('click', () => {
            navigate('mix-random');
        });
    }

    const homeTelegramBtn = document.getElementById('home-view-all-telegram-btn');
    if (homeTelegramBtn) {
        homeTelegramBtn.addEventListener('click', () => {
            navigate('telegram');
        });
    }
}

if (document.readyState !== 'loading') {
    initHomeView();
} else {
    document.addEventListener('DOMContentLoaded', () => {
        initHomeView();
    });
}
