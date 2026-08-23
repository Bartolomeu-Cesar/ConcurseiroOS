// ==================== TAB 4: FLASHCARDS ====================
import { escapeHtml, toast, showLoading, showEmpty, api, undoableDelete } from './utils.js';
import { switchTab } from './tabs.js';

let flashcardsToday = [], currentFlashIndex = 0;
let flashSessao = [], flashSessaoIndex = 0, flashSessaoMode = '';
let _loadMetas = null, _loadStreakBadge = null, _getConfigSessoes = null;
let _flashReviewedToday = 0; // Total revisados hoje (persiste na sessão)
let _flashOriginalTotal = 0; // Total original (pendentes + já revisados)
let _flashSessionStart = null; // Timestamp início da sessão de revisão
let _flashCardStart = null; // Timestamp início do card atual
let _flashSessionSeconds = 0; // Segundos acumulados na sessão

/**
 * Inicia o timer global automaticamente se não estiver ativo.
 * Usa um Pomodoro de 25 min para a matéria indicada.
 */
function _autoStartTimerIfNeeded(materia) {
  try {
    const timerState = localStorage.getItem('pomo_timer');
    if (timerState) return; // Timer já está rodando
    if (typeof window.startGlobalTimer === 'function') {
      window.startGlobalTimer(materia, 25, 'flashcard');
    } else if (typeof startGlobalTimer === 'function') {
      startGlobalTimer(materia, 25, 'flashcard');
    }
  } catch(e) {}
}

export async function loadFlashcardsToday() {
  try {
    flashcardsToday = await fetch('/api/flashcards/today').then(r => r.json());
    currentFlashIndex = 0;

    // Buscar quantos já foram revisados hoje do streak
    try {
      const streak = await fetch('/api/streaks').then(r => r.json());
      _flashReviewedToday = (streak && streak.hoje && streak.hoje.flashcards_revisados) ? streak.hoje.flashcards_revisados : 0;
    } catch(e) {
      _flashReviewedToday = parseInt(sessionStorage.getItem('flash_reviewed_today') || '0');
    }
    _flashOriginalTotal = flashcardsToday.length + _flashReviewedToday;

    showCurrentFlashcard();
  } catch (e) { toast('Erro ao carregar flashcards de hoje', 'error'); }
}

function showCurrentFlashcard() {
  const q = document.getElementById('flash-question'), a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn'), rv = document.getElementById('flash-review-btns');
  const progressEl = document.getElementById('flash-progress');
  const pendentes = flashcardsToday.length;
  const totalOriginal = _flashOriginalTotal || pendentes;
  const done = _flashReviewedToday + currentFlashIndex;
  const total = totalOriginal || 1;

  if (progressEl && totalOriginal > 0) {
    progressEl.style.display = 'block';
    const pct = Math.min(100, Math.round((done / total) * 100));
    document.getElementById('flash-progress-text').textContent = `${done}/${total} revisados`;
    document.getElementById('flash-progress-pct').textContent = `${pct}%`;
    document.getElementById('flash-progress-bar').style.width = `${pct}%`;
    const bar = document.getElementById('flash-progress-bar');
    bar.style.background = pct >= 100 ? '#a6e3a1' : pct >= 50 ? '#f9e2af' : '#89b4fa';
    // Garantir largura mínima visível quando progresso > 0
    if (done > 0 && pct < 5) bar.style.width = '5%';
  } else if (progressEl) { progressEl.style.display = 'none'; }
  if (currentFlashIndex >= pendentes) {
    const doneAll = _flashReviewedToday + currentFlashIndex;
    q.innerHTML = `<span style="color:#a6e3a1;font-size:1.3rem;font-weight:600;">🎉 Parabéns! ${doneAll} flashcards revisados hoje!</span>`;
    a.style.display = 'none'; rb.style.display = 'none'; rv.style.display = 'none';
    if (progressEl) {
      document.getElementById('flash-progress-text').textContent = `${doneAll}/${total} revisados ✓`;
      document.getElementById('flash-progress-pct').textContent = '100%';
      document.getElementById('flash-progress-bar').style.width = '100%';
      document.getElementById('flash-progress-bar').style.background = '#a6e3a1';
    }
    return;
  }
  const card = flashcardsToday[currentFlashIndex];
  const badge = card.materia ? `<span style="font-size:0.7rem;background:#45475a;color:#cba6f7;padding:2px 8px;border-radius:4px;margin-bottom:4px;display:inline-block;">📚 ${card.materia}</span><br>` : '';
  q.innerHTML = badge + escapeHtml(card.pergunta);
  a.textContent = card.resposta;
  a.style.display = 'none';
  rb.style.display = 'inline-block';
  rv.style.display = 'none';
  // Track time per card
  _flashCardStart = Date.now();
  if (!_flashSessionStart) _flashSessionStart = Date.now();
}

