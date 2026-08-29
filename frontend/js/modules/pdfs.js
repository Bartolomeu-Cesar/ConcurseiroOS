// ==================== TAB 1: PDFs ====================
import { state } from './state.js';
import { escapeHtml, showLoading, showEmpty, toast, confirmModal, promptModal } from './utils.js';

const API = '';
const OPEN_KEY = 'folders_open';
const TIMER_KEY = 'leitor_timer_state';
const TIMER_LIMIT_KEY = 'leitor_timer_limit_min';

function getOpenFolders() {
  try { return new Set(JSON.parse(sessionStorage.getItem(OPEN_KEY)) || []); }
  catch { return new Set(); }
}

function saveOpenFolders(set) { sessionStorage.setItem(OPEN_KEY, JSON.stringify([...set])); }

// Dependências injetadas em init
let _linkPdfToDisc = null;
let _unlinkPdf = null;

export async function load() {
  showLoading('tree');
  try {
    const [tree, bulk] = await Promise.all([
      fetch(`${API}/api/tree`).then(r => r.json()),
      fetch(`${API}/api/progress-bulk`).then(r => r.json())
    ]);
    // Always reload edital data for vinculo display
    try { state.editalData = await fetch('/api/edital').then(r => r.json()); }
    catch (e) { state.editalData = []; }
    document.getElementById('tree').innerHTML = '';
    renderNodes(tree, document.getElementById('tree'), bulk, '');
    if (tree.length === 0) {
      showEmpty('tree', '📚', 'Nenhum PDF encontrado. Adicione arquivos PDF na pasta backend/pdfs/ para começar!');
    }
  } catch (e) {
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
    } else if (n.type === 'folder') {
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
      if (getOpenFolders().has(path)) children.classList.add('open');
      header.addEventListener('click', () => {
        children.classList.toggle('open');
        const updated = getOpenFolders();
        if (children.classList.contains('open')) updated.add(path);
        else updated.delete(path);
        saveOpenFolders(updated);
      });
      renderNodes(node.children, children, bulk, path);
      container.appendChild(div);
    } else if (node.type === 'pdf') {
      const prog = bulk[path];
      const tp = prog ? prog.total_pages : null;
      const cp = prog ? prog.current_page : 1;
      const pct = tp ? (cp >= tp ? 100 : Math.round((cp / tp) * 100)) : 0;
      const label = tp ? `pág. ${cp}/${tp} (${pct}%)` : 'não lido';
      const vinculado = state.editalData.find(e => e.pdf_link === path);
      const materiaTag = vinculado ? `<span class="pdf-materia-tag">${escapeHtml(vinculado.materia)}</span>` : '';
      const linkBtn = vinculado
        ? `<button class="pdf-link-disc-btn pdf-unlink" onclick="event.stopPropagation();unlinkPdf('${path.replace(/'/g, "\\'")}')" title="Desvincular disciplina" aria-label="Desvincular disciplina">❌</button>`
        : `<button class="pdf-link-disc-btn" onclick="event.stopPropagation();linkPdfToDisc('${path.replace(/'/g, "\\'")}')" title="Vincular a disciplina">🔗</button>`;
      const div = document.createElement('div');
      div.innerHTML = `
        <div class="pdf-item" data-path="${path}" style="background:linear-gradient(to right, rgba(137,220,235,0.25) ${pct}%, transparent ${pct}%);">
          <span>📄</span>
          <span class="pdf-name">${escapeHtml(node.name.replace(/_/g, ' '))}</span>
          ${materiaTag}
          <span class="pdf-progress">${label}</span>
          ${pct === 100 ? '<span class="badge-done">✓</span>' : ''}
          ${linkBtn}
        </div>
      `;
      div.querySelector('.pdf-item').addEventListener('click', () => { window.open(`viewer.html?path=${encodeURIComponent(path)}`, '_blank'); });
      container.appendChild(div);
    }
  }
}

// --- Pomodoro Timer ---
let timerInterval = null, elapsed = 0, paused = false, limitSeconds = 0, startedAt = null;

function fmt(s) { return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }
function saveState() { localStorage.setItem(TIMER_KEY, JSON.stringify({ elapsed, paused, limitSeconds, startedAt, running: !!timerInterval })); }
function loadState() { try { const r = localStorage.getItem(TIMER_KEY); return r ? JSON.parse(r) : null; } catch { return null; } }
function clearState() { localStorage.removeItem(TIMER_KEY); }

