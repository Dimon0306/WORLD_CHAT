// app/static/sw.js
const CACHE_NAME = 'secure-chat-v1';
const STATIC_ASSETS = [
  '/',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png'
];

// Установка: кэшируем статику
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Активация: чистим старый кэш
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(names => 
      Promise.all(names.filter(n => n !== CACHE_NAME).map(n => caches.delete(n)))
    )
  );
  self.clients.claim();
});

// Перехват запросов: кэш для статики, сеть для всего остального
self.addEventListener('fetch', (event) => {
  // Не кэшируем API, WebSocket, динамические запросы
  if (event.request.url.includes('/api/') || 
      event.request.url.includes('/ws') ||
      event.request.method !== 'GET') {
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      
      return fetch(event.request).then(response => {
        if (!response || response.status !== 200) return response;
        
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        return response;
      });
    })
  );
});