export function revealAnswer() {
  document.getElementById('flash-answer').style.display = 'block';
  document.getElementById('flash-reveal-btn').style.display = 'none';

  // Auto-start global timer if not already running
  _autoStartTimerIfNeeded('Flashcards (Revisão)');

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

export async function reviewFlashcard(quality) {
  const card = flashcardsToday[currentFlashIndex];
  if (!card) return;
  try {
    // Acumular tempo gasto neste card
    if (_flashCardStart) {
      const elapsed = Math.round((Date.now() - _flashCardStart) / 1000);
      // Cap em 5 min por card (evita tempo inflado se usuário saiu)
      _flashSessionSeconds += Math.min(elapsed, 300);
      _flashCardStart = null;
    }

    const data = await api(`/api/flashcards/${card.id}/review-sm2`, { method: 'POST', body: { quality } });
    const msgs = ['Esqueceu — recomeçar','Quase — recomeçar','Errou — recomeçar','Difícil — +1d','Bom — +' + data.intervalo_dias + 'd','Fácil — +' + data.intervalo_dias + 'd'];
    toast(`${msgs[quality]} (EF: ${data.easiness_factor.toFixed(2)})`, quality >= 3 ? 'success' : 'warning', 3000);
    currentFlashIndex++;
    showCurrentFlashcard();
    loadAllFlashcards();
    if (_loadStreakBadge) _loadStreakBadge();
    if (_loadMetas) _loadMetas();

    // Registrar sessão de estudo a cada 5 cards ou ao terminar
    const isFinished = currentFlashIndex >= flashcardsToday.length;
    if ((currentFlashIndex % 5 === 0 || isFinished) && _flashSessionSeconds > 30) {
      const horas = Math.round(_flashSessionSeconds / 3600 * 100) / 100;
      fetch('/api/sessoes-estudo/registrar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ horas: horas, materia: 'Flashcards (Revisão)', tipo: 'flashcard' })
      }).catch(() => {});
      _flashSessionSeconds = 0; // Reset para próximo bloco
    }
  } catch (e) { toast('Erro ao revisar', 'error'); }
}

export async function addFlashcard() {
  const p = document.getElementById('flash-pergunta').value.trim(), r = document.getElementById('flash-resposta').value.trim();
  if (!p || !r) { toast('Preencha pergunta e resposta.', 'warning'); return; }
  const materia = document.getElementById('flash-add-materia')?.value || '';
  await fetch('/api/flashcards', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pergunta: p, resposta: r, materia }) });
  document.getElementById('flash-pergunta').value = '';
  document.getElementById('flash-resposta').value = '';
  toast('Flashcard criado!', 'success');
  loadFlashcardsToday();
  loadAllFlashcards();
}

