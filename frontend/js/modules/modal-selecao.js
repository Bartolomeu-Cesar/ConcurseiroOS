// ==================== MODAL DE SELEÇÃO GENÉRICO ====================
import { state } from './state.js';
import { escapeHtml } from './utils.js';

export function openSelectModal(title, items, callback) {
  state.selectModalCallback = callback;
  document.getElementById('select-modal-title').textContent = title;
  const searchEl = document.getElementById('select-modal-search');
  searchEl.value = '';
  searchEl.placeholder = 'Filtrar por nome, cargo ou edital...';
  renderSelectItems(items);
  document.getElementById('select-modal').classList.add('show');
  setTimeout(() => searchEl.focus(), 100);
  searchEl.oninput = (e) => {
    const q = e.target.value.toLowerCase();
    const filtered = items.filter(i =>
      i.label.toLowerCase().includes(q) || (i.sub || '').toLowerCase().includes(q)
    );
    renderSelectItems(filtered);
  };
}

function renderSelectItems(items) {
  const list = document.getElementById('select-modal-list');
  const clickableCount = items.filter(i => !i.disabled).length;
  list.innerHTML = items.map((item, i) => {
    if (item.disabled) {
      return `<div class="select-item select-group-header" style="pointer-events:none;opacity:0.7;font-weight:700;padding:8px 14px 4px;font-size:0.78rem;border-bottom:none;">
        <span class="si-icon">${item.icon || ''}</span>
        <span class="si-label">${escapeHtml(item.label)}</span>
        <span class="si-sub">${escapeHtml(item.sub || '')}</span>
      </div>`;
    }
    return `<div class="select-item" data-index="${i}" onclick="selectModalChoice(${i})">
      <span class="si-icon">${item.icon || ''}</span>
      <span class="si-label">${escapeHtml(item.label)}</span>
      <span class="si-sub">${escapeHtml(item.sub || '')}</span>
    </div>`;
  }).join('');
  list._items = items;
}

export function selectModalChoice(index) {
  const list = document.getElementById('select-modal-list');
  const item = list._items[index];
  if (item.disabled) return; // Don't select group headers
  const callback = state.selectModalCallback;
  closeSelectModal();
  if (callback) callback(item);
}

export function closeSelectModal() {
  document.getElementById('select-modal').classList.remove('show');
  state.selectModalCallback = null;
}

export function initModalSelecao() {
  document.getElementById('select-modal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) closeSelectModal();
  });
}
