// ==================== TAB 4: FLASHCARDS ====================
import { escapeHtml, toast, showLoading, showEmpty, api, undoableDelete, confirmModal } from './utils.js';
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
let _chunkPauseShown = false; // Controle para não re-mostrar pausa de chunk
let _examMode = false; // Encoding Specificity: modo prova sem ajudas
let _productionCount = 0; // Production Effect: contador para hint de ler em voz alta
let _currentFilterMateria = ''; // Matéria filtrada na sessão atual (para sugerir próxima)

// Timer por card (análogo ao das questões): começa no tempo estimado pela
// complexidade (card.tempo_segundos), decresce até 0 e então conta tempo extra.
// Roda enquanto o estudante lê pergunta E resposta; só para quando ele confirma
// se acertou/errou (reviewFlashcard/sessaoNext), não ao revelar a resposta.
let _flashTimerInterval = null;
let _flashTimerSeg = 0;
let _flashTimerMax = 0;
let _flashTimerFase = 'regressiva'; // 'regressiva' (previsto) | 'extra' (excedente)
let _flashTimerExtra = 0;           // segundos além do previsto (fase extra)
let _flashTimerElapsed = 0;         // segundos totais no card (previsto + extra)
let _lastTempoResumo = null;        // resumo de tempo do card ao avaliar acerto/erro

function _stopFlashTimer() {
  if (_flashTimerInterval) {
    clearInterval(_flashTimerInterval);
    _flashTimerInterval = null;
  }
  const timer = document.getElementById('flash-timer');
  if (timer) timer.style.display = 'none';
}

/**
 * Timer de revisão de flashcard em duas fases:
 *  1) Regressiva: parte do tempo previsto (card.tempo_segundos, calculado no
 *     backend a partir de enunciado + resposta + estado FSRS) e decresce até 0.
 *  2) Extra: ao zerar NÃO para — passa a CRESCER, computando todo o tempo que o
 *     estudante ainda leva até indicar acertou/errou (revelar a resposta chama
 *     _stopFlashTimer). Assim medimos o tempo real completo no card.
 */
function _startFlashTimer(segundos) {
  _stopFlashTimer();
  _flashTimerMax = Math.max(1, segundos || 20);
  _flashTimerSeg = _flashTimerMax;
  _flashTimerFase = 'regressiva';
  _flashTimerExtra = 0;
  _flashTimerElapsed = 0;

  const timer = document.getElementById('flash-timer');
  const fill = document.getElementById('flash-timer-fill');
  const label = document.getElementById('flash-timer-label');
  if (!timer || !fill || !label) return;

  timer.style.display = 'block';
  fill.style.width = '100%';
  fill.style.background = 'var(--blue)';
  fill.style.animation = '';
  label.textContent = `⏱ ${_flashTimerSeg}s`;
  label.style.color = 'var(--text-sub)';
  label.style.fontWeight = '';

  _flashTimerInterval = setInterval(() => {
    _flashTimerElapsed++;

    if (_flashTimerFase === 'regressiva') {
      _flashTimerSeg--;

      if (_flashTimerSeg > 0) {
        // Ainda dentro do tempo previsto: barra decrescente + gradiente de cor.
        const pct = Math.max(0, (_flashTimerSeg / _flashTimerMax) * 100);
        fill.style.width = pct + '%';
        label.textContent = `⏱ ${_flashTimerSeg}s`;
        if (_flashTimerSeg <= 5) {
          label.style.color = 'var(--red)';
          fill.style.background = 'var(--red)';
        } else if (_flashTimerSeg <= 10) {
          label.style.color = 'var(--yellow)';
          fill.style.background = 'var(--peach)';
        } else {
          label.style.color = 'var(--text-sub)';
          fill.style.background = 'var(--blue)';
        }
      } else {
        // Esgotou o previsto → entra na fase EXTRA (cronômetro crescente).
        _flashTimerFase = 'extra';
        fill.style.width = '100%';
        fill.style.background = 'var(--red)';
        label.style.color = 'var(--red)';
        label.style.fontWeight = '700';
        label.textContent = '⏱ +0s (tempo extra)';
      }
    } else {
      // Fase extra: apenas incrementa e mostra quanto passou do previsto.
      _flashTimerExtra++;
      label.textContent = `⏱ +${_flashTimerExtra}s (tempo extra)`;
    }
  }, 1000);
}

/** Descreve o desempenho de tempo do card atual (para feedback ao avaliar). */
function _resumoTempoCard() {
  const previsto = _flashTimerMax || 0;
  const total = _flashTimerElapsed || 0;
  const extra = _flashTimerExtra || 0;
  const dentroDoPrevisto = extra <= 0 && total <= previsto;
  return { previsto, total, extra, dentroDoPrevisto };
}

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
    _currentFilterMateria = ''; // Reset filtro de matéria
    flashcardsToday = await fetch('/api/flashcards/today').then(r => r.json());
    currentFlashIndex = 0;

    // Buscar quantos flashcards foram revisados HOJE (contagem específica de
    // flashcards, sem contaminação de súmulas/outros modos). Fallback para o
    // streak se o endpoint novo não existir (compat.).
    try {
      const cnt = await fetch('/api/flashcards/today-count').then(r => r.json());
      _flashReviewedToday = (cnt && typeof cnt.revisados_hoje === 'number') ? cnt.revisados_hoje : 0;
    } catch(e) {
      try {
        const streak = await fetch('/api/streaks').then(r => r.json());
        _flashReviewedToday = (streak && streak.hoje && streak.hoje.flashcards_revisados) ? streak.hoje.flashcards_revisados : 0;
      } catch(e2) {
        _flashReviewedToday = parseInt(sessionStorage.getItem('flash_reviewed_today') || '0');
      }
    }
    _flashOriginalTotal = flashcardsToday.length + _flashReviewedToday;

    showCurrentFlashcard();
  } catch (e) { toast('Erro ao carregar flashcards de hoje', 'error'); }
}

