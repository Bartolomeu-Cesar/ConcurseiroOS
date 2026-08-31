// viewer.js — extracted from viewer.html inline script
// ES module (strict mode by default)
import { confirmModal, promptModal } from '../modules/utils.js';

const API = '';
const TIMER_LIMIT_KEY = 'leitor_timer_limit_min';

const params = new URLSearchParams(location.search);
const path = params.get('path');
if (!path) { location.href = '/'; }

// Chave única por PDF — evita conflito com timer pomodoro da listagem (pdfs.js)
const TIMER_KEY = 'viewer_timer_' + (path || '').replace(/[^a-zA-Z0-9]/g, '_');

function encodePath(p) {
  return p.split('/').map(encodeURIComponent).join('/');
}

const name = path.split('/').pop().replace('.pdf', '').replace(/_/g, ' ');
document.title = name;
document.getElementById('title').textContent = name;

// ---------- Progresso ----------
let totalPages = 1;
let currentPage = 1;
let saveTimer = null;
let lastSavedPage = null;
let saving = false;

async function initProgress() {
  const prog = await fetch(`${API}/api/progress/${encodePath(path)}`).then(r => r.json());
  totalPages = prog.total_pages || 1;
  currentPage = prog.current_page || 1;
  lastSavedPage = currentPage;
  updateInfo();

  // Verifica se o PDF ainda existe no diretório antes de tentar renderizar.
  try {
    const chk = await fetch(`${API}/api/pdf-existe/${encodePath(path)}`).then(r => r.json());
    if (chk && chk.existe === false) {
      mostrarPdfInexistente();
      return;
    }
  } catch (e) { /* rede offline: segue e deixa o PDF.js tentar (pode estar em cache) */ }

  const pdfUrl = encodeURIComponent(`${location.origin}/pdf/${encodePath(path)}`);
  const frame = document.getElementById('pdf-frame');
  frame.src = `/pdfjs/web/viewer.html?file=${pdfUrl}#page=${currentPage}`;

  frame.addEventListener('load', () => {
    let tries = 0;
    const wait = setInterval(() => {
      tries++;
      if (readPageFromViewer() || tries > 40) clearInterval(wait);
    }, 250);
    // Arma o auto-resume só depois que a página inicial sincronizou (evita
    // retomar o timer por causa da sincronização de abertura, não do usuário).
    setTimeout(() => { _timerAutoResumeArmado = true; }, 1500);
  });

  setInterval(() => readPageFromViewer(), 400);
}

function mostrarPdfInexistente() {
  const viewer = document.getElementById('viewer');
  if (viewer) {
    viewer.innerHTML = `
      <div style="flex:1;display:flex;align-items:center;justify-content:center;padding:24px;">
        <div style="background:var(--bg-surface,#313244);border:1px solid var(--border,#45475a);border-radius:16px;padding:36px 32px;max-width:420px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.4);">
          <div style="font-size:2.6rem;margin-bottom:12px;">📄❌</div>
          <h2 style="color:var(--red,#f38ba8);font-size:1.15rem;margin:0 0 10px;">PDF não encontrado</h2>
          <p style="color:var(--text,#cdd6f4);font-size:0.9rem;line-height:1.6;margin:0 0 20px;">
            O arquivo <strong>${_escHtml(name)}</strong> não existe mais no diretório.<br>
            Ele pode ter sido movido, renomeado ou excluído.
          </p>
          <a href="/" style="display:inline-block;background:var(--accent,#89b4fa);color:var(--bg,#1e1e2e);border-radius:8px;padding:10px 22px;font-weight:600;font-size:0.9rem;text-decoration:none;">🏠 Voltar ao início</a>
        </div>
      </div>`;
  }
  const pageInfo = document.getElementById('page-info');
  if (pageInfo) pageInfo.textContent = 'PDF indisponível';
  showStudyToast('⚠️ Este PDF não existe mais no diretório.');
}

function readPageFromViewer() {
  const frame = document.getElementById('pdf-frame');
  try {
    const win = frame.contentWindow;
    if (!win) return false;

    const app = win.PDFViewerApplication;
    if (app && app.pdfDocument) {
      if (app.pagesCount && app.pagesCount !== totalPages) {
        totalPages = app.pagesCount;
      }
      const p = app.page;
      if (p && p !== currentPage) setPage(p);
      return true;
    }

    const doc = frame.contentDocument;
    if (doc) {
      const input = doc.getElementById('pageNumber');
      if (input && input.value) {
        const p = parseInt(input.value, 10);
        if (p && p !== currentPage) setPage(p);
        return true;
      }
    }

    const hash = win.location.hash || '';
    const match = hash.match(/page=(\d+)/i);
    if (match) {
      const p = parseInt(match[1], 10);
      if (p && p !== currentPage) setPage(p);
      return true;
    }
  } catch (e) {}
  return false;
}

function setPage(p) {
  if (!p || p < 1) return;
  const mudou = currentPage !== p;
  currentPage = p;
  updateInfo();
  scheduleSave();

  // Mudança de página = sinal de que o estudante voltou a ler o PDF. Se o
  // cronômetro estava PAUSADO (ex: parou para fazer um resumo/revisão), retoma
  // automaticamente. Só age em mudança real e após o carregamento inicial
  // assentar (_timerAutoResumeArmado), para não retomar na sincronização inicial.
  if (mudou && _timerAutoResumeArmado && paused) {
    _retomarTimerAuto();
  }

  // Detectar se chegou na última página (PDF concluído)
  if (currentPage >= totalPages && totalPages > 1 && !window._pdfFinishShown) {
    window._pdfFinishShown = true;
    setTimeout(() => ofereceQuestoesPdf(), 1500);
  }
}

// Retoma o cronômetro pausado automaticamente (disparado por mudança de página).
function _retomarTimerAuto() {
  paused = false;
  startedAt = Date.now() - (elapsed * 1000);
  clearInterval(timerInterval);
  timerInterval = setInterval(tick, 250);
  tick();
  saveTimerState();
  _atualizarBotoesTimer();
  showStudyToast('▶ Cronômetro retomado (você voltou a ler o PDF).');
}

function ofereceQuestoesPdf() {
  // Extrair matéria do nome do PDF
  const filename = path.split('/').pop().replace(/\.pdf$/i, '').replace(/[-_]/g, ' ');

  const modal = document.createElement('div');
  modal.id = 'pdf-finish-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:99999;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `<div style="background:#313244;border-radius:16px;padding:24px;max-width:380px;width:90%;text-align:center;">
    <div style="font-size:1.5rem;margin-bottom:8px;">📖✅</div>
    <h3 style="color:#a6e3a1;margin-bottom:8px;">PDF Concluído!</h3>
    <p style="font-size:0.82rem;color:#cdd6f4;margin-bottom:16px;">${filename}</p>
    <p style="font-size:0.82rem;color:#f9e2af;margin-bottom:16px;">📝 Fixe o conteúdo com questões ou flashcards!</p>
    <div style="display:flex;flex-direction:column;gap:8px;">
      <button onclick="window.open('/#tab-flashcards','_self');localStorage.setItem('pos_pdf_acao','questoes');" style="background:#89b4fa;color:#1e1e2e;border:none;border-radius:8px;padding:12px;font-weight:600;cursor:pointer;font-size:0.9rem;">❓ Resolver Questões</button>
      <button onclick="window.open('/#tab-flashcards','_self');localStorage.setItem('pos_pdf_acao','flashcards');" style="background:#cba6f7;color:#1e1e2e;border:none;border-radius:8px;padding:12px;font-weight:600;cursor:pointer;font-size:0.9rem;">🧠 Revisar Flashcards</button>
      <button onclick="document.getElementById('pdf-finish-modal').remove();" style="background:#45475a;color:#cdd6f4;border:none;border-radius:8px;padding:10px;cursor:pointer;font-size:0.85rem;">⏭ Pular (continuar depois)</button>
    </div>
  </div>`;
  document.body.appendChild(modal);
}

function updateInfo() {
  const pct = totalPages > 1
    ? Math.round(((currentPage - 1) / (totalPages - 1)) * 100)
    : (currentPage >= 1 ? 100 : 0);
  document.getElementById('page-info').textContent =
    `Página ${currentPage} / ${totalPages} (${pct}%)`;
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveProgress, 600);
}

async function saveProgress() {
  if (saving || currentPage === lastSavedPage) return;
  saving = true;
  try {
    const res = await fetch(`${API}/api/progress/${encodePath(path)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_page: currentPage, total_pages: totalPages }),
      keepalive: true
    });
    if (res.ok) {
      lastSavedPage = currentPage;
      localStorage.setItem('leitor_progress_updated', Date.now().toString());
    }
  } catch (e) {}
  finally { saving = false; }
}

function saveOnExit() {
  readPageFromViewer();
  if (currentPage === lastSavedPage) return;

  const body = JSON.stringify({ current_page: currentPage, total_pages: totalPages });
  const url = `${API}/api/progress/${encodePath(path)}`;

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true
  });
  try {
    navigator.sendBeacon(url, new Blob([body], { type: 'application/json' }));
  } catch (e) {}
  localStorage.setItem('leitor_progress_updated', Date.now().toString());
}

// ---------- Timer ----------
let timerInterval = null;
let elapsed = 0;
let paused = false;
let _timerAutoResumeArmado = false; // libera o auto-resume só após a carga inicial
let limitSeconds = 15 * 60;
let startedAt = null;

// --- Reading Session Time Tracking ---
const _sessionOpenedAt = Date.now();
const _lastReportedKey = 'leitor_last_reported_' + (path || '').replace(/\//g, '_');
const _lastReportedAt = parseInt(localStorage.getItem(_lastReportedKey) || '0');

const display = document.getElementById('timer-display');

function fmt(s) {
  const h = String(Math.floor(s / 3600)).padStart(2, '0');
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const sec = String(s % 60).padStart(2, '0');
  return `${h}:${m}:${sec}`;
}

function saveTimerState() {
  localStorage.setItem(TIMER_KEY, JSON.stringify({
    elapsed,
    paused,
    limitSeconds,
    startedAt,
    running: !!timerInterval
  }));
}

function loadTimerState() {
  try {
    const raw = localStorage.getItem(TIMER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function clearTimerState() {
  localStorage.removeItem(TIMER_KEY);
}

function updateTimerDisplay() {
  display.textContent = fmt(elapsed);
  display.classList.toggle('done', limitSeconds > 0 && elapsed >= limitSeconds);
}

function tick() {
  if (paused || !startedAt) return;
  elapsed = Math.floor((Date.now() - startedAt) / 1000);
  updateTimerDisplay();
  saveTimerState();
  if (elapsed >= limitSeconds) {
    finishTimer(true);
  }
}

function startTimer(limitMin, resumeElapsed = 0) {
  limitSeconds = limitMin * 60;
  elapsed = resumeElapsed;
  startedAt = Date.now() - (elapsed * 1000);
  paused = false;
  clearInterval(timerInterval);
  timerInterval = setInterval(tick, 250);
  tick();
  saveTimerState();
}

function finishTimer(showOverlay = false) {
  clearInterval(timerInterval);
  timerInterval = null;
  paused = false;
  startedAt = null;
  elapsed = 0;
  updateTimerDisplay();
  clearTimerState();
  localStorage.setItem('leitor_timer_finished', Date.now().toString());

  if (showOverlay) {
    document.getElementById('overlay').classList.add('show');
  }
}

// Atualiza os ícones/estado dos botões de controle do cronômetro.
function _atualizarBotoesTimer() {
  const bt = document.getElementById('btn-timer-toggle');
  if (!bt) return;
  const rodando = !!timerInterval && !paused;
  bt.textContent = rodando ? '⏸' : '▶';
  bt.title = rodando ? 'Pausar cronômetro' : 'Retomar cronômetro';
  bt.style.color = rodando ? 'var(--yellow,#f9e2af)' : 'var(--green,#a6e3a1)';
}

// Pausa ou retoma o cronômetro (mantém o tempo já decorrido).
function toggleTimerPause() {
  if (paused || !timerInterval) {
    // Retomar: recalcula startedAt para continuar de `elapsed`.
    paused = false;
    startedAt = Date.now() - (elapsed * 1000);
    clearInterval(timerInterval);
    timerInterval = setInterval(tick, 250);
    tick();
    showStudyToast('▶ Cronômetro retomado.');
  } else {
    // Pausar: congela o tempo decorrido e para o intervalo.
    paused = true;
    elapsed = startedAt ? Math.floor((Date.now() - startedAt) / 1000) : elapsed;
    clearInterval(timerInterval);
    timerInterval = null;
    updateTimerDisplay();
    showStudyToast('⏸ Cronômetro pausado.');
  }
  saveTimerState();
  _atualizarBotoesTimer();
}

// Para e zera o cronômetro (sem exibir o overlay de descanso).
function pararTimer() {
  finishTimer(false);
  _atualizarBotoesTimer();
  showStudyToast('⏹ Cronômetro parado e zerado.');
}

function initTimer() {
  const state = loadTimerState();
  const minutes = parseInt(localStorage.getItem(TIMER_LIMIT_KEY) || '15', 10);

  if (state && state.running && !state.paused && state.startedAt) {
    limitSeconds = state.limitSeconds || minutes * 60;
    startedAt = state.startedAt;
    elapsed = Math.floor((Date.now() - startedAt) / 1000);
    if (elapsed >= limitSeconds) {
      finishTimer(true);
      return;
    }
    paused = false;
    clearInterval(timerInterval);
    timerInterval = setInterval(tick, 250);
    tick();
  } else if (state && state.paused && state.limitSeconds > 0) {
    // Restaura o cronômetro no estado PAUSADO (não retoma sozinho no reload).
    limitSeconds = state.limitSeconds;
    elapsed = state.elapsed || 0;
    paused = true;
    startedAt = null;
    timerInterval = null;
    updateTimerDisplay();
    saveTimerState();
  } else {
    startTimer(minutes, 0);
  }
}

document.getElementById('btn-overlay-ok').addEventListener('click', () => {
  document.getElementById('overlay').classList.remove('show');
});

function onLeave() {
  saveOnExit();
  // Save timer state (persists for when user returns to viewer)
  saveTimerState();
  // Report reading time to streak (horas_estudadas)
  const readingSeconds = Math.floor((Date.now() - _sessionOpenedAt) / 1000);
  if (readingSeconds >= 60) { // Only report if read for at least 1 minute
    const horas = readingSeconds / 3600;
    const materia = path.split('/')[0] || 'Leitura PDF';
    fetch('/api/sessoes-estudo/registrar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        materia: materia,
        horas: Math.round(horas * 10000) / 10000,
        tipo: 'leitura',
      }),
      keepalive: true
    }).catch(() => {});
    // Mark as reported to avoid double-counting on next visit
    localStorage.setItem(_lastReportedKey, Date.now().toString());
  }
}

document.getElementById('btn-voltar').addEventListener('click', (e) => {
  e.preventDefault();
  onLeave();
  location.href = '/';
});

window.addEventListener('beforeunload', onLeave);
window.addEventListener('pagehide', onLeave);

// ---------- Painel Lateral de Questões ----------
let sidePanelQuestions = [];
let sidePanelMateria = '';

function toggleSidePanel() {
  const panel = document.getElementById('side-panel');
  const vaiAbrir = !panel.classList.contains('open');
  if (vaiAbrir) {
    // Exclusão mútua: fecha os painéis fixed do lado direito e zera o padding
    // do viewer (o #side-panel empurra o PDF sozinho, por ser flex-item).
    _fecharPaineisFixed(null);
    _aplicarPaddingViewer(0);
    _painelAtivo = 'questoes';
  } else if (_painelAtivo === 'questoes') {
    _painelAtivo = null;
  }
  panel.classList.toggle('open');
  if (panel.classList.contains('open') && sidePanelQuestions.length === 0) {
    loadSidePanelQuestions();
  }
}

async function loadSidePanelQuestions() {
  const body = document.getElementById('side-panel-body');
  
  // Tentar identificar a matéria pelo nome do PDF
  const pdfName = name.toLowerCase();
  
  // Buscar matérias vinculadas a este PDF
  try {
    const editalData = await fetch('/api/edital').then(r => r.json());
    const vinculados = editalData.filter(e => e.pdf_link === path);
    
    if (vinculados.length > 0) {
      sidePanelMateria = vinculados[0].materia;
    } else {
      // Tentar identificar pela nome do arquivo
      const materias = await fetch('/api/questoes/materias').then(r => r.json());
      sidePanelMateria = materias.find(m => pdfName.includes(m.toLowerCase().split(' ')[0]?.toLowerCase())) || '';
    }
  } catch(e) {}

  // Buscar questões
  let url = '/api/questoes';
  if (sidePanelMateria) {
    url += `?materia=${encodeURIComponent(sidePanelMateria)}`;
    document.querySelector('#side-panel-header h3').textContent = `❓ ${sidePanelMateria}`;
  }

  try {
    const questoes = await fetch(url).then(r => r.json());
    sidePanelQuestions = questoes;

    if (questoes.length === 0) {
      body.innerHTML = `<div class="sp-empty">Nenhuma questão encontrada${sidePanelMateria ? ' para "'+sidePanelMateria+'"' : ''}.<br><br><a href="/questoes.html" style="color:#89b4fa;">Cadastrar questões →</a></div>`;
      return;
    }

    // Sortear 5 questões aleatórias
    const shuffled = questoes.sort(() => Math.random() - 0.5).slice(0, 5);
    renderSidePanelQuestions(shuffled);
  } catch(e) {
    body.innerHTML = '<div class="sp-empty">Erro ao carregar questões.</div>';
  }
}

function renderSidePanelQuestions(questoes) {
  const body = document.getElementById('side-panel-body');
  body.innerHTML = questoes.map((q, idx) => {
    const alts = [
      { letter: 'A', text: q.alternativa_a },
      { letter: 'B', text: q.alternativa_b },
      { letter: 'C', text: q.alternativa_c },
      { letter: 'D', text: q.alternativa_d },
    ];
    if (q.alternativa_e) alts.push({ letter: 'E', text: q.alternativa_e });

    return `<div class="sp-question" data-id="${q.id}" data-correct="${q.resposta_correta}" data-start="${Date.now()}">
      <div class="sp-meta">
        ${q.materia}${q.topico ? ' • '+q.topico : ''}
        <span class="sp-timer" id="sp-timer-${q.id}" style="float:right;font-family:monospace;font-size:0.78rem;color:#89b4fa;">⏱ 0:00</span>
      </div>
      <div class="sp-enunciado">${q.enunciado}</div>
      ${alts.map(a => `<div class="sp-alt" data-letter="${a.letter}" onclick="selectSideAlt(this)"><span class="letter">${a.letter})</span> ${a.text}</div>`).join('')}
      <div class="sp-feedback" id="fb-${q.id}"></div>
    </div>`;
  }).join('') + `<div style="text-align:center;padding:12px;"><button onclick="loadSidePanelQuestions()" style="background:#45475a;border:none;color:#cdd6f4;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:0.82rem;">🔄 Novas questões</button></div>`;

  // Iniciar timers visuais para cada questão
  if (window._spTimerInterval) clearInterval(window._spTimerInterval);
  window._spTimerInterval = setInterval(() => {
    document.querySelectorAll('.sp-question:not([data-answered])').forEach(qEl => {
      const start = parseInt(qEl.dataset.start || '0');
      if (!start) return;
      const timerEl = qEl.querySelector('.sp-timer');
      if (!timerEl) return;
      const seg = Math.round((Date.now() - start) / 1000);
      const min = Math.floor(seg / 60);
      const s = String(seg % 60).padStart(2, '0');
      timerEl.textContent = `⏱ ${min}:${s}`;
      if (seg > 120) timerEl.style.color = '#f38ba8';
      else if (seg > 60) timerEl.style.color = '#f9e2af';
    });
  }, 1000);
}

