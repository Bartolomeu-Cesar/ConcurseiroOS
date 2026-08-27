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
