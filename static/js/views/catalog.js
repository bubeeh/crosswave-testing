// Catalog / Artist-Label Exploration View Module (Bandcamp + YouTube)
import { showToast, escapeHtml, PLACEHOLDER_COVER, isCollectionUrl, youtubeVideoId } from '../core/utils.js';
import { switchTab } from '../core/router.js';
import { playTrackImmediately } from '../player/player.js';
import { openCollectionDetailView } from './album.js';

const PLATFORM_LABELS = {
    bandcamp: 'Bandcamp',
    youtube: 'YouTube',
};

const PLATFORM_ICONS = {
    bandcamp: 'fa-brands fa-bandcamp',
    youtube: 'fa-brands fa-youtube',
};

// Converte un SearchResult canonico (payload /api/catalog) nella forma UI.
function toUiTrack(item) {
    const platform = item.platform;
    const isAlbum = isCollectionUrl(platform, item.url);
    const native = platform === 'youtube' ? youtubeVideoId(item.url) : '';
    return {
        id: (platform === 'youtube' && native) ? `yt_${native}` : item.canonical_id,
        canonical_id: item.canonical_id,
        title: item.title || 'Senza Titolo',
        artist: item.uploader || 'Artista Sconosciuto',
        source: platform,
        url: item.url,
        thumbnail: item.thumbnail || '',
        duration: item.duration || 0,
        type: isAlbum ? 'album' : 'track',
        is_topic: !!item.is_topic,
        verified: !!item.channel_is_verified,
        catalog_url: item.catalog_url || '',
    };
}

export async function openCatalogView({ url, platform, name, isTopic } = {}) {
    if (!url) {
        showToast('URL del catalogo non trovato.', 'error');
        return;
    }
    switchTab('catalog');
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

    const cover = document.getElementById('catalog-view-cover');
    const badge = document.getElementById('catalog-view-badge');
    const title = document.getElementById('catalog-view-title');
    const meta = document.getElementById('catalog-view-meta');
    const relatedBox = document.getElementById('catalog-view-related');
    const sectionsBox = document.getElementById('catalog-view-sections');

    const icon = PLATFORM_ICONS[platform] || 'fa-solid fa-compass';
    const pLabel = PLATFORM_LABELS[platform] || (platform ? platform.toUpperCase() : 'CATALOGO');
    if (badge) badge.innerHTML = `<i class="${icon}"></i> ${pLabel}`;
    if (title) title.innerText = name || 'Caricamento catalogo...';
    if (meta) meta.innerText = 'Caricamento uscite...';
    if (cover) cover.src = PLACEHOLDER_COVER;
    if (relatedBox) relatedBox.innerHTML = '';
    if (sectionsBox) {
        sectionsBox.innerHTML = '<div class="loader-spinner"><div class="double-bounce1"></div><div class="double-bounce2"></div></div>';
    }

    try {
        const qs = new URLSearchParams({ url });
        if (platform) qs.set('platform', platform);
        if (isTopic) qs.set('topic', '1');
        const response = await fetch(`/api/catalog?${qs.toString()}`);
        const data = await response.json();

        if (data.error) {
            showToast(data.error, 'error');
            if (sectionsBox) sectionsBox.innerHTML = `<div class="search-placeholder-state"><i class="fa-solid fa-face-frown placeholder-icon"></i><p>${escapeHtml(data.error)}</p></div>`;
            if (meta) meta.innerText = '';
            return;
        }

        const catalog = data.catalog || {};
        if (title) title.innerText = catalog.name || name || 'Catalogo';
        if (cover && catalog.thumbnail) cover.src = catalog.thumbnail;

        const sections = catalog.sections || [];
        const totalItems = sections.reduce((acc, s) => acc + (s.total || (s.items || []).length), 0);
        if (meta) {
            const rel = sections.map(s => `${s.total} ${s.label.toLowerCase()}`).join(' • ');
            meta.innerText = `${totalItems} uscite • ${rel}`;
        }

        // Etichetta collegata (Bandcamp): chip che riapre il catalogo della label.
        if (relatedBox && (catalog.related || []).length > 0) {
            relatedBox.innerHTML = '';
            catalog.related.forEach(rel => {
                const chip = document.createElement('button');
                chip.className = 'btn btn-outline-cyan btn-sm';
                chip.style.padding = '4px 12px';
                chip.innerHTML = `<i class="fa-solid fa-tag"></i> Etichetta: ${escapeHtml(rel.name)}`;
                chip.addEventListener('click', () => {
                    openCatalogView({ url: rel.url, platform: rel.platform, name: rel.name });
                });
                relatedBox.appendChild(chip);
            });
        }

        if (!sectionsBox) return;
        if (sections.length === 0) {
            sectionsBox.innerHTML = '<div class="search-placeholder-state"><i class="fa-solid fa-face-frown placeholder-icon"></i><p>Nessuna uscita trovata.</p></div>';
            return;
        }

        sectionsBox.innerHTML = '';
        sections.forEach(section => {
            sectionsBox.appendChild(renderSection(section));
        });

    } catch (err) {
        console.error('Failed to load catalog', err);
        showToast('Errore nel caricamento del catalogo.', 'error');
        if (sectionsBox) sectionsBox.innerHTML = '';
    }
}

