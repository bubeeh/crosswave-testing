// Helper Utilities for CrossWave Hybrid

// Placeholder LOCALE (servito dall'app, cacheato dal Service Worker).
// Mai usare un URL remoto come fallback di sé stesso: se il fallback fallisce,
// l'onerror si riattiverebbe in loop generando richieste infinite.
export const PLACEHOLDER_COVER = '/static/icons/placeholder.svg';

// Carica uno script esterno una sola volta (SDK lazy) e ne attende il load.
const _scriptPromises = {};
export function loadScriptOnce(url, globalName) {
    if (globalName && window[globalName]) return Promise.resolve();
    if (_scriptPromises[url]) return _scriptPromises[url];
    _scriptPromises[url] = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = url;
        s.async = true;
        s.onload = () => resolve();
        s.onerror = () => {
            delete _scriptPromises[url];
            reject(new Error('Impossibile caricare ' + url));
        };
        document.head.appendChild(s);
    });
    return _scriptPromises[url];
}

// Riconosce l'id nativo di un video YouTube dall'URL.
export function youtubeVideoId(url) {
    const m = String(url || '').match(/[?&]v=([\w-]+)/);
    return m ? m[1] : '';
}

// True se l'URL è una raccolta (album Bandcamp, playlist YouTube, set SoundCloud).
export function isCollectionUrl(platform, url) {
    const u = String(url || '');
    if (platform === 'bandcamp') return u.includes('/album/');
    if (platform === 'youtube') return u.includes('/playlist');
    if (platform === 'soundcloud') return u.includes('/sets/');
    return false;
}

export function escapeHtml(text) {
    if (!text) return '';
    return text
        .toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

export function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type === 'error' ? 'toast-error' : 'toast-success'}`;

    let iconClass = 'fa-solid fa-circle-check';
    if (type === 'error') iconClass = 'fa-solid fa-circle-exclamation';

    toast.innerHTML = `<i class="${iconClass}"></i> <span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 5000);
}

export function formatTime(seconds) {
    if (isNaN(seconds) || seconds === null || seconds < 0) return '0:00';

    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.floor(seconds % 60);

    return `${minutes}:${remainingSeconds < 10 ? '0' : ''}${remainingSeconds}`;
}

export function calculateTotalDuration(tracks) {
    if (!tracks || tracks.length === 0) return '0 min';
    const totalSec = tracks.reduce((sum, t) => sum + (t.duration || 0), 0);

    if (totalSec < 60) return `${Math.floor(totalSec)} sec`;

    const min = Math.round(totalSec / 60);
    return `${min} min`;
}

export function getPlatformGradient(source) {
    if (source === 'youtube') return 'radial-gradient(circle, rgba(255, 0, 0, 0.4) 0%, rgba(0,0,0,0) 70%)';
    if (source === 'soundcloud') return 'radial-gradient(circle, rgba(255, 85, 0, 0.4) 0%, rgba(0,0,0,0) 70%)';
    if (source === 'bandcamp') return 'radial-gradient(circle, rgba(30, 160, 196, 0.4) 0%, rgba(0,0,0,0) 70%)';
    if (source === 'mixcloud') return 'radial-gradient(circle, rgba(80, 0, 255, 0.4) 0%, rgba(0,0,0,0) 70%)';
    return 'none';
}
