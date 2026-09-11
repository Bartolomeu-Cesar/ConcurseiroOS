// caderno-erros.js — ES module extracted from caderno-erros.html
import { escapeJsString } from '/js/modules/utils.js';
import { illustration } from '/js/modules/illustrations.js';

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
        ${illustration('concluido')}
        <p class="empty-msg">${filtroMateria ? 'Nenhuma revisão pendente nesta matéria!' : 'Nenhuma revisão pendente hoje! Volte amanhã.'}</p>
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
        <span class="revisao-feedback__detalhe">Como foi lembrar a resposta?</span>
        <div class="revisao-facilidade">
          <button class="revisao-btn revisao-btn--dificil" onclick="revisar(${questaoId}, true, 3)" title="Acertei, mas com esforço — continuar revisando">😅 Acertei, mas foi difícil</button>
          <button class="revisao-btn revisao-btn--ok" onclick="revisar(${questaoId}, true, 4)" title="Lembrei com facilidade — pode dominar e sair do caderno">😎 Fácil, dominei →</button>
        </div>
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

    // Errorful Learning (Kornell 2009): após errar, oferece teste imediato de
    // uma questão similar do mesmo conceito — consolida a correção e reduz a
    // repetição do erro. Busca em background e injeta um bloco no feedback.
    _oferecerQuestaoSimilar(questaoId);
  }
};

// ============================================================
// ERRORFUL LEARNING — questão similar após errar no caderno de erros
// Evidência: Kornell et al. (2009), Potts & Shanks (2014)
// ============================================================
async function _oferecerQuestaoSimilar(questaoId) {
  // Recupera matéria/tópico da questão errada a partir dos dados carregados.
  const q = _findQuestaoNoCaderno(questaoId);
  if (!q || !q.materia) return;
  try {
    const url = `/api/questoes/similar?materia=${encodeURIComponent(q.materia)}`
      + `&excluir_id=${questaoId}&topico=${encodeURIComponent(q.topico || '')}`;
    const similar = await fetch(url).then(r => r.ok ? r.json() : null);
    if (similar && similar.id) {
      _renderErrorfulCaderno(questaoId, similar);
    }
  } catch (e) { /* silencioso: recurso complementar */ }
}

function _findQuestaoNoCaderno(id) {
  if (!dadosCaderno) return null;
  const pools = [dadosCaderno.pendentes_hoje || []];
  for (const pool of pools) {
    const found = pool.find(x => x.id === id);
    if (found) return found;
  }
  return null;
}

function _renderErrorfulCaderno(questaoId, q) {
  const feedback = document.getElementById(`feedback-${questaoId}`);
  if (!feedback) return;

  const alts = [];
  for (const letra of ['a', 'b', 'c', 'd', 'e']) {
    const texto = q[`alternativa_${letra}`];
    if (texto) alts.push({ letra: letra.toUpperCase(), texto });
  }
  const isCE = alts.length <= 2;
  let correctLetter = (q.resposta_correta || '').toUpperCase();

  // Embaralha a posição da correta (>2 alternativas), mantendo rótulos fixos.
  if (!isCE) {
    const rotulos = alts.map(a => a.letra);
    const textoCorreto = (alts.find(a => a.letra === correctLetter) || {}).texto;
    const textos = alts.map(a => a.texto);
    for (let i = textos.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [textos[i], textos[j]] = [textos[j], textos[i]];
    }
    for (let i = 0; i < alts.length; i++) {
      alts[i] = { letra: rotulos[i], texto: textos[i] };
      if (textos[i] === textoCorreto) correctLetter = rotulos[i];
    }
  }

  let altsHtml;
  if (isCE) {
    altsHtml = `<div style="display:flex;gap:8px;margin-top:8px;">
      <button class="efl-alt-${questaoId}" onclick="answerErrorfulCaderno(${questaoId},'A','${correctLetter}')" style="flex:1;padding:8px;background:var(--ce-card);border:2px solid var(--ce-green,#a6e3a1);border-radius:6px;color:var(--ce-green,#a6e3a1);cursor:pointer;font-weight:600;">✓ CERTO</button>
      <button class="efl-alt-${questaoId}" onclick="answerErrorfulCaderno(${questaoId},'B','${correctLetter}')" style="flex:1;padding:8px;background:var(--ce-card);border:2px solid var(--ce-red,#f38ba8);border-radius:6px;color:var(--ce-red,#f38ba8);cursor:pointer;font-weight:600;">✗ ERRADO</button>
    </div>`;
  } else {
    altsHtml = alts.map(a => `<button class="efl-alt-${questaoId}" onclick="answerErrorfulCaderno(${questaoId},'${a.letra}','${correctLetter}')" style="display:block;width:100%;text-align:left;padding:8px 12px;margin-top:4px;background:var(--ce-card);border:1px solid var(--ce-border);border-radius:6px;color:var(--ce-text);cursor:pointer;font-size:0.8rem;"><strong>${a.letra})</strong> ${escapeAttr(a.texto)}</button>`).join('');
  }

  const block = document.createElement('div');
  block.id = `efl-${questaoId}`;
  block.style.cssText = 'margin-top:10px;padding:12px;background:rgba(137,180,250,0.08);border:1px solid rgba(137,180,250,0.25);border-radius:8px;';
  block.innerHTML = `
    <div style="margin-bottom:8px;">
      <span style="font-size:0.72rem;background:var(--ce-blue,#89b4fa);color:var(--ce-bg,#1e1e2e);padding:2px 8px;border-radius:4px;font-weight:600;">⚡ Errorful Learning</span>
      <span style="font-size:0.68rem;color:var(--ce-subtext,#a6adc8);margin-left:6px;">Teste imediato do mesmo conceito — consolida a correção</span>
    </div>
    <div style="font-size:0.82rem;color:var(--ce-text);margin-bottom:6px;">${escapeAttr(q.enunciado || '')}</div>
    ${altsHtml}`;
  feedback.appendChild(block);
}

