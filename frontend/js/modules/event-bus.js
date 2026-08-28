/**
 * EventBus — Comunicação centralizada entre módulos do ConcurseiroOS
 *
 * Permite que módulos emitam eventos e outros escutem sem imports circulares.
 *
 * Eventos emitidos:
 *   'questao:respondida'    → { materia, topico, acertou, tempo_seg }
 *   'flashcard:revisado'    → { materia, quality, acertou }
 *   'desafio:completado'    → { tipo, pontos }
 *   'topico:concluido'      → { id, materia, topico }
 *   'topico:iniciado'       → { id, materia, topico }
 *   'sessao:horas'          → { materia, horas, tipo }
 *   'xp:ganho'              → { quantidade, fonte }
 *   'fadiga:detectada'      → { nivel, sugestao }
 *   'milestone:alcancado'   → { emoji, titulo, pct }
 *   'boss:derrotado'        → { tier, dano }
 *
 * Uso:
 *   import { emit, on } from './modules/event-bus.js';
 *   emit('questao:respondida', { materia: 'Direito', acertou: true });
 *   on('questao:respondida', (data) => { ... });
 */

const _listeners = {};

/**
 * Emite evento para todos os listeners registrados
 * @param {string} event — nome do evento
 * @param {object} data — dados do evento
 */
export function emit(event, data = {}) {
  if (_listeners[event]) {
    _listeners[event].forEach(fn => {
      try { fn(data); } catch(e) { console.error(`[EventBus] Error in ${event} handler:`, e); }
    });
  }
  // Também dispara CustomEvent no document (para código legado/inline)
  document.dispatchEvent(new CustomEvent(`app:${event}`, { detail: data }));
}

/**
 * Registra listener para um evento
 * @param {string} event — nome do evento
 * @param {function} handler — callback
 * @returns {function} unsubscribe function
 */
export function on(event, handler) {
  if (!_listeners[event]) _listeners[event] = [];
  _listeners[event].push(handler);
  return () => { _listeners[event] = _listeners[event].filter(fn => fn !== handler); };
}

/**
 * Registra listener que executa apenas 1 vez
 */
export function once(event, handler) {
  const unsub = on(event, (data) => { unsub(); handler(data); });
  return unsub;
}

// Expose globally for inline onclick and non-module scripts
window._eventBus = { emit, on, once };
