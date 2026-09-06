/**
 * XP Real-time Notification Module
 *
 * Shows a floating "+X XP" animation after each action (flashcard, questão, etc.)
 * Lightweight, no dependencies. Auto-injects CSS on first use.
 *
 * Usage:
 *   import { showXpGain } from './modules/xp-notify.js';
 *   showXpGain(10);           // "+10 XP" default
 *   showXpGain(5, '🧠');      // "+5 XP" with custom icon
 *   showXpGain(50, '🎯', 'Desafio completo!');  // With label
 */

let _stylesInjected = false;

function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;
  const style = document.createElement('style');
  style.id = 'xp-notify-styles';
  style.textContent = `
    .xp-notify {
      position: fixed;
      bottom: 80px;
      right: 24px;
      display: flex;
      align-items: center;
      gap: 6px;
      background: linear-gradient(135deg, rgba(203,166,247,0.95), rgba(137,180,250,0.95));
      color: #1e1e2e;
      font-weight: 800;
      font-size: 1rem;
      padding: 8px 16px;
      border-radius: 12px;
      box-shadow: 0 4px 20px rgba(203,166,247,0.4);
      z-index: 10000;
      pointer-events: none;
      animation: xpFlyUp 1.8s ease-out forwards;
      font-family: system-ui, -apple-system, sans-serif;
    }
    .xp-notify .xp-label {
      font-size: 0.72rem;
      font-weight: 600;
      opacity: 0.8;
    }
    @keyframes xpFlyUp {
      0% { opacity: 0; transform: translateY(20px) scale(0.8); }
      15% { opacity: 1; transform: translateY(0) scale(1.1); }
      30% { transform: translateY(-5px) scale(1); }
      70% { opacity: 1; transform: translateY(-10px); }
      100% { opacity: 0; transform: translateY(-40px) scale(0.9); }
    }
    @media (max-width: 600px) {
      .xp-notify {
        bottom: 70px;
        right: 16px;
        font-size: 0.9rem;
        padding: 6px 12px;
      }
    }
  `;
  document.head.appendChild(style);
}

/**
 * Show XP gain notification
 * @param {number} amount - XP gained
 * @param {string} icon - Emoji icon (default: ⚡)
 * @param {string} label - Optional sub-label (e.g. "Flashcard", "Questão correta")
 */
export function showXpGain(amount, icon = '⚡', label = '') {
  if (!amount || amount <= 0) return;
  _injectStyles();

  const el = document.createElement('div');
  el.className = 'xp-notify';
  el.innerHTML = `${icon} +${amount} XP${label ? `<span class="xp-label">${label}</span>` : ''}`;
  document.body.appendChild(el);

  // Remove after animation completes
  setTimeout(() => el.remove(), 2000);
}

/**
 * Show XP for flashcard review
 * @param {number} quality - Review quality (0-5)
 */
export function showFlashcardXp(quality) {
  const xp = quality >= 3 ? 5 : 2; // Acerto = 5xp, erro/difícil = 2xp (esforço)
  showXpGain(xp, '🧠', quality >= 3 ? '' : 'esforço');
}

/**
 * Show XP for question answer
 * @param {boolean} correct - Whether the answer was correct
 */
export function showQuestionXp(correct) {
  if (correct) {
    showXpGain(10, '✅', 'questão correta');
  } else {
    showXpGain(5, '📝', 'questão resolvida');
  }
}

// Expose globally for inline onclick compatibility
window.showXpGain = showXpGain;

