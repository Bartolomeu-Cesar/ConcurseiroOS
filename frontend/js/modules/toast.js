/**
 * Toast Notification Module
 * 
 * Unified toast system extracted from multiple pages.
 * Supports: success, error, warning, info types.
 * Features: auto-dismiss, progress bar, action buttons, close button.
 * 
 * Usage:
 *   import { toast, showToast, removeToast } from './modules/toast.js';
 *   toast('Mensagem', 'success');
 *   toast('Excluído!', 'warning', 5000, { label: '↩ Desfazer', onClick: () => {} });
 */

// ==================== TOAST CONTAINER ====================
let toastContainer = document.getElementById('toast-container');
if (!toastContainer) {
  toastContainer = document.createElement('div');
  toastContainer.id = 'toast-container';
  toastContainer.setAttribute('role', 'alert');
  toastContainer.setAttribute('aria-live', 'assertive');
  toastContainer.setAttribute('aria-atomic', 'false');
  document.body.appendChild(toastContainer);
}

// ==================== INJECT STYLES (if not already present) ====================
if (!document.getElementById('toast-module-styles')) {
  const style = document.createElement('style');
  style.id = 'toast-module-styles';
  style.textContent = `
    #toast-container {
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 99999;
      display: flex;
      flex-direction: column;
      gap: 8px;
      pointer-events: none;
    }
    .toast {
      background: #313244;
      border-radius: 10px;
      padding: 12px 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.4);
      font-size: 0.88rem;
      color: #cdd6f4;
      pointer-events: auto;
      transform: translateX(120%);
      opacity: 0;
      transition: transform 0.3s ease, opacity 0.3s ease;
      max-width: 380px;
      position: relative;
      overflow: hidden;
    }
    .toast-show { transform: translateX(0); opacity: 1; }
    .toast-hide { transform: translateX(120%); opacity: 0; }
    .toast-success { border-left: 4px solid #a6e3a1; }
    .toast-error { border-left: 4px solid #f38ba8; }
    .toast-warning { border-left: 4px solid #f9e2af; }
    .toast-info { border-left: 4px solid #89b4fa; }
    .toast-icon { font-size: 1.1rem; flex-shrink: 0; }
    .toast-msg { flex: 1; line-height: 1.4; }
    .toast-close {
      background: none; border: none; color: #6c7086; font-size: 1.2rem;
      cursor: pointer; padding: 0 4px; line-height: 1;
    }
    .toast-close:hover { color: #cdd6f4; }
    .toast-action {
      background: rgba(137,180,250,0.15); border: 1px solid #89b4fa;
      color: #89b4fa; border-radius: 6px; padding: 4px 10px;
      font-size: 0.8rem; cursor: pointer; white-space: nowrap;
    }
    .toast-action:hover { background: rgba(137,180,250,0.25); }
    .toast-progress {
      position: absolute; bottom: 0; left: 0; right: 0; height: 3px;
      background: rgba(108,112,134,0.3);
    }
    .toast-progress-bar {
      height: 100%; width: 100%; background: currentColor;
      opacity: 0.4;
    }
    .toast-success .toast-progress-bar { background: #a6e3a1; }
    .toast-error .toast-progress-bar { background: #f38ba8; }
    .toast-warning .toast-progress-bar { background: #f9e2af; }
    .toast-info .toast-progress-bar { background: #89b4fa; }
  `;
  document.head.appendChild(style);
}

// ==================== CORE FUNCTIONS ====================

/**
 * Show a toast notification with full features (progress bar, actions, close button).
 * @param {string} message - Toast message
 * @param {'success'|'error'|'warning'|'info'} type - Toast type
 * @param {number} duration - Duration in ms (default: 4000)
 * @param {object|null} action - Optional action button { label: string, onClick: function }
 * @returns {HTMLElement} The toast element
 */
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
  requestAnimationFrame(() => { bar.style.width = '0%'; });

  const timer = setTimeout(() => removeToast(el), duration);
  el._timer = timer;
  return el;
}

/**
 * Simple toast (compatible with dashboard/social/mastery inline patterns).
 * Drop-in replacement for the simpler showToast(msg, type) pattern.
 * @param {string} message - Toast message
 * @param {'success'|'error'|'warning'|'info'} type - Toast type
 * @param {number} duration - Duration in ms (default: 4000)
 */
export function showToast(message, type = 'info', duration = 4000) {
  return toast(message, type, duration);
}

/**
 * Remove a toast element with animation.
 * @param {HTMLElement} el - The toast element to remove
 */
export function removeToast(el) {
  if (!el || !el.parentNode) return;
  clearTimeout(el._timer);
  el.classList.add('toast-hide');
  setTimeout(() => el.remove(), 300);
}

export default toast;