function renderSection(section) {
    const wrap = document.createElement('div');
    wrap.className = 'catalog-section';
    wrap.style.marginBottom = '30px';

    const heading = document.createElement('h3');
    heading.className = 'section-subtitle';
    heading.style.marginBottom = '14px';
    heading.innerHTML = `${escapeHtml(section.label)} <span style="color: var(--text-muted); font-size: 0.8rem; font-weight: 500;">(${section.total})</span>`;
    wrap.appendChild(heading);

    const grid = document.createElement('div');
    grid.style.display = 'grid';
    grid.style.gridTemplateColumns = 'repeat(auto-fill, minmax(150px, 1fr))';
    grid.style.gap = '14px';
    (section.items || []).forEach(item => grid.appendChild(renderCard(item)));
    wrap.appendChild(grid);
    return wrap;
}

function renderCard(item) {
    const track = toUiTrack(item);
    const isAlbum = track.type === 'album';

    const card = document.createElement('div');
    card.className = 'catalog-card glassmorphic-card';
    card.style.cssText = 'cursor: pointer; border-radius: 12px; overflow: hidden; background: var(--bg-glass); border: 1px solid var(--border-color); transition: var(--transition-fast);';

    const typeTag = isAlbum
        ? `<span class="card-type-badge" style="position: absolute; top: 8px; left: 8px; margin: 0;">ALBUM</span>`
        : '';

    card.innerHTML = `
        <div style="position: relative; aspect-ratio: 1; overflow: hidden;">
            <img src="${escapeHtml(track.thumbnail || PLACEHOLDER_COVER)}"
                 alt="${escapeHtml(track.title)}"
                 style="width: 100%; height: 100%; object-fit: cover; display: block;"
                 onerror="this.onerror=null;this.src='${PLACEHOLDER_COVER}'">
            ${typeTag}
        </div>
        <div style="padding: 10px;">
            <div class="truncate" style="font-size: 0.85rem; font-weight: 600; color: var(--text-primary);">${escapeHtml(track.title)}</div>
            <div class="truncate" style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 2px;">${escapeHtml(track.artist)}</div>
        </div>
    `;

    card.addEventListener('mouseenter', () => { card.style.borderColor = 'var(--accent-cyan)'; });
    card.addEventListener('mouseleave', () => { card.style.borderColor = 'var(--border-color)'; });

    card.addEventListener('click', () => {
        if (isAlbum) {
            openCollectionDetailView(track);
        } else {
            playTrackImmediately(track);
        }
    });

    return card;
}
