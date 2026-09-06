// caderno-erros.js — ES module extracted from caderno-erros.html
import { escapeJsString } from '/js/modules/utils.js';

const API_BASE = '';
let dadosCaderno = null;
let revisadasHoje = new Set();
let filtroMateria = '';
let _cardTimers = {}; // Tempo de início por questão

async function fetchCaderno() {
  try {
    const res = await fetch(`${API_BASE}/api/questoes/erros/caderno`);
    if (!res.ok) throw new Error('Erro ao carregar caderno');
    const raw = await res.json();
    // Handle both old format (array) and new format (object)
    if (Array.isArray(raw)) {
      dadosCaderno = { pendentes_hoje: raw, total_erros: raw.length, por_materia: {}, padroes_erro: [] };
    } else {
      dadosCaderno = raw;
    }
    renderAll();
  } catch (err) {
    document.getElementById('lista-revisao').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <p>Erro ao carregar caderno de erros: ${err.message}</p>
      </div>`;
  }
}

function renderAll() {
  if (!dadosCaderno) return;

  const { pendentes_hoje, total_erros, por_materia, padroes_erro } = dadosCaderno;

  // Badge & stats
  document.getElementById('total-badge').textContent = pendentes_hoje.length;
  document.getElementById('stat-total').textContent = total_erros;
  document.getElementById('stat-pendentes').textContent = pendentes_hoje.length;
  document.getElementById('stat-materias').textContent = Object.keys(por_materia).length;
  document.getElementById('stat-padroes').textContent = padroes_erro.length;

  // Progress
  updateProgress();

  // Matérias chips
  renderMateriasChips(por_materia);

  // Questões
  renderRevisao(pendentes_hoje);

  // Padrões
  renderPadroes(padroes_erro);
}

function updateProgress() {
  const total = dadosCaderno.pendentes_hoje.length;
  const done = revisadasHoje.size;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const section = document.getElementById('progress-section');
  section.style.display = total > 0 ? 'block' : 'none';

  const progressBar = document.getElementById('review-progress');
  if (progressBar) {
    progressBar.setAttribute('value', pct);
    progressBar.setAttribute('label', `Revisão — ${done}/${total} revisadas hoje`);
  }
}

function renderMateriasChips(por_materia) {
  const container = document.getElementById('materias-chips');
  const sorted = Object.entries(por_materia).sort((a, b) => b[1] - a[1]);

  let html = `<button class="materia-chip ${!filtroMateria ? 'active' : ''}" onclick="setFiltroMateria('')">Todas</button>`;
  for (const [mat, count] of sorted) {
    const active = filtroMateria === mat ? 'active' : '';
    html += `<button class="materia-chip ${active}" onclick="setFiltroMateria('${escapeJsString(mat)}')">${escapeAttr(mat)} (${count})</button>`;
  }
  container.innerHTML = html;
}

window.setFiltroMateria = function(mat) {
  filtroMateria = mat;
  renderAll();
};

function escapeAttr(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderRevisao(pendentes) {
  const container = document.getElementById('lista-revisao');
  let filtered = pendentes;

  if (filtroMateria) {
    filtered = filtered.filter(q => q.materia === filtroMateria);
  }

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🎉</div>
        <p>${filtroMateria ? 'Nenhuma revisão pendente nesta matéria!' : 'Nenhuma revisão pendente hoje! Volte amanhã.'}</p>
      </div>`;
    return;
  }

  let html = '';
  for (let idx = 0; idx < filtered.length; idx++) {
    const q = filtered[idx];
    const revisada = revisadasHoje.has(q.id);

    // Recall indicator
    const recall = Math.round((q.recall_estimado || 0) * 100);
    const recallColor = recall <= 30 ? 'var(--ce-red, #f38ba8)' : recall <= 60 ? 'var(--ce-yellow, #f9e2af)' : 'var(--ce-green, #a6e3a1)';
    const recallLabel = recall <= 30 ? '🔴 Esquecendo' : recall <= 60 ? '🟡 Frágil' : '🟢 Estável';

    // Intervalo label
    const intervalo = q.intervalo_atual || 1;
    const intervaloLabel = intervalo >= 30 ? `${Math.round(intervalo/30)}m` : `${intervalo}d`;

    // Revisões count
    const revisoes = q.revisoes_count || 0;

    // Enunciado (expandível)
    const enunciadoFull = q.enunciado || '';
    const enunciadoShort = enunciadoFull.length > 150 ? enunciadoFull.substring(0, 150) + '…' : enunciadoFull;
    const needsExpand = enunciadoFull.length > 150;

    // Montar alternativas
    const alternativas = [];
    for (const letra of ['a', 'b', 'c', 'd', 'e']) {
      const texto = q[`alternativa_${letra}`];
      if (texto) {
        alternativas.push({ letra: letra.toUpperCase(), texto });
      }
    }

    // Resposta errada e correta
    const respostaErrada = (q.resposta_usuario || '').toUpperCase();
    const respostaCorreta = (q.resposta_correta || '').toUpperCase();
    const isCertoErrado = !q.alternativa_c && !q.alternativa_d;
    const respostaErradaDisplay = !respostaErrada ? '' : isCertoErrado ? (respostaErrada === 'A' ? 'CERTO' : 'ERRADO') : respostaErrada;

    html += `
      <div class="revisao-card ${revisada ? 'revisao-card--done' : ''}" id="card-${q.id}">
        <div class="revisao-card__header">
          <div class="revisao-card__meta">
            <span class="revisao-card__materia">${escapeAttr(q.materia)}</span>
            <span class="revisao-card__badge" style="background:${recallColor}22;color:${recallColor};border:1px solid ${recallColor}44;">${recallLabel} ${recall}%</span>
          </div>
          <div class="revisao-card__stats">
            <span title="Intervalo atual">📅 ${intervaloLabel}</span>
            <span title="Revisões feitas">🔁 ${revisoes}x</span>
            <span class="revisao-card__num">${idx + 1}/${filtered.length}</span>
          </div>
        </div>

        <div class="revisao-card__body">
          <p class="revisao-card__enunciado" id="enunciado-${q.id}">${escapeAttr(enunciadoShort)}</p>
          ${needsExpand ? `<button class="revisao-card__expand" onclick="toggleEnunciado(${q.id}, this)" data-full="${escapeAttr(enunciadoFull)}">Ver completo ▾</button>` : ''}
        </div>

        <div class="revisao-card__hint">
          ${respostaErradaDisplay ? `<span>Da última vez você marcou <strong style="color:var(--ce-wrong);">${respostaErradaDisplay}</strong> — tente novamente:</span>` : `<span>Tente novamente:</span>`}
        </div>

        <div class="revisao-card__alternativas" id="alts-${q.id}">
          ${alternativas.map(a => `
            <button class="revisao-alt-btn"
                    onclick="selecionarAlternativa(${q.id}, '${a.letra}', '${respostaCorreta}', '${respostaErrada}')"
                    id="alt-${q.id}-${a.letra}"
                    ${revisada ? 'disabled' : ''}>
              <span class="revisao-alt-letra">${a.letra})</span>
              <span class="revisao-alt-texto">${escapeAttr(a.texto)}</span>
            </button>
          `).join('')}
        </div>

        <div class="revisao-card__feedback" id="feedback-${q.id}" style="display:none;"></div>

        ${revisada ? '<div class="revisao-card__done-overlay">✓ Revisada</div>' : ''}
      </div>`;
  }
  container.innerHTML = html;

  // Iniciar timers para tracking de tempo real por questão
  filtered.forEach(q => { if (!revisadasHoje.has(q.id)) _cardTimers[q.id] = Date.now(); });
}