function updateDisplay() {
  const display = document.getElementById('timer-display');
  if (!display) return;
  display.textContent = fmt(elapsed);
  display.classList.toggle('done', limitSeconds > 0 && elapsed >= limitSeconds);
}

function tick() {
  if (paused || !startedAt) return;
  elapsed = Math.floor((Date.now() - startedAt) / 1000);
  updateDisplay();
  saveState();
  if (elapsed >= limitSeconds) stopTimer(true);
}

function startTimer(fromContinue = false) {
  const select = document.getElementById('timer-select');
  const btnStart = document.getElementById('btn-start');
  const btnPause = document.getElementById('btn-pause');
  const btnStop = document.getElementById('btn-stop');

  limitSeconds = fromContinue ? limitSeconds : parseInt(select.value, 10) * 60;
  if (!fromContinue) {
    localStorage.setItem(TIMER_LIMIT_KEY, select.value);
    elapsed = 0;
    startedAt = Date.now();
  } else {
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
  const btnPause = document.getElementById('btn-pause');
  const btnStart = document.getElementById('btn-start');
  if (!timerInterval) return;
  clearInterval(timerInterval);
  timerInterval = null;
  paused = true;
  if (startedAt) elapsed = Math.floor((Date.now() - startedAt) / 1000);
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
  const display = document.getElementById('timer-display');
  const select = document.getElementById('timer-select');
  const btnStart = document.getElementById('btn-start');
  const btnPause = document.getElementById('btn-pause');
  const btnStop = document.getElementById('btn-stop');
  if (display) { display.textContent = '00:00:00'; display.classList.remove('done'); }
  if (select) select.disabled = false;
  if (btnStart) { btnStart.textContent = '▶ Iniciar'; btnStart.disabled = false; }
  if (btnPause) { btnPause.textContent = '⏸ Pausar'; btnPause.disabled = true; }
  if (btnStop) btnStop.disabled = true;
  clearState();
  localStorage.setItem('leitor_timer_finished', Date.now().toString());
  if (showOverlay) document.getElementById('overlay').style.display = 'flex';
}

function restoreTimer() {
  const display = document.getElementById('timer-display');
  const select = document.getElementById('timer-select');
  const btnStart = document.getElementById('btn-start');
  const btnPause = document.getElementById('btn-pause');
  const btnStop = document.getElementById('btn-stop');
  if (!display) return;

  const timerState = loadState();
  if (!timerState) {
    elapsed = 0; paused = false; startedAt = null; limitSeconds = 0;
    display.textContent = '00:00:00'; display.classList.remove('done');
    select.disabled = false;
    btnStart.textContent = '▶ Iniciar'; btnStart.disabled = false;
    btnPause.disabled = true; btnStop.disabled = true;
    return;
  }
  elapsed = timerState.elapsed || 0;
  paused = timerState.paused || false;
  limitSeconds = timerState.limitSeconds || 0;
  startedAt = timerState.startedAt || null;
  if (timerState.running && !paused && startedAt) {
    select.disabled = true;
    btnStart.disabled = true;
    btnPause.disabled = false;
    btnStop.disabled = false;
    elapsed = Math.floor((Date.now() - startedAt) / 1000);
    updateDisplay();
    if (elapsed >= limitSeconds) { stopTimer(true); return; }
    clearInterval(timerInterval);
    timerInterval = setInterval(tick, 250);
  } else if (paused && limitSeconds > 0) {
    select.disabled = true;
    btnStart.disabled = false;
    btnStart.textContent = '▶ Continuar';
    btnPause.disabled = true;
    btnStop.disabled = false;
    updateDisplay();
  } else {
    updateDisplay();
  }
}

export function exportProgress() {
  const a = document.createElement('a');
  a.href = '/api/export';
  a.download = 'leitor_progress.json';
  a.click();
}

export async function importProgress(input) {
  const file = input.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/import', { method: 'POST', body: form });
  const data = await res.json();
  input.value = '';
  if (data.ok) { toast(`Importado! ${data.imported} registro(s).`, 'success'); load(); }
  else { toast('Erro ao importar.', 'error'); }
}

export async function uploadPdf(input) {
  const file = input.files[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    toast('Apenas arquivos PDF são aceitos.', 'error');
    input.value = '';
    return;
  }
  // Verificar limite do plano antes de upload
  if (window.checkPlanLimit && !(await window.checkPlanLimit('pdfs'))) { input.value = ''; return; }
  toast('Enviando PDF...', 'info');
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch('/api/pdfs/upload', { method: 'POST', body: form });
    const data = await res.json();
    input.value = '';
    if (data.ok) {
      toast(`PDF "${data.filename}" enviado! (${data.total_pages} páginas, ${data.size_mb}MB)`, 'success');
      load(); // Reload tree
    } else {
      toast(data.detail || 'Erro ao enviar PDF.', 'error');
    }
  } catch (e) {
    toast('Erro de conexão ao enviar PDF.', 'error');
    input.value = '';
  }
}

