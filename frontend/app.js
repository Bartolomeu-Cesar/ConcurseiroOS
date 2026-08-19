// ==================== API TYPES ====================
/// <reference path="types.ts" />
// ==================== SECURITY: HTML SANITIZATION ====================
function escapeHtml(text) {
    if (!text)
        return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
// ==================== TOAST NOTIFICATION SYSTEM ====================
const toastContainer = document.createElement('div');
toastContainer.id = 'toast-container';
document.body.appendChild(toastContainer);
function toast(message, type = 'info', duration = 4000, action = null) {
    // type: 'success' | 'error' | 'warning' | 'info'
    // action: { label: string, onClick: function } para botão de ação (ex: Desfazer)
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
    // Trigger animation
    requestAnimationFrame(() => el.classList.add('toast-show'));
    // Action button
    if (action) {
        el.querySelector('.toast-action').onclick = () => { action.onClick(); removeToast(el); };
    }
    // Close button
    el.querySelector('.toast-close').onclick = () => removeToast(el);
    // Progress bar animation
    const bar = el.querySelector('.toast-progress-bar');
    bar.style.transition = `width ${duration}ms linear`;
    requestAnimationFrame(() => bar.style.width = '0%');
    // Auto dismiss
    const timer = setTimeout(() => removeToast(el), duration);
    el._timer = timer;
    return el;
}
function removeToast(el) {
    if (!el || !el.parentNode)
        return;
    clearTimeout(el._timer);
    el.classList.add('toast-hide');
    setTimeout(() => el.remove(), 300);
}
// ==================== LOADING STATES ====================
function showLoading(container) {
    if (typeof container === 'string')
        container = document.getElementById(container);
    if (!container)
        return;
    container.innerHTML = `<div class="skeleton-group">
    <div class="skeleton skeleton-line" style="width:80%"></div>
    <div class="skeleton skeleton-line" style="width:60%"></div>
    <div class="skeleton skeleton-line" style="width:70%"></div>
    <div class="skeleton skeleton-line" style="width:50%"></div>
  </div>`;
}
function showSpinner(container) {
    if (typeof container === 'string')
        container = document.getElementById(container);
    if (!container)
        return;
    container.innerHTML = '<div class="spinner-wrapper"><div class="spinner"></div></div>';
}
function showEmpty(container, icon = '📚', message = 'Nenhum item encontrado') {
    if (typeof container === 'string')
        container = document.getElementById(container);
    if (!container)
        return;
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon}</div><div class="empty-msg">${message}</div></div>`;
}
// ==================== ERROR HANDLING & FETCH WRAPPER ====================
let isOffline = false;
function showOfflineBanner() {
    if (document.getElementById('offline-banner'))
        return;
    const banner = document.createElement('div');
    banner.id = 'offline-banner';
    banner.innerHTML = '⚠️ Sem conexão com o servidor. Algumas funções podem não funcionar.';
    document.body.prepend(banner);
}
function hideOfflineBanner() {
    const b = document.getElementById('offline-banner');
    if (b)
        b.remove();
}
window.addEventListener('online', () => { isOffline = false; hideOfflineBanner(); toast('Conexão restaurada!', 'success', 3000); });
window.addEventListener('offline', () => { isOffline = true; showOfflineBanner(); toast('Você está offline', 'warning', 5000); });
async function api(url, options = {}) {
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
            if (isOffline) {
                isOffline = false;
                hideOfflineBanner();
            }
            if (!res.ok) {
                const errText = await res.text().catch(() => 'Erro desconhecido');
                throw new Error(`HTTP ${res.status}: ${errText}`);
            }
            return await res.json();
        }
        catch (err) {
            if (err.name === 'AbortError') {
                if (attempt === retries) {
                    toast('Servidor demorou para responder', 'error');
                    throw err;
                }
            }
            else if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
                isOffline = true;
                showOfflineBanner();
                if (attempt === retries) {
                    toast('Sem conexão com servidor', 'error');
                    throw err;
                }
            }
            else {
                if (attempt === retries) {
                    toast(err.message || 'Erro ao comunicar com servidor', 'error');
                    throw err;
                }
            }
            await new Promise(r => setTimeout(r, 1000 * (attempt + 1))); // backoff
        }
    }
}
// ==================== KEYBOARD SHORTCUTS ====================
const shortcuts = [
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
    // Ignorar se estiver digitando em input/textarea
    if (e.target.matches('input, textarea, select, [contenteditable]')) {
        if (e.key === 'Escape')
            e.target.blur();
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
function closeActiveOverlay() {
    // Fechar modais abertos
    const modals = document.querySelectorAll('.modal-overlay');
    modals.forEach(m => { if (m.style.display !== 'none' && m.style.display !== '')
        m.style.display = 'none'; });
    // Fechar overlay de pausa
    const ov = document.getElementById('overlay');
    if (ov)
        ov.style.display = 'none';
    // Fechar quick search
    const qs = document.getElementById('quick-search-overlay');
    if (qs)
        qs.remove();
    // Fechar shortcuts panel
    const sp = document.getElementById('shortcuts-panel');
    if (sp)
        sp.remove();
}
function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    const btn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
    if (btn) {
        btn.classList.add('active');
        btn.setAttribute('aria-selected', 'true');
    }
    const tab = document.getElementById(tabId);
    if (tab)
        tab.classList.add('active');
}
function openQuickSearch() {
    if (document.getElementById('quick-search-overlay'))
        return;
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
    overlay.addEventListener('click', (e) => { if (e.target === overlay)
        overlay.remove(); });
    const input = document.getElementById('quick-search-input');
    input.addEventListener('input', debounce(() => quickSearchQuery(input.value), 200));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape')
            overlay.remove();
        if (e.key === 'Enter') {
            const first = document.querySelector('.qs-result.active, .qs-result');
            if (first)
                first.click();
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
    if (!container)
        return;
    if (!query || query.length < 2) {
        container.innerHTML = '';
        return;
    }
    const q = query.toLowerCase();
    // Buscar em editalData (tópicos/matérias)
    const results = (editalData || []).filter(e => e.materia.toLowerCase().includes(q) || e.topico.toLowerCase().includes(q)).slice(0, 10);
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
function goToEditalItem(id) {
    closeActiveOverlay();
    switchTab('tab-edital');
    // Highlight the item
    setTimeout(() => {
        const el = document.querySelector(`[data-id="${id}"]`);
        if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.classList.add('highlight-flash');
            setTimeout(() => el.classList.remove('highlight-flash'), 2000);
        }
    }, 200);
}
function debounce(fn, ms) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
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
    panel.addEventListener('click', (e) => { if (e.target === panel)
        panel.remove(); });
}
// ==================== UNDO SYSTEM ====================
let pendingDeletions = [];
function undoableDelete(itemDesc, deleteUrl, onComplete) {
    // Mostra toast com botão Desfazer, só executa delete após timeout
    let cancelled = false;
    const toastEl = toast(`${itemDesc} excluído`, 'warning', 5000, {
        label: '↩ Desfazer',
        onClick: () => { cancelled = true; toast('Exclusão cancelada!', 'success', 2000); if (onComplete)
            onComplete(false); }
    });
    setTimeout(async () => {
        if (!cancelled) {
            try {
                await fetch(deleteUrl, { method: 'DELETE' });
                if (onComplete)
                    onComplete(true);
            }
            catch (e) {
                toast('Erro ao excluir', 'error');
            }
        }
    }, 5200);
}
// ==================== TAB NAVIGATION ====================
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        btn.setAttribute('aria-selected', 'true');
        document.getElementById(btn.dataset.tab).classList.add('active');
    });
});
// ==================== TAB 1: PDFs ====================
const API = '';
const OPEN_KEY = 'folders_open';
const TIMER_KEY = 'leitor_timer_state';
const TIMER_LIMIT_KEY = 'leitor_timer_limit_min';
var editalData = []; // Declaração global (usada por PDFs e Edital)
function getOpenFolders() {
    try {
        return new Set(JSON.parse(sessionStorage.getItem(OPEN_KEY)) || []);
    }
    catch {
        return new Set();
    }
}
function saveOpenFolders(set) { sessionStorage.setItem(OPEN_KEY, JSON.stringify([...set])); }
async function load() {
    showLoading('tree');
    try {
        const [tree, bulk] = await Promise.all([
            fetch(`${API}/api/tree`).then(r => r.json()),
            fetch(`${API}/api/progress-bulk`).then(r => r.json())
        ]);
        // Garantir editalData carregado para mostrar tags de disciplina nos PDFs
        if (!editalData || editalData.length === 0) {
            try {
                editalData = await fetch('/api/edital').then(r => r.json());
            }
            catch (e) { }
        }
        document.getElementById('tree').innerHTML = '';
        renderNodes(tree, document.getElementById('tree'), bulk, '');
        if (tree.length === 0) {
            showEmpty('tree', '📚', 'Nenhum PDF encontrado. Adicione arquivos PDF na pasta backend/pdfs/ para começar!');
        }
    }
    catch (e) {
        toast('Erro ao carregar PDFs', 'error');
        showEmpty('tree', '📄', 'Erro ao carregar. Tente novamente.');
    }
}
function calcFolderProgress(children, bulk, prefix) {
    let read = 0, total = 0;
    for (const n of children) {
        if (n.type === 'pdf') {
            const p = prefix ? `${prefix}/${n.name}` : n.name;
            const prog = bulk[p];
            const tp = prog ? prog.total_pages : 1;
            const cp = prog ? prog.current_page : 1;
            total += tp;
            read += cp - 1;
        }
        else if (n.type === 'folder') {
            const sub = calcFolderProgress(n.children, bulk, prefix ? `${prefix}/${n.name}` : n.name);
            total += sub.total;
            read += sub.read;
        }
    }
    return { read, total };
}
function renderNodes(nodes, container, bulk, prefix) {
    for (const node of nodes) {
        const path = prefix ? `${prefix}/${node.name}` : node.name;
        if (node.type === 'folder') {
            const { read, total } = calcFolderProgress(node.children, bulk, path);
            const pct = total > 0 ? Math.round((read / total) * 100) : 0;
            const div = document.createElement('div');
            div.className = 'folder';
            div.innerHTML = `
        <div class="folder-header"><span class="folder-icon">📁</span><span class="folder-name">${escapeHtml(node.name)}</span><span class="folder-progress">${pct}% concluído</span>${pct === 100 ? '<span class="badge-done">✓</span>' : ''}</div>
        <div class="folder-bar"><div class="folder-bar-fill" style="width:${pct}%"></div></div>
        <div class="folder-children"></div>
      `;
            const header = div.querySelector('.folder-header');
            const children = div.querySelector('.folder-children');
            if (getOpenFolders().has(path))
                children.classList.add('open');
            header.addEventListener('click', () => {
                children.classList.toggle('open');
                const updated = getOpenFolders();
                if (children.classList.contains('open'))
                    updated.add(path);
                else
                    updated.delete(path);
                saveOpenFolders(updated);
            });
            renderNodes(node.children, children, bulk, path);
            container.appendChild(div);
        }
        else if (node.type === 'pdf') {
            const prog = bulk[path];
            const tp = prog ? prog.total_pages : null;
            const cp = prog ? prog.current_page : 1;
            const pct = tp ? Math.round(((cp - 1) / tp) * 100) : 0;
            const label = tp ? `pág. ${cp}/${tp} (${pct}%)` : 'não lido';
            // Verificar se este PDF está vinculado a alguma disciplina
            const vinculado = editalData.find(e => e.pdf_link === path);
            const materiaTag = vinculado ? `<span class="pdf-materia-tag">${escapeHtml(vinculado.materia)}</span>` : '';
            const linkBtn = vinculado
                ? `<button class="pdf-link-disc-btn pdf-unlink" onclick="event.stopPropagation();unlinkPdf('${path.replace(/'/g, "\\'")}')" title="Desvincular disciplina">❌</button>`
                : `<button class="pdf-link-disc-btn" onclick="event.stopPropagation();linkPdfToDisc('${path.replace(/'/g, "\\'")}')" title="Vincular a disciplina">🔗</button>`;
            const div = document.createElement('div');
            div.innerHTML = `
        <div class="pdf-item" data-path="${path}">
          <span>📄</span>
          <span class="pdf-name">${escapeHtml(node.name.replace(/_/g, ' '))}</span>
          ${materiaTag}
          <span class="pdf-progress">${label}</span>
          ${pct === 100 ? '<span class="badge-done">✓</span>' : ''}
          ${linkBtn}
        </div>
        <div class="pdf-bar"><div class="pdf-bar-fill" style="width:${pct}%"></div></div>
      `;
            div.querySelector('.pdf-item').addEventListener('click', () => { window.open(`viewer.html?path=${encodeURIComponent(path)}`, '_blank'); });
            container.appendChild(div);
        }
    }
}
load();
window.addEventListener('storage', (e) => {
    if (e.key === 'leitor_progress_updated')
        load();
    if (e.key === 'leitor_timer_finished' || e.key === 'leitor_timer_state') {
        clearInterval(timerInterval);
        timerInterval = null;
        restoreTimer();
    }
});
window.addEventListener('focus', () => load());
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible')
    load(); });