function showCurrentFlashcard() {
  const q = document.getElementById('flash-question'), a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn'), rv = document.getElementById('flash-review-btns');
  // Parar qualquer timer regressivo do card anterior (será reiniciado abaixo se
  // um novo card for exibido). Cobre pausa de chunk, fim de sessão e trocas.
  _stopFlashTimer();
  // Limpar hint de leitura em voz alta ao trocar de card (evita acúmulo no DOM)
  document.getElementById('production-hint')?.remove();
  const progressEl = document.getElementById('flash-progress');
  const pendentes = flashcardsToday.length;
  const totalOriginal = _flashOriginalTotal || pendentes;
  const done = _flashReviewedToday + currentFlashIndex;
  const total = totalOriginal || 1;

  // === CHUNKING (Miller, 1956): Pausa reflexiva a cada 5-7 cards ===
  // Só ativa em sessões com 8+ cards, pausa a cada CHUNK_SIZE cards revisados
  // Desativado no Modo Prova (Encoding Specificity)
  const CHUNK_SIZE = 6;
  if (!_examMode && pendentes >= 8 && currentFlashIndex > 0 && currentFlashIndex < pendentes
      && currentFlashIndex % CHUNK_SIZE === 0 && !_chunkPauseShown) {
    _chunkPauseShown = true;
    _showChunkPause(currentFlashIndex, pendentes);
    return;
  }
  _chunkPauseShown = false;

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
    // Distributed Summary: prompt de 1 frase ao final da sessão
    // Evidência: Rawson & Dunlosky (2022) — Resumir distribuído consolida mais que resumir uma vez
    const summaryPrompt = doneAll >= 3 ? `
      <div style="margin-top:12px;padding:10px;background:var(--bg-surface);border-radius:8px;">
        <div style="font-size:0.78rem;color:var(--accent);font-weight:600;margin-bottom:4px;">📝 Distributed Summary</div>
        <div style="font-size:0.7rem;color:var(--text-sub);margin-bottom:6px;">Resuma em 1 frase o que aprendeu/revisou nesta sessão:</div>
        <textarea id="session-summary-input" placeholder="Ex: 'Revisão de prazos processuais — mandado de segurança é 120 dias, habeas data é...' " aria-label="Resumo da sessão"
          style="width:100%;min-height:40px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px;color:var(--text);font-size:0.8rem;font-family:inherit;resize:vertical;"></textarea>
        <button onclick="saveSessionSummary()" style="margin-top:6px;background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;font-size:0.78rem;font-weight:600;cursor:pointer;">💾 Salvar resumo</button>
      </div>` : '';

    // Se foi sessão filtrada por matéria, oferecer próxima matéria
    let nextMateriaHtml = '';
    if (_currentFilterMateria) {
      nextMateriaHtml = `<div id="next-materia-suggestion" style="margin-top:12px;text-align:center;">
        <div style="font-size:0.75rem;color:var(--text-sub);margin-bottom:6px;">Carregando próximas matérias...</div>
      </div>`;
      // Buscar próxima matéria async
      _loadNextMateriaSuggestion();
    }

    q.innerHTML = `<span style="color:#a6e3a1;font-size:1.3rem;font-weight:600;">🎉 ${_currentFilterMateria ? _currentFilterMateria + ' concluída!' : 'Parabéns!'} ${doneAll} flashcards revisados!</span>${nextMateriaHtml}${summaryPrompt}`;
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
  const isVariation = card._expanding_retrieval;
  const badge = card.materia ? `<span style="font-size:0.7rem;background:#45475a;color:#cba6f7;padding:2px 8px;border-radius:4px;margin-bottom:4px;display:inline-block;">📚 ${card.materia}</span><br>` : '';

  // Variação de Contexto: cards re-inseridos via expanding retrieval são mostrados INVERTIDOS
  // (resposta como pista → lembrar a pergunta/conceito)
  // Evidência: Smith et al. (1978) — Variar contexto de encoding melhora recall em 20-40%
  if (isVariation) {
    const variationBadge = `<span style="font-size:0.65rem;background:var(--peach);color:var(--bg);padding:2px 6px;border-radius:4px;margin-bottom:4px;display:inline-block;">🔄 Variação de Contexto</span><br>`;
    q.innerHTML = badge + variationBadge + `<div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:6px;">A resposta é a pista — lembre o conceito/pergunta original:</div>` + `<div style="font-weight:600;">${escapeHtml(card.resposta)}</div>`;
    a.textContent = card.pergunta; // Inverte: mostra pergunta como "resposta"
  } else {
    q.innerHTML = badge + escapeHtml(card.pergunta);
    a.textContent = card.resposta;
  }
  a.style.display = 'none';
  rv.style.display = 'none';

  // No Modo Prova: sem metacognição, sem generation mode — direto ao ponto
  if (_examMode) {
    rb.style.display = 'inline-block';
    _flashCardStart = Date.now();
    if (!_flashSessionStart) _flashSessionStart = Date.now();
    _startFlashTimer(card.tempo_segundos);
    return;
  }

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
      <textarea id="flash-generation-input" placeholder="Digite sua resposta antes de revelar..." aria-label="Sua resposta"
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
  _startFlashTimer(card.tempo_segundos);
}

function _segmentText(text) {
  // Dividir em partes de ~60-80 chars nos limites de frase
  const sentences = text.split(/(?<=[.;!?])\s+|(?<=\n)/);
  const parts = [];
  let current = '';
  for (const s of sentences) {
    if (current.length + s.length > 80 && current.length > 0) {
      parts.push(current.trim());
      current = s;
    } else {
      current += (current ? ' ' : '') + s;
    }
  }
  if (current.trim()) parts.push(current.trim());
  return parts.length > 1 ? parts : [text];
}

export function revealNextSegment() {
  if (!window._segParts) return;
  window._segCurrent++;
  const parts = window._segParts;
  const idx = window._segCurrent;
  const answerEl = document.getElementById('flash-answer');
  if (idx < parts.length) {
    let html = parts.slice(0, idx + 1).map(p => `<div style="font-size:0.82rem;color:var(--text);margin-bottom:4px;">${p}</div>`).join('');
    if (idx + 1 < parts.length) {
      html += `<button id="seg-more-btn" onclick="revealNextSegment()" style="margin-top:4px;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;padding:4px 10px;color:var(--accent);font-size:0.72rem;cursor:pointer;">Parte ${idx + 2}/${parts.length} ▼</button>`;
    }
    answerEl.innerHTML = html;
  }
}

