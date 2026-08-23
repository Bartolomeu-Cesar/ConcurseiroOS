// ==================== QUESTÕES DO DIA ====================
import { escapeHtml, toast } from './utils.js';
import { switchTab } from './tabs.js';

let questoesDia = [], qDiaIdx = 0, qDiaAcertos = 0;
let qDiaStartTime = null; // Timestamp de quando a questão foi exibida
let _loadMetas = null, _loadStreakBadge = null, _getConfigSessoes = null;

export async function carregarQuestoesDia() {
  try {
    const cfg = _getConfigSessoes();
    const qtd = cfg.questoes_dia;
    const all = await fetch('/api/questoes?limit=200').then(r => r.json());
    const pool = Array.isArray(all) ? all : (all.items || []);
    if (pool.length === 0) { alert('Nenhuma questão no banco. Adicione questões primeiro.'); return; }
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
  const alts = [
    {letra: 'A', texto: q.alternativa_a},
    {letra: 'B', texto: q.alternativa_b},
    {letra: 'C', texto: q.alternativa_c},
    {letra: 'D', texto: q.alternativa_d},
  ];
  if (q.alternativa_e) alts.push({letra: 'E', texto: q.alternativa_e});
  card.innerHTML = `<div style="padding:12px;background:#1e1e2e;border-radius:8px;">
    <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#9399b2;margin-bottom:6px;">
      <span>${qDiaIdx + 1}/${total}</span>
      <span id="qdia-timer" style="font-family:monospace;font-size:0.82rem;color:#89b4fa;font-weight:600;">⏱ 0:00</span>
      <span style="color:#cba6f7;">${q.materia || ''}</span>
    </div>
    <div style="font-size:0.88rem;color:#cdd6f4;margin-bottom:12px;line-height:1.5;">${escapeHtml(q.enunciado)}</div>
    <div id="qdia-alternativas">
      ${alts.map(a => `<button class="qdia-alt" onclick="responderQuestaoDia('${a.letra}')" style="display:block;width:100%;text-align:left;padding:8px 12px;margin-bottom:6px;background:#313244;border:1px solid #45475a;border-radius:6px;color:#cdd6f4;cursor:pointer;font-size:0.82rem;"><strong>${a.letra})</strong> ${escapeHtml(a.texto)}</button>`).join('')}
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
    // Self-Explanation: obrigatório explicar POR QUÊ errou (+40% retenção)
    fb.innerHTML = `<strong>✗ Errado! Resposta: ${q.resposta_correta}</strong>
      <span style="float:right;color:#9399b2;font-size:0.75rem;">⏱ ${tempoFmt}</span>
      ${q.explicacao ? '<br><span style="color:#cdd6f4;font-size:0.78rem;">💡 ' + q.explicacao + '</span>' : ''}
      <div style="margin-top:10px;padding:10px;background:rgba(249,226,175,0.1);border:1px solid var(--yellow);border-radius:8px;">
        <div style="font-size:0.75rem;color:var(--yellow);font-weight:600;margin-bottom:6px;">🧠 Self-Explanation — Explique por que a resposta correta é "${q.resposta_correta}":</div>
        <textarea id="qdia-self-explain" placeholder="Escreva com suas palavras por que esta é a resposta correta... (Isso melhora sua retenção em 40%!)" 
          style="width:100%;min-height:50px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px;color:var(--text);font-size:0.82rem;font-family:inherit;resize:vertical;"></textarea>
        <button onclick="submitSelfExplanation(${q.id})" style="margin-top:6px;background:var(--yellow);color:var(--bg);border:none;border-radius:6px;padding:6px 14px;font-weight:600;cursor:pointer;font-size:0.82rem;">💾 Salvar e continuar</button>
        <button onclick="advanceQuestao()" style="margin-top:6px;margin-left:6px;background:var(--bg-elevated);color:var(--text-sub);border:none;border-radius:6px;padding:6px 14px;font-size:0.78rem;cursor:pointer;">Pular →</button>
      </div>`;
  }
  try {
    await fetch(`/api/questoes/${q.id}/responder`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ resposta: letra, tempo_segundos: tempoSegundos }) });
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
  advanceQuestao();
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