// --- Pomodoro Timer ---
let timerInterval = null, elapsed = 0, paused = false, limitSeconds = 0, startedAt = null;
const display = document.getElementById('timer-display');
const select = document.getElementById('timer-select');
const btnStart = document.getElementById('btn-start');
const btnPause = document.getElementById('btn-pause');
const btnStop = document.getElementById('btn-stop');
const savedLimit = localStorage.getItem(TIMER_LIMIT_KEY);
if (savedLimit)
    select.value = savedLimit;
select.addEventListener('change', () => { localStorage.setItem(TIMER_LIMIT_KEY, select.value); });
function fmt(s) { return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }
function saveState() { localStorage.setItem(TIMER_KEY, JSON.stringify({ elapsed, paused, limitSeconds, startedAt, running: !!timerInterval })); }
function loadState() { try {
    const r = localStorage.getItem(TIMER_KEY);
    return r ? JSON.parse(r) : null;
}
catch {
    return null;
} }
function clearState() { localStorage.removeItem(TIMER_KEY); }
function updateDisplay() { display.textContent = fmt(elapsed); display.classList.toggle('done', limitSeconds > 0 && elapsed >= limitSeconds); }
function tick() { if (paused || !startedAt)
    return; elapsed = Math.floor((Date.now() - startedAt) / 1000); updateDisplay(); saveState(); if (elapsed >= limitSeconds)
    stopTimer(true); }
function startTimer(fromContinue = false) {
    limitSeconds = fromContinue ? limitSeconds : parseInt(select.value, 10) * 60;
    if (!fromContinue) {
        localStorage.setItem(TIMER_LIMIT_KEY, select.value);
        elapsed = 0;
        startedAt = Date.now();
    }
    else {
        startedAt = Date.now() - (elapsed * 1000);
    }
    paused = false;
    select.disabled = true;
    btnStart.disabled = true;
    btnPause.disabled = false;
    btnStop.disabled = false;
    btnPause.textContent = '⏸ Pausar';
    btnStart.textContent = '▶ Iniciar';
    clearInterval(timerInterval);
    timerInterval = setInterval(tick, 250);
    tick();
    saveState();
}
function pauseTimer() {
    if (!timerInterval)
        return;
    clearInterval(timerInterval);
    timerInterval = null;
    paused = true;
    if (startedAt)
        elapsed = Math.floor((Date.now() - startedAt) / 1000);
    startedAt = null;
    btnPause.disabled = true;
    btnStart.textContent = '▶ Continuar';
    btnStart.disabled = false;
    updateDisplay();
    saveState();
}
function stopTimer(showOverlay = false) {
    clearInterval(timerInterval);
    timerInterval = null;
    // Salvar tempo estudado se > 1 minuto
    if (startedAt) {
        const finalElapsed = Math.floor((Date.now() - startedAt) / 1000);
        if (finalElapsed >= 60) {
            const hours = finalElapsed / 3600;
            fetch('/api/sessoes-estudo/registrar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ horas: hours, materia: 'Leitura PDF', tipo: 'timer' })
            }).catch(() => {});
        }
    }
    elapsed = 0;
    paused = false;
    startedAt = null;
    limitSeconds = 0;
    display.textContent = '00:00:00';
    display.classList.remove('done');
    select.disabled = false;
    btnStart.textContent = '▶ Iniciar';
    btnStart.disabled = false;
    btnPause.textContent = '⏸ Pausar';
    btnPause.disabled = true;
    btnStop.disabled = true;
    clearState();
    localStorage.setItem('leitor_timer_finished', Date.now().toString());
    if (showOverlay)
        document.getElementById('overlay').style.display = 'flex';
}
function restoreTimer() {
    const state = loadState();
    if (!state) {
        elapsed = 0;
        paused = false;
        startedAt = null;
        limitSeconds = 0;
        display.textContent = '00:00:00';
        display.classList.remove('done');
        select.disabled = false;
        btnStart.textContent = '▶ Iniciar';
        btnStart.disabled = false;
        btnPause.disabled = true;
        btnStop.disabled = true;
        return;
    }
    elapsed = state.elapsed || 0;
    paused = state.paused || false;
    limitSeconds = state.limitSeconds || 0;
    startedAt = state.startedAt || null;
    if (state.running && !paused && startedAt) {
        select.disabled = true;
        btnStart.disabled = true;
        btnPause.disabled = false;
        btnStop.disabled = false;
        elapsed = Math.floor((Date.now() - startedAt) / 1000);
        updateDisplay();
        if (elapsed >= limitSeconds) {
            stopTimer(true);
            return;
        }
        clearInterval(timerInterval);
        timerInterval = setInterval(tick, 250);
    }
    else if (paused && limitSeconds > 0) {
        select.disabled = true;
        btnStart.disabled = false;
        btnStart.textContent = '▶ Continuar';
        btnPause.disabled = true;
        btnStop.disabled = false;
        updateDisplay();
    }
    else {
        updateDisplay();
    }
}
btnStart.addEventListener('click', () => { btnStart.textContent.includes('Continuar') ? startTimer(true) : startTimer(false); });
btnPause.addEventListener('click', pauseTimer);
btnStop.addEventListener('click', () => stopTimer(false));
restoreTimer();
// Export/Import
function exportProgress() { const a = document.createElement('a'); a.href = '/api/export'; a.download = 'leitor_progress.json'; a.click(); }
async function importProgress(input) {
    const file = input.files[0];
    if (!file)
        return;
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/import', { method: 'POST', body: form });
    const data = await res.json();
    input.value = '';
    if (data.ok) {
        toast(`Importado! ${data.imported} registro(s).`, 'success');
        load();
    }
    else {
        toast('Erro ao importar.', 'error');
    }
}
// ==================== TAB 2: EDITAL ====================
let editalTimer = null, editalStartedAt = null, editalElapsed = 0, editalPaused = false, editalSelectedId = null;
const editalDisplay = document.getElementById('edital-timer-display');
const editalMateriaLabel = document.getElementById('edital-materia-label');
const editalBtnStart = document.getElementById('edital-btn-start');
const editalBtnStop = document.getElementById('edital-btn-stop');
const EDITAL_OPEN_KEY = 'edital_accordion_state';
function editalFmt(s) { return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }
function editalTick() { if (editalPaused || !editalStartedAt)
    return; editalElapsed = Math.floor((Date.now() - editalStartedAt) / 1000); editalDisplay.textContent = editalFmt(editalElapsed); }
