const CACHE_NAME = 'saas-sender-v4'; // Bumped to force sw refresh
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
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // IMPORTANT: Only handle same-origin requests.
    // Let the browser handle all cross-origin requests (fonts, APIs, external assets)
    // natively so they are subject to the HTML document's normal security rules
    // and don't get blocked by service-worker-inherited CSP.
    if (url.origin !== self.location.origin) {
        return; // Do NOT call event.respondWith() for cross-origin requests
    }

    // Skip non-GET requests (POST, PUT, DELETE etc.) — can't be cached
    if (event.request.method !== 'GET') {
        return;
    }

    // 1. For Navigation (HTML) requests, use Network First
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
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

    // 2. For same-origin static assets, use Cache First
    if (ASSETS.includes(url.pathname) || url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(event.request).then((response) => {
                return response || fetch(event.request);
            })
        );
        return;
    }

    // 3. All other same-origin requests: Network only
    // (API calls, etc. — don't cache these)
});