export function revealAnswer() {
  // NÃO paramos o timer aqui: o estudante ainda vai ler a resposta e decidir se
  // acertou/errou. O timer segue contando (previsto → tempo extra) e só para em
  // reviewFlashcard(), quando a avaliação é confirmada.
  // Record confidence level (metacognition)
  const confidence = _currentConfidence;
  _currentConfidence = 0; // Reset

  // === COGNITIVE LOAD SEGMENTING (Mayer 2009) ===
  // Respostas longas (>120 chars) são reveladas em partes para reduzir carga cognitiva
  const answerEl = document.getElementById('flash-answer');
  const card = flashcardsToday[currentFlashIndex];
  if (!_examMode && card && card.resposta && card.resposta.length > 120) {
    const parts = _segmentText(card.resposta);
    let currentPart = 0;
    answerEl.innerHTML = `<div style="font-size:0.82rem;color:var(--text);">${parts[0]}</div>`
      + (parts.length > 1 ? `<button id="seg-more-btn" onclick="revealNextSegment()" style="margin-top:6px;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;padding:4px 10px;color:var(--accent);font-size:0.72rem;cursor:pointer;">Parte ${currentPart + 2}/${parts.length} ▼</button>` : '')
      + `<div style="font-size:0.6rem;color:var(--text-sub);margin-top:4px;">Segmenting (Mayer, 2009): revelar em partes reduz cognitive overload</div>`;
    answerEl.style.display = 'block';
    window._segParts = parts;
    window._segCurrent = 0;
  } else {
    answerEl.style.display = 'block';
  }
  document.getElementById('flash-reveal-btn').style.display = 'none';
  document.getElementById('flash-confidence-area')?.remove();
  document.getElementById('flash-generation-area')?.remove();

  // === PRODUCTION EFFECT (MacLeod 2010) ===
  // Ler em voz alta melhora encoding em 10-15% vs ler silenciosamente
  // Mostrar hint sutil a cada 4 cards (não em todo card para não irritar)
  _productionCount = (_productionCount || 0) + 1;
  // Remover hint anterior (evita acúmulo/duplicação entre cards ou re-reveals)
  document.getElementById('production-hint')?.remove();
  if (!_examMode && _productionCount % 4 === 1) {
    const ansEl = document.getElementById('flash-answer');
    if (ansEl) {
      const hint = document.createElement('div');
      hint.id = 'production-hint';
      hint.style.cssText = 'font-size:0.65rem;color:var(--accent);text-align:center;margin-top:6px;opacity:0.8;';
      hint.innerHTML = '🔊 <em>Leia a resposta em voz alta — melhora memória em 15% (MacLeod, 2010)</em>';
      ansEl.parentElement.insertBefore(hint, ansEl.nextSibling);
    }
  }

  // Auto-start global timer if not already running
  _autoStartTimerIfNeeded('Flashcards (Revisão)');

  // Show metacognition feedback if confidence was recorded
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
    // O estudante confirmou acerto/erro: AGORA o recall termina de verdade.
    // Captura o desempenho de tempo (previsto vs total, incluindo o tempo lendo
    // a resposta) e só então para o timer.
    _lastTempoResumo = _resumoTempoCard();
    _stopFlashTimer();

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

    // Feedback de tempo: total gasto (recall + leitura da resposta) vs previsto.
    let tempoMsg = '';
    const rt = _lastTempoResumo;
    if (rt && rt.previsto > 0) {
      tempoMsg = rt.dentroDoPrevisto
        ? ` ⏱ ${rt.total}s/${rt.previsto}s ✓`
        : ` ⏱ ${rt.total}s/${rt.previsto}s (+${rt.extra}s)`;
    }

    toast(`${msgs[quality]} [${stateLabel}]${metacogMsg}${tempoMsg}`, quality >= 3 ? 'success' : 'warning', 3000);

    // === HYPERCORRECTION EFFECT (Butterfield & Metcalfe, 2001) ===
    // Erros com alta confiança são corrigidos com mais eficácia.
    // Quando confiança >= 4 E quality <= 1 → feedback especial que ativa surprise signal no cérebro
    const isHypercorrection = lastMetacog && lastMetacog.confidence >= 4 && quality <= 1;
    if (isHypercorrection && !_examMode) {
      _showHypercorrectionFeedback(card, lastMetacog.confidence);
      return; // Pausa — o aluno precisa processar o "surprise"
    }

    // XP real-time feedback
    showFlashcardXp(quality);

    // Emitir evento para integração cross-module
    emit('flashcard:revisado', { materia: card.materia, quality, acertou: quality >= 3 });

    // Feed adaptive pomodoro fatigue detection
    if (window._adaptivePomo) {
      const tempoCard = _flashCardStart ? Math.round((Date.now() - _flashCardStart) / 1000) : 0;
      window._adaptivePomo.recordAnswer(quality >= 3, tempoCard);
    }

    // Keyword Mnemonic: sugerir mnemônico após erro em card difícil
    // Desativado no Modo Prova
    _mnemonicErrorCount = (_mnemonicErrorCount || 0) + (quality <= 1 ? 1 : 0);
    if (!_examMode && quality <= 1 && card.repetitions > 0 && _mnemonicErrorCount % 2 === 0) {
      _showMnemonicSuggestion(card);
      return; // Pausa — fluxo continua ao pular/salvar mnemônico
    }

    // Elaborative Interrogation: prompt "Por quê?" após acerto (quality >= 3)
    // Desativado no Modo Prova
    _elaborationAccertCount = (_elaborationAccertCount || 0) + (quality >= 3 ? 1 : 0);
    const shouldElaborate = !_examMode && quality >= 3 && _elaborationAccertCount % 3 === 0 && card.pergunta;
    if (shouldElaborate) {
      _showElaborationPrompt(card);
      return; // Pausa — o fluxo continua ao pular/salvar a elaboração
    }

    // === MICRO-BREAKS COGNITIVOS (Frontiers 2025) ===
    // Pausa de 5s após cards difíceis (quality <= 2) para melhorar encoding
    // Desativado no Modo Prova. Não aplica se já houve mnemonic ou hypercorrection.
    if (!_examMode && quality <= 2 && currentFlashIndex < flashcardsToday.length - 1) {
      _showMicroBreak(quality);
      return;
    }

    _advanceAfterReview();
  } catch (e) { toast('Erro ao revisar', 'error'); }
}

let _elaborationAccertCount = 0;
let _mnemonicErrorCount = 0;

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
      }).then(() => {
        // Notifica a UI para atualizar o "tempo de hoje" sem refresh manual.
        emit('sessao:horas', { materia: 'Flashcards (Revisão)', horas, tipo: 'flashcard' });
      }).catch(() => {});
      _flashSessionSeconds = 0; // Reset para próximo bloco
    }
}

function _showMicroBreak(quality) {
  const q = document.getElementById('flash-question');
  const a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn');
  const rv = document.getElementById('flash-review-btns');

  if (a) a.style.display = 'none';
  if (rb) rb.style.display = 'none';
  if (rv) rv.style.display = 'none';

  const msgs = [
    '🧠 Respire... seu cérebro está processando.',
    '💭 Pausa cognitiva — encoding em andamento...',
    '🌊 Momento de consolidação. Respire fundo.',
  ];
  const msg = msgs[Math.floor(Math.random() * msgs.length)];

  let countdown = 5;
  q.innerHTML = `
    <div style="text-align:center;padding:20px;">
      <div style="font-size:2rem;margin-bottom:8px;animation:pulse 1.5s ease-in-out infinite;">🧘</div>
      <div style="font-size:0.85rem;color:var(--text);margin-bottom:4px;">${msg}</div>
      <div style="font-size:0.65rem;color:var(--text-sub);margin-bottom:12px;">Micro-break de ${countdown}s melhora consolidação (Frontiers 2025)</div>
      <div id="microbreak-countdown" style="font-size:1.5rem;font-weight:800;color:var(--accent);">${countdown}</div>
      <button onclick="skipMicroBreak()" style="margin-top:12px;background:none;border:none;color:var(--text-sub);font-size:0.7rem;cursor:pointer;text-decoration:underline;">Pular →</button>
    </div>
  `;

  // Countdown auto-advance
  const interval = setInterval(() => {
    countdown--;
    const el = document.getElementById('microbreak-countdown');
    if (el) el.textContent = countdown;
    if (countdown <= 0) {
      clearInterval(interval);
      _advanceAfterReview();
    }
  }, 1000);

  // Guardar referência para poder cancelar se pular
  window._microBreakInterval = interval;
}

