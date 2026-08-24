// Home View Module for CrossWave Hybrid (Modular Home Dashboard)
import { state } from '../core/state.js';
import { showToast, escapeHtml } from '../core/utils.js';
import { navigate, switchTab } from '../core/router.js';
import { loadHomeMixRandom } from './mixrandom.js';
import { createResultRow, executeSearch } from './search.js';
import { openRadioDetailModal } from './radios.js';
import { openBandcampAlbumDetailView } from './album.js';
import { playTrack } from '../player/player.js';

const STORAGE_KEY = 'crosswave_home_layout_v1';

const DEFAULT_WIDGET_LAYOUT = [
    { id: 'radios', width: 'full' },
    { id: 'mixrandom', width: 'half' },
    { id: 'telegram', width: 'half' },
    { id: 'favorites', width: 'half' },
    { id: 'watchlater', width: 'half' },
    { id: 'quick_actions', width: 'full' }
];

let isEditMode = false;
let draggedWidgetId = null;

// Registry of available widgets
const WIDGET_REGISTRY = {
    radios: {
        id: 'radios',
        title: 'Web Radio in Diretta',
        icon: 'fa-solid fa-radio accent-cyan',
        description: 'Stazioni radio in streaming live',
        actionBtn: { text: 'Tutte le Radio', icon: 'fa-solid fa-tower-broadcast', target: 'web-radio' },
        renderContent: async (container) => renderRadiosWidget(container)
    },
    mixrandom: {
        id: 'mixrandom',
        title: 'Mix Random',
        icon: 'fa-solid fa-shuffle accent-cyan',
        description: 'Brano o DJ set estratto a sorte dai tuoi canali',
        actionBtn: { text: 'Altri Mix', icon: 'fa-solid fa-dice', target: 'mix-random' },
        renderContent: async (container) => renderMixRandomWidget(container)
    },
    telegram: {
        id: 'telegram',
        title: 'Gruppo Ascolto',
        icon: 'fa-brands fa-telegram',
        iconStyle: 'color: #0088cc;',
        description: 'Brani e dischi condivisi dalla community Telegram',
        actionBtn: { text: 'Vedi Tutti', icon: 'fa-solid fa-list', target: 'telegram' },
        renderContent: async (container) => renderTelegramWidget(container)
    },
    favorites: {
        id: 'favorites',
        title: 'I Tuoi Preferiti',
        icon: 'fa-solid fa-heart accent-pink',
        description: 'Accesso rapido ai brani salvati nei preferiti',
        actionBtn: { text: 'Vedi Tutti', icon: 'fa-solid fa-heart', target: 'favorites' },
        renderContent: async (container) => renderFavoritesWidget(container)
    },
    watchlater: {
        id: 'watchlater',
        title: 'Guarda / Ascolta Dopo',
        icon: 'fa-solid fa-clock accent-cyan',
        description: 'Coda di brani da ascoltare in seguito',
        actionBtn: { text: 'Vedi Tutti', icon: 'fa-solid fa-clock', target: 'watch-later' },
        renderContent: async (container) => renderWatchLaterWidget(container)
    },
    quick_actions: {
        id: 'quick_actions',
        title: 'Scorciatoie & Mood',
        icon: 'fa-solid fa-bolt accent-cyan',
        description: 'Pulsanti veloci per avviare playlist, radio e generi',
        renderContent: async (container) => renderQuickActionsWidget(container)
    }
};

function getSavedLayout() {
    try {
        const data = localStorage.getItem(STORAGE_KEY);
        if (data) {
            const parsed = JSON.parse(data);
            if (Array.isArray(parsed) && parsed.length > 0) {
                return parsed;
            }
        }
    } catch (e) {
        console.error('Failed to parse home layout from localStorage:', e);
    }
    return [...DEFAULT_WIDGET_LAYOUT];
}

function saveLayout(layout) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
    } catch (e) {
        console.error('Failed to save home layout:', e);
    }
}

export async function loadHomeDashboard() {
    updateGreeting();
    renderHomeGrid();
}

