const CACHE_NAME = 'saas-sender-v1';

self.addEventListener('install', (event) => {
    // Perform install steps
});

self.addEventListener('fetch', (event) => {
    // Simple pass-through for now
    event.respondWith(fetch(event.request));
});