async function selectSideAlt(el) {
  const question = el.closest('.sp-question');
  if (question.dataset.answered) return;
  question.dataset.answered = '1';

  const letter = el.dataset.letter;
  const correct = question.dataset.correct;
  const qId = question.dataset.id;
  const startTime = parseInt(question.dataset.start || '0');
  const tempoSegundos = startTime ? Math.round((Date.now() - startTime) / 1000) : 0;

  // Marcar seleção
  el.classList.add('selected');

  // Enviar resposta ao backend
  const res = await fetch(`/api/questoes/${qId}/responder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resposta: letter, tempo_segundos: tempoSegundos })
  }).then(r => r.json());

  // Mostrar resultado
  question.querySelectorAll('.sp-alt').forEach(a => {
    if (a.dataset.letter === correct) a.classList.add('correct');
    if (a.dataset.letter === letter && !res.acertou) a.classList.add('wrong');
  });

  const fb = document.getElementById(`fb-${qId}`);
  const isCE = question.querySelectorAll('.sp-alt').length === 2;
  const correctLabel = isCE ? (correct === 'A' ? 'CERTO' : 'ERRADO') : `Alternativa ${correct}`;
  fb.textContent = res.acertou ? '✓ Correto!' : `✗ Errado. Resposta: ${correctLabel}`;
  fb.style.color = res.acertou ? '#a6e3a1' : '#f38ba8';
  fb.classList.add('show');
}

initProgress();
initTimer();
_atualizarBotoesTimer();
initDestaques();

// ========== STUDY TOOLS ==========

// --- Notes ---
let notesVisible = false;
function toggleNotePanel() {
  notesVisible = !notesVisible;
  const panel = document.getElementById('notes-panel');
  panel.style.display = notesVisible ? 'flex' : 'none';
  if (notesVisible) loadNotesForPage();
}

async function loadNotesForPage() {
  document.getElementById('note-page-num').textContent = currentPage;
  const list = document.getElementById('notes-list');
  try {
    const notes = await fetch(`/api/notas?pdf_path=${encodeURIComponent(path)}&pagina=${currentPage}`).then(r => r.json());
    if (notes.length === 0) {
      list.innerHTML = '<div style="color:#585b70;font-size:0.82rem;text-align:center;padding:20px;">Nenhuma nota nesta página.<br>Adicione abaixo! ⬇</div>';
    } else {
      list.innerHTML = notes.map(n => `
        <div style="background:#1e1e2e;border-radius:8px;padding:10px;margin-bottom:8px;position:relative;">
          <div style="font-size:0.82rem;color:#cdd6f4;line-height:1.5;white-space:pre-wrap;">${n.conteudo}</div>
          <div style="display:flex;justify-content:space-between;margin-top:6px;">
            <span style="font-size:0.7rem;color:#585b70;">${n.created_at?.split('T')[0] || ''}</span>
            <button onclick="deleteNote(${n.id})" style="background:none;border:none;color:#f38ba855;cursor:pointer;font-size:0.75rem;" aria-label="Excluir nota">🗑</button>
          </div>
        </div>
      `).join('');
    }
  } catch { list.innerHTML = '<div style="color:#f38ba8;">Erro ao carregar notas</div>'; }
}

async function saveNote() {
  const input = document.getElementById('note-input');
  const text = input.value.trim();
  if (!text) return;
  await fetch('/api/notas', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ pdf_path: path, pagina: currentPage, conteudo: text })
  });
  input.value = '';
  loadNotesForPage();
}

async function deleteNote(id) {
  await fetch(`/api/notas/${id}`, { method: 'DELETE' });
  loadNotesForPage();
}

// Update notes when page changes
let lastNotePage = 0;
setInterval(() => {
  if (notesVisible && currentPage !== lastNotePage) {
    lastNotePage = currentPage;
    loadNotesForPage();
  }
}, 500);

// --- Bookmarks ---
async function addBookmark() {
  const label = await promptModal('Label para o bookmark (opcional):', { title: 'Novo Bookmark' });
  // null = usuário cancelou → não criar bookmark. String vazia = confirmou sem label.
  if (label === null) return;
  const cores = ['blue', 'green', 'yellow', 'red', 'purple'];
  const cor = cores[Math.floor(Math.random() * cores.length)];
  await fetch('/api/bookmarks', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ pdf_path: path, pagina: currentPage, label, cor })
  });
  showStudyToast(`🔖 Página ${currentPage} marcada!`);
}

// --- Painel dedicado de Bookmarks ---
let bookmarksVisible = false;

const _BM_CORES = {
  blue: '#89b4fa', green: '#a6e3a1', yellow: '#f9e2af',
  red: '#f38ba8', purple: '#cba6f7',
};

function toggleBookmarksPanel() {
  _togglePainelDireita('bookmarks', loadBookmarksPanel);
}

async function loadBookmarksPanel() {
  const body = document.getElementById('bookmarks-body');
  try {
    const bms = await fetch(`/api/bookmarks?pdf_path=${encodeURIComponent(path)}`).then(r => r.json());
    if (!Array.isArray(bms) || bms.length === 0) {
      body.innerHTML = `<div style="color:var(--text-sub,#585b70);font-size:0.85rem;text-align:center;padding:24px 12px;line-height:1.6;">
        Nenhum bookmark ainda.<br><br>Use o botão <strong>🔖</strong> (ou tecla <strong>B</strong>) para marcar a página atual.</div>`;
      return;
    }
    body.innerHTML = bms.map(b => {
      const cor = _BM_CORES[b.cor] || _BM_CORES.blue;
      const label = b.label && b.label.trim() ? _escHtml(b.label) : `Página ${b.pagina}`;
      return `<div style="display:flex;align-items:center;gap:8px;background:var(--bg,#1e1e2e);border-left:3px solid ${cor};border-radius:8px;padding:10px 12px;margin-bottom:8px;">
        <div style="flex:1;min-width:0;cursor:pointer;" onclick="goToPage(${b.pagina});toggleBookmarksPanel();" title="Ir para a página ${b.pagina}">
          <div style="font-size:0.85rem;color:var(--text,#cdd6f4);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${label}</div>
          <div style="font-size:0.72rem;color:var(--text-sub,#9399b2);">📄 Página ${b.pagina}${b.created_at ? ' · ' + (b.created_at.split('T')[0]) : ''}</div>
        </div>
        <button onclick="goToPage(${b.pagina});toggleBookmarksPanel();" title="Ir" style="background:var(--bg-elevated,#45475a);border:none;color:${cor};border-radius:6px;padding:5px 9px;font-size:0.75rem;cursor:pointer;">↪</button>
        <button onclick="excluirBookmark(${b.id})" title="Excluir" style="background:none;border:none;color:var(--red,#f38ba8);cursor:pointer;font-size:0.85rem;">🗑</button>
      </div>`;
    }).join('');
  } catch (e) {
    body.innerHTML = '<div style="color:var(--red,#f38ba8);font-size:0.85rem;">Erro ao carregar bookmarks.</div>';
  }
}

async function excluirBookmark(id) {
  if (!(await confirmModal('Excluir bookmark', 'Remover este bookmark?', { type: 'danger', confirmText: 'Excluir' }))) return;
  await fetch(`/api/bookmarks/${id}`, { method: 'DELETE' });
  loadBookmarksPanel();
}

// --- Quick Flashcard ---
function quickFlashcard() {
  document.getElementById('fc-page-num').textContent = currentPage;
  document.getElementById('fc-pergunta').value = '';
  document.getElementById('fc-resposta').value = '';
  document.getElementById('flashcard-modal').style.display = 'flex';
  document.getElementById('fc-pergunta').focus();
}

function closeFlashcardModal() {
  document.getElementById('flashcard-modal').style.display = 'none';
}

async function saveQuickFlashcard() {
  const pergunta = document.getElementById('fc-pergunta').value.trim();
  const resposta = document.getElementById('fc-resposta').value.trim();
  if (!pergunta || !resposta) { showStudyToast('Preencha pergunta e resposta.'); return; }

  // Try to get materia from PDF name or edital link
  let materia = '';
  try {
    const editalData = await fetch('/api/edital').then(r => r.json());
    const vinc = editalData.find(e => e.pdf_link === path);
    if (vinc) materia = vinc.materia;
  } catch {}

  await fetch('/api/flashcards', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ pergunta, resposta, materia })
  });
  closeFlashcardModal();
  showStudyToast('🧠 Flashcard criado! Será revisado amanhã.');
}

// --- Pomodoro Mode ---
let pomodoroActive = false;
let pomodoroCount = 0;

// Configuração do Pomodoro (persistida em localStorage, por usuário/dispositivo).
const POMODORO_CFG_KEY = 'viewer_pomodoro_cfg';
const POMODORO_DEFAULTS = { foco: 25, pausa: 5, pausaLonga: 15, ciclos: 4 };

function getPomodoroCfg() {
  try {
    const raw = localStorage.getItem(POMODORO_CFG_KEY);
    if (raw) {
      const c = JSON.parse(raw);
      return {
        foco: Number(c.foco) || POMODORO_DEFAULTS.foco,
        pausa: Number(c.pausa) || POMODORO_DEFAULTS.pausa,
        pausaLonga: Number(c.pausaLonga) || POMODORO_DEFAULTS.pausaLonga,
        ciclos: Number(c.ciclos) || POMODORO_DEFAULTS.ciclos,
      };
    }
  } catch { /* ignora config corrompida */ }
  return { ...POMODORO_DEFAULTS };
}

function togglePomodoroMode() {
  pomodoroActive = !pomodoroActive;
  const btn = document.getElementById('btn-pomodoro');
  if (pomodoroActive) {
    const cfg = getPomodoroCfg();
    btn.style.background = '#f38ba8';
    btn.style.color = '#1e1e2e';
    btn.textContent = '🍅 ON';
    startTimer(cfg.foco, 0);
    showStudyToast(`🍅 Pomodoro ativado! ${cfg.foco} min de foco.`);
    pomodoroCount++;
  } else {
    btn.style.background = '#45475a';
    btn.style.color = '#f38ba8';
    btn.textContent = '🍅';
    showStudyToast('🍅 Pomodoro desativado.');
  }
}

// Override finish timer for Pomodoro
const _origFinishTimer = finishTimer;
finishTimer = function(showOverlay) {
  _origFinishTimer(showOverlay);
  if (pomodoroActive) {
    const cfg = getPomodoroCfg();
    // Pausa longa a cada N ciclos concluídos; caso contrário, pausa curta.
    const ehPausaLonga = pomodoroCount > 0 && pomodoroCount % cfg.ciclos === 0;
    const pausaMin = ehPausaLonga ? cfg.pausaLonga : cfg.pausa;
    const pausaLabel = ehPausaLonga ? 'pausa longa' : 'pausa';
    setTimeout(async () => {
      if (await confirmModal('Pomodoro', `🍅 Pomodoro completo! Fazer ${pausaLabel} de ${pausaMin} min?`, { type: 'success', confirmText: 'Pausar', cancelText: 'Continuar' })) {
        startTimer(pausaMin, 0);
        showStudyToast(`☕ ${ehPausaLonga ? 'Pausa longa' : 'Pausa'} de ${pausaMin} min. Relaxe!`);
      } else {
        startTimer(cfg.foco, 0);
        pomodoroCount++;
        showStudyToast(`🍅 Pomodoro ${pomodoroCount} iniciado!`);
      }
    }, 500);
  }
};

// --- Configuração do Pomodoro (modal) ---
function abrirConfigPomodoro() {
  const cfg = getPomodoroCfg();
  document.getElementById('pomo-foco').value = cfg.foco;
  document.getElementById('pomo-pausa').value = cfg.pausa;
  document.getElementById('pomo-pausa-longa').value = cfg.pausaLonga;
  document.getElementById('pomo-ciclos').value = cfg.ciclos;
  document.getElementById('pomodoro-config-modal').style.display = 'flex';
}

function fecharConfigPomodoro() {
  document.getElementById('pomodoro-config-modal').style.display = 'none';
}

function resetConfigPomodoro() {
  document.getElementById('pomo-foco').value = POMODORO_DEFAULTS.foco;
  document.getElementById('pomo-pausa').value = POMODORO_DEFAULTS.pausa;
  document.getElementById('pomo-pausa-longa').value = POMODORO_DEFAULTS.pausaLonga;
  document.getElementById('pomo-ciclos').value = POMODORO_DEFAULTS.ciclos;
}

function salvarConfigPomodoro() {
  const clamp = (v, min, max, def) => {
    const n = parseInt(v, 10);
    if (isNaN(n)) return def;
    return Math.max(min, Math.min(max, n));
  };
  const cfg = {
    foco: clamp(document.getElementById('pomo-foco').value, 1, 120, POMODORO_DEFAULTS.foco),
    pausa: clamp(document.getElementById('pomo-pausa').value, 1, 60, POMODORO_DEFAULTS.pausa),
    pausaLonga: clamp(document.getElementById('pomo-pausa-longa').value, 1, 120, POMODORO_DEFAULTS.pausaLonga),
    ciclos: clamp(document.getElementById('pomo-ciclos').value, 1, 12, POMODORO_DEFAULTS.ciclos),
  };
  localStorage.setItem(POMODORO_CFG_KEY, JSON.stringify(cfg));
  fecharConfigPomodoro();
  showStudyToast(`🍅 Config salva: ${cfg.foco}/${cfg.pausa} min (longa ${cfg.pausaLonga} a cada ${cfg.ciclos}).`);
  // Se o Pomodoro estiver ativo, aplica o novo tempo de foco imediatamente.
  if (pomodoroActive) startTimer(cfg.foco, 0);
}

// --- Study Summary ---
let summaryVisible = false;
function toggleStudySummary() {
  _togglePainelDireita('summary', loadStudySummary);
}

async function loadStudySummary() {
  const body = document.getElementById('summary-body');
  const sessionTime = elapsed || 0;
  const pagesRead = currentPage - (lastSavedPage || 1);

  // Load bookmarks and notes for this PDF
  let bookmarks = [], notes = [];
  try {
    bookmarks = await fetch(`/api/bookmarks?pdf_path=${encodeURIComponent(path)}`).then(r => r.json());
    notes = await fetch(`/api/notas?pdf_path=${encodeURIComponent(path)}`).then(r => r.json());
  } catch {}

  const mins = Math.floor(sessionTime / 60);
  const secs = sessionTime % 60;

  body.innerHTML = `
    <div style="background:#1e1e2e;border-radius:10px;padding:14px;margin-bottom:12px;">
      <div style="font-size:0.85rem;color:#cba6f7;font-weight:600;margin-bottom:10px;">⏱ Sessão Atual</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div style="text-align:center;">
          <div style="font-size:1.3rem;font-weight:700;color:#f9e2af;">${mins}:${String(secs).padStart(2,'0')}</div>
          <div style="font-size:0.7rem;color:#9399b2;">Tempo</div>
        </div>
        <div style="text-align:center;">
          <div style="font-size:1.3rem;font-weight:700;color:#89b4fa;">${currentPage}/${totalPages}</div>
          <div style="font-size:0.7rem;color:#9399b2;">Página</div>
        </div>
      </div>
      ${pomodoroActive ? `<div style="margin-top:8px;text-align:center;font-size:0.8rem;color:#f38ba8;">🍅 Pomodoro ${pomodoroCount} ativo</div>` : ''}
    </div>

    <div style="background:#1e1e2e;border-radius:10px;padding:14px;margin-bottom:12px;">
      <div style="font-size:0.85rem;color:#a6e3a1;font-weight:600;margin-bottom:8px;">📊 Progresso</div>
      <div style="height:8px;background:#45475a;border-radius:4px;overflow:hidden;margin-bottom:6px;">
        <div style="width:${Math.round((currentPage/totalPages)*100)}%;height:100%;background:linear-gradient(90deg,#89b4fa,#a6e3a1);border-radius:4px;"></div>
      </div>
      <div style="font-size:0.75rem;color:#9399b2;text-align:center;">${Math.round((currentPage/totalPages)*100)}% concluído</div>
    </div>

    ${bookmarks.length > 0 ? `
    <div style="background:#1e1e2e;border-radius:10px;padding:14px;margin-bottom:12px;">
      <div style="font-size:0.85rem;color:#89b4fa;font-weight:600;margin-bottom:8px;">🔖 Bookmarks (${bookmarks.length})</div>
      ${bookmarks.slice(0, 8).map(b => `
        <div style="display:flex;align-items:center;gap:6px;padding:4px 0;font-size:0.8rem;cursor:pointer;" onclick="goToPage(${b.pagina})">
          <span style="color:#89b4fa;">p.${b.pagina}</span>
          <span style="color:#cdd6f4;">${b.label || 'Sem label'}</span>
        </div>
      `).join('')}
    </div>` : ''}

    ${notes.length > 0 ? `
    <div style="background:#1e1e2e;border-radius:10px;padding:14px;margin-bottom:12px;">
      <div style="font-size:0.85rem;color:#f9e2af;font-weight:600;margin-bottom:8px;">📝 Notas (${notes.length})</div>
      ${notes.slice(0, 5).map(n => `
        <div style="padding:4px 0;font-size:0.78rem;border-bottom:1px solid #313244;cursor:pointer;" onclick="goToPage(${n.pagina})">
          <span style="color:#89b4fa;">p.${n.pagina}</span> — <span style="color:#9399b2;">${n.conteudo.substring(0, 60)}${n.conteudo.length > 60 ? '...' : ''}</span>
        </div>
      `).join('')}
    </div>` : ''}

    <div style="background:#1e1e2e;border-radius:10px;padding:14px;">
      <div style="font-size:0.85rem;color:#fab387;font-weight:600;margin-bottom:8px;">💡 Dicas de Estudo Ativo</div>
      <ul style="font-size:0.78rem;color:#9399b2;padding-left:16px;line-height:1.8;">
        <li>📝 Anote conceitos-chave de cada página</li>
        <li>🧠 Crie flashcards do que aprendeu</li>
        <li>🔖 Marque páginas para revisar depois</li>
        <li>❓ Resolva questões ao terminar o capítulo</li>
        <li>🍅 Use Pomodoro: 25 min foco + 5 min pausa</li>
      </ul>
    </div>
  `;
}

// --- Go to page helper ---
function goToPage(page) {
  const frame = document.getElementById('pdf-frame');
  try {
    const app = frame.contentWindow?.PDFViewerApplication;
    if (app) app.page = page;
  } catch {}
}

// --- Toast for study tools ---
function showStudyToast(msg) {
  const toast = document.createElement('div');
  toast.style.cssText = 'position:fixed;top:50px;left:50%;transform:translateX(-50%);background:#313244;color:#cdd6f4;padding:10px 20px;border-radius:8px;font-size:0.85rem;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,0.3);animation:fadeIn 0.3s;';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 0.3s'; setTimeout(() => toast.remove(), 300); }, 2500);
}

// --- Keyboard shortcuts ---
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'n' || e.key === 'N') toggleNotePanel();
  if (e.key === 'b' || e.key === 'B') addBookmark();
  if (e.key === 'f' || e.key === 'F') quickFlashcard();
  if (e.key === 'p' || e.key === 'P') togglePomodoroMode();
  if (e.key === 's' || e.key === 'S') toggleStudySummary();
  if (e.key === 'r' || e.key === 'R') toggleActiveRecall();
  if (e.key === 'a' || e.key === 'A') askAIAboutPage();
});

// --- Active Recall Mode (MarginNote-style) ---
let recallActive = false;
function toggleActiveRecall() {
  recallActive = !recallActive;
  const panel = document.getElementById('recall-panel');
  const btn = document.getElementById('btn-recall');
  if (recallActive) {
    panel.style.display = 'block';
    btn.style.background = '#94e2d5';
    btn.style.color = '#1e1e2e';
    btn.textContent = '🔓';
    document.getElementById('recall-page').textContent = currentPage;
    document.getElementById('recall-input').value = '';
    document.getElementById('recall-feedback').style.display = 'none';
    document.getElementById('recall-input').focus();
  } else {
    panel.style.display = 'none';
    btn.style.background = '#45475a';
    btn.style.color = '#94e2d5';
    btn.textContent = '🔒';
  }
}

async function checkRecall() {
  const input = document.getElementById('recall-input').value.trim();
  if (!input) return;
  const fb = document.getElementById('recall-feedback');
  fb.style.display = 'block';

  // Try AI check if available
  try {
    const notes = await fetch(`/api/notas?pdf_path=${encodeURIComponent(path)}&pagina=${currentPage}`).then(r => r.json());
    const hasNotes = notes.length > 0;

    // Simple self-assessment (AI-powered if available)
    fb.innerHTML = `
      <div style="font-size:0.85rem;color:#a6e3a1;font-weight:600;margin-bottom:8px;">✓ Recall registrado!</div>
      <p style="font-size:0.8rem;color:#cdd6f4;margin-bottom:10px;">Agora volte ao texto e verifique o que esqueceu. Pontos que você não lembrou são os que mais precisa revisar.</p>
      <div style="font-size:0.8rem;color:#9399b2;margin-bottom:8px;">Como avalia seu recall?</div>
      <div style="display:flex;gap:6px;">
        <button onclick="rateRecall(1)" style="flex:1;background:#f38ba8;color:#1e1e2e;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.8rem;font-weight:600;">😣 Ruim</button>
        <button onclick="rateRecall(3)" style="flex:1;background:#f9e2af;color:#1e1e2e;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.8rem;font-weight:600;">😐 Ok</button>
        <button onclick="rateRecall(5)" style="flex:1;background:#a6e3a1;color:#1e1e2e;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.8rem;font-weight:600;">😊 Ótimo</button>
      </div>
      ${hasNotes ? '<div style="margin-top:8px;font-size:0.75rem;color:#585b70;">💡 Compare com suas notas desta página</div>' : ''}
    `;
  } catch {
    fb.innerHTML = '<div style="color:#a6e3a1;">✓ Recall salvo. Confira o texto agora!</div>';
  }
}

function rateRecall(quality) {
  // Save recall attempt to notes as a special recall entry
  const input = document.getElementById('recall-input').value.trim();
  fetch('/api/notas', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ pdf_path: path, pagina: currentPage, conteudo: `[RECALL q=${quality}] ${input}` })
  });
  showStudyToast(`🔒 Recall avaliado (${quality}/5) — salvo como nota!`);
  toggleActiveRecall();
}

// --- AI Page Actions ---
function askAIAboutPage() {
  document.getElementById('ai-page-num').textContent = currentPage;
  document.getElementById('ai-page-response').style.display = 'none';
  document.getElementById('ai-page-input').value = '';
  document.getElementById('ai-page-modal').style.display = 'flex';
}

function closeAIModal() {
  document.getElementById('ai-page-modal').style.display = 'none';
}

async function aiAction(action) {
  const responseEl = document.getElementById('ai-page-response');
  responseEl.style.display = 'block';
  responseEl.innerHTML = '<span style="color:#fab387;">🤖 Processando...</span>';

  // Get context: notes from this page + PDF name
  let context = `PDF: ${name}, Página: ${currentPage}`;
  try {
    const notes = await fetch(`/api/notas?pdf_path=${encodeURIComponent(path)}&pagina=${currentPage}`).then(r => r.json());
    if (notes.length > 0) {
      context += `\nNotas do estudante: ${notes.map(n => n.conteudo).join('; ')}`;
    }
  } catch {}

  let mensagem = '';
  switch(action) {
    case 'resumir': mensagem = `Resuma os pontos principais da página ${currentPage} do material "${name}". ${context}`; break;
    case 'flashcards': mensagem = `Gere 5 flashcards dos conceitos-chave. Contexto: ${context}`; break;
    case 'questoes': mensagem = `Gere 3 questões de concurso sobre o conteúdo. Contexto: ${context}`; break;
    case 'simplificar': mensagem = `Simplifique o conteúdo jurídico desta página em linguagem acessível. ${context}`; break;
    case 'mapa': mensagem = `Crie um mapa mental em texto (hierarquia com - e →) dos conceitos. ${context}`; break;
    case 'pergunta':
      mensagem = document.getElementById('ai-page-input').value.trim();
      if (!mensagem) { responseEl.innerHTML = '<span style="color:#f38ba8;">Digite uma pergunta.</span>'; return; }
      mensagem += ` (Contexto: ${context})`;
      break;
  }

  try {
    const res = await fetch('/api/ai/chat', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ mensagem, contexto: context })
    });
    const data = await res.json();
    if (res.ok) {
      responseEl.innerHTML = data.resposta || data.detail || 'Sem resposta';
    } else {
      responseEl.innerHTML = `<span style="color:#f38ba8;">${data.detail || 'AI não disponível. Configure um provider em Social → AI Tutor → ⚙️'}</span>`;
    }
  } catch (e) {
    responseEl.innerHTML = `<span style="color:#f38ba8;">Erro: ${e.message}</span>`;
  }
}

// --- Gerar com IA a partir do PDF (resumo / flashcards / questões) ---
function _escHtml(s) {
  const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML;
}

function abrirGerarIA() {
  const pgAtual = currentPage || 1;
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.innerHTML = `
    <div style="background:var(--bg-surface,#313244);border:1px solid var(--border,#45475a);border-radius:14px;padding:20px;max-width:560px;width:100%;max-height:92vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
      <h3 style="color:var(--text,#cdd6f4);margin:0 0 4px;font-size:1rem;">✨ Gerar com IA — ${_escHtml(name)}</h3>
      <p style="color:var(--text-sub,#a6adc8);font-size:0.78rem;margin:0 0 14px;">A IA lê o texto do intervalo de páginas escolhido e gera o conteúdo.</p>

      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
        <label style="flex:1;min-width:120px;font-size:0.78rem;color:var(--text,#cdd6f4);">Ação
          <select id="ia-acao" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border,#45475a);background:var(--bg,#1e1e2e);color:var(--text,#cdd6f4);">
            <option value="resumo">📄 Resumo</option>
            <option value="flashcards">🧠 Flashcards</option>
            <option value="questoes">❓ Questões</option>
          </select>
        </label>
        <label style="width:88px;font-size:0.78rem;color:var(--text,#cdd6f4);">Pág. inicial
          <input type="number" id="ia-pg-ini" min="1" value="${pgAtual}" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border,#45475a);background:var(--bg,#1e1e2e);color:var(--text,#cdd6f4);">
        </label>
        <label style="width:88px;font-size:0.78rem;color:var(--text,#cdd6f4);">Pág. final
          <input type="number" id="ia-pg-fim" min="1" value="${pgAtual}" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border,#45475a);background:var(--bg,#1e1e2e);color:var(--text,#cdd6f4);">
        </label>
      </div>

      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px;">
        <label id="ia-qtd-wrap" style="width:120px;font-size:0.78rem;color:var(--text,#cdd6f4);">Quantidade
          <input type="number" id="ia-qtd" min="1" max="20" value="5" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border,#45475a);background:var(--bg,#1e1e2e);color:var(--text,#cdd6f4);">
        </label>
        <label id="ia-salvar-wrap" style="display:flex;align-items:center;gap:6px;font-size:0.8rem;color:var(--text,#cdd6f4);margin-top:16px;">
          <input type="checkbox" id="ia-salvar" checked style="width:16px;height:16px;"> Salvar no meu material
        </label>
      </div>

      <div style="display:flex;gap:8px;justify-content:flex-end;margin-bottom:12px;">
        <button id="ia-cancel" style="background:var(--bg,#1e1e2e);border:1px solid var(--border,#45475a);color:var(--text,#cdd6f4);border-radius:8px;padding:8px 16px;font-size:0.82rem;cursor:pointer;">Fechar</button>
        <button id="ia-gerar" style="background:var(--mauve,#cba6f7);color:#1e1e2e;border:none;border-radius:8px;padding:8px 18px;font-weight:700;font-size:0.82rem;cursor:pointer;">Gerar</button>
      </div>

      <div id="ia-resultado" style="display:none;background:var(--bg,#1e1e2e);border:1px solid var(--border,#45475a);border-radius:8px;padding:12px;font-size:0.82rem;color:var(--text,#cdd6f4);white-space:pre-wrap;line-height:1.5;max-height:320px;overflow-y:auto;"></div>
    </div>`;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector('#ia-cancel').onclick = close;
  overlay.onclick = (e) => { if (e.target === overlay) close(); };

  // Quantidade/salvar só fazem sentido para flashcards/questões
  const acaoSel = overlay.querySelector('#ia-acao');
  const ajustarCampos = () => {
    const ehResumo = acaoSel.value === 'resumo';
    overlay.querySelector('#ia-qtd-wrap').style.display = ehResumo ? 'none' : 'block';
    overlay.querySelector('#ia-salvar-wrap').style.display = ehResumo ? 'none' : 'flex';
  };
  acaoSel.onchange = ajustarCampos;
  ajustarCampos();

  overlay.querySelector('#ia-gerar').onclick = async () => {
    const acao = acaoSel.value;
    const pgIni = Math.max(1, parseInt(overlay.querySelector('#ia-pg-ini').value) || 1);
    const pgFim = Math.max(pgIni, parseInt(overlay.querySelector('#ia-pg-fim').value) || pgIni);
    const qtd = Math.min(20, Math.max(1, parseInt(overlay.querySelector('#ia-qtd').value) || 5));
    const salvar = overlay.querySelector('#ia-salvar').checked;
    const resultado = overlay.querySelector('#ia-resultado');
    const btn = overlay.querySelector('#ia-gerar');

    resultado.style.display = 'block';
    resultado.innerHTML = '<span style="color:#fab387;">🤖 Lendo o PDF e gerando com IA...</span>';
    btn.disabled = true; btn.style.opacity = '0.6';

    try {
      const res = await fetch('/api/ai/analisar-pdf', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pdf_path: path, acao,
          pagina_inicial: pgIni, pagina_final: pgFim,
          materia: name, quantidade: qtd, salvar,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        resultado.innerHTML = `<span style="color:#f38ba8;">${_escHtml(data.detail || 'Não foi possível gerar. Configure um provider de IA em Social → AI Tutor → ⚙️.')}</span>`;
        return;
      }
      resultado.innerHTML = _renderResultadoIA(data);
    } catch (e) {
      resultado.innerHTML = `<span style="color:#f38ba8;">Erro de conexão: ${_escHtml(e.message)}</span>`;
    } finally {
      btn.disabled = false; btn.style.opacity = '1';
    }
  };
}

function _renderResultadoIA(data) {
  const tecnica = data.tecnica
    ? `<div style="font-size:0.72rem;color:var(--mauve,#cba6f7);margin-bottom:8px;">🔬 Técnica: ${_escHtml(data.tecnica)}</div>`
    : '';
  if (data.acao === 'resumo') {
    return tecnica + _escHtml(data.resumo || data.resposta || '');
  }
  if (data.acao === 'flashcards') {
    const fcs = data.flashcards || [];
    const salvo = data.salvo ? `<div style="color:#a6e3a1;margin-bottom:8px;">✅ ${data.salvos} flashcard(s) salvo(s) para revisão (FSRS).</div>` : '';
    if (!fcs.length) return tecnica + '<span style="color:#f38ba8;">A IA não retornou flashcards. Tente outro intervalo.</span>';
    return tecnica + salvo + fcs.map((f, i) =>
      `<div style="border-bottom:1px solid var(--border,#45475a);padding:6px 0;"><strong>${i + 1}. ${_escHtml(f.pergunta)}</strong><br><span style="color:var(--text-sub,#a6adc8);">${_escHtml(f.resposta)}</span></div>`
    ).join('');
  }
  if (data.acao === 'questoes') {
    const qs = data.questoes || [];
    const salvo = data.salvo ? `<div style="color:#a6e3a1;margin-bottom:8px;">✅ ${data.salvos} questão(ões) salva(s) no banco.</div>` : '';
    if (!qs.length) return tecnica + '<span style="color:#f38ba8;">A IA não retornou questões. Tente outro intervalo.</span>';
    return tecnica + salvo + qs.map((q, i) => {
      const alts = ['a', 'b', 'c', 'd', 'e']
        .filter(l => q['alternativa_' + l])
        .map(l => `${l.toUpperCase()}) ${_escHtml(q['alternativa_' + l])}`).join('<br>');
      return `<div style="border-bottom:1px solid var(--border,#45475a);padding:8px 0;"><strong>${i + 1}. ${_escHtml(q.enunciado)}</strong><br>${alts}<br><span style="color:#a6e3a1;">Gabarito: ${_escHtml(q.resposta_correta)}</span></div>`;
    }).join('');
  }
  return tecnica + _escHtml(data.resposta || '');
}

// --- Study Technique Selector ---
const TECHNIQUES = {
  livre: { name: '📖 Leitura Livre', guide: '' },
  sq3r: {
    name: '📐 SQ3R',
    guide: `<strong>SQ3R — Survey, Question, Read, Recite, Review:</strong><br>
    1️⃣ <strong>Survey:</strong> Folheie rapidamente — títulos, gráficos, resumos<br>
    2️⃣ <strong>Question:</strong> Transforme títulos em perguntas ("O que é...", "Por que...")<br>
    3️⃣ <strong>Read:</strong> Leia buscando responder suas perguntas<br>
    4️⃣ <strong>Recite:</strong> Feche o livro e responda de memória (use 🔒 Recall)<br>
    5️⃣ <strong>Review:</strong> Revise ao final — crie flashcards do que esqueceu`
  },
  cornell: {
    name: '📋 Cornell',
    guide: `<strong>Método Cornell:</strong><br>
    📝 Divida suas notas em 3 áreas:<br>
    • <strong>Direita (70%):</strong> Anotações durante a leitura<br>
    • <strong>Esquerda (30%):</strong> Palavras-chave e perguntas (depois)<br>
    • <strong>Rodapé:</strong> Resumo em 1-2 frases (ao terminar)<br><br>
    💡 Use o painel de Notas (📝) para anotar e depois revise criando flashcards.`
  },
  feynman: {
    name: '🧪 Feynman',
    guide: `<strong>Técnica Feynman:</strong><br>
    1️⃣ Leia o conceito<br>
    2️⃣ Explique como se fosse para uma criança (use 🔒 Recall)<br>
    3️⃣ Identifique lacunas — onde travou?<br>
    4️⃣ Volte ao texto e simplifique mais<br><br>
    💡 Se não consegue explicar simples, não entendeu de verdade.`
  },
  pomodoro: {
    name: '🍅 Pomodoro',
    guide: `<strong>Técnica Pomodoro:</strong><br>
    🍅 25 min de foco total (sem distrações)<br>
    ☕ 5 min de pausa (levante, hidrate)<br>
    🔄 A cada 4 pomodoros: pausa longa (15-30 min)<br><br>
    💡 Ative o botão 🍅 na toolbar para timer automático.`
  }
};

function setStudyTechnique(technique) {
  const guide = document.getElementById('technique-guide');
  const content = document.getElementById('technique-content');
  const t = TECHNIQUES[technique];
  if (t && t.guide) {
    content.innerHTML = t.guide;
    guide.style.display = 'block';
    setTimeout(() => { guide.style.display = 'none'; }, 15000);
  } else {
    guide.style.display = 'none';
  }
  localStorage.setItem('study_technique', technique);
  showStudyToast(`Técnica: ${t.name}`);
}

// Restore technique on load
const savedTechnique = localStorage.getItem('study_technique');
if (savedTechnique) document.getElementById('study-technique').value = savedTechnique;

// --- Reading Speed Tracker ---
let pageTimestamps = [];
let lastPageForSpeed = currentPage;
setInterval(() => {
  if (currentPage !== lastPageForSpeed) {
    pageTimestamps.push({ page: currentPage, time: Date.now() });
    lastPageForSpeed = currentPage;
    // Calculate pages/minute (last 5 pages)
    if (pageTimestamps.length >= 2) {
      const recent = pageTimestamps.slice(-6);
      const timeDiff = (recent[recent.length-1].time - recent[0].time) / 60000; // minutes
      const pagesDiff = recent.length - 1;
      if (timeDiff > 0) {
        const ppm = (pagesDiff / timeDiff).toFixed(1);
        const speedEl = document.getElementById('reading-speed');
        if (speedEl) speedEl.textContent = `${ppm} pg/min`;
      }
    }
  }
}, 1000);

// ========== CADERNO DE REVISÃO (recortes de PDF + notas) ==========
let revisaoVisible = false;

// Tags de bloco (categorias de estudo) com rótulo e cor.
const _REV_TAGS = {
  '': { label: 'Sem tag', cor: 'var(--text-sub,#9399b2)' },
  decorar: { label: '📌 Decorar', cor: 'var(--red,#f38ba8)' },
  entender: { label: '💡 Entender', cor: 'var(--blue,#89b4fa)' },
  pegadinha: { label: '⚠️ Pegadinha', cor: 'var(--yellow,#f9e2af)' },
  revisar: { label: '🔁 Revisar', cor: 'var(--mauve,#cba6f7)' },
};
let _revFsTagFiltro = ''; // filtro de tag ativo na tela cheia ('' = todas)
let _revFsBusca = '';     // termo de busca ativo na tela cheia
let _revFsZoom = 1.0;     // zoom do documento na tela cheia
let _revFsRecall = false; // Modo Recall (Retrieval Practice): oculta conteúdo
let _revFsBlocos = [];    // cache dos blocos carregados p/ re-render sem refetch
let _cropState = null; // { startX, startY } durante o arraste

// ---------- Gerenciador central de painéis laterais (lado direito) ----------
// Painéis fixed que ocupam o lado direito e cobririam o PDF. São mutuamente
// exclusivos: abrir um fecha os demais. O #viewer (flex, iframe flex:1) recebe
// padding-right = largura do painel ativo, empurrando o PDF para a esquerda.
// O #side-panel (Questões) vive DENTRO do flex e já empurra sozinho, mas também
// participa da exclusão para não haver dois painéis abertos ao mesmo tempo.
const _PAINEIS_DIREITA = {
  revisao: { el: 'revisao-panel', largura: 380 },
  bookmarks: { el: 'bookmarks-panel', largura: 340 },
  summary: { el: 'summary-panel', largura: 320 },
};
let _painelAtivo = null; // 'revisao' | 'bookmarks' | 'summary' | 'questoes' | null

function _aplicarPaddingViewer(px) {
  const viewer = document.getElementById('viewer');
  if (!viewer) return;
  viewer.style.transition = 'padding-right 0.25s ease';
  viewer.style.paddingRight = px ? `${px}px` : '';
}

// Fecha todos os painéis fixed do lado direito e, opcionalmente, o de questões.
// Não altera o padding aqui — quem chama decide o estado final.
function _fecharPaineisFixed(exceto) {
  for (const [nome, cfg] of Object.entries(_PAINEIS_DIREITA)) {
    if (nome === exceto) continue;
    const el = document.getElementById(cfg.el);
    if (el) el.style.display = 'none';
  }
  // Sincroniza as flags de visibilidade dos toggles legados.
  if (exceto !== 'revisao') revisaoVisible = false;
  if (exceto !== 'bookmarks') bookmarksVisible = false;
  if (exceto !== 'summary') summaryVisible = false;
}

// Abre/fecha um painel fixed garantindo exclusão mútua. Retorna true se ficou
// aberto. `onOpen` é chamado quando o painel passa a ficar visível.
function _togglePainelDireita(nome, onOpen) {
  const cfg = _PAINEIS_DIREITA[nome];
  const el = document.getElementById(cfg.el);
  if (!el) return false;
  const vaiAbrir = _painelAtivo !== nome;

  // Fecha os outros painéis fixed e o de questões (flex).
  _fecharPaineisFixed(nome);
  const sidePanel = document.getElementById('side-panel');
  if (sidePanel && nome !== 'questoes') sidePanel.classList.remove('open');

  if (vaiAbrir) {
    el.style.display = 'flex';
    _painelAtivo = nome;
    _aplicarPaddingViewer(cfg.largura);
    // flag legada
    if (nome === 'revisao') revisaoVisible = true;
    else if (nome === 'bookmarks') bookmarksVisible = true;
    else if (nome === 'summary') summaryVisible = true;
    if (typeof onOpen === 'function') onOpen();
  } else {
    el.style.display = 'none';
    _painelAtivo = null;
    _aplicarPaddingViewer(0);
    if (nome === 'revisao') revisaoVisible = false;
    else if (nome === 'bookmarks') bookmarksVisible = false;
    else if (nome === 'summary') summaryVisible = false;
  }
  return vaiAbrir;
}

function toggleRevisaoPanel() {
  _togglePainelDireita('revisao', () => {
    _revBusca = '';
    const bInput = document.getElementById('revisao-busca');
    if (bInput) bInput.value = '';
    loadRevisao();
  });
}

let _revBlocos = [];        // cache dos blocos do painel p/ busca sem refetch
let _revBusca = '';         // termo de busca do painel

async function loadRevisao() {
  const body = document.getElementById('revisao-body');
  _loadAgendaStatus();
  try {
    const blocos = await fetch(`/api/revisao/${encodePath(path)}`).then(r => r.json());
    if (!Array.isArray(blocos) || blocos.length === 0) {
      _revBlocos = [];
      body.innerHTML = `<div style="color:var(--text-sub,#585b70);font-size:0.85rem;text-align:center;padding:24px 12px;line-height:1.6;">
        Nenhum bloco ainda.<br><br>Use <strong>✂️ Recortar página</strong> para capturar uma parte importante do PDF, ou <strong>📝 Nota de texto</strong> para escrever um resumo.</div>`;
      return;
    }
    _revBlocos = blocos;
    _renderRevisaoLista();
  } catch (e) {
    body.innerHTML = '<div style="color:var(--red,#f38ba8);font-size:0.85rem;">Erro ao carregar caderno.</div>';
  }
}

// Filtra blocos por título/conteúdo (case-insensitive) e re-renderiza a lista.
function _renderRevisaoLista() {
  const body = document.getElementById('revisao-body');
  if (!body) return;
  const termo = _revBusca.trim().toLowerCase();
  const visiveis = termo
    ? _revBlocos.filter(b => `${b.titulo || ''} ${b.conteudo || ''}`.toLowerCase().includes(termo))
    : _revBlocos;
  if (visiveis.length === 0) {
    body.innerHTML = `<div style="color:var(--text-sub,#585b70);font-size:0.85rem;text-align:center;padding:24px 12px;">Nenhum bloco corresponde a “${_escHtml(_revBusca)}”.</div>`;
    return;
  }
  body.innerHTML = visiveis.map((b, i) => _renderBlocoRevisao(b, i, visiveis.length)).join('');
}

// Handler do campo de busca do painel.
function filtrarRevisao(termo) {
  _revBusca = termo || '';
  _renderRevisaoLista();
}

function _renderBlocoRevisao(b, idx, total) {
  const titulo = b.titulo ? `<div style="font-weight:600;color:var(--teal,#94e2d5);font-size:0.85rem;margin-bottom:6px;">${_escHtml(b.titulo)}</div>` : '';
  const img = (b.tipo === 'recorte' && b.imagem_data)
    ? `<img src="${b.imagem_data}" alt="Recorte p.${b.pagina}" style="max-width:100%;border-radius:6px;display:block;margin-bottom:6px;border:1px solid var(--border,#45475a);">`
    : '';
  const conteudo = b.conteudo
    ? `<div style="font-size:0.82rem;color:var(--text,#cdd6f4);line-height:1.5;white-space:pre-wrap;margin-bottom:6px;">${_escHtml(b.conteudo)}</div>`
    : '';
  const tagAtual = b.tag || '';
  const tagCor = (_REV_TAGS[tagAtual] || _REV_TAGS['']).cor;
  const tagOpcoes = Object.entries(_REV_TAGS).map(([k, v]) =>
    `<option value="${k}" ${k === tagAtual ? 'selected' : ''}>${v.label}</option>`).join('');
  const bordaTag = tagAtual ? `border-left:3px solid ${tagCor};` : '';
  return `<div style="background:var(--bg,#1e1e2e);border-radius:10px;padding:12px;margin-bottom:10px;${bordaTag}" data-id="${b.id}">
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
      <span style="font-size:0.7rem;color:var(--blue,#89b4fa);cursor:pointer;" onclick="goToPage(${b.pagina})" title="Ir para a página">p.${b.pagina}</span>
      <select onchange="setBlocoTag(${b.id}, this.value)" title="Categoria do bloco" style="font-size:0.68rem;background:var(--bg-surface,#313244);color:${tagCor};border:1px solid var(--border,#45475a);border-radius:5px;padding:2px 4px;cursor:pointer;max-width:110px;">${tagOpcoes}</select>
      <span style="flex:1;"></span>
      <button onclick="moverBlocoRevisao(${b.id}, -1)" ${idx === 0 ? 'disabled' : ''} title="Subir" style="background:none;border:none;color:${idx === 0 ? 'var(--border,#45475a)' : 'var(--text-sub,#9399b2)'};cursor:pointer;font-size:0.8rem;">▲</button>
      <button onclick="moverBlocoRevisao(${b.id}, 1)" ${idx === total - 1 ? 'disabled' : ''} title="Descer" style="background:none;border:none;color:${idx === total - 1 ? 'var(--border,#45475a)' : 'var(--text-sub,#9399b2)'};cursor:pointer;font-size:0.8rem;">▼</button>
      <button onclick="editarBlocoRevisao(${b.id})" title="Editar título/comentário" style="background:none;border:none;color:var(--yellow,#f9e2af);cursor:pointer;font-size:0.78rem;">✏️</button>
      ${b.tipo === 'recorte' && b.imagem_data ? `<button onclick="abrirOclusaoEditor(${b.id})" title="Ocultar partes da imagem (image occlusion)" style="background:none;border:none;color:var(--teal,#94e2d5);cursor:pointer;font-size:0.78rem;">🕶️</button>` : ''}
      <button onclick="blocoParaFlashcard(${b.id})" title="Criar flashcard (revisão espaçada)" style="background:none;border:none;color:var(--mauve,#cba6f7);cursor:pointer;font-size:0.78rem;">🧠</button>
      <button onclick="excluirBlocoRevisao(${b.id})" title="Excluir" style="background:none;border:none;color:var(--red,#f38ba8);cursor:pointer;font-size:0.78rem;">🗑</button>
    </div>
    ${titulo}${img}${conteudo}
  </div>`;
}

// --- Capturar texto selecionado no PDF ---
// Lê o texto atualmente selecionado dentro do iframe do PDF.js (mesma origem).
function _getSelecaoIframe() {
  const frame = document.getElementById('pdf-frame');
  try {
    const sel = frame && frame.contentWindow && frame.contentWindow.getSelection
      ? frame.contentWindow.getSelection().toString()
      : '';
    if (sel && sel.trim()) return sel.trim();
  } catch (e) { /* cross-origin improvável (PDF.js é self-hosted em /pdfjs) */ }
  // Fallback: seleção na janela principal.
  try {
    const s = window.getSelection ? window.getSelection().toString() : '';
    return (s || '').trim();
  } catch (e) { return ''; }
}

// Captura o texto selecionado no PDF e salva como bloco de texto no caderno.
async function capturarSelecaoTexto() {
  const texto = _getSelecaoIframe();
  if (!texto) {
    showStudyToast('✍️ Selecione um trecho de texto no PDF primeiro.');
    return;
  }
  // Normaliza quebras de linha artificiais do PDF (uma frase quebrada em várias linhas).
  const limpo = texto.replace(/\s*\n\s*/g, ' ').replace(/\s{2,}/g, ' ').trim();
  const titulo = await promptModal('Título (opcional):', { title: '✍️ Capturar seleção', placeholder: 'Ex: Art. 5º, inciso X' });
  if (titulo === null) return; // cancelou
  const res = await fetch('/api/revisao', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pdf_path: path, tipo: 'texto', titulo: titulo.trim(), conteudo: limpo, pagina: currentPage }),
  });
  if (res.ok) {
    showStudyToast('✍️ Trecho capturado no caderno!');
    if (!revisaoVisible) toggleRevisaoPanel(); else loadRevisao();
  } else {
    const err = await res.json().catch(() => ({}));
    showStudyToast('⚠️ ' + (err.detail || 'Erro ao capturar trecho.'));
  }
}

// --- Nota de texto ---
async function adicionarNotaRevisao() {
  const texto = await promptModal('Escreva o resumo/nota para o caderno de revisão:', { title: '📝 Nota de revisão', multiline: true });
  if (!texto || !texto.trim()) return;
  const titulo = await promptModal('Título (opcional):', { title: 'Título da nota' });
  await fetch('/api/revisao', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pdf_path: path, tipo: 'texto', titulo: (titulo || '').trim(), conteudo: texto.trim(), pagina: currentPage }),
  });
  showStudyToast('📑 Nota adicionada ao caderno!');
  loadRevisao();
}

// --- Recorte de imagem da página ---
function _getPageCanvas() {
  // Obtém o canvas da página atual renderizada dentro do iframe do PDF.js.
  const frame = document.getElementById('pdf-frame');
  try {
    const app = frame.contentWindow?.PDFViewerApplication;
    if (!app || !app.pdfViewer) return null;
    const pageView = app.pdfViewer.getPageView(currentPage - 1);
    if (!pageView) return null;
    // PDF.js expõe o canvas renderizado em pageView.canvas.
    const canvas = pageView.canvas || (pageView.div && pageView.div.querySelector('canvas'));
    return canvas || null;
  } catch (e) {
    return null;
  }
}

function iniciarRecorte() {
  const canvas = _getPageCanvas();
  if (!canvas) {
    showStudyToast('⚠️ Página ainda renderizando. Role até a página e tente de novo.');
    return;
  }
  const overlay = document.getElementById('crop-overlay');
  overlay.style.display = 'block';
  document.getElementById('crop-rect').style.display = 'none';
  _cropState = null;
}

function cancelarRecorte() {
  document.getElementById('crop-overlay').style.display = 'none';
  document.getElementById('crop-rect').style.display = 'none';
  _cropState = null;
}

(function _setupCropEvents() {
  const overlay = document.getElementById('crop-overlay');
  const rect = document.getElementById('crop-rect');
  if (!overlay) return;

  overlay.addEventListener('mousedown', (e) => {
    if (e.target.closest('#crop-hint')) return;
    _cropState = { startX: e.clientX, startY: e.clientY };
    rect.style.left = e.clientX + 'px';
    rect.style.top = e.clientY + 'px';
    rect.style.width = '0px';
    rect.style.height = '0px';
    rect.style.display = 'block';
  });

  overlay.addEventListener('mousemove', (e) => {
    if (!_cropState) return;
    const x = Math.min(e.clientX, _cropState.startX);
    const y = Math.min(e.clientY, _cropState.startY);
    const w = Math.abs(e.clientX - _cropState.startX);
    const h = Math.abs(e.clientY - _cropState.startY);
    rect.style.left = x + 'px';
    rect.style.top = y + 'px';
    rect.style.width = w + 'px';
    rect.style.height = h + 'px';
  });

  overlay.addEventListener('mouseup', (e) => {
    if (!_cropState) return;
    const x = Math.min(e.clientX, _cropState.startX);
    const y = Math.min(e.clientY, _cropState.startY);
    const w = Math.abs(e.clientX - _cropState.startX);
    const h = Math.abs(e.clientY - _cropState.startY);
    _cropState = null;
    overlay.style.display = 'none';
    rect.style.display = 'none';
    if (w < 8 || h < 8) { showStudyToast('Seleção muito pequena.'); return; }
    _processarRecorte(x, y, w, h);
  });
})();

function _processarRecorte(vx, vy, vw, vh) {
  const frame = document.getElementById('pdf-frame');
  const canvas = _getPageCanvas();
  if (!canvas) { showStudyToast('⚠️ Não foi possível acessar a página.'); return; }

  // Retângulo do iframe na viewport da janela principal.
  const frameRect = frame.getBoundingClientRect();
  // Retângulo do canvas relativo ao documento do iframe → soma o offset do iframe.
  const canvasRect = canvas.getBoundingClientRect(); // relativo ao iframe

  // Coordenadas da seleção relativas ao canvas (em CSS px).
  const relX = vx - frameRect.left - canvasRect.left;
  const relY = vy - frameRect.top - canvasRect.top;

  // Escala entre pixels reais do canvas e o tamanho CSS exibido.
  const scaleX = canvas.width / canvasRect.width;
  const scaleY = canvas.height / canvasRect.height;

  // Interseção com a área visível do canvas.
  const sx = Math.max(0, relX) * scaleX;
  const sy = Math.max(0, relY) * scaleY;
  const sw = Math.min(vw, canvasRect.width - Math.max(0, relX)) * scaleX;
  const sh = Math.min(vh, canvasRect.height - Math.max(0, relY)) * scaleY;

  if (sw < 4 || sh < 4) {
    showStudyToast('⚠️ Selecione uma área sobre o conteúdo do PDF.');
    return;
  }

  const out = document.createElement('canvas');
  // Upscale para garantir nitidez ao exibir grande: recortes estreitos são
  // ampliados até uma largura-alvo (~1400px), preservando a proporção.
  const larguraAlvo = 1400;
  const fator = sw < larguraAlvo ? Math.min(3, larguraAlvo / sw) : 1;
  out.width = Math.round(sw * fator);
  out.height = Math.round(sh * fator);
  const ctx = out.getContext('2d');
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  // Fundo branco (PDF pode ter transparência).
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, out.width, out.height);
  try {
    ctx.drawImage(canvas, sx, sy, sw, sh, 0, 0, out.width, out.height);
  } catch (e) {
    showStudyToast('⚠️ Erro ao recortar (canvas protegido).');
    return;
  }

  let dataUrl;
  try {
    dataUrl = out.toDataURL('image/png');
  } catch (e) {
    showStudyToast('⚠️ Não foi possível gerar a imagem.');
    return;
  }

  // Abre modal de confirmação com preview.
  document.getElementById('crop-preview').src = dataUrl;
  document.getElementById('crop-titulo').value = '';
  document.getElementById('crop-comentario').value = '';
  document.getElementById('crop-confirm').style.display = 'flex';
  document.getElementById('crop-confirm').dataset.img = dataUrl;
}

function descartarRecorte() {
  const modal = document.getElementById('crop-confirm');
  modal.style.display = 'none';
  modal.dataset.img = '';
}

async function salvarRecorte() {
  const modal = document.getElementById('crop-confirm');
  const dataUrl = modal.dataset.img;
  if (!dataUrl) { descartarRecorte(); return; }
  const titulo = document.getElementById('crop-titulo').value.trim();
  const comentario = document.getElementById('crop-comentario').value.trim();

  const res = await fetch('/api/revisao', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pdf_path: path, tipo: 'recorte',
      titulo, conteudo: comentario, imagem_data: dataUrl, pagina: currentPage,
    }),
  });
  if (res.ok) {
    showStudyToast('📑 Recorte salvo no caderno!');
    modal.style.display = 'none';
    modal.dataset.img = '';
    if (!revisaoVisible) toggleRevisaoPanel(); else loadRevisao();
  } else {
    const err = await res.json().catch(() => ({}));
    showStudyToast('⚠️ ' + (err.detail || 'Erro ao salvar recorte.'));
  }
}

// --- Editar / mover / excluir blocos ---
async function editarBlocoRevisao(id) {
  const blocos = await fetch(`/api/revisao/${encodePath(path)}`).then(r => r.json());
  const b = blocos.find(x => x.id === id);
  if (!b) return;
  const titulo = await promptModal('Título:', { title: 'Editar bloco', defaultValue: b.titulo || '' });
  if (titulo === null) return;
  const conteudo = await promptModal('Comentário / texto:', { title: 'Editar bloco', defaultValue: b.conteudo || '', multiline: true });
  await fetch(`/api/revisao/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ titulo: titulo.trim(), conteudo: (conteudo || '').trim() }),
  });
  loadRevisao();
}