function updateGreeting() {
    const hour = new Date().getHours();
    let greeting = 'Buon ascolto 🎧';
    if (hour >= 5 && hour < 12) greeting = 'Buongiorno ☀️';
    else if (hour >= 12 && hour < 18) greeting = 'Buon pomeriggio 🎧';
    else greeting = 'Buonasera 🌙';

    const timeTag = document.getElementById('home-greeting-time');
    if (timeTag) timeTag.innerText = greeting;
}

function renderHomeGrid() {
    const container = document.getElementById('home-widgets-container');
    if (!container) return;

    if (isEditMode) {
        container.classList.add('edit-mode');
    } else {
        container.classList.remove('edit-mode');
    }

    const layout = getSavedLayout();
    container.innerHTML = '';

    if (layout.length === 0) {
        container.innerHTML = `
            <div class="glassmorphic-card p-4 text-center w-100" style="margin: 20px 0; border: 1px dashed var(--accent-cyan);">
                <i class="fa-solid fa-square-plus" style="font-size: 2rem; color: var(--accent-cyan); margin-bottom: 10px;"></i>
                <h4 style="font-weight: 700; margin-bottom: 6px;">Nessun widget in Home</h4>
                <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 16px;">La tua home page è attualmente vuota. Aggiungi dei widget o ripristina il layout predefinito.</p>
                <div class="d-flex justify-content-center gap-2">
                    <button class="btn btn-cyan btn-sm" id="empty-add-widget-btn"><i class="fa-solid fa-plus me-1"></i> Aggiungi Widget</button>
                    <button class="btn btn-secondary btn-sm" id="empty-reset-widget-btn"><i class="fa-solid fa-rotate-left me-1"></i> Ripristina Layout</button>
                </div>
            </div>
        `;
        const btnAdd = container.querySelector('#empty-add-widget-btn');
        if (btnAdd) btnAdd.addEventListener('click', openAddHomeWidgetModal);
        const btnReset = container.querySelector('#empty-reset-widget-btn');
        if (btnReset) btnReset.addEventListener('click', resetHomeLayout);
        return;
    }

    layout.forEach((item, index) => {
        const widgetDef = WIDGET_REGISTRY[item.id];
        if (!widgetDef) return;

        const wrapper = document.createElement('div');
        wrapper.className = `home-widget-wrapper width-${item.width || 'half'}`;
        wrapper.dataset.widgetId = item.id;

        if (isEditMode) {
            wrapper.setAttribute('draggable', 'true');
            wrapper.addEventListener('dragstart', handleDragStart);
            wrapper.addEventListener('dragover', handleDragOver);
            wrapper.addEventListener('dragleave', handleDragLeave);
            wrapper.addEventListener('drop', handleDrop);
            wrapper.addEventListener('dragend', handleDragEnd);
        }

        const card = document.createElement('div');
        card.className = 'home-widget-card';

        // Edit control bar (visible in Edit Mode)
        let editBarHtml = '';
        if (isEditMode) {
            const isFull = item.width === 'full';
            editBarHtml = `
                <div class="home-widget-edit-bar">
                    <div class="d-flex align-items-center gap-2">
                        <span class="widget-drag-handle" title="Trascina per riordinare"><i class="fa-solid fa-grip-vertical"></i></span>
                        <strong class="text-light" style="font-size: 0.85rem;">${escapeHtml(widgetDef.title)}</strong>
                    </div>
                    <div class="d-flex align-items-center gap-1">
                        <button class="widget-ctrl-btn btn-up" data-idx="${index}" title="Sposta Su" ${index === 0 ? 'disabled style="opacity:0.3;"' : ''}>
                            <i class="fa-solid fa-arrow-up"></i>
                        </button>
                        <button class="widget-ctrl-btn btn-down" data-idx="${index}" title="Sposta Giù" ${index === layout.length - 1 ? 'disabled style="opacity:0.3;"' : ''}>
                            <i class="fa-solid fa-arrow-down"></i>
                        </button>
                        <button class="widget-ctrl-btn btn-width" data-idx="${index}" title="Cambia Larghezza (${isFull ? '100%' : '50%'})">
                            <i class="fa-solid ${isFull ? 'fa-compress' : 'fa-expand'} me-1"></i> ${isFull ? 'Intera' : 'Metà'}
                        </button>
                        <button class="widget-ctrl-btn btn-remove" data-id="${item.id}" title="Rimuovi Widget">
                            <i class="fa-solid fa-xmark"></i>
                        </button>
                    </div>
                </div>
            `;
        }

        // Section Header
        let actionBtnHtml = '';
        if (widgetDef.actionBtn) {
            actionBtnHtml = `
                <button class="btn btn-secondary btn-sm widget-action-btn" data-target="${widgetDef.actionBtn.target}" style="font-size: 0.8rem; padding: 4px 10px;">
                    <i class="${widgetDef.actionBtn.icon} me-1"></i> ${escapeHtml(widgetDef.actionBtn.text)}
                </button>
            `;
        }

        const iconStyle = widgetDef.iconStyle ? `style="${widgetDef.iconStyle}"` : '';

        card.innerHTML = `
            ${editBarHtml}
            <div class="home-section-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <h3 style="font-size: 1.05rem; font-weight: 700; margin: 0; display: flex; align-items: center; gap: 8px;">
                    <i class="${widgetDef.icon}" ${iconStyle}></i> ${escapeHtml(widgetDef.title)}
                </h3>
                ${actionBtnHtml}
            </div>
            <div class="widget-content-body" id="widget-body-${item.id}" style="flex: 1;">
                <div class="empty-state-text" style="font-size:12px; padding:12px;">Caricamento...</div>
            </div>
        `;

        wrapper.appendChild(card);
        container.appendChild(wrapper);

        // Bind Action button
        const actionBtn = card.querySelector('.widget-action-btn');
        if (actionBtn) {
            actionBtn.addEventListener('click', () => {
                const target = actionBtn.getAttribute('data-target');
                if (target) navigate(target);
            });
        }

        // Bind Edit buttons
        if (isEditMode) {
            const btnUp = card.querySelector('.btn-up');
            if (btnUp && !btnUp.disabled) btnUp.addEventListener('click', () => moveWidget(index, index - 1));

            const btnDown = card.querySelector('.btn-down');
            if (btnDown && !btnDown.disabled) btnDown.addEventListener('click', () => moveWidget(index, index + 1));

            const btnWidth = card.querySelector('.btn-width');
            if (btnWidth) btnWidth.addEventListener('click', () => toggleWidgetWidth(index));

            const btnRemove = card.querySelector('.btn-remove');
            if (btnRemove) btnRemove.addEventListener('click', () => removeWidget(item.id));
        }

        // Render widget content
        const bodyContainer = card.querySelector(`#widget-body-${item.id}`);
        if (bodyContainer) {
            widgetDef.renderContent(bodyContainer);
        }
    });
}