export function skipMicroBreak() {
  if (window._microBreakInterval) {
    clearInterval(window._microBreakInterval);
    window._microBreakInterval = null;
  }
  _advanceAfterReview();
}

function _showChunkPause(cardsDone, totalPendentes) {
  const q = document.getElementById('flash-question');
  const a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn');
  const rv = document.getElementById('flash-review-btns');

  if (a) a.style.display = 'none';
  if (rb) rb.style.display = 'none';
  if (rv) rv.style.display = 'none';

  const blocoNum = Math.ceil(cardsDone / 6);
  const restantes = totalPendentes - cardsDone;

  // Buscar matérias dos últimos 6 cards revisados
  const blocoCarts = flashcardsToday.slice(Math.max(0, cardsDone - 6), cardsDone);
  const materiasBlocos = [...new Set(blocoCarts.map(c => c.materia || 'Geral'))];

  // === FORWARD TESTING EFFECT (Chan 2018, Pastötter 2011) ===
  // Quiz rápido de 2 cards do bloco anterior → potencializa aprendizado do próximo bloco
  const quizCards = blocoCarts.filter(c => c.pergunta && c.resposta).sort(() => Math.random() - 0.5).slice(0, 2);
  let forwardTestHtml = '';
  if (quizCards.length > 0) {
    forwardTestHtml = `
      <div style="margin-bottom:10px;padding:10px;background:rgba(137,180,250,0.1);border:1px solid var(--blue);border-radius:8px;">
        <div style="font-size:0.75rem;color:var(--blue);font-weight:600;margin-bottom:6px;">⚡ Forward Testing — Relembre antes de avançar:</div>
        ${quizCards.map((c, i) => `
          <div style="margin-bottom:6px;padding:6px;background:var(--bg);border-radius:6px;">
            <div style="font-size:0.75rem;color:var(--text);">${i + 1}. ${escapeHtml(c.pergunta).substring(0, 80)}${c.pergunta.length > 80 ? '...' : ''}</div>
            <div class="fwd-answer" id="fwd-answer-${i}" style="display:none;font-size:0.72rem;color:var(--green);margin-top:3px;font-weight:600;">→ ${escapeHtml(c.resposta).substring(0, 60)}</div>
            <button onclick="document.getElementById('fwd-answer-${i}').style.display='block';this.style.display='none';" style="font-size:0.65rem;color:var(--accent);background:none;border:none;cursor:pointer;margin-top:2px;">Revelar ↓</button>
          </div>
        `).join('')}
        <div style="font-size:0.62rem;color:var(--text-sub);margin-top:4px;">Pastötter (2011): Testar bloco anterior melhora encoding do próximo em 20-30%</div>
      </div>`;
  }

  q.innerHTML = `
    <div style="text-align:center;margin-bottom:10px;">
      <span style="font-size:1.5rem;">🧩</span>
      <div style="font-size:0.92rem;font-weight:700;color:var(--accent);margin:4px 0;">Pausa Reflexiva — Bloco ${blocoNum} concluído!</div>
      <div style="font-size:0.7rem;color:var(--text-sub);">Chunking (Miller, 1956): Blocos de 5-7 itens otimizam a memória de trabalho</div>
    </div>
    ${forwardTestHtml}
    <div style="background:var(--bg-surface);border-radius:8px;padding:12px;margin-bottom:10px;">
      <div style="font-size:0.8rem;color:var(--text);font-weight:600;margin-bottom:6px;">📊 Progresso do bloco:</div>
      <div style="display:flex;gap:10px;margin-bottom:8px;">
        <div style="flex:1;text-align:center;">
          <div style="font-size:1.1rem;font-weight:700;color:var(--green);">${cardsDone}</div>
          <div style="font-size:0.65rem;color:var(--text-sub);">Revisados</div>
        </div>
        <div style="flex:1;text-align:center;">
          <div style="font-size:1.1rem;font-weight:700;color:var(--yellow);">${restantes}</div>
          <div style="font-size:0.65rem;color:var(--text-sub);">Restantes</div>
        </div>
      </div>
      <div style="font-size:0.72rem;color:var(--text-sub);">Matérias: ${materiasBlocos.join(', ')}</div>
    </div>
    <div style="margin-bottom:10px;">
      <div style="font-size:0.78rem;color:var(--text);font-weight:600;margin-bottom:4px;">🤔 Mini-resumo (opcional):</div>
      <textarea id="chunk-resumo" placeholder="O que você aprendeu neste bloco? Conceitos-chave, regras, conexões..." aria-label="Resumo do bloco"
        style="width:100%;min-height:50px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px;color:var(--text);font-size:0.8rem;font-family:inherit;resize:vertical;"></textarea>
    </div>
    <div style="display:flex;gap:8px;">
      <button onclick="continueAfterChunk()" style="flex:1;background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:10px;font-size:0.85rem;font-weight:600;cursor:pointer;">▶ Próximo bloco (${restantes} cards)</button>
    </div>
  `;
}

export function continueAfterChunk() {
  // Salvar mini-resumo se preenchido
  const resumo = document.getElementById('chunk-resumo')?.value.trim();
  if (resumo) {
    // Salvar como elaboração do bloco
    const card = flashcardsToday[currentFlashIndex - 1]; // Último card do bloco
    fetch('/api/study-intelligence/elaboration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        flashcard_id: card ? card.id : null,
        prompt_tipo: 'chunk_summary',
        resposta_usuario: resumo
      })
    }).catch(() => {});
    toast('📝 Mini-resumo salvo!', 'success', 1500);
  }
  // Continuar para o próximo card
  _chunkPauseShown = false;
  showCurrentFlashcard();
}

// ============================================================
// HYPERCORRECTION EFFECT — Feedback especial para erros com alta confiança
// Evidência: Butterfield & Metcalfe (2001) — Surprise signal do erro
// inesperado ativa processos de encoding mais profundos
// ============================================================

