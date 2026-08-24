// Web Radio View Module for CrossWave Hybrid
import { showToast, escapeHtml } from '../core/utils.js';
import { playTrack } from '../player/player.js';

export async function loadWebRadios() {
    const grid = document.getElementById('web-radios-grid');
    if (!grid) return;
    try {
        const response = await fetch('/api/radios');
        const data = await response.json();
        const radios = data.radios || [];
        grid.innerHTML = '';
        if (radios.length === 0) {
            grid.innerHTML = '<div class="empty-state-text" style="grid-column: 1/-1;">Nessuna stazione web radio presente.</div>';
            return;
        }
        radios.forEach(radio => {
            const card = document.createElement('div');
            card.className = 'radio-card glassmorphic-card';
            card.style.padding = '12px 20px';
            card.style.borderRadius = '16px';
            card.style.display = 'flex';
            card.style.flexDirection = 'row';
            card.style.alignItems = 'center';
            card.style.justifyContent = 'space-between';
            card.style.background = 'var(--bg-glass)';

            card.innerHTML = `
                <div style="display: flex; align-items: center; gap: 16px; flex: 1; min-width: 0;">
                    <img src="${radio.logo || 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=150'}" alt="${escapeHtml(radio.name)}" style="width: 50px; height: 50px; border-radius: 12px; object-fit: cover; border: 2px solid var(--accent-cyan); flex-shrink: 0;">
                    <div style="flex: 1; min-width: 0; text-align: left;">
                        <div style="font-weight: 700; font-size: 1rem; margin-bottom: 2px;" class="truncate">${escapeHtml(radio.name)}</div>
                        <div style="font-size: 0.82rem; color: var(--accent-cyan);" class="truncate">${escapeHtml(radio.genre || 'Web Radio')}</div>
                    </div>
                </div>
                <div style="display: flex; gap: 10px; align-items: center; flex-shrink: 0;">
                    <button class="btn btn-secondary btn-sm btn-info-radio" title="Info & Palinsesto" style="padding: 8px 12px;"><i class="fa-solid fa-circle-info"></i> Info</button>
                    <button class="btn btn-cyan btn-sm btn-play-radio" style="padding: 8px 16px;"><i class="fa-solid fa-play"></i> Ascolta Live</button>
                    ${radio.id > 10 ? `<button class="btn btn-secondary btn-sm btn-del-radio" title="Elimina" style="padding: 8px 12px;"><i class="fa-solid fa-trash"></i></button>` : ''}
                </div>
            `;

            card.querySelector('.btn-info-radio').addEventListener('click', () => {
                openRadioDetailModal(radio.id);
            });

            card.querySelector('.btn-play-radio').addEventListener('click', () => {
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

            const delBtn = card.querySelector('.btn-del-radio');
            if (delBtn) {
                delBtn.addEventListener('click', async () => {
                    if (confirm(`Eliminare la stazione "${radio.name}"?`)) {
                        try {
                            const res = await fetch(`/api/radios/${radio.id}`, { method: 'DELETE' });
                            if (res.ok) {
                                showToast(`Stazione '${radio.name}' rimossa`);
                                loadWebRadios();
                            }
                        } catch (e) {
                            showToast('Errore durante l\'eliminazione', 'error');
                        }
                    }
                });
            }

            grid.appendChild(card);
        });
    } catch (err) {
        console.error('Failed to load web radios', err);
    }
}

export async function openRadioDetailModal(radioId) {
    const modal = document.getElementById('radio-detail-modal');
    if (!modal) return;

    const logoEl = document.getElementById('radio-detail-logo');
    const nameEl = document.getElementById('radio-detail-name');
    const genreEl = document.getElementById('radio-detail-genre');
    const nowEl = document.getElementById('radio-detail-now-playing');
    const scheduleList = document.getElementById('radio-detail-schedule-list');

    if (logoEl) logoEl.src = 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=150';
    if (nameEl) nameEl.innerText = 'Caricamento...';
    if (genreEl) genreEl.innerText = '--';
    if (nowEl) nowEl.innerText = 'Lettura metadati live in corso...';
    if (scheduleList) scheduleList.innerHTML = '<div class="empty-state-text">Caricamento palinsesto...</div>';

    modal.classList.remove('hidden');

    try {
        const response = await fetch(`/api/radios/${radioId}/details`);
        const data = await response.json();
        const radio = data.radio;

        if (!radio) return;

        if (logoEl) logoEl.src = radio.logo || 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=150';
        if (nameEl) nameEl.innerText = radio.name;
        if (genreEl) genreEl.innerText = radio.genre || 'Web Radio';
        if (nowEl) nowEl.innerText = radio.now_playing || 'Trasmissione Live in corso';

        if (scheduleList) {
            scheduleList.innerHTML = '';
            if (radio.schedule && radio.schedule.length > 0) {
                radio.schedule.forEach(item => {
                    const row = document.createElement('div');
                    row.style.display = 'flex';
                    row.style.justifyContent = 'space-between';
                    row.style.gap = '12px';
                    row.style.fontSize = '0.85rem';
                    row.style.padding = '8px 0';
                    row.style.borderBottom = '1px solid rgba(255,255,255,0.06)';

                    const isUrl = item.title.startsWith('http://') || item.title.startsWith('https://');
                    const titleHtml = isUrl
                        ? `<a href="${escapeHtml(item.title)}" target="_blank" rel="noreferrer" style="color: var(--accent-cyan); text-decoration: underline; font-weight: 600;">${escapeHtml(item.title)} <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 0.72rem;"></i></a>`
                        : `<span style="color: var(--text-primary); text-align: right; flex: 1;">${escapeHtml(item.title)}</span>`;

                    row.innerHTML = `
                        <span style="color: var(--accent-cyan); font-weight: 600; min-width: 120px;">${escapeHtml(item.time)}</span>
                        ${titleHtml}
                    `;
                    scheduleList.appendChild(row);
                });
            }
        }

        const playBtn = document.getElementById('radio-detail-play-btn');
        if (playBtn) {
            playBtn.onclick = () => {
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
                modal.classList.add('hidden');
                showToast(`In riproduzione: ${radio.name}`);
            };
        }
    } catch (err) {
        console.error('Failed to open radio details:', err);
    }
}

export function initRadiosView() {
    const openAddRadioBtn = document.getElementById('open-add-radio-btn');
    const closeAddRadioBtn = document.getElementById('close-add-radio-modal');
    const saveRadioBtn = document.getElementById('save-radio-btn');
    const addRadioModal = document.getElementById('add-radio-modal');

    if (openAddRadioBtn && addRadioModal) {
        openAddRadioBtn.addEventListener('click', () => {
            const nameIn = document.getElementById('radio-name-input');
            const urlIn = document.getElementById('radio-url-input');
            const genreIn = document.getElementById('radio-genre-input');
            if (nameIn) nameIn.value = '';
            if (urlIn) urlIn.value = '';
            if (genreIn) genreIn.value = '';
            addRadioModal.classList.remove('hidden');
        });
    }

    if (closeAddRadioBtn && addRadioModal) {
        closeAddRadioBtn.addEventListener('click', () => {
            addRadioModal.classList.add('hidden');
        });
    }

    if (saveRadioBtn && addRadioModal) {
        saveRadioBtn.addEventListener('click', async () => {
            const nameEl = document.getElementById('radio-name-input');
            const urlEl = document.getElementById('radio-url-input');
            const genreEl = document.getElementById('radio-genre-input');

            const name = nameEl ? nameEl.value.trim() : '';
            const stream_url = urlEl ? urlEl.value.trim() : '';
            const genre = genreEl && genreEl.value.trim() ? genreEl.value.trim() : 'Web Radio';

            if (!name || !stream_url) {
                showToast('Inserisci sia il nome che l\'URL di streaming', 'error');
                return;
            }

            try {
                const response = await fetch('/api/radios', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, stream_url, genre })
                });
                const data = await response.json();
                if (response.ok) {
                    addRadioModal.classList.add('hidden');
                    showToast(`Stazione '${name}' aggiunta`);
                    loadWebRadios();
                } else {
                    showToast(data.error || 'Errore durante il salvataggio', 'error');
                }
            } catch (err) {
                showToast('Errore di connessione col server', 'error');
            }
        });
    }

    const closeRadioDetailModalBtn = document.getElementById('close-radio-detail-modal');
    const radioDetailModal = document.getElementById('radio-detail-modal');
    if (closeRadioDetailModalBtn && radioDetailModal) {
        closeRadioDetailModalBtn.addEventListener('click', () => {
            radioDetailModal.classList.add('hidden');
        });
    }
}

if (document.readyState !== 'loading') {
    initRadiosView();
} else {
    document.addEventListener('DOMContentLoaded', () => {
        initRadiosView();
    });
}
