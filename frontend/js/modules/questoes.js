// ==================== QUESTÕES DO DIA ====================
import { escapeHtml, toast } from './utils.js';
import { switchTab } from './tabs.js';
import { showQuestionXp } from './xp-notify.js';
import { emit } from './event-bus.js';

let questoesDia = [], qDiaIdx = 0, qDiaAcertos = 0;
let qDiaStartTime = null; // Timestamp de quando a questão foi exibida
let _loadMetas = null, _loadStreakBadge = null, _getConfigSessoes = null;
let _lastRespostaId = null; // ID da última resposta registrada (para error analysis)

export async function carregarQuestoesDia() {
  try {
    const cfg = _getConfigSessoes();
    const qtd = cfg.questoes_dia;
    const all = await fetch('/api/questoes?limit=200').then(r => r.json());
    const pool = Array.isArray(all) ? all : (all.items || []);
    if (pool.length === 0) { toast('Nenhuma questão no banco. Adicione questões primeiro.', 'warning'); return; }
    questoesDia = pool.sort(() => Math.random() - 0.5).slice(0, qtd);
    qDiaIdx = 0;
    qDiaAcertos = 0;

    // Auto-start global timer if not already running
    try {
      const timerState = localStorage.getItem('pomo_timer');
      if (!timerState && typeof window.startGlobalTimer === 'function') {
        window.startGlobalTimer('Questões do Dia', 25, 'questoes');
      }
    } catch(e) {}

    document.getElementById('questoes-dia-area').style.display = 'none';
    document.getElementById('questao-dia-card').style.display = 'block';
    document.getElementById('questoes-dia-progress').style.display = 'block';
    showQuestaoDia();
  } catch(e) { toast('Erro ao carregar questões', 'error'); }
}

