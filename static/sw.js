// CrossWave Player - minimal service worker (app shell + static asset cache)
const CACHE_VERSION = 'crosswave-v11';
const SHELL_ASSETS = [
    '/',
    '/static/css/style.css',
    '/static/js/app.js',
    '/static/manifest.webmanifest',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/static/icons/placeholder.svg'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_VERSION)
            .then((cache) => cache.addAll(SHELL_ASSETS).catch(() => undefined))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.map((k) => (k === CACHE_VERSION ? null : caches.delete(k)))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const req = event.request;
    if (req.method !== 'GET') return;

    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;
    // Never cache API traffic: always go to the network.
    if (url.pathname.startsWith('/api/')) return;

    // Navigations: network-first, fall back to cached shell when offline.
    if (req.mode === 'navigate') {
        event.respondWith(
            fetch(req)
                .then((res) => {
                    const copy = res.clone();
                    caches.open(CACHE_VERSION).then((cache) => cache.put('/', copy)).catch(() => undefined);
                    return res;
                })
                .catch(() => caches.match('/'))
        );
        return;
    }

    // Static assets: network-first (moduli JS/CSS sempre freschi quando online),
    // fallback alla cache solo offline. Evita che i moduli importati senza
    // query di versione restino serviti da una copia vecchia.
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            fetch(req)
                .then((res) => {
                    if (res && res.ok) {
                        const copy = res.clone();
                        caches.open(CACHE_VERSION).then((cache) => cache.put(req, copy)).catch(() => undefined);
                    }
                    return res;
                })
                .catch(() => caches.match(req, { ignoreSearch: true }))
        );
    }
});
