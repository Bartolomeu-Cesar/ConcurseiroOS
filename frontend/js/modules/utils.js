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

// ==================== MODAL ACCESSIBILITY HELPER ====================
// Aplica semântica de diálogo (role/aria-modal/aria-labelledby), trap de foco,
// fechamento com Esc e restauração do foco ao elemento anterior.
// `onClose(reason)` é chamado quando o usuário pressiona Esc (reason = 'escape').
let _modalIdSeq = 0;
function _setupModalA11y(overlay, { labelId, onEscape } = {}) {
  const dialog = overlay.firstElementChild;
  if (dialog) {
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    if (labelId) dialog.setAttribute('aria-labelledby', labelId);
  }
  // Elemento que tinha o foco antes de abrir o modal (para restaurar ao fechar)
  const previouslyFocused = document.activeElement;

  const getFocusable = () => Array.from(
    overlay.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
  ).filter((el) => !el.disabled && el.offsetParent !== null);

  const onKeydown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      if (onEscape) onEscape();
      return;
    }
    if (e.key === 'Tab') {
      const focusable = getFocusable();
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };
  overlay.addEventListener('keydown', onKeydown);

  // Restaura o foco quando o overlay é removido do DOM
  const cleanup = () => {
    if (previouslyFocused && typeof previouslyFocused.focus === 'function' && document.contains(previouslyFocused)) {
      previouslyFocused.focus();
    }
  };
  const origRemove = overlay.remove.bind(overlay);
  overlay.remove = () => { cleanup(); origRemove(); };
}

// ==================== MODAL DE CONFIRMAÇÃO ====================
export function confirmModal(title, message, { confirmText = 'Confirmar', cancelText = 'Cancelar', type = 'warning', icon = '⚠️' } = {}) {
  return new Promise((resolve) => {
    const colors = { warning: '#f9e2af', danger: '#f38ba8', info: '#89b4fa', success: '#a6e3a1' };
    const btnColors = { warning: '#f9e2af', danger: '#f38ba8', info: '#89b4fa', success: '#a6e3a1' };
    const titleId = `cm-title-${++_modalIdSeq}`;
    const overlay = document.createElement('div');
    overlay.id = 'confirm-modal-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.15s;';
    overlay.innerHTML = `<div style="background:#313244;border-radius:16px;padding:28px;max-width:400px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.5);border:1px solid #45475a;animation:scaleIn 0.15s;">
      <div style="text-align:center;margin-bottom:16px;">
        <div style="font-size:2.2rem;margin-bottom:8px;" aria-hidden="true">${escapeHtml(icon)}</div>
        <h3 id="${titleId}" style="color:${colors[type]};margin-bottom:8px;font-size:1.1rem;">${escapeHtml(title)}</h3>
        <p style="font-size:0.85rem;color:#cdd6f4;line-height:1.5;white-space:pre-line;">${escapeHtml(message)}</p>
      </div>
      <div style="display:flex;gap:10px;justify-content:center;">
        <button id="cm-cancel" style="background:#45475a;color:#cdd6f4;border:none;border-radius:8px;padding:10px 20px;font-size:0.88rem;cursor:pointer;font-weight:500;min-width:100px;">${escapeHtml(cancelText)}</button>
        <button id="cm-confirm" style="background:${btnColors[type]};color:#1e1e2e;border:none;border-radius:8px;padding:10px 20px;font-size:0.88rem;cursor:pointer;font-weight:700;min-width:100px;">${escapeHtml(confirmText)}</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    _setupModalA11y(overlay, { labelId: titleId, onEscape: () => { overlay.remove(); resolve(false); } });
    overlay.querySelector('#cm-confirm').onclick = () => { overlay.remove(); resolve(true); };
    overlay.querySelector('#cm-cancel').onclick = () => { overlay.remove(); resolve(false); };
    overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } });
    overlay.querySelector('#cm-cancel').focus();
  });
}

// ==================== MODAL DE AVISO (alert) ====================
export function alertModal(message, { title = 'Aviso', type = 'info', icon = null, okText = 'OK' } = {}) {
  return new Promise((resolve) => {
    const colors = { warning: '#f9e2af', danger: '#f38ba8', info: '#89b4fa', success: '#a6e3a1' };
    const icons = { warning: '⚠️', danger: '❌', info: 'ℹ️', success: '✅' };
    const _icon = icon || icons[type] || 'ℹ️';
    const titleId = `am-title-${++_modalIdSeq}`;
    const overlay = document.createElement('div');
    overlay.id = 'alert-modal-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.15s;';
    overlay.innerHTML = `<div style="background:#313244;border-radius:16px;padding:28px;max-width:420px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.5);border:1px solid #45475a;animation:scaleIn 0.15s;">
      <div style="text-align:center;margin-bottom:16px;">
        <div style="font-size:2.2rem;margin-bottom:8px;" aria-hidden="true">${_icon}</div>
        <h3 id="${titleId}" style="color:${colors[type]};margin-bottom:8px;font-size:1.1rem;">${escapeHtml(title)}</h3>
        <p style="font-size:0.85rem;color:#cdd6f4;line-height:1.5;white-space:pre-line;">${escapeHtml(message)}</p>
      </div>
      <div style="display:flex;justify-content:center;">
        <button id="am-ok" style="background:${colors[type]};color:#1e1e2e;border:none;border-radius:8px;padding:10px 24px;font-size:0.88rem;cursor:pointer;font-weight:700;min-width:120px;">${escapeHtml(okText)}</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    const close = () => { overlay.remove(); resolve(true); };
    _setupModalA11y(overlay, { labelId: titleId, onEscape: close });
    overlay.querySelector('#am-ok').onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelector('#am-ok').focus();
  });
}

