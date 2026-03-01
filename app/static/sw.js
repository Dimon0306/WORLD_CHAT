// app/static/sw.js
const CACHE_NAME = 'secure-chat-v2'; // ← Версия для сброса кэша

const STATIC_ASSETS = [
  '/',
  '/static/icons/qwe.png',
  '/static/manifest.json'
];

// === Установка Service Worker ===
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
      .catch(err => console.error('❌ SW install error:', err))
  );
});

// === Активация: очистка старого кэша ===
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(names => 
      Promise.all(
        names.filter(name => name !== CACHE_NAME)
          .map(name => caches.delete(name))
      )
    )
  );
  self.clients.claim();
});

// === Перехват запросов ===
self.addEventListener('fetch', (event) => {
  // Не кэшируем API, WebSocket, POST-запросы
  if (event.request.url.includes('/api/') || 
      event.request.url.includes('/ws') ||
      event.request.method !== 'GET') {
    return;
  }

  event.respondWith(
    caches.match(event.request)
      .then(cached => {
        if (cached) return cached;
        
        return fetch(event.request)
          .then(response => {
            if (!response || response.status !== 200 || response.type !== 'basic') {
              return response;
            }
            
            const clone = response.clone();
            caches.open(CACHE_NAME)
              .then(cache => cache.put(event.request, clone))
              .catch(err => console.error('❌ SW cache error:', err));
            
            return response;
          })
          .catch(err => {
            console.error('❌ SW fetch error:', err);
            return caches.match('/'); // Fallback на главную
          });
      })
      .catch(err => {
        console.error('❌ SW match error:', err);
      })
  );
}); 
