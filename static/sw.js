// Service Worker for AMStrength Workout Logger PWA
const CACHE_NAME = 'amstrength-v1';
const urlsToCache = [
  '/',
  '/static/css/style.css',
  '/static/icon-192x192.png',
  '/static/icon-512x512.png'
];

// Install event - cache key resources
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        return cache.addAll(urlsToCache);
      })
  );
});

// Fetch event - serve from cache, update cache with network response
self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.match(event.request).then((response) => {
        // Fetch from network and update cache
        const fetchPromise = fetch(event.request).then((networkResponse) => {
          // Update cache with new response
          cache.put(event.request, networkResponse.clone());
          return networkResponse;
        });
        
        // Return cached version immediately, or wait for network
        return response || fetchPromise;
      });
    })
  );
});

// Activate event - clean up old caches
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
