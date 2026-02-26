const CACHE_NAME = 'tictactoe-v1';
const ASSETS = [
    '/',
    '/static/icons/Снимок.png',
    // Добавьте сюда пути к вашим CSS файлам, если они отдельные
    // '/static/css/style.css' 
];

// Установка: кэшируем файлы
self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
    );
});

// Активация: чистим старый кэш
self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)));
        })
    );
});

// Перехват запросов: отдаем из кэша, если нет сети
self.addEventListener('fetch', (e) => {
    e.respondWith(
        caches.match(e.request).then((response) => response || fetch(e.request))
    );
});