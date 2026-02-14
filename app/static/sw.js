const CACHE_NAME = 'saas-sender-v2'; // Bumped version
const ASSETS = [
    '/manifest.json',
    '/static/img/icon.svg',
    '/static/dist/styles.css'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // 1. For Navigation (HTML) requests, use Network First
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    // Update cache for offline use, but mostly rely on the fresh network response
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseClone);
                    });
                    return response;
                })
                .catch(() => {
                    // If network fails (offline), try cache
                    return caches.match(event.request);
                })
        );
        return;
    }

    // 2. For static assets in ASSETS, use Cache First
    if (ASSETS.includes(url.pathname) || url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(event.request).then((response) => {
                return response || fetch(event.request);
            })
        );
        return;
    }

    // 3. Default: Network only or whatever
    event.respondWith(fetch(event.request));
});

