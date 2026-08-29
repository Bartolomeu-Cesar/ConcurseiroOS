// simulado-cronometrado.js — ES module extracted from simulado-cronometrado.html

import { confirmModal, alertModal, promptModal } from '../modules/utils.js';
import { toast } from '../modules/toast.js';

// ==================== STATE ====================
let examState = {
  id: null,
  questoes: [],
  respostas: {},     // questao_id -> letra
  tempos: {},        // questao_id -> tempo_seg acumulado
  flags: new Set(),  // questao_ids marcadas para revisão
  currentIndex: 0,
  startTime: null,
  questionStartTime: null,
  timerInterval: null,
  heartbeatInterval: null,
  tempoTotalMin: 240,
};

// ==================== CONFIG ====================
async function loadMaterias() {
  try {
    const materias = await fetch('/api/questoes/materias').then(r => r.json());
    const grid = document.getElementById('materias-grid');
    if (materias.length === 0) {
      grid.innerHTML = '<span style="color:var(--crono-text-sub);font-size:0.8rem;">Nenhuma matéria disponível. Cadastre questões primeiro.</span>';
      return;
    }
    grid.innerHTML = materias.map(m => `
      <label>
        <input type="checkbox" class="cfg-mat-cb" value="${m}" checked>
        ${m}
      </label>
    `).join('');
  } catch (e) {
    console.error('Erro ao carregar matérias:', e);
  }
}

window.toggleAllMaterias = function(checked) {
  document.querySelectorAll('.cfg-mat-cb').forEach(cb => cb.checked = checked);
};

function getSelectedMaterias() {
  const all = document.querySelectorAll('.cfg-mat-cb');
  const checked = [...document.querySelectorAll('.cfg-mat-cb:checked')];
  // Se todas selecionadas, retornar vazio (= todas)
  if (checked.length === all.length) return [];
  return checked.map(cb => cb.value);
}

// ==================== START EXAM ====================
window.iniciarSimulado = async function() {
  const titulo = document.getElementById('cfg-titulo').value.trim() || `Simulado Cronometrado ${new Date().toLocaleDateString('pt-BR')}`;
  const tempo = parseInt(document.getElementById('cfg-tempo').value);
  const questoes = parseInt(document.getElementById('cfg-questoes').value);
  const facil = parseInt(document.getElementById('cfg-facil').value) || 0;
  const medio = parseInt(document.getElementById('cfg-medio').value) || 0;
  const dificil = parseInt(document.getElementById('cfg-dificil').value) || 0;
  const materias = getSelectedMaterias();

  const body = {
    titulo,
    tempo_total_min: tempo,
    questoes_total: questoes,
    materias,
    dificuldade_mix: { facil, medio, dificil },
  };

  try {
    const res = await fetch('/api/simulados/cronometrado', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json();
      toast('Erro: ' + (err.detail || 'Não foi possível criar o simulado'), 'error');
      return;
    }

    const data = await res.json();
    startExam(data);
  } catch (e) {
    toast('Erro de conexão: ' + e.message, 'error');
  }
};

function startExam(data) {
  examState.id = data.id;
  examState.questoes = data.questoes;
  examState.respostas = {};
  examState.tempos = {};
  examState.flags = new Set();
  examState.currentIndex = 0;
  examState.startTime = Date.now();
  examState.questionStartTime = Date.now();
  examState.tempoTotalMin = data.tempo_total_min;

  // Hide config, show exam
  document.getElementById('crono-config').style.display = 'none';
  document.getElementById('crono-exam').classList.add('active');
  document.getElementById('crono-results').classList.remove('active');

  // Setup timer
  document.getElementById('exam-total-num').textContent = data.total_questoes;
  clearInterval(examState.timerInterval);
  examState.timerInterval = setInterval(updateTimer, 1000);

  // Heartbeat: registra o tempo parcial periodicamente (para simulados
  // abandonados/parciais) e ao sair da página. Sem dupla contagem (delta no backend).
  _startHeartbeat();

  // Build navigator grid
  buildNavGrid();

  // Show first question
  showQuestion(0);
}

// ==================== HEARTBEAT (tempo parcial / abandono) ====================
function _elapsedSeg() {
  return examState.startTime ? Math.floor((Date.now() - examState.startTime) / 1000) : 0;
}

