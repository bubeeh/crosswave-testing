import { showToast, escapeHtml } from '../core/utils.js';
import { addToQueue } from '../player/player.js';
import { openBandcampAlbumDetailView } from './album.js';
import { sendToSoundload } from './soundload.js';

let telegramShares = [];

export async function loadTelegramFeed() {
    const tbody = document.getElementById('telegram-feed-tbody');
    const badge = document.getElementById('telegram-count-badge');
    if (!tbody) return;

    try {
        const response = await fetch('/api/telegram/feed');
        if (!response.ok) throw new Error('Impossibile caricare il feed Telegram');

        const data = await response.json();
        telegramShares = data.shares || [];

        if (badge) badge.textContent = `${telegramShares.length} Tracce`;

        renderTelegramTable(telegramShares);
    } catch (err) {
        console.error('Errore feed Telegram:', err);
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center text-danger py-4">
                    <i class="fa-solid fa-triangle-exclamation fa-2x mb-2 d-block"></i>
                    Errore nel caricamento del feed Telegram: ${escapeHtml(err.message)}
                </td>
            </tr>
        `;
    }
}

function renderTelegramTable(items) {
    const tbody = document.getElementById('telegram-feed-tbody');
    if (!tbody) return;

    if (items.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center text-muted py-5">
                    <i class="fa-brands fa-telegram fa-3x mb-3 text-muted d-block opacity-50"></i>
                    Nessun brano condiviso finora. Incolla dei link di Bandcamp nel tuo gruppo Telegram!
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = items.map((share, idx) => {
        const defaultThumb = 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=120';
        const thumbUrl = share.thumbnail || defaultThumb;
        const sender = share.sender_username ? `@${escapeHtml(share.sender_username)}` : escapeHtml(share.sender_name || 'Amico');
        const dateStr = share.created_at ? share.created_at.substring(0, 10) : 'Oggi';

        return `
            <tr data-index="${idx}" class="telegram-row">
                <td class="clickable-album-trigger" data-index="${idx}" style="cursor: pointer;">
                    <img src="${escapeHtml(thumbUrl)}" class="rounded border border-color" style="width: 48px; height: 48px; object-fit: cover;" onerror="this.src='${defaultThumb}'">
                </td>
                <td class="clickable-album-trigger" data-index="${idx}" style="cursor: pointer;">
                    <div class="fw-bold text-light text-hover-accent">${escapeHtml(share.title || 'Senza Titolo')}</div>
                    <div class="text-muted small">${escapeHtml(share.artist || 'Artista Sconosciuto')}</div>
                </td>
                <td>
                    <span class="badge bg-dark border border-secondary text-light px-2 py-1">${escapeHtml(share.label || 'Self-Released')}</span>
                </td>
                <td class="text-muted small font-mono">${escapeHtml(share.release_date || 'N/D')}</td>
                <td>
                    <span class="badge bg-primary bg-opacity-25 text-info border border-info border-opacity-25 px-2 py-1">
                        <i class="fa-solid fa-user me-1"></i>${sender}
                    </span>
                </td>
                <td class="text-muted small font-mono">${dateStr}</td>
                <td class="text-end">
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-success btn-play-telegram" data-index="${idx}" title="Apri Disco e Riproduci">
                            <i class="fa-solid fa-play"></i>
                        </button>
                        <button class="btn btn-outline-secondary btn-queue-telegram" data-index="${idx}" title="Aggiungi alla Coda">
                            <i class="fa-solid fa-plus"></i>
                        </button>
                        <button class="btn btn-outline-dark text-muted btn-del-telegram" data-id="${share.id}" title="Rimuovi dal Feed">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    // Bind event listeners sugli elementi dinamici della tabella
    tbody.querySelectorAll('.clickable-album-trigger, .btn-play-telegram').forEach(el => {
        el.addEventListener('click', (e) => {
            const idx = parseInt(e.currentTarget.getAttribute('data-index'));
            const share = items[idx];
            if (!share) return;
            openBandcampAlbumDetailView({
                url: share.url,
                title: share.title,
                artist: share.artist,
                thumbnail: share.thumbnail
            });
        });
    });

    tbody.querySelectorAll('.btn-queue-telegram').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const idx = parseInt(e.currentTarget.getAttribute('data-index'));
            const share = items[idx];
            if (!share) return;
            addToQueue({
                id: `tg_${share.id}`,
                title: share.title,
                artist: share.artist,
                source: share.platform || 'bandcamp',
                url: share.url,
                thumbnail: share.thumbnail,
                duration: 0
            });
            showToast(`"${share.title}" aggiunto alla coda`);
        });
    });

    tbody.querySelectorAll('.btn-dl-telegram').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const idx = parseInt(e.currentTarget.getAttribute('data-index'));
            const share = items[idx];
            if (!share) return;
            sendToSoundload(share.url);
        });
    });

    tbody.querySelectorAll('.btn-del-telegram').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const id = e.currentTarget.getAttribute('data-id');
            if (!id) return;
            if (!confirm('Rimuovere questo brano dal feed Telegram?')) return;
            try {
                const res = await fetch(`/api/telegram/feed/${id}`, { method: 'DELETE' });
                if (res.ok) {
                    showToast('Elemento rimosso dal feed Telegram');
                    loadTelegramFeed();
                }
            } catch (err) {
                showToast('Errore durante l\'eliminazione', 'error');
            }
        });
    });
}

export function initTelegramView() {
    const filterInput = document.getElementById('telegram-filter-input');
    if (filterInput) {
        filterInput.addEventListener('input', (e) => {
            const q = e.target.value.toLowerCase().trim();
            const filtered = telegramShares.filter(s => 
                (s.title && s.title.toLowerCase().includes(q)) ||
                (s.artist && s.artist.toLowerCase().includes(q)) ||
                (s.label && s.label.toLowerCase().includes(q)) ||
                (s.sender_name && s.sender_name.toLowerCase().includes(q)) ||
                (s.sender_username && s.sender_username.toLowerCase().includes(q))
            );
            renderTelegramTable(filtered);
        });
    }

    const refreshBtn = document.getElementById('btn-refresh-telegram');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            loadTelegramFeed();
            showToast('Feed Telegram aggiornato');
        });
    }
}

if (document.readyState !== 'loading') {
    initTelegramView();
} else {
    document.addEventListener('DOMContentLoaded', () => {
        initTelegramView();
    });
}