export function showQuestaoDia() {
  const card = document.getElementById('questao-dia-card');
  // Aleatorização das alternativas: antes de qualquer render/timer, garante que a
  // questão atual foi servida embaralhada (sob demanda). Substitui no array e
  // re-renderiza uma única vez. A checagem de acerto usa q.resposta_correta (já
  // remapeada) e o /responder recebe embaralhada=true. Ignora a tela de conclusão.
  if (qDiaIdx < questoesDia.length) {
    const _q = questoesDia[qDiaIdx];
    if (_q && _q.id && !_q._embaralhado) {
      fetch(`/api/questoes/${_q.id}?embaralhar=true`)
        .then(r => r.ok ? r.json() : null)
        .then(emb => {
          questoesDia[qDiaIdx] = emb ? { ...emb, _embaralhado: true } : { ..._q, _embaralhado: true };
          showQuestaoDia();
        })
        .catch(() => { questoesDia[qDiaIdx] = { ..._q, _embaralhado: true }; showQuestaoDia(); });
      return;
    }
  }
  const total = questoesDia.length;
  const pct = Math.round((qDiaIdx / total) * 100);
  document.getElementById('qdia-progress-text').textContent = `${qDiaIdx}/${total} respondidas`;
  document.getElementById('qdia-progress-pct').textContent = `${pct}%`;
  document.getElementById('qdia-progress-bar').style.width = `${pct}%`;
  document.getElementById('qdia-progress-bar').style.background = pct >= 100 ? '#a6e3a1' : pct >= 50 ? '#f9e2af' : '#89b4fa';
  if (qDiaIdx >= total) {
    const pctAcerto = Math.round((qDiaAcertos / total) * 100);
    card.innerHTML = `<div style="text-align:center;padding:16px;">
      <div style="font-size:1.3rem;margin-bottom:8px;">🎉 Questões do Dia Concluídas!</div>
      <div style="font-size:2rem;font-weight:700;color:${pctAcerto >= 70 ? '#a6e3a1' : pctAcerto >= 50 ? '#f9e2af' : '#f38ba8'};">${pctAcerto}%</div>
      <div style="font-size:0.85rem;color:#9399b2;">${qDiaAcertos}/${total} acertos</div>
      <button onclick="carregarQuestoesDia()" style="margin-top:12px;background:#89b4fa;color:#1e1e2e;border:none;border-radius:6px;padding:8px 16px;font-weight:600;cursor:pointer;">🔄 Nova Rodada</button>
    </div>`;
    document.getElementById('qdia-progress-text').textContent = `${total}/${total} respondidas ✓`;
    document.getElementById('qdia-progress-pct').textContent = '100%';
    document.getElementById('qdia-progress-bar').style.width = '100%';
    document.getElementById('qdia-progress-bar').style.background = '#a6e3a1';
    qDiaStartTime = null;
    return;
  }
  // Iniciar timer para esta questão
  qDiaStartTime = Date.now();

  // Timer visual — limpar anterior e iniciar novo
  if (window._qDiaTimerInterval) clearInterval(window._qDiaTimerInterval);
  window._qDiaTimerInterval = setInterval(() => {
    const el = document.getElementById('qdia-timer');
    if (!el || !qDiaStartTime) { clearInterval(window._qDiaTimerInterval); return; }
    const seg = Math.round((Date.now() - qDiaStartTime) / 1000);
    const min = Math.floor(seg / 60);
    const s = String(seg % 60).padStart(2, '0');
    el.textContent = `⏱ ${min}:${s}`;
    if (seg > 120) el.style.color = '#f38ba8';
    else if (seg > 60) el.style.color = '#f9e2af';
    else el.style.color = '#89b4fa';
  }, 1000);

  const q = questoesDia[qDiaIdx];
  const isCertoErrado = !q.alternativa_c && !q.alternativa_d;
  const alts = isCertoErrado
    ? [{letra: 'A', texto: 'CERTO'}, {letra: 'B', texto: 'ERRADO'}]
    : [
        {letra: 'A', texto: q.alternativa_a},
        {letra: 'B', texto: q.alternativa_b},
        {letra: 'C', texto: q.alternativa_c},
        {letra: 'D', texto: q.alternativa_d},
        ...(q.alternativa_e ? [{letra: 'E', texto: q.alternativa_e}] : []),
      ];
  const altsHtml = isCertoErrado
    ? `<div style="display:flex;gap:12px;justify-content:center;margin-top:12px;max-width:280px;margin-left:auto;margin-right:auto;">
        <button class="qdia-alt" onclick="responderQuestaoDia('A')" style="flex:1;padding:10px 16px;background:#313244;border:2px solid #a6e3a1;border-radius:8px;color:#a6e3a1;cursor:pointer;font-size:0.82rem;font-weight:700;text-align:center;">✓ CERTO</button>
        <button class="qdia-alt" onclick="responderQuestaoDia('B')" style="flex:1;padding:10px 16px;background:#313244;border:2px solid #f38ba8;border-radius:8px;color:#f38ba8;cursor:pointer;font-size:0.82rem;font-weight:700;text-align:center;">✗ ERRADO</button>
      </div>`
    : alts.map(a => `<button class="qdia-alt" onclick="responderQuestaoDia('${a.letra}')" style="display:block;width:100%;text-align:left;padding:8px 12px;margin-bottom:6px;background:#313244;border:1px solid #45475a;border-radius:6px;color:#cdd6f4;cursor:pointer;font-size:0.82rem;"><strong>${a.letra})</strong> ${escapeHtml(a.texto)}</button>`).join('');
  card.innerHTML = `<div style="padding:12px;background:#1e1e2e;border-radius:8px;">
    <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#9399b2;margin-bottom:6px;">
      <span>${qDiaIdx + 1}/${total}</span>
      <span id="qdia-timer" style="font-family:monospace;font-size:0.82rem;color:#89b4fa;font-weight:600;">⏱ 0:00</span>
      <span style="color:#cba6f7;">${q.materia || ''}</span>
    </div>
    <div style="font-size:0.88rem;color:#cdd6f4;margin-bottom:12px;line-height:1.5;">${isCertoErrado ? '🔵 Julgue o item: ' : ''}${escapeHtml(q.enunciado)}</div>
    <div id="qdia-alternativas">
      ${altsHtml}
    </div>
    <div id="qdia-feedback" style="display:none;margin-top:10px;padding:10px;border-radius:6px;font-size:0.82rem;"></div>
  </div>`;
}