function _sendHeartbeat(useBeacon = false) {
  if (!examState.id) return;
  const tempo = _elapsedSeg();
  if (tempo <= 0) return;
  const url = `/api/simulados/cronometrado/${examState.id}/heartbeat`;
  const payload = JSON.stringify({ tempo_total_seg: tempo });
  // Ao sair da página, sendBeacon é mais confiável (sobrevive ao unload).
  if (useBeacon && navigator.sendBeacon) {
    try {
      navigator.sendBeacon(url, new Blob([payload], { type: 'application/json' }));
      return;
    } catch (e) { /* cai no fetch abaixo */ }
  }
  // fetch normal (o auth-interceptor injeta o token). keepalive ajuda no unload.
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
    keepalive: true,
  }).catch(() => {});
}

function _onVisibility() {
  if (document.visibilityState === 'hidden') _sendHeartbeat(true);
}
function _onPageHide() { _sendHeartbeat(true); }

function _startHeartbeat() {
  _stopHeartbeat();
  // Registro incremental a cada 30s enquanto a prova está ativa
  examState.heartbeatInterval = setInterval(() => _sendHeartbeat(false), 30000);
  document.addEventListener('visibilitychange', _onVisibility);
  window.addEventListener('pagehide', _onPageHide);
}

function _stopHeartbeat() {
  if (examState.heartbeatInterval) {
    clearInterval(examState.heartbeatInterval);
    examState.heartbeatInterval = null;
  }
  document.removeEventListener('visibilitychange', _onVisibility);
  window.removeEventListener('pagehide', _onPageHide);
}

// ==================== TIMER ====================
function updateTimer() {
  const elapsed = Math.floor((Date.now() - examState.startTime) / 1000);
  const totalSec = examState.tempoTotalMin * 60;
  const remaining = Math.max(0, totalSec - elapsed);

  const h = String(Math.floor(remaining / 3600)).padStart(2, '0');
  const m = String(Math.floor((remaining % 3600) / 60)).padStart(2, '0');
  const s = String(remaining % 60).padStart(2, '0');

  const el = document.getElementById('exam-timer');
  el.textContent = `${h}:${m}:${s}`;

  // Color based on time
  el.className = 'timer-display';
  if (remaining < 300) el.classList.add('danger');      // < 5min
  else if (remaining < 600) el.classList.add('warning'); // < 10min

  if (remaining <= 0) {
    finalizarProva();
  }
}

// ==================== NAVIGATOR ====================
function buildNavGrid() {
  const grid = document.getElementById('nav-grid');
  grid.innerHTML = examState.questoes.map((q, i) =>
    `<button class="nav-cell" data-index="${i}" onclick="goToQuestion(${i})">${i + 1}</button>`
  ).join('');
  updateNavGrid();
}

function updateNavGrid() {
  const cells = document.querySelectorAll('.nav-cell');
  cells.forEach((cell, i) => {
    const q = examState.questoes[i];
    cell.className = 'nav-cell';
    if (i === examState.currentIndex) cell.classList.add('current');
    else if (examState.respostas[q.id]) cell.classList.add('answered');
    if (examState.flags.has(q.id)) cell.classList.add('flagged');
  });

  // Update answered count
  const answered = Object.keys(examState.respostas).length;
  document.getElementById('exam-answered-count').textContent = answered;
}

// ==================== QUESTION DISPLAY ====================
function showQuestion(index) {
  // Save time for previous question
  saveQuestionTime();

  examState.currentIndex = index;
  examState.questionStartTime = Date.now();

  const q = examState.questoes[index];
  const selected = examState.respostas[q.id] || '';
  const flagged = examState.flags.has(q.id);

  document.getElementById('exam-current-num').textContent = index + 1;

  const html = `
    <div class="exam-q-header">
      <span class="exam-q-num">#${q.num}</span>
      <span class="exam-q-materia">${q.materia || 'Geral'}</span>
      <button class="exam-q-flag ${flagged ? 'active' : ''}" onclick="toggleFlag(${q.id})" title="Marcar para revisão">
        🚩 ${flagged ? 'Marcada' : 'Revisar'}
      </button>
    </div>
    <div class="exam-enunciado">${q.enunciado}</div>
    <div class="exam-alternativas">
      ${q.alternativas.map(a => `
        <div class="exam-alt ${selected === a.letra ? 'selected' : ''}" onclick="selectAnswer(${q.id}, '${a.letra}', this)">
          <span class="exam-alt-letter">${a.letra})</span>
          <span class="exam-alt-text">${a.texto}</span>
        </div>
      `).join('')}
    </div>
  `;
  document.getElementById('exam-question').innerHTML = html;

  // Update nav buttons
  document.getElementById('btn-exam-prev').disabled = index === 0;
  const nextBtn = document.getElementById('btn-exam-next');
  nextBtn.textContent = index === examState.questoes.length - 1 ? 'Última ✓' : 'Próxima →';

  updateNavGrid();
}