// ==================== MODAL DE ENTRADA (prompt) ====================
export function promptModal(message, { title = 'Informe', defaultValue = '', placeholder = '', confirmText = 'Confirmar', cancelText = 'Cancelar', icon = '✏️', multiline = false } = {}) {
  return new Promise((resolve) => {
    const titleId = `pm-title-${++_modalIdSeq}`;
    const overlay = document.createElement('div');
    overlay.id = 'prompt-modal-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.15s;';
    const field = multiline
      ? `<textarea id="pm-input" placeholder="${escapeHtml(placeholder)}" style="width:100%;min-height:90px;padding:10px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;font-size:0.9rem;font-family:inherit;resize:vertical;">${escapeHtml(defaultValue)}</textarea>`
      : `<input id="pm-input" type="text" value="${escapeHtml(defaultValue)}" placeholder="${escapeHtml(placeholder)}" style="width:100%;padding:10px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;font-size:0.9rem;">`;
    overlay.innerHTML = `<div style="background:#313244;border-radius:16px;padding:28px;max-width:420px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.5);border:1px solid #45475a;animation:scaleIn 0.15s;">
      <div style="text-align:center;margin-bottom:14px;">
        <div style="font-size:2rem;margin-bottom:6px;" aria-hidden="true">${escapeHtml(icon)}</div>
        <h3 id="${titleId}" style="color:#89b4fa;margin-bottom:8px;font-size:1.1rem;">${escapeHtml(title)}</h3>
        ${message ? `<p style="font-size:0.85rem;color:#cdd6f4;line-height:1.5;margin-bottom:12px;">${escapeHtml(message)}</p>` : ''}
      </div>
      ${field}
      <div style="display:flex;gap:10px;justify-content:center;margin-top:16px;">
        <button id="pm-cancel" style="background:#45475a;color:#cdd6f4;border:none;border-radius:8px;padding:10px 20px;font-size:0.88rem;cursor:pointer;font-weight:500;min-width:100px;">${escapeHtml(cancelText)}</button>
        <button id="pm-confirm" style="background:#89b4fa;color:#1e1e2e;border:none;border-radius:8px;padding:10px 20px;font-size:0.88rem;cursor:pointer;font-weight:700;min-width:100px;">${escapeHtml(confirmText)}</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    const input = overlay.querySelector('#pm-input');
    const doConfirm = () => { const v = input.value; overlay.remove(); resolve(v); };
    const doCancel = () => { overlay.remove(); resolve(null); };
    _setupModalA11y(overlay, { labelId: titleId, onEscape: doCancel });
    overlay.querySelector('#pm-confirm').onclick = doConfirm;
    overlay.querySelector('#pm-cancel').onclick = doCancel;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) doCancel(); });
    if (!multiline) input.addEventListener('keydown', (e) => { if (e.key === 'Enter') doConfirm(); });
    input.focus();
    input.select?.();
  });
}

// ==================== TOAST (re-exported from toast.js) ====================
export { toast, removeToast } from './toast.js';

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

  // Incluir token de autenticação se disponível
  const token = localStorage.getItem('auth_token');
  if (token) {
    fetchOptions.headers['Authorization'] = `Bearer ${token}`;
  }

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