// Controls: Reorder / Resize / Remove
function moveWidget(fromIndex, toIndex) {
    const layout = getSavedLayout();
    if (fromIndex < 0 || fromIndex >= layout.length || toIndex < 0 || toIndex >= layout.length) return;
    const item = layout.splice(fromIndex, 1)[0];
    layout.splice(toIndex, 0, item);
    saveLayout(layout);
    renderHomeGrid();
}

function toggleWidgetWidth(index) {
    const layout = getSavedLayout();
    if (layout[index]) {
        layout[index].width = layout[index].width === 'full' ? 'half' : 'full';
        saveLayout(layout);
        renderHomeGrid();
    }
}

function removeWidget(widgetId) {
    let layout = getSavedLayout();
    layout = layout.filter(item => item.id !== widgetId);
    saveLayout(layout);
    renderHomeGrid();
    const title = WIDGET_REGISTRY[widgetId] ? WIDGET_REGISTRY[widgetId].title : widgetId;
    showToast(`Widget "${title}" rimosso`);
}

function resetHomeLayout() {
    saveLayout(DEFAULT_WIDGET_LAYOUT);
    renderHomeGrid();
    showToast('Layout Home ripristinato');
}

// Drag & Drop Handlers
function handleDragStart(e) {
    draggedWidgetId = this.dataset.widgetId;
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', draggedWidgetId);
}