function saveQuestionTime() {
  if (examState.questionStartTime && examState.questoes[examState.currentIndex]) {
    const q = examState.questoes[examState.currentIndex];
    const elapsed = Math.floor((Date.now() - examState.questionStartTime) / 1000);
    examState.tempos[q.id] = (examState.tempos[q.id] || 0) + elapsed;
  }
}

window.selectAnswer = function(questaoId, letra, el) {
  examState.respostas[questaoId] = letra;
  // Update UI
  document.querySelectorAll('.exam-alt').forEach(a => a.classList.remove('selected'));
  el.classList.add('selected');
  updateNavGrid();
};

window.toggleFlag = function(questaoId) {
  if (examState.flags.has(questaoId)) {
    examState.flags.delete(questaoId);
  } else {
    examState.flags.add(questaoId);
  }
  // Re-render current question to update flag button
  showQuestion(examState.currentIndex);
};

window.goToQuestion = function(index) {
  showQuestion(index);
};

window.examNext = function() {
  if (examState.currentIndex < examState.questoes.length - 1) {
    showQuestion(examState.currentIndex + 1);
  }
};

window.examPrev = function() {
  if (examState.currentIndex > 0) {
    showQuestion(examState.currentIndex - 1);
  }
};

// ==================== SUBMIT ====================
window.showSubmitModal = function() {
  const answered = Object.keys(examState.respostas).length;
  const total = examState.questoes.length;
  const flagged = examState.flags.size;

  let text = `Você respondeu <strong>${answered}</strong> de <strong>${total}</strong> questões.`;
  if (total - answered > 0) text += `<br><span style="color:var(--crono-yellow);">⚠️ ${total - answered} questão(ões) em branco.</span>`;
  if (flagged > 0) text += `<br><span style="color:var(--crono-orange);">🚩 ${flagged} questão(ões) marcada(s) para revisão.</span>`;
  text += '<br><br>Deseja entregar a prova?';

  document.getElementById('submit-modal-text').innerHTML = text;
  document.getElementById('submit-modal').classList.add('active');
};

window.hideSubmitModal = function() {
  document.getElementById('submit-modal').classList.remove('active');
};

window.finalizarProva = finalizarProva;