function _showHypercorrectionFeedback(card, confidence) {
  const q = document.getElementById('flash-question');
  const a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn');
  const rv = document.getElementById('flash-review-btns');

  if (a) a.style.display = 'none';
  if (rb) rb.style.display = 'none';
  if (rv) rv.style.display = 'none';

  q.innerHTML = `
    <div style="text-align:center;padding:8px;animation:pulse 1s ease-in-out;">
      <div style="font-size:2rem;margin-bottom:6px;">⚡</div>
      <div style="font-size:0.95rem;font-weight:800;color:var(--red);margin-bottom:6px;">HYPERCORRECTION ACTIVADO!</div>
      <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:12px;">
        Você tinha confiança ${'⭐'.repeat(confidence)} mas ERROU.<br>
        <strong style="color:var(--green);">Isso é BOM!</strong> Seu cérebro vai fixar a correção com mais força.<br>
        <span style="font-size:0.65rem;">(Butterfield & Metcalfe, 2001: erros surpresa são 30% mais bem corrigidos)</span>
      </div>
      <div style="background:var(--bg-surface);border-radius:8px;padding:12px;margin-bottom:10px;text-align:left;">
        <div style="font-size:0.75rem;color:var(--red);margin-bottom:4px;">❌ Você pensava que sabia:</div>
        <div style="font-size:0.82rem;color:var(--text);margin-bottom:8px;">${escapeHtml(card.pergunta)}</div>
        <div style="font-size:0.75rem;color:var(--green);margin-bottom:4px;">✅ Resposta CORRETA (memorize agora!):</div>
        <div style="font-size:0.92rem;font-weight:700;color:var(--green);padding:8px;background:rgba(166,227,161,0.1);border-radius:6px;">${escapeHtml(card.resposta)}</div>
      </div>
      <div style="font-size:0.72rem;color:var(--accent);margin-bottom:8px;">💡 Repita mentalmente 3x: "${card.resposta.substring(0, 50)}..."</div>
      <button onclick="dismissHypercorrection()" style="background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:10px 20px;font-size:0.85rem;font-weight:600;cursor:pointer;">✓ Memorizado — Próximo</button>
    </div>
  `;
}

export function dismissHypercorrection() {
  _advanceAfterReview();
}

// ============================================================
// KEYWORD MNEMONIC — Sugestão de mnemônicos para cards difíceis
// Evidência: Atkinson (1975), Pressley et al. (1982)
// ============================================================

function _showMnemonicSuggestion(card) {
  const q = document.getElementById('flash-question');
  const a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn');
  const rv = document.getElementById('flash-review-btns');

  if (a) a.style.display = 'none';
  if (rb) rb.style.display = 'none';
  if (rv) rv.style.display = 'none';

  // Gerar sugestões de mnemônicos baseadas na resposta
  const resposta = card.resposta || '';
  const pergunta = card.pergunta || '';
  const palavrasChave = resposta.split(/\s+/).filter(p => p.length > 4).slice(0, 3);
  const iniciais = palavrasChave.map(p => p[0].toUpperCase()).join('');

  // Técnicas mnemônicas sugeridas
  const sugestoes = [];
  if (iniciais.length >= 2) {
    sugestoes.push(`<strong>Acrônimo:</strong> "${iniciais}" → forme uma palavra ou frase com essas letras`);
  }
  sugestoes.push(`<strong>Associação visual:</strong> Imagine uma cena absurda/engraçada conectando a pergunta à resposta`);
  sugestoes.push(`<strong>Rima/Música:</strong> Transforme a resposta em uma rima ou encaixe numa melodia conhecida`);
  if (resposta.length < 100) {
    sugestoes.push(`<strong>Palavra-chave:</strong> Associe "${palavrasChave[0] || resposta.split(' ')[0]}" a algo que você já conhece`);
  }

  q.innerHTML = `
    <div style="text-align:center;margin-bottom:8px;">
      <span style="font-size:1.3rem;">🔑</span>
      <div style="font-size:0.88rem;font-weight:700;color:var(--peach);margin:4px 0;">Keyword Mnemonic</div>
      <div style="font-size:0.7rem;color:var(--text-sub);">Você errou esse card novamente. Crie um mnemônico para fixar!</div>
      <div style="font-size:0.65rem;color:var(--text-sub);">Pressley et al. (1982): Mnemônicos melhoram recall em 20-50%</div>
    </div>
    <div style="background:var(--bg-surface);border-radius:8px;padding:10px;margin-bottom:8px;">
      <div style="font-size:0.75rem;color:var(--text-sub);margin-bottom:2px;">❓ ${escapeHtml(pergunta).substring(0, 100)}</div>
      <div style="font-size:0.82rem;color:var(--text);font-weight:600;">✅ ${escapeHtml(resposta).substring(0, 150)}</div>
    </div>
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:8px;">
      <div style="font-size:0.75rem;font-weight:600;color:var(--accent);margin-bottom:6px;">💡 Sugestões de mnemônicos:</div>
      ${sugestoes.map(s => `<div style="font-size:0.75rem;color:var(--text-sub);padding:3px 0;">• ${s}</div>`).join('')}
    </div>
    <textarea id="mnemonic-input" placeholder="Crie seu mnemônico aqui... (ex: 'Para lembrar que CF art.5 tem 78 incisos → 5+7+8=20, como nota máxima')" aria-label="Seu mnemônico"
      style="width:100%;min-height:50px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:0.82rem;font-family:inherit;resize:vertical;"></textarea>
    <div style="display:flex;gap:8px;margin-top:8px;">
      <button onclick="saveMnemonic()" style="flex:1;background:var(--peach);color:var(--bg);border:none;border-radius:6px;padding:8px;font-size:0.8rem;font-weight:600;cursor:pointer;">🔑 Salvar Mnemônico</button>
      <button onclick="skipMnemonic()" style="flex:1;background:var(--bg-surface);color:var(--text-sub);border:1px solid var(--border);border-radius:6px;padding:8px;font-size:0.8rem;cursor:pointer;">⏭ Pular</button>
    </div>
  `;
}

export function skipMnemonic() {
  _advanceAfterReview();
}

