// Web Radio View Module for CrossWave Hybrid
import { showToast, escapeHtml } from '../core/utils.js';
import { playTrack } from '../player/player.js';

const DEFAULT_RADIO_LOGO = 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=150';

function stationInitials(name) {
    const words = String(name || '').replace(/[^\p{L}\p{N}\s]/gu, ' ').trim().split(/\s+/).filter(Boolean);
    if (words.length === 0) return 'RD';
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return (words[0][0] + words[1][0]).toUpperCase();
}

function escapeAttr(text) {
    return String(text == null ? '' : text).replace(/"/g, '&quot;');
}

async function loadRadioProgram(radio, programEl) {
    if (!programEl) return;
    try {
        const response = await fetch(`/api/radios/now_playing?url=${encodeURIComponent(radio.stream_url)}&name=${encodeURIComponent(radio.name)}`);
        const data = await response.json();
        const title = (data && data.now_playing) ? data.now_playing : '';
        programEl.innerText = title || 'Trasmissione live in corso';
    } catch (e) {
        programEl.innerText = 'Trasmissione live in corso';
    }
}

export async function loadWebRadios() {
    const grid = document.getElementById('web-radios-grid');
    const subtitle = document.getElementById('web-radios-subtitle');
    if (!grid) return;
    try {
        const response = await fetch('/api/radios');
        const data = await response.json();
        const radios = data.radios || [];
        grid.innerHTML = '';

        if (subtitle) {
            subtitle.innerText = `${radios.length} ${radios.length === 1 ? 'stazione' : 'stazioni'} in streaming live`;
        }

        if (radios.length === 0) {
            grid.innerHTML = '<div class="empty-state-text" style="grid-column: 1/-1;">Nessuna stazione web radio presente.</div>';
            return;
        }

        radios.forEach(radio => {
            const card = document.createElement('div');
            card.className = 'radio-card';
            card.dataset.radioId = radio.id;

            const initials = stationInitials(radio.name);
            const logoUrl = radio.logo || DEFAULT_RADIO_LOGO;
            const logoFailed = !radio.logo;
            const deleteBtn = radio.id > 10
                ? `<button class="btn btn-secondary btn-sm btn-del-radio" title="Elimina"><i class="fa-solid fa-trash"></i></button>`
                : '';

            card.innerHTML = `
                <div class="radio-card-top">
                    <div class="radio-logo ${logoFailed ? 'logo-failed' : ''}">
                        <img class="radio-logo-img" src="${escapeAttr(logoUrl)}" alt="${escapeAttr(radio.name)}" loading="lazy">
                        <div class="radio-logo-fallback" aria-hidden="true">${escapeHtml(initials)}</div>
                    </div>
                    <div class="radio-card-head">
                        <div class="radio-name truncate">${escapeHtml(radio.name)}</div>
                        <div class="radio-genre truncate">${escapeHtml(radio.genre || 'Web Radio')}</div>
                    </div>
                </div>
                <div class="radio-onair">
                    <span class="radio-live"><i class="fa-solid fa-circle blink"></i> IN ONDA</span>
                    <span class="radio-program truncate">Caricamento...</span>
                </div>
                <div class="radio-card-actions">
                    <button class="btn btn-secondary btn-info-radio" title="Info & Palinsesto"><i class="fa-solid fa-circle-info"></i> Info</button>
                    <button class="btn btn-cyan btn-play-radio"><i class="fa-solid fa-play"></i> Ascolta live</button>
                    ${deleteBtn}
                </div>
            `;

            const logoImg = card.querySelector('.radio-logo-img');
            const logoBox = card.querySelector('.radio-logo');
            if (logoImg) {
                logoImg.addEventListener('error', () => logoBox.classList.add('logo-failed'));
            }

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
            loadRadioProgram(radio, card.querySelector('.radio-program'));
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
