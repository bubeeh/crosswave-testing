// Home Dashboard View Module for CrossWave Hybrid (Clean Link Cards Launcher)
import { state } from '../core/state.js';
import { showToast, escapeHtml } from '../core/utils.js';
import { navigate } from '../core/router.js';
import { executeSearch } from './search.js';
import { loadHomeMixRandom } from './mixrandom.js';

export async function loadHomeDashboard() {
    initHomeSearch();
    bindNavLinkCards();
    updateHomeBadges();
    loadHomeMixRandom();
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
    // Playlists count badge
    const playlistPill = document.getElementById('home-playlist-count-pill');
    if (playlistPill) {
        const count = Object.keys(state.playlists || {}).length;
        playlistPill.innerText = `${count} raccolte`;
    }
}