async function moverBlocoRevisao(id, dir) {
  const blocos = await fetch(`/api/revisao/${encodePath(path)}`).then(r => r.json());
  const idx = blocos.findIndex(x => x.id === id);
  if (idx === -1) return;
  const alvo = idx + dir;
  if (alvo < 0 || alvo >= blocos.length) return;
  // Troca as ordens dos dois blocos.
  const a = blocos[idx], b = blocos[alvo];
  await Promise.all([
    fetch(`/api/revisao/${a.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ordem: b.ordem }) }),
    fetch(`/api/revisao/${b.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ordem: a.ordem }) }),
  ]);
  loadRevisao();
}

async function excluirBlocoRevisao(id) {
  if (!(await confirmModal('Excluir bloco', 'Remover este bloco do caderno de revisão?', { type: 'danger', confirmText: 'Excluir' }))) return;
  await fetch(`/api/revisao/${id}`, { method: 'DELETE' });
  loadRevisao();
}

// --- Tag/categoria do bloco ---
async function setBlocoTag(id, tag) {
  const res = await fetch(`/api/revisao/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tag }),
  });
  if (res.ok) {
    showStudyToast('🏷️ Categoria atualizada.');
    loadRevisao();
  } else {
    showStudyToast('⚠️ Erro ao atualizar categoria.');
  }
}
async function blocoParaFlashcard(id) {
  const res = await fetch(`/api/revisao/${id}/flashcard`, { method: 'POST' });
  if (res.ok) {
    const data = await res.json();
    showStudyToast(`🧠 Flashcard criado${data.materia ? ' em ' + data.materia : ''}! Será revisado (FSRS).`);
  } else {
    const err = await res.json().catch(() => ({}));
    showStudyToast('⚠️ ' + (err.detail || 'Não foi possível criar o flashcard.'));
  }
}

// --- Agendamento espaçado do caderno (Spaced Practice) ---
// Atualiza a linha de status do painel com a próxima revisão agendada.
async function _loadAgendaStatus() {
  const el = document.getElementById('revisao-agenda-status');
  if (!el) return;
  try {
    const a = await fetch(`/api/revisao-agenda/${encodePath(path)}`).then(r => r.json());
    if (a && a.agendado) {
      const hoje = new Date().toISOString().slice(0, 10);
      const venceu = a.proxima_revisao <= hoje;
      el.style.display = 'block';
      el.innerHTML = venceu
        ? `🔔 Revisão pendente (agendada p/ ${a.proxima_revisao}). <span style="text-decoration:underline;cursor:pointer;" onclick="marcarCadernoRevisado()">Marcar como revisado</span>`
        : `📅 Próxima revisão: <strong>${a.proxima_revisao}</strong> (a cada ${a.intervalo_dias}d). <span style="text-decoration:underline;cursor:pointer;" onclick="marcarCadernoRevisado()">Revisei hoje</span>`;
    } else {
      el.style.display = 'none';
    }
  } catch (e) { /* silencioso */ }
}

// Abre um mini-modal com opções de intervalo (sem diálogo nativo).
function abrirAgendaRevisao() {
  let modal = document.getElementById('agenda-revisao-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'agenda-revisao-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1002;display:flex;align-items:center;justify-content:center;padding:16px;';
    document.body.appendChild(modal);
  }
  const opcoes = [1, 3, 7, 15, 30].map(d =>
    `<button onclick="agendarCaderno(${d})" style="background:var(--bg-elevated,#45475a);color:var(--text,#cdd6f4);border:1px solid var(--border,#45475a);border-radius:8px;padding:10px;font-size:0.85rem;cursor:pointer;">Em ${d} dia${d > 1 ? 's' : ''}</button>`
  ).join('');
  modal.innerHTML = `
    <div style="background:var(--bg-surface,#313244);border:1px solid var(--border,#45475a);border-radius:14px;padding:22px;max-width:380px;width:100%;">
      <h3 style="color:var(--peach,#fab387);margin:0 0 6px;font-size:1rem;">📅 Agendar revisão do caderno</h3>
      <p style="font-size:0.8rem;color:var(--text-sub,#a6adc8);margin:0 0 14px;">Spaced Practice: escolha quando revisar este caderno de novo. A cada revisão concluída, o intervalo aumenta automaticamente.</p>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:12px;">${opcoes}</div>
      <div style="display:flex;justify-content:space-between;gap:8px;">
        <button onclick="cancelarAgendaCaderno()" title="Remover agendamento" style="background:var(--bg,#1e1e2e);border:1px solid var(--border,#45475a);color:var(--red,#f38ba8);border-radius:8px;padding:8px 14px;font-size:0.8rem;cursor:pointer;">🗑 Cancelar agenda</button>
        <button onclick="fecharAgendaRevisao()" style="background:var(--bg,#1e1e2e);border:1px solid var(--border,#45475a);color:var(--text,#cdd6f4);border-radius:8px;padding:8px 16px;font-size:0.82rem;cursor:pointer;">Fechar</button>
      </div>
    </div>`;
  modal.style.display = 'flex';
}

function fecharAgendaRevisao() {
  const modal = document.getElementById('agenda-revisao-modal');
  if (modal) modal.style.display = 'none';
}

async function agendarCaderno(dias) {
  const res = await fetch('/api/revisao-agenda', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pdf_path: path, dias }),
  });
  if (res.ok) {
    const d = await res.json();
    showStudyToast(`📅 Revisão agendada para ${d.proxima_revisao}!`);
    fecharAgendaRevisao();
    _loadAgendaStatus();
  } else {
    showStudyToast('⚠️ Erro ao agendar revisão.');
  }
}

async function marcarCadernoRevisado() {
  const res = await fetch(`/api/revisao-agenda/${encodePath(path)}/revisado`, { method: 'POST' });
  if (res.ok) {
    const d = await res.json();
    showStudyToast(`✅ Revisado! Próxima em ${d.intervalo_dias} dias (${d.proxima_revisao}).`);
    _loadAgendaStatus();
  } else {
    showStudyToast('⚠️ Erro ao registrar revisão.');
  }
}

async function cancelarAgendaCaderno() {
  await fetch(`/api/revisao-agenda/${encodePath(path)}`, { method: 'DELETE' });
  showStudyToast('Agendamento removido.');
  fecharAgendaRevisao();
  _loadAgendaStatus();
}

// --- Auto-gerar blocos de revisão com IA ---
function abrirGerarRevisaoIA() {
  const pgAtual = currentPage || 1;
  let modal = document.getElementById('gerar-revisao-ia-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'gerar-revisao-ia-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:1002;display:flex;align-items:center;justify-content:center;padding:16px;';
    document.body.appendChild(modal);
  }
  modal.innerHTML = `
    <div style="background:var(--bg-surface,#313244);border:1px solid var(--border,#45475a);border-radius:14px;padding:20px;max-width:440px;width:100%;">
      <h3 style="color:var(--mauve,#cba6f7);margin:0 0 4px;font-size:1rem;">✨ Gerar revisão com IA</h3>
      <p style="font-size:0.78rem;color:var(--text-sub,#a6adc8);margin:0 0 14px;">A IA lê o intervalo de páginas e cria blocos de resumo direto no caderno.</p>
      <div style="display:flex;gap:8px;margin-bottom:14px;">
        <label style="flex:1;font-size:0.78rem;color:var(--text,#cdd6f4);">Pág. inicial
          <input type="number" id="gri-pg-ini" min="1" value="${pgAtual}" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border,#45475a);background:var(--bg,#1e1e2e);color:var(--text,#cdd6f4);">
        </label>
        <label style="flex:1;font-size:0.78rem;color:var(--text,#cdd6f4);">Pág. final
          <input type="number" id="gri-pg-fim" min="1" value="${pgAtual}" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border,#45475a);background:var(--bg,#1e1e2e);color:var(--text,#cdd6f4);">
        </label>
      </div>
      <div id="gri-status" style="display:none;font-size:0.8rem;color:var(--peach,#fab387);margin-bottom:10px;"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button onclick="fecharGerarRevisaoIA()" style="background:var(--bg,#1e1e2e);border:1px solid var(--border,#45475a);color:var(--text,#cdd6f4);border-radius:8px;padding:8px 16px;font-size:0.82rem;cursor:pointer;">Fechar</button>
        <button id="gri-gerar" onclick="gerarRevisaoIA()" style="background:var(--mauve,#cba6f7);color:#1e1e2e;border:none;border-radius:8px;padding:8px 18px;font-weight:700;font-size:0.82rem;cursor:pointer;">Gerar</button>
      </div>
    </div>`;
  modal.style.display = 'flex';
}

function fecharGerarRevisaoIA() {
  const modal = document.getElementById('gerar-revisao-ia-modal');
  if (modal) modal.style.display = 'none';
}

async function gerarRevisaoIA() {
  const pgIni = Math.max(1, parseInt(document.getElementById('gri-pg-ini').value) || 1);
  const pgFim = Math.max(pgIni, parseInt(document.getElementById('gri-pg-fim').value) || pgIni);
  const status = document.getElementById('gri-status');
  const btn = document.getElementById('gri-gerar');
  status.style.display = 'block';
  status.textContent = '🤖 Lendo o PDF e gerando blocos...';
  btn.disabled = true; btn.style.opacity = '0.6';
  try {
    const res = await fetch('/api/revisao-ia/gerar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_path: path, pagina_inicial: pgIni, pagina_final: pgFim, materia: name }),
    });
    const data = await res.json();
    if (!res.ok) {
      status.style.color = 'var(--red,#f38ba8)';
      status.textContent = data.detail || 'Não foi possível gerar. Configure um provider de IA em Social → AI Tutor → ⚙️.';
      return;
    }
    showStudyToast(`✨ ${data.salvos} bloco(s) de revisão gerado(s) com IA!`);
    fecharGerarRevisaoIA();
    loadRevisao();
  } catch (e) {
    status.style.color = 'var(--red,#f38ba8)';
    status.textContent = 'Erro de conexão.';
  } finally {
    btn.disabled = false; btn.style.opacity = '1';
  }
}

async function abrirRevisaoTelaCheia() {
  const overlay = document.getElementById('revisao-fullscreen');
  const body = document.getElementById('rev-fs-body');
  console.log('[revisão FS] abrir: overlay=', !!overlay, 'body=', !!body, 'path=', path);
  document.getElementById('rev-fs-titulo').textContent = name;
  overlay.style.display = 'flex';
  // Sempre abre em modo leitura normal (recall desligado) para estado previsível.
  _revFsRecall = false;
  _revFsTagFiltro = '';
  _revFsBusca = '';
  const _fsBuscaInput = document.getElementById('rev-fs-busca');
  if (_fsBuscaInput) _fsBuscaInput.value = '';
  const rbtn = document.getElementById('rev-fs-recall-btn');
  if (rbtn) { rbtn.style.background = 'var(--bg-elevated,#45475a)'; rbtn.style.color = 'var(--peach,#fab387)'; }
  body.innerHTML = '<div style="text-align:center;color:var(--text-sub,#9399b2);padding:40px;">Carregando revisão...</div>';

  let blocos;
  try {
    const _resp = await fetch(`/api/revisao/${encodePath(path)}`);
    console.log('[revisão FS] fetch status=', _resp.status);
    blocos = await _resp.json();
    console.log('[revisão FS] blocos recebidos=', Array.isArray(blocos) ? blocos.length : blocos);
  } catch (e) {
    console.error('[revisão FS] erro no fetch:', e);
    body.innerHTML = '<div style="text-align:center;color:var(--red,#f38ba8);padding:40px;">Erro ao carregar revisão.</div>';
    return;
  }
  if (!Array.isArray(blocos) || blocos.length === 0) {
    console.warn('[revisão FS] resposta não é lista de blocos ou está vazia:', blocos);
    body.innerHTML = `<div style="max-width:760px;margin:0 auto;text-align:center;color:var(--text-sub,#9399b2);padding:60px 20px;line-height:1.7;">
      <div style="font-size:2.4rem;margin-bottom:12px;">📭</div>
      Caderno de revisão vazio.<br>Recorte partes do PDF ou adicione notas para montá-lo.</div>`;
    return;
  }

  _revFsBlocos = blocos;
  _renderRevFsDoc();
  console.log('[revisão FS] render concluído, blocos=', _revFsBlocos.length);
}

// Renderiza (ou re-renderiza) o documento da tela cheia respeitando o modo recall.
function _renderRevFsDoc() {
  const body = document.getElementById('rev-fs-body');
  if (!body) return;
  try {
    // Chips de filtro por tag: mostra as tags presentes nos blocos + "Todas".
    const tagsPresentes = [...new Set(_revFsBlocos.map(b => b.tag || '').filter(Boolean))];
    const chip = (val, label, cor) => `<button onclick="setRevFsTagFiltro('${val}')" style="background:${_revFsTagFiltro === val ? cor : 'var(--bg-elevated,#45475a)'};color:${_revFsTagFiltro === val ? 'var(--bg,#1e1e2e)' : cor};border:1px solid ${cor};border-radius:999px;padding:3px 12px;font-size:0.75rem;cursor:pointer;font-weight:600;">${label}</button>`;
    const filtros = tagsPresentes.length > 0
      ? `<div style="max-width:840px;margin:0 auto 16px;display:flex;gap:6px;flex-wrap:wrap;justify-content:center;">
          ${chip('', 'Todas', 'var(--text-sub,#9399b2)')}
          ${tagsPresentes.map(t => chip(t, (_REV_TAGS[t] || {}).label || t, (_REV_TAGS[t] || {}).cor || 'var(--text-sub,#9399b2)')).join('')}
        </div>`
      : '';
    const termo = (_revFsBusca || '').trim().toLowerCase();
    const visiveis = _revFsBlocos.filter(b => {
      if (_revFsTagFiltro && (b.tag || '') !== _revFsTagFiltro) return false;
      if (termo && !`${b.titulo || ''} ${b.conteudo || ''}`.toLowerCase().includes(termo)) return false;
      return true;
    });
    body.innerHTML = `<div id="rev-fs-doc" style="margin:0 auto;">
      ${_revFsRecall ? `<div style="max-width:840px;margin:0 auto 18px;padding:10px 14px;background:rgba(250,179,135,0.12);border:1px solid var(--peach,#fab387);border-radius:8px;font-size:0.85rem;color:var(--peach,#fab387);text-align:center;">🎯 Modo Recall ativo — tente lembrar o conteúdo antes de clicar para revelar.</div>` : ''}
      ${filtros}
      ${visiveis.length ? visiveis.map((b, i) => _renderBlocoFullscreen(b, i)).join('') : '<div style="text-align:center;color:var(--text-sub,#9399b2);padding:40px;">Nenhum bloco corresponde ao filtro/busca.</div>'}
    </div>`;
    applyRevFsZoom();
  } catch (e) {
    body.innerHTML = `<div style="text-align:center;color:var(--red,#f38ba8);padding:40px;">Erro ao renderizar a revisão: ${_escHtml(e && e.message ? e.message : String(e))}</div>`;
    console.error('[revisão tela cheia] erro ao renderizar:', e);
  }
}

// Aplica filtro de tag na tela cheia.
function setRevFsTagFiltro(tag) {
  _revFsTagFiltro = tag || '';
  _renderRevFsDoc();
}

// Aplica busca por termo na tela cheia. O input fica no header (fora de
// #rev-fs-body), então não é destruído pelo re-render — sem perda de foco.
function setRevFsBusca(termo) {
  _revFsBusca = termo || '';
  _renderRevFsDoc();
}

// Alterna o Modo Recall (Retrieval Practice) e re-renderiza.
function toggleRevFsRecall() {
  _revFsRecall = !_revFsRecall;
  const btn = document.getElementById('rev-fs-recall-btn');
  if (btn) {
    btn.style.background = _revFsRecall ? 'var(--peach,#fab387)' : 'var(--bg-elevated,#45475a)';
    btn.style.color = _revFsRecall ? 'var(--bg,#1e1e2e)' : 'var(--peach,#fab387)';
  }
  _renderRevFsDoc();
}

// Revela um bloco individual coberto pela cortina de recall.
function revelarBlocoRecall(idx) {
  const cortina = document.getElementById(`rev-recall-cover-${idx}`);
  const alvo = document.getElementById(`rev-recall-content-${idx}`);
  if (cortina) cortina.style.display = 'none';
  if (alvo) alvo.style.display = 'block';
}

function _renderBlocoFullscreen(b, idx) {
  const titulo = b.titulo
    ? `<h2 style="font-size:1.35em;color:var(--teal,#94e2d5);margin:0 0 12px;border-bottom:2px solid var(--border,#45475a);padding-bottom:8px;">${_escHtml(b.titulo)}</h2>`
    : '';
  // width:100% faz o recorte preencher a largura do documento (ocupa melhor o
  // espaço mesmo quando o PNG original é pequeno). image-rendering suaviza o upscale.
  const img = (b.tipo === 'recorte' && b.imagem_data)
    ? _imgComOclusoes(b, idx)
    : '';
  const conteudo = b.conteudo
    ? `<div style="font-size:1.02em;color:var(--text,#cdd6f4);line-height:1.75;white-space:pre-wrap;margin-bottom:10px;">${_escHtml(b.conteudo)}</div>`
    : '';

  // Modo Recall: oculta imagem+conteúdo sob uma cortina clicável (Retrieval
  // Practice). O título e a página ficam visíveis como "dica" para o recall.
  // Exceção: recortes que já têm oclusões usam os próprios retângulos como
  // mecanismo de recall — não recebem a cortina cheia.
  const temOclusao = b.tipo === 'recorte' && _parseOclusoes(b).length > 0;
  let corpo;
  if (_revFsRecall && !temOclusao && (img || conteudo)) {
    corpo = `
      <div id="rev-recall-cover-${idx}" onclick="revelarBlocoRecall(${idx})" title="Clique para revelar" style="cursor:pointer;background:repeating-linear-gradient(45deg,var(--bg-elevated,#45475a),var(--bg-elevated,#45475a) 10px,var(--bg-surface,#313244) 10px,var(--bg-surface,#313244) 20px);border:2px dashed var(--peach,#fab387);border-radius:8px;padding:28px 16px;text-align:center;color:var(--peach,#fab387);font-size:0.9em;">
        🎯 Tente lembrar o conteúdo desta seção.<br><strong>Clique para revelar</strong> 👁
      </div>
      <div id="rev-recall-content-${idx}" style="display:none;">${img}${conteudo}</div>`;
  } else {
    corpo = `${img}${conteudo}`;
  }

  const tagBadge = (b.tag && _REV_TAGS[b.tag])
    ? `<span style="font-size:0.7em;padding:2px 10px;border-radius:999px;background:${_REV_TAGS[b.tag].cor};color:var(--bg,#1e1e2e);font-weight:700;margin-left:8px;">${_REV_TAGS[b.tag].label}</span>`
    : '';
  return `<section style="background:var(--bg-surface,#313244);border-radius:12px;padding:24px 28px;margin-bottom:22px;box-shadow:0 2px 12px rgba(0,0,0,0.25);${b.tag && _REV_TAGS[b.tag] ? `border-left:4px solid ${_REV_TAGS[b.tag].cor};` : ''}">
    <div style="font-size:0.75em;color:var(--blue,#89b4fa);margin-bottom:10px;">
      <span style="cursor:pointer;" onclick="goToPage(${b.pagina});fecharRevisaoTelaCheia();" title="Abrir a página ${b.pagina} no PDF">📄 Página ${b.pagina} — abrir no PDF ↪</span>${tagBadge}
    </div>
    ${titulo}${corpo}
  </section>`;
}

function fecharRevisaoTelaCheia() {
  document.getElementById('revisao-fullscreen').style.display = 'none';
}

// ---------- Image Occlusion (cloze visual) ----------
// Parseia o JSON de oclusões de um bloco em array de {x,y,w,h} (0-1).
function _parseOclusoes(b) {
  if (!b || !b.oclusoes) return [];
  try {
    const arr = JSON.parse(b.oclusoes);
    return Array.isArray(arr) ? arr : [];
  } catch (e) { return []; }
}

// Renderiza a imagem do recorte com retângulos de oclusão sobrepostos. Cada
// retângulo revela o trecho ao ser clicado (Retrieval Practice visual).
function _imgComOclusoes(b, idx) {
  const regs = _parseOclusoes(b);
  const imgTag = `<img src="${b.imagem_data}" alt="Recorte p.${b.pagina}" style="width:100%;height:auto;border-radius:8px;display:block;border:1px solid var(--border,#45475a);box-shadow:0 2px 10px rgba(0,0,0,0.35);">`;
  if (regs.length === 0) {
    return `<div style="margin:0 auto 14px;">${imgTag}</div>`;
  }
  const overlays = regs.map((r, ri) => `
    <div onclick="this.style.opacity=this.style.opacity==='0'?'1':'0';" title="Clique para revelar/ocultar"
      style="position:absolute;left:${(r.x * 100).toFixed(2)}%;top:${(r.y * 100).toFixed(2)}%;width:${(r.w * 100).toFixed(2)}%;height:${(r.h * 100).toFixed(2)}%;background:var(--teal,#94e2d5);border-radius:3px;cursor:pointer;transition:opacity 0.15s;" data-oc="${idx}-${ri}"></div>`).join('');
  return `<div style="position:relative;margin:0 auto 14px;">${imgTag}${overlays}</div>`;
}

// --- Editor de oclusão ---
let _ocluirState = null; // { id, regs: [], dragStart, imgEl, wrapEl }

async function abrirOclusaoEditor(id) {
  const blocos = await fetch(`/api/revisao/${encodePath(path)}`).then(r => r.json());
  const b = Array.isArray(blocos) ? blocos.find(x => x.id === id) : null;
  if (!b || b.tipo !== 'recorte' || !b.imagem_data) { showStudyToast('⚠️ Bloco de recorte não encontrado.'); return; }

  const editor = document.getElementById('oclusao-editor');
  const img = document.getElementById('oclusao-img');
  const wrap = document.getElementById('oclusao-canvas-wrap');
  img.src = b.imagem_data;
  _ocluirState = { id, regs: _parseOclusoes(b), dragStart: null, imgEl: img, wrapEl: wrap };
  editor.style.display = 'flex';
  // Aguarda a imagem ter dimensões para desenhar as regiões existentes.
  if (img.complete) _ocluirRedesenhar(); else img.onload = _ocluirRedesenhar;
}

// Redesenha as regiões já existentes sobre a imagem (no editor).
function _ocluirRedesenhar() {
  const { wrapEl, regs } = _ocluirState;
  // Remove overlays antigos (mantém a <img>).
  wrapEl.querySelectorAll('.oc-edit-rect').forEach(el => el.remove());
  regs.forEach((r, i) => {
    const d = document.createElement('div');
    d.className = 'oc-edit-rect';
    d.title = 'Clique para remover';
    d.style.cssText = `position:absolute;left:${r.x * 100}%;top:${r.y * 100}%;width:${r.w * 100}%;height:${r.h * 100}%;background:rgba(148,226,213,0.75);border:1px solid #94e2d5;border-radius:3px;cursor:pointer;`;
    d.addEventListener('click', (e) => { e.stopPropagation(); _ocluirState.regs.splice(i, 1); _ocluirRedesenhar(); });
    wrapEl.appendChild(d);
  });
}

