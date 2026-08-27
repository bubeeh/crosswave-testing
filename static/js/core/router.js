// Core Router with Tab Registry & Hash Navigation for CrossWave Hybrid

const tabRegistry = {}; // tabId -> { onEnter, onLeave }

export function registerTab(tabId, handlers) {
    tabRegistry[tabId] = handlers;
}

const HASH_MAP = {
    'home': '#/home',
    'search': '#/search',
    'downloads': '#/downloads',
    'web-radio': '#/web-radio',
    'mix-random': '#/mix-random',
    'playlists': '#/playlists',
    'telegram': '#/telegram',
    'queue-history': '#/queue-history',
};

const REVERSE_HASH_MAP = {};
Object.keys(HASH_MAP).forEach(k => {
    REVERSE_HASH_MAP[HASH_MAP[k]] = k;
});

let currentTabId = null;

export function switchTab(tabId) {
    if (currentTabId && tabRegistry[currentTabId] && tabRegistry[currentTabId].onLeave) {
        try {
            tabRegistry[currentTabId].onLeave();
        } catch (e) {
            console.error(`Error in onLeave for tab ${currentTabId}:`, e);
        }
    }

    document.querySelectorAll('.tab-content').forEach(section => {
        section.classList.remove('active');
    });

    const targetTab = document.getElementById(`tab-${tabId}`);
    if (targetTab) {
        targetTab.classList.add('active');
    }

    currentTabId = tabId;

    if (tabRegistry[tabId] && tabRegistry[tabId].onEnter) {
        try {
            tabRegistry[tabId].onEnter();
        } catch (e) {
            console.error(`Error in onEnter for tab ${tabId}:`, e);
        }
    } else {
        if (tabRegistry['downloads'] && tabRegistry['downloads'].onLeave) {
            tabRegistry['downloads'].onLeave();
        }
    }

    // Sync active class on nav-btn elements
    document.querySelectorAll('.nav-btn').forEach(btn => {
        const btnTab = btn.getAttribute('data-tab');
        if (btnTab === tabId) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

export function navigate(tabId) {
    if (HASH_MAP[tabId]) {
        if (window.location.hash !== HASH_MAP[tabId]) {
            window.location.hash = HASH_MAP[tabId];
        } else {
            switchTab(tabId);
        }
    } else {
        switchTab(tabId);
    }
}

if (typeof window !== 'undefined') {
    window.switchTab = switchTab;
    window.navigate = navigate;
}

export function initRouter() {
    // Unica delegazione globale per nav-btn, data-target e logo
    document.addEventListener('click', (e) => {
        const navBtn = e.target.closest('.nav-btn');
        if (navBtn) {
            const tabId = navBtn.getAttribute('data-tab');
            if (tabId) {
                e.preventDefault();
                navigate(tabId);
                return;
            }
        }

        const linkCard = e.target.closest('[data-target]');
        if (linkCard) {
            const targetTab = linkCard.getAttribute('data-target');
            if (targetTab) {
                e.preventDefault();
                navigate(targetTab);
                return;
            }
        }

        const headerLogo = e.target.closest('#header-logo-home');
        if (headerLogo) {
            e.preventDefault();
            navigate('home');
            return;
        }
    });

    window.addEventListener('hashchange', () => {
        const hash = window.location.hash;
        const tabId = REVERSE_HASH_MAP[hash] || 'home';
        switchTab(tabId);
    });

    const initialHash = window.location.hash;
    const initialTabId = REVERSE_HASH_MAP[initialHash] || 'home';
    switchTab(initialTabId);
}
