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

  const pdfUrl = encodeURIComponent(`${location.origin}/pdf/${encodePath(path)}`);
  const frame = document.getElementById('pdf-frame');
  frame.src = `/pdfjs/web/viewer.html?file=${pdfUrl}#page=${currentPage}`;

  frame.addEventListener('load', () => {
    let tries = 0;
    const wait = setInterval(() => {
      tries++;
      if (readPageFromViewer() || tries > 40) clearInterval(wait);
    }, 250);
  });

  setInterval(() => readPageFromViewer(), 400);
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
  currentPage = p;
  updateInfo();
  scheduleSave();

  // Detectar se chegou na última página (PDF concluído)
  if (currentPage >= totalPages && totalPages > 1 && !window._pdfFinishShown) {
    window._pdfFinishShown = true;
    setTimeout(() => ofereceQuestoesPdf(), 1500);
  }
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
    startTimer(Math.round(state.limitSeconds / 60), state.elapsed || 0);
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
  const label = await promptModal('Label para o bookmark (opcional):', { title: 'Novo Bookmark' }) || '';
  const cores = ['blue', 'green', 'yellow', 'red', 'purple'];
  const cor = cores[Math.floor(Math.random() * cores.length)];
  await fetch('/api/bookmarks', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ pdf_path: path, pagina: currentPage, label, cor })
  });
  showStudyToast(`🔖 Página ${currentPage} marcada!`);
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
function togglePomodoroMode() {
  pomodoroActive = !pomodoroActive;
  const btn = document.getElementById('btn-pomodoro');
  if (pomodoroActive) {
    btn.style.background = '#f38ba8';
    btn.style.color = '#1e1e2e';
    btn.textContent = '🍅 ON';
    // Start 25 min timer
    startTimer(25, 0);
    showStudyToast('🍅 Pomodoro ativado! 25 min de foco.');
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
    // After 25 min work, suggest 5 min break
    setTimeout(async () => {
      if (await confirmModal('Pomodoro', '🍅 Pomodoro completo! Fazer pausa de 5 min?', { type: 'success', confirmText: 'Pausar', cancelText: 'Continuar' })) {
        startTimer(5, 0);
        showStudyToast('☕ Pausa de 5 min. Relaxe!');
      } else {
        // Continue with next pomodoro
        startTimer(25, 0);
        pomodoroCount++;
        showStudyToast(`🍅 Pomodoro ${pomodoroCount} iniciado!`);
      }
    }, 500);
  }
};

// --- Study Summary ---
let summaryVisible = false;
function toggleStudySummary() {
  summaryVisible = !summaryVisible;
  const panel = document.getElementById('summary-panel');
  panel.style.display = summaryVisible ? 'flex' : 'none';
  if (summaryVisible) loadStudySummary();
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

// === Window assignments for HTML onclick/onchange handlers ===
window.toggleNotePanel = toggleNotePanel;
window.addBookmark = addBookmark;
window.quickFlashcard = quickFlashcard;
window.togglePomodoroMode = togglePomodoroMode;
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
window.selectSideAlt = selectSideAlt;
window.loadSidePanelQuestions = loadSidePanelQuestions;
window.goToPage = goToPage;
