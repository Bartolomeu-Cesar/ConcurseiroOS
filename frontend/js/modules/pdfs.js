// ==================== TAB 1: PDFs ====================
import { state } from './state.js';
import { escapeHtml, showLoading, showEmpty, toast } from './utils.js';

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
    if (!state.editalData || state.editalData.length === 0) {
      try { state.editalData = await fetch('/api/edital').then(r => r.json()); }
      catch (e) { }
    }
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
      const pct = tp ? Math.round(((cp - 1) / tp) * 100) : 0;
      const label = tp ? `pág. ${cp}/${tp} (${pct}%)` : 'não lido';
      const vinculado = state.editalData.find(e => e.pdf_link === path);
      const materiaTag = vinculado ? `<span class="pdf-materia-tag">${escapeHtml(vinculado.materia)}</span>` : '';
      const linkBtn = vinculado
        ? `<button class="pdf-link-disc-btn pdf-unlink" onclick="event.stopPropagation();unlinkPdf('${path.replace(/'/g, "\\'")}')" title="Desvincular disciplina">❌</button>`
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
  window.addEventListener('focus', () => load());
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') load(); });

  load();
}