function handleDragOver(e) {
    if (e.preventDefault) e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    this.classList.add('drag-over');
    return false;
}

function handleDragLeave() {
    this.classList.remove('drag-over');
}

function handleDrop(e) {
    if (e.stopPropagation) e.stopPropagation();
    this.classList.remove('drag-over');
    const targetWidgetId = this.dataset.widgetId;

    if (draggedWidgetId && targetWidgetId && draggedWidgetId !== targetWidgetId) {
        const layout = getSavedLayout();
        const fromIndex = layout.findIndex(item => item.id === draggedWidgetId);
        const toIndex = layout.findIndex(item => item.id === targetWidgetId);

        if (fromIndex !== -1 && toIndex !== -1) {
            const [draggedItem] = layout.splice(fromIndex, 1);
            layout.splice(toIndex, 0, draggedItem);
            saveLayout(layout);
            renderHomeGrid();
        }
    }
    return false;
}

function handleDragEnd() {
    this.classList.remove('dragging');
    document.querySelectorAll('.home-widget-wrapper').forEach(el => el.classList.remove('drag-over'));
}

// --- Content Renderers for Registered Widgets ---

async function renderRadiosWidget(container) {
    container.className = 'home-horizontal-scroll';
    container.style.cssText = 'display: flex; flex-direction: row; gap: 14px; overflow-x: auto; flex-wrap: nowrap; padding: 4px 4px 12px 4px; scrollbar-width: thin;';

    try {
        const res = await fetch('/api/radios');
        const data = await res.json();
        const radios = data.radios || [];
        container.innerHTML = '';
        if (radios.length === 0) {
            container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Nessuna stazione web radio disponibile.</div>';
            return;
        }

        radios.forEach(radio => {
            const card = document.createElement('div');
            card.className = 'glassmorphic-card';
            card.style.cssText = 'min-width: 250px; width: 250px; padding: 12px 14px; border-radius: 14px; display: flex; flex-direction: row; align-items: center; justify-content: space-between; gap: 10px; flex: 0 0 auto; background: var(--bg-glass);';

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
                btnInfo.addEventListener('click', () => openRadioDetailModal(radio.id));
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

            container.appendChild(card);
        });
    } catch (e) {
        container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Errore caricamento radio.</div>';
    }
}

