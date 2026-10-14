// Digging View Module for CrossWave Hybrid
// Aggrega feed editoriali (Bandcamp Daily, riviste) via /api/digging.
import { showToast, escapeHtml, PLACEHOLDER_COVER } from '../core/utils.js';

const SOURCE_ICON = 'fa-solid fa-compass';

let diggingState = {
    category: '',
    feed: '',
    feeds: [],
};

function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    try {
        return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'short', year: 'numeric' });
    } catch (e) {
        return d.toISOString().slice(0, 10);
    }
}

function externalUrl(url) {
    return escapeHtml(String(url || ''));
}

function createDiggingCard(item, compact = false) {
    const card = document.createElement('article');
    card.className = 'digging-card glassmorphic-card' + (compact ? ' compact' : '');

    const cover = item.image ? escapeHtml(item.image) : PLACEHOLDER_COVER;
    const date = formatDate(item.published);
    const summary = compact ? '' : (item.summary || '');
    const url = item.url || '';

    card.innerHTML = `
        <a class="digging-card-link" href="${externalUrl(url)}" target="_blank" rel="noopener noreferrer">
            <div class="digging-card-media">
                <img src="${cover}" alt="" loading="lazy"
                     onerror="this.onerror=null;this.src='${PLACEHOLDER_COVER}'">
            </div>
            <div class="digging-card-body">
                <div class="digging-card-meta">
                    <span class="digging-source"><i class="${SOURCE_ICON}"></i> ${escapeHtml(item.source || '')}</span>
                    ${date ? `<span class="digging-date">${escapeHtml(date)}</span>` : ''}
                </div>
                <h3 class="digging-card-title">${escapeHtml(item.title || 'Senza titolo')}</h3>
                ${summary ? `<p class="digging-card-summary">${escapeHtml(summary)}</p>` : ''}
            </div>
        </a>
    `;
    return card;
}

function renderFilterChips(feeds) {
    const box = document.getElementById('digging-filters');
    if (!box) return;
    box.innerHTML = '';

    const categories = [];
    feeds.forEach(f => {
        const c = (f.category || '').trim();
        if (c && !categories.includes(c)) categories.push(c);
    });

    const allChip = document.createElement('button');
    allChip.className = 'digging-chip' + (!diggingState.category && !diggingState.feed ? ' active' : '');
    allChip.dataset.category = '';
    allChip.innerHTML = `<i class="fa-solid fa-layer-group"></i> Tutte`;
    box.appendChild(allChip);

    categories.forEach(cat => {
        const chip = document.createElement('button');
        chip.className = 'digging-chip' + (diggingState.category === cat ? ' active' : '');
        chip.dataset.category = cat;
        chip.textContent = cat;
        box.appendChild(chip);
    });

    // Separatore + chip per singola fonte (con rimozione)
    if (feeds.length) {
        const divider = document.createElement('span');
        divider.className = 'digging-filter-divider';
        box.appendChild(divider);
    }
    feeds.forEach(feed => {
        const chip = document.createElement('span');
        chip.className = 'digging-chip digging-chip-feed'
            + (diggingState.feed === feed.name ? ' active' : '');
        chip.dataset.feed = feed.name;
        chip.innerHTML = `<i class="fa-solid fa-rss"></i> ${escapeHtml(feed.name)}`;
        if (feed.id != null) {
            const del = document.createElement('button');
            del.className = 'digging-chip-del';
            del.title = `Rimuovi "${feed.name}"`;
            del.dataset.del = feed.id;
            del.innerHTML = '<i class="fa-solid fa-xmark"></i>';
            chip.appendChild(del);
        }
        box.appendChild(chip);
    });

    box.querySelectorAll('.digging-chip[data-category]').forEach(chip => {
        chip.addEventListener('click', () => {
            diggingState.category = chip.dataset.category || '';
            diggingState.feed = '';
            loadDigging();
        });
    });

    box.querySelectorAll('.digging-chip-feed[data-feed]').forEach(chip => {
        chip.addEventListener('click', (e) => {
            if (e.target.closest('.digging-chip-del')) return;
            diggingState.feed = chip.dataset.feed || '';
            diggingState.category = '';
            loadDigging();
        });
    });

    box.querySelectorAll('.digging-chip-del').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = btn.dataset.del;
            const label = btn.closest('.digging-chip-feed').dataset.feed;
            if (!confirm(`Rimuovere la fonte "${label}"?`)) return;
            try {
                const res = await fetch(`/api/digging/feeds/${id}`, { method: 'DELETE' });
                if (res.ok) {
                    showToast(`Fonte '${label}' rimossa`);
                    loadDigging();
                } else {
                    showToast('Errore durante la rimozione', 'error');
                }
            } catch (err) {
                showToast('Errore di connessione', 'error');
            }
        });
    });
}

