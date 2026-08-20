const CACHE_NAME = 'concurseiro-v4';
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/dashboard.html',
  '/questoes.html',
  '/viewer.html',
  '/login.html',
  '/styles.css',
  '/js/app.js',
  '/js/modules/auth.js',
  '/js/modules/flashcards.js',
  '/js/modules/questoes.js',
  '/js/modules/sumulas.js',
  '/manifest.json',
  '/icon.svg',
  '/timer-global.js',
  '/app.js',
];

// CDN assets to cache (Chart.js etc.)
const CDN_CACHE = 'concurseiro-cdn-v1';
const CDN_URLS = [
  'https://cdn.jsdelivr.net/npm/chart.js',
];

// Install: precache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS);
    }).then(() => {
      return caches.open(CDN_CACHE).then((cache) => {
        return Promise.allSettled(CDN_URLS.map(url => cache.add(url)));
      });
    })
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  const allowedCaches = [CACHE_NAME, CDN_CACHE];
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => !allowedCaches.includes(k)).map((k) => caches.delete(k))
      );
    })
  );
  self.clients.claim();
});

// Fetch: different strategies per request type
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API requests: Network-first, no cache (data must be fresh)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        // If offline and it's a GET, return a cached response if available
        if (event.request.method === 'GET') {
          return caches.match(event.request);
        }
        return new Response(JSON.stringify({ detail: 'Offline — sem conexão com o servidor' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        });
      })
    );
    return;
  }

  // CDN assets: Cache-first (rarely change)
  if (url.hostname.includes('cdn.jsdelivr.net')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          const clone = response.clone();
          caches.open(CDN_CACHE).then((cache) => cache.put(event.request, clone));
          return response;
        });
      })
    );
    return;
  }

  // PDF files: Cache-first (large, rarely change)
  if (url.pathname.endsWith('.pdf')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        });
      })
    );
    return;
  }

  // Static assets: Stale-while-revalidate (fast + fresh)
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((response) => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => cached);

      return cached || fetchPromise;
    })
  );
});

// Background sync: queue failed POST requests for retry
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-study-sessions') {
    event.waitUntil(replayFailedRequests());
  }
});

async function replayFailedRequests() {
  // Future: replay queued study sessions when back online
  // For now, just log
  console.log('[SW] Background sync triggered');
}
