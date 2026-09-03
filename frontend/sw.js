// ==================== ConcurseiroOS — Service Worker v6 ====================
const CACHE_VERSION = 'v216';
const CACHE_NAME = `concurseiro-${CACHE_VERSION}`;
const CDN_CACHE = `concurseiro-cdn-${CACHE_VERSION}`;
const RUNTIME_CACHE = `concurseiro-runtime-${CACHE_VERSION}`;

// App shell — precached on install
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/dashboard.html',
  '/questoes.html',
  '/viewer.html',
  '/login.html',
  '/social.html',
  '/mastery.html',
  '/raio-x.html',
  '/batalha.html',
  '/caderno-erros.html',
  '/simulado-cronometrado.html',
  '/studyroom.html',
  '/admin.html',
  '/catalogo.html',
  '/offline.html',
  '/css/main.css',
  '/js/app.js',
  '/js/modules/auth.js',
  '/js/modules/flashcards.js',
  '/js/modules/questoes.js',
  '/js/modules/sumulas.js',
  '/js/modules/utils.js',
  '/js/modules/theme.js',
  '/js/modules/api.js',
  '/js/modules/toast.js',
  '/js/modules/pdfs.js',
  '/js/modules/local-pdfs.js',
  '/js/modules/edital.js',
  '/js/modules/ciclo.js',
  '/js/modules/trilha.js',
  '/js/modules/metas.js',
  '/js/modules/modal-selecao.js',
  '/js/modules/vincular-pdf.js',
  '/js/modules/ui.js',
  '/js/modules/export-import.js',
  '/js/modules/tabs.js',
  '/js/modules/shortcuts.js',
  '/js/modules/state.js',
  '/js/modules/presence.js',
  '/js/modules/markdown.js',
  '/js/pages/index.js',
  '/js/pages/dashboard/main.js',
  '/js/pages/dashboard/gamification.js',
  '/js/pages/dashboard/treinador.js',
  '/manifest.json',
  '/icon.svg',
  '/icons/icon-192.svg',
  '/icons/icon-512.svg',
  '/timer-global.js',
  '/sidebar.js',
  '/ai-tutor-widget.js',
  '/auth-interceptor.js',
];

// CDN assets
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

async function replayFailedRequests(authToken) {
  const db = await openOfflineDB();
  const tx = db.transaction(STORE_NAME, 'readonly');
  const store = tx.objectStore(STORE_NAME);
  const items = await new Promise((resolve, reject) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  let replayed = 0;
  let discarded = 0;
  let remaining = 0;
  for (const item of items) {
    // Re-injeta o token ATUAL (o header salvo pode estar ausente/expirado se a
    // ação foi enfileirada sem login). Sem isso, o servidor recusa com 401 e o
    // item ficaria preso para sempre.
    const headers = { ...(item.headers || {}) };
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
      delete headers['authorization']; // evita header duplicado em minúsculo
    }
    try {
      const response = await fetch(item.url, {
        method: item.method,
        headers,
        body: item.method !== 'GET' ? item.body : undefined
      });
      if (response.ok) {
        const delTx = db.transaction(STORE_NAME, 'readwrite');
        delTx.objectStore(STORE_NAME).delete(item.id);
        replayed++;
      } else if (response.status >= 400 && response.status < 500) {
        // Erro de cliente (401/403/404/422...): reenviar de novo nunca vai
        // resolver — descarta o item para não travar a fila indefinidamente.
        const delTx = db.transaction(STORE_NAME, 'readwrite');
        delTx.objectStore(STORE_NAME).delete(item.id);
        discarded++;
        console.warn(`[SW] Descartada mutation ${item.method} ${item.url} — HTTP ${response.status}`);
      } else {
        // 5xx: erro temporário do servidor — mantém na fila para nova tentativa.
        remaining++;
      }
    } catch (e) {
      // Erro de rede: ainda offline, para o loop e mantém o restante na fila.
      remaining += 1;
      break;
    }
  }

  // Notify clients
  const clients = await self.clients.matchAll();
  clients.forEach(client => {
    client.postMessage({
      type: 'SYNC_COMPLETE',
      replayed,
      discarded,
      pending: Math.max(0, items.length - replayed - discarded)
    });
  });

  console.log(`[SW] Replay: ${replayed} enviadas, ${discarded} descartadas (4xx), ${items.length - replayed - discarded} pendentes`);
  return { replayed, discarded, pending: items.length - replayed - discarded };
}