export async function loadDigging() {
    const grid = document.getElementById('digging-grid');
    const subtitle = document.getElementById('digging-subtitle');
    const placeholder = document.getElementById('digging-placeholder');
    if (!grid) return;

    grid.innerHTML = '';
    if (placeholder) {
        placeholder.classList.remove('hidden');
        placeholder.querySelector('p').innerText = 'Caricamento delle fonti in corso...';
    }

    const params = new URLSearchParams({ limit: '60' });
    if (diggingState.category) params.set('category', diggingState.category);
    if (diggingState.feed) params.set('feeds', diggingState.feed);

    try {
        const res = await fetch(`/api/digging?${params.toString()}`);
        const data = await res.json();
        const feeds = data.feeds || [];
        diggingState.feeds = feeds;

        renderFilterChips(feeds);

        const items = data.items || [];
        if (subtitle) {
            subtitle.innerText = items.length
                ? `${items.length} articoli da ${feeds.length} fonti`
                : 'Editoriali e riviste musicali';
        }

        if (items.length === 0) {
            if (placeholder) {
                placeholder.classList.remove('hidden');
                const errors = Object.values(data.errors || {});
                placeholder.querySelector('p').innerText = errors.length
                    ? 'Nessun articolo disponibile. Alcune fonti non sono raggiungibili.'
                    : 'Nessun articolo trovato.';
            }
            return;
        }

        if (placeholder) placeholder.classList.add('hidden');
        items.forEach(item => grid.appendChild(createDiggingCard(item, false)));
    } catch (err) {
        console.error('Failed to load digging feeds', err);
        if (placeholder) {
            placeholder.classList.remove('hidden');
            placeholder.querySelector('p').innerText = 'Impossibile caricare le fonti in questo momento.';
        }
    }
}

export async function loadHomeDigging() {
    const list = document.getElementById('home-digging-list');
    const section = document.getElementById('home-digging-section');
    if (!list) return;
    try {
        const res = await fetch('/api/digging?limit=3');
        const data = await res.json();
        const items = data.items || [];
        list.innerHTML = '';
        if (items.length === 0) {
            if (section) section.classList.add('hidden');
            return;
        }
        if (section) section.classList.remove('hidden');
        items.forEach(item => list.appendChild(createDiggingCard(item, true)));
    } catch (err) {
        if (section) section.classList.add('hidden');
    }
}

export function initDiggingView() {
    const modal = document.getElementById('add-feed-modal');
    const openBtn = document.getElementById('open-add-feed-btn');
    const closeBtn = document.getElementById('close-add-feed-modal');
    const saveBtn = document.getElementById('save-feed-btn');

    if (openBtn && modal) {
        openBtn.addEventListener('click', () => {
            ['feed-name-input', 'feed-url-input', 'feed-category-input'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            modal.classList.remove('hidden');
        });
    }

    if (closeBtn && modal) {
        closeBtn.addEventListener('click', () => modal.classList.add('hidden'));
    }

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.classList.add('hidden');
        });
    }

    if (saveBtn && modal) {
        saveBtn.addEventListener('click', async () => {
            const name = (document.getElementById('feed-name-input')?.value || '').trim();
            const url = (document.getElementById('feed-url-input')?.value || '').trim();
            const category = (document.getElementById('feed-category-input')?.value || '').trim() || 'Editoriale';
            if (!name || !url) {
                showToast('Inserisci sia il nome che l\'URL del feed', 'error');
                return;
            }
            try {
                const res = await fetch('/api/digging/feeds', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, url, category }),
                });
                const data = await res.json();
                if (res.ok) {
                    modal.classList.add('hidden');
                    showToast(`Fonte '${name}' aggiunta`);
                    diggingState.category = '';
                    diggingState.feed = '';
                    loadDigging();
                } else {
                    showToast(data.error || 'Errore durante il salvataggio', 'error');
                }
            } catch (err) {
                showToast('Errore di connessione col server', 'error');
            }
        });
    }
}

if (document.readyState !== 'loading') {
    initDiggingView();
} else {
    document.addEventListener('DOMContentLoaded', initDiggingView);
}