async function finalizarProva() {
  window.hideSubmitModal();
  clearInterval(examState.timerInterval);
  _stopHeartbeat();

  // Save time for current question
  saveQuestionTime();

  const tempoTotal = Math.floor((Date.now() - examState.startTime) / 1000);

  // Build respostas array
  const respostas = examState.questoes.map(q => ({
    questao_id: q.id,
    resposta: examState.respostas[q.id] || '',
    tempo_seg: examState.tempos[q.id] || 0,
  }));

  try {
    const res = await fetch(`/api/simulados/cronometrado/${examState.id}/finalizar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ respostas, tempo_total_seg: tempoTotal }),
    });

    if (!res.ok) {
      const err = await res.json();
      toast('Erro ao finalizar: ' + (err.detail || 'desconhecido'), 'error');
      return;
    }

    const data = await res.json();
    showResults(data);
  } catch (e) {
    toast('Erro de conexão: ' + e.message, 'error');
  }
}

// ==================== RESULTS ====================
function showResults(data) {
  document.getElementById('crono-exam').classList.remove('active');
  const resultsDiv = document.getElementById('crono-results');
  resultsDiv.classList.add('active');

  const tempoFormatado = formatTempo(data.tempo_total_seg);
  const tempoMedioFormatado = data.tempo_medio_por_questao > 0 ? `${Math.floor(data.tempo_medio_por_questao / 60)}m${Math.round(data.tempo_medio_por_questao % 60)}s` : '--';

  // Verdict
  let verdictHtml = '';
  if (data.aprovado_estimado !== null && data.aprovado_estimado !== undefined) {
    const cls = data.aprovado_estimado ? 'aprovado' : 'reprovado';
    const icon = data.aprovado_estimado ? '🎉' : '📚';
    const msg = data.aprovado_estimado
      ? 'Parabéns! Sua nota supera a nota de corte histórica!'
      : `Continue estudando! Nota de corte: ${data.nota_corte}%`;
    verdictHtml = `
      <div class="results-verdict ${cls}">
        <h3>${icon} ${data.aprovado_estimado ? 'APROVADO (estimativa)' : 'ABAIXO DA NOTA DE CORTE'}</h3>
        <p>${msg}</p>
      </div>
    `;
  }

  // Matérias bars
  const materiasHtml = data.por_materia.map(m => {
    const pct = m.total > 0 ? Math.round((m.acertos / m.total) * 100) : 0;
    const color = pct >= 70 ? 'var(--crono-green)' : pct >= 50 ? 'var(--crono-yellow)' : 'var(--crono-red)';
    return `
      <div class="materia-bar">
        <span class="mat-name" title="${m.materia}">${m.materia}</span>
        <div class="mat-bar-bg">
          <div class="mat-bar-fill" style="width:${pct}%;background:${color};"></div>
        </div>
        <span class="mat-score" style="color:${color};">${m.acertos}/${m.total}</span>
      </div>
    `;
  }).join('');

  resultsDiv.innerHTML = `
    <div class="results-header">
      <h2>📊 Resultado do Simulado</h2>
      <p class="subtitle">Tempo total: ${tempoFormatado}</p>
    </div>

    ${verdictHtml}

    <div class="results-grid">
      <div class="result-card">
        <div class="result-val" style="color:var(--crono-accent);">${data.nota_bruta}%</div>
        <div class="result-lbl">Nota Bruta</div>
      </div>
      <div class="result-card">
        <div class="result-val" style="color:var(--crono-blue);">${data.nota_tri}%</div>
        <div class="result-lbl">Nota TRI (est.)</div>
      </div>
      <div class="result-card">
        <div class="result-val" style="color:var(--crono-green);">${data.total_acertos}</div>
        <div class="result-lbl">Acertos</div>
      </div>
      <div class="result-card">
        <div class="result-val" style="color:var(--crono-red);">${data.total_erros}</div>
        <div class="result-lbl">Erros</div>
      </div>
      <div class="result-card">
        <div class="result-val" style="color:var(--crono-text-sub);">${data.total_em_branco}</div>
        <div class="result-lbl">Em Branco</div>
      </div>
      <div class="result-card">
        <div class="result-val" style="color:var(--crono-orange);">${tempoMedioFormatado}</div>
        <div class="result-lbl">Tempo Médio/Questão</div>
      </div>
    </div>

    <div class="results-materias">
      <h3>📚 Desempenho por Matéria</h3>
      ${materiasHtml || '<p style="color:var(--crono-text-sub);font-size:0.85rem;">Sem dados por matéria.</p>'}
    </div>

    <div class="radar-container">
      <canvas id="radar-chart" width="400" height="400"></canvas>
    </div>

    <div class="results-actions">
      <a href="/questoes.html" class="btn" style="background:var(--crono-elevated);color:var(--crono-text);text-decoration:none;">← Questões</a>
      <button class="btn" style="background:var(--crono-accent);color:var(--crono-bg);" onclick="novoSimulado()">🔄 Novo Simulado</button>
      <button class="btn" style="background:var(--crono-blue);color:#fff;" onclick="verGabarito()">📋 Ver Gabarito</button>
    </div>
  `;

  // Draw radar chart
  if (data.por_materia.length >= 3) {
    drawRadarChart(data.por_materia);
  }
}

function formatTempo(seg) {
  const h = Math.floor(seg / 3600);
  const m = Math.floor((seg % 3600) / 60);
  const s = seg % 60;
  if (h > 0) return `${h}h ${m}min`;
  return `${m}min ${s}s`;
}

window.novoSimulado = function() {
  document.getElementById('crono-config').style.display = 'block';
  document.getElementById('crono-results').classList.remove('active');
};

window.verGabarito = async function() {
  try {
    const res = await fetch(`/api/simulados/cronometrado/${examState.id}`);
    const data = await res.json();
    showGabarito(data.questoes);
  } catch (e) {
    toast('Erro ao carregar gabarito: ' + e.message, 'error');
  }
};

function showGabarito(questoes) {
  const resultsDiv = document.getElementById('crono-results');
  let html = `
    <div class="results-header">
      <h2>📋 Gabarito Completo</h2>
      <button class="btn" style="background:var(--crono-elevated);color:var(--crono-text);padding:8px 16px;border:none;border-radius:8px;cursor:pointer;margin-top:10px;" onclick="history.back()">← Voltar ao Resultado</button>
    </div>
  `;

  questoes.forEach((q, i) => {
    const respondeu = q.resposta_usuario || '—';
    const correta = q.resposta_correta;
    const acertou = q.acertou === 1;
    const icon = q.resposta_usuario ? (acertou ? '✅' : '❌') : '⬜';
    const borderColor = q.resposta_usuario ? (acertou ? 'var(--crono-green)' : 'var(--crono-red)') : 'var(--crono-border)';

    html += `
      <div style="background:var(--crono-surface);border-radius:10px;padding:16px;margin-bottom:10px;border-left:4px solid ${borderColor};">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
          <span style="font-weight:700;color:var(--crono-accent);">#${q.num}</span>
          <span style="font-size:0.78rem;background:var(--crono-elevated);padding:2px 8px;border-radius:10px;color:var(--crono-text-sub);">${q.materia}</span>
          <span style="margin-left:auto;font-size:0.85rem;">${icon}</span>
        </div>
        <p style="font-size:0.88rem;line-height:1.5;margin-bottom:8px;color:var(--crono-text);">${q.enunciado.substring(0, 200)}${q.enunciado.length > 200 ? '...' : ''}</p>
        <div style="font-size:0.82rem;display:flex;gap:14px;color:var(--crono-text-sub);">
          <span>Sua: <strong style="color:${acertou ? 'var(--crono-green)' : 'var(--crono-red)'};">${respondeu}</strong></span>
          <span>Correta: <strong style="color:var(--crono-green);">${correta}</strong></span>
        </div>
        ${q.explicacao ? `<p style="font-size:0.8rem;color:var(--crono-text-sub);margin-top:8px;padding-top:8px;border-top:1px solid var(--crono-border);"><em>💡 ${q.explicacao}</em></p>` : ''}
      </div>
    `;
  });

  html += `
    <div class="results-actions" style="margin-top:20px;">
      <button class="btn" style="background:var(--crono-accent);color:var(--crono-bg);padding:12px 24px;border:none;border-radius:8px;cursor:pointer;" onclick="novoSimulado()">🔄 Novo Simulado</button>
    </div>
  `;

  resultsDiv.innerHTML = html;
}

// ==================== RADAR CHART (Canvas) ====================
function drawRadarChart(materias) {
  const canvas = document.getElementById('radar-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  const cx = W / 2;
  const cy = H / 2;
  const radius = Math.min(cx, cy) - 60;
  const n = materias.length;
  const angleStep = (2 * Math.PI) / n;

  ctx.clearRect(0, 0, W, H);

  // Draw grid circles
  ctx.strokeStyle = 'rgba(147,153,178,0.2)';
  ctx.lineWidth = 1;
  for (let level = 1; level <= 5; level++) {
    const r = (radius / 5) * level;
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const angle = -Math.PI / 2 + i * angleStep;
      const x = cx + r * Math.cos(angle);
      const y = cy + r * Math.sin(angle);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Draw axes
  ctx.strokeStyle = 'rgba(147,153,178,0.3)';
  for (let i = 0; i < n; i++) {
    const angle = -Math.PI / 2 + i * angleStep;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle));
    ctx.stroke();
  }

  // Draw data polygon
  const values = materias.map(m => m.total > 0 ? m.acertos / m.total : 0);
  ctx.beginPath();
  ctx.fillStyle = 'rgba(203,166,247,0.25)';
  ctx.strokeStyle = 'rgba(203,166,247,0.8)';
  ctx.lineWidth = 2;
  values.forEach((val, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const r = radius * val;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  // Draw dots and labels
  ctx.fillStyle = 'rgba(203,166,247,1)';
  values.forEach((val, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const r = radius * val;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, 2 * Math.PI);
    ctx.fill();
  });

  // Labels
  const isDark = !document.body.classList.contains('light-theme');
  ctx.fillStyle = isDark ? '#cdd6f4' : '#4c4f69';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'center';
  materias.forEach((m, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const labelR = radius + 30;
    const x = cx + labelR * Math.cos(angle);
    const y = cy + labelR * Math.sin(angle);

    // Truncate long names
    const name = m.materia.length > 14 ? m.materia.substring(0, 12) + '…' : m.materia;
    const pct = m.total > 0 ? Math.round((m.acertos / m.total) * 100) : 0;

    ctx.fillText(name, x, y);
    ctx.fillText(`${pct}%`, x, y + 13);
  });
}

// ==================== INIT ====================
loadMaterias();

// Default title with today's date
document.getElementById('cfg-titulo').value = `Simulado Cronometrado ${new Date().toLocaleDateString('pt-BR')}`;