export async function saveMnemonic() {
  const input = document.getElementById('mnemonic-input');
  const texto = input ? input.value.trim() : '';
  const card = flashcardsToday[currentFlashIndex];

  if (texto && card) {
    fetch('/api/study-intelligence/elaboration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        flashcard_id: card.id,
        prompt_tipo: 'keyword_mnemonic',
        resposta_usuario: texto
      })
    }).catch(() => {});
    toast('🔑 Mnemônico salvo! Será mostrado nas próximas revisões.', 'success', 2500);
  }

  _advanceAfterReview();
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
    `Por que essa é a resposta correta?`,
    `Explique COM SUAS PALAVRAS por que isso é verdade.`,
    `Qual é a lógica/fundamento por trás dessa resposta?`,
  ];
  const prompt = prompts[Math.floor(Math.random() * prompts.length)];

  // Escapar HTML para evitar XSS ao interpolar conteúdo do card
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

  q.innerHTML = `
    <div style="text-align:center;margin-bottom:8px;">
      <span style="font-size:1.3rem;">🤔</span>
      <div style="font-size:0.85rem;font-weight:700;color:var(--accent);margin:4px 0;">Elaborative Interrogation</div>
      <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:8px;">Explicar fortalece a memória em 10-40% (Dunlosky, 2013)</div>
    </div>
    <div style="background:var(--bg-surface);border-radius:8px;padding:10px;margin-bottom:10px;">
      <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:6px;">📚 ${esc(card.materia || 'Flashcard')}</div>
      <div style="font-size:0.82rem;color:var(--text);margin-bottom:4px;"><span style="color:var(--text-sub);">Pergunta:</span> ${esc(card.pergunta)}</div>
      <div style="font-size:0.82rem;color:var(--text);border-top:1px dashed var(--border);padding-top:6px;margin-top:6px;"><span style="color:var(--text-sub);">Resposta:</span> <strong>${esc(card.resposta)}</strong></div>
    </div>
    <div style="background:var(--bg-surface);border-radius:8px;padding:10px;margin-bottom:10px;">
      <div style="font-size:0.85rem;font-weight:600;color:var(--text);">${esc(prompt)}</div>
    </div>
    <textarea id="elaboration-input" placeholder="Escreva sua explicação... (opcional mas recomendado)" aria-label="Sua explicação"
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
  // Verificar limite do plano antes de criar
  if (window.checkPlanLimit && !(await window.checkPlanLimit('flashcards'))) return;
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
  _stopFlashTimer();
  if (flashSessaoIndex >= flashSessao.length) {
    q.innerHTML = '<span style="color:#a6e3a1;font-size:1.3rem;font-weight:600;">🎉 Sessão concluída! Parabéns!</span>';
    a.style.display = 'none'; rb.style.display = 'none'; rv.style.display = 'none';
    flashSessao = []; flashSessaoMode = '';
    return;
  }
  const card = flashSessao[flashSessaoIndex];
  // Limpar resíduos do fluxo de Revisão SRS (campo de escrever resposta,
  // slider de confiança, hint de produção). Sem isso, o texto digitado
  // permanecia visível ao trocar de card na sessão por disciplina/aleatória.
  document.getElementById('flash-genmode-toggle')?.remove();
  document.getElementById('flash-generation-area')?.remove();
  document.getElementById('flash-confidence-area')?.remove();
  document.getElementById('production-hint')?.remove();
  const badge = card.materia ? `<span style="font-size:0.7rem;background:#45475a;color:#cba6f7;padding:2px 8px;border-radius:4px;margin-bottom:6px;display:inline-block;">📚 ${card.materia}</span><br>` : '';
  q.innerHTML = badge + `<span>${flashSessaoIndex + 1}/${flashSessao.length}</span> — ${escapeHtml(card.pergunta)}`;
  a.textContent = card.resposta;
  a.style.display = 'none';
  rb.style.display = 'inline-block';
  rv.style.display = 'none';
  // Timer regressivo por complexidade (mesmo da revisão SRS): usa tempo_segundos
  // calculado no backend por pergunta+resposta+FSRS. Sem isso caía no fallback.
  _startFlashTimer(card.tempo_segundos);
  rb.onclick = function() {
    // NÃO para o timer ao revelar: segue até o estudante avaliar em sessaoNext().
    a.style.display = 'block'; rb.style.display = 'none';
    rv.style.display = 'flex';
    // Auto-start global timer if not already running (igual ao fluxo de revisão SRS)
    _autoStartTimerIfNeeded(card.materia ? `Flashcards: ${card.materia}` : 'Flashcards (Sessão)');
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
  _stopFlashTimer();  // recall encerrado só ao confirmar acerto/erro
  const card = flashSessao[flashSessaoIndex];
  if (card && card.id) {
    try {
      const data = await api(`/api/flashcards/${card.id}/review-fsrs`, { method: 'POST', body: { quality } });
      // Feedback de calibração da próxima revisão (igual ao fluxo de Revisão SRS)
      if (data && data.intervalo_dias != null) {
        const intervalLabel = data.intervalo_dias >= 30
          ? `${Math.round(data.intervalo_dias / 30)}m`
          : `${data.intervalo_dias}d`;
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
        const suffix = stateLabel ? ` [${stateLabel}]` : '';
        toast(`${msgs[quality] || ''}${suffix}`, quality >= 3 ? 'success' : 'warning', 3000);
      }
    } catch(e) {}
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

// Persistência da batalha em andamento (Fase E): salva no localStorage para
// retomar após fechar/recarregar. O estado é pequeno e expira no mesmo dia.
// O FSRS de cada card já é persistido no servidor a cada ataque, então retomar
// não reprocessa cards — apenas continua de onde parou.
const _BOSS_KEY = 'concurseiro_boss_battle';

function _hojeStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function _salvarBossBattle() {
  if (!_bossBattle) return;
  try {
    localStorage.setItem(_BOSS_KEY, JSON.stringify({ ..._bossBattle, data: _hojeStr() }));
  } catch (e) { /* storage cheio/indisponível — ignora */ }
}

function _limparBossBattle() {
  try { localStorage.removeItem(_BOSS_KEY); } catch (e) {}
}

function _carregarBossBattleSalvo() {
  try {
    const raw = localStorage.getItem(_BOSS_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw);
    // Válida somente se: for de hoje, tiver cards e ainda não terminou.
    if (!s || s.data !== _hojeStr()) { _limparBossBattle(); return null; }
    if (!Array.isArray(s.cards) || !s.cards.length || !s.boss) { _limparBossBattle(); return null; }
    const terminou = s.index >= s.cards.length || s.danoTotal >= s.boss.hp_total;
    if (terminou) { _limparBossBattle(); return null; }
    return s;
  } catch (e) { _limparBossBattle(); return null; }
}

export async function startBossBattle() {
  // Retomar batalha salva de hoje, se houver.
  const salvo = _carregarBossBattleSalvo();
  if (salvo) {
    const restantes = salvo.cards.length - salvo.index;
    const ok = await confirmModal(
      'Retomar batalha?',
      `Você tem uma batalha contra ${salvo.boss.emoji} ${salvo.boss.nome} em andamento (${restantes} card(s) restante(s)). Deseja continuar de onde parou?`,
      { type: 'info', confirmText: 'Retomar', cancelText: 'Nova batalha' }
    );
    if (ok) {
      _bossBattle = salvo;
      // defaults para campos que podem faltar em payloads antigos
      _bossBattle.combo = _bossBattle.combo || { bonus_por_acerto: 5, teto: 15, inicio: 3 };
      _bossBattle.critMult = _bossBattle.critMult || 2;
      _bossBattle.fraquezas = _bossBattle.fraquezas || [];
      _bossBattle.stats = _bossBattle.stats || { easy: 0, good: 0, hard: 0, again: 0 };
      _renderBossBattle();
      toast(`⚔️ Batalha retomada! ${restantes} card(s) restante(s).`, 'info', 2500);
      return;
    }
    _limparBossBattle();
  }

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
      combo: data.combo || { bonus_por_acerto: 5, teto: 15, inicio: 3 },
      critMult: data.crit_mult || (data.boss && data.boss.crit_mult) || 2,
      fraquezas: data.fraquezas || (data.boss && data.boss.fraquezas) || [],
      comboAtual: 0,   // acertos (>=Good) consecutivos correntes
      comboMax: 0,     // maior sequência de acertos na batalha
      index: 0,
      danoTotal: 0,
      stats: { easy: 0, good: 0, hard: 0, again: 0 },
    };
    _salvarBossBattle();
    _renderBossBattle();
    const fraq = (data.fraquezas || []);
    const msgFraq = fraq.length ? ` Fraco em: ${fraq.join(', ')} (dano crítico!)` : '';
    toast(`⚔️ ${data.boss.emoji} ${data.boss.nome} apareceu!${msgFraq}`, 'warning', 3500);
  } catch(e) { toast('Erro ao iniciar Boss Battle', 'error'); }
}

function _renderBossBattle() {
  const b = _bossBattle;
  if (!b) return;
  _stopFlashTimer();
  const q = document.getElementById('flash-question'), a = document.getElementById('flash-answer');
  const rb = document.getElementById('flash-reveal-btn'), rv = document.getElementById('flash-review-btns');
  const progressEl = document.getElementById('flash-progress');

  // Boss HP bar
  const hpPct = Math.max(0, Math.round((b.boss.hp_atual - b.danoTotal) / b.boss.hp_total * 100));
  const hpColor = hpPct > 50 ? 'var(--red)' : hpPct > 25 ? 'var(--peach)' : 'var(--green)';

  if (progressEl) {
    progressEl.style.display = 'block';
    const comboTxt = b.comboAtual >= 2 ? ` 🔥×${b.comboAtual}` : '';
    document.getElementById('flash-progress-text').textContent = `⚔️ ${b.boss.emoji} ${b.boss.nome} — HP: ${Math.max(0, b.boss.hp_total - b.danoTotal)}/${b.boss.hp_total}${comboTxt}`;
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
      body: JSON.stringify({ boss_tier: b.boss.tier || 1, boss_hp_total: b.boss.hp_total, dano_total: b.danoTotal, cards_revisados: b.index, acertos_easy: b.stats.easy, acertos_good: b.stats.good, acertos_hard: b.stats.hard, erros_again: b.stats.again, combo_max: b.comboMax, derrotou })
    }).catch(() => {});
    _limparBossBattle();
    _bossBattle = null;
    return;
  }

  // Mostrar card atual
  const card = b.cards[b.index];
  const badgeFraco = card.ponto_fraco
    ? `<div style="text-align:center;margin-bottom:6px;"><span style="background:var(--red);color:var(--bg);font-size:0.66rem;font-weight:700;padding:2px 8px;border-radius:10px;">🎯 PONTO FRACO — dano crítico ×${b.critMult}</span></div>`
    : '';
  q.innerHTML = `<div style="text-align:center;margin-bottom:6px;font-size:0.72rem;color:var(--text-sub);">⚔️ Card ${b.index + 1}/${b.cards.length} | Dano total: ${b.danoTotal}</div>` +
    badgeFraco +
    `<div style="font-size:0.95rem;color:var(--text);">${card.pergunta}</div>`;
  a.style.display = 'none';
  rb.style.display = 'inline-block';
  rv.style.display = 'none';

  // Override reveal para boss mode — usa a resposta já presente no card
  // (o payload de /boss-battle já traz `resposta`), sem baixar todos os cards.
  rb.onclick = function() {
    a.textContent = card.resposta || '(sem resposta)';
    a.style.display = 'block';
    rb.style.display = 'none';
    rv.style.display = 'flex';
    rv.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;width:100%;">
        <button onclick="bossBattleReview(1)" style="background:var(--red);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.72rem;font-weight:600;cursor:pointer;">💨 Errei<br>10dmg</button>
        <button onclick="bossBattleReview(2)" style="background:var(--peach);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.72rem;font-weight:600;cursor:pointer;">⚔️ Difícil<br>15dmg</button>
        <button onclick="bossBattleReview(3)" style="background:var(--blue);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.72rem;font-weight:600;cursor:pointer;">🗡️ Bom<br>20dmg</button>
        <button onclick="bossBattleReview(4)" style="background:var(--green);color:var(--bg);border:none;border-radius:6px;padding:8px 4px;font-size:0.72rem;font-weight:600;cursor:pointer;">💥 Fácil<br>25dmg</button>
      </div>`;
  };
}