async function renderMixRandomWidget(container) {
    container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Caricamento mix casuale...</div>';
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
                <div class="d-flex align-items-center gap-2 mb-1">
                    <span class="badge bg-secondary bg-opacity-50 text-light" style="font-size: 0.65rem;">
                        <i class="fa-solid fa-tv me-1"></i>${escapeHtml(track.channel_label || 'Canale')}
                    </span>
                </div>
                <div style="font-weight: 700; font-size: 0.88rem;" class="truncate text-light">${escapeHtml(track.title || 'Senza Titolo')}</div>
                <div style="font-size: 0.76rem; color: var(--text-muted);" class="truncate">${escapeHtml(track.artist || 'Artista Sconosciuto')}</div>
            </div>
        `;

        const btnPlay = card.querySelector('.btn-play-home-mix');
        if (btnPlay) {
            btnPlay.addEventListener('click', () => {
                playTrack(track);
                showToast(`Riproduzione: ${track.title}`);
            });
        }

        const btnNext = card.querySelector('.btn-next-home-mix');
        if (btnNext) {
            btnNext.addEventListener('click', () => renderMixRandomWidget(container));
        }

        container.appendChild(card);
    } catch (e) {
        container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Errore caricamento Mix Random.</div>';
    }
}

async function renderTelegramWidget(container) {
    container.className = 'home-horizontal-scroll';
    container.style.cssText = 'display: flex; flex-direction: row; gap: 14px; overflow-x: auto; flex-wrap: nowrap; padding: 4px 4px 12px 4px; scrollbar-width: thin;';

    try {
        const res = await fetch('/api/telegram/feed');
        const data = await res.json();
        const shares = data.shares || [];
        container.innerHTML = '';
        if (shares.length === 0) {
            container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Nessun brano condiviso dagli amici finora.</div>';
            return;
        }

        let currentTgIdx = 0;

        const renderTgCard = (index) => {
            container.innerHTML = '';
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

            container.appendChild(card);
        };

        renderTgCard(0);
    } catch (e) {
        container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Errore caricamento Gruppo Ascolto.</div>';
    }
}

async function renderFavoritesWidget(container) {
    try {
        const res = await fetch('/api/favorites');
        const data = await res.json();
        const tracks = data.favorites || [];
        container.innerHTML = '';
        if (tracks.length === 0) {
            container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Nessun preferito salvato. Clicca ❤️ sui brani!</div>';
        } else {
            tracks.slice(0, 5).forEach((t, idx) => {
                container.appendChild(createResultRow(t, idx));
            });
        }
    } catch (e) {
        container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Errore caricamento preferiti.</div>';
    }
}

async function renderWatchLaterWidget(container) {
    try {
        const res = await fetch('/api/watch_later');
        const data = await res.json();
        const tracks = data.watch_later || [];
        container.innerHTML = '';
        if (tracks.length === 0) {
            container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Nessun brano in coda. Clicca su Guarda Dopo!</div>';
        } else {
            tracks.slice(0, 5).forEach((t, idx) => {
                container.appendChild(createResultRow(t, idx));
            });
        }
    } catch (e) {
        container.innerHTML = '<div class="empty-state-text" style="font-size:12px; padding:12px;">Errore caricamento guarda dopo.</div>';
    }
}

async function renderQuickActionsWidget(container) {
    container.innerHTML = `
        <div class="d-flex flex-wrap gap-2 py-2">
            <button class="btn btn-outline-cyan btn-sm flex-fill" id="qa-play-favs" style="font-size: 0.82rem; padding: 8px 12px;">
                <i class="fa-solid fa-play me-1"></i> Riproduci Preferiti
            </button>
            <button class="btn btn-outline-purple btn-sm flex-fill" id="qa-radio-favs" style="font-size: 0.82rem; padding: 8px 12px;">
                <i class="fa-solid fa-radio me-1"></i> Radio dai Preferiti
            </button>
            <button class="btn btn-secondary btn-sm flex-fill" id="qa-lofi" style="font-size: 0.82rem; padding: 8px 12px;">
                <i class="fa-solid fa-brain me-1"></i> Lofi Study Focus
            </button>
            <button class="btn btn-secondary btn-sm flex-fill" id="qa-djsets" style="font-size: 0.82rem; padding: 8px 12px;">
                <i class="fa-solid fa-compact-disc me-1"></i> DJ Sets Live 2026
            </button>
        </div>
    `;

    const qaFavs = container.querySelector('#qa-play-favs');
    if (qaFavs) {
        qaFavs.addEventListener('click', () => {
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

    const qaRadio = container.querySelector('#qa-radio-favs');
    if (qaRadio) {
        qaRadio.addEventListener('click', () => {
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

    const qaLofi = container.querySelector('#qa-lofi');
    if (qaLofi) {
        qaLofi.addEventListener('click', () => {
            const searchInput = document.getElementById('search-input');
            if (searchInput) searchInput.value = 'Lofi beats study chill';
            navigate('search');
            executeSearch();
        });
    }

    const qaDj = container.querySelector('#qa-djsets');
    if (qaDj) {
        qaDj.addEventListener('click', () => {
            const searchInput = document.getElementById('search-input');
            if (searchInput) searchInput.value = 'DJ set mix live 2026';
            navigate('search');
            executeSearch();
        });
    }
}

// Modal: Add Widget
function openAddHomeWidgetModal() {
    const modal = document.getElementById('add-home-widget-modal');
    const listContainer = document.getElementById('add-home-widget-list');
    if (!modal || !listContainer) return;

    const currentLayout = getSavedLayout();
    const currentIds = new Set(currentLayout.map(item => item.id));

    listContainer.innerHTML = '';

    Object.values(WIDGET_REGISTRY).forEach(widget => {
        const isAdded = currentIds.has(widget.id);
        const itemEl = document.createElement('div');
        itemEl.className = 'add-widget-item';

        const iconStyle = widget.iconStyle ? `style="${widget.iconStyle}"` : '';

        itemEl.innerHTML = `
            <div class="d-flex align-items-center gap-3">
                <i class="${widget.icon}" ${iconStyle} style="font-size: 1.3rem;"></i>
                <div>
                    <strong style="font-size: 0.9rem;" class="text-light">${escapeHtml(widget.title)}</strong>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">${escapeHtml(widget.description)}</div>
                </div>
            </div>
            <div>
                ${isAdded
                    ? `<span class="badge bg-secondary text-muted" style="font-size: 0.75rem;"><i class="fa-solid fa-check me-1"></i> Inserito</span>`
                    : `<button class="btn btn-cyan btn-sm btn-add-w" data-id="${widget.id}" style="font-size: 0.78rem; padding: 4px 10px;"><i class="fa-solid fa-plus me-1"></i> Aggiungi</button>`
                }
            </div>
        `;

        if (!isAdded) {
            const btnAdd = itemEl.querySelector('.btn-add-w');
            if (btnAdd) {
                btnAdd.addEventListener('click', () => {
                    const layout = getSavedLayout();
                    layout.push({ id: widget.id, width: 'half' });
                    saveLayout(layout);
                    renderHomeGrid();
                    openAddHomeWidgetModal(); // refresh list
                    showToast(`Widget "${widget.title}" aggiunto in Home`);
                });
            }
        }

        listContainer.appendChild(itemEl);
    });

    modal.classList.remove('hidden');
}

function closeAddHomeWidgetModal() {
    const modal = document.getElementById('add-home-widget-modal');
    if (modal) modal.classList.add('hidden');
}

export function initHomeView() {
    // Search Bar on Home
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

    // Toggle Edit Mode Button
    const toggleEditBtn = document.getElementById('toggle-home-edit-btn');
    const toolbar = document.getElementById('home-edit-toolbar');
    const doneEditBtn = document.getElementById('home-done-edit-btn');

    const setEditState = (enable) => {
        isEditMode = enable;
        if (toolbar) {
            if (isEditMode) toolbar.classList.remove('hidden');
            else toolbar.classList.add('hidden');
        }
        if (toggleEditBtn) {
            toggleEditBtn.innerHTML = isEditMode
                ? '<i class="fa-solid fa-check me-1"></i> Fine Modifica'
                : '<i class="fa-solid fa-sliders me-1"></i> Personalizza Home';
            toggleEditBtn.classList.toggle('btn-cyan', isEditMode);
            toggleEditBtn.classList.toggle('btn-outline-cyan', !isEditMode);
        }
        renderHomeGrid();
    };

    if (toggleEditBtn) {
        toggleEditBtn.addEventListener('click', () => setEditState(!isEditMode));
    }
    if (doneEditBtn) {
        doneEditBtn.addEventListener('click', () => setEditState(false));
    }

    // Edit Toolbar Buttons
    const addWidgetBtn = document.getElementById('home-add-widget-btn');
    if (addWidgetBtn) addWidgetBtn.addEventListener('click', openAddHomeWidgetModal);

    const resetLayoutBtn = document.getElementById('home-reset-layout-btn');
    if (resetLayoutBtn) resetLayoutBtn.addEventListener('click', resetHomeLayout);

    // Modal Close Button
    const closeModalBtn = document.getElementById('close-add-home-widget-modal');
    if (closeModalBtn) closeModalBtn.addEventListener('click', closeAddHomeWidgetModal);
}

if (document.readyState !== 'loading') {
    initHomeView();
} else {
    document.addEventListener('DOMContentLoaded', () => {
        initHomeView();
    });
}