editalBtnStart.addEventListener('click', () => {
    if (!editalSelectedId) {
        toast('Selecione um tópico no accordion abaixo.', 'warning');
        return;
    }
    if (editalTimer) {
        clearInterval(editalTimer);
        editalTimer = null;
        editalPaused = true;
        editalElapsed = Math.floor((Date.now() - editalStartedAt) / 1000);
        editalStartedAt = null;
        editalBtnStart.textContent = '▶ Iniciar';
        editalBtnStop.style.display = 'inline-block';
    }
    else {
        if (editalPaused) {
            editalStartedAt = Date.now() - (editalElapsed * 1000);
        }
        else {
            editalStartedAt = Date.now();
            editalElapsed = 0;
        }
        editalPaused = false;
        editalTimer = setInterval(editalTick, 250);
        editalBtnStart.textContent = '⏸ Pausar';
        editalBtnStop.style.display = 'inline-block';
        editalTick();
    }
});
editalBtnStop.addEventListener('click', async () => {
    clearInterval(editalTimer);
    editalTimer = null;
    if (editalStartedAt)
        editalElapsed = Math.floor((Date.now() - editalStartedAt) / 1000);
    const hours = editalElapsed / 3600;
    if (editalSelectedId && editalElapsed > 0) {
        await fetch(`/api/edital/${editalSelectedId}/horas`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ horas: hours }) });
        loadEdital();
        loadStreakBadge();
    }
    editalElapsed = 0;
    editalStartedAt = null;
    editalPaused = false;
    editalDisplay.textContent = '00:00:00';
    editalBtnStart.textContent = '▶ Iniciar';
    editalBtnStop.style.display = 'none';
});
function getAccordionState() {
    try {
        return JSON.parse(sessionStorage.getItem(EDITAL_OPEN_KEY)) || {};
    }
    catch {
        return {};
    }
}
function saveAccordionState(state) { sessionStorage.setItem(EDITAL_OPEN_KEY, JSON.stringify(state)); }
let editalInfo = [];
async function loadEdital() {
    showLoading('edital-accordion');
    try {
        const [dataRes, infoRes] = await Promise.all([
            fetch('/api/edital').then(r => r.json()),
            fetch('/api/edital/info').then(r => r.ok ? r.json() : [])
        ]);
        editalData = dataRes;
        editalInfo = infoRes;
    }
    catch (e) {
        // Se info falhar, carregar só os dados do edital
        try {
            editalData = await fetch('/api/edital').then(r => r.json());
            editalInfo = [];
        }
        catch (e2) {
            editalData = [];
            editalInfo = [];
            toast('Erro ao carregar edital', 'error');
        }
    }
    renderEditalTree();
}
function getStatusClass(s) { return s === 'Em Andamento' ? 'status-em-andamento' : s === 'Concluído' ? 'status-concluido' : 'status-nao-iniciado'; }
function formatHours(h) { const hrs = Math.floor(h); const mins = Math.round((h - hrs) * 60); if (hrs === 0 && mins === 0)
    return '—'; if (hrs === 0)
    return `${mins}m`; if (mins === 0)
    return `${hrs}h`; return `${hrs}h${mins}m`; }
