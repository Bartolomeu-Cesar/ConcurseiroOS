// ==================== UTILS ====================
// escapeHtml, confirmModal, toast, loading states, fetch wrapper, undo

import { state } from './state.js';

// ==================== SECURITY: HTML SANITIZATION ====================
export function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ==================== MODAL DE CONFIRMAÇÃO ====================
export function confirmModal(title, message, { confirmText = 'Confirmar', cancelText = 'Cancelar', type = 'warning', icon = '⚠️' } = {}) {
  return new Promise((resolve) => {
    const colors = { warning: '#f9e2af', danger: '#f38ba8', info: '#89b4fa', success: '#a6e3a1' };
    const btnColors = { warning: '#f9e2af', danger: '#f38ba8', info: '#89b4fa', success: '#a6e3a1' };
    const overlay = document.createElement('div');
    overlay.id = 'confirm-modal-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.15s;';
    overlay.innerHTML = `<div style="background:#313244;border-radius:16px;padding:28px;max-width:400px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.5);border:1px solid #45475a;animation:scaleIn 0.15s;">
      <div style="text-align:center;margin-bottom:16px;">
        <div style="font-size:2.2rem;margin-bottom:8px;">${icon}</div>
        <h3 style="color:${colors[type]};margin-bottom:8px;font-size:1.1rem;">${title}</h3>
        <p style="font-size:0.85rem;color:#cdd6f4;line-height:1.5;">${message}</p>
      </div>
      <div style="display:flex;gap:10px;justify-content:center;">
        <button id="cm-cancel" style="background:#45475a;color:#cdd6f4;border:none;border-radius:8px;padding:10px 20px;font-size:0.88rem;cursor:pointer;font-weight:500;min-width:100px;">${cancelText}</button>
        <button id="cm-confirm" style="background:${btnColors[type]};color:#1e1e2e;border:none;border-radius:8px;padding:10px 20px;font-size:0.88rem;cursor:pointer;font-weight:700;min-width:100px;">${confirmText}</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#cm-confirm').onclick = () => { overlay.remove(); resolve(true); };
    overlay.querySelector('#cm-cancel').onclick = () => { overlay.remove(); resolve(false); };
    overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } });
    overlay.querySelector('#cm-cancel').focus();
  });
}

// ==================== TOAST NOTIFICATION SYSTEM ====================
const toastContainer = document.createElement('div');
toastContainer.id = 'toast-container';
document.body.appendChild(toastContainer);

export function toast(message, type = 'info', duration = 4000, action = null) {
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `
    <span class="toast-icon">${icons[type] || icons.info}</span>
    <span class="toast-msg">${message}</span>
    ${action ? `<button class="toast-action">${action.label}</button>` : ''}
    <button class="toast-close">×</button>
    <div class="toast-progress"><div class="toast-progress-bar"></div></div>
  `;
  toastContainer.appendChild(el);
  requestAnimationFrame(() => el.classList.add('toast-show'));
  if (action) {
    el.querySelector('.toast-action').onclick = () => { action.onClick(); removeToast(el); };
  }
  el.querySelector('.toast-close').onclick = () => removeToast(el);
  const bar = el.querySelector('.toast-progress-bar');
  bar.style.transition = `width ${duration}ms linear`;
  requestAnimationFrame(() => bar.style.width = '0%');
  const timer = setTimeout(() => removeToast(el), duration);
  el._timer = timer;
  return el;
}

export function removeToast(el) {
  if (!el || !el.parentNode) return;
  clearTimeout(el._timer);
  el.classList.add('toast-hide');
  setTimeout(() => el.remove(), 300);
}

// ==================== LOADING STATES ====================
export function showLoading(container) {
  if (typeof container === 'string') container = document.getElementById(container);
  if (!container) return;
  container.innerHTML = `<div class="skeleton-group">
    <div class="skeleton skeleton-line" style="width:80%"></div>
    <div class="skeleton skeleton-line" style="width:60%"></div>
    <div class="skeleton skeleton-line" style="width:70%"></div>
    <div class="skeleton skeleton-line" style="width:50%"></div>
  </div>`;
}

export function showSpinner(container) {
  if (typeof container === 'string') container = document.getElementById(container);
  if (!container) return;
  container.innerHTML = '<div class="spinner-wrapper"><div class="spinner"></div></div>';
}

export function showEmpty(container, icon = '📚', message = 'Nenhum item encontrado') {
  if (typeof container === 'string') container = document.getElementById(container);
  if (!container) return;
  container.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon}</div><div class="empty-msg">${message}</div></div>`;
}

// ==================== ERROR HANDLING & FETCH WRAPPER ====================
function showOfflineBanner() {
  if (document.getElementById('offline-banner')) return;
  const banner = document.createElement('div');
  banner.id = 'offline-banner';
  banner.innerHTML = '⚠️ Sem conexão com o servidor. Algumas funções podem não funcionar.';
  document.body.prepend(banner);
}

function hideOfflineBanner() {
  const b = document.getElementById('offline-banner');
  if (b) b.remove();
}

export function initOfflineListeners() {
  window.addEventListener('online', () => { state.isOffline = false; hideOfflineBanner(); toast('Conexão restaurada!', 'success', 3000); });
  window.addEventListener('offline', () => { state.isOffline = true; showOfflineBanner(); toast('Você está offline', 'warning', 5000); });
}

export async function api(url, options = {}) {
  const { method = 'GET', body = null, retries = 2, timeout = 10000 } = options;
  const fetchOptions = { method, headers: {} };
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
      if (state.isOffline) {
        state.isOffline = false;
        hideOfflineBanner();
      }
      if (!res.ok) {
        const errText = await res.text().catch(() => 'Erro desconhecido');
        throw new Error(`HTTP ${res.status}: ${errText}`);
      }
      return await res.json();
    } catch (err) {
      if (err.name === 'AbortError') {
        if (attempt === retries) {
          toast('Servidor demorou para responder', 'error');
          throw err;
        }
      } else if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
        state.isOffline = true;
        showOfflineBanner();
        if (attempt === retries) {
          toast('Sem conexão com servidor', 'error');
          throw err;
        }
      } else {
        if (attempt === retries) {
          toast(err.message || 'Erro ao comunicar com servidor', 'error');
          throw err;
        }
      }
      await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
    }
  }
}

// ==================== UNDO SYSTEM ====================
export function undoableDelete(itemDesc, deleteUrl, onComplete) {
  let cancelled = false;
  const toastEl = toast(`${itemDesc} excluído`, 'warning', 5000, {
    label: '↩ Desfazer',
    onClick: () => { cancelled = true; toast('Exclusão cancelada!', 'success', 2000); if (onComplete) onComplete(false); }
  });
  setTimeout(async () => {
    if (!cancelled) {
      try {
        await fetch(deleteUrl, { method: 'DELETE' });
        if (onComplete) onComplete(true);
      } catch (e) {
        toast('Erro ao excluir', 'error');
      }
    }
  }, 5200);
}

// ==================== HELPERS ====================
export function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

export function formatHours(h) {
  const hrs = Math.floor(h);
  const mins = Math.round((h - hrs) * 60);
  if (hrs === 0 && mins === 0) return '—';
  if (hrs === 0) return `${mins}m`;
  if (mins === 0) return `${hrs}h`;
  return `${hrs}h${mins}m`;
}
