// desafio.js — Desafio diário card and modal
import { getCSSVar } from './helpers.js';
import '/js/components/question-card.js';

let desafioDiarioData = null;
let desafioQuestoes = [];
let desafioIdx = 0;
let desafioRespostas = [];
let desafioTimer = null;
let desafioTimerSeg = 30; // Agora dinâmico por questão (fallback 30s)
let desafioTimerMax = 30; // Tempo total da questão atual
let desafioStartTime = null; // Timestamp de início do desafio

export async function loadDesafioDiarioCard() {
  try {
    const data = await fetch('/api/desafio-diario').then(r => r.json());
    desafioDiarioData = data;
    const card = document.getElementById('desafio-diario-card');
    const btn = document.getElementById('desafio-diario-btn');
    const status = document.getElementById('desafio-diario-status');
    const desc = document.getElementById('desafio-diario-desc');

    if (!data.questoes || data.questoes.length === 0) {
      status.innerHTML = '<span style="color:var(--text-sub);">Sem questões</span>';
      btn.textContent = '📚 Adicionar Questões';
      btn.onclick = () => window.location.href = '/questoes.html';
      return;
    }

    // Descrição reflete o número REAL de questões geradas (pode ser < 5 quando não
    // há questões elegíveis suficientes: dominadas/ciclo ativo/já respondidas).
    const n = data.questoes.length;
    if (desc) desc.textContent = `${n} ${n === 1 ? 'questão rápida' : 'questões rápidas'} baseada${n === 1 ? '' : 's'} nas suas fraquezas`;

    if (data.completado) {
      card.classList.add('completed');
      status.innerHTML = `<span style="color:var(--green);">✅ ${data.acertos}/${data.questoes.length} · +${data.pontos}pts</span>`;
      btn.textContent = '✅ Concluído Hoje';
      btn.disabled = true;
    } else {
      status.innerHTML = `<span style="color:var(--yellow);">${data.questoes.length} questões</span>`;
      btn.textContent = '⚡ Começar Desafio';
      btn.disabled = false;
      btn.onclick = iniciarDesafioDiario;
    }
  } catch(e) {
    console.error('Desafio Diário error:', e);
  }
}

export function iniciarDesafioDiario() {
  if (!desafioDiarioData || !desafioDiarioData.questoes || desafioDiarioData.questoes.length === 0) return;
  if (desafioDiarioData.completado) return;

  // Registrar timestamp de início para cálculo de tempo real
  desafioStartTime = Date.now();

  // Iniciar timer global para tracking visual
  try {
    if (typeof window.startGlobalTimer === 'function') {
      // Estimar tempo total: soma dos tempos adaptativos de todas as questões
      const tempoTotalEstimado = desafioDiarioData.questoes.reduce((acc, q) => acc + (q.tempo_segundos || 30), 0);
      const tempoMin = Math.ceil(tempoTotalEstimado / 60);
      window.startGlobalTimer('Desafio Diário', tempoMin, 'questoes');
    }
  } catch(e) {}

  desafioQuestoes = desafioDiarioData.questoes;
  desafioIdx = 0;
  desafioRespostas = [];

  showDesafioModal();
  showDesafioQuestion();
}

function showDesafioModal() {
  const overlay = document.createElement('div');
  overlay.className = 'desafio-modal-overlay';
  overlay.id = 'desafio-modal-overlay';
  overlay.innerHTML = `
    <div class="desafio-modal" id="desafio-modal-content">
      <div class="desafio-modal-header">
        <h2>🎯 Desafio Diário</h2>
        <span style="font-size:0.82rem;color:var(--text-sub);" id="desafio-timer-label">⏱ --s</span>
      </div>
      <div class="desafio-timer-bar">
        <div class="desafio-timer-fill" id="desafio-timer-fill" style="width:100%"></div>
      </div>
      <div id="desafio-body"></div>
    </div>
  `;
  document.body.appendChild(overlay);
}

