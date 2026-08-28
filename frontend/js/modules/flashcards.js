// ==================== TAB 4: FLASHCARDS ====================
import { escapeHtml, toast, showLoading, showEmpty, api, undoableDelete } from './utils.js';
import { switchTab } from './tabs.js';
import { showFlashcardXp } from './xp-notify.js';
import { emit } from './event-bus.js';

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

// Metacognition state
let _currentConfidence = 0;
let _metacogHistory = []; // {cardId, confidence, quality, gap}
let _generationMode = localStorage.getItem('flash_generation_mode') === 'true';

// Toggle generation mode
export function toggleGenerationMode() {
  _generationMode = !_generationMode;
  localStorage.setItem('flash_generation_mode', _generationMode);
  showCurrentFlashcard();
}

// Set confidence level (metacognition)
export function setFlashConfidence(level) {
  _currentConfidence = level;
  // Visual feedback: highlight selected button
  document.querySelectorAll('#flash-confidence-btns .conf-btn').forEach(btn => {
    const btnLevel = parseInt(btn.dataset.level);
    if (btnLevel === level) {
      btn.style.borderColor = 'var(--accent)';
      btn.style.background = 'var(--bg-elevated)';
      btn.style.transform = 'scale(1.1)';
    } else {
      btn.style.borderColor = 'var(--border)';
      btn.style.background = 'var(--bg)';
      btn.style.transform = 'scale(1)';
    }
  });
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
  rv.style.display = 'none';

  // Add metacognition confidence slider + generation mode BEFORE reveal button
  const genModeToggle = `<div style="display:flex;justify-content:flex-end;margin-bottom:6px;">
    <label style="font-size:0.68rem;color:var(--text-sub);cursor:pointer;display:flex;align-items:center;gap:4px;">
      <input type="checkbox" ${_generationMode ? 'checked' : ''} onchange="toggleGenerationMode()" style="width:14px;height:14px;"> ✍️ Escrever resposta
    </label>
  </div>`;

  // Generation Effect: text input to type answer
  let generationHtml = '';
  if (_generationMode) {
    generationHtml = `<div id="flash-generation-area" style="margin-bottom:10px;">
      <textarea id="flash-generation-input" placeholder="Digite sua resposta antes de revelar..." 
        style="width:100%;min-height:60px;background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:0.85rem;font-family:inherit;resize:vertical;"
        onkeydown="if(event.key==='Enter'&&event.ctrlKey)revealAnswer()"></textarea>
      <div style="font-size:0.65rem;color:var(--text-sub);margin-top:2px;">Ctrl+Enter para revelar</div>
    </div>`;
  }

  // Metacognition: confidence slider
  const confidenceHtml = `<div id="flash-confidence-area" style="margin-bottom:10px;text-align:center;">
    <div style="font-size:0.75rem;color:var(--text-sub);margin-bottom:6px;">🧠 Quão confiante você está na resposta?</div>
    <div style="display:flex;justify-content:center;gap:6px;" id="flash-confidence-btns">
      <button onclick="setFlashConfidence(1)" class="conf-btn" data-level="1" style="padding:6px 10px;border-radius:6px;border:2px solid var(--border);background:var(--bg);color:var(--red);font-size:0.8rem;font-weight:600;cursor:pointer;">1<br><span style="font-size:0.6rem;">Nenhuma</span></button>
      <button onclick="setFlashConfidence(2)" class="conf-btn" data-level="2" style="padding:6px 10px;border-radius:6px;border:2px solid var(--border);background:var(--bg);color:var(--peach);font-size:0.8rem;font-weight:600;cursor:pointer;">2<br><span style="font-size:0.6rem;">Pouca</span></button>
      <button onclick="setFlashConfidence(3)" class="conf-btn" data-level="3" style="padding:6px 10px;border-radius:6px;border:2px solid var(--border);background:var(--bg);color:var(--yellow);font-size:0.8rem;font-weight:600;cursor:pointer;">3<br><span style="font-size:0.6rem;">Média</span></button>
      <button onclick="setFlashConfidence(4)" class="conf-btn" data-level="4" style="padding:6px 10px;border-radius:6px;border:2px solid var(--border);background:var(--bg);color:var(--blue);font-size:0.8rem;font-weight:600;cursor:pointer;">4<br><span style="font-size:0.6rem;">Alta</span></button>
      <button onclick="setFlashConfidence(5)" class="conf-btn" data-level="5" style="padding:6px 10px;border-radius:6px;border:2px solid var(--border);background:var(--bg);color:var(--green);font-size:0.8rem;font-weight:600;cursor:pointer;">5<br><span style="font-size:0.6rem;">Total</span></button>
    </div>
  </div>`;

  // Insert between question and reveal button
  const revealContainer = document.getElementById('flash-reveal-btn').parentElement;
  // Remove old confidence/generation areas
  document.getElementById('flash-confidence-area')?.remove();
  document.getElementById('flash-generation-area')?.remove();
  document.getElementById('flash-genmode-toggle')?.remove();
  
  // Insert new areas
  const insertDiv = document.createElement('div');
  insertDiv.id = 'flash-genmode-toggle';
  insertDiv.innerHTML = genModeToggle + generationHtml + confidenceHtml;
  rb.parentElement.insertBefore(insertDiv, rb);

  rb.style.display = 'inline-block';
  // Track time per card
  _flashCardStart = Date.now();
  if (!_flashSessionStart) _flashSessionStart = Date.now();
}

