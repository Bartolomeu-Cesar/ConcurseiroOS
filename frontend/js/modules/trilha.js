// ==================== TRILHA DE ESTUDO (ROADMAP) ====================
// Visualização longitudinal do percurso de estudo: etapas por tópico do edital
// com estado concluída / atual / bloqueada. Consome os endpoints da Fase 1/2:
//   GET  /api/trilha
//   POST /api/trilha/gerar
//   POST /api/trilha/etapas/{id}/concluir
//
// Técnicas: Progress Milestones (marcos de progresso) + desbloqueio progressivo
// (Desirable Difficulty). Integra com Ciclo (matérias) e Knowledge Graph (ordem).

import { api, toast, escapeHtml, confirmModal, showLoading } from './utils.js';

const STATUS_META = {
  concluida: { icon: '✅', cor: 'var(--green, #a6e3a1)', label: 'Concluída' },
  atual: { icon: '🔵', cor: 'var(--accent, #cba6f7)', label: 'Atual' },
  bloqueada: { icon: '🔒', cor: 'var(--text-sub, #6c7086)', label: 'Bloqueada' },
};

export async function loadTrilha() {
  const container = document.getElementById('trilha-roadmap');
  if (!container) return;
  showLoading('trilha-roadmap');
  try {
    const data = await api('/api/trilha');
    renderTrilha(data);
  } catch {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">🧭</div>
      <div class="empty-msg">Não foi possível carregar a trilha. Tente novamente.</div></div>`;
  }
}

function renderTrilha(data) {
  const container = document.getElementById('trilha-roadmap');
  const progressoBox = document.getElementById('trilha-progresso');
  if (!container) return;

  if (!data || !data.trilha) {
    if (progressoBox) progressoBox.innerHTML = '';
    container.innerHTML = `<div class="empty-state">
      <div class="empty-icon">🧭</div>
      <div class="empty-msg">Você ainda não tem uma trilha de estudo.<br>
      Gere uma a partir do seu ciclo e do edital para ver o caminho ideal, etapa por etapa.</div>
      <button class="iobtn" style="margin-top:12px;" onclick="gerarTrilha()">🚀 Gerar minha trilha</button>
    </div>`;
    return;
  }

  const { etapas = [], progresso } = data;

  // Barra de progresso + resumo
  if (progressoBox && progresso) {
    const pct = progresso.pct_conclusao || 0;
    const atualTxt = progresso.etapa_atual
      ? `${escapeHtml(progresso.etapa_atual.materia)} · ${escapeHtml(progresso.etapa_atual.topico)}`
      : (progresso.concluida ? '🎉 Trilha concluída!' : '—');
    progressoBox.innerHTML = `
      <div class="trilha-progress-head">
        <span>${progresso.concluidas}/${progresso.total_etapas} etapas</span>
        <span>${pct}%</span>
      </div>
      <div class="trilha-progress-bar"><div class="trilha-progress-fill" style="width:${pct}%;"></div></div>
      <div class="trilha-progress-atual">📍 Agora: <strong>${atualTxt}</strong></div>
    `;
  }

  if (!etapas.length) {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">🧭</div>
      <div class="empty-msg">Trilha sem etapas. Adicione tópicos ao edital e gere novamente.</div></div>`;
    return;
  }

  container.innerHTML = etapas.map(e => _etapaHtml(e)).join('');
}

function _etapaHtml(e) {
  const meta = STATUS_META[e.status] || STATUS_META.bloqueada;
  const acao = e.status === 'atual'
    ? `<button class="trilha-btn-concluir" onclick="concluirEtapaTrilha(${e.id})" title="Marcar etapa como concluída">✓ Concluir</button>`
    : (e.status === 'bloqueada'
        ? '<span class="trilha-etapa-lock" title="Conclua a etapa anterior">🔒</span>'
        : '<span class="trilha-etapa-done" title="Concluída">✓</span>');

  return `
    <div class="trilha-etapa trilha-etapa--${e.status}">
      <div class="trilha-etapa-marker" style="--marker-cor:${meta.cor};">
        <span class="trilha-etapa-num">${e.ordem}</span>
      </div>
      <div class="trilha-etapa-body">
        <div class="trilha-etapa-materia">${escapeHtml(e.materia)}</div>
        <div class="trilha-etapa-topico">${escapeHtml(e.topico)}</div>
        <div class="trilha-etapa-razao">${meta.icon} ${escapeHtml(e.razao || meta.label)}</div>
      </div>
      <div class="trilha-etapa-acao">${acao}</div>
    </div>
  `;
}

