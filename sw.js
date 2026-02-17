const CACHE_NAME = 'garden-cache-v4';
const ASSETS = [
  '/',
  '/index.html',
  '/archivio.html',
  '/manifest.json',
  '/css/style.css',
  '/js/theme.js',
  '/js/seer.js',
  '/js/imagesloaded.js',
  '/js/masonry.js',
  '/js/settings.js',
  '/js/util.js',
  '/js/grid.js',
  '/js/nav.js',
  '/js/wrap.js',
  '/js/add.js',
  '/js/main.js',
  '/js/lightbox.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') {
    return;
  }

  const requestUrl = new URL(event.request.url);
  if (requestUrl.origin !== self.location.origin) {
    return;
  }

  const isCriticalAsset =
    event.request.mode === 'navigate' ||
    requestUrl.pathname.endsWith('.html') ||
    requestUrl.pathname.endsWith('.css') ||
    requestUrl.pathname.endsWith('.js') ||
    requestUrl.pathname.endsWith('.json');

  if (!isCriticalAsset) {
    event.respondWith(
      caches.match(event.request).then(response => response || fetch(event.request))
    );
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response && response.status === 200) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() =>
        caches.match(event.request).then(response => {
          if (response) {
            return response;
          }
          if (event.request.mode === 'navigate') {
            return caches.match('/index.html');
          }
          return Response.error();
        })
      )
  );
});