export function revealAnswer() {
  // Record confidence level (metacognition)
  const confidence = _currentConfidence;
  _currentConfidence = 0; // Reset

  document.getElementById('flash-answer').style.display = 'block';
  document.getElementById('flash-reveal-btn').style.display = 'none';
  document.getElementById('flash-confidence-area')?.remove();
  document.getElementById('flash-generation-area')?.remove();

  // Auto-start global timer if not already running
  _autoStartTimerIfNeeded('Flashcards (Revisão)');

  // Show metacognition feedback if confidence was recorded
  const card = flashcardsToday[currentFlashIndex];
  let metacogHtml = '';
  if (confidence > 0 && card) {
    _metacogHistory.push({ cardId: card.id, confidence, timestamp: Date.now() });
    metacogHtml = `<div id="flash-metacog-feedback" style="font-size:0.72rem;color:var(--text-sub);margin-bottom:6px;text-align:center;">
      Confiança: ${'⭐'.repeat(confidence)}${'☆'.repeat(5 - confidence)} — Avalie abaixo se acertou
    </div>`;
  }

  const rv = document.getElementById('flash-review-btns');
  rv.style.display = 'flex';
  rv.innerHTML = metacogHtml + `
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;width:100%;">
      <button onclick="reviewFlashcard(0)" style="background:var(--red);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">0•Esqueci</button>
      <button onclick="reviewFlashcard(1)" style="background:var(--red);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">1•Errei</button>
      <button onclick="reviewFlashcard(2)" style="background:var(--peach);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">2•Quase</button>
      <button onclick="reviewFlashcard(3)" style="background:var(--yellow);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">3•Difícil</button>
      <button onclick="reviewFlashcard(4)" style="background:var(--green);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">4•Bom</button>
      <button onclick="reviewFlashcard(5)" style="background:var(--green);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">5•Fácil</button>
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

    // Metacognition: track confidence vs actual result gap
    const lastMetacog = _metacogHistory.find(m => m.cardId === card.id && !m.quality);
    if (lastMetacog) {
      lastMetacog.quality = quality;
      // Gap: confidence alta + quality baixo = overconfidence
      // Gap: confidence baixa + quality alto = underconfidence
      const expectedQuality = lastMetacog.confidence; // 1-5 maps roughly to 0-5 quality
      lastMetacog.gap = quality - expectedQuality;
      lastMetacog.calibrated = Math.abs(lastMetacog.gap) <= 1;
      // Save metacog history to localStorage
      try {
        const stored = JSON.parse(localStorage.getItem('metacog_history') || '[]');
        stored.push(lastMetacog);
        localStorage.setItem('metacog_history', JSON.stringify(stored.slice(-100)));
      } catch(e) {}
    }

    const data = await api(`/api/flashcards/${card.id}/review-fsrs`, { method: 'POST', body: { quality } });
    const intervalLabel = data.intervalo_dias >= 30 ? `${Math.round(data.intervalo_dias / 30)}m` : `${data.intervalo_dias}d`;
    const stateNames = ['Novo', 'Aprendendo', 'Revisão', 'Reaprendendo'];
    const stateLabel = stateNames[data.fsrs_state] || '';
    const msgs = [
      'Esqueceu — amanhã',
      'Errou — amanhã',
      'Quase — amanhã',
      `Difícil — +${intervalLabel}`,
      `Bom — +${intervalLabel}`,
      `Fácil — +${intervalLabel}`,
    ];

    // Metacognition feedback toast
    let metacogMsg = '';
    if (lastMetacog && lastMetacog.confidence > 0) {
      if (lastMetacog.confidence >= 4 && quality <= 2) metacogMsg = ' ⚠️ Overconfidence!';
      else if (lastMetacog.confidence <= 2 && quality >= 4) metacogMsg = ' 💡 Você sabia mais do que pensava!';
      else if (lastMetacog.calibrated) metacogMsg = ' ✅ Boa calibração!';
    }

    toast(`${msgs[quality]} [${stateLabel}]${metacogMsg}`, quality >= 3 ? 'success' : 'warning', 3000);

    // XP real-time feedback
    showFlashcardXp(quality);

    // Emitir evento para integração cross-module
    emit('flashcard:revisado', { materia: card.materia, quality, acertou: quality >= 3 });

    // Feed adaptive pomodoro fatigue detection
    if (window._adaptivePomo) {
      const tempoCard = _flashCardStart ? Math.round((Date.now() - _flashCardStart) / 1000) : 0;
      window._adaptivePomo.recordAnswer(quality >= 3, tempoCard);
    }

    // Elaborative Interrogation: prompt "Por quê?" após acerto (quality >= 3)
    // Mostrar a cada 3 cards acertados para não sobrecarregar (não em todo card)
    _elaborationAccertCount = (_elaborationAccertCount || 0) + (quality >= 3 ? 1 : 0);
    const shouldElaborate = quality >= 3 && _elaborationAccertCount % 3 === 0 && card.pergunta;
    if (shouldElaborate) {
      _showElaborationPrompt(card);
      return; // Pausa — o fluxo continua ao pular/salvar a elaboração
    }

    _advanceAfterReview();
  } catch (e) { toast('Erro ao revisar', 'error'); }
}

let _elaborationAccertCount = 0;

function _advanceAfterReview() {
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
}

function _showElaborationPrompt(card) {
  const q = document.getElementById('flash-question');
  const a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn');
  const rv = document.getElementById('flash-review-btns');

  // Esconder botões de review
  rv.style.display = 'none';
  rb.style.display = 'none';
  a.style.display = 'none';

  // Gerar prompt contextual
  const prompts = [
    `Por que "${card.resposta}" é a resposta correta?`,
    `Explique COM SUAS PALAVRAS por que isso é verdade.`,
    `Qual é a lógica/fundamento por trás dessa resposta?`,
  ];
  const prompt = prompts[Math.floor(Math.random() * prompts.length)];

  q.innerHTML = `
    <div style="text-align:center;margin-bottom:8px;">
      <span style="font-size:1.3rem;">🤔</span>
      <div style="font-size:0.85rem;font-weight:700;color:var(--accent);margin:4px 0;">Elaborative Interrogation</div>
      <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:8px;">Explicar fortalece a memória em 10-40% (Dunlosky, 2013)</div>
    </div>
    <div style="background:var(--bg-surface);border-radius:8px;padding:10px;margin-bottom:10px;">
      <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:4px;">📚 ${card.materia || 'Flashcard'}</div>
      <div style="font-size:0.85rem;font-weight:600;color:var(--text);">${prompt}</div>
    </div>
    <textarea id="elaboration-input" placeholder="Escreva sua explicação... (opcional mas recomendado)"
      style="width:100%;min-height:70px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:0.82rem;font-family:inherit;resize:vertical;"></textarea>
    <div style="display:flex;gap:8px;margin-top:8px;">
      <button onclick="saveElaboration()" style="flex:1;background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:8px;font-size:0.8rem;font-weight:600;cursor:pointer;">💾 Salvar</button>
      <button onclick="skipElaboration()" style="flex:1;background:var(--bg-surface);color:var(--text-sub);border:1px solid var(--border);border-radius:6px;padding:8px;font-size:0.8rem;cursor:pointer;">⏭ Pular</button>
    </div>
  `;
}

export function skipElaboration() {
  _advanceAfterReview();
}

export async function saveElaboration() {
  const input = document.getElementById('elaboration-input');
  const texto = input ? input.value.trim() : '';
  const card = flashcardsToday[currentFlashIndex];

  if (texto && card) {
    // Salvar no backend via endpoint existente
    fetch('/api/study-intelligence/elaboration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        flashcard_id: card.id,
        prompt_tipo: 'elaborative_interrogation',
        resposta_usuario: texto
      })
    }).catch(() => {});
    toast('💡 Elaboração salva! Memória reforçada.', 'success', 2000);
  }

  _advanceAfterReview();
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
          html += cards.map(c => `<div class="flash-list-item"><span style="flex:1;color:#cdd6f4;">${escapeHtml(c.pergunta)}</span><button class="flash-list-edit" onclick="openFlashEditModal(${c.id})" title="Editar" aria-label="Editar flashcard">✏️</button><button class="flash-list-delete" onclick="deleteFlashcard(${c.id})" aria-label="Excluir flashcard">🗑</button></div>`).join('');
          html += '</div></div>';
        }
      } else {
        html = all.map(c => `<div class="flash-list-item"><span style="flex:1;color:#cdd6f4;">${escapeHtml(c.pergunta)}</span><button class="flash-list-edit" onclick="openFlashEditModal(${c.id})" title="Editar" aria-label="Editar flashcard">✏️</button><button class="flash-list-delete" onclick="deleteFlashcard(${c.id})" aria-label="Excluir flashcard">🗑</button></div>`).join('');
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
    try { await api(`/api/flashcards/${card.id}/review-fsrs`, { method: 'POST', body: { quality } }); } catch(e) {}
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

// ============================================================
// ESTUDO POR ÁUDIO (TTS) — Web Speech API
// Modo "ouvir": pergunta → pausa → resposta
// ============================================================

let _ttsPlaying = false;
let _ttsQueue = [];
let _ttsIndex = 0;
let _ttsPaused = false;

export function startAudioMode() {
  if (!('speechSynthesis' in window)) {
    toast('Seu navegador não suporta Text-to-Speech.', 'error');
    return;
  }
  if (flashcardsToday.length === 0) {
    toast('Nenhum flashcard pendente para ouvir.', 'warning');
    return;
  }
  _ttsQueue = [...flashcardsToday];
  _ttsIndex = 0;
  _ttsPlaying = true;
  _ttsPaused = false;
  toast(`🔊 Modo Áudio: ${_ttsQueue.length} cards. Ouça a pergunta e tente lembrar a resposta.`, 'success', 4000);
  _ttsPlayCard();
}

export function stopAudioMode() {
  window.speechSynthesis.cancel();
  _ttsPlaying = false;
  _ttsPaused = false;
  _ttsQueue = [];
  toast('🔇 Modo áudio encerrado.', 'info');
}

export function pauseAudioMode() {
  if (_ttsPaused) {
    window.speechSynthesis.resume();
    _ttsPaused = false;
    toast('▶ Áudio retomado', 'info', 1500);
  } else {
    window.speechSynthesis.pause();
    _ttsPaused = true;
    toast('⏸ Áudio pausado', 'info', 1500);
  }
}

export function skipAudioCard() {
  window.speechSynthesis.cancel();
  _ttsIndex++;
  if (_ttsIndex < _ttsQueue.length) {
    _ttsPlayCard();
  } else {
    toast('🎉 Todos os cards ouvidos!', 'success');
    _ttsPlaying = false;
  }
}

function _ttsPlayCard() {
  if (_ttsIndex >= _ttsQueue.length || !_ttsPlaying) {
    _ttsPlaying = false;
    toast('🎉 Sessão de áudio concluída!', 'success');
    return;
  }
  const card = _ttsQueue[_ttsIndex];
  const synth = window.speechSynthesis;

  // Configurar voz pt-BR
  const voices = synth.getVoices();
  const ptVoice = voices.find(v => v.lang.startsWith('pt')) || voices[0];

  // 1. Falar "Pergunta:" + pergunta
  const uttPergunta = new SpeechSynthesisUtterance(`Pergunta. ${card.pergunta}`);
  uttPergunta.lang = 'pt-BR';
  uttPergunta.rate = 0.9;
  if (ptVoice) uttPergunta.voice = ptVoice;

  // 2. Pausa de 3 segundos para pensar
  // 3. Falar "Resposta:" + resposta
  const uttResposta = new SpeechSynthesisUtterance(`Resposta. ${card.resposta}`);
  uttResposta.lang = 'pt-BR';
  uttResposta.rate = 0.9;
  if (ptVoice) uttResposta.voice = ptVoice;

  uttPergunta.onend = () => {
    // Pausa de 3s antes da resposta
    setTimeout(() => {
      if (!_ttsPlaying) return;
      synth.speak(uttResposta);
    }, 3000);
  };

  uttResposta.onend = () => {
    // Pausa de 2s antes do próximo card
    setTimeout(() => {
      _ttsIndex++;
      if (_ttsPlaying) _ttsPlayCard();
    }, 2000);
  };

  // Mostrar visual do card atual
  const q = document.getElementById('flash-question');
  if (q) {
    const badge = card.materia ? `<span style="font-size:0.7rem;background:var(--bg-surface);color:var(--accent);padding:2px 8px;border-radius:4px;display:inline-block;margin-bottom:4px;">🔊 ${card.materia}</span><br>` : '';
    q.innerHTML = badge + `<div style="font-size:0.9rem;">${_ttsIndex + 1}/${_ttsQueue.length} — ${card.pergunta}</div>`;
  }

  synth.speak(uttPergunta);
}

// ============================================================
// MODO COMMUTING — Player áudio hands-free (pausas longas)
// Ideal para ônibus/carro: pergunta → 10s pensar → resposta
// Controle via MediaSession API (botões do fone bluetooth)
// ============================================================

let _commutingActive = false;

export function startCommutingMode() {
  if (!('speechSynthesis' in window)) {
    toast('Seu navegador não suporta Text-to-Speech.', 'error');
    return;
  }
  if (flashcardsToday.length === 0) {
    toast('Nenhum flashcard pendente. Adicione cards para usar o modo commuting.', 'warning');
    return;
  }
  _ttsQueue = [...flashcardsToday];
  _ttsIndex = 0;
  _ttsPlaying = true;
  _ttsPaused = false;
  _commutingActive = true;

  // Registrar MediaSession para controle por fone bluetooth
  if ('mediaSession' in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: 'ConcurseiroOS — Modo Commuting',
      artist: `${_ttsQueue.length} flashcards pendentes`,
      album: 'Revisão por Áudio',
    });
    navigator.mediaSession.setActionHandler('play', () => pauseAudioMode());
    navigator.mediaSession.setActionHandler('pause', () => pauseAudioMode());
    navigator.mediaSession.setActionHandler('nexttrack', () => skipAudioCard());
    navigator.mediaSession.setActionHandler('previoustrack', () => {}); // no-op
  }

  toast(`🎧 Modo Commuting: ${_ttsQueue.length} cards. Ouça → pense 10s → ouça resposta. Use fone para controlar.`, 'success', 5000);
  _commutingPlayCard();
}

export function stopCommutingMode() {
  window.speechSynthesis.cancel();
  _ttsPlaying = false;
  _commutingActive = false;
  if ('mediaSession' in navigator) {
    navigator.mediaSession.metadata = null;
  }
  toast('🎧 Modo commuting encerrado.', 'info');
}

function _commutingPlayCard() {
  if (_ttsIndex >= _ttsQueue.length || !_ttsPlaying) {
    _ttsPlaying = false;
    _commutingActive = false;
    toast('🎉 Revisão commuting concluída! Todos os cards ouvidos.', 'success');
    return;
  }
  const card = _ttsQueue[_ttsIndex];
  const synth = window.speechSynthesis;
  const voices = synth.getVoices();
  const ptVoice = voices.find(v => v.lang.startsWith('pt')) || voices[0];

  // Anunciar número do card
  const uttNum = new SpeechSynthesisUtterance(`Card ${_ttsIndex + 1} de ${_ttsQueue.length}. ${card.materia || ''}.`);
  uttNum.lang = 'pt-BR';
  uttNum.rate = 1.0;
  if (ptVoice) uttNum.voice = ptVoice;

  // Pergunta
  const uttPergunta = new SpeechSynthesisUtterance(card.pergunta);
  uttPergunta.lang = 'pt-BR';
  uttPergunta.rate = 0.85;  // Mais lento no commuting
  if (ptVoice) uttPergunta.voice = ptVoice;

  // Resposta
  const uttResposta = new SpeechSynthesisUtterance(`Resposta: ${card.resposta}`);
  uttResposta.lang = 'pt-BR';
  uttResposta.rate = 0.85;
  if (ptVoice) uttResposta.voice = ptVoice;

  // Fluxo: anúncio → pergunta → 10s pausa → "resposta:" → resposta → 3s → próximo
  uttNum.onend = () => {
    if (!_ttsPlaying) return;
    synth.speak(uttPergunta);
  };

  uttPergunta.onend = () => {
    if (!_ttsPlaying) return;
    // Pausa LONGA de 10s para pensar (commuting = sem visual)
    setTimeout(() => {
      if (!_ttsPlaying) return;
      // Beep sonoro antes da resposta (feedback auditivo)
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.frequency.value = 880; gain.gain.value = 0.2;
        osc.start(); osc.stop(ctx.currentTime + 0.15);
      } catch(e) {}
      setTimeout(() => { if (_ttsPlaying) synth.speak(uttResposta); }, 300);
    }, 10000);
  };

  uttResposta.onend = () => {
    // 3s entre cards
    setTimeout(() => {
      _ttsIndex++;
      if (_ttsPlaying && _commutingActive) _commutingPlayCard();
    }, 3000);
  };

  // Atualizar MediaSession
  if ('mediaSession' in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: card.pergunta.substring(0, 60),
      artist: card.materia || 'Flashcard',
      album: `${_ttsIndex + 1}/${_ttsQueue.length}`,
    });
  }

  synth.speak(uttNum);
}

// ============================================================
// ============================================================
// LEITNER SYSTEM — Visualização de Caixas 1-5
// ============================================================

export async function loadLeitnerBoxes() {
  const container = document.getElementById('leitner-boxes');
  if (!container) return;

  try {
    const all = await fetch('/api/flashcards').then(r => r.json());
    if (!all || all.length === 0) { container.style.display = 'none'; return; }

    // Mapear flashcards para caixas Leitner baseado no FSRS state + stability
    const boxes = [
      { num: 1, label: 'Novo/Aprendendo', color: '#f38ba8', interval: '1d', cards: [] },
      { num: 2, label: 'Curto prazo', color: '#fab387', interval: '3d', cards: [] },
      { num: 3, label: 'Médio prazo', color: '#f9e2af', interval: '7-30d', cards: [] },
      { num: 4, label: 'Longo prazo', color: '#a6e3a1', interval: '1-3m', cards: [] },
      { num: 5, label: 'Dominado', color: '#89b4fa', interval: '3m+', cards: [] },
    ];

    all.forEach(c => {
      const state = c.fsrs_state || 0;
      const stability = c.stability || 0;

      if (state <= 1 || stability < 3) {
        boxes[0].cards.push(c);
      } else if (stability < 7) {
        boxes[1].cards.push(c);
      } else if (stability < 30) {
        boxes[2].cards.push(c);
      } else if (stability < 90) {
        boxes[3].cards.push(c);
      } else {
        boxes[4].cards.push(c);
      }
    });

    container.style.display = 'block';
    const total = all.length;

    container.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <span style="font-size:0.88rem;font-weight:700;color:var(--text);">📦 Sistema Leitner</span>
        <span style="font-size:0.72rem;color:var(--text-sub);">${total} cards total</span>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;">
        ${boxes.map(b => {
          const pct = total > 0 ? Math.round(b.cards.length / total * 100) : 0;
          const height = Math.max(40, Math.min(100, 40 + pct * 0.6));
          return `
            <div style="flex:1;min-width:55px;text-align:center;">
              <div style="background:${b.color}22;border:2px solid ${b.color};border-radius:10px;height:${height}px;display:flex;flex-direction:column;align-items:center;justify-content:center;position:relative;transition:height 0.3s;">
                <span style="font-size:1.1rem;font-weight:800;color:${b.color};">${b.cards.length}</span>
                <span style="font-size:0.6rem;color:var(--text-sub);">${pct}%</span>
              </div>
              <div style="font-size:0.65rem;font-weight:600;color:${b.color};margin-top:4px;">Caixa ${b.num}</div>
              <div style="font-size:0.58rem;color:var(--text-sub);">${b.interval}</div>
            </div>`;
        }).join('')}
      </div>
      <div style="font-size:0.68rem;color:var(--text-sub);margin-top:8px;text-align:center;">
        Responda corretamente → sobe de caixa | Erre → volta para caixa 1
      </div>
    `;
  } catch(e) { container.style.display = 'none'; }
}

