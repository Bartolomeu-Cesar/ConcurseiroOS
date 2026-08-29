// ==================== PRESENÇA SOCIAL (HEARTBEAT) ====================
// Envia periodicamente o status de atividade do usuário para que amigos
// vejam quem está estudando (prova social / incentivo).
//
// O status é inferido automaticamente da página/atividade atual, mas pode
// ser sobrescrito via setPresenceStatus(). Roda em todas as páginas.

let _presenceStatus = 'estudando';
let _presenceMateria = '';
let _presenceDetalhe = '';
let _presenceInterval = null;
const HEARTBEAT_MS = 90 * 1000; // 90s

// Mapa de apresentação dos status (espelha STATUS_VALIDOS do backend).
// `cor` é usada na bolinha de status sobre o avatar.
export const STATUS_META = {
  estudando: { label: 'Estudando', emoji: '📖', cor: '#a6e3a1' },
  focado: { label: 'Em foco (Pomodoro)', emoji: '🎯', cor: '#f38ba8' },
  revisando: { label: 'Revisando', emoji: '🔁', cor: '#cba6f7' },
  questoes: { label: 'Resolvendo questões', emoji: '✍️', cor: '#89b4fa' },
  simulado: { label: 'Fazendo simulado', emoji: '⏱️', cor: '#fab387' },
  lendo: { label: 'Lendo PDF', emoji: '📄', cor: '#94e2d5' },
  descansando: { label: 'Descansando', emoji: '☕', cor: '#f9e2af' },
  offline: { label: 'Offline', emoji: '💤', cor: '#6c7086' },
};

/**
 * Retorna o status de presença atual do usuário (o mesmo enviado no heartbeat):
 * o override manual quando definido, ou o inferido da página.
 * @returns {{status:string, label:string, emoji:string, cor:string}}
 */
export function getCurrentPresenceStatus() {
  const status = _presenceStatus && _presenceStatus !== 'auto'
    ? _presenceStatus
    : _inferStatus().status;
  const meta = STATUS_META[status] || STATUS_META.estudando;
  return { status, ...meta };
}
window.getCurrentPresenceStatus = getCurrentPresenceStatus;

/** Infere o status a partir da URL/página atual. */
function _inferStatus() {
  const path = (location.pathname || '').toLowerCase();
  // Timer Pomodoro ativo tem prioridade → foco
  try {
    if (localStorage.getItem('pomo_timer')) return { status: 'focado' };
  } catch (e) {}

  if (path.includes('viewer') || path.includes('leitor')) return { status: 'lendo' };
  if (path.includes('flashcard')) return { status: 'revisando' };
  if (path.includes('simulado')) return { status: 'simulado' };
  if (path.includes('quest')) return { status: 'questoes' };
  return { status: 'estudando' };
}

async function _sendHeartbeat() {
  if (document.hidden) return; // Não bate se aba não está visível
  const inferred = _inferStatus();
  const body = {
    status: _presenceStatus === 'auto' ? inferred.status : _presenceStatus,
    materia: _presenceMateria || '',
    detalhe: _presenceDetalhe || '',
  };
  try {
    const token = localStorage.getItem('auth_token');
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    await fetch('/api/social/status', { method: 'POST', headers, body: JSON.stringify(body) });
  } catch (e) { /* silencioso */ }
}

/** Define manualmente o status (ex: 'descansando', 'focado'). 'auto' = inferir. */
export function setPresenceStatus(status, materia = '', detalhe = '') {
  _presenceStatus = status;
  _presenceMateria = materia;
  _presenceDetalhe = detalhe;
  _sendHeartbeat();
}
window.setPresenceStatus = setPresenceStatus;

/** Inicia o heartbeat automático. Chamado uma vez por página. */
export function startPresence() {
  if (_presenceInterval) return;
  _presenceStatus = 'auto';
  _sendHeartbeat(); // Imediato
  _presenceInterval = setInterval(_sendHeartbeat, HEARTBEAT_MS);

  // Marcar offline ao sair
  window.addEventListener('beforeunload', () => {
    try {
      const token = localStorage.getItem('auth_token');
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      // sendBeacon não suporta headers custom; usa fetch keepalive
      fetch('/api/social/status/offline', { method: 'POST', headers, keepalive: true });
    } catch (e) {}
  });

  // Re-bate ao voltar para a aba
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) _sendHeartbeat();
  });
}
window.startPresence = startPresence;

/** Renderiza o widget de amigos ativos em um container (por id). */
export async function renderFriendsPresence(containerId = 'friends-presence') {
  const container = document.getElementById(containerId);
  if (!container) return;
  try {
    const token = localStorage.getItem('auth_token');
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch('/api/social/status/amigos', { headers });
    const data = await res.json();
    const amigos = data.amigos || [];

    if (!amigos.length) {
      container.innerHTML = '<div style="font-size:0.8rem;color:var(--text-sub,#9399b2);padding:8px;">Adicione amigos para ver quem está estudando! 👋</div>';
      return;
    }

    const online = amigos.filter(a => a.online);
    const header = `<div style="font-size:0.82rem;font-weight:600;color:var(--text,#cdd6f4);margin-bottom:8px;">👥 Amigos ativos (${data.online_count}/${data.total})</div>`;

    const items = amigos.map(a => `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 4px;opacity:${a.online ? '1' : '0.5'};">
        <div style="position:relative;font-size:1.3rem;">
          ${a.avatar}
          <span style="position:absolute;bottom:-2px;right:-2px;width:10px;height:10px;border-radius:50%;background:${a.online ? '#a6e3a1' : '#6c7086'};border:2px solid var(--bg,#1e1e2e);"></span>
        </div>
        <div style="flex:1;min-width:0;overflow:hidden;">
          <div style="font-size:0.8rem;color:var(--text,#cdd6f4);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtmlLocal(a.nome)}</div>
          <div style="font-size:0.7rem;color:var(--text-sub,#9399b2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
            ${a.online ? `${a.status_emoji} ${a.status_label}${a.materia ? ' · ' + escapeHtmlLocal(a.materia) : ''}` : '💤 Offline'}
          </div>
        </div>
      </div>
    `).join('');

    container.innerHTML = header + items;
  } catch (e) {
    container.innerHTML = '';
  }
}
window.renderFriendsPresence = renderFriendsPresence;

/** Busca a mensagem motivacional de resumo. */
export async function getPresenceResumo() {
  try {
    const token = localStorage.getItem('auth_token');
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch('/api/social/status/resumo', { headers });
    return await res.json();
  } catch (e) {
    return null;
  }
}
window.getPresenceResumo = getPresenceResumo;

function escapeHtmlLocal(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}