export function initPdfs(deps) {
  _linkPdfToDisc = deps.linkPdfToDisc;
  _unlinkPdf = deps.unlinkPdf;

  const select = document.getElementById('timer-select');
  const btnStart = document.getElementById('btn-start');
  const btnPause = document.getElementById('btn-pause');
  const btnStop = document.getElementById('btn-stop');

  if (select) {
    const savedLimit = localStorage.getItem(TIMER_LIMIT_KEY);
    if (savedLimit) select.value = savedLimit;
    select.addEventListener('change', () => { localStorage.setItem(TIMER_LIMIT_KEY, select.value); });
  }

  if (btnStart) btnStart.addEventListener('click', () => { btnStart.textContent.includes('Continuar') ? startTimer(true) : startTimer(false); });
  if (btnPause) btnPause.addEventListener('click', pauseTimer);
  if (btnStop) btnStop.addEventListener('click', () => stopTimer(false));

  restoreTimer();

  window.addEventListener('storage', (e) => {
    if (e.key === 'leitor_progress_updated') load();
    if (e.key === 'leitor_timer_finished' || e.key === 'leitor_timer_state') {
      clearInterval(timerInterval);
      timerInterval = null;
      restoreTimer();
    }
  });
  window.addEventListener('focus', () => { state.editalData = null; load(); });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { state.editalData = null; load(); } });

  load();
}


// ==================== ORGANIZAÇÃO VIRTUAL (DRAG & DROP) ====================

let _orgMode = false; // Modo organização ativo

export function toggleOrgMode() {
  _orgMode = !_orgMode;
  const btn = document.getElementById('org-mode-btn');
  if (btn) {
    btn.textContent = _orgMode ? '✅ Sair do Modo Organizar' : '📂 Organizar PDFs';
    btn.style.background = _orgMode ? 'var(--green)' : 'var(--bg-surface)';
    btn.style.color = _orgMode ? 'var(--bg)' : 'var(--text)';
  }
  if (_orgMode) {
    _loadOrganizacao();
    toast('📂 Modo Organizar ativo! Arraste PDFs para pastas.', 'info', 3000);
  } else {
    load(); // Recarrega árvore normal
  }
}

export async function criarPastaVirtual() {
  const nome = await promptModal('Nome da nova pasta:', { title: 'Nova Pasta' });
  if (!nome || !nome.trim()) return;
  try {
    await fetch('/api/pdf/pastas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome: nome.trim() })
    });
    toast(`📁 Pasta "${nome}" criada!`, 'success');
    _loadOrganizacao();
  } catch(e) { toast('Erro ao criar pasta', 'error'); }
}

async function _loadOrganizacao() {
  const container = document.getElementById('tree');
  container.innerHTML = '<p style="color:var(--text-sub);padding:8px;">Carregando organização...</p>';

  try {
    const data = await fetch('/api/pdf/organizacao').then(r => r.json());
    container.innerHTML = '';

    // Botão criar pasta
    const toolbar = document.createElement('div');
    toolbar.style.cssText = 'display:flex;gap:8px;margin-bottom:10px;padding:4px;';
    toolbar.innerHTML = `
      <button onclick="criarPastaVirtual()" style="padding:6px 12px;background:var(--accent);color:var(--bg);border:none;border-radius:6px;font-size:0.78rem;font-weight:600;cursor:pointer;">➕ Nova Pasta</button>
      <span style="font-size:0.7rem;color:var(--text-sub);align-self:center;">Arraste PDFs para pastas • ${data.total_pdfs || 0} PDFs, ${data.organizados || 0} organizados</span>
    `;
    container.appendChild(toolbar);

    // Renderizar árvore organizada com drag-and-drop
    _renderOrgTree(data.tree || [], container);
  } catch(e) {
    container.innerHTML = '<p style="color:var(--red);">Erro ao carregar organização</p>';
  }
}