export async function responderQuestaoDia(letra) {
  const q = questoesDia[qDiaIdx];
  const tempoSegundos = qDiaStartTime ? Math.round((Date.now() - qDiaStartTime) / 1000) : 0;
  // Parar o timer visual
  if (window._qDiaTimerInterval) clearInterval(window._qDiaTimerInterval);
  const acertou = letra.toUpperCase() === q.resposta_correta.toUpperCase();
  if (acertou) qDiaAcertos++;

  // XP real-time feedback
  showQuestionXp(acertou);

  // Emitir evento para integração cross-module
  emit('questao:respondida', { materia: q.materia, acertou, tempo_seg: tempoSegundos });

  // Feed adaptive pomodoro fatigue detection
  if (window._adaptivePomo) {
    window._adaptivePomo.recordAnswer(acertou, tempoSegundos);
  }
  document.querySelectorAll('.qdia-alt').forEach(btn => {
    btn.disabled = true; btn.style.cursor = 'default';
    const btnLetra = btn.textContent.trim().charAt(0);
    if (btnLetra === q.resposta_correta) { btn.style.background = '#1e3a2e'; btn.style.borderColor = '#a6e3a1'; btn.style.color = '#a6e3a1'; }
    else if (btnLetra === letra && !acertou) { btn.style.background = '#3a1e1e'; btn.style.borderColor = '#f38ba8'; btn.style.color = '#f38ba8'; }
  });
  const tempoFmt = `${Math.floor(tempoSegundos / 60)}:${String(tempoSegundos % 60).padStart(2, '0')}`;
  const fb = document.getElementById('qdia-feedback');
  fb.style.display = 'block';
  fb.style.background = acertou ? '#1e3a2e' : '#3a1e1e';
  fb.style.color = acertou ? '#a6e3a1' : '#f38ba8';

  if (acertou) {
    fb.innerHTML = `<strong>✓ Correto!</strong>
      <span style="float:right;color:#9399b2;font-size:0.75rem;">⏱ ${tempoFmt}</span>
      ${q.explicacao ? '<br><span style="color:#cdd6f4;font-size:0.78rem;">' + q.explicacao + '</span>' : ''}
      <br><button onclick="advanceQuestao()" style="margin-top:8px;background:#89b4fa;color:#1e1e2e;border:none;border-radius:6px;padding:6px 14px;font-weight:600;cursor:pointer;">Próxima →</button>`;
  } else {
    // Self-Explanation corrigido (Chi et al. 1994):
    // 1. Mostrar resposta correta + explicação
    // 2. Pedir para REFORMULAR com próprias palavras (não explicar do zero)
    const isCE = !q.alternativa_c && !q.alternativa_d;
    const respostaTexto = isCE ? (q.resposta_correta === 'A' ? 'CERTO' : 'ERRADO') : q.resposta_correta;
    const temExplicacao = q.explicacao && q.explicacao.trim();
    fb.innerHTML = `<strong>✗ Errado! Resposta: ${respostaTexto}</strong>
      <span style="float:right;color:#9399b2;font-size:0.75rem;">⏱ ${tempoFmt}</span>
      ${temExplicacao ? `<div style="margin-top:8px;padding:10px;background:rgba(166,227,161,0.08);border:1px solid var(--green);border-radius:8px;">
        <div style="font-size:0.72rem;color:var(--green);font-weight:600;margin-bottom:4px;">💡 Explicação:</div>
        <div style="font-size:0.82rem;color:var(--text);">${q.explicacao}</div>
      </div>` : `<div style="margin-top:6px;font-size:0.78rem;color:var(--text-sub);font-style:italic;">Sem explicação cadastrada para esta questão.</div>`}
      <div style="margin-top:10px;padding:10px;background:rgba(249,226,175,0.1);border:1px solid var(--yellow);border-radius:8px;">
        <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:4px;">📋 Por que errei?</div>
        <div id="qdia-error-chips" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;">
          <button class="error-chip" data-motivo="leitura_incompleta" onclick="selectErrorChip(this)">📖 Leitura incompleta</button>
          <button class="error-chip" data-motivo="conceito_errado" onclick="selectErrorChip(this)">❌ Conceito errado</button>
          <button class="error-chip" data-motivo="excecao_regra" onclick="selectErrorChip(this)">⚠️ Exceção da regra</button>
          <button class="error-chip" data-motivo="pegadinha" onclick="selectErrorChip(this)">🪤 Pegadinha</button>
          <button class="error-chip" data-motivo="chute" onclick="selectErrorChip(this)">🎲 Chutei</button>
          <button class="error-chip" data-motivo="desatencao" onclick="selectErrorChip(this)">😵 Desatenção</button>
          <button class="error-chip" data-motivo="tempo" onclick="selectErrorChip(this)">⏰ Faltou tempo</button>
        </div>
        <div style="font-size:0.75rem;color:var(--yellow);font-weight:600;margin-bottom:4px;">🧠 Reformule — agora que viu a explicação, resuma com suas palavras:</div>
        <textarea id="qdia-self-explain" placeholder="Resuma com suas palavras o que aprendeu com esse erro... (reformular consolida a correção)" aria-label="Sua explicação sobre o erro" 
          style="width:100%;min-height:50px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px;color:var(--text);font-size:0.82rem;font-family:inherit;resize:vertical;"></textarea>
        <button onclick="submitSelfExplanation(${q.id})" style="margin-top:6px;background:var(--yellow);color:var(--bg);border:none;border-radius:6px;padding:6px 14px;font-weight:600;cursor:pointer;font-size:0.82rem;">💾 Salvar e continuar</button>
        <button onclick="advanceQuestao()" style="margin-top:6px;margin-left:6px;background:var(--bg-elevated);color:var(--text-sub);border:none;border-radius:6px;padding:6px 14px;font-size:0.78rem;cursor:pointer;">Pular →</button>
      </div>`;
  }
  try {
    const resp = await fetch(`/api/questoes/${q.id}/responder`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ resposta: letra, tempo_segundos: tempoSegundos, embaralhada: !!q.embaralhada }) });
    if (resp.status === 403) {
      const err = await resp.json().catch(() => ({}));
      toast(err.detail || 'Limite de questões do dia atingido. Faça upgrade!', 'warning');
      if (window.showUpgradeModal) window.showUpgradeModal();
      return;
    }
    if (resp.ok) {
      const data = await resp.json();
      _lastRespostaId = data.id || data.resposta_id || null;
    }
    if (_loadMetas) _loadMetas();
    if (_loadStreakBadge) _loadStreakBadge();
  } catch(e) {}
}

