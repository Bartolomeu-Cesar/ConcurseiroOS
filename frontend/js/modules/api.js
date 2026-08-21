/**
 * API Fetch Wrapper Module
 * 
 * Unified fetch wrapper with:
 * - Automatic auth token injection (Bearer from localStorage)
 * - Timeout with AbortController
 * - Retry logic with exponential backoff
 * - Offline detection & banner
 * - Error toast notifications (optional, requires toast module)
 * 
 * Usage:
 *   import { api, apiFetch } from './modules/api.js';
 *   const data = await api('/api/edital');
 *   const result = await api('/api/sessions', { method: 'POST', body: { duration: 30 } });
 */

// ==================== STATE ====================
let isOffline = false;
let toastFn = null;

/**
 * Set the toast function for error reporting.
 * Call this once after importing both modules:
 *   import { toast } from './modules/toast.js';
 *   import { setToastHandler } from './modules/api.js';
 *   setToastHandler(toast);
 * 
 * @param {function} fn - The toast function to use for error notifications
 */
export function setToastHandler(fn) {
  toastFn = fn;
}

function notify(message, type = 'error') {
  if (toastFn) toastFn(message, type);
  else console.warn(`[API] ${type}: ${message}`);
}

// ==================== OFFLINE BANNER ====================
function showOfflineBanner() {
  if (document.getElementById('offline-banner')) return;
  const banner = document.createElement('div');
  banner.id = 'offline-banner';
  banner.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#f38ba8;color:#1e1e2e;text-align:center;padding:8px;font-size:0.85rem;font-weight:600;z-index:100000;';
  banner.textContent = '⚠️ Sem conexão com o servidor. Algumas funções podem não funcionar.';
  document.body.prepend(banner);
}

function hideOfflineBanner() {
  const b = document.getElementById('offline-banner');
  if (b) b.remove();
}

// ==================== ONLINE/OFFLINE LISTENERS ====================
/**
 * Initialize offline/online event listeners.
 * Call once on page load to enable automatic offline detection.
 */
export function initOfflineListeners() {
  window.addEventListener('online', () => {
    isOffline = false;
    hideOfflineBanner();
    notify('Conexão restaurada!', 'success');
  });
  window.addEventListener('offline', () => {
    isOffline = true;
    showOfflineBanner();
    notify('Você está offline', 'warning');
  });
}

// ==================== CORE API FUNCTION ====================
/**
 * Fetch wrapper with auth token, retries, timeout, and error handling.
 * 
 * @param {string} url - The URL to fetch
 * @param {object} options - Options
 * @param {string} options.method - HTTP method (default: 'GET')
 * @param {object|null} options.body - Request body (will be JSON.stringify'd)
 * @param {number} options.retries - Number of retry attempts (default: 2)
 * @param {number} options.timeout - Timeout in ms (default: 10000)
 * @param {object} options.headers - Additional headers to merge
 * @param {boolean} options.raw - If true, return the Response object instead of parsing JSON
 * @returns {Promise<any>} Parsed JSON response (or Response if raw: true)
 */
export async function api(url, options = {}) {
  const { method = 'GET', body = null, retries = 2, timeout = 10000, headers = {}, raw = false } = options;
  const fetchOptions = { method, headers: { ...headers } };

  // Inject auth token
  const token = localStorage.getItem('auth_token');
  if (token && !fetchOptions.headers['Authorization'] && !fetchOptions.headers['authorization']) {
    fetchOptions.headers['Authorization'] = `Bearer ${token}`;
  }

  // JSON body
  if (body) {
    fetchOptions.headers['Content-Type'] = 'application/json';
    fetchOptions.body = JSON.stringify(body);
  }

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeout);
      fetchOptions.signal = controller.signal;

      const res = await fetch(url, fetchOptions);
      clearTimeout(timeoutId);

      // Restore online state
      if (isOffline) {
        isOffline = false;
        hideOfflineBanner();
      }

      if (raw) return res;

      if (!res.ok) {
        const errText = await res.text().catch(() => 'Erro desconhecido');
        throw new Error(`HTTP ${res.status}: ${errText}`);
      }

      return await res.json();
    } catch (err) {
      if (err.name === 'AbortError') {
        if (attempt === retries) {
          notify('Servidor demorou para responder', 'error');
          throw err;
        }
      } else if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
        isOffline = true;
        showOfflineBanner();
        if (attempt === retries) {
          notify('Sem conexão com servidor', 'error');
          throw err;
        }
      } else {
        if (attempt === retries) {
          notify(err.message || 'Erro ao comunicar com servidor', 'error');
          throw err;
        }
      }
      // Exponential backoff
      await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
    }
  }
}

/**
 * Simple fetch with auth token injection (no retries, no JSON parsing).
 * Drop-in replacement for pages that just need auth headers on fetch.
 * Returns the raw Response.
 * 
 * @param {string} url - The URL to fetch
 * @param {object} options - Standard fetch options
 * @returns {Promise<Response>}
 */
export function apiFetch(url, options = {}) {
  const token = localStorage.getItem('auth_token');
  if (token) {
    options = { ...options };
    options.headers = { ...(options.headers || {}) };
    if (!options.headers['Authorization'] && !options.headers['authorization']) {
      options.headers['Authorization'] = 'Bearer ' + token;
    }
  }
  return fetch(url, options);
}

/**
 * Check if currently offline.
 * @returns {boolean}
 */
export function getOfflineState() {
  return isOffline;
}

export default api;