// ===== INSTALL: precache app shell =====
self.addEventListener('install', (event) => {
  console.log(`[SW] Installing ${CACHE_NAME}`);
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => caches.open(CDN_CACHE))
      .then(cache => Promise.allSettled(CDN_URLS.map(url => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

// ===== ACTIVATE: clean old caches =====
self.addEventListener('activate', (event) => {
  console.log(`[SW] Activating ${CACHE_NAME}`);
  const currentCaches = [CACHE_NAME, CDN_CACHE, RUNTIME_CACHE];
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(key => !currentCaches.includes(key))
          .map(key => {
            console.log(`[SW] Deleting old cache: ${key}`);
            return caches.delete(key);
          })
      ))
      .then(() => self.clients.claim())
  );
});

// ===== FETCH: multi-strategy =====
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-http(s) requests
  if (!url.protocol.startsWith('http')) return;

  // --- API mutation (POST/PUT/DELETE): Network with offline queue ---
  if (url.pathname.startsWith('/api/') && ['POST', 'PUT', 'DELETE', 'PATCH'].includes(request.method)) {
    event.respondWith(networkWithOfflineQueue(request));
    return;
  }

  // --- API GET: Network-first, fall back to cache ---
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request));
    return;
  }

  // --- CDN assets: Cache-first ---
  if (url.hostname !== location.hostname) {
    event.respondWith(cacheFirst(request, CDN_CACHE));
    return;
  }

  // --- JS/CSS da própria app: Stale-while-revalidate ---
  // cache-first prendia versões antigas de scripts (ex.: novas funções não
  // apareciam ate trocar de CACHE_NAME). SWR serve rapido do cache mas busca a
  // versao nova em background, entregando-a no proximo load.
  if (/\.(css|js|mjs)$/i.test(url.pathname) && !url.pathname.startsWith('/pdfjs/')) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  // --- Demais assets estáticos imutáveis (imagens, fontes, PDF.js): Cache-first ---
  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(request, CACHE_NAME));
    return;
  }

  // --- HTML navigation: Stale-while-revalidate with offline fallback ---
  if (request.mode === 'navigate' || request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(staleWhileRevalidateWithOfflineFallback(request));
    return;
  }

  // --- Everything else: Stale-while-revalidate ---
  event.respondWith(staleWhileRevalidate(request));
});

// ===== FETCH STRATEGIES =====

// Network-first: try network, fall back to cache
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok && request.method === 'GET') {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ detail: 'Offline — sem conexão com o servidor' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

// Cache-first: check cache, fall back to network
async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    // Return a basic offline response for missing static assets
    return new Response('', { status: 503, statusText: 'Offline' });
  }
}

// Stale-while-revalidate: return cache immediately, update in background
async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  const networkPromise = fetch(request)
    .then(response => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => cached);

  return cached || await networkPromise;
}