window.loadLeitnerBoxes = loadLeitnerBoxes;

// BOSS BATTLE MODE — Gamified Flashcard Review
// ============================================================

let _bossBattle = null;

export async function startBossBattle() {
  try {
    const data = await fetch('/api/study-intelligence/boss-battle').then(r => r.json());
    if (!data.boss || !data.cards.length) {
      toast(data.mensagem || 'Sem flashcards pendentes para batalha!', 'info');
      return;
    }
    _bossBattle = {
      boss: data.boss,
      cards: data.cards,
      dano_map: data.dano_map,
      index: 0,
      danoTotal: 0,
      stats: { easy: 0, good: 0, hard: 0, again: 0 },
    };
    _renderBossBattle();
    toast(`⚔️ ${data.boss.emoji} ${data.boss.nome} apareceu!`, 'warning', 3000);
  } catch(e) { toast('Erro ao iniciar Boss Battle', 'error'); }
}

function _renderBossBattle() {
  const b = _bossBattle;
  if (!b) return;
  const q = document.getElementById('flash-question'), a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn'), rv = document.getElementById('flash-review-btns');
  const progressEl = document.getElementById('flash-progress');

  // Boss HP bar
  const hpPct = Math.max(0, Math.round((b.boss.hp_atual - b.danoTotal) / b.boss.hp_total * 100));
  const hpColor = hpPct > 50 ? 'var(--red)' : hpPct > 25 ? 'var(--peach)' : 'var(--green)';

  if (progressEl) {
    progressEl.style.display = 'block';
    document.getElementById('flash-progress-text').textContent = `⚔️ ${b.boss.emoji} ${b.boss.nome} — HP: ${Math.max(0, b.boss.hp_total - b.danoTotal)}/${b.boss.hp_total}`;
    document.getElementById('flash-progress-pct').textContent = `${b.index}/${b.cards.length}`;
    document.getElementById('flash-progress-bar').style.width = `${100 - hpPct}%`;
    document.getElementById('flash-progress-bar').style.background = hpPct > 50 ? 'var(--blue)' : hpPct > 25 ? 'var(--peach)' : 'var(--green)';
  }

  // Boss derrotado?
  if (b.danoTotal >= b.boss.hp_total || b.index >= b.cards.length) {
    const derrotou = b.danoTotal >= b.boss.hp_total;
    q.innerHTML = derrotou
      ? `<div style="text-align:center;"><span style="font-size:2.5rem;">🏆</span><br><strong style="color:var(--green);font-size:1.2rem;">BOSS DERROTADO!</strong><br><span style="color:var(--text-sub);">${b.boss.emoji} ${b.boss.nome} foi eliminado!</span></div>`
      : `<div style="text-align:center;"><span style="font-size:2.5rem;">😤</span><br><strong style="color:var(--peach);font-size:1.1rem;">Boss sobreviveu!</strong><br><span style="color:var(--text-sub);">HP restante: ${b.boss.hp_total - b.danoTotal}. Volte amanhã!</span></div>`;
    a.style.display = 'none'; rb.style.display = 'none'; rv.style.display = 'none';
    // Registrar resultado
    fetch('/api/study-intelligence/boss-battle/resultado', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ boss_tier: b.boss.tier || 1, boss_hp_total: b.boss.hp_total, dano_total: b.danoTotal, cards_revisados: b.index, acertos_easy: b.stats.easy, acertos_good: b.stats.good, acertos_hard: b.stats.hard, erros_again: b.stats.again, derrotou })
    }).catch(() => {});
    _bossBattle = null;
    return;
  }

  // Mostrar card atual
  const card = b.cards[b.index];
  q.innerHTML = `<div style="text-align:center;margin-bottom:6px;font-size:0.72rem;color:var(--text-sub);">⚔️ Card ${b.index + 1}/${b.cards.length} | Dano total: ${b.danoTotal}</div>` +
    `<div style="font-size:0.95rem;color:var(--text);">${card.pergunta}</div>`;
  a.style.display = 'none';
  rb.style.display = 'inline-block';
  rv.style.display = 'none';

  // Override reveal para boss mode
  rb.onclick = function() {
    // Buscar resposta do card
    fetch(`/api/flashcards?page=1&limit=1`).catch(() => {});
    // Mostrar resposta (precisa buscar do servidor)
    fetch(`/api/flashcards`).then(r => r.json()).then(all => {
      const fullCard = (Array.isArray(all) ? all : all.items || []).find(c => c.id === card.id);
      a.textContent = fullCard ? fullCard.resposta : '(resposta)';
      a.style.display = 'block';
      rb.style.display = 'none';
      rv.style.display = 'flex';
      rv.innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;width:100%;">
          <button onclick="bossBattleReview(1)" style="background:var(--red);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.72rem;font-weight:600;cursor:pointer;">💨 Miss<br>5dmg</button>
          <button onclick="bossBattleReview(2)" style="background:var(--peach);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.72rem;font-weight:600;cursor:pointer;">⚔️ Fraco<br>15dmg</button>
          <button onclick="bossBattleReview(3)" style="background:var(--blue);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.72rem;font-weight:600;cursor:pointer;">🗡️ Forte<br>30dmg</button>
          <button onclick="bossBattleReview(4)" style="background:var(--green);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.72rem;font-weight:600;cursor:pointer;">💥 Critical<br>50dmg</button>
        </div>`;
    }).catch(() => { a.textContent = '(erro ao carregar)'; a.style.display = 'block'; });
  };
}

export async function bossBattleReview(rating) {
  if (!_bossBattle) return;
  const card = _bossBattle.cards[_bossBattle.index];
  const dano = _bossBattle.dano_map[rating] || 0;
  _bossBattle.danoTotal += dano;

  // Track stats
  if (rating === 4) _bossBattle.stats.easy++;
  else if (rating === 3) _bossBattle.stats.good++;
  else if (rating === 2) _bossBattle.stats.hard++;
  else _bossBattle.stats.again++;

  // Review the flashcard via FSRS
  const quality = {1: 0, 2: 2, 3: 4, 4: 5}[rating] || 3;
  try {
    await fetch(`/api/flashcards/${card.id}/review-fsrs`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ quality })
    });
  } catch(e) {}

  // Feedback visual rápido
  const msgs = ['💨 Miss! 5 dano', '⚔️ 15 dano!', '🗡️ 30 dano!', '💥 CRITICAL! 50 dano!'];
  toast(msgs[rating - 1], rating >= 3 ? 'success' : 'warning', 1500);

  _bossBattle.index++;
  _renderBossBattle();
}

/**
 * Inicia revisão de flashcards filtrada por matéria.
 * Chamada pelo dashboard (metas.js) ao clicar na matéria.
 * Usa /api/flashcards/today?materia=X para trazer apenas os pendentes SRS daquela matéria.
 */
export async function startFlashByMateria(materia) {
  try {
    const pendentes = await fetch(`/api/flashcards/today?materia=${encodeURIComponent(materia)}`).then(r => r.json());
    if (!pendentes || pendentes.length === 0) {
      toast(`Nenhum flashcard pendente em "${materia}".`, 'info');
      return;
    }
    // Carregar na fila de revisão principal
    flashcardsToday = pendentes;
    currentFlashIndex = 0;
    _flashOriginalTotal = pendentes.length;
    _flashReviewedToday = 0;
    _flashSessionStart = Date.now();
    _flashSessionSeconds = 0;

    // Navegar para a aba de flashcards
    switchTab('tab-flashcards');
    showCurrentFlashcard();
    toast(`📚 Revisão: ${materia} (${pendentes.length} pendentes)`, 'success');
  } catch (e) {
    toast('Erro ao iniciar revisão por matéria', 'error');
  }
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


// ============================================================
// FREE RECALL (Brain Dump) — Escrita livre sem consulta
// Evidência: Karpicke & Blunt (2011), Roediger & Karpicke (2006)
// ============================================================

export async function openBrainDump() {
  // Buscar matérias disponíveis
  let materias = [];
  try {
    materias = await fetch('/api/edital/materias-disponiveis').then(r => r.json());
  } catch(e) {}

  if (materias.length === 0) {
    toast('Adicione matérias ao edital primeiro.', 'warning');
    return;
  }

  const q = document.getElementById('flash-question');
  const a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn');
  const rv = document.getElementById('flash-review-btns');
  const progressEl = document.getElementById('flash-progress');

  if (a) a.style.display = 'none';
  if (rb) rb.style.display = 'none';
  if (rv) rv.style.display = 'none';
  if (progressEl) progressEl.style.display = 'none';

  const materiaOpts = materias.map(m => `<option value="${m}">${m}</option>`).join('');

  q.innerHTML = `
    <div style="text-align:center;margin-bottom:10px;">
      <span style="font-size:1.5rem;">🧠</span>
      <div style="font-size:0.95rem;font-weight:700;color:var(--accent);margin:4px 0;">Free Recall (Brain Dump)</div>
      <div style="font-size:0.72rem;color:var(--text-sub);">Escreva TUDO que lembra sobre uma matéria — sem consultar nada!</div>
      <div style="font-size:0.65rem;color:var(--text-sub);margin-top:2px;">Karpicke & Blunt (2011): Free recall = retenção igual ou superior a concept mapping</div>
    </div>
    <select id="brain-dump-materia" style="width:100%;padding:8px;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-bottom:8px;font-size:0.85rem;">
      <option value="">📚 Escolha a matéria...</option>
      ${materiaOpts}
    </select>
    <textarea id="brain-dump-texto" placeholder="Escreva tudo que lembra sobre essa matéria... conceitos, regras, exceções, exemplos, artigos, súmulas... O que vier à mente! Sem consultar nada."
      style="width:100%;min-height:150px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;color:var(--text);font-size:0.85rem;font-family:inherit;resize:vertical;line-height:1.5;"></textarea>
    <div id="brain-dump-counter" style="font-size:0.7rem;color:var(--text-sub);text-align:right;margin-top:2px;">0 palavras</div>
    <div style="display:flex;gap:8px;margin-top:10px;">
      <button onclick="submitBrainDump()" style="flex:1;background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:10px;font-size:0.85rem;font-weight:600;cursor:pointer;">📊 Analisar Gaps</button>
      <button onclick="closeBrainDump()" style="flex:0.5;background:var(--bg-surface);color:var(--text-sub);border:1px solid var(--border);border-radius:6px;padding:10px;font-size:0.85rem;cursor:pointer;">Cancelar</button>
    </div>
  `;

  // Contador de palavras em tempo real
  setTimeout(() => {
    const textarea = document.getElementById('brain-dump-texto');
    const counter = document.getElementById('brain-dump-counter');
    if (textarea && counter) {
      textarea.addEventListener('input', () => {
        const words = textarea.value.trim().split(/\s+/).filter(w => w.length > 0).length;
        counter.textContent = `${words} palavras`;
        counter.style.color = words >= 50 ? 'var(--green)' : words >= 20 ? 'var(--yellow)' : 'var(--text-sub)';
      });
      textarea.focus();
    }
  }, 100);
}

export async function submitBrainDump() {
  const materia = document.getElementById('brain-dump-materia')?.value;
  const texto = document.getElementById('brain-dump-texto')?.value.trim();

  if (!materia) { toast('Selecione uma matéria.', 'warning'); return; }
  if (!texto || texto.split(/\s+/).length < 5) { toast('Escreva pelo menos 5 palavras.', 'warning'); return; }

  try {
    const result = await api('/api/study-intelligence/brain-dump', {
      method: 'POST',
      body: { materia, texto }
    });

    // Mostrar resultado da análise
    const q = document.getElementById('flash-question');
    const analise = result.analise;

    let gapsHtml = '';
    if (analise.gaps.length > 0) {
      gapsHtml = `
        <div style="margin-top:8px;">
          <div style="font-size:0.78rem;font-weight:600;color:var(--red);margin-bottom:4px;">❌ Gaps (tópicos não mencionados):</div>
          ${analise.gaps.map(g => `<div style="font-size:0.75rem;padding:2px 6px;color:var(--text-sub);">• ${g}</div>`).join('')}
        </div>`;
    }

    let mencionadosHtml = '';
    if (analise.mencionados_lista.length > 0) {
      mencionadosHtml = `
        <div style="margin-top:8px;">
          <div style="font-size:0.78rem;font-weight:600;color:var(--green);margin-bottom:4px;">✅ Tópicos cobertos:</div>
          ${analise.mencionados_lista.map(m => `<div style="font-size:0.75rem;padding:2px 6px;color:var(--text-sub);">• ${m}</div>`).join('')}
        </div>`;
    }

    const coberturaColor = analise.cobertura_pct >= 70 ? 'var(--green)' : analise.cobertura_pct >= 40 ? 'var(--yellow)' : 'var(--red)';

    q.innerHTML = `
      <div style="text-align:center;margin-bottom:12px;">
        <span style="font-size:1.5rem;">📊</span>
        <div style="font-size:0.95rem;font-weight:700;color:var(--accent);">Resultado do Brain Dump</div>
      </div>
      <div style="display:flex;gap:12px;margin-bottom:10px;">
        <div style="flex:1;background:var(--bg-surface);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.3rem;font-weight:700;color:${coberturaColor};">${analise.cobertura_pct}%</div>
          <div style="font-size:0.7rem;color:var(--text-sub);">Cobertura</div>
        </div>
        <div style="flex:1;background:var(--bg-surface);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.3rem;font-weight:700;color:var(--blue);">${result.palavras_escritas}</div>
          <div style="font-size:0.7rem;color:var(--text-sub);">Palavras</div>
        </div>
        <div style="flex:1;background:var(--bg-surface);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.3rem;font-weight:700;color:var(--peach);">${analise.nao_mencionados}</div>
          <div style="font-size:0.7rem;color:var(--text-sub);">Gaps</div>
        </div>
      </div>
      <div style="font-size:0.82rem;color:var(--text);padding:8px;background:var(--bg-surface);border-radius:8px;margin-bottom:8px;">${result.mensagem}</div>
      ${gapsHtml}
      ${mencionadosHtml}
      <div style="margin-top:12px;display:flex;gap:8px;">
        <button onclick="openBrainDump()" style="flex:1;background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:8px;font-size:0.8rem;font-weight:600;cursor:pointer;">🔄 Novo Brain Dump</button>
        <button onclick="closeBrainDump()" style="flex:1;background:var(--bg-surface);color:var(--text-sub);border:1px solid var(--border);border-radius:6px;padding:8px;font-size:0.8rem;cursor:pointer;">Voltar</button>
      </div>
    `;

    toast(`Brain Dump salvo! ${analise.cobertura_pct}% de cobertura.`, analise.cobertura_pct >= 70 ? 'success' : 'warning');
  } catch(e) {
    toast('Erro ao salvar brain dump', 'error');
  }
}

export function closeBrainDump() {
  // Volta ao estado normal de flashcards
  loadFlashcardsToday();
}