export async function loadAllFlashcards() {
  showLoading('flash-list');
  try {
    const matFilter = document.getElementById('flash-materia-filter')?.value || '';
    const url = matFilter ? `/api/flashcards?materia=${encodeURIComponent(matFilter)}` : '/api/flashcards';
    const all = await fetch(url).then(r => r.json());
    document.getElementById('flash-count').textContent = `Total: ${all.length} flashcard(s)${matFilter ? ' em ' + matFilter : ''}`;
    if (all.length === 0) {
      showEmpty('flash-list', '🧠', 'Nenhum flashcard criado. Crie perguntas e respostas para revisar com repetição espaçada!');
    } else {
      const grouped = {};
      all.forEach(c => { const mat = c.materia || 'Sem matéria'; if (!grouped[mat]) grouped[mat] = []; grouped[mat].push(c); });
      let html = '';
      if (!matFilter && Object.keys(grouped).length > 1) {
        for (const [mat, cards] of Object.entries(grouped).sort((a,b) => b[1].length - a[1].length)) {
          const matId = 'flash-group-' + mat.replace(/[^a-zA-Z0-9]/g, '_');
          html += `<div style="margin-top:8px;">
            <div onclick="toggleFlashGroup('${matId}')" style="font-size:0.8rem;font-weight:600;color:#cba6f7;padding:6px 10px;background:#45475a;border-radius:6px;margin-bottom:2px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;user-select:none;">
              <span><span class="flash-chevron" id="chev-${matId}">▶</span> 📚 ${mat} (${cards.length})</span>
            </div>
            <div id="${matId}" style="display:none;">`;
          html += cards.map(c => `<div class="flash-list-item"><span style="flex:1;color:#cdd6f4;">${escapeHtml(c.pergunta)}</span><button class="flash-list-edit" onclick="openFlashEditModal(${c.id})" title="Editar">✏️</button><button class="flash-list-delete" onclick="deleteFlashcard(${c.id})">🗑</button></div>`).join('');
          html += '</div></div>';
        }
      } else {
        html = all.map(c => `<div class="flash-list-item"><span style="flex:1;color:#cdd6f4;">${escapeHtml(c.pergunta)}</span><button class="flash-list-edit" onclick="openFlashEditModal(${c.id})" title="Editar">✏️</button><button class="flash-list-delete" onclick="deleteFlashcard(${c.id})">🗑</button></div>`).join('');
      }
      document.getElementById('flash-list').innerHTML = html;
    }
    loadFlashMaterias();
  } catch (e) { toast('Erro ao carregar flashcards', 'error'); }
}

export function toggleFlashGroup(id) {
  const el = document.getElementById(id);
  const chev = document.getElementById('chev-' + id);
  if (!el) return;
  if (el.style.display === 'none') { el.style.display = 'block'; if (chev) chev.textContent = '▼'; }
  else { el.style.display = 'none'; if (chev) chev.textContent = '▶'; }
}

async function loadFlashMaterias() {
  try {
    const mats = await fetch('/api/flashcards/materias').then(r => r.json());
    const sel = document.getElementById('flash-materia-filter');
    const current = sel.value;
    sel.innerHTML = '<option value="">Todas as Disciplinas</option>' +
      mats.map(m => `<option value="${m.materia}" ${m.materia === current ? 'selected' : ''}>${m.materia} (${m.total})</option>`).join('');
  } catch(e) {}
}

