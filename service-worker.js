const CACHE_NAME = 'polyglotvoice-cache-v1';
const urlsToCache = [
  '/',
  '/static/js/recorder.js',
  '/static/css/styles.css',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  '/static/icons/icon-144x144.png',
  '/static/icons/icon-96x96.png',
  '/static/icons/icon-72x72.png',
  '/static/icons/icon-48x48.png',
  '/static/img/robot.png',
  '/static/favicon.ico'
];

// Установка сервис-воркера и кэширование ресурсов
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        return cache.addAll(urlsToCache);
      })
  );
});

// Обслуживание запросов из кэша
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          return response;
        }
        return fetch(event.request);
      })
  );
});

// Обновление сервис-воркера
self.addEventListener('activate', event => {
  const cacheWhitelist = [CACHE_NAME];
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (!cacheWhitelist.includes(cacheName)) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});