window.answerErrorfulCaderno = function(questaoId, resposta, correta) {
  const acertou = resposta.toUpperCase() === correta.toUpperCase();
  const block = document.getElementById(`efl-${questaoId}`);
  if (block) {
    block.querySelectorAll(`.efl-alt-${questaoId}`).forEach(btn => {
      btn.disabled = true; btn.style.cursor = 'default'; btn.style.opacity = '0.7';
    });
    const msg = document.createElement('div');
    msg.style.cssText = `margin-top:8px;font-weight:600;color:${acertou ? 'var(--ce-green,#a6e3a1)' : 'var(--ce-red,#f38ba8)'};font-size:0.82rem;`;
    msg.textContent = acertou
      ? '✅ Correto! O conceito está consolidado.'
      : `❌ Errou de novo. Correta: ${correta}. Reforce esse tópico!`;
    block.appendChild(msg);
  }
  showToast(acertou ? '⚡ Conceito consolidado!' : '⚠️ Reforce esse tópico.');
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

window.revisar = async function(questaoId, acertou, facilidade) {
  try {
    // Calcular tempo real gasto nesta questão
    const startTime = _cardTimers[questaoId];
    const tempoSegundos = startTime ? Math.round((Date.now() - startTime) / 1000) : 0;

    // Corpo: envia a facilidade (rating FSRS 3=Good "difícil", 4=Easy "fácil")
    // quando o usuário acerta e escolhe o nível. Só o acerto FÁCIL (com reps e
    // dificuldade adequadas) gradua a questão (sai do caderno).
    const payload = { acertou, tempo_segundos: tempoSegundos };
    if (acertou && facilidade) payload.facilidade = facilidade;

    const res = await fetch(`${API_BASE}/api/questoes/erros/revisar/${questaoId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
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
      let msg;
      if (data.graduou) {
        // Conteúdo dominado (Successive Relearning): a questão saiu do caderno.
        msg = '🎓 Dominado! Esta questão saiu do caderno de erros.';
        // Remove o card com uma pequena animação de saída.
        card.style.transition = 'opacity 0.4s, transform 0.4s';
        card.style.opacity = '0';
        card.style.transform = 'scale(0.96)';
        setTimeout(() => card.remove(), 400);
      } else {
        msg = acertou
          ? `✅ Próxima revisão em ${data.novo_intervalo} dia${data.novo_intervalo > 1 ? 's' : ''}`
          : `🔄 Voltará amanhã para revisão`;
      }
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

// ============================================================
// MODO ÁUDIO — ouvir as questões erradas pendentes (revisão hands-free)
// Ideal para transporte: lê o enunciado → pausa para pensar → lê a resposta
// correta. Usa speechSynthesis (Web Speech API, custo zero) + MediaSession
// (controle por fone bluetooth). Combina com o Successive Relearning: revisar
// passivamente o que mais importa (os erros) no tempo morto.
// ============================================================
let _audioAtivo = false;
let _audioPausado = false;
let _audioFila = [];
let _audioIdx = 0;

function _letraParaTexto(q, letra) {
  const L = (letra || '').toUpperCase();
  const isCE = !q.alternativa_c && !q.alternativa_d;
  if (isCE) return L === 'A' ? 'Certo' : 'Errado';
  const txt = q[`alternativa_${L.toLowerCase()}`];
  return txt ? `Alternativa ${L}. ${txt}` : `Alternativa ${L}`;
}

function _ptVoice() {
  const voices = window.speechSynthesis.getVoices();
  return voices.find(v => v.lang && v.lang.startsWith('pt')) || voices[0] || null;
}

function _fala(texto, rate) {
  const u = new SpeechSynthesisUtterance(texto);
  u.lang = 'pt-BR';
  u.rate = rate || 0.9;
  const v = _ptVoice();
  if (v) u.voice = v;
  return u;
}

window.toggleAudioCaderno = function() {
  if (_audioAtivo) { stopAudioCaderno(); return; }
  startAudioCaderno();
};

window.startAudioCaderno = function() {
  if (!('speechSynthesis' in window)) {
    showToast('Seu navegador não suporta leitura em voz (Text-to-Speech).');
    return;
  }
  // Fila = pendentes de hoje (respeita filtro de matéria selecionado).
  let pend = (dadosCaderno && dadosCaderno.pendentes_hoje) ? [...dadosCaderno.pendentes_hoje] : [];
  if (filtroMateria) pend = pend.filter(q => q.materia === filtroMateria);
  if (pend.length === 0) {
    showToast('Nenhuma questão pendente para ouvir hoje. 🎉');
    return;
  }
  _audioFila = pend;
  _audioIdx = 0;
  _audioAtivo = true;
  _audioPausado = false;

  const painel = document.getElementById('audio-caderno-painel');
  if (painel) painel.style.display = 'block';
  const btn = document.getElementById('btn-audio-caderno');
  if (btn) btn.innerHTML = '🎧 Ouvindo…';

  if ('mediaSession' in navigator) {
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: 'Caderno de Erros — Revisão por Áudio',
        artist: `${_audioFila.length} questões erradas`,
        album: 'ConcurseiroOS',
      });
      navigator.mediaSession.setActionHandler('play', () => pauseAudioCaderno());
      navigator.mediaSession.setActionHandler('pause', () => pauseAudioCaderno());
      navigator.mediaSession.setActionHandler('nexttrack', () => skipAudioCaderno());
    } catch (e) { /* MediaSession best-effort */ }
  }

  showToast(`🎧 Modo Áudio: ${_audioFila.length} questões. Ouça → pense → ouça a resposta.`);
  _audioPlay();
};

window.stopAudioCaderno = function() {
  try { window.speechSynthesis.cancel(); } catch (e) {}
  _audioAtivo = false;
  _audioPausado = false;
  _audioFila = [];
  const painel = document.getElementById('audio-caderno-painel');
  if (painel) painel.style.display = 'none';
  const btn = document.getElementById('btn-audio-caderno');
  if (btn) btn.innerHTML = '🎧 Modo Áudio';
  if ('mediaSession' in navigator) {
    try { navigator.mediaSession.metadata = null; } catch (e) {}
  }
};

window.pauseAudioCaderno = function() {
  const btn = document.getElementById('btn-audio-pause');
  if (_audioPausado) {
    window.speechSynthesis.resume();
    _audioPausado = false;
    if (btn) btn.innerHTML = '⏸ Pausar';
  } else {
    window.speechSynthesis.pause();
    _audioPausado = true;
    if (btn) btn.innerHTML = '▶ Retomar';
  }
};

window.skipAudioCaderno = function() {
  try { window.speechSynthesis.cancel(); } catch (e) {}
  _audioIdx++;
  if (_audioAtivo && _audioIdx < _audioFila.length) {
    _audioPlay();
  } else if (_audioIdx >= _audioFila.length) {
    _audioConcluir();
  }
};

function _audioConcluir() {
  showToast('🎉 Revisão por áudio concluída!');
  stopAudioCaderno();
}

function _audioStatus(texto) {
  const el = document.getElementById('audio-caderno-status');
  if (el) el.textContent = texto;
}

function _audioPlay() {
  if (!_audioAtivo || _audioIdx >= _audioFila.length) {
    _audioConcluir();
    return;
  }
  const q = _audioFila[_audioIdx];
  const synth = window.speechSynthesis;
  const pos = `${_audioIdx + 1}/${_audioFila.length}`;

  _audioStatus(`🎧 ${pos} — ${q.materia || ''}: ouça e tente lembrar a resposta…`);

  const uttEnun = _fala(`Questão ${_audioIdx + 1}. ${q.materia || ''}. ${q.enunciado || ''}`, 0.9);
  const respostaTexto = _letraParaTexto(q, q.resposta_correta);
  const uttResp = _fala(`Resposta correta. ${respostaTexto}`, 0.9);

  uttEnun.onend = () => {
    if (!_audioAtivo) return;
    _audioStatus(`🤔 ${pos} — Pense na resposta…`);
    // Pausa de 6s para recuperação ativa (retrieval) antes da resposta.
    setTimeout(() => {
      if (!_audioAtivo) return;
      _audioStatus(`✅ ${pos} — Resposta correta`);
      synth.speak(uttResp);
    }, 6000);
  };

  uttResp.onend = () => {
    // Pausa de 2s antes da próxima questão.
    setTimeout(() => {
      if (!_audioAtivo) return;
      _audioIdx++;
      _audioPlay();
    }, 2000);
  };

  synth.speak(uttEnun);
}

// Init
fetchCaderno();
loadErrorAnalysisStats();
