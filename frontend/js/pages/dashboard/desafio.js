// desafio.js — Desafio diário card and modal
import { getCSSVar } from './helpers.js';
import '/js/components/question-card.js';

let desafioDiarioData = null;
let desafioQuestoes = [];
let desafioIdx = 0;
let desafioRespostas = [];
let desafioTimer = null;
let desafioTimerSeg = 15;

export async function loadDesafioDiarioCard() {
  try {
    const data = await fetch('/api/desafio-diario').then(r => r.json());
    desafioDiarioData = data;
    const card = document.getElementById('desafio-diario-card');
    const btn = document.getElementById('desafio-diario-btn');
    const status = document.getElementById('desafio-diario-status');

    if (!data.questoes || data.questoes.length === 0) {
      status.innerHTML = '<span style="color:var(--text-sub);">Sem questões</span>';
      btn.textContent = '📚 Adicionar Questões';
      btn.onclick = () => window.location.href = '/questoes.html';
      return;
    }

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

  // Auto-start global timer if not already running
  try {
    const timerState = localStorage.getItem('pomo_timer');
    if (!timerState && typeof window.startGlobalTimer === 'function') {
      window.startGlobalTimer('Desafio Diário', 25, 'questoes');
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
        <span style="font-size:0.82rem;color:var(--text-sub);" id="desafio-timer-label">⏱ 15s</span>
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

    desafioRespostas.push({ questao_id: desafioQuestoes[desafioIdx].id, resposta: letter });

    setTimeout(() => {
      desafioIdx++;
      showDesafioQuestion();
    }, 400);
  }, { once: true });

  desafioTimerSeg = 15;
  const timerFill = document.getElementById('desafio-timer-fill');
  const timerLabel = document.getElementById('desafio-timer-label');

  clearInterval(desafioTimer);
  timerFill.style.width = '100%';
  timerLabel.textContent = '⏱ 15s';

  desafioTimer = setInterval(() => {
    desafioTimerSeg--;
    const pct = (desafioTimerSeg / 15) * 100;
    timerFill.style.width = pct + '%';
    timerLabel.textContent = `⏱ ${desafioTimerSeg}s`;

    if (desafioTimerSeg <= 5) {
      timerLabel.style.color = 'var(--red)';
    } else {
      timerLabel.style.color = 'var(--text-sub)';
    }

    if (desafioTimerSeg <= 0) {
      clearInterval(desafioTimer);
      desafioRespostas.push({ questao_id: desafioQuestoes[desafioIdx].id, resposta: '' });
      desafioIdx++;
      showDesafioQuestion();
    }
  }, 1000);
}

// selectDesafioAlternativa is no longer needed — question-card dispatches 'answer-selected' event

async function submitDesafioRespostas() {
  clearInterval(desafioTimer);

  const body = document.getElementById('desafio-body');
  body.innerHTML = '<div style="text-align:center;padding:30px;"><div style="font-size:2rem;margin-bottom:8px;">⏳</div><div style="color:var(--text-sub);">Calculando resultados...</div></div>';

  try {
    const result = await fetch('/api/desafio-diario/responder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ respostas: desafioRespostas })
    }).then(r => r.json());

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

  body.innerHTML = `
    <div class="desafio-results">
      <div style="font-size:3rem;margin-bottom:8px;">${emoji}</div>
      <div class="desafio-results-score" style="color:${scoreColor};">${result.acertos}/${result.total}</div>
      <div class="desafio-results-xp">+${result.pontos_ganhos} XP</div>
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
