// ==================== KEYBOARD SHORTCUTS ====================
import { state } from './state.js';
import { escapeHtml, debounce } from './utils.js';
import { switchTab } from './tabs.js';

let shortcuts = [];

function closeActiveOverlay() {
  const modals = document.querySelectorAll('.modal-overlay');
  modals.forEach(m => { if (m.style.display !== 'none' && m.style.display !== '') m.style.display = 'none'; });
  const ov = document.getElementById('overlay');
  if (ov) ov.style.display = 'none';
  const qs = document.getElementById('quick-search-overlay');
  if (qs) qs.remove();
  const sp = document.getElementById('shortcuts-panel');
  if (sp) sp.remove();
}

function openQuickSearch() {
  if (document.getElementById('quick-search-overlay')) return;
  const overlay = document.createElement('div');
  overlay.id = 'quick-search-overlay';
  overlay.className = 'modal-overlay';
  overlay.style.display = 'flex';
  overlay.innerHTML = `
    <div class="quick-search-box">
      <input type="text" id="quick-search-input" placeholder="Buscar tópico, matéria, PDF..." autofocus>
      <div id="quick-search-results" class="quick-search-results"></div>
      <div class="quick-search-hint">Esc para fechar • Enter para abrir • ↑↓ para navegar</div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  const input = document.getElementById('quick-search-input');
  input.addEventListener('input', debounce(() => quickSearchQuery(input.value), 200));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') overlay.remove();
    if (e.key === 'Enter') {
      const first = document.querySelector('.qs-result.active, .qs-result');
      if (first) first.click();
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const results = [...document.querySelectorAll('.qs-result')];
      const current = results.findIndex(r => r.classList.contains('active'));
      results.forEach(r => r.classList.remove('active'));
      const next = e.key === 'ArrowDown' ? Math.min(current + 1, results.length - 1) : Math.max(current - 1, 0);
      if (results[next]) {
        results[next].classList.add('active');
        results[next].scrollIntoView({ block: 'nearest' });
      }
    }
  });
}

function quickSearchQuery(query) {
  const container = document.getElementById('quick-search-results');
  if (!container) return;
  if (!query || query.length < 2) { container.innerHTML = ''; return; }
  const q = query.toLowerCase();
  const results = (state.editalData || []).filter(e => e.materia.toLowerCase().includes(q) || e.topico.toLowerCase().includes(q)).slice(0, 10);
  if (results.length === 0) {
    container.innerHTML = '<div class="qs-empty">Nenhum resultado</div>';
    return;
  }
  container.innerHTML = results.map((r, i) => `
    <div class="qs-result ${i === 0 ? 'active' : ''}" onclick="goToEditalItem(${r.id})">
      <span class="qs-materia">${escapeHtml(r.materia)}</span>
      <span class="qs-topico">${escapeHtml(r.topico)}</span>
    </div>
  `).join('');
}

export function goToEditalItem(id) {
  closeActiveOverlay();
  switchTab('tab-edital');
  setTimeout(() => {
    const el = document.querySelector(`[data-id="${id}"]`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('highlight-flash');
      setTimeout(() => el.classList.remove('highlight-flash'), 2000);
    }
  }, 200);
}

function showShortcutsPanel() {
  if (document.getElementById('shortcuts-panel')) {
    document.getElementById('shortcuts-panel').remove();
    return;
  }
  const panel = document.createElement('div');
  panel.id = 'shortcuts-panel';
  panel.className = 'modal-overlay';
  panel.style.display = 'flex';
  panel.innerHTML = `
    <div class="modal-box" style="max-width:400px;">
      <h3>⌨️ Atalhos de Teclado</h3>
      <div class="shortcuts-list">
        ${shortcuts.map(s => `<div class="shortcut-row"><kbd>${s.ctrl ? 'Ctrl+' : ''}${s.alt ? 'Alt+' : ''}${s.shift ? 'Shift+' : ''}${s.key}</kbd><span>${s.desc}</span></div>`).join('')}
      </div>
      <div class="modal-btns"><button class="iobtn" onclick="this.closest('.modal-overlay').remove()">Fechar</button></div>
    </div>
  `;
  document.body.appendChild(panel);
  panel.addEventListener('click', (e) => { if (e.target === panel) panel.remove(); });
}

export function initShortcuts() {
  shortcuts = [
    { key: 'Escape', desc: 'Fechar modal/overlay', action: closeActiveOverlay },
    { key: 'k', ctrl: true, desc: 'Busca rápida (Ctrl+K)', action: openQuickSearch },
    { key: '1', alt: true, desc: 'Tab PDFs', action: () => switchTab('tab-pdfs') },
    { key: '2', alt: true, desc: 'Tab Edital', action: () => switchTab('tab-edital') },
    { key: '3', alt: true, desc: 'Tab Ciclo', action: () => switchTab('tab-ciclo') },
    { key: '4', alt: true, desc: 'Tab Flashcards', action: () => switchTab('tab-flashcards') },
    { key: '5', alt: true, desc: 'Tab Metas', action: () => switchTab('tab-metas') },
    { key: '?', shift: true, desc: 'Mostrar atalhos', action: showShortcutsPanel },
  ];

  document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, textarea, select, [contenteditable]')) {
      if (e.key === 'Escape') e.target.blur();
      return;
    }
    for (const s of shortcuts) {
      if (s.key === e.key && !!s.ctrl === (e.ctrlKey || e.metaKey) && !!s.alt === e.altKey && !!s.shift === e.shiftKey) {
        e.preventDefault();
        s.action();
        return;
      }
    }
  });
}