export async function iniciarSessaoFlash(mode) {
  flashSessaoMode = mode;
  const cfg = _getConfigSessoes();
  if (mode === 'revisao') { loadFlashcardsToday(); toast('📅 Modo Revisão SRS ativado!', 'success'); return; }
  if (mode === 'disciplina') {
    const mats = await fetch('/api/flashcards/materias').then(r => r.json());
    if (mats.length === 0) { toast('Nenhum flashcard disponível', 'warning'); return; }
    const opts = mats.map(m => m.materia).filter(m => m);
    const escolha = await promptSelect('📚 Escolha a disciplina:', opts);
    if (!escolha) return;
    flashSessao = await fetch(`/api/flashcards/aleatorio?materia=${encodeURIComponent(escolha)}&quantidade=${cfg.flashcards_sessao}`).then(r => r.json());
    if (flashSessao.length === 0) { toast('Nenhum flashcard nessa disciplina', 'warning'); return; }
    flashSessaoIndex = 0;
    showSessaoFlashcard();
    toast(`📚 Sessão: ${escolha} (${flashSessao.length} cards)`, 'success');
    return;
  }
  if (mode === 'aleatorio') {
    flashSessao = await fetch(`/api/flashcards/aleatorio?quantidade=${cfg.flashcards_sessao}`).then(r => r.json());
    if (flashSessao.length === 0) { toast('Nenhum flashcard disponível', 'warning'); return; }
    flashSessaoIndex = 0;
    showSessaoFlashcard();
    toast(`🎲 Sessão Aleatória (${flashSessao.length} cards)`, 'success');
    return;
  }
}

function showSessaoFlashcard() {
  const q = document.getElementById('flash-question'), a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn'), rv = document.getElementById('flash-review-btns');
  if (flashSessaoIndex >= flashSessao.length) {
    q.innerHTML = '<span style="color:#a6e3a1;font-size:1.3rem;font-weight:600;">🎉 Sessão concluída! Parabéns!</span>';
    a.style.display = 'none'; rb.style.display = 'none'; rv.style.display = 'none';
    flashSessao = []; flashSessaoMode = '';
    return;
  }
  const card = flashSessao[flashSessaoIndex];
  const badge = card.materia ? `<span style="font-size:0.7rem;background:#45475a;color:#cba6f7;padding:2px 8px;border-radius:4px;margin-bottom:6px;display:inline-block;">📚 ${card.materia}</span><br>` : '';
  q.innerHTML = badge + `<span>${flashSessaoIndex + 1}/${flashSessao.length}</span> — ${escapeHtml(card.pergunta)}`;
  a.textContent = card.resposta;
  a.style.display = 'none';
  rb.style.display = 'inline-block';
  rv.style.display = 'none';
  rb.onclick = function() {
    a.style.display = 'block'; rb.style.display = 'none';
    rv.style.display = 'flex';
    rv.innerHTML = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;width:100%;">
      <button onclick="sessaoNext(0)" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">0•Esqueci</button>
      <button onclick="sessaoNext(1)" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">1•Errei</button>
      <button onclick="sessaoNext(2)" style="background:#fab387;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">2•Quase</button>
      <button onclick="sessaoNext(3)" style="background:#f9e2af;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">3•Difícil</button>
      <button onclick="sessaoNext(4)" style="background:#a6e3a1;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">4•Bom</button>
      <button onclick="sessaoNext(5)" style="background:#a6e3a1;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">5•Fácil</button>
    </div>`;
  };
}

export async function sessaoNext(quality) {
  const card = flashSessao[flashSessaoIndex];
  if (card && card.id) {
    try { await api(`/api/flashcards/${card.id}/review-sm2`, { method: 'POST', body: { quality } }); } catch(e) {}
  }
  flashSessaoIndex++;
  showSessaoFlashcard();
  if (_loadMetas) _loadMetas();
  if (_loadStreakBadge) _loadStreakBadge();
}

function promptSelect(title, options) {
  return new Promise((resolve) => {
    const modal = document.getElementById('select-modal');
    document.getElementById('select-modal-title').textContent = title;
    const list = document.getElementById('select-modal-list');
    const search = document.getElementById('select-modal-search');
    search.value = '';
    function render(filter) {
      const filtered = filter ? options.filter(o => o.toLowerCase().includes(filter.toLowerCase())) : options;
      list.innerHTML = filtered.map(o => `<div class="select-item" onclick="this.dispatchEvent(new CustomEvent('pick',{bubbles:true,detail:'${o.replace(/'/g, "\\'")}'}))">${o}</div>`).join('');
    }
    render('');
    search.oninput = () => render(search.value);
    list.onclick = (e) => { if (e.target.classList.contains('select-item')) { modal.style.display = 'none'; resolve(e.target.textContent); } };
    modal.querySelector('.iobtn').onclick = () => { modal.style.display = 'none'; resolve(null); };
    modal.style.display = 'flex';
  });
}