function renderEditalTree() {
    const container = document.getElementById('edital-accordion');
    const state = getAccordionState();
    if (editalData.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-msg">Nenhum edital cadastrado ainda. Use o formulário abaixo para adicionar matérias e tópicos, ou importe um PDF de edital.</div></div>';
        return;
    }
    // Construir tree: Concurso > Cargo > Matéria > Tópicos
    const tree = {};
    for (const item of editalData) {
        const concurso = item.edital_nome || 'Geral';
        const cargo = item.cargo || 'Geral';
        const mat = item.materia;
        if (!tree[concurso])
            tree[concurso] = {};
        if (!tree[concurso][cargo])
            tree[concurso][cargo] = {};
        if (!tree[concurso][cargo][mat])
            tree[concurso][cargo][mat] = [];
        tree[concurso][cargo][mat].push(item);
    }
    const total = editalData.length;
    const concluidos = editalData.filter(i => i.status === 'Concluído').length;
    document.getElementById('edital-stats').textContent = `${total} tópicos • ${concluidos} concluídos (${total > 0 ? Math.round(concluidos / total * 100) : 0}%)`;
    let html = '';
    const concursos = Object.keys(tree).sort();
    for (const concurso of concursos) {
        const concKey = `c_${concurso}`;
        const concOpen = state[concKey] !== false;
        const concItems = editalData.filter(i => i.edital_nome === concurso);
        const concDone = concItems.filter(i => i.status === 'Concluído').length;
        const concPct = concItems.length > 0 ? Math.round(concDone / concItems.length * 100) : 0;
        html += `<div class="tree-l1">
      <div class="tree-node tree-node-l1 ${concOpen ? 'open' : ''}" data-key="${concKey}" onclick="toggleTree(this)">
        <span class="tree-chevron">▶</span>
        <span class="tree-icon">📋</span>
        <span class="tree-label">${escapeHtml(concurso)}</span>
        <span class="tree-stats">${concDone}/${concItems.length} (${concPct}%)</span>
        <div class="tree-bar"><div class="tree-bar-fill" style="width:${concPct}%"></div></div>
        <button class="tree-archive-btn" onclick="event.stopPropagation();arquivarConcurso('${concurso.replace(/'/g, "\\'")}')" title="Arquivar concurso inteiro">📦</button>
        <button class="tree-archive-btn tree-excluir-btn" onclick="event.stopPropagation();excluirConcurso('${concurso.replace(/'/g, "\\'")}')" title="Excluir concurso inteiro">🗑</button>
      </div>
      <div class="tree-children ${concOpen ? 'open' : ''}">`;
        const cargos = Object.keys(tree[concurso]).sort();
        for (const cargo of cargos) {
            const cargoKey = `cr_${concurso}_${cargo}`;
            const cargoOpen = state[cargoKey] === true;
            const cargoItems = concItems.filter(i => (i.cargo || 'Geral') === cargo);
            const cargoDone = cargoItems.filter(i => i.status === 'Concluído').length;
            const cargoPct = cargoItems.length > 0 ? Math.round(cargoDone / cargoItems.length * 100) : 0;
            // Nível 2: Cargo - buscar metadados
            const info = editalInfo.find(i => i.edital_nome === concurso && i.cargo === cargo);
            const infoHtml = info ? `<div class="tree-info-badge" title="${escapeHtml(info.local_prova || '')}">
        ${info.data_prova_objetiva ? `<span>📅 ${escapeHtml(info.data_prova_objetiva)}</span>` : ''}
        ${info.subsidio ? `<span>💰 ${escapeHtml(info.subsidio)}</span>` : ''}
        ${info.vagas ? `<span>🎯 ${escapeHtml(info.vagas)}</span>` : ''}
      </div>` : '';
            html += `<div class="tree-l2">
        <div class="tree-node tree-node-l2 ${cargoOpen ? 'open' : ''}" data-key="${cargoKey}" onclick="toggleTree(this)">
          <span class="tree-chevron">▶</span>
          <span class="tree-icon">👤</span>
          <span class="tree-label">${escapeHtml(cargo)}</span>
          ${infoHtml}
          <span class="tree-stats">${cargoDone}/${cargoItems.length}</span>
          <div class="tree-bar"><div class="tree-bar-fill" style="width:${cargoPct}%"></div></div>
          <button class="tree-archive-btn" onclick="event.stopPropagation();arquivarCargo('${concurso.replace(/'/g, "\\'")}','${cargo.replace(/'/g, "\\'")}')\" title="Arquivar">📦</button>
          <button class="tree-archive-btn tree-excluir-btn" onclick="event.stopPropagation();excluirCargo('${concurso.replace(/'/g, "\\'")}','${cargo.replace(/'/g, "\\'")}')\" title="Excluir permanentemente">🗑</button>
        </div>
        <div class="tree-children ${cargoOpen ? 'open' : ''}">`;
            // Se há info detalhada, mostrar card dentro do cargo
            if (info) {
                html += `<div class="tree-info-card">
          ${info.data_prova_objetiva ? `<div><strong>📅 Objetiva:</strong> ${escapeHtml(info.data_prova_objetiva)}</div>` : ''}
          ${info.data_prova_discursiva ? `<div><strong>📝 Discursiva:</strong> ${escapeHtml(info.data_prova_discursiva)}</div>` : ''}
          ${info.horario ? `<div><strong>🕐 Horário:</strong> ${escapeHtml(info.horario)}</div>` : ''}
          ${info.local_prova ? `<div><strong>📍 Local:</strong> ${escapeHtml(info.local_prova)}</div>` : ''}
          ${info.vagas ? `<div><strong>🎯 Vagas:</strong> ${escapeHtml(info.vagas)}</div>` : ''}
          ${info.subsidio ? `<div><strong>💰 Subsídio:</strong> ${escapeHtml(info.subsidio)}</div>` : ''}
          ${info.inscricoes ? `<div><strong>📋 Inscrições:</strong> ${escapeHtml(info.inscricoes)}</div>` : ''}
          ${info.link_edital ? `<div><a href="${escapeHtml(info.link_edital)}" target="_blank" style="color:#89b4fa;font-size:0.8rem;">🔗 Abrir edital no Cebraspe</a></div>` : ''}
        </div>`;
            }
            const materias = Object.keys(tree[concurso][cargo]).sort();
            for (const matNome of materias) {
                const matKey = `m_${concurso}_${cargo}_${matNome}`;
                const matOpen = state[matKey] === true;
                const items = tree[concurso][cargo][matNome];
                const matDone = items.filter(i => i.status === 'Concluído').length;
                const matPct = items.length > 0 ? Math.round(matDone / items.length * 100) : 0;
                const matHoras = items.reduce((a, i) => a + i.horas_estudadas, 0);
                html += `<div class="tree-l3">
          <div class="tree-node tree-node-l3 ${matOpen ? 'open' : ''}" data-key="${matKey}" onclick="toggleTree(this)">
            <span class="tree-chevron">▶</span>
            <span class="tree-icon">📚</span>
            <span class="tree-label">${escapeHtml(matNome)}</span>
            <span class="tree-stats">${matDone}/${items.length}${matHoras > 0 ? ' • ' + formatHours(matHoras) : ''}</span>
            <div class="tree-bar"><div class="tree-bar-fill" style="width:${matPct}%"></div></div>
            <button class="tree-pdf-link-btn" style="font-size:0.7rem;" onclick="event.stopPropagation();linkPdfToMateria('${matNome.replace(/'/g, "\\\\'")}','${concurso}','${cargo}')" title="Vincular PDF à matéria">🔗</button>
          </div>
          <div class="tree-children ${matOpen ? 'open' : ''}">`;
                for (const item of items) {
                    const sel = item.id === editalSelectedId ? ' selected' : '';
                    const safeMateria = item.materia.replace(/'/g, "\\'");
                    const safeTopico = item.topico.replace(/'/g, "\\'");
                    const pdfBtn = item.pdf_link
                        ? `<a class="tree-pdf-btn" href="viewer.html?path=${encodeURIComponent(item.pdf_link)}${item.pdf_pagina ? '#page=' + item.pdf_pagina : ''}" target="_blank" onclick="event.stopPropagation()" title="Abrir PDF">📖</a>`
                        : `<button class="tree-pdf-link-btn" onclick="event.stopPropagation();linkPdfToTopic(${item.id},'${safeMateria}')" title="Vincular PDF">🔗</button>`;
                    html += `<div class="tree-leaf${sel}" data-id="${item.id}" onclick="selectEditalTopic(${item.id}, '${safeMateria}', '${safeTopico}')">
            <span class="tree-status ${getStatusClass(item.status)}" onclick="event.stopPropagation();toggleEditalStatus(${item.id})">${item.status === 'Concluído' ? '✓' : item.status === 'Em Andamento' ? '◐' : '○'}</span>
            <span class="tree-topic">${escapeHtml(item.topico)}</span>
            ${item.horas_estudadas > 0 ? `<span class="tree-hours">${formatHours(item.horas_estudadas)}</span>` : ''}
            ${pdfBtn}
            <button class="tree-note" onclick="event.stopPropagation();openNoteModal(${item.id})" title="Notas">📝</button>
            <button class="tree-del" onclick="event.stopPropagation();deleteEditalItem(${item.id})">×</button>
          </div>`;
                }
                html += `</div></div>`;
            }
            html += `</div></div>`;
        }
        html += `</div></div>`;
    }
    container.innerHTML = html;
}
function toggleTree(el) {
    const key = el.dataset.key;
    const state = getAccordionState();
    const isOpen = el.classList.contains('open');
    el.classList.toggle('open');
    const body = el.nextElementSibling;
    if (body)
        body.classList.toggle('open');
    state[key] = !isOpen;
    saveAccordionState(state);
}
function toggleAllEdital(expand) {
    const state = getAccordionState();
    document.querySelectorAll('.tree-node').forEach(h => {
        const key = h.dataset.key;
        if (expand) {
            h.classList.add('open');
            h.nextElementSibling?.classList.add('open');
            state[key] = true;
        }
        else {
            h.classList.remove('open');
            h.nextElementSibling?.classList.remove('open');
            state[key] = false;
        }
    });
    saveAccordionState(state);
}
function selectEditalTopic(id, materia, topico) {
    editalSelectedId = id;
    editalMateriaLabel.textContent = `📖 ${materia} — ${topico}`;
    document.querySelectorAll('.tree-leaf').forEach(r => r.classList.remove('selected'));
    const row = document.querySelector(`.tree-leaf[data-id="${id}"]`);
    if (row)
        row.classList.add('selected');
}
async function toggleEditalStatus(id) { await fetch(`/api/edital/${id}/status`, { method: 'PUT' }); loadEdital(); }
async function deleteEditalItem(id) {
    undoableDelete('Tópico', `/api/edital/${id}`, (deleted) => {
        if (deleted) {
            if (editalSelectedId == id) {
                editalSelectedId = null;
                editalMateriaLabel.textContent = 'Nenhuma matéria selecionada';
            }
            loadEdital();
        }
        else {
            // Undo - reload to restore view
            loadEdital();
        }
    });
}
async function addEdital() {
    const concurso = document.getElementById('edital-nome-input').value.trim() || 'Geral';
    const cargo = document.getElementById('edital-cargo-input').value.trim() || '';
    const m = document.getElementById('edital-materia-input').value.trim();
    const t = document.getElementById('edital-topico-input').value.trim();
    if (!m || !t) {
        toast('Preencha matéria e tópico.', 'warning');
        return;
    }
    await fetch('/api/edital', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ edital_nome: concurso, cargo: cargo, materia: m, topico: t }) });
    document.getElementById('edital-materia-input').value = '';
    document.getElementById('edital-topico-input').value = '';
    loadEdital();
}
async function importEditalPdf(input) {
    const file = input.files[0];
    if (!file)
        return;
    const nome = document.getElementById('edital-pdf-nome').value.trim() || 'Importado';
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`/api/edital/importar-pdf?edital_nome=${encodeURIComponent(nome)}`, { method: 'POST', body: form }).then(r => r.json());
    input.value = '';
    if (res.ok) {
        toast(`Importados ${res.importados} itens!`, 'success');
        loadEdital();
    }
    else {
        toast('Erro ao importar.', 'error');
    }
}
loadEdital();
// ==================== TAB 3: CICLO ====================
let cicloTimerInterval = null, cicloStartedAt = null, cicloElapsed = 0, cicloPaused = false;
let cicloProximoId = null, cicloProximoMateria = '';
async function loadCiclo() {
    showLoading('ciclo-list');
    try {
        const [ciclo, proximo] = await Promise.all([
            fetch('/api/ciclo').then(r => r.json()),
            fetch('/api/ciclo/proximo').then(r => r.json())
        ]);
        // Card de foco
        cicloProximoId = proximo.id || null;
        cicloProximoMateria = proximo.materia || '—';
        document.getElementById('ciclo-focus-materia').textContent = cicloProximoMateria;
        const pctProx = proximo.horas_alvo > 0 ? Math.round((proximo.horas_cumpridas || 0) / proximo.horas_alvo * 100) : 0;
        document.getElementById('ciclo-focus-sub').textContent = `${(proximo.horas_cumpridas || 0).toFixed(1)}h / ${(proximo.horas_alvo || 0).toFixed(1)}h (${pctProx}%)`;
        // Lista
        const list = document.getElementById('ciclo-list');
        if (ciclo.length === 0) {
            list.innerHTML = '<div class="empty-state"><div class="empty-icon">🔄</div><div class="empty-msg">Nenhuma matéria no ciclo. Adicione matérias ou importe do edital para começar o estudo intercalado.</div></div>';
            return;
        }
        const totalHoras = ciclo.reduce((a, c) => a + c.horas_alvo, 0);
        const totalCumpridas = ciclo.reduce((a, c) => a + c.horas_cumpridas, 0);
        const pctGeral = totalHoras > 0 ? Math.round(totalCumpridas / totalHoras * 100) : 0;
        let html = `<div style="font-size:0.8rem;color:#9399b2;margin-bottom:8px;display:flex;justify-content:space-between;"><span>${ciclo.length} matérias no ciclo</span><span>Progresso geral: ${pctGeral}% (${totalCumpridas.toFixed(1)}h / ${totalHoras.toFixed(1)}h)</span></div>`;
        html += ciclo.map(c => {
            const pct = c.horas_alvo > 0 ? Math.min(100, (c.horas_cumpridas / c.horas_alvo) * 100) : 0;
            const isNext = c.id === cicloProximoId;
            return `<div class="ciclo-item ${isNext ? 'is-next' : ''}">
        ${isNext ? '<span style="color:#a6e3a1;font-size:0.8rem;">▶</span>' : '<span style="width:14px;"></span>'}
        <span class="ciclo-materia">${escapeHtml(c.materia)}</span>
        <div class="ciclo-bar"><div class="ciclo-bar-fill" style="width:${pct}%;${pct >= 100 ? 'background:#a6e3a1;' : ''}"></div></div>
        <span class="ciclo-pct">${Math.round(pct)}%</span>
        <span class="ciclo-hours">${c.horas_cumpridas.toFixed(1)}h / ${c.horas_alvo.toFixed(1)}h</span>
        <button class="ciclo-delete" onclick="deleteCiclo(${c.id})">🗑</button>
      </div>`;
        }).join('');
        list.innerHTML = html;
    }
    catch (e) {
        toast('Erro ao carregar ciclo', 'error');
        showEmpty('ciclo-list', '🔄', 'Erro ao carregar ciclo.');
    }
}
function cicloTimerToggle() {
    if (!cicloProximoId) {
        toast('Adicione matérias ao ciclo primeiro.', 'warning');
        return;
    }
    const btn = document.getElementById('ciclo-btn-start');
    const stopBtn = document.getElementById('ciclo-btn-stop');
    if (cicloTimerInterval) {
        // Pausar
        clearInterval(cicloTimerInterval);
        cicloTimerInterval = null;
        cicloPaused = true;
        cicloElapsed = Math.floor((Date.now() - cicloStartedAt) / 1000);
        cicloStartedAt = null;
        btn.textContent = '▶ Continuar';
        btn.style.background = '#fab387';
    }
    else {
        // Iniciar/Continuar
        if (cicloPaused) {
            cicloStartedAt = Date.now() - (cicloElapsed * 1000);
        }
        else {
            cicloStartedAt = Date.now();
            cicloElapsed = 0;
        }
        cicloPaused = false;
        cicloTimerInterval = setInterval(cicloTimerTick, 250);
        btn.textContent = '⏸ Pausar';
        btn.style.background = '#fab387';
        stopBtn.style.display = 'inline-block';
        cicloTimerTick();
    }
}
function cicloTimerTick() {
    if (!cicloStartedAt)
        return;
    cicloElapsed = Math.floor((Date.now() - cicloStartedAt) / 1000);
    const h = String(Math.floor(cicloElapsed / 3600)).padStart(2, '0');
    const m = String(Math.floor((cicloElapsed % 3600) / 60)).padStart(2, '0');
    const s = String(cicloElapsed % 60).padStart(2, '0');
    document.getElementById('ciclo-timer-display').textContent = `${h}:${m}:${s}`;
}
async function cicloTimerStop() {
    clearInterval(cicloTimerInterval);
    cicloTimerInterval = null;
    if (cicloStartedAt)
        cicloElapsed = Math.floor((Date.now() - cicloStartedAt) / 1000);
    const hours = cicloElapsed / 3600;
    if (cicloProximoId && cicloElapsed > 30) { // Mínimo 30 segundos
        await fetch(`/api/ciclo/${cicloProximoId}/horas`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ horas: hours })
        });
    }
    cicloElapsed = 0;
    cicloStartedAt = null;
    cicloPaused = false;
    document.getElementById('ciclo-timer-display').textContent = '00:00:00';
    document.getElementById('ciclo-btn-start').textContent = '▶ Estudar';
    document.getElementById('ciclo-btn-start').style.background = '#a6e3a1';
    document.getElementById('ciclo-btn-stop').style.display = 'none';
    loadCiclo();
    loadStreakBadge();
}
async function importarCicloDoEdital() {
    // Buscar matérias do edital e oferecer seleção
    const materias = [...new Set(editalData.map(e => e.materia))].sort();
    if (materias.length === 0) {
        toast('Nenhuma matéria no edital.', 'warning');
        return;
    }
    // Verificar quais já estão no ciclo
    const cicloAtual = await fetch('/api/ciclo').then(r => r.json());
    const jaNoCliclo = new Set(cicloAtual.map(c => c.materia));
    const novas = materias.filter(m => !jaNoCliclo.has(m));
    if (novas.length === 0) {
        toast('Todas as matérias do edital já estão no ciclo.', 'info');
        return;
    }
    if (!confirm(`Importar ${novas.length} matérias do edital para o ciclo?\n\n${novas.slice(0, 10).join('\n')}${novas.length > 10 ? '\n...' : ''}`))
        return;
    for (const m of novas) {
        await fetch('/api/ciclo', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ materia: m, horas_alvo: 2.0 })
        });
    }
    toast(`${novas.length} matérias importadas!`, 'success');
    loadCiclo();
}
async function addCiclo() {
    const m = document.getElementById('ciclo-materia-input').value.trim();
    const h = parseFloat(document.getElementById('ciclo-horas-input').value) || 2;
    if (!m) {
        toast('Preencha a matéria.', 'warning');
        return;
    }
    await fetch('/api/ciclo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ materia: m, horas_alvo: h }) });
    document.getElementById('ciclo-materia-input').value = '';
    loadCiclo();
}
async function deleteCiclo(id) {
    undoableDelete('Matéria do ciclo', `/api/ciclo/${id}`, (deleted) => {
        if (deleted)
            loadCiclo();
    });
}
async function resetarCiclo() { if (confirm('Resetar todas as horas cumpridas?')) {
    await fetch('/api/ciclo/resetar', { method: 'POST' });
    loadCiclo();
    toast('Horas resetadas!', 'success');
} }
loadCiclo();
// ==================== TAB 4: FLASHCARDS ====================
let flashcardsToday = [], currentFlashIndex = 0;
async function loadFlashcardsToday() {
    try {
        flashcardsToday = await fetch('/api/flashcards/today').then(r => r.json());
        currentFlashIndex = 0;
        showCurrentFlashcard();
    }
    catch (e) {
        toast('Erro ao carregar flashcards de hoje', 'error');
    }
}
function showCurrentFlashcard() {
    const q = document.getElementById('flash-question'), a = document.getElementById('flash-answer');
    const rb = document.getElementById('flash-reveal-btn'), rv = document.getElementById('flash-review-btns');
    if (currentFlashIndex >= flashcardsToday.length) {
        q.innerHTML = '<span style="color:#a6e3a1;font-size:1.3rem;font-weight:600;">🎉 Não há revisões pendentes para hoje!</span>';
        a.style.display = 'none';
        rb.style.display = 'none';
        rv.style.display = 'none';
        return;
    }
    const card = flashcardsToday[currentFlashIndex];
    q.textContent = card.pergunta;
    a.textContent = card.resposta;
    a.style.display = 'none';
    rb.style.display = 'inline-block';
    rv.style.display = 'none';
}
function revealAnswer() {
    document.getElementById('flash-answer').style.display = 'block';
    document.getElementById('flash-reveal-btn').style.display = 'none';
    const rv = document.getElementById('flash-review-btns');
    rv.style.display = 'flex';
    rv.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;width:100%;">
      <button onclick="reviewFlashcard(0)" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">0•Esqueci</button>
      <button onclick="reviewFlashcard(1)" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">1•Errei</button>
      <button onclick="reviewFlashcard(2)" style="background:#fab387;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">2•Quase</button>
      <button onclick="reviewFlashcard(3)" style="background:#f9e2af;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">3•Difícil</button>
      <button onclick="reviewFlashcard(4)" style="background:#a6e3a1;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">4•Bom</button>
      <button onclick="reviewFlashcard(5)" style="background:#a6e3a1;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">5•Fácil</button>
    </div>
  `;
}
async function reviewFlashcard(quality) {
    const card = flashcardsToday[currentFlashIndex];
    if (!card)
        return;
    try {
        const data = await api(`/api/flashcards/${card.id}/review-sm2`, {
            method: 'POST',
            body: { quality: quality }
        });
        const msgs = [
            'Esqueceu — recomeçar',
            'Quase — recomeçar',
            'Errou — recomeçar',
            'Difícil — +1d',
            'Bom — +' + data.intervalo_dias + 'd',
            'Fácil — +' + data.intervalo_dias + 'd'
        ];
        toast(`${msgs[quality]} (EF: ${data.easiness_factor.toFixed(2)})`, quality >= 3 ? 'success' : 'warning', 3000);
        currentFlashIndex++;
        showCurrentFlashcard();
        loadAllFlashcards();
        loadStreakBadge();
    }
    catch (e) {
        toast('Erro ao revisar', 'error');
    }
}
async function addFlashcard() {
    const p = document.getElementById('flash-pergunta').value.trim(), r = document.getElementById('flash-resposta').value.trim();
    if (!p || !r) {
        toast('Preencha pergunta e resposta.', 'warning');
        return;
    }
    await fetch('/api/flashcards', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pergunta: p, resposta: r }) });
    document.getElementById('flash-pergunta').value = '';
    document.getElementById('flash-resposta').value = '';
    toast('Flashcard criado!', 'success');
    loadFlashcardsToday();
    loadAllFlashcards();
}
async function loadAllFlashcards() {
    showLoading('flash-list');
    try {
        const all = await fetch('/api/flashcards').then(r => r.json());
        document.getElementById('flash-count').textContent = `Total: ${all.length} flashcard(s)`;
        if (all.length === 0) {
            showEmpty('flash-list', '🧠', 'Nenhum flashcard criado. Crie perguntas e respostas para revisar com repetição espaçada!');
        }
        else {
            document.getElementById('flash-list').innerHTML = all.map(c => `
        <div class="flash-list-item"><span style="flex:1;color:#cdd6f4;">${escapeHtml(c.pergunta)}</span><button class="flash-list-delete" onclick="deleteFlashcard(${c.id})">🗑</button></div>
      `).join('');
        }
    }
    catch (e) {
        toast('Erro ao carregar flashcards', 'error');
    }
}
async function deleteFlashcard(id) {
    undoableDelete('Flashcard', `/api/flashcards/${id}`, (deleted) => {
        if (deleted) {
            loadAllFlashcards();
            loadFlashcardsToday();
        }
    });
}
loadFlashcardsToday();
loadAllFlashcards();
// ==================== TAB 5: METAS ====================
async function loadMetas() {
    try {
        const data = await fetch('/api/metas').then(r => r.json());
        const cfg = data.config;
        const prog = data.progresso;
        document.getElementById('meta-horas').value = cfg.meta_horas;
        document.getElementById('meta-questoes').value = cfg.meta_questoes;
        document.getElementById('meta-flashcards').value = cfg.meta_flashcards;
        document.getElementById('meta-paginas').value = cfg.meta_paginas;
        const progEl = document.getElementById('metas-progresso');
        const items = [
            { icon: '⏱', label: 'Horas', val: prog.horas.toFixed(1), meta: cfg.meta_horas, pct: Math.min(100, (prog.horas / cfg.meta_horas) * 100), color: '#89b4fa' },
            { icon: '❓', label: 'Questões', val: prog.questoes, meta: cfg.meta_questoes, pct: Math.min(100, (prog.questoes / cfg.meta_questoes) * 100), color: '#a6e3a1' },
            { icon: '🧠', label: 'Flashcards', val: prog.flashcards, meta: cfg.meta_flashcards, pct: Math.min(100, (prog.flashcards / cfg.meta_flashcards) * 100), color: '#cba6f7' },
        ];
        progEl.innerHTML = items.map(m => `
      <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #45475a;">
        <span style="font-size:1.2rem;">${m.icon}</span>
        <span style="min-width:80px;font-size:0.88rem;">${m.label}</span>
        <div style="flex:1;height:8px;background:#45475a;border-radius:4px;overflow:hidden;"><div style="height:100%;width:${m.pct}%;background:${m.color};border-radius:4px;"></div></div>
        <span style="font-size:0.85rem;font-weight:700;color:${m.color};min-width:70px;text-align:right;">${m.val}/${m.meta}</span>
      </div>
    `).join('');
        // Mini dots no header
        document.getElementById('meta-dot-h').className = 'meta-dot' + (items[0].pct >= 100 ? ' done' : items[0].pct > 0 ? ' partial' : '');
        document.getElementById('meta-dot-q').className = 'meta-dot' + (items[1].pct >= 100 ? ' done' : items[1].pct > 0 ? ' partial' : '');
        document.getElementById('meta-dot-f').className = 'meta-dot' + (items[2].pct >= 100 ? ' done' : items[2].pct > 0 ? ' partial' : '');
    }
    catch (e) {
        toast('Erro ao carregar metas', 'error');
    }
}
async function salvarMetas() {
    try {
        await fetch('/api/metas', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
                meta_horas: parseFloat(document.getElementById('meta-horas').value),
                meta_questoes: parseInt(document.getElementById('meta-questoes').value),
                meta_flashcards: parseInt(document.getElementById('meta-flashcards').value),
                meta_paginas: parseInt(document.getElementById('meta-paginas').value),
            }) });
        toast('Metas salvas!', 'success');
        loadMetas();
    }
    catch (e) {
        toast('Erro ao salvar metas', 'error');
    }
}
async function loadStreakBadge() {
    try {
        const data = await fetch('/api/streaks').then(r => r.json());
        document.getElementById('streak-num').textContent = data.streak_atual;
        const streakEl = document.getElementById('metas-streak');
        if (streakEl) {
            streakEl.innerHTML = `
        <div style="display:flex;align-items:center;gap:16px;">
          <span style="font-size:2.5rem;">🔥</span>
          <div><div style="font-size:1.6rem;font-weight:700;color:#fab387;">${data.streak_atual} dias</div><div style="font-size:0.85rem;color:#9399b2;">consecutivos de estudo</div></div>
          <div style="margin-left:auto;text-align:right;"><div style="font-size:1.2rem;font-weight:700;color:#a6e3a1;">${data.melhor_streak}</div><div style="font-size:0.75rem;color:#9399b2;">recorde</div></div>
        </div>
      `;
        }
    }
    catch (e) {
        // Silently fail for streaks - non-critical
    }
}
loadMetas();
loadStreakBadge();
// ==================== PWA ====================
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => { });
}
// ==================== COUNTDOWN ====================
async function loadCountdown() {
    try {
        const provas = await fetch('/api/countdown').then(r => r.json());
        if (!provas.length)
            return;
        const now = new Date();
        const favorito = localStorage.getItem('countdown_favorito'); // "edital|cargo"
        // Parsear datas
        const parsed = provas.map(p => {
            let parts = p.data_objetiva.match(/(\d+)[\/\-](\d+)[\/\-](\d+)/);
            if (!parts)
                return null;
            let d;
            if (parts[3].length === 4)
                d = new Date(parts[3], parts[2] - 1, parts[1]);
            else
                d = new Date(parts[1], parts[2] - 1, parts[3]);
            const diff = Math.ceil((d - now) / 86400000);
            return diff > 0 ? { ...p, date: d, days: diff } : null;
        }).filter(Boolean);
        if (!parsed.length)
            return;
        // Usar favorito ou a mais próxima
        let selected = null;
        if (favorito) {
            selected = parsed.find(p => `${p.edital}|${p.cargo}` === favorito);
        }
        if (!selected) {
            selected = parsed.sort((a, b) => a.days - b.days)[0];
        }
        const el = document.getElementById('countdown-badge');
        if (el) {
            el.innerHTML = `<span class="countdown-icon">⏳</span><span class="countdown-text">${escapeHtml(selected.cargo)}: <strong>${selected.days}d</strong></span><span class="countdown-fav" title="Alterar cargo favorito">⭐</span>`;
            el.onclick = () => showCountdownPicker(parsed);
        }
    }
    catch (e) { }
}
function showCountdownPicker(provas) {
    openSelectModal('⏳ Escolher prova para countdown', provas.map((p, i) => ({
        icon: '📅',
        label: `${p.edital} - ${p.cargo}`,
        sub: `${p.days} dias restantes`,
        value: i
    })).concat([{ icon: '🔄', label: 'Automático (mais próxima)', sub: 'Seleciona sempre a prova mais próxima', value: -1 }]), (choice) => {
        if (choice.value === -1) {
            localStorage.removeItem('countdown_favorito');
        }
        else {
            const p = provas[choice.value];
            localStorage.setItem('countdown_favorito', `${p.edital}|${p.cargo}`);
        }
        loadCountdown();
    });
}
loadCountdown();
setInterval(loadCountdown, 60000);
// ==================== THEME TOGGLE ====================
function toggleTheme() {
    const body = document.body;
    const isDark = body.classList.toggle('light-theme');
    localStorage.setItem('theme', isDark ? 'light' : 'dark');
    document.querySelector('meta[name=theme-color]').content = isDark ? '#eff1f5' : '#1e1e2e';
}
if (localStorage.getItem('theme') === 'light')
    document.body.classList.add('light-theme');
// ==================== GAMIFICATION BADGE ====================
async function loadXpBadge() {
    try {
        const data = await fetch('/api/gamification').then(r => r.json());
        const el = document.getElementById('xp-badge');
        if (el)
            el.innerHTML = `<span class="xp-level">Lv.${data.nivel}</span><div class="xp-bar-mini"><div class="xp-bar-mini-fill" style="width:${data.pct_nivel}%"></div></div><span style="color:#9399b2;">${data.xp}xp</span>`;
    }
    catch (e) { }
}
loadXpBadge();
// ==================== BROWSER NOTIFICATIONS ====================
async function checkNotifications() {
    if (!('Notification' in window))
        return;
    if (Notification.permission === 'default') {
        Notification.requestPermission();
    }
    if (Notification.permission !== 'granted')
        return;
    try {
        const notifs = await fetch('/api/notificacoes').then(r => r.json());
        if (notifs.length > 0 && !sessionStorage.getItem('notif_shown_today')) {
            const alta = notifs.find(n => n.prioridade === 'alta');
            if (alta) {
                new Notification('ConcurseiroOS', { body: alta.msg, icon: '/icon.svg' });
                sessionStorage.setItem('notif_shown_today', '1');
            }
        }
    }
    catch (e) { }
}
setTimeout(checkNotifications, 3000);
// ==================== NOTAS POR TÓPICO ====================
let noteCurrentId = null;
// ==================== VINCULAR PDF A TÓPICO ====================
async function linkPdfToTopic(id, materia) {
    const tree = await fetch('/api/tree').then(r => r.json());
    const pdfs = [];
    function extractPdfs(nodes, prefix) {
        for (const n of nodes) {
            if (n.type === 'pdf')
                pdfs.push(prefix ? `${prefix}/${n.name}` : n.name);
            else if (n.type === 'folder')
                extractPdfs(n.children, prefix ? `${prefix}/${n.name}` : n.name);
        }
    }
    extractPdfs(tree, '');
    if (pdfs.length === 0) {
        toast('Nenhum PDF disponível. Adicione PDFs na pasta backend/pdfs/', 'warning');
        return;
    }
    openSelectModal(`📖 Vincular PDF a "${materia}"`, pdfs.map(p => ({
        icon: '📄',
        label: p.split('/').pop().replace(/_/g, ' ').replace('.pdf', ''),
        sub: p.includes('/') ? p.split('/').slice(0, -1).join('/') : '',
        value: p
    })), async (choice) => {
        const pdfPath = choice.value;
        const pagina = 1;
        await fetch(`/api/edital/${id}/pdf`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pdf_link: pdfPath, pdf_pagina: pagina })
        });
        loadEdital();
    });
}
// Vincular PDF em bulk (toda a matéria de uma vez)
async function linkPdfToMateria(materia, editalNome, cargo) {
    const tree = await fetch('/api/tree').then(r => r.json());
    const pdfs = [];
    function extractPdfs(nodes, prefix) {
        for (const n of nodes) {
            if (n.type === 'pdf')
                pdfs.push(prefix ? `${prefix}/${n.name}` : n.name);
            else if (n.type === 'folder')
                extractPdfs(n.children, prefix ? `${prefix}/${n.name}` : n.name);
        }
    }
    extractPdfs(tree, '');
    if (pdfs.length === 0) {
        toast('Nenhum PDF disponível.', 'warning');
        return;
    }
    openSelectModal(`🔗 Vincular PDF a "${materia}"`, pdfs.map(p => ({
        icon: '📄',
        label: p.split('/').pop().replace(/_/g, ' ').replace('.pdf', ''),
        sub: p.includes('/') ? p.split('/').slice(0, -1).join('/') : '',
        value: p
    })), async (choice) => {
        await fetch(`/api/edital/vincular-bulk?materia=${encodeURIComponent(materia)}&pdf_link=${encodeURIComponent(choice.value)}&edital_nome=${encodeURIComponent(editalNome || '')}&cargo=${encodeURIComponent(cargo || '')}`, { method: 'PUT' });
        loadEdital();
    });
}
// Desvincular PDF diretamente (botão ❌ na tela de PDFs)
async function unlinkPdf(pdfPath) {
    const vinculado = editalData.find(e => e.pdf_link === pdfPath);
    if (!confirm(`Desvincular "${pdfPath.split('/').pop()}" de "${vinculado?.materia || 'disciplina'}"?`))
        return;
    await fetch(`/api/edital/desvincular-pdf?pdf_link=${encodeURIComponent(pdfPath)}`, { method: 'PUT' });
    editalData = await fetch('/api/edital').then(r => r.json());
    await load();
}
// Vincular PDF a uma disciplina (da tela de PDFs)
async function linkPdfToDisc(pdfPath) {
    const materias = [...new Set(editalData.map(e => e.materia))].sort();
    if (materias.length === 0) {
        toast('Nenhuma disciplina cadastrada no edital.', 'warning');
        return;
    }
    openSelectModal(`🔗 Vincular "${pdfPath.split('/').pop()}"`, materias.map(m => ({
        icon: '📚',
        label: m,
        sub: `${editalData.filter(e => e.materia === m).length} tópicos`,
        value: m
    })), async (choice) => {
        const materia = choice.value;
        // Verificar se precisa escolher edital/cargo
        const editaisCargos = [...new Set(editalData.filter(e => e.materia === materia).map(e => `${e.edital_nome}|${e.cargo}`))];
        let editalNome = '', cargo = '';
        if (editaisCargos.length > 1) {
            openSelectModal(`📋 "${materia}" existe em vários editais`, editaisCargos.map(ec => {
                const [e, c] = ec.split('|');
                return { icon: '👤', label: `${e} - ${c}`, sub: '', value: ec };
            }).concat([{ icon: '📌', label: 'Todos os editais', sub: 'Vincular em todas as ocorrências', value: '' }]), async (ch2) => {
                if (ch2.value) {
                    [editalNome, cargo] = ch2.value.split('|');
                }
                await fetch(`/api/edital/vincular-bulk?materia=${encodeURIComponent(materia)}&pdf_link=${encodeURIComponent(pdfPath)}&edital_nome=${encodeURIComponent(editalNome)}&cargo=${encodeURIComponent(cargo)}`, { method: 'PUT' });
                editalData = await fetch('/api/edital').then(r => r.json());
                await load();
            });
        }
        else {
            await fetch(`/api/edital/vincular-bulk?materia=${encodeURIComponent(materia)}&pdf_link=${encodeURIComponent(pdfPath)}`, { method: 'PUT' });
            editalData = await fetch('/api/edital').then(r => r.json());
            await load();
        }
    });
}
function openNoteModal(id) {
    noteCurrentId = id;
    document.getElementById('note-modal').classList.add('show');
    loadNotesForTopic(id);
}
function closeNoteModal() {
    document.getElementById('note-modal').classList.remove('show');
    noteCurrentId = null;
}
async function loadNotesForTopic(id) {
    const notes = await fetch(`/api/edital/${id}/notas`).then(r => r.json());
    const list = document.getElementById('note-modal-list');
    list.innerHTML = notes.map(n => `
    <div class="nota-item">
      <span class="nota-text">${escapeHtml(n.conteudo)}</span>
      <button class="nota-del" onclick="deleteNote(${n.id})">×</button>
    </div>
  `).join('');
}
async function saveNote() {
    const text = document.getElementById('note-modal-input').value.trim();
    if (!text)
        return;
    await fetch(`/api/edital/${noteCurrentId}/notas`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ edital_id: noteCurrentId, conteudo: text })
    });
    document.getElementById('note-modal-input').value = '';
    loadNotesForTopic(noteCurrentId);
}
async function deleteNote(id) {
    await fetch(`/api/notas-topico/${id}`, { method: 'DELETE' });
    loadNotesForTopic(noteCurrentId);
}
// Close modal on outside click
document.getElementById('note-modal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay'))
        closeNoteModal();
});
// ==================== MODAL DE SELEÇÃO GENÉRICO ====================
let selectModalCallback = null;
function openSelectModal(title, items, callback) {
    selectModalCallback = callback;
    document.getElementById('select-modal-title').textContent = title;
    document.getElementById('select-modal-search').value = '';
    renderSelectItems(items);
    document.getElementById('select-modal').classList.add('show');
    setTimeout(() => document.getElementById('select-modal-search').focus(), 100);
    // Filtro de busca
    document.getElementById('select-modal-search').oninput = (e) => {
        const q = e.target.value.toLowerCase();
        const filtered = items.filter(i => i.label.toLowerCase().includes(q) || (i.sub || '').toLowerCase().includes(q));
        renderSelectItems(filtered);
    };
}
function renderSelectItems(items) {
    const list = document.getElementById('select-modal-list');
    list.innerHTML = items.map((item, i) => `
    <div class="select-item" data-index="${i}" onclick="selectModalChoice(${i})">
      <span class="si-icon">${item.icon || ''}</span>
      <span class="si-label">${escapeHtml(item.label)}</span>
      <span class="si-sub">${escapeHtml(item.sub || '')}</span>
    </div>
  `).join('');
    // Guardar items para referência
    list._items = items;
}
function selectModalChoice(index) {
    const list = document.getElementById('select-modal-list');
    const item = list._items[index];
    closeSelectModal();
    if (selectModalCallback)
        selectModalCallback(item);
}
function closeSelectModal() {
    document.getElementById('select-modal').classList.remove('show');
    selectModalCallback = null;
}
document.getElementById('select-modal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay'))
        closeSelectModal();
});
// ==================== ARQUIVAR / EXCLUIR EDITAIS ====================
async function arquivarCargo(editalNome, cargo) {
    if (!confirm(`Arquivar "${cargo}" de "${editalNome}"?\n\nOs tópicos não serão excluídos, apenas ocultados.`))
        return;
    await fetch(`/api/edital/arquivar?edital_nome=${encodeURIComponent(editalNome)}&cargo=${encodeURIComponent(cargo)}`, { method: 'PUT' });
    editalData = await fetch('/api/edital').then(r => r.json());
    renderEditalTree();
    toast('Cargo arquivado!', 'success');
}
async function excluirCargo(editalNome, cargo) {
    if (!confirm(`⚠️ EXCLUIR PERMANENTEMENTE "${cargo}" de "${editalNome}"?\n\nEsta ação não pode ser desfeita!`))
        return;
    if (!confirm(`Tem certeza? Todos os tópicos, notas e vínculos serão perdidos.`))
        return;
    await fetch(`/api/edital/excluir-edital?edital_nome=${encodeURIComponent(editalNome)}&cargo=${encodeURIComponent(cargo)}`, { method: 'DELETE' });
    editalData = await fetch('/api/edital').then(r => r.json());
    renderEditalTree();
    toast('Cargo excluído permanentemente', 'success');
}
async function arquivarConcurso(editalNome) {
    if (!confirm(`Arquivar TODO o concurso "${editalNome}" (todos os cargos)?\n\nOs dados não serão excluídos, apenas ocultados.`))
        return;
    await fetch(`/api/edital/arquivar?edital_nome=${encodeURIComponent(editalNome)}`, { method: 'PUT' });
    editalData = await fetch('/api/edital').then(r => r.json());
    renderEditalTree();
    toast('Concurso arquivado!', 'success');
}
async function excluirConcurso(editalNome) {
    if (!confirm(`⚠️ EXCLUIR PERMANENTEMENTE TODO o concurso "${editalNome}"?\n\nTodos os cargos, tópicos, notas e vínculos serão perdidos!`))
        return;
    if (!confirm(`ÚLTIMA CONFIRMAÇÃO: excluir "${editalNome}" por completo? Isso é irreversível.`))
        return;
    await fetch(`/api/edital/excluir-edital?edital_nome=${encodeURIComponent(editalNome)}`, { method: 'DELETE' });
    editalData = await fetch('/api/edital').then(r => r.json());
    renderEditalTree();
    toast('Concurso excluído permanentemente', 'success');
}
async function showArquivados() {
    const arquivados = await fetch('/api/edital/arquivados').then(r => r.json());
    if (arquivados.length === 0) {
        toast('Nenhum edital arquivado.', 'info');
        return;
    }
    openSelectModal('📦 Editais Arquivados — Desarquivar', arquivados.map(a => ({
        icon: '📦',
        label: `${a.edital_nome} - ${a.cargo}`,
        sub: `${a.total} tópicos`,
        value: a
    })), async (choice) => {
        const a = choice.value;
        await fetch(`/api/edital/desarquivar?edital_nome=${encodeURIComponent(a.edital_nome)}&cargo=${encodeURIComponent(a.cargo)}`, { method: 'PUT' });
        editalData = await fetch('/api/edital').then(r => r.json());
        renderEditalTree();
        toast('Edital desarquivado!', 'success');
    });
}
// ==================== MODO FOCO ====================
function enterFocusMode() {
    const el = document.documentElement;
    if (el.requestFullscreen)
        el.requestFullscreen();
    else if (el.webkitRequestFullscreen)
        el.webkitRequestFullscreen();
    document.body.classList.add('focus-mode');
    // Show only the edital tab
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector('[data-tab="tab-edital"]').classList.add('active');
    document.getElementById('tab-edital').classList.add('active');
    // Hide non-essential elements
    document.getElementById('header').style.display = 'none';
    document.querySelector('.nav-links').style.display = 'none';
    document.getElementById('tab-bar').style.display = 'none';
    // Show exit button
    if (!document.getElementById('exit-focus-btn')) {
        const btn = document.createElement('button');
        btn.id = 'exit-focus-btn';
        btn.className = 'iobtn';
        btn.style.cssText = 'position:fixed;top:12px;right:12px;z-index:9999;background:#f38ba8;color:#1e1e2e;';
        btn.textContent = '✕ Sair do Foco';
        btn.onclick = exitFocusMode;
        document.body.appendChild(btn);
    }
}
function exitFocusMode() {
    if (document.exitFullscreen)
        document.exitFullscreen();
    else if (document.webkitExitFullscreen)
        document.webkitExitFullscreen();
    document.body.classList.remove('focus-mode');
    document.getElementById('header').style.display = '';
    document.querySelector('.nav-links').style.display = '';
    document.getElementById('tab-bar').style.display = '';
    const btn = document.getElementById('exit-focus-btn');
    if (btn)
        btn.remove();
}
document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement)
        exitFocusMode();
});
// ==================== REVISÃO ESPAÇADA UI ====================
// Add SRS button to tree topics (enhance the existing tree-leaf render)
document.addEventListener('dblclick', async (e) => {
    const leaf = e.target.closest('.tree-leaf');
    if (!leaf)
        return;
    const id = leaf.dataset.id;
    if (!id)
        return;
    if (confirm('Agendar revisão espaçada para este tópico?')) {
        const res = await fetch(`/api/edital/${id}/agendar-revisao`, { method: 'POST' }).then(r => r.json());
        toast(`Revisão agendada para: ${res.proxima_revisao} (intervalo: ${res.intervalo} dias)`, 'success');
    }
});
// ==================== ACCESSIBILITY: FOCUS MANAGEMENT ====================
function trapFocus(element) {
    const focusable = element.querySelectorAll('button, input, textarea, select, a[href], [tabindex]:not([tabindex="-1"])');
    if (focusable.length === 0)
        return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    first.focus();
    element.addEventListener('keydown', (e) => {
        if (e.key !== 'Tab')
            return;
        if (e.shiftKey) {
            if (document.activeElement === first) {
                e.preventDefault();
                last.focus();
            }
        }
        else {
            if (document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    });
}
// ==================== CONFETTI EFFECT ====================
function launchConfetti(duration = 2000) {
    const canvas = document.createElement('canvas');
    canvas.id = 'confetti-canvas';
    document.body.appendChild(canvas);
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const colors = ['#a6e3a1', '#f38ba8', '#89b4fa', '#fab387', '#cba6f7', '#f9e2af'];
    const particles = Array.from({ length: 80 }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height - canvas.height,
        size: Math.random() * 8 + 4,
        color: colors[Math.floor(Math.random() * colors.length)],
        speed: Math.random() * 3 + 2,
        angle: Math.random() * Math.PI * 2,
        spin: (Math.random() - 0.5) * 0.2
    }));
    const start = Date.now();
    function draw() {
        if (Date.now() - start > duration) {
            canvas.remove();
            return;
        }
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        for (const p of particles) {
            p.y += p.speed;
            p.x += Math.sin(p.angle) * 0.5;
            p.angle += p.spin;
            ctx.fillStyle = p.color;
            ctx.fillRect(p.x, p.y, p.size, p.size * 0.6);
        }
        requestAnimationFrame(draw);
    }
    draw();
}
// ==================== ONBOARDING / FIRST USE ====================
function checkFirstUse() {
    if (localStorage.getItem('concurseiro_onboarded'))
        return;
    // Mostrar welcome modal
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.style.display = 'flex';
    overlay.id = 'onboarding-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.innerHTML = `
    <div class="modal-box" style="max-width:500px;text-align:center;">
      <div style="font-size:3rem;margin-bottom:12px;">🎓</div>
      <h2 style="color:#cba6f7;margin-bottom:12px;">Bem-vindo ao ConcurseiroOS!</h2>
      <p style="color:#9399b2;margin-bottom:20px;line-height:1.6;">
        Seu sistema completo de estudos para concursos públicos.<br>
        Aqui você pode ler PDFs, gerenciar editais, criar flashcards,<br>
        resolver questões e acompanhar seu progresso.
      </p>
      <div style="text-align:left;background:#1e1e2e;border-radius:8px;padding:16px;margin-bottom:20px;font-size:0.85rem;">
        <div style="margin-bottom:8px;"><strong>🚀 Dicas rápidas:</strong></div>
        <div style="margin-bottom:6px;">• <kbd>Ctrl+K</kbd> — Busca rápida em tópicos</div>
        <div style="margin-bottom:6px;">• <kbd>Alt+1-5</kbd> — Trocar entre abas</div>
        <div style="margin-bottom:6px;">• <kbd>Shift+?</kbd> — Ver todos os atalhos</div>
        <div>• O timer registra horas de estudo automaticamente</div>
      </div>
      <button class="iobtn" style="background:#cba6f7;color:#1e1e2e;padding:10px 32px;font-size:1rem;" onclick="dismissOnboarding()">Começar a Estudar! 💪</button>
    </div>
  `;
    document.body.appendChild(overlay);
    trapFocus(overlay);
}
function dismissOnboarding() {
    localStorage.setItem('concurseiro_onboarded', '1');
    const el = document.getElementById('onboarding-overlay');
    if (el)
        el.remove();
    toast('Bons estudos! Use Shift+? para ver os atalhos.', 'info', 5000);
}
// Verificar primeiro uso após carregar
setTimeout(checkFirstUse, 500);
// ==================== EXPORT FUNCTIONS ====================
function exportarEdital(formato) {
    window.open(`/api/edital/exportar?formato=${formato}`, '_blank');
}
function exportarCiclo(formato) {
    window.open(`/api/ciclo/exportar?formato=${formato}`, '_blank');
}
function exportarFlashcards(formato) {
    window.open(`/api/flashcards/exportar?formato=${formato}`, '_blank');
}
// ==================== IMPORT FUNCTIONS ====================
async function importarEditalFile(input) {
    const file = input.files?.[0];
    if (!file)
        return;
    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/api/edital/importar', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.ok) {
            toast(`Importados ${data.importados} tópicos do edital!`, 'success');
            loadEdital();
        }
        else {
            toast('Erro ao importar edital', 'error');
        }
    }
    catch (e) {
        toast('Erro ao importar edital', 'error');
    }
    input.value = '';
}
async function importarCicloFile(input) {
    const file = input.files?.[0];
    if (!file)
        return;
    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/api/ciclo/importar', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.ok) {
            toast(`Importadas ${data.importados} matérias no ciclo!`, 'success');
            loadCiclo();
        }
        else {
            toast('Erro ao importar ciclo', 'error');
        }
    }
    catch (e) {
        toast('Erro ao importar ciclo', 'error');
    }
    input.value = '';
}
async function importarFlashcardsFile(input) {
    const file = input.files?.[0];
    if (!file)
        return;
    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/api/flashcards/importar', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.ok) {
            toast(`Importados ${data.importados} flashcards!`, 'success');
            loadAllFlashcards();
            loadFlashcardsToday();
        }
        else {
            toast('Erro ao importar flashcards', 'error');
        }
    }
    catch (e) {
        toast('Erro ao importar flashcards', 'error');
    }
    input.value = '';
}
