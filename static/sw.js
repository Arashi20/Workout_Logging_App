// Service Worker for AMStrength Workout Logger PWA
//
// Strategy: network-first for everything, with the cache used purely as an
// offline safety net. The app is server-rendered, so a cached page would show
// stale training data -- we never serve one while the network is reachable.
//
// Served from /sw.js (not /static/sw.js) so its scope covers the whole app.
// A worker's default scope is its own directory, so a worker under /static/
// can only ever control /static/ pages -- which means none of this app's.
const VERSION = 'v2';
const CACHE_NAME = `amstrength-${VERSION}`;
const OFFLINE_URL = '/offline';

// Only assets that are identical for every user. Never precache an
// authenticated page -- it would put one user's data in the cache.
const PRECACHE_URLS = [
  OFFLINE_URL,
  '/static/css/style.css',
  '/static/icon-192x192.png',
  '/static/icon-512x512.png'
];

// Install - cache the offline page and core static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      // Don't wait for every open tab to close before taking over.
      .then(() => self.skipWaiting())
  );
});

// Activate - drop caches from previous versions, then take control
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names.filter((name) => name !== CACHE_NAME)
             .map((name) => caches.delete(name))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // Never intercept anything that changes data. Logging a set is a POST, and
  // a replayed POST would duplicate it -- so those always go straight to the
  // network, untouched.
  if (request.method !== 'GET') return;

  // Leave cross-origin requests (e.g. the Chart.js CDN) to the browser.
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Page navigations: always fetch fresh; show the offline page only if the
  // network genuinely fails.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }

  // Static assets: still network-first so a deploy is picked up immediately,
  // falling back to the cached copy only when offline.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Only store complete, successful responses.
          if (response && response.ok && response.type === 'basic') {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
  }

  // Everything else falls through to normal browser handling.
});