export async function deleteFlashcard(id) {
  undoableDelete('Flashcard', `/api/flashcards/${id}`, (deleted) => {
    if (deleted) { loadAllFlashcards(); loadFlashcardsToday(); }
  });
}

// Evento para receber sessão pós-estudo do módulo edital
export function startSessionFromEvent(sessaoData, materia) {
  flashSessao = sessaoData;
  flashSessaoIndex = 0;
  switchTab('tab-flashcards');
  showSessaoFlashcard();
  toast(`🧠 Sessão: ${materia} (${flashSessao.length} cards)`, 'success');
}

export async function openFlashEditModal(id) {
  const modal = document.getElementById('flash-edit-modal');
  const sel = document.getElementById('flash-edit-materia');
  // Carregar disciplinas do edital
  try {
    const materias = await fetch('/api/edital/materias-disponiveis').then(r => r.json());
    sel.innerHTML = '<option value="">Sem disciplina</option>' +
      materias.map(m => `<option value="${m}">${m}</option>`).join('');
  } catch(e) { /* manter opção padrão */ }
  // Carregar dados do flashcard
  try {
    const all = await fetch('/api/flashcards').then(r => r.json());
    const card = all.find(c => c.id === id);
    if (!card) { toast('Flashcard não encontrado', 'error'); return; }
    document.getElementById('flash-edit-id').value = id;
    document.getElementById('flash-edit-pergunta').value = card.pergunta;
    document.getElementById('flash-edit-resposta').value = card.resposta;
    sel.value = card.materia || '';
  } catch(e) { toast('Erro ao carregar flashcard', 'error'); return; }
  modal.style.display = 'flex';
}

export function closeFlashEditModal() {
  document.getElementById('flash-edit-modal').style.display = 'none';
}

export async function saveFlashEdit() {
  const id = document.getElementById('flash-edit-id').value;
  const pergunta = document.getElementById('flash-edit-pergunta').value.trim();
  const resposta = document.getElementById('flash-edit-resposta').value.trim();
  const materia = document.getElementById('flash-edit-materia').value;
  if (!pergunta || !resposta) { toast('Pergunta e resposta são obrigatórios', 'warning'); return; }
  try {
    await api(`/api/flashcards/${id}`, {
      method: 'PUT',
      body: { pergunta, resposta, materia }
    });
    toast('Flashcard atualizado!', 'success');
    closeFlashEditModal();
    loadAllFlashcards();
    loadFlashcardsToday();
  } catch(e) { toast('Erro ao salvar edição', 'error'); }
}

export function initFlashcards(deps) {
  _loadMetas = deps.loadMetas;
  _loadStreakBadge = deps.loadStreakBadge;
  _getConfigSessoes = deps.getConfigSessoes;

  // Ouvir evento de sessão pós-estudo
  window.addEventListener('iniciar-flash-pos-estudo', (e) => {
    startSessionFromEvent(e.detail.flashSessao, e.detail.materia);
  });

  // Carregar disciplinas para o select de criação
  loadAddMaterias();

  loadFlashcardsToday();
  loadAllFlashcards();
}

async function loadAddMaterias() {
  try {
    const materias = await fetch('/api/edital/materias-disponiveis').then(r => r.json());
    const sel = document.getElementById('flash-add-materia');
    if (sel) {
      sel.innerHTML = '<option value="">📚 Disciplina (opcional)</option>' +
        materias.map(m => `<option value="${m}">${m}</option>`).join('');
    }
  } catch(e) { /* silencioso */ }
}