window.toggleEnunciado = function(id, btn) {
  const el = document.getElementById(`enunciado-${id}`);
  const fullText = btn.dataset.full;
  if (el.dataset.expanded === 'true') {
    el.textContent = fullText.length > 150 ? fullText.substring(0, 150) + '…' : fullText;
    el.dataset.expanded = 'false';
    btn.textContent = 'Ver completo ▾';
  } else {
    el.textContent = fullText;
    el.dataset.expanded = 'true';
    btn.textContent = 'Recolher ▴';
  }
};

window.selecionarAlternativa = function(questaoId, letraSelecionada, correta, erradaAnterior) {
  if (revisadasHoje.has(questaoId)) return;

  const acertou = letraSelecionada === correta;

  // Desabilitar todos os botões e marcar correta/errada
  const container = document.getElementById(`alts-${questaoId}`);
  container.querySelectorAll('.revisao-alt-btn').forEach(btn => {
    btn.disabled = true;
    const letra = btn.id.split('-').pop();

    if (letra === correta) {
      btn.classList.add('revisao-alt-btn--correct');
    } else if (letra === letraSelecionada && !acertou) {
      btn.classList.add('revisao-alt-btn--wrong');
    }
  });

  // Mostrar feedback
  const feedback = document.getElementById(`feedback-${questaoId}`);
  feedback.style.display = 'block';

  if (acertou) {
    feedback.innerHTML = `
      <div class="revisao-feedback revisao-feedback--ok">
        <span class="revisao-feedback__msg">✅ Correto! Você corrigiu o erro anterior.</span>
        <button class="revisao-btn revisao-btn--ok" onclick="revisar(${questaoId}, true)">Próxima revisão →</button>
      </div>`;
  } else {
    const isCE = container.querySelectorAll('.revisao-alt-btn').length === 2;
    const letraDisplay = isCE ? (letraSelecionada === 'A' ? 'CERTO' : 'ERRADO') : letraSelecionada;
    const erradaDisplay = !erradaAnterior ? '' : isCE ? (erradaAnterior === 'A' ? 'CERTO' : 'ERRADO') : erradaAnterior;
    const mesmoErro = letraSelecionada === erradaAnterior;
    const msgExtra = mesmoErro
      ? '⚠️ Mesmo erro de antes — atenção redobrada nesse conceito!'
      : erradaDisplay ? `Você marcou ${letraDisplay}, antes marcou ${erradaDisplay}.` : `Você marcou ${letraDisplay}.`;
    const corretaDisplay = isCE ? (correta === 'A' ? 'CERTO' : 'ERRADO') : correta;
    feedback.innerHTML = `
      <div class="revisao-feedback revisao-feedback--errou">
        <div class="revisao-feedback__info">
          <span class="revisao-feedback__msg">❌ Errou novamente. Correta: <strong>${corretaDisplay}</strong></span>
          <span class="revisao-feedback__detalhe">${msgExtra}</span>
        </div>
        <button class="revisao-btn revisao-btn--errei" onclick="revisar(${questaoId}, false)">Entendi, avançar →</button>
      </div>`;
  }
};