export async function bossBattleReview(rating) {
  if (!_bossBattle) return;
  const b = _bossBattle;
  const card = b.cards[b.index];
  const danoBase = b.dano_map[rating] || 0;

  // Combo: ratings >= 3 (Good/Easy) contam como acerto e mantêm o combo.
  // Hard (2) mantém o combo (lembrou, com esforço) mas não incrementa forte;
  // Again (1) quebra o combo (sem punição de XP — só recomeça a sequência).
  const acerto = rating >= 3;
  let danoCombo = 0;
  if (acerto) {
    b.comboAtual++;
    if (b.comboAtual > b.comboMax) b.comboMax = b.comboAtual;
    if (b.comboAtual >= (b.combo.inicio || 3)) {
      // Bônus cresce com o combo, limitado ao teto.
      const passos = b.comboAtual - (b.combo.inicio || 3) + 1;
      danoCombo = Math.min(passos * (b.combo.bonus_por_acerto || 5), b.combo.teto || 15);
    }
  } else if (rating === 1) {
    b.comboAtual = 0; // Again quebra o combo
  }
  // Hard (2) não incrementa nem zera o combo (mantém a sequência viva sem contar)

  // Dano crítico por ponto fraco (Fase D): acertar (>=Good) um card de matéria
  // fraca do boss multiplica o dano — incentiva alternar matérias (interleaving).
  const critMult = b.critMult || 2;
  const ehCritico = acerto && card.ponto_fraco;
  let dano = danoBase + danoCombo;
  if (ehCritico) dano = dano * critMult;
  b.danoTotal += dano;

  // Track stats
  if (rating === 4) b.stats.easy++;
  else if (rating === 3) b.stats.good++;
  else if (rating === 2) b.stats.hard++;
  else b.stats.again++;

  // Review the flashcard via FSRS
  const quality = {1: 0, 2: 2, 3: 4, 4: 5}[rating] || 3;
  try {
    await fetch(`/api/flashcards/${card.id}/review-fsrs`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ quality })
    });
  } catch(e) {}

  // Feedback visual: dano base + combo (+ crítico de ponto fraco)
  const rotulos = ['💨 Errou', '⚔️ Difícil', '🗡️ Bom', '💥 Fácil'];
  let msg = `${rotulos[rating - 1]} — ${dano} dano`;
  if (danoCombo > 0) msg += ` (combo ×${b.comboAtual})`;
  if (ehCritico) msg = `🎯 CRÍTICO! ${msg} (ponto fraco ×${critMult})`;
  toast(msg, ehCritico ? 'success' : (rating >= 2 ? 'success' : 'info'), 1600);

  b.index++;
  _salvarBossBattle();
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
    _currentFilterMateria = materia; // Tracking da matéria filtrada

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

  // Verificar se veio do dashboard com matéria para revisão
  const pendingMateria = sessionStorage.getItem('flash_start_materia');
  if (pendingMateria) {
    sessionStorage.removeItem('flash_start_materia');
    // Garantir que a tab está visível e DOM pronto antes de iniciar
    switchTab('tab-flashcards');
    setTimeout(() => {
      switchTab('tab-flashcards');
      startFlashByMateria(pendingMateria);
    }, 500);
  } else {
    loadFlashcardsToday();
  }
  loadAllFlashcards();

  // Recarregar a fila/contagem ao voltar para a aba de flashcards (SPA sem
  // reload). Sem isso, `_flashReviewedToday` ficava obsoleto e o progresso
  // exibia valores como "2/24" em vez de refletir o total já revisado hoje.
  // Não recarrega no meio de uma sessão em andamento (evita perder posição):
  //  - sessão filtrada por matéria (_currentFilterMateria)
  //  - já revelou/revisou algum card nesta sessão (currentFlashIndex > 0)
  try {
    const flashTab = document.getElementById('tab-flashcards');
    if (flashTab && typeof MutationObserver !== 'undefined') {
      let _eraAtiva = flashTab.classList.contains('active');
      const obs = new MutationObserver(() => {
        const ativaAgora = flashTab.classList.contains('active');
        const acabouDeAbrir = ativaAgora && !_eraAtiva;
        _eraAtiva = ativaAgora;
        if (!acabouDeAbrir) return;
        const sessaoEmAndamento = _currentFilterMateria || currentFlashIndex > 0;
        if (!sessaoEmAndamento) loadFlashcardsToday();
      });
      obs.observe(flashTab, { attributes: true, attributeFilter: ['class'] });
    }
  } catch (e) { /* observer é best-effort */ }
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

  _stopFlashTimer();
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
    <select id="brain-dump-materia" aria-label="Matéria do brain dump" style="width:100%;padding:8px;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-bottom:8px;font-size:0.85rem;">
      <option value="">📚 Escolha a matéria...</option>
      ${materiaOpts}
    </select>
    <textarea id="brain-dump-texto" placeholder="Escreva tudo que lembra sobre essa matéria... conceitos, regras, exceções, exemplos, artigos, súmulas... O que vier à mente! Sem consultar nada." aria-label="Brain dump da matéria"
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