// Setup de arraste no wrap do editor (uma vez).
// As coordenadas são calculadas relativas à <img> renderizada (getBoundingClientRect
// da imagem), não do wrap — o wrap inline-block pode ter tamanho diferente da
// imagem (por max-height:70vh), o que deslocaria as regiões.
(function _setupOclusaoEvents() {
  const wrap = document.getElementById('oclusao-canvas-wrap');
  if (!wrap) return;
  let temp = null;

  const imgRect = () => document.getElementById('oclusao-img').getBoundingClientRect();

  wrap.addEventListener('mousedown', (e) => {
    if (!_ocluirState || e.target.classList.contains('oc-edit-rect')) return;
    e.preventDefault();
    const rect = imgRect();
    _ocluirState.dragStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    temp = document.createElement('div');
    temp.className = 'oc-edit-temp';
    temp.style.cssText = 'position:absolute;background:rgba(148,226,213,0.5);border:1px dashed #94e2d5;border-radius:3px;pointer-events:none;';
    wrap.appendChild(temp);
  });

  wrap.addEventListener('mousemove', (e) => {
    if (!_ocluirState || !_ocluirState.dragStart || !temp) return;
    const rect = imgRect();
    // Clampa dentro da imagem.
    const cx = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    const cy = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
    const x = Math.min(cx, _ocluirState.dragStart.x), y = Math.min(cy, _ocluirState.dragStart.y);
    const w = Math.abs(cx - _ocluirState.dragStart.x), h = Math.abs(cy - _ocluirState.dragStart.y);
    temp.style.left = x + 'px'; temp.style.top = y + 'px';
    temp.style.width = w + 'px'; temp.style.height = h + 'px';
  });

  wrap.addEventListener('mouseup', (e) => {
    if (!_ocluirState || !_ocluirState.dragStart) return;
    const rect = imgRect();
    const cx = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    const cy = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
    const x = Math.min(cx, _ocluirState.dragStart.x), y = Math.min(cy, _ocluirState.dragStart.y);
    const w = Math.abs(cx - _ocluirState.dragStart.x), h = Math.abs(cy - _ocluirState.dragStart.y);
    _ocluirState.dragStart = null;
    if (temp) { temp.remove(); temp = null; }
    // Converte px → coords relativas (0-1) à imagem exibida.
    if (w > 6 && h > 6 && rect.width > 0 && rect.height > 0) {
      _ocluirState.regs.push({
        x: +(x / rect.width).toFixed(4), y: +(y / rect.height).toFixed(4),
        w: +(w / rect.width).toFixed(4), h: +(h / rect.height).toFixed(4),
      });
      _ocluirRedesenhar();
    }
  });
})();

