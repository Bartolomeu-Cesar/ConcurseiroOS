/**
 * CAT Session — Computerized Adaptive Testing UI
 *
 * Sessão adaptativa que ajusta dificuldade em tempo real,
 * mantendo o aluno na zona de flow (65-80% acerto).
 *
 * Endpoints:
 *   POST /api/sessao-adaptativa/iniciar
 *   GET  /api/sessao-adaptativa/{id}/proxima
 *   POST /api/sessao-adaptativa/{id}/responder
 *   GET  /api/sessao-adaptativa/{id}/resultado
 */

import { showToast } from './toast.js';

// ─── State ───────────────────────────────────────────────────
let _sessionId = null;
let _materia = '';
let _totalQuestoes = 20;
let _progresso = 0;
let _timerInterval = null;
let _tempoInicio = 0;
let _questaoAtual = null;
let _overlay = null;

// ─── Helpers ─────────────────────────────────────────────────
function _getHeaders() {
  const token = localStorage.getItem('auth_token');
  const h = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

function _diffIcon(dificuldade) {
  if (dificuldade === 'Fácil') return '🟢';
  if (dificuldade === 'Difícil') return '🔴';
  return '🟡';
}

function _zonaEmoji(zona) {
  if (zona === 'flow') return '🎯';
  if (zona === 'conforto') return '😎';
  if (zona === 'abaixo') return '📉';
  return '🔄'; // aquecimento
}

function _zonaLabel(zona) {
  if (zona === 'flow') return 'Zona de Flow';
  if (zona === 'conforto') return 'Zona de Conforto';
  if (zona === 'abaixo') return 'Abaixo do Flow';
  return 'Aquecendo';
}

function _formatTime(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

function _thetaToNivel(theta) {
  if (theta <= -1.5) return 'Iniciante';
  if (theta <= -0.5) return 'Básico';
  if (theta <= 0.5) return 'Intermediário';
  if (theta <= 1.5) return 'Avançado';
  return 'Expert';
}

// ─── CSS (injected once) ─────────────────────────────────────
let _cssInjected = false;
function _injectCSS() {
  if (_cssInjected) return;
  _cssInjected = true;
  const style = document.createElement('style');
  style.id = 'cat-session-css';
  style.textContent = `
    .cat-overlay {
      position: fixed;
      inset: 0;
      z-index: 9999;
      background: var(--bg, #1e1e2e);
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      animation: catFadeIn .25s ease;
    }
    @keyframes catFadeIn {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* Header */
    .cat-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      background: var(--bg-surface, #313244);
      border-bottom: 1px solid var(--border, #45475a);
      flex-wrap: wrap;
      gap: 8px;
    }
    .cat-header__left {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .cat-header__materia {
      font-weight: 700;
      font-size: .95rem;
      color: var(--text, #cdd6f4);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 160px;
    }
    .cat-header__progress-text {
      font-size: .82rem;
      color: var(--text-sub, #bac2de);
    }
    .cat-header__right {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .cat-header__timer {
      font-family: monospace;
      font-size: .9rem;
      color: var(--yellow, #f9e2af);
    }
    .cat-header__zona {
      font-size: .78rem;
      padding: 2px 8px;
      border-radius: var(--radius-sm, 6px);
      background: var(--bg-elevated, #45475a);
      color: var(--text-sub, #bac2de);
    }
    .cat-header__zona[data-zona="flow"] {
      background: color-mix(in srgb, var(--green) 20%, transparent);
      color: var(--green, #a6e3a1);
    }
    .cat-close-btn {
      background: none;
      border: none;
      color: var(--text-muted, #6c7086);
      font-size: 1.4rem;
      cursor: pointer;
      padding: 4px;
      line-height: 1;
    }
    .cat-close-btn:hover { color: var(--red, #f38ba8); }

    /* Progress bar */
    .cat-progress-bar {
      height: 4px;
      background: var(--bg-elevated, #45475a);
      width: 100%;
    }
    .cat-progress-bar__fill {
      height: 100%;
      background: var(--accent, #cba6f7);
      transition: width .3s ease;
    }

    /* Body */
    .cat-body {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px 16px;
      max-width: 720px;
      margin: 0 auto;
      width: 100%;
    }
    .cat-enunciado {
      font-size: 1.05rem;
      line-height: 1.6;
      color: var(--text, #cdd6f4);
      margin-bottom: 24px;
      width: 100%;
      white-space: pre-wrap;
    }
    .cat-alternativas {
      width: 100%;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .cat-alt-btn {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 14px 16px;
      border-radius: var(--radius-md, 8px);
      border: 1.5px solid var(--border, #45475a);
      background: var(--bg-surface, #313244);
      color: var(--text, #cdd6f4);
      cursor: pointer;
      font-size: .95rem;
      text-align: left;
      line-height: 1.5;
      transition: border-color .15s, background .15s;
    }
    .cat-alt-btn:hover {
      border-color: var(--accent, #cba6f7);
      background: var(--bg-elevated, #45475a);
    }
    .cat-alt-btn.selected {
      border-color: var(--accent, #cba6f7);
      background: color-mix(in srgb, var(--accent) 12%, var(--bg-surface));
    }
    .cat-alt-btn.correct {
      border-color: var(--green, #a6e3a1);
      background: color-mix(in srgb, var(--green) 12%, var(--bg-surface));
    }
    .cat-alt-btn.wrong {
      border-color: var(--red, #f38ba8);
      background: color-mix(in srgb, var(--red) 12%, var(--bg-surface));
    }
    .cat-alt-btn[disabled] { pointer-events: none; opacity: .7; }
    .cat-alt-letter {
      font-weight: 700;
      min-width: 22px;
      color: var(--accent, #cba6f7);
    }

    /* Feedback */
    .cat-feedback {
      margin-top: 20px;
      padding: 12px 16px;
      border-radius: var(--radius-md, 8px);
      font-size: .9rem;
      width: 100%;
      text-align: center;
      animation: catFadeIn .2s ease;
    }
    .cat-feedback.correct {
      background: color-mix(in srgb, var(--green) 15%, var(--bg-surface));
      color: var(--green, #a6e3a1);
    }
    .cat-feedback.wrong {
      background: color-mix(in srgb, var(--red) 15%, var(--bg-surface));
      color: var(--red, #f38ba8);
    }
    .cat-next-btn {
      margin-top: 16px;
      padding: 10px 28px;
      border: none;
      border-radius: var(--radius-md, 8px);
      background: var(--accent, #cba6f7);
      color: var(--bg, #1e1e2e);
      font-weight: 700;
      font-size: .95rem;
      cursor: pointer;
      transition: opacity .15s;
    }
    .cat-next-btn:hover { opacity: .85; }

    /* Result card */
    .cat-result {
      width: 100%;
      max-width: 520px;
      margin: 0 auto;
      text-align: center;
    }
    .cat-result__title {
      font-size: 1.4rem;
      font-weight: 700;
      margin-bottom: 8px;
      color: var(--text, #cdd6f4);
    }
    .cat-result__subtitle {
      font-size: .9rem;
      color: var(--text-sub, #bac2de);
      margin-bottom: 24px;
    }
    .cat-result__stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }
    .cat-result__stat {
      background: var(--bg-surface, #313244);
      border-radius: var(--radius-md, 8px);
      padding: 16px 12px;
    }
    .cat-result__stat-label {
      font-size: .75rem;
      color: var(--text-muted, #6c7086);
      text-transform: uppercase;
      letter-spacing: .5px;
      margin-bottom: 4px;
    }
    .cat-result__stat-value {
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--text, #cdd6f4);
    }
    .cat-result__stat-value.green { color: var(--green, #a6e3a1); }
    .cat-result__stat-value.yellow { color: var(--yellow, #f9e2af); }
    .cat-result__stat-value.red { color: var(--red, #f38ba8); }
    .cat-result__stat-value.accent { color: var(--accent, #cba6f7); }
    .cat-result__sugestao {
      background: var(--bg-surface, #313244);
      border-radius: var(--radius-md, 8px);
      padding: 16px;
      font-size: .9rem;
      color: var(--text-sub, #bac2de);
      margin-bottom: 20px;
    }
    .cat-result__evolucao {
      display: flex;
      align-items: flex-end;
      gap: 3px;
      height: 60px;
      justify-content: center;
      margin-bottom: 20px;
    }
    .cat-result__evo-bar {
      width: 8px;
      border-radius: 3px;
      min-height: 4px;
      transition: height .2s;
    }
    .cat-result__close-btn {
      padding: 10px 32px;
      border: none;
      border-radius: var(--radius-md, 8px);
      background: var(--accent, #cba6f7);
      color: var(--bg, #1e1e2e);
      font-weight: 700;
      font-size: .95rem;
      cursor: pointer;
    }
    .cat-result__close-btn:hover { opacity: .85; }

    /* Loading spinner */
    .cat-loading {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      color: var(--text-sub, #bac2de);
    }
    .cat-spinner {
      width: 32px; height: 32px;
      border: 3px solid var(--border, #45475a);
      border-top-color: var(--accent, #cba6f7);
      border-radius: 50%;
      animation: catSpin .7s linear infinite;
    }
    @keyframes catSpin { to { transform: rotate(360deg); } }

    /* Difficulty badge */
    .cat-diff-badge {
      font-size: .78rem;
      padding: 2px 8px;
      border-radius: var(--radius-sm, 6px);
      background: var(--bg-elevated, #45475a);
    }

    /* Start card (for embedding in dashboard/questoes) */
    .cat-start-card {
      background: var(--bg-surface, #313244);
      border-radius: var(--radius-lg, 12px);
      padding: 20px;
      text-align: center;
      border: 1px solid var(--border, #45475a);
    }
    .cat-start-card__title {
      font-size: 1.1rem;
      font-weight: 700;
      color: var(--text, #cdd6f4);
      margin-bottom: 6px;
    }
    .cat-start-card__desc {
      font-size: .85rem;
      color: var(--text-sub, #bac2de);
      margin-bottom: 16px;
    }
    .cat-start-btn {
      padding: 10px 24px;
      border: none;
      border-radius: var(--radius-md, 8px);
      background: var(--accent, #cba6f7);
      color: var(--bg, #1e1e2e);
      font-weight: 700;
      font-size: .92rem;
      cursor: pointer;
      transition: opacity .15s;
    }
    .cat-start-btn:hover { opacity: .85; }

    /* Mobile adjustments */
    @media (max-width: 480px) {
      .cat-header { padding: 10px 12px; }
      .cat-header__materia { max-width: 100px; font-size: .85rem; }
      .cat-body { padding: 16px 12px; }
      .cat-enunciado { font-size: .95rem; }
      .cat-alt-btn { padding: 12px 14px; font-size: .88rem; }
      .cat-result__stats { grid-template-columns: repeat(2, 1fr); }
    }
  `;
  document.head.appendChild(style);
}

// ─── API Calls ───────────────────────────────────────────────
async function _apiIniciar(materia, totalQuestoes) {
  const res = await fetch('/api/sessao-adaptativa/iniciar', {
    method: 'POST',
    headers: _getHeaders(),
    body: JSON.stringify({ materia: materia || null, total_questoes: totalQuestoes }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Erro ao iniciar sessão');
  return res.json();
}

async function _apiProxima(sessionId) {
  const res = await fetch(`/api/sessao-adaptativa/${sessionId}/proxima`, {
    headers: _getHeaders(),
  });
  if (res.status === 404) return null; // sem mais questões
  if (!res.ok) throw new Error((await res.json()).detail || 'Erro ao buscar questão');
  return res.json();
}

async function _apiResponder(sessionId, questaoId, resposta, tempoMs) {
  const res = await fetch(`/api/sessao-adaptativa/${sessionId}/responder`, {
    method: 'POST',
    headers: _getHeaders(),
    body: JSON.stringify({ questao_id: questaoId, resposta, tempo_ms: tempoMs }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Erro ao responder');
  return res.json();
}

async function _apiResultado(sessionId) {
  const res = await fetch(`/api/sessao-adaptativa/${sessionId}/resultado`, {
    headers: _getHeaders(),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Erro ao buscar resultado');
  return res.json();
}

// ─── Timer ───────────────────────────────────────────────────
function _startTimer() {
  _tempoInicio = Date.now();
  const el = _overlay?.querySelector('.cat-header__timer');
  if (!el) return;
  el.textContent = '00:00';
  clearInterval(_timerInterval);
  _timerInterval = setInterval(() => {
    const elapsed = Date.now() - _tempoInicio;
    el.textContent = _formatTime(elapsed);
  }, 1000);
}

function _stopTimer() {
  clearInterval(_timerInterval);
  _timerInterval = null;
  return Date.now() - _tempoInicio;
}

// ─── Render Functions ────────────────────────────────────────
function _renderOverlay() {
  _injectCSS();
  const el = document.createElement('div');
  el.className = 'cat-overlay';
  el.innerHTML = `
    <div class="cat-header">
      <div class="cat-header__left">
        <span class="cat-header__materia"></span>
        <span class="cat-header__progress-text"></span>
        <span class="cat-diff-badge"></span>
      </div>
      <div class="cat-header__right">
        <span class="cat-header__zona"></span>
        <span class="cat-header__timer">00:00</span>
        <button class="cat-close-btn" title="Encerrar sessão">&times;</button>
      </div>
    </div>
    <div class="cat-progress-bar"><div class="cat-progress-bar__fill" style="width:0%"></div></div>
    <div class="cat-body">
      <div class="cat-loading"><div class="cat-spinner"></div><span>Preparando sessão...</span></div>
    </div>
  `;
  el.querySelector('.cat-close-btn').onclick = () => _finalizarSessao();
  document.body.appendChild(el);
  return el;
}

function _updateHeader(data) {
  if (!_overlay) return;
  const matEl = _overlay.querySelector('.cat-header__materia');
  const progEl = _overlay.querySelector('.cat-header__progress-text');
  const diffEl = _overlay.querySelector('.cat-diff-badge');
  const zonaEl = _overlay.querySelector('.cat-header__zona');
  const fillEl = _overlay.querySelector('.cat-progress-bar__fill');

  matEl.textContent = _materia || 'Geral';
  progEl.textContent = `${_progresso + 1}/${_totalQuestoes}`;

  if (data?.questao?.dificuldade) {
    diffEl.textContent = `${_diffIcon(data.questao.dificuldade)} ${data.questao.dificuldade}`;
  }

  const zona = data?.zona_flow || 'aquecimento';
  zonaEl.textContent = `${_zonaEmoji(zona)} ${_zonaLabel(zona)}`;
  zonaEl.setAttribute('data-zona', zona);

  const pct = Math.min(100, (_progresso / _totalQuestoes) * 100);
  fillEl.style.width = `${pct}%`;
}

function _renderQuestao(data) {
  const body = _overlay.querySelector('.cat-body');
  const q = data.questao;

  const alternativas = [
    { letter: 'A', text: q.alternativa_a },
    { letter: 'B', text: q.alternativa_b },
    { letter: 'C', text: q.alternativa_c },
    { letter: 'D', text: q.alternativa_d },
  ];
  if (q.alternativa_e) {
    alternativas.push({ letter: 'E', text: q.alternativa_e });
  }

  body.innerHTML = `
    <div class="cat-enunciado">${_escapeHtml(q.enunciado)}</div>
    <div class="cat-alternativas">
      ${alternativas.map(a => `
        <button class="cat-alt-btn" data-letter="${a.letter}">
          <span class="cat-alt-letter">${a.letter})</span>
          <span>${_escapeHtml(a.text)}</span>
        </button>
      `).join('')}
    </div>
  `;

  // Bind click
  body.querySelectorAll('.cat-alt-btn').forEach(btn => {
    btn.onclick = () => _selecionarResposta(btn.dataset.letter);
  });
}

function _escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function _selecionarResposta(letter) {
  const btns = _overlay.querySelectorAll('.cat-alt-btn');
  btns.forEach(b => {
    b.setAttribute('disabled', '');
    if (b.dataset.letter === letter) b.classList.add('selected');
  });

  const tempoMs = _stopTimer();

  try {
    const res = await _apiResponder(_sessionId, _questaoAtual.questao.id, letter, tempoMs);

    // Highlight correct/wrong
    btns.forEach(b => {
      if (b.dataset.letter === res.resposta_correta) b.classList.add('correct');
      if (b.dataset.letter === letter && !res.acertou) b.classList.add('wrong');
    });

    // Show feedback
    const body = _overlay.querySelector('.cat-body');
    const fbDiv = document.createElement('div');
    fbDiv.className = `cat-feedback ${res.acertou ? 'correct' : 'wrong'}`;
    fbDiv.textContent = res.feedback;
    body.appendChild(fbDiv);

    _progresso = res.progresso;

    // Update zona
    const zonaEl = _overlay.querySelector('.cat-header__zona');
    zonaEl.textContent = `${_zonaEmoji(res.zona_flow)} ${_zonaLabel(res.zona_flow)}`;
    zonaEl.setAttribute('data-zona', res.zona_flow);

    // Update progress bar
    const fillEl = _overlay.querySelector('.cat-progress-bar__fill');
    const pct = Math.min(100, (_progresso / _totalQuestoes) * 100);
    fillEl.style.width = `${pct}%`;

    // Check if session complete
    if (_progresso >= _totalQuestoes) {
      setTimeout(() => _finalizarSessao(), 1500);
      return;
    }

    // Next button
    const nextBtn = document.createElement('button');
    nextBtn.className = 'cat-next-btn';
    nextBtn.textContent = 'Próxima →';
    nextBtn.onclick = () => _carregarProxima();
    body.appendChild(nextBtn);

  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function _carregarProxima() {
  const body = _overlay.querySelector('.cat-body');
  body.innerHTML = '<div class="cat-loading"><div class="cat-spinner"></div><span>Carregando questão...</span></div>';

  try {
    const data = await _apiProxima(_sessionId);

    if (!data) {
      // sem mais questões
      await _finalizarSessao();
      return;
    }

    _questaoAtual = data;
    _updateHeader(data);
    _renderQuestao(data);
    _startTimer();

  } catch (err) {
    showToast(err.message, 'error');
    await _finalizarSessao();
  }
}

async function _finalizarSessao() {
  _stopTimer();
  const body = _overlay.querySelector('.cat-body');
  body.innerHTML = '<div class="cat-loading"><div class="cat-spinner"></div><span>Calculando resultado...</span></div>';

  try {
    const res = await _apiResultado(_sessionId);
    _renderResultado(res);
  } catch (err) {
    showToast(err.message, 'error');
    _fecharOverlay();
  }
}

function _renderResultado(data) {
  const body = _overlay.querySelector('.cat-body');

  // Determine color for pct
  let pctClass = 'red';
  if (data.pct >= 65) pctClass = 'green';
  else if (data.pct >= 50) pctClass = 'yellow';

  // Mini evolucao chart
  const evoHtml = data.evolucao.map(e => {
    const h = Math.max(6, ((e.theta + 3) / 6) * 56); // normalize theta [-3,3] to [6,56]px
    const color = e.acertou ? 'var(--green, #a6e3a1)' : 'var(--red, #f38ba8)';
    return `<div class="cat-result__evo-bar" style="height:${h}px;background:${color}" title="Q${e.questao_num}: θ=${e.theta}"></div>`;
  }).join('');

  body.innerHTML = `
    <div class="cat-result">
      <div class="cat-result__title">Sessão Finalizada! 🎉</div>
      <div class="cat-result__subtitle">${data.materia || 'Geral'} — ${data.total} questões</div>
      <div class="cat-result__evolucao">${evoHtml}</div>
      <div class="cat-result__stats">
        <div class="cat-result__stat">
          <div class="cat-result__stat-label">Acertos</div>
          <div class="cat-result__stat-value ${pctClass}">${data.pct}%</div>
        </div>
        <div class="cat-result__stat">
          <div class="cat-result__stat-label">Questões</div>
          <div class="cat-result__stat-value">${data.acertos}/${data.total}</div>
        </div>
        <div class="cat-result__stat">
          <div class="cat-result__stat-label">Theta (θ)</div>
          <div class="cat-result__stat-value accent">${data.theta_final}</div>
        </div>
        <div class="cat-result__stat">
          <div class="cat-result__stat-label">Nível</div>
          <div class="cat-result__stat-value">${_thetaToNivel(data.theta_final)}</div>
        </div>
        <div class="cat-result__stat">
          <div class="cat-result__stat-label">Zona Predominante</div>
          <div class="cat-result__stat-value">${_zonaEmoji(data.zona_predominante)} ${_zonaLabel(data.zona_predominante)}</div>
        </div>
      </div>
      <div class="cat-result__sugestao">💡 ${_escapeHtml(data.sugestao_proxima_sessao)}</div>
      <button class="cat-result__close-btn">Fechar</button>
    </div>
  `;

  body.querySelector('.cat-result__close-btn').onclick = () => _fecharOverlay();

  // Hide header timer & progress since session is done
  const header = _overlay.querySelector('.cat-header__timer');
  if (header) header.style.display = 'none';
}

function _fecharOverlay() {
  _stopTimer();
  if (_overlay) {
    _overlay.remove();
    _overlay = null;
  }
  _sessionId = null;
  _questaoAtual = null;
}

// ─── Public API ──────────────────────────────────────────────

/**
 * Inicia uma sessão adaptativa (CAT).
 * @param {Object} opts
 * @param {string} [opts.materia] - Matéria para filtrar questões
 * @param {number} [opts.totalQuestoes=20] - Quantidade de questões
 */
export async function startCatSession(opts = {}) {
  const materia = opts.materia || '';
  const totalQuestoes = opts.totalQuestoes || 20;

  _materia = materia;
  _totalQuestoes = totalQuestoes;
  _progresso = 0;

  _overlay = _renderOverlay();

  try {
    const res = await _apiIniciar(materia, totalQuestoes);
    _sessionId = res.session_id;
    _materia = res.materia || materia;
    _totalQuestoes = res.total_questoes || totalQuestoes;

    showToast('Sessão adaptativa iniciada!', 'success');
    await _carregarProxima();

  } catch (err) {
    showToast(err.message, 'error');
    _fecharOverlay();
  }
}

/**
 * Mostra resultado de uma sessão anterior pelo ID.
 * @param {string} sessionId
 */
export async function showCatResult(sessionId) {
  _injectCSS();
  _overlay = _renderOverlay();
  _sessionId = sessionId;

  try {
    const res = await _apiResultado(sessionId);
    _materia = res.materia || '';
    _updateHeader({ zona_flow: res.zona_predominante, questao: { dificuldade: 'Médio' } });
    _renderResultado(res);
  } catch (err) {
    showToast(err.message, 'error');
    _fecharOverlay();
  }
}

/**
 * Renderiza o card/botão de iniciar sessão adaptativa em um container.
 * @param {HTMLElement} container - Elemento onde inserir o card
 * @param {Object} [opts] - Opções (materia, totalQuestoes)
 */
export function renderCatStartCard(container, opts = {}) {
  _injectCSS();
  const card = document.createElement('div');
  card.className = 'cat-start-card';
  const showTitle = opts.showTitle !== false;
  card.innerHTML = `
    ${showTitle ? '<div class="cat-start-card__title">🧠 Sessão Adaptativa (CAT)</div>' : ''}
    <div class="cat-start-card__desc">
      Questões que se adaptam ao seu nível em tempo real.
      Mantém você na zona de flow (65-80% de acerto).
    </div>
    <button class="cat-start-btn">▶ Iniciar Sessão Adaptativa</button>
  `;
  card.querySelector('.cat-start-btn').onclick = () => startCatSession(opts);
  container.appendChild(card);
  return card;
}

// ─── Window Exposure (inline onclick) ────────────────────────
window.startCatSession = startCatSession;
window.showCatResult = showCatResult;