function renderPadroes(padroes) {
  const container = document.getElementById('lista-padroes');

  let filtered = padroes;
  if (filtroMateria) {
    filtered = filtered.filter(p => p.materia === filtroMateria);
  }

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📊</div>
        <p>Nenhum padrão de erro identificado ainda. Continue praticando!</p>
      </div>`;
    return;
  }

  let html = '';
  for (const p of filtered) {
    html += `
      <div class="padrao-card">
        <div class="padrao-header">
          <span class="padrao-text">${escapeAttr(p.padrao)}</span>
          <span class="padrao-count">${p.count}x</span>
        </div>
        <div class="padrao-detail">
          ${escapeAttr(p.materia)} → ${escapeAttr(p.topico)} | Resposta errada frequente: "${escapeAttr(p.resposta_errada)}"
        </div>
      </div>`;
  }
  container.innerHTML = html;
}

window.revisar = async function(questaoId, acertou) {
  try {
    // Calcular tempo real gasto nesta questão
    const startTime = _cardTimers[questaoId];
    const tempoSegundos = startTime ? Math.round((Date.now() - startTime) / 1000) : 0;

    const res = await fetch(`${API_BASE}/api/questoes/erros/revisar/${questaoId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acertou, tempo_segundos: tempoSegundos })
    });
    if (!res.ok) throw new Error('Erro ao registrar revisão');
    const data = await res.json();

    revisadasHoje.add(questaoId);

    // Visual feedback no card
    const card = document.getElementById(`card-${questaoId}`);
    if (card) {
      card.classList.add('revisao-card--done');
      card.querySelectorAll('button').forEach(b => b.disabled = true);
      // Show result toast
      const msg = acertou
        ? `✅ Próxima revisão em ${data.novo_intervalo} dia${data.novo_intervalo > 1 ? 's' : ''}`
        : `🔄 Voltará amanhã para revisão`;
      showToast(msg);
    }

    updateProgress();
  } catch (err) {
    showToast('❌ Erro: ' + err.message);
  }
};