function ocluirLimpar() {
  if (!_ocluirState) return;
  _ocluirState.regs = [];
  _ocluirRedesenhar();
}

async function ocluirSalvar() {
  if (!_ocluirState) return;
  const payload = JSON.stringify(_ocluirState.regs);
  console.log('[oclusão] salvando', _ocluirState.regs.length, 'região(ões) no bloco', _ocluirState.id, payload);
  if (_ocluirState.regs.length === 0) {
    showStudyToast('⚠️ Nenhuma região desenhada. Arraste sobre a imagem antes de salvar.');
    return;
  }
  try {
    const res = await fetch(`/api/revisao/${_ocluirState.id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ oclusoes: payload }),
    });
    console.log('[oclusão] PUT status', res.status);
    if (res.ok) {
      showStudyToast(`🕶️ ${_ocluirState.regs.length} região(ões) de oclusão salva(s)!`);
      ocluirFechar();
      loadRevisao();
    } else {
      const err = await res.json().catch(() => ({}));
      showStudyToast('⚠️ ' + (err.detail || `Erro ao salvar oclusões (HTTP ${res.status}).`));
    }
  } catch (e) {
    console.error('[oclusão] erro no PUT:', e);
    showStudyToast('⚠️ Erro de conexão ao salvar oclusões.');
  }
}

function ocluirFechar() {
  const editor = document.getElementById('oclusao-editor');
  if (editor) editor.style.display = 'none';
  const wrap = document.getElementById('oclusao-canvas-wrap');
  if (wrap) wrap.querySelectorAll('.oc-edit-rect,.oc-edit-temp').forEach(el => el.remove());
  _ocluirState = null;
}

function revFsZoom(dir) {
  _revFsZoom = Math.max(0.6, Math.min(2.2, _revFsZoom + dir * 0.15));
  applyRevFsZoom();
}

function applyRevFsZoom() {
  const doc = document.getElementById('rev-fs-doc');
  if (!doc) return;
  // O zoom escala a fonte E a largura do documento — como as imagens usam
  // width:100%, elas crescem/encolhem junto com o zoom (não só o texto).
  // Largura base ~840px, expandindo até ~1600px no zoom máximo.
  doc.style.fontSize = _revFsZoom.toFixed(2) + 'rem';
  const largura = Math.round(840 * _revFsZoom);
  doc.style.maxWidth = largura + 'px';
}

// --- Export ---
async function exportRevisaoMd() {
  // window.open() faz navegação direta e NÃO envia o header Authorization →
  // 401 quando AUTH_ENABLED=true. Buscamos via fetch (o interceptor injeta o
  // token) e disparamos o download a partir do Blob.
  try {
    const res = await fetch(`/api/revisao/${encodePath(path)}/export`);
    if (!res.ok) {
      showStudyToast(res.status === 401 ? '⚠️ Sessão expirada. Faça login novamente.' : `⚠️ Falha ao exportar (HTTP ${res.status}).`);
      return;
    }
    let filename = `revisao_${name.replace(/\s+/g, '_')}.md`;
    const disp = res.headers.get('Content-Disposition') || '';
    const m = disp.match(/filename="?([^"]+)"?/i);
    if (m) filename = m[1];
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
  } catch (e) {
    showStudyToast('⚠️ Erro ao exportar o caderno.');
  }
}

async function imprimirRevisao() {
  const blocos = await fetch(`/api/revisao/${encodePath(path)}`).then(r => r.json());
  if (!Array.isArray(blocos) || blocos.length === 0) { showStudyToast('Caderno vazio.'); return; }
  const nome = name;
  const html = `<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>Revisão — ${_escHtml(nome)}</title>
    <style>
      body{font-family:system-ui,Arial,sans-serif;color:#1a1a1a;max-width:800px;margin:24px auto;padding:0 16px;line-height:1.5;}
      h1{font-size:1.4rem;border-bottom:2px solid #333;padding-bottom:8px;}
      .bloco{margin:18px 0;padding-bottom:14px;border-bottom:1px solid #ddd;page-break-inside:avoid;}
      .bloco h2{font-size:1.05rem;margin:0 0 6px;color:#111;}
      .pag{font-size:0.75rem;color:#777;margin-bottom:6px;}
      img{max-width:100%;border:1px solid #ccc;border-radius:4px;display:block;margin:6px 0;}
      p{white-space:pre-wrap;margin:6px 0;font-size:0.92rem;}
      @media print{body{margin:0;}}
    </style></head><body>
    <h1>📑 Caderno de Revisão — ${_escHtml(nome)}</h1>
    ${blocos.map(b => `<div class="bloco">
      ${b.titulo ? `<h2>${_escHtml(b.titulo)}</h2>` : ''}
      <div class="pag">Página ${b.pagina}</div>
      ${(b.tipo === 'recorte' && b.imagem_data) ? `<img src="${b.imagem_data}" alt="Recorte p.${b.pagina}">` : ''}
      ${b.conteudo ? `<p>${_escHtml(b.conteudo)}</p>` : ''}
    </div>`).join('')}
    <script>window.onload=function(){setTimeout(function(){window.print();},300);};<\/script>
    </body></html>`;
  const w = window.open('', '_blank');
  if (!w) { showStudyToast('Permita pop-ups para imprimir.'); return; }
  w.document.write(html);
  w.document.close();
}

// Atalho de teclado C para o caderno + Esc para cancelar recorte
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'c' || e.key === 'C') toggleRevisaoPanel();
  if (e.key === 'm' || e.key === 'M') toggleBookmarksPanel();
  if (e.key === 'h' || e.key === 'H') toggleDestaquesPanel();
  if (e.key === 'Escape' && document.getElementById('crop-overlay').style.display === 'block') cancelarRecorte();
  if (e.key === 'Escape' && document.getElementById('revisao-fullscreen').style.display === 'flex') fecharRevisaoTelaCheia();
});

// ==================== DESTAQUES (marca-texto persistente por página) ====================
// Mapa de cores: chave (backend) -> rgba para overlay semitransparente (highlight).
const _DESTAQUE_CORES = {
  yellow: 'rgba(249,226,175,0.45)',
  green: 'rgba(166,227,161,0.45)',
  blue: 'rgba(137,180,250,0.40)',
  pink: 'rgba(245,194,231,0.45)',
  orange: 'rgba(250,179,135,0.45)',
};
// Cores sólidas (para linha de sublinhado/tachado e contorno da caixa).
const _DESTAQUE_CORES_SOLIDAS = {
  yellow: '#f9e2af', green: '#a6e3a1', blue: '#89b4fa', pink: '#f5c2e7', orange: '#fab387',
};
let _destaques = [];          // cache de todos os destaques do PDF
let _selPendente = null;      // { pagina, rects:[{x,y,w,h}], texto } da seleção atual
let _destaquesVisible = false;
let _destaqueEstilo = 'highlight'; // estilo atual escolhido na barra

// Define o estilo de marcação atual e destaca o botão ativo na barra.
function setDestaqueEstilo(estilo) {
  _destaqueEstilo = estilo;
  const bar = document.getElementById('destaque-colorbar');
  if (bar) {
    bar.querySelectorAll('[data-estilo]').forEach(b => {
      const ativo = b.getAttribute('data-estilo') === estilo;
      b.style.outline = ativo ? '2px solid var(--accent,#cba6f7)' : 'none';
    });
  }
}

// Retorna o documento do iframe do PDF.js (mesma origem).
function _pdfDoc() {
  const frame = document.getElementById('pdf-frame');
  try { return frame && frame.contentDocument ? frame.contentDocument : null; } catch (e) { return null; }
}

// Acha a div.page (PDF.js) que contém um ponto, retornando {pageDiv, pagina}.
function _pageDivDoRect(doc, cx, cy) {
  const pages = doc.querySelectorAll('.page[data-page-number]');
  for (const pg of pages) {
    const r = pg.getBoundingClientRect();
    if (cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom) {
      return { pageDiv: pg, pagina: parseInt(pg.getAttribute('data-page-number'), 10) };
    }
  }
  return null;
}

// Captura a seleção atual dentro do iframe e monta _selPendente (rects 0-1 por página).
function _capturarSelecaoDestaque() {
  const doc = _pdfDoc();
  if (!doc) return null;
  const sel = doc.getSelection && doc.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
  const texto = sel.toString().trim();
  if (!texto) return null;

  const range = sel.getRangeAt(0);
  const clientRects = Array.from(range.getClientRects()).filter(r => r.width > 1 && r.height > 1);
  if (clientRects.length === 0) return null;

  let pagina = null, pageDiv = null;
  const rectsRel = [];
  for (const cr of clientRects) {
    const cx = cr.left + cr.width / 2, cy = cr.top + cr.height / 2;
    const hit = _pageDivDoRect(doc, cx, cy);
    if (!hit) continue;
    if (pagina === null) { pagina = hit.pagina; pageDiv = hit.pageDiv; }
    if (hit.pagina !== pagina) continue; // mantém simples: 1 página por destaque
    const pr = pageDiv.getBoundingClientRect();
    if (pr.width <= 0 || pr.height <= 0) continue;
    rectsRel.push({
      x: +((cr.left - pr.left) / pr.width).toFixed(4),
      y: +((cr.top - pr.top) / pr.height).toFixed(4),
      w: +(cr.width / pr.width).toFixed(4),
      h: +(cr.height / pr.height).toFixed(4),
    });
  }
  if (pagina === null || rectsRel.length === 0) return null;
  return { pagina, rects: rectsRel, texto: texto.slice(0, 5000) };
}

// Mostra a barra de cores perto do fim da seleção.
function _mostrarColorbar() {
  const doc = _pdfDoc();
  const frame = document.getElementById('pdf-frame');
  const bar = document.getElementById('destaque-colorbar');
  if (!doc || !bar) return;
  const sel = doc.getSelection();
  if (!sel || sel.rangeCount === 0) { _esconderColorbar(); return; }
  const rects = sel.getRangeAt(0).getClientRects();
  if (!rects.length) { _esconderColorbar(); return; }
  const last = rects[rects.length - 1];
  const fr = frame.getBoundingClientRect();
  let left = fr.left + last.right - 150;
  let top = fr.top + last.bottom + 6;
  left = Math.max(8, Math.min(window.innerWidth - 200, left));
  top = Math.max(48, Math.min(window.innerHeight - 50, top));
  bar.style.left = left + 'px';
  bar.style.top = top + 'px';
  bar.style.display = 'flex';
  setDestaqueEstilo(_destaqueEstilo); // realça o botão do estilo atual
}

function _esconderColorbar() {
  const bar = document.getElementById('destaque-colorbar');
  if (bar) bar.style.display = 'none';
}

// Cria um destaque a partir da seleção pendente, com a cor escolhida.
async function criarDestaque(cor) {
  const sel = _selPendente || _capturarSelecaoDestaque();
  if (!sel) { showStudyToast('🖍️ Selecione um trecho de texto no PDF primeiro.'); return; }
  _esconderColorbar();
  const estilo = _destaqueEstilo || 'highlight';
  try {
    const res = await fetch('/api/destaques', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_path: path, pagina: sel.pagina, cor, texto: sel.texto, rects: JSON.stringify(sel.rects), estilo }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      _destaques.push({ id: data.id, pdf_path: path, pagina: sel.pagina, cor, texto: sel.texto, rects: JSON.stringify(sel.rects), estilo });
      _renderDestaquesPagina(sel.pagina);
      showStudyToast('🖍️ Marcação salva!');
      const doc = _pdfDoc();
      if (doc && doc.getSelection) doc.getSelection().removeAllRanges();
    } else {
      showStudyToast('⚠️ ' + (data.detail || 'Erro ao salvar marcação.'));
    }
  } catch (e) {
    showStudyToast('⚠️ Erro de conexão ao salvar marcação.');
  }
  _selPendente = null;
}

// Carrega todos os destaques do PDF e desenha nas páginas já renderizadas.
async function carregarDestaques() {
  try {
    _destaques = await fetch(`/api/destaques/${encodePath(path)}`).then(r => r.json());
    if (!Array.isArray(_destaques)) _destaques = [];
  } catch (e) { _destaques = []; }
  _reaplicarTodosDestaques();
}

// Desenha os overlays de destaque de uma página específica dentro da div.page.
function _renderDestaquesPagina(pagina) {
  const doc = _pdfDoc();
  if (!doc) return;
  const pageDiv = doc.querySelector(`.page[data-page-number="${pagina}"]`);
  if (!pageDiv) return;
  let layer = pageDiv.querySelector('.concurseiro-hl-layer');
  if (layer) layer.remove();
  const doList = _destaques.filter(d => d.pagina === pagina);
  if (doList.length === 0) return;
  layer = doc.createElement('div');
  layer.className = 'concurseiro-hl-layer';
  layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:5;';
  for (const d of doList) {
    let rects = [];
    try { rects = JSON.parse(d.rects || '[]'); } catch (e) { rects = []; }
    const estilo = d.estilo || 'highlight';
    const corBg = _DESTAQUE_CORES[d.cor] || _DESTAQUE_CORES.yellow;
    const corSolida = _DESTAQUE_CORES_SOLIDAS[d.cor] || _DESTAQUE_CORES_SOLIDAS.yellow;
    for (const r of rects) {
      const div = doc.createElement('div');
      let extra;
      if (estilo === 'underline') {
        // Linha na base do retângulo (sublinhado).
        extra = `background:transparent;border-bottom:2px solid ${corSolida};`;
      } else if (estilo === 'strike') {
        // Linha no meio (tachado) via gradiente de fundo fino centralizado.
        extra = `background:linear-gradient(${corSolida},${corSolida}) center/100% 2px no-repeat;`;
      } else if (estilo === 'box') {
        // Contorno retangular.
        extra = `background:transparent;border:1.5px solid ${corSolida};border-radius:3px;`;
      } else {
        // highlight (padrão): marca-texto.
        extra = `background:${corBg};border-radius:2px;mix-blend-mode:multiply;`;
      }
      div.style.cssText = `position:absolute;left:${r.x * 100}%;top:${r.y * 100}%;width:${r.w * 100}%;height:${r.h * 100}%;pointer-events:auto;cursor:pointer;${extra}`;
      div.title = 'Clique para remover esta marcação';
      div.addEventListener('click', (ev) => { ev.stopPropagation(); excluirDestaque(d.id); });
      layer.appendChild(div);
    }
  }
  pageDiv.appendChild(layer);
}

// Reaplica em todas as páginas atualmente renderizadas no DOM do PDF.js.
function _reaplicarTodosDestaques() {
  const doc = _pdfDoc();
  if (!doc) return;
  const paginas = new Set(_destaques.map(d => d.pagina));
  paginas.forEach(p => _renderDestaquesPagina(p));
}

async function excluirDestaque(id) {
  if (!(await confirmModal('Remover destaque', 'Remover este destaque?', { type: 'danger', confirmText: 'Remover' }))) return;
  try {
    await fetch(`/api/destaques/${id}`, { method: 'DELETE' });
  } catch (e) { /* segue e atualiza local */ }
  const rem = _destaques.find(d => d.id === id);
  _destaques = _destaques.filter(d => d.id !== id);
  if (rem) _renderDestaquesPagina(rem.pagina);
  if (_destaquesVisible) _renderPainelDestaques();
  showStudyToast('Destaque removido.');
}

// --- Painel lateral de destaques ---
function toggleDestaquesPanel() {
  _destaquesVisible = !_destaquesVisible;
  const panel = document.getElementById('destaques-panel');
  panel.style.display = _destaquesVisible ? 'flex' : 'none';
  const viewer = document.getElementById('viewer');
  if (viewer) { viewer.style.transition = 'padding-right 0.25s ease'; viewer.style.paddingRight = _destaquesVisible ? '340px' : ''; }
  if (_destaquesVisible) _renderPainelDestaques();
}

function _renderPainelDestaques() {
  const body = document.getElementById('destaques-body');
  if (!body) return;
  if (!_destaques || _destaques.length === 0) {
    body.innerHTML = `<div style="color:var(--text-sub,#585b70);font-size:0.85rem;text-align:center;padding:24px 12px;line-height:1.6;">
      Nenhum destaque ainda.<br><br>Selecione um trecho de texto no PDF e escolha uma cor na barra que aparece.</div>`;
    return;
  }
  const ordenados = [..._destaques].sort((a, b) => a.pagina - b.pagina || a.id - b.id);
  const _ESTILO_ICONE = { highlight: '🖍️', underline: 'S̲', strike: 'S̶', box: '▢' };
  body.innerHTML = ordenados.map(d => {
    const cor = _DESTAQUE_CORES[d.cor] || _DESTAQUE_CORES.yellow;
    const txt = (d.texto && d.texto.trim()) ? _escHtml(d.texto.trim()) : '(sem texto)';
    const icone = _ESTILO_ICONE[d.estilo || 'highlight'] || '🖍️';
    return `<div style="background:var(--bg,#1e1e2e);border-left:4px solid ${cor};border-radius:8px;padding:10px 12px;margin-bottom:8px;">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
        <span title="Estilo" style="font-size:0.8rem;">${icone}</span>
        <span style="font-size:0.7rem;color:var(--blue,#89b4fa);cursor:pointer;" onclick="goToPage(${d.pagina})" title="Ir para a página">p.${d.pagina}</span>
        <span style="flex:1;"></span>
        <button onclick="excluirDestaque(${d.id})" title="Remover" style="background:none;border:none;color:var(--red,#f38ba8);cursor:pointer;font-size:0.78rem;">🗑</button>
      </div>
      <div style="font-size:0.82rem;color:var(--text,#cdd6f4);line-height:1.5;cursor:pointer;" onclick="goToPage(${d.pagina})">${txt}</div>
    </div>`;
  }).join('');
}

// Liga os eventos de seleção no iframe (chamado após o PDF.js carregar).
function _setupDestaqueEvents() {
  const doc = _pdfDoc();
  if (!doc) return false;
  if (doc._hlBound) return true; // evita bind duplicado
  doc._hlBound = true;
  doc.addEventListener('mouseup', () => {
    setTimeout(() => {
      const sel = _capturarSelecaoDestaque();
      if (sel) { _selPendente = sel; _mostrarColorbar(); }
      else { _selPendente = null; _esconderColorbar(); }
    }, 10);
  });
  doc.addEventListener('scroll', () => { _esconderColorbar(); reaplicarDestaquesDebounced(); }, true);
  return true;
}

// Reaplica destaques com debounce (páginas do PDF.js entram/saem do DOM ao rolar).
let _reaplicarTimer = null;
function reaplicarDestaquesDebounced() {
  clearTimeout(_reaplicarTimer);
  _reaplicarTimer = setTimeout(() => _reaplicarTodosDestaques(), 250);
}

// Inicialização: espera o PDF.js montar, liga eventos e carrega destaques.
function initDestaques() {
  let tries = 0;
  const iv = setInterval(() => {
    tries++;
    const doc = _pdfDoc();
    let app = null;
    try { app = document.getElementById('pdf-frame').contentWindow.PDFViewerApplication; } catch (e) { app = null; }
    if (doc && app && app.pdfDocument) {
      _setupDestaqueEvents();
      carregarDestaques();
      setInterval(() => _reaplicarTodosDestaques(), 1500);
      clearInterval(iv);
    } else if (tries > 60) {
      clearInterval(iv);
    }
  }, 300);
}


// === Window assignments for HTML onclick/onchange handlers ===
window.toggleNotePanel = toggleNotePanel;
window.toggleTimerPause = toggleTimerPause;
window.pararTimer = pararTimer;
window.criarDestaque = criarDestaque;
window.toggleDestaquesPanel = toggleDestaquesPanel;
window.excluirDestaque = excluirDestaque;
window.setDestaqueEstilo = setDestaqueEstilo;
window.addBookmark = addBookmark;
window.toggleBookmarksPanel = toggleBookmarksPanel;
window.loadBookmarksPanel = loadBookmarksPanel;
window.excluirBookmark = excluirBookmark;
window.quickFlashcard = quickFlashcard;
window.togglePomodoroMode = togglePomodoroMode;
window.abrirConfigPomodoro = abrirConfigPomodoro;
window.fecharConfigPomodoro = fecharConfigPomodoro;
window.resetConfigPomodoro = resetConfigPomodoro;
window.salvarConfigPomodoro = salvarConfigPomodoro;
window.toggleStudySummary = toggleStudySummary;
window.toggleActiveRecall = toggleActiveRecall;
window.askAIAboutPage = askAIAboutPage;
window.setStudyTechnique = setStudyTechnique;
window.toggleSidePanel = toggleSidePanel;
window.saveNote = saveNote;
window.deleteNote = deleteNote;
window.closeFlashcardModal = closeFlashcardModal;
window.saveQuickFlashcard = saveQuickFlashcard;
window.checkRecall = checkRecall;
window.rateRecall = rateRecall;
window.closeAIModal = closeAIModal;
window.aiAction = aiAction;
window.abrirGerarIA = abrirGerarIA;
window.selectSideAlt = selectSideAlt;
window.loadSidePanelQuestions = loadSidePanelQuestions;
window.goToPage = goToPage;
window.toggleRevisaoPanel = toggleRevisaoPanel;
window.iniciarRecorte = iniciarRecorte;
window.cancelarRecorte = cancelarRecorte;
window.descartarRecorte = descartarRecorte;
window.salvarRecorte = salvarRecorte;
window.adicionarNotaRevisao = adicionarNotaRevisao;
window.editarBlocoRevisao = editarBlocoRevisao;
window.moverBlocoRevisao = moverBlocoRevisao;
window.excluirBlocoRevisao = excluirBlocoRevisao;
window.blocoParaFlashcard = blocoParaFlashcard;
window.exportRevisaoMd = exportRevisaoMd;
window.imprimirRevisao = imprimirRevisao;
window.abrirRevisaoTelaCheia = abrirRevisaoTelaCheia;
window.fecharRevisaoTelaCheia = fecharRevisaoTelaCheia;
window.revFsZoom = revFsZoom;
window.toggleRevFsRecall = toggleRevFsRecall;
window.revelarBlocoRecall = revelarBlocoRecall;
window.abrirOclusaoEditor = abrirOclusaoEditor;
window.ocluirLimpar = ocluirLimpar;
window.ocluirSalvar = ocluirSalvar;
window.ocluirFechar = ocluirFechar;
window.abrirAgendaRevisao = abrirAgendaRevisao;
window.fecharAgendaRevisao = fecharAgendaRevisao;
window.agendarCaderno = agendarCaderno;
window.marcarCadernoRevisado = marcarCadernoRevisado;
window.cancelarAgendaCaderno = cancelarAgendaCaderno;
window.abrirGerarRevisaoIA = abrirGerarRevisaoIA;
window.fecharGerarRevisaoIA = fecharGerarRevisaoIA;
window.gerarRevisaoIA = gerarRevisaoIA;
window.setBlocoTag = setBlocoTag;
window.setRevFsTagFiltro = setRevFsTagFiltro;
window.capturarSelecaoTexto = capturarSelecaoTexto;
window.filtrarRevisao = filtrarRevisao;
window.setRevFsBusca = setRevFsBusca;