function _renderOrgTree(nodes, container) {
  for (const node of nodes) {
    if (node.type === 'folder') {
      const div = document.createElement('div');
      div.className = 'folder org-folder';
      div.dataset.pastaId = node.id || '';
      div.innerHTML = `
        <div class="folder-header" style="display:flex;align-items:center;gap:6px;">
          <span class="folder-icon">${node.virtual ? '📂' : '📁'}</span>
          <span class="folder-name" style="flex:1;">${escapeHtml(node.name)}</span>
          ${node.virtual ? `<button onclick="event.stopPropagation();_renomearPasta(${node.id},'${escapeHtml(node.name)}')" style="background:none;border:none;cursor:pointer;font-size:0.7rem;" title="Renomear">✏️</button><button onclick="event.stopPropagation();_excluirPasta(${node.id})" style="background:none;border:none;cursor:pointer;font-size:0.7rem;" title="Excluir">🗑</button>` : ''}
          <span style="font-size:0.65rem;color:var(--text-sub);">${(node.children || []).length} itens</span>
        </div>
        <div class="folder-children open org-drop-zone" data-pasta-id="${node.id || ''}" style="min-height:30px;border:1px dashed transparent;border-radius:6px;transition:border-color 0.2s;padding:4px;"></div>
      `;
      const dropZone = div.querySelector('.org-drop-zone');
      _setupDropZone(dropZone, node.id);
      _renderOrgTree(node.children || [], dropZone);
      container.appendChild(div);
    } else if (node.type === 'pdf') {
      const item = document.createElement('div');
      item.className = 'pdf-item org-draggable';
      item.draggable = true;
      item.dataset.pdfPath = node.path || node.name;
      item.style.cssText = 'padding:6px 8px;background:var(--bg-surface);border-radius:6px;margin:3px 0;cursor:grab;display:flex;align-items:center;gap:6px;font-size:0.8rem;transition:opacity 0.2s;';
      item.innerHTML = `<span>📄</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(node.name.replace('.pdf', ''))}</span>`;

      // Drag events
      item.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/plain', node.path || node.name);
        e.dataTransfer.effectAllowed = 'move';
        item.style.opacity = '0.5';
      });
      item.addEventListener('dragend', () => { item.style.opacity = '1'; });
      container.appendChild(item);
    }
  }

  // Drop zone para a raiz (se é o container principal)
  if (container.id === 'tree' || container.parentElement?.id === 'tree') {
    // A raiz já é um drop zone implícito
    _setupDropZone(container, null);
  }
}

function _setupDropZone(zone, pastaId) {
  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    zone.style.borderColor = 'var(--accent)';
    zone.style.background = 'rgba(137,180,250,0.05)';
  });
  zone.addEventListener('dragleave', () => {
    zone.style.borderColor = 'transparent';
    zone.style.background = '';
  });
  zone.addEventListener('drop', async (e) => {
    e.preventDefault();
    zone.style.borderColor = 'transparent';
    zone.style.background = '';
    const pdfPath = e.dataTransfer.getData('text/plain');
    if (!pdfPath) return;

    try {
      await fetch('/api/pdf/mover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pdf_path: pdfPath, pasta_virtual_id: pastaId || null })
      });
      toast(`📄 PDF movido ${pastaId ? 'para a pasta' : 'para raiz'}!`, 'success', 1500);
      _loadOrganizacao(); // Recarrega
    } catch(e) { toast('Erro ao mover PDF', 'error'); }
  });
}

async function _renomearPasta(id, nomeAtual) {
  const novoNome = await promptModal('Novo nome:', { title: 'Renomear Pasta', defaultValue: nomeAtual });
  if (!novoNome || novoNome.trim() === nomeAtual) return;
  await fetch(`/api/pdf/pastas/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nome: novoNome.trim() })
  });
  toast('✏️ Pasta renomeada!', 'success');
  _loadOrganizacao();
}

async function _excluirPasta(id) {
  if (!await confirmModal('Excluir Pasta', 'Excluir pasta? (PDFs não serão deletados, voltam para raiz)', { type: 'danger', confirmText: 'Excluir' })) return;
  await fetch(`/api/pdf/pastas/${id}`, { method: 'DELETE' });
  toast('🗑 Pasta excluída', 'info');
  _loadOrganizacao();
}

window._renomearPasta = _renomearPasta;
window._excluirPasta = _excluirPasta;