// ============================================================
// DISTRIBUTED SUMMARY — Resumo de 1 frase ao final da sessão
// Evidência: Rawson & Dunlosky (2022) — Successive Relearning
// ============================================================

export function saveSessionSummary() {
  const input = document.getElementById('session-summary-input');
  const texto = input ? input.value.trim() : '';
  if (!texto) {
    toast('Escreva pelo menos uma frase.', 'warning');
    return;
  }
  fetch('/api/study-intelligence/elaboration', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      flashcard_id: null,
      prompt_tipo: 'distributed_summary',
      resposta_usuario: texto
    })
  }).catch(() => {});
  toast('📝 Resumo da sessão salvo! Isso consolida o aprendizado.', 'success', 2500);
  const container = input.closest('div');
  if (container) container.innerHTML = `<div style="color:var(--green);font-size:0.8rem;font-weight:600;text-align:center;padding:8px;">✅ Resumo salvo!</div>`;
}

async function _loadNextMateriaSuggestion() {
  try {
    const pendentes = await fetch('/api/flashcards/today').then(r => r.json());
    if (!pendentes || pendentes.length === 0) {
      const el = document.getElementById('next-materia-suggestion');
      if (el) el.innerHTML = `<div style="color:var(--green);font-size:0.82rem;font-weight:600;">✅ Todas as matérias revisadas hoje! Zero pendentes.</div>`;
      return;
    }

    // Agrupar por matéria
    const materias = {};
    pendentes.forEach(f => { const m = f.materia || 'Sem matéria'; materias[m] = (materias[m] || 0) + 1; });

    const el = document.getElementById('next-materia-suggestion');
    if (!el) return;

    const sorted = Object.entries(materias).sort((a, b) => b[1] - a[1]);
    el.innerHTML = `
      <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:6px;">📚 Próximas matérias pendentes (${pendentes.length} restantes):</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;justify-content:center;">
        ${sorted.slice(0, 4).map(([m, c]) => `<button onclick="startFlashByMateria('${m.replace(/'/g, "\\'")}')" style="padding:6px 10px;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:pointer;font-size:0.75rem;"><strong>${m}</strong> (${c})</button>`).join('')}
      </div>
      <button onclick="loadFlashcardsToday()" style="margin-top:8px;padding:6px 14px;background:var(--accent);color:var(--bg);border:none;border-radius:6px;font-size:0.78rem;font-weight:600;cursor:pointer;">▶ Revisar TODAS (${pendentes.length})</button>
    `;
  } catch(e) {
    const el = document.getElementById('next-materia-suggestion');
    if (el) el.innerHTML = '';
  }
}

// ============================================================
// ENCODING SPECIFICITY (MODO PROVA) — Simula condições reais
// Evidência: Tulving & Thomson (1973) — Recall é melhor quando
// condições de teste = condições de encoding. Simular pressão
// de prova durante revisão melhora performance no dia da prova.
// ============================================================

export function startExamMode() {
  _examMode = true;
  toast('🎯 MODO PROVA ativado! Sem ajudas — simule a pressão real.', 'warning', 3000);
  loadFlashcardsToday();
}

export function stopExamMode() {
  _examMode = false;
  toast('📚 Modo normal restaurado.', 'info', 2000);
  loadFlashcardsToday();
}