// Stale-while-revalidate for HTML with offline fallback
async function staleWhileRevalidateWithOfflineFallback(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  const networkPromise = fetch(request)
    .then(response => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(async () => {
      // Network failed — return cached version or offline page
      if (cached) return cached;
      return await caches.match('/offline.html');
    });

  // If we have a cached version, return it immediately and revalidate in background
  if (cached) {
    // Fire and forget: update cache in background
    networkPromise.catch(() => {});
    return cached;
  }

  // No cache — must wait for network
  return await networkPromise;
}

// Network with offline queue for mutations
async function networkWithOfflineQueue(request) {
  try {
    const response = await fetch(request.clone());
    return response;
  } catch (err) {
    await queueMutation(request);
    // Register background sync
    if (self.registration.sync) {
      try {
        await self.registration.sync.register('sync-mutations');
      } catch (e) {
        console.log('[SW] Background sync registration failed:', e);
      }
    }
    return new Response(JSON.stringify({
      ok: true,
      queued: true,
      message: 'Salvo offline — será sincronizado quando conectar'
    }), {
      status: 202,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

// ===== HELPERS =====
function isStaticAsset(pathname) {
  return /\.(css|js|svg|png|jpg|jpeg|gif|webp|ico|woff|woff2|ttf|eot|json)$/i.test(pathname) ||
    pathname.startsWith('/icons/') ||
    pathname.startsWith('/pdfjs/');
}

// ===== BACKGROUND SYNC =====
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-mutations' || event.tag === 'sync-study-sessions') {
    event.waitUntil(replayFailedRequests());
  }
});

// ===== PERIODIC BACKGROUND SYNC (for refreshing cached data) =====
self.addEventListener('periodicsync', (event) => {
  if (event.tag === 'refresh-dashboard') {
    event.waitUntil(
      fetch('/api/dashboard/stats')
        .then(response => {
          if (response.ok) {
            return caches.open(RUNTIME_CACHE).then(cache => cache.put('/api/dashboard/stats', response));
          }
        })
        .catch(() => {})
    );
  }
});

// ===== PUSH NOTIFICATIONS =====
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || 'ConcurseiroOS';
  const options = {
    body: data.body || '',
    icon: '/icons/icon-192.svg',
    badge: '/icons/icon-192.svg',
    tag: data.tag || 'default',
    data: { url: data.url || '/' },
    actions: data.actions || [],
    requireInteraction: data.requireInteraction || false,
    vibrate: [200, 100, 200]
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const action = event.action;
  const url = event.notification.data?.url || '/';

  // Handle notification actions
  let targetUrl = url;
  if (action === 'open-flashcards') targetUrl = '/#tab-flashcards';
  else if (action === 'open-questoes') targetUrl = '/questoes.html';
  else if (action === 'open-dashboard') targetUrl = '/dashboard.html';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      // Try to focus existing window
      for (const client of windowClients) {
        if (client.url.includes(targetUrl) && 'focus' in client) {
          return client.focus();
        }
      }
      // Open new window
      return clients.openWindow(targetUrl);
    })
  );
});

// ===== MESSAGE HANDLER =====
self.addEventListener('message', (event) => {
  const { type } = event.data || {};

  switch (type) {
    case 'GET_PENDING_COUNT':
      openOfflineDB().then(db => {
        const tx = db.transaction(STORE_NAME, 'readonly');
        const req = tx.objectStore(STORE_NAME).count();
        req.onsuccess = () => {
          event.source.postMessage({ type: 'PENDING_COUNT', count: req.result });
        };
      });
      break;

    case 'FORCE_SYNC':
      // Disparado pelo botão "Sincronizar agora" — reenvia a fila usando o
      // token atual do cliente (resolve itens enfileirados sem login).
      replayFailedRequests(event.data?.token).then(result => {
        event.source.postMessage({ type: 'FORCE_SYNC_DONE', ...result });
      });
      break;

    case 'SKIP_WAITING':
      self.skipWaiting();
      break;

    case 'GET_CACHE_STATS':
      getCacheStats().then(stats => {
        event.source.postMessage({ type: 'CACHE_STATS', stats });
      });
      break;

    case 'CLEAR_RUNTIME_CACHE':
      caches.delete(RUNTIME_CACHE).then(() => {
        event.source.postMessage({ type: 'CACHE_CLEARED' });
      });
      break;
  }
});

// Get cache statistics for offline page
async function getCacheStats() {
  const stats = { pages: 0, assets: 0, apiResponses: 0, totalSize: 0 };
  try {
    const cacheNames = await caches.keys();
    for (const name of cacheNames) {
      const cache = await caches.open(name);
      const keys = await cache.keys();
      for (const request of keys) {
        const url = new URL(request.url);
        if (url.pathname.endsWith('.html') || url.pathname === '/') stats.pages++;
        else if (url.pathname.startsWith('/api/')) stats.apiResponses++;
        else stats.assets++;
      }
    }
  } catch (e) {
    console.error('[SW] Error getting cache stats:', e);
  }
  return stats;
}