export async function gerarTrilha() {
  const existente = document.querySelector('.trilha-etapa');
  if (existente) {
    const ok = await confirmModal(
      'Gerar nova trilha?',
      'Isso substitui a trilha atual por uma nova baseada no ciclo e no edital. O progresso das etapas será recalculado (tópicos já concluídos permanecem concluídos).',
      { type: 'warning', confirmText: 'Gerar', cancelText: 'Cancelar' }
    );
    if (!ok) return;
  }
  const btns = document.querySelectorAll('[onclick="gerarTrilha()"]');
  btns.forEach(b => { b.disabled = true; });
  try {
    const res = await fetch('/api/trilha/gerar', { method: 'POST', headers: _authHeaders() });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 400) {
        // Backend explica: "monte o ciclo" ou "matérias do ciclo sem tópicos"
        toast(data.detail || 'Monte seu ciclo de estudos antes de gerar a trilha.', 'warning');
      } else {
        toast(data.detail || 'Erro ao gerar trilha.', 'error');
      }
      return;
    }
    renderTrilha(data);
    toast('🧭 Trilha gerada!', 'success');
  } catch {
    toast('Erro de conexão ao gerar trilha.', 'error');
  } finally {
    btns.forEach(b => { b.disabled = false; });
  }
}

export async function concluirEtapaTrilha(etapaId) {
  try {
    const res = await fetch(`/api/trilha/etapas/${etapaId}/concluir`, { method: 'POST', headers: _authHeaders() });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      toast(res.status === 409 ? 'Conclua a etapa anterior primeiro.' : (data.detail || 'Erro ao concluir etapa.'), 'error');
      return;
    }
    renderTrilha(data);
    const xp = data.xp_topico || 0;
    if (data.progresso && data.progresso.concluida) {
      toast('🎉 Trilha concluída! Parabéns!', 'success');
    } else {
      toast(xp > 0 ? `✅ Etapa concluída! +${xp} XP` : '✅ Etapa concluída!', 'success');
    }
  } catch {
    toast('Erro de conexão ao concluir etapa.', 'error');
  }
}

function _authHeaders() {
  const h = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem('auth_token');
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

export async function sincronizarTrilhaCalendario() {
  const temTrilha = document.querySelector('.trilha-etapa');
  if (!temTrilha) {
    toast('Gere uma trilha antes de agendar no calendário.', 'warning');
    return;
  }
  const ok = await confirmModal(
    'Agendar no calendário?',
    'As próximas etapas pendentes da trilha serão distribuídas pelos dias úteis do seu calendário (60 min cada). Agendamentos anteriores da trilha serão substituídos; suas outras atividades permanecem.',
    { type: 'info', confirmText: 'Agendar', cancelText: 'Cancelar' }
  );
  if (!ok) return;
  try {
    const res = await fetch('/api/trilha/sincronizar-calendario', { method: 'POST', headers: _authHeaders() });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      toast(data.detail || 'Erro ao agendar no calendário.', 'error');
      return;
    }
    toast(`📅 ${data.agendadas} etapa(s) agendadas no calendário!`, 'success');
  } catch {
    toast('Erro de conexão ao agendar no calendário.', 'error');
  }
}

export function initTrilha() {
  // Carrega se a aba já estiver ativa no load
  const tab = document.getElementById('tab-trilha');
  if (tab && tab.classList.contains('active')) {
    loadTrilha();
  }
}

// Expor para onclick inline (regra #4)
window.loadTrilha = loadTrilha;
window.gerarTrilha = gerarTrilha;
window.concluirEtapaTrilha = concluirEtapaTrilha;
window.sincronizarTrilhaCalendario = sincronizarTrilhaCalendario;