// Expor qDiaIdx para uso no onclick inline
export function advanceQuestao() { qDiaIdx++; showQuestaoDia(); }

// Self-Explanation: salvar explicação do aluno
export async function submitSelfExplanation(questaoId) {
  const textarea = document.getElementById('qdia-self-explain');
  const explicacao = textarea?.value?.trim();
  if (!explicacao) {
    textarea.style.borderColor = 'var(--red)';
    textarea.placeholder = 'Escreva pelo menos uma frase explicando...';
    return;
  }
  try {
    await fetch('/api/study-intelligence/self-explanation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ questao_id: questaoId, explicacao })
    });
    toast('💡 Explicação salva! Isso fortalece sua memória.', 'success');
  } catch (e) {}

  // Enviar error analysis se motivo selecionado
  const selectedChip = document.querySelector('.error-chip.selected');
  if (selectedChip && _lastRespostaId) {
    try {
      await fetch('/api/questoes/erros/analise', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resposta_id: _lastRespostaId,
          motivo: selectedChip.dataset.motivo,
          detalhe: explicacao
        })
      });
    } catch (e) {}
  }

  // === ERRORFUL LEARNING: Buscar questão similar para teste imediato ===
  // Evidência: Kornell et al. (2009) — Errar + feedback + teste imediato do mesmo conceito
  // consolida a correção e previne repetição do mesmo erro.
  const q = questoesDia[qDiaIdx];
  if (q && q.materia) {
    try {
      const similar = await fetch(`/api/questoes/similar?materia=${encodeURIComponent(q.materia)}&excluir_id=${q.id}&topico=${encodeURIComponent(q.topico || '')}`).then(r => r.json());
      if (similar && similar.id) {
        _showErrorfulLearningQuestion(similar);
        return; // Não avança — mostra questão similar primeiro
      }
    } catch(e) {}
  }

  advanceQuestao();
}

// Error Analysis: selecionar chip de motivo
export function selectErrorChip(btn) {
  document.querySelectorAll('.error-chip').forEach(c => c.classList.remove('selected'));
  btn.classList.add('selected');
}

// ============================================================
// ERRORFUL LEARNING — Questão similar após erro
// Evidência: Kornell et al. (2009), Potts & Shanks (2014)
// ============================================================