function escapeAttrDesafio(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function showDesafioQuestion() {
  if (desafioIdx >= desafioQuestoes.length) {
    submitDesafioRespostas();
    return;
  }

  const q = desafioQuestoes[desafioIdx];
  const body = document.getElementById('desafio-body');

  // Build alternativas object for question-card
  const alts = {};
  if (q.alternativas && Array.isArray(q.alternativas)) {
    for (const a of q.alternativas) {
      alts[a.letra] = a.texto;
    }
  } else if (q.alternativas && typeof q.alternativas === 'object') {
    Object.assign(alts, q.alternativas);
  }

  body.innerHTML = `
    <div class="desafio-question-num">Questão ${desafioIdx + 1} de ${desafioQuestoes.length}</div>
    <question-card
      enunciado="${escapeAttrDesafio(q.enunciado)}"
      materia="${escapeAttrDesafio(q.materia)}"
      dificuldade="${escapeAttrDesafio(q.dificuldade || 'Médio')}"
      alternativas='${JSON.stringify(alts).replace(/'/g, '&#39;')}'
      resposta-correta="${escapeAttrDesafio(q.resposta_correta)}"
      mode="answer"
    ></question-card>
  `;

  // Listen for the answer-selected event from the component
  const questionCard = body.querySelector('question-card');
  questionCard.addEventListener('answer-selected', (e) => {
    clearInterval(desafioTimer);
    const { letter } = e.detail;

    desafioRespostas.push({
      questao_id: desafioQuestoes[desafioIdx].id,
      resposta: letter,
      tempo_segundos: desafioTimerMax - desafioTimerSeg, // tempo real gasto
    });

    setTimeout(() => {
      desafioIdx++;
      showDesafioQuestion();
    }, 400);
  }, { once: true });

  // Tempo adaptativo: usar tempo_segundos da API (baseado na complexidade da questão)
  desafioTimerMax = q.tempo_segundos || 30;
  desafioTimerSeg = desafioTimerMax;
  const timerFill = document.getElementById('desafio-timer-fill');
  const timerLabel = document.getElementById('desafio-timer-label');

  clearInterval(desafioTimer);
  timerFill.style.width = '100%';
  timerLabel.textContent = `⏱ ${desafioTimerSeg}s`;
  timerLabel.style.color = 'var(--text-sub)';

  desafioTimer = setInterval(() => {
    desafioTimerSeg--;
    const pct = (desafioTimerSeg / desafioTimerMax) * 100;
    timerFill.style.width = pct + '%';
    timerLabel.textContent = `⏱ ${desafioTimerSeg}s`;

    if (desafioTimerSeg <= 5) {
      timerLabel.style.color = 'var(--red)';
    } else if (desafioTimerSeg <= 10) {
      timerLabel.style.color = 'var(--yellow)';
    } else {
      timerLabel.style.color = 'var(--text-sub)';
    }

    if (desafioTimerSeg <= 0) {
      clearInterval(desafioTimer);
      desafioRespostas.push({
        questao_id: desafioQuestoes[desafioIdx].id,
        resposta: '',
        tempo_segundos: desafioTimerMax, // usou todo o tempo
      });
      desafioIdx++;
      showDesafioQuestion();
    }
  }, 1000);
}

// selectDesafioAlternativa is no longer needed — question-card dispatches 'answer-selected' event

async function submitDesafioRespostas() {
  clearInterval(desafioTimer);

  // Calcular tempo real gasto no desafio
  const tempoRealSeg = desafioStartTime ? Math.round((Date.now() - desafioStartTime) / 1000) : 0;

  // Parar timer global e registrar sessão de estudo com tempo real
  try {
    // Limpar o timer global (sem modal de confirmação)
    localStorage.removeItem('pomo_timer');
    const widget = document.getElementById('global-timer-widget');
    if (widget) widget.remove();

    // Registrar sessão de estudo com tempo REAL gasto (mínimo 10s para evitar registro de clique acidental)
    if (tempoRealSeg >= 10) {
      const horas = Math.round((tempoRealSeg / 3600) * 100) / 100;
      fetch('/api/sessoes-estudo/registrar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ horas, materia: 'Desafio Diário', tipo: 'desafio_diario' })
      }).catch(() => {});
    }
  } catch(e) {}

  const body = document.getElementById('desafio-body');
  body.innerHTML = '<div style="text-align:center;padding:30px;"><div style="font-size:2rem;margin-bottom:8px;">⏳</div><div style="color:var(--text-sub);">Calculando resultados...</div></div>';

  try {
    const result = await fetch('/api/desafio-diario/responder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ respostas: desafioRespostas })
    }).then(r => r.json());

    // Adicionar tempo real ao resultado para exibição
    result.tempo_real_seg = tempoRealSeg;
    showDesafioResults(result);
  } catch(e) {
    body.innerHTML = `<div style="text-align:center;color:var(--red);padding:20px;">Erro ao enviar respostas: ${e.message}</div>`;
  }
}

