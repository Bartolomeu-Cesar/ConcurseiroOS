/**
 * Fatigue Detection Module — Tracking intra-sessão
 *
 * Integra com backend:
 *   POST /api/sessao/iniciar     — inicia tracking
 *   POST /api/sessao/heartbeat   — envia métricas por questão
 *   GET  /api/sessao/{id}/resumo — resultado final
 *
 * Uso:
 *   import { startFatigueSession, sendHeartbeat, endFatigueSession } from './fatigue-tracker.js';
 *   const session = await startFatigueSession('Direito Constitucional');
 *   // Após cada questão:
 *   const status = await sendHeartbeat(tempoMs, acertou);
 *   // status.status pode ser: 'flow', 'fadiga_leve', 'fadiga_moderada', 'fadiga_alta'
 *   // Ao encerrar:
 *   const resumo = await endFatigueSession();
 */

import { showToast } from './toast.js';

let _sessionId = null;
let _questaoNum = 0;
let _materia = '';
let _alertShown = {}; // Evitar alertas repetidos

function _getHeaders() {
  const token = localStorage.getItem('auth_token');
  const h = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

/**
 * Inicia uma sessão de tracking de fadiga
 * @param {string} materia — matéria sendo estudada
 * @param {string} tipo — 'questoes' | 'flashcards' | 'leitura'
 * @returns {{ session_id, materia, tipo }}
 */
export async function startFatigueSession(materia = '', tipo = 'questoes') {
  try {
    const res = await fetch('/api/sessao/iniciar', {
      method: 'POST',
      headers: _getHeaders(),
      body: JSON.stringify({ materia, tipo }),
    }).then(r => r.json());

    if (res.ok) {
      _sessionId = res.session_id;
      _questaoNum = 0;
      _materia = materia || '';
      _alertShown = {};
      return res;
    }
  } catch (e) {
    // Silently fail — tracking não é crítico
  }
  return null;
}

/**
 * Envia heartbeat após cada questão/card respondido
 * @param {number} tempoMs — tempo gasto na questão (ms)
 * @param {boolean} acertou — se acertou
 * @returns {{ status, metricas, sugestao } | null}
 */
export async function sendHeartbeat(tempoMs, acertou) {
  if (!_sessionId) return null;
  _questaoNum++;

  try {
    const res = await fetch('/api/sessao/heartbeat', {
      method: 'POST',
      headers: _getHeaders(),
      body: JSON.stringify({
        session_id: _sessionId,
        questao_num: _questaoNum,
        tempo_ms: tempoMs,
        acertou: Boolean(acertou),
      }),
    }).then(r => r.json());

    // Mostrar alertas baseado no status
    _handleFatigueAlert(res);

    return res;
  } catch (e) {
    return null;
  }
}

/**
 * Mostra alertas de fadiga ao estudante
 */
function _handleFatigueAlert(res) {
  if (!res || !res.status) return;

  const { status, sugestao, metricas } = res;

  // Alerta leve — mostrar apenas uma vez
  if (status === 'fadiga_leve' && !_alertShown.leve) {
    _alertShown.leve = true;
    _showFatigueToast('⚠️ Fadiga leve detectada', sugestao, 'warning');
  }

  // Alerta moderado — banner persistente
  if (status === 'fadiga_moderada' && !_alertShown.moderada) {
    _alertShown.moderada = true;
    _showFatigueBanner('fadiga_moderada', sugestao, metricas);
  }

  // Alerta alto — banner urgente + sugestão de parar
  if (status === 'fadiga_alta' && !_alertShown.alta) {
    _alertShown.alta = true;
    _showFatigueBanner('fadiga_alta', sugestao, metricas);
  }
}

function _showFatigueToast(title, msg, type) {
  showToast(`${title}: ${msg}`, type, 6000);
}

function _showFatigueBanner(level, sugestao, metricas) {
  // Remover banner anterior se existir
  const existing = document.getElementById('fatigue-banner');
  if (existing) existing.remove();

  const isHigh = level === 'fadiga_alta';
  const borderColor = isHigh ? '#f38ba8' : '#f9e2af';
  const icon = isHigh ? '🛑' : '⚠️';
  const bgColor = isHigh ? 'rgba(243,139,168,0.1)' : 'rgba(249,226,175,0.1)';

  const banner = document.createElement('div');
  banner.id = 'fatigue-banner';
  banner.style.cssText = `
    position: fixed;
    bottom: 80px;
    left: 50%;
    transform: translateX(-50%);
    max-width: 420px;
    width: 90%;
    background: var(--bg-elevated, #45475a);
    border: 2px solid ${borderColor};
    border-radius: 14px;
    padding: 16px 20px;
    z-index: 9999;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    animation: slideUp 0.3s ease;
  `;

  const pctQueda = metricas
    ? Math.round(((metricas.pct_acerto_inicio - metricas.pct_acerto_recente) / Math.max(metricas.pct_acerto_inicio, 1)) * 100)
    : 0;

  banner.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
      <span style="font-size:1.5rem;">${icon}</span>
      <div style="flex:1;">
        <div style="font-weight:700;color:var(--text, #cdd6f4);font-size:0.92rem;">
          ${isHigh ? 'Fadiga Alta — Hora de Parar!' : 'Fadiga Moderada — Troque de Atividade'}
        </div>
        <div style="font-size:0.78rem;color:var(--text-sub, #9399b2);margin-top:2px;">${sugestao}</div>
      </div>
      <button onclick="document.getElementById('fatigue-banner').remove()" style="background:none;border:none;color:var(--text-sub);font-size:1.2rem;cursor:pointer;padding:4px;" title="Fechar">✕</button>
    </div>
    ${metricas ? `
      <div style="display:flex;gap:12px;font-size:0.72rem;color:var(--text-sub, #9399b2);background:${bgColor};border-radius:8px;padding:8px 12px;">
        <span>📊 ${metricas.questoes_respondidas} questões</span>
        <span>⏱ ${metricas.duracao_sessao_min.toFixed(0)}min</span>
        <span>📉 Acerto: ${metricas.pct_acerto_inicio.toFixed(0)}% → ${metricas.pct_acerto_recente.toFixed(0)}%${pctQueda > 0 ? ` (-${pctQueda}%)` : ''}</span>
      </div>
    ` : ''}
    <div style="display:flex;gap:8px;margin-top:10px;">
      <button onclick="document.getElementById('fatigue-banner').remove();window.location.href='/'" style="flex:1;padding:8px;background:var(--green, #a6e3a1);color:#1e1e2e;border:none;border-radius:8px;font-weight:600;font-size:0.82rem;cursor:pointer;">
        ${isHigh ? '🛑 Encerrar Sessão' : '🔄 Trocar Matéria'}
      </button>
      <button onclick="document.getElementById('fatigue-banner').remove()" style="flex:1;padding:8px;background:var(--border, #45475a);color:var(--text);border:none;border-radius:8px;font-size:0.82rem;cursor:pointer;">
        Continuar Mesmo Assim
      </button>
    </div>
  `;

  document.body.appendChild(banner);

  // Auto-dismiss após 30s
  setTimeout(() => { if (banner.parentNode) banner.remove(); }, 30000);
}

/**
 * Encerra a sessão e retorna resumo
 * @returns {{ total_questoes, acertos, percentual_acerto, tempo_medio_ms, pico_performance, queda_detectada_em, duracao_total_min } | null}
 */
export async function endFatigueSession() {
  if (!_sessionId) return null;

  try {
    const res = await fetch(`/api/sessao/${_sessionId}/resumo`, {
      headers: _getHeaders(),
    }).then(r => r.json());

    // Reset state
    const sessionId = _sessionId;
    _sessionId = null;
    _questaoNum = 0;
    _alertShown = {};

    if (res.ok) {
      return res;
    }
  } catch (e) {}
  return null;
}

/**
 * Retorna se há sessão ativa
 */
export function hasActiveSession() {
  return _sessionId !== null;
}

/**
 * Retorna o session_id atual (para uso externo)
 */
export function getSessionId() {
  return _sessionId;
}

// Inject keyframe animation
if (!document.getElementById('fatigue-anim-style')) {
  const style = document.createElement('style');
  style.id = 'fatigue-anim-style';
  style.textContent = `
    @keyframes slideUp {
      from { opacity: 0; transform: translateX(-50%) translateY(30px); }
      to { opacity: 1; transform: translateX(-50%) translateY(0); }
    }
  `;
  document.head.appendChild(style);
}

// Window exposure
window.endFatigueSession = endFatigueSession;