function truncate(text, max) {
  if (!text) return '';
  return text.length > max ? text.substring(0, max) + '...' : text;
}

function showToast(msg) {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; bottom: 96px; right: 24px;
    padding: 12px 20px; border-radius: 10px;
    background: var(--ce-card); color: var(--ce-text);
    font-size: 0.85rem; font-weight: 600;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    z-index: 99999; animation: fadeIn 0.3s ease;
  `;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ===== Error Analysis Stats =====

const MOTIVO_LABELS = {
  leitura_incompleta: '📖 Leitura incompleta',
  conceito_errado: '❌ Conceito errado',
  excecao_regra: '⚠️ Exceção da regra',
  pegadinha: '🪤 Pegadinha',
  chute: '🎲 Chutei',
  desatencao: '😵 Desatenção',
  tempo: '⏰ Faltou tempo'
};

const MOTIVO_COLORS = [
  'var(--ce-accent, #f38ba8)',
  'var(--ce-blue, #89b4fa)',
  'var(--ce-warning, #f9e2af)',
  'var(--ce-success, #a6e3a1)',
  'var(--ce-mauve, #cba6f7)',
  'var(--ce-wrong, #f38ba8)',
  'var(--ce-subtext, #a6adc8)'
];

async function loadErrorAnalysisStats() {
  try {
    const res = await fetch(`${API_BASE}/api/questoes/erros/analise/stats`);
    if (!res.ok) return;
    const data = await res.json();

    if (!data || data.total_analisados <= 0) return;

    const container = document.getElementById('error-analysis-stats');
    if (!container) return;

    const barsHtml = data.stats.map((item, idx) => {
      const label = MOTIVO_LABELS[item.motivo] || item.motivo;
      const color = MOTIVO_COLORS[idx % MOTIVO_COLORS.length];
      return `
        <div style="margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <span style="font-size:0.82rem;color:var(--ce-text);">${label}</span>
            <span style="font-size:0.75rem;color:var(--ce-subtext);font-weight:600;">${item.total} (${item.percentual.toFixed(1)}%)</span>
          </div>
          <div style="background:var(--ce-border);border-radius:6px;height:8px;overflow:hidden;">
            <div style="width:${item.percentual}%;height:100%;background:${color};border-radius:6px;transition:width 0.4s ease;"></div>
          </div>
        </div>`;
    }).join('');

    const dicaHtml = data.dica ? `
      <div style="margin-top:14px;padding:10px 14px;background:rgba(249,226,175,0.1);border:1px solid rgba(249,226,175,0.25);border-radius:8px;font-size:0.82rem;color:var(--ce-warning);line-height:1.5;">
        ${data.dica}
      </div>` : '';

    container.innerHTML = `
      <div style="background:var(--ce-card);border-radius:12px;padding:16px 20px;margin-bottom:24px;">
        <div style="font-size:1rem;font-weight:700;color:var(--ce-mauve);margin-bottom:14px;display:flex;align-items:center;gap:8px;">
          📋 Análise de Erros
          <span style="font-size:0.72rem;font-weight:600;color:var(--ce-subtext);margin-left:auto;">${data.total_analisados} analisados</span>
        </div>
        ${barsHtml}
        ${dicaHtml}
      </div>`;
  } catch (err) {
    // Silently fail — non-critical section
  }
}

// Init
fetchCaderno();
loadErrorAnalysisStats();
