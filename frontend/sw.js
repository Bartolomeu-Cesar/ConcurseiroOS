const CACHE_NAME = 'concurseiro-v5';
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/dashboard.html',
  '/questoes.html',
  '/viewer.html',
  '/login.html',
  '/styles.css',
  '/layout.css',
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

// ===== OFFLINE MUTATION QUEUE (IndexedDB) =====
const DB_NAME = 'concurseiro-offline';
const STORE_NAME = 'pending-mutations';

function openOfflineDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function queueMutation(request) {
  const db = await openOfflineDB();
  const tx = db.transaction(STORE_NAME, 'readwrite');
  const store = tx.objectStore(STORE_NAME);
  const body = await request.clone().text();
  store.add({
    url: request.url,
    method: request.method,
    headers: Object.fromEntries(request.headers.entries()),
    body: body,
    timestamp: Date.now()
  });
  return new Promise((resolve, reject) => {
    tx.oncomplete = resolve;
    tx.onerror = reject;
  });
}

async function replayFailedRequests() {
  const db = await openOfflineDB();
  const tx = db.transaction(STORE_NAME, 'readonly');
  const store = tx.objectStore(STORE_NAME);
  const items = await new Promise((resolve, reject) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  let replayed = 0;
  for (const item of items) {
    try {
      const response = await fetch(item.url, {
        method: item.method,
        headers: item.headers,
        body: item.method !== 'GET' ? item.body : undefined
      });
      if (response.ok) {
        // Remove from queue
        const delTx = db.transaction(STORE_NAME, 'readwrite');
        delTx.objectStore(STORE_NAME).delete(item.id);
        replayed++;
      }
    } catch (e) {
      // Still offline, stop trying
      break;
    }
  }

  // Notify clients about sync result
  const clients = await self.clients.matchAll();
  clients.forEach(client => {
    client.postMessage({ type: 'SYNC_COMPLETE', replayed, pending: items.length - replayed });
  });

  console.log(`[SW] Replayed ${replayed}/${items.length} queued mutations`);
}

// ===== INSTALL: precache static assets =====
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

// ===== ACTIVATE: clean old caches =====
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

// ===== FETCH: different strategies per request type =====
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API mutation requests (POST/PUT/DELETE): Network with offline queue fallback
  if (url.pathname.startsWith('/api/') && ['POST', 'PUT', 'DELETE'].includes(event.request.method)) {
    event.respondWith(
      fetch(event.request.clone()).catch(async (err) => {
        await queueMutation(event.request);
        // Register for background sync
        if (self.registration.sync) {
          await self.registration.sync.register('sync-study-sessions');
        }
        return new Response(JSON.stringify({ ok: true, queued: true, message: 'Salvo offline - será sincronizado quando conectar' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      })
    );
    return;
  }

  // API GET requests: Network-first, fallback to cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => {
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

// ===== BACKGROUND SYNC =====
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-study-sessions') {
    event.waitUntil(replayFailedRequests());
  }
});

// ===== PUSH NOTIFICATIONS =====
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || 'ConcurseiroOS';
  const options = {
    body: data.body || '',
    icon: '/icon-192.png',
    badge: '/icon-72.png',
    tag: data.tag || 'default',
    data: { url: data.url || '/' },
    actions: data.actions || [],
    requireInteraction: data.requireInteraction || false
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window' }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url.includes(url) && 'focus' in client) return client.focus();
      }
      return clients.openWindow(url);
    })
  );
});

// ===== MESSAGE HANDLER (pending count) =====
self.addEventListener('message', (event) => {
  if (event.data?.type === 'GET_PENDING_COUNT') {
    openOfflineDB().then(db => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const req = tx.objectStore(STORE_NAME).count();
      req.onsuccess = () => {
        event.source.postMessage({ type: 'PENDING_COUNT', count: req.result });
      };
    });
  }
});