function _showErrorfulLearningQuestion(q) {
  const fb = document.getElementById('qdia-feedback');
  const container = document.getElementById('qdia-container') || fb?.parentElement;
  if (!container) { advanceQuestao(); return; }

  // Montar alternativas
  const alts = [];
  if (q.alternativa_a) alts.push({ letra: 'A', texto: q.alternativa_a });
  if (q.alternativa_b) alts.push({ letra: 'B', texto: q.alternativa_b });
  if (q.alternativa_c) alts.push({ letra: 'C', texto: q.alternativa_c });
  if (q.alternativa_d) alts.push({ letra: 'D', texto: q.alternativa_d });
  if (q.alternativa_e) alts.push({ letra: 'E', texto: q.alternativa_e });

  const isCE = alts.length <= 2;
  let altsHtml;
  if (isCE) {
    altsHtml = `<div style="display:flex;gap:8px;margin-top:8px;">
      <button class="efl-alt" onclick="answerErrorfulLearning('A','${q.resposta_correta}')" style="flex:1;padding:8px;background:var(--bg-surface);border:2px solid var(--green);border-radius:6px;color:var(--green);cursor:pointer;font-weight:600;">✓ CERTO</button>
      <button class="efl-alt" onclick="answerErrorfulLearning('B','${q.resposta_correta}')" style="flex:1;padding:8px;background:var(--bg-surface);border:2px solid var(--red);border-radius:6px;color:var(--red);cursor:pointer;font-weight:600;">✗ ERRADO</button>
    </div>`;
  } else {
    altsHtml = alts.map(a => `<button class="efl-alt" onclick="answerErrorfulLearning('${a.letra}','${q.resposta_correta}')" style="display:block;width:100%;text-align:left;padding:8px 12px;margin-top:4px;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:pointer;font-size:0.8rem;"><strong>${a.letra})</strong> ${a.texto}</button>`).join('');
  }

  fb.style.display = 'block';
  fb.style.background = 'rgba(137,180,250,0.1)';
  fb.style.color = 'var(--text)';
  fb.innerHTML = `
    <div style="margin-bottom:8px;">
      <span style="font-size:0.72rem;background:var(--blue);color:var(--bg);padding:2px 8px;border-radius:4px;font-weight:600;">⚡ Errorful Learning</span>
      <span style="font-size:0.65rem;color:var(--text-sub);margin-left:6px;">Teste imediato do mesmo conceito — consolida a correção</span>
    </div>
    <div style="font-size:0.82rem;color:var(--text);margin-bottom:6px;">${q.enunciado}</div>
    ${altsHtml}
    <button onclick="advanceQuestao()" style="margin-top:8px;background:var(--bg-elevated);color:var(--text-sub);border:none;border-radius:6px;padding:4px 10px;font-size:0.72rem;cursor:pointer;">Pular →</button>
  `;
}

export function answerErrorfulLearning(resposta, correta) {
  const acertou = resposta.toUpperCase() === correta.toUpperCase();
  const fb = document.getElementById('qdia-feedback');

  // Desabilitar botões
  document.querySelectorAll('.efl-alt').forEach(btn => {
    btn.disabled = true; btn.style.cursor = 'default'; btn.style.opacity = '0.7';
  });

  // Feedback rápido
  const msg = acertou
    ? '<div style="margin-top:8px;color:var(--green);font-weight:600;">✅ Correto! O conceito está consolidado.</div>'
    : `<div style="margin-top:8px;color:var(--red);font-weight:600;">❌ Errou novamente. Resposta: ${correta}. Revise esse tópico!</div>`;

  fb.innerHTML += msg + `<button onclick="advanceQuestao()" style="margin-top:8px;background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:6px 14px;font-weight:600;cursor:pointer;font-size:0.82rem;">Próxima →</button>`;

  toast(acertou ? '⚡ Conceito consolidado!' : '⚠️ Revise esse tópico.', acertou ? 'success' : 'warning', 2000);
}

export function initQuestoes(deps) {
  _loadMetas = deps.loadMetas;
  _loadStreakBadge = deps.loadStreakBadge;
  _getConfigSessoes = deps.getConfigSessoes;

  // Ouvir evento de questões pós-estudo
  window.addEventListener('iniciar-questoes-pos-estudo', (e) => {
    const { pool, materia } = e.detail;
    questoesDia = pool.sort(() => Math.random() - 0.5).slice(0, 5);
    qDiaIdx = 0;
    qDiaAcertos = 0;
    switchTab('tab-flashcards');
    document.getElementById('questoes-dia-area').style.display = 'none';
    document.getElementById('questao-dia-card').style.display = 'block';
    document.getElementById('questoes-dia-progress').style.display = 'block';
    showQuestaoDia();
    toast(`📝 5 questões de ${materia}`, 'success');
  });
}