// ==================== CELEBRAÇÃO DE MARCOS (MILESTONES) ====================
// Catálogo de marcos com mensagem e ícone. Cada marco dispara UMA VEZ (persistido em
// localStorage) para não repetir a celebração. Ex.: primeiro acerto, streak de 7 dias.
const _MILESTONES = {
  primeira_questao: { icon: '🎯', title: 'Primeira questão!', msg: 'Você começou a praticar. O primeiro passo é o mais importante.' },
  primeiro_flashcard: { icon: '🧠', title: 'Primeiro flashcard!', msg: 'A repetição espaçada vai fixar isso na sua memória.' },
  streak_7: { icon: '🔥', title: '7 dias seguidos!', msg: 'Uma semana de constância. É assim que se constrói aprovação.' },
  streak_30: { icon: '🏆', title: '30 dias de streak!', msg: 'Um mês sem falhar. Você está no jogo pra valer.' },
  subiu_liga: { icon: '⬆️', title: 'Subiu de liga!', msg: 'Seu esforço te levou para o próximo nível. Continue!' },
  primeiro_simulado: { icon: '📝', title: 'Primeiro simulado!', msg: 'Simular a prova é treino de verdade. Mandou bem!' },
  nivel_100_questoes: { icon: '💯', title: '100 questões resolvidas!', msg: 'Centena batida. A prática leva à perfeição.' },
};

function _injectMilestoneStyles() {
  if (document.getElementById('milestone-styles')) return;
  const style = document.createElement('style');
  style.id = 'milestone-styles';
  style.textContent = `
    .milestone-toast {
      position: fixed; top: 24px; left: 50%; transform: translateX(-50%) translateY(-20px);
      display: flex; align-items: center; gap: 12px;
      background: var(--bg-surface, #313244); color: var(--text, #cdd6f4);
      border: 1px solid var(--border, #45475a);
      border-left: 4px solid var(--accent, #cba6f7);
      border-radius: 14px; padding: 14px 20px 14px 16px;
      box-shadow: 0 12px 40px rgba(0,0,0,0.35);
      z-index: 10001; opacity: 0; max-width: 92vw;
      animation: milestoneIn 0.5s cubic-bezier(0.16,1,0.3,1) forwards;
    }
    .milestone-toast .m-icon {
      font-size: 2rem; line-height: 1;
      width: 52px; height: 52px; flex-shrink: 0;
      display: flex; align-items: center; justify-content: center; border-radius: 50%;
      background: radial-gradient(circle at 30% 30%, rgba(203,166,247,0.28), rgba(137,180,250,0.14));
    }
    .milestone-toast .m-title { font-weight: 800; font-size: 0.95rem; color: var(--accent, #cba6f7); }
    .milestone-toast .m-msg { font-size: 0.8rem; color: var(--text-sub, #9399b2); margin-top: 2px; line-height: 1.4; }
    .milestone-toast.leaving { animation: milestoneOut 0.4s ease forwards; }
    @keyframes milestoneIn { to { opacity: 1; transform: translateX(-50%) translateY(0); } }
    @keyframes milestoneOut { to { opacity: 0; transform: translateX(-50%) translateY(-20px); } }
    @media (prefers-reduced-motion: reduce) {
      .milestone-toast, .milestone-toast.leaving { animation: none; opacity: 1; transform: translateX(-50%); }
    }
  `;
  document.head.appendChild(style);
}

/**
 * Celebra um marco (uma vez por marco). Mostra um banner especial + confete.
 * @param {string} key - chave do marco em _MILESTONES
 * @param {object} opts - { force: ignora o "uma vez"; confetti: bool (default true) }
 */
export function celebrateMilestone(key, opts = {}) {
  const m = _MILESTONES[key];
  if (!m) return;
  const storeKey = `milestone_${key}`;
  if (!opts.force && localStorage.getItem(storeKey)) return; // já celebrado
  localStorage.setItem(storeKey, '1');

  _injectMilestoneStyles();
  const el = document.createElement('div');
  el.className = 'milestone-toast';
  el.setAttribute('role', 'status');
  el.setAttribute('aria-live', 'polite');
  el.innerHTML = `<div class="m-icon" aria-hidden="true">${m.icon}</div><div><div class="m-title">${m.title}</div><div class="m-msg">${m.msg}</div></div>`;
  document.body.appendChild(el);

  // Confete (reusa o de ui.js se disponível globalmente)
  if (opts.confetti !== false && typeof window.launchConfetti === 'function') {
    try { window.launchConfetti(1600); } catch (e) {}
  }

  setTimeout(() => { el.classList.add('leaving'); setTimeout(() => el.remove(), 400); }, 4200);
}

window.celebrateMilestone = celebrateMilestone;