function showDesafioResults(result) {
  const body = document.getElementById('desafio-body');
  const timerBar = document.querySelector('.desafio-timer-bar');
  const timerLabel = document.getElementById('desafio-timer-label');
  if (timerBar) timerBar.style.display = 'none';
  if (timerLabel) timerLabel.style.display = 'none';

  const header = document.querySelector('.desafio-modal-header h2');
  if (header) header.textContent = '🏆 Resultado';

  const scoreColor = result.acertos >= 4 ? 'var(--green)' : result.acertos >= 3 ? 'var(--yellow)' : 'var(--red)';
  const emoji = result.acertos === result.total ? '🎉' : result.acertos >= 3 ? '👏' : '💪';

  // Formatar tempo real
  const tempoReal = result.tempo_real_seg || 0;
  const tempoFmt = tempoReal >= 60
    ? `${Math.floor(tempoReal / 60)}min ${tempoReal % 60}s`
    : `${tempoReal}s`;

  body.innerHTML = `
    <div class="desafio-results">
      <div style="font-size:3rem;margin-bottom:8px;">${emoji}</div>
      <div class="desafio-results-score" style="color:${scoreColor};">${result.acertos}/${result.total}</div>
      <div class="desafio-results-xp">+${result.pontos_ganhos} XP</div>
      <div style="font-size:0.8rem;color:var(--text-sub);margin-top:4px;">⏱ Tempo: ${tempoFmt}</div>
      ${result.streak_bonus > 0 ? `<div class="desafio-results-detail">🔥 Streak bonus: +${result.streak_bonus} pts</div>` : ''}
      <div style="margin-top:16px;text-align:left;">
        ${result.resultados.map((r, i) => `
          <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);font-size:0.82rem;">
            <span style="font-size:1rem;">${r.acertou ? '✅' : '❌'}</span>
            <span style="flex:1;color:var(--text);">Questão ${i + 1}</span>
            ${!r.acertou ? `<span style="color:var(--text-sub);font-size:0.75rem;">Correta: ${r.correta}</span>` : ''}
          </div>
        `).join('')}
      </div>
      <button class="desafio-close-btn" onclick="closeDesafioModal()">Fechar</button>
    </div>
  `;

  if (result.acertos === result.total) {
    spawnDesafioConfetti();
  }

  loadDesafioDiarioCard();
}

export function closeDesafioModal() {
  clearInterval(desafioTimer);
  // Parar timer global se o desafio foi abandonado
  try {
    const timerState = localStorage.getItem('pomo_timer');
    if (timerState) {
      const state = JSON.parse(timerState);
      if (state.materia === 'Desafio Diário') {
        localStorage.removeItem('pomo_timer');
        const widget = document.getElementById('global-timer-widget');
        if (widget) widget.remove();
      }
    }
  } catch(e) {}
  const overlay = document.getElementById('desafio-modal-overlay');
  if (overlay) overlay.remove();
}

function spawnDesafioConfetti() {
  const overlay = document.getElementById('desafio-modal-overlay');
  if (!overlay) return;
  const confettiContainer = document.createElement('div');
  confettiContainer.style.cssText = 'position:absolute;inset:0;overflow:hidden;pointer-events:none;z-index:0;';
  overlay.insertBefore(confettiContainer, overlay.firstChild);
  const colors = ['#f38ba8','#a6e3a1','#89b4fa','#f9e2af','#cba6f7','#fab387','#94e2d5'];
  for (let i = 0; i < 50; i++) {
    const piece = document.createElement('div');
    piece.style.cssText = `position:absolute;width:${6+Math.random()*8}px;height:${6+Math.random()*8}px;background:${colors[Math.floor(Math.random()*colors.length)]};border-radius:${Math.random()>0.5?'50%':'2px'};left:${Math.random()*100}%;top:-10px;animation:desafioConfetti ${2+Math.random()*2}s ease-out ${Math.random()*1.5}s forwards;`;
    confettiContainer.appendChild(piece);
  }
}

// Window assignments for HTML onclick
window.iniciarDesafioDiario = iniciarDesafioDiario;
window.closeDesafioModal = closeDesafioModal;
