// ==================== TAB 2: EDITAL ====================
import { state } from './state.js';
import { escapeHtml, toast, showLoading, undoableDelete, confirmModal, formatHours } from './utils.js';
import { openSelectModal } from './modal-selecao.js';
import { switchTab } from './tabs.js';

let editalTimer = null, editalStartedAt = null, editalElapsed = 0, editalPaused = false;
let editalInfo = [];
const EDITAL_OPEN_KEY = 'edital_accordion_state';

// Dependências injetadas
let _loadMetas = null;
let _loadStreakBadge = null;
let _getConfigSessoes = null;
let _linkPdfToTopic = null;
let _linkPdfToMateria = null;
let _openNoteModal = null;

function editalFmt(s) { return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }
function editalTick() {
  if (editalPaused || !editalStartedAt) return;
  editalElapsed = Math.floor((Date.now() - editalStartedAt) / 1000);
  const display = document.getElementById('edital-timer-display');
  if (display) display.textContent = editalFmt(editalElapsed);
}

function getAccordionState() { try { return JSON.parse(sessionStorage.getItem(EDITAL_OPEN_KEY)) || {}; } catch { return {}; } }
function saveAccordionState(s) { sessionStorage.setItem(EDITAL_OPEN_KEY, JSON.stringify(s)); }
function getStatusClass(s) { return s === 'Em Andamento' ? 'status-em-andamento' : s === 'Concluído' ? 'status-concluido' : 'status-nao-iniciado'; }

export async function loadEdital() {
  showLoading('edital-accordion');
  try {
    const [dataRes, infoRes] = await Promise.all([
      fetch('/api/edital').then(r => r.json()),
      fetch('/api/edital/info').then(r => r.ok ? r.json() : [])
    ]);
    state.editalData = dataRes;
    editalInfo = infoRes;
  } catch (e) {
    try {
      state.editalData = await fetch('/api/edital').then(r => r.json());
      editalInfo = [];
    } catch (e2) {
      state.editalData = [];
      editalInfo = [];
      toast('Erro ao carregar edital', 'error');
    }
  }
  renderEditalTree();
  loadSpacingAlert();
  loadKnowledgeGraph();
}

async function loadSpacingAlert() {
  try {
    const data = await fetch('/api/spacing/resumo').then(r => r.json());
    const el = document.getElementById('spacing-alert');
    if (!el) return;

    const pendentes = data.precisam_revisao || 0;
    if (pendentes === 0) {
      el.style.display = 'none';
      return;
    }

    el.style.display = 'block';
    const overdueText = data.overdue > 0 ? `<span style="color:var(--red);font-weight:600;">${data.overdue} atrasados</span>` : '';
    const dueText = data.due > 0 ? `<span style="color:var(--yellow);">${data.due} na hora</span>` : '';
    const separator = overdueText && dueText ? ' · ' : '';

    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span style="font-size:1.2rem;">📐</span>
        <div>
          <div style="font-size:0.85rem;font-weight:600;">Spacing Calculator</div>
          <div style="font-size:0.78rem;color:var(--text-sub);">
            ${pendentes} tópico${pendentes > 1 ? 's' : ''} precisa${pendentes > 1 ? 'm' : ''} de revisão: ${overdueText}${separator}${dueText}
          </div>
        </div>
        <button onclick="showSpacingDetails()" style="margin-left:auto;background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:5px 12px;font-size:0.78rem;font-weight:600;cursor:pointer;">Ver tópicos</button>
      </div>`;
  } catch (e) {}
}

export async function showSpacingDetails() {
  try {
    const data = await fetch('/api/spacing?apenas_pendentes=true').then(r => r.json());
    const topicos = data.topicos || [];
    if (topicos.length === 0) { toast('Nenhum tópico pendente de revisão.', 'info'); return; }

    const urgencyColors = { overdue: 'var(--red)', due: 'var(--yellow)', soon: 'var(--blue)', ok: 'var(--green)' };
    const urgencyLabels = { overdue: '⚠️ Atrasado', due: '🔔 Na hora', soon: '📅 Em breve', ok: '✅ OK' };

    let html = topicos.slice(0, 20).map(t => `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);">
        <span style="color:${urgencyColors[t.urgency]};font-size:0.72rem;font-weight:600;min-width:70px;">${urgencyLabels[t.urgency]}</span>
        <div style="flex:1;min-width:0;">
          <div style="font-size:0.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${t.topico}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">${t.materia} · Gap ideal: ${t.optimal_gap_dias}d · Última: ${t.days_since_review === 999 ? 'nunca' : t.days_since_review + 'd atrás'}</div>
        </div>
      </div>`).join('');

    if (topicos.length > 20) html += `<div style="font-size:0.72rem;color:var(--text-sub);padding:8px 0;">...e mais ${topicos.length - 20} tópicos</div>`;

    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `
      <div style="background:var(--bg-elevated);border-radius:16px;padding:20px;max-width:500px;width:92%;max-height:80vh;overflow-y:auto;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <h3 style="font-size:1rem;">📐 Tópicos para Revisão</h3>
          <button onclick="this.closest('div[style*=fixed]').remove()" style="background:none;border:none;color:var(--text-sub);cursor:pointer;font-size:1.2rem;">✕</button>
        </div>
        <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:12px;">
          Retenção desejada: <strong>${Math.round(data.desired_retention * 100)}%</strong> · ${data.overdue} atrasados · ${data.due} na hora
        </div>
        ${html}
      </div>`;
    document.body.appendChild(modal);
  } catch (e) { toast('Erro ao carregar spacing', 'error'); }
}

function renderEditalTree() {
  const container = document.getElementById('edital-accordion');
  const accState = getAccordionState();
  if (state.editalData.length === 0) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-msg">Nenhum edital cadastrado ainda. Use o formulário abaixo para adicionar matérias e tópicos, ou importe um PDF de edital.</div></div>';
    return;
  }
  const tree = {};
  for (const item of state.editalData) {
    const concurso = item.edital_nome || 'Geral';
    const cargo = item.cargo || 'Geral';
    const mat = item.materia;
    if (!tree[concurso]) tree[concurso] = {};
    if (!tree[concurso][cargo]) tree[concurso][cargo] = {};
    if (!tree[concurso][cargo][mat]) tree[concurso][cargo][mat] = [];
    tree[concurso][cargo][mat].push(item);
  }
  const total = state.editalData.length;
  const concluidos = state.editalData.filter(i => i.status === 'Concluído').length;
  document.getElementById('edital-stats').textContent = `${total} tópicos • ${concluidos} concluídos (${total > 0 ? Math.round(concluidos / total * 100) : 0}%)`;

  let html = '';
  const concursos = Object.keys(tree).sort();
  for (const concurso of concursos) {
    const concKey = `c_${concurso}`;
    const concOpen = accState[concKey] === true;
    const concItems = state.editalData.filter(i => i.edital_nome === concurso);
    const concDone = concItems.filter(i => i.status === 'Concluído').length;
    const concPct = concItems.length > 0 ? Math.round(concDone / concItems.length * 100) : 0;
    html += `<div class="tree-l1">
      <div class="tree-node tree-node-l1 ${concOpen ? 'open' : ''}" data-key="${concKey}" onclick="toggleTree(this)">
        <span class="tree-chevron">▶</span>
        <span class="tree-icon">📋</span>
        <span class="tree-label">${escapeHtml(concurso)}</span>
        <span class="tree-stats">${concDone}/${concItems.length} (${concPct}%)</span>
        <div class="tree-bar"><div class="tree-bar-fill" style="width:${concPct}%"></div></div>
        <button class="tree-archive-btn" onclick="event.stopPropagation();editarEdital('${concurso.replace(/'/g, "\\'")}')" title="Editar metadados">✏️</button>
        <button class="tree-archive-btn" onclick="event.stopPropagation();arquivarConcurso('${concurso.replace(/'/g, "\\'")}')" title="Arquivar concurso inteiro">📦</button>
        <button class="tree-archive-btn tree-excluir-btn" onclick="event.stopPropagation();excluirConcurso('${concurso.replace(/'/g, "\\'")}')" title="Excluir concurso inteiro" aria-label="Excluir concurso">🗑</button>
      </div>
      <div class="tree-children ${concOpen ? 'open' : ''}">`;
    const cargos = Object.keys(tree[concurso]).sort();
    for (const cargo of cargos) {
      const cargoKey = `cr_${concurso}_${cargo}`;
      const cargoOpen = accState[cargoKey] === true;
      const cargoItems = concItems.filter(i => (i.cargo || 'Geral') === cargo);
      const cargoDone = cargoItems.filter(i => i.status === 'Concluído').length;
      const cargoPct = cargoItems.length > 0 ? Math.round(cargoDone / cargoItems.length * 100) : 0;
      const info = editalInfo.find(i => i.edital_nome === concurso && i.cargo === cargo);
      const infoHtml = info ? `<div class="tree-info-badge" title="${escapeHtml(info.local_prova || '')}">
        ${info.data_prova_objetiva ? `<span>📅 ${escapeHtml(info.data_prova_objetiva)}</span>` : ''}
        ${info.subsidio ? `<span>💰 ${escapeHtml(info.subsidio)}</span>` : ''}
        ${info.vagas ? `<span>🎯 ${escapeHtml(info.vagas)}</span>` : ''}
      </div>` : '';
      html += `<div class="tree-l2">
        <div class="tree-node tree-node-l2 ${cargoOpen ? 'open' : ''}" data-key="${cargoKey}" onclick="toggleTree(this)">
          <span class="tree-chevron">▶</span>
          <span class="tree-icon">👤</span>
          <span class="tree-label">${escapeHtml(cargo)}</span>
          ${infoHtml}
          <span class="tree-stats">${cargoDone}/${cargoItems.length}</span>
          <div class="tree-bar"><div class="tree-bar-fill" style="width:${cargoPct}%"></div></div>
          <button class="tree-archive-btn" onclick="event.stopPropagation();arquivarCargo('${concurso.replace(/'/g, "\\'")}','${cargo.replace(/'/g, "\\'")}')\" title="Arquivar">📦</button>
          <button class="tree-archive-btn tree-excluir-btn" onclick="event.stopPropagation();excluirCargo('${concurso.replace(/'/g, "\\'")}','${cargo.replace(/'/g, "\\'")}')\" title="Excluir permanentemente" aria-label="Excluir cargo">🗑</button>
        </div>
        <div class="tree-children ${cargoOpen ? 'open' : ''}">`;
      if (info) {
        html += `<div class="tree-info-card">
          ${info.data_prova_objetiva ? `<div><strong>📅 Objetiva:</strong> ${escapeHtml(info.data_prova_objetiva)}</div>` : ''}
          ${info.data_prova_discursiva ? `<div><strong>📝 Discursiva:</strong> ${escapeHtml(info.data_prova_discursiva)}</div>` : ''}
          ${info.horario ? `<div><strong>🕐 Horário:</strong> ${escapeHtml(info.horario)}</div>` : ''}
          ${info.local_prova ? `<div><strong>📍 Local:</strong> ${escapeHtml(info.local_prova)}</div>` : ''}
          ${info.vagas ? `<div><strong>🎯 Vagas:</strong> ${escapeHtml(info.vagas)}</div>` : ''}
          ${info.subsidio ? `<div><strong>💰 Subsídio:</strong> ${escapeHtml(info.subsidio)}</div>` : ''}
          ${info.inscricoes ? `<div><strong>📋 Inscrições:</strong> ${escapeHtml(info.inscricoes)}</div>` : ''}
          ${info.link_edital ? `<div><a href="${escapeHtml(info.link_edital)}" target="_blank" style="color:#89b4fa;font-size:0.8rem;">🔗 Abrir edital no Cebraspe</a></div>` : ''}
        </div>`;
      }
      const materias = Object.keys(tree[concurso][cargo]).sort();
      for (const matNome of materias) {
        const matKey = `m_${concurso}_${cargo}_${matNome}`;
        const matOpen = accState[matKey] === true;
        const items = tree[concurso][cargo][matNome];
        const matDone = items.filter(i => i.status === 'Concluído').length;
        const matPct = items.length > 0 ? Math.round(matDone / items.length * 100) : 0;
        const matHoras = items.reduce((a, i) => a + i.horas_estudadas, 0);
        html += `<div class="tree-l3">
          <div class="tree-node tree-node-l3 ${matOpen ? 'open' : ''}" data-key="${matKey}" onclick="toggleTree(this)">
            <span class="tree-chevron">▶</span>
            <span class="tree-icon">📚</span>
            <span class="tree-label">${escapeHtml(matNome)}</span>
            <span class="tree-stats">${matDone}/${items.length}${matHoras > 0 ? ' • ' + formatHours(matHoras) : ''}</span>
            <div class="tree-bar"><div class="tree-bar-fill" style="width:${matPct}%"></div></div>
            <button class="tree-pdf-link-btn" style="font-size:0.7rem;" onclick="event.stopPropagation();linkPdfToMateria('${matNome.replace(/'/g, "\\\\'")}','${concurso}','${cargo}')" title="Vincular PDF à matéria">🔗</button>
          </div>
          <div class="tree-children ${matOpen ? 'open' : ''}">`;
        for (const item of items) {
          const sel = item.id === state.editalSelectedId ? ' selected' : '';
          const safeMateria = item.materia.replace(/'/g, "\\'");
          const safeTopico = item.topico.replace(/'/g, "\\'");
          const pdfBtn = item.pdf_link
            ? `<a class="tree-pdf-btn" href="viewer.html?path=${encodeURIComponent(item.pdf_link)}${item.pdf_pagina ? '#page=' + item.pdf_pagina : ''}" target="_blank" onclick="event.stopPropagation()" title="Abrir PDF">📖</a>`
            : `<button class="tree-pdf-link-btn" onclick="event.stopPropagation();linkPdfToTopic(${item.id},'${safeMateria}')" title="Vincular PDF">🔗</button>`;
          const videoBtn = item.video_link
            ? `<button class="tree-pdf-btn" onclick="event.stopPropagation();openVideoPlayer(${item.id},'${escapeHtml(item.video_link).replace(/'/g, "\\'")}','${safeTopico}')" title="Assistir vídeo">▶️</button>`
            : `<button class="tree-pdf-link-btn" onclick="event.stopPropagation();linkVideoToTopic(${item.id},'${safeTopico}')" title="Vincular vídeo YouTube">🎬</button>`;
          html += `<div class="tree-leaf${sel}" data-id="${item.id}" onclick="selectEditalTopic(${item.id}, '${safeMateria}', '${safeTopico}')">
            <span class="tree-status ${getStatusClass(item.status)}" onclick="event.stopPropagation();toggleEditalStatus(${item.id})">${item.status === 'Concluído' ? '✓' : item.status === 'Em Andamento' ? '◐' : '○'}</span>
            <span class="tree-topic">${escapeHtml(item.topico)}</span>
            ${item.horas_estudadas > 0 ? `<span class="tree-hours">${formatHours(item.horas_estudadas)}</span>` : ''}
            ${pdfBtn}
            ${videoBtn}
            <button class="tree-note" onclick="event.stopPropagation();openNoteModal(${item.id})" title="Notas">📝</button>
            <button class="tree-del" onclick="event.stopPropagation();deleteEditalItem(${item.id})">×</button>
          </div>`;
        }
        html += `</div></div>`;
      }
      html += `</div></div>`;
    }
    html += `</div></div>`;
  }
  container.innerHTML = html;
}

export function toggleTree(el) {
  const key = el.dataset.key;
  const accState = getAccordionState();
  const isOpen = el.classList.contains('open');
  el.classList.toggle('open');
  const body = el.nextElementSibling;
  if (body) body.classList.toggle('open');
  accState[key] = !isOpen;
  saveAccordionState(accState);
}

export function toggleAllEdital(expand) {
  const accState = getAccordionState();
  document.querySelectorAll('.tree-node').forEach(h => {
    const key = h.dataset.key;
    if (expand) { h.classList.add('open'); h.nextElementSibling?.classList.add('open'); accState[key] = true; }
    else { h.classList.remove('open'); h.nextElementSibling?.classList.remove('open'); accState[key] = false; }
  });
  saveAccordionState(accState);
}

export function selectEditalTopic(id, materia, topico) {
  state.editalSelectedId = id;
  const label = document.getElementById('edital-materia-label');
  if (label) label.textContent = `📖 ${materia} — ${topico}`;
  document.querySelectorAll('.tree-leaf').forEach(r => r.classList.remove('selected'));
  const row = document.querySelector(`.tree-leaf[data-id="${id}"]`);
  if (row) row.classList.add('selected');
}

export async function toggleEditalStatus(id) {
  const res = await fetch(`/api/edital/${id}/status`, { method: 'PUT' }).then(r => r.json());
  loadEdital();
  if (res.status === 'Concluído') {
    const topico = state.editalData.find(t => t.id === id);
    if (topico) ofereceQuestoesPosEstudo(topico.materia, topico.topico);
    // Check milestones
    checkMilestones();
  }
}

async function checkMilestones() {
  try {
    const data = await fetch('/api/milestones/check').then(r => r.json());
    if (data.new_milestones && data.new_milestones.length > 0) {
      // Atrasar para não conflitar com modal de tópico concluído
      setTimeout(() => {
        data.new_milestones.forEach(m => showMilestoneCelebration(m));
      }, 2000);
    }
  } catch (e) {}
}

function showMilestoneCelebration(milestone) {
  const overlay = document.createElement('div');
  overlay.className = 'milestone-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.3s ease;';
  overlay.innerHTML = `
    <div style="background:var(--bg-elevated);border-radius:20px;padding:32px;max-width:400px;width:90%;text-align:center;animation:scaleIn 0.4s ease;">
      <div style="font-size:3rem;margin-bottom:12px;">${milestone.emoji}</div>
      <h2 style="color:var(--accent);margin-bottom:8px;font-size:1.3rem;">${milestone.titulo}</h2>
      <p style="color:var(--text);font-size:0.92rem;margin-bottom:6px;">${milestone.msg}</p>
      <div style="font-size:2rem;font-weight:700;color:var(--green);margin:12px 0;">${milestone.pct}%</div>
      <button onclick="this.closest('.milestone-overlay').remove()" 
        style="background:var(--accent);color:var(--bg);border:none;border-radius:8px;padding:10px 24px;font-weight:600;cursor:pointer;font-size:0.9rem;">
        Continuar 💪
      </button>
    </div>`;
  document.body.appendChild(overlay);
  // Confetti se disponível
  if (typeof launchConfetti === 'function') launchConfetti();
  // Auto-remove após 10s
  setTimeout(() => overlay.remove(), 10000);
}

function ofereceQuestoesPosEstudo(materia, topico) {
  const modal = document.createElement('div');
  modal.id = 'pos-estudo-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `<div style="background:#313244;border-radius:16px;padding:24px;max-width:380px;width:90%;text-align:center;">
    <div style="font-size:1.5rem;margin-bottom:8px;">🎉</div>
    <h3 style="color:#a6e3a1;margin-bottom:8px;">Tópico Concluído!</h3>
    <p style="font-size:0.82rem;color:#cdd6f4;margin-bottom:4px;"><strong>${materia}</strong></p>
    <p style="font-size:0.78rem;color:#9399b2;margin-bottom:16px;">${topico}</p>
    <p style="font-size:0.82rem;color:#f9e2af;margin-bottom:16px;">📝 Que tal fixar com algumas questões?</p>
    <div style="display:flex;flex-direction:column;gap:8px;">
      <button onclick="iniciarQuestoesPosEstudo('${materia.replace(/'/g, "\\'")}');document.getElementById('pos-estudo-modal').remove();" style="background:#89b4fa;color:#1e1e2e;border:none;border-radius:8px;padding:12px;font-weight:600;cursor:pointer;font-size:0.9rem;">❓ Resolver Questões (${materia})</button>
      <button onclick="iniciarFlashPosEstudo('${materia.replace(/'/g, "\\'")}');document.getElementById('pos-estudo-modal').remove();" style="background:#cba6f7;color:#1e1e2e;border:none;border-radius:8px;padding:12px;font-weight:600;cursor:pointer;font-size:0.9rem;">🧠 Revisar Flashcards</button>
      <button onclick="document.getElementById('pos-estudo-modal').remove();" style="background:#45475a;color:#cdd6f4;border:none;border-radius:8px;padding:10px;cursor:pointer;font-size:0.85rem;">⏭ Pular (continuar depois)</button>
    </div>
  </div>`;
  document.body.appendChild(modal);
}

export async function iniciarQuestoesPosEstudo(materia) {
  try {
    const all = await fetch(`/api/questoes?materia=${encodeURIComponent(materia)}&limit=50`).then(r => r.json());
    const pool = Array.isArray(all) ? all : (all.items || []);
    if (pool.length === 0) { toast('Nenhuma questão disponível para esta matéria.', 'warning'); return; }
    // Dispara evento customizado para o módulo questoes capturar
    window.dispatchEvent(new CustomEvent('iniciar-questoes-pos-estudo', { detail: { pool, materia } }));
  } catch(e) { toast('Erro ao carregar questões', 'error'); }
}

export async function iniciarFlashPosEstudo(materia) {
  const cfg = _getConfigSessoes();
  const flashSessao = await fetch(`/api/flashcards/aleatorio?materia=${encodeURIComponent(materia)}&quantidade=${cfg.flashcards_sessao}`).then(r => r.json());
  if (flashSessao.length === 0) { toast('Nenhum flashcard para esta matéria.', 'warning'); return; }
  window.dispatchEvent(new CustomEvent('iniciar-flash-pos-estudo', { detail: { flashSessao, materia } }));
}

export async function deleteEditalItem(id) {
  undoableDelete('Tópico', `/api/edital/${id}`, (deleted) => {
    if (deleted) {
      if (state.editalSelectedId == id) {
        state.editalSelectedId = null;
        const label = document.getElementById('edital-materia-label');
        if (label) label.textContent = 'Nenhuma matéria selecionada';
      }
      loadEdital();
    } else { loadEdital(); }
  });
}

export async function addEdital() {
  const concurso = document.getElementById('edital-nome-input').value.trim() || 'Geral';
  const cargo = document.getElementById('edital-cargo-input').value.trim() || '';
  const m = document.getElementById('edital-materia-input').value.trim();
  const t = document.getElementById('edital-topico-input').value.trim();
  if (!m || !t) { toast('Preencha matéria e tópico.', 'warning'); return; }
  await fetch('/api/edital', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ edital_nome: concurso, cargo: cargo, materia: m, topico: t }) });
  document.getElementById('edital-materia-input').value = '';
  document.getElementById('edital-topico-input').value = '';
  loadEdital();
}

export async function importEditalPdf(input) {
  const file = input.files[0];
  if (!file) return;
  const nome = document.getElementById('edital-pdf-nome').value.trim();
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`/api/edital/importar-pdf-v2?confirmar=true&edital_nome=${encodeURIComponent(nome)}`, { method: 'POST', body: form }).then(r => r.json());
  input.value = '';
  if (res.ok) { toast(`Importados ${res.importados} itens!`, 'success'); loadEdital(); }
  else { toast('Erro ao importar.', 'error'); }
}

// ==================== ARQUIVAR / EXCLUIR EDITAIS ====================
export async function arquivarCargo(editalNome, cargo) {
  const ok = await confirmModal('Arquivar Cargo', `Arquivar <strong>"${cargo}"</strong> de <strong>"${editalNome}"</strong>?<br><br>Os tópicos não serão excluídos, apenas ocultados.`, { confirmText: 'Arquivar', type: 'info', icon: '📦' });
  if (!ok) return;
  await fetch(`/api/edital/arquivar?edital_nome=${encodeURIComponent(editalNome)}&cargo=${encodeURIComponent(cargo)}`, { method: 'PUT' });
  state.editalData = await fetch('/api/edital').then(r => r.json());
  renderEditalTree();
  toast('Cargo arquivado!', 'success');
}

export async function excluirCargo(editalNome, cargo) {
  const ok1 = await confirmModal('Excluir Cargo', `Excluir permanentemente <strong>"${cargo}"</strong> de <strong>"${editalNome}"</strong>?<br><br>Todos os tópicos, notas e vínculos serão perdidos.`, { confirmText: 'Excluir', type: 'danger', icon: '🗑️' });
  if (!ok1) return;
  try {
    const res = await fetch(`/api/edital/excluir-edital?edital_nome=${encodeURIComponent(editalNome)}&cargo=${encodeURIComponent(cargo)}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.ok) { toast(`Cargo "${cargo}" excluído (${data.excluidos} tópicos)`, 'success'); }
    else { toast('Erro ao excluir: ' + (data.detail || 'desconhecido'), 'error'); }
  } catch(e) { toast('Erro de conexão ao excluir.', 'error'); }
  await loadEdital();
}

export async function arquivarConcurso(editalNome) {
  const ok = await confirmModal('Arquivar Concurso', `Arquivar TODO o concurso <strong>"${editalNome}"</strong> (todos os cargos)?<br><br>Os dados não serão excluídos, apenas ocultados.`, { confirmText: 'Arquivar', type: 'info', icon: '📦' });
  if (!ok) return;
  await fetch(`/api/edital/arquivar?edital_nome=${encodeURIComponent(editalNome)}`, { method: 'PUT' });
  state.editalData = await fetch('/api/edital').then(r => r.json());
  renderEditalTree();
  toast('Concurso arquivado!', 'success');
}

export async function excluirConcurso(editalNome) {
  const ok1 = await confirmModal('Excluir Concurso', `Excluir permanentemente TODO o concurso <strong>"${editalNome}"</strong>?<br><br>Todos os cargos, tópicos, notas e vínculos serão perdidos!`, { confirmText: 'Excluir Tudo', type: 'danger', icon: '🗑️' });
  if (!ok1) return;
  const ok2 = await confirmModal('Última Confirmação', `Tem certeza absoluta? Isso é <strong>irreversível</strong>.`, { confirmText: 'Sim, excluir', cancelText: 'Não, voltar', type: 'danger', icon: '⚠️' });
  if (!ok2) return;
  try {
    const res = await fetch(`/api/edital/excluir-edital?edital_nome=${encodeURIComponent(editalNome)}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.ok) { toast(`Concurso "${editalNome}" excluído (${data.excluidos} tópicos)`, 'success'); }
    else { toast('Erro ao excluir: ' + (data.detail || 'desconhecido'), 'error'); }
  } catch(e) { toast('Erro de conexão ao excluir.', 'error'); }
  await loadEdital();
}

export async function showArquivados() {
  const arquivados = await fetch('/api/edital/arquivados').then(r => r.json());
  if (arquivados.length === 0) { toast('Nenhum edital arquivado.', 'info'); return; }
  openSelectModal('📦 Editais Arquivados — Desarquivar', arquivados.map(a => ({
    icon: '📦', label: `${a.edital_nome} - ${a.cargo}`, sub: `${a.total} tópicos`, value: a
  })), async (choice) => {
    const a = choice.value;
    await fetch(`/api/edital/desarquivar?edital_nome=${encodeURIComponent(a.edital_nome)}&cargo=${encodeURIComponent(a.cargo)}`, { method: 'PUT' });
    state.editalData = await fetch('/api/edital').then(r => r.json());
    renderEditalTree();
    toast('Edital desarquivado!', 'success');
  });
}

// ==================== EDITAR METADADOS ====================
export async function editarEdital(editalNome) {
  const infos = await fetch(`/api/edital/info?edital_nome=${encodeURIComponent(editalNome)}`).then(r => r.json()).catch(() => []);
  const overlay = document.createElement('div');
  overlay.id = 'editar-edital-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:99999;display:flex;align-items:center;justify-content:center;overflow-y:auto;padding:20px;';

  const infosData = infos.length === 0
    ? [{ id: null, edital_nome: editalNome, cargo: '', orgao: '', banca: '', vagas: '', subsidio: '', inscricoes: '', data_prova_objetiva: '', data_prova_discursiva: '', horario: '', local_prova: '', taxa_inscricao: '', link_edital: '', observacoes: '' }]
    : infos;

  let cardsHtml = infos.length === 0 ? `<p style="color:#9399b2;font-size:0.85rem;">Nenhum metadado cadastrado. Preencha abaixo para criar.</p>` : '';
  cardsHtml += infosData.map((info, idx) => `
    <div style="background:#1e1e2e;border:1px solid #45475a;border-radius:8px;padding:12px;margin-bottom:12px;" data-info-id="${info.id || ''}">
      <div style="font-size:0.82rem;color:#cba6f7;font-weight:600;margin-bottom:8px;">${info.cargo || 'Novo Cargo'}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:0.78rem;">
        <label style="color:#9399b2;">Cargo<input type="text" class="ei-field" data-idx="${idx}" data-field="cargo" value="${escapeHtml(info.cargo)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Órgão<input type="text" class="ei-field" data-idx="${idx}" data-field="orgao" value="${escapeHtml(info.orgao)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Banca<input type="text" class="ei-field" data-idx="${idx}" data-field="banca" value="${escapeHtml(info.banca)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Vagas<input type="text" class="ei-field" data-idx="${idx}" data-field="vagas" value="${escapeHtml(info.vagas)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Subsídio<input type="text" class="ei-field" data-idx="${idx}" data-field="subsidio" value="${escapeHtml(info.subsidio)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Inscrições<input type="text" class="ei-field" data-idx="${idx}" data-field="inscricoes" value="${escapeHtml(info.inscricoes)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Data Prova Objetiva<input type="date" class="ei-field" data-idx="${idx}" data-field="data_prova_objetiva" value="${info.data_prova_objetiva || ''}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Data Prova Discursiva<input type="date" class="ei-field" data-idx="${idx}" data-field="data_prova_discursiva" value="${info.data_prova_discursiva || ''}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Horário<input type="text" class="ei-field" data-idx="${idx}" data-field="horario" value="${escapeHtml(info.horario)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Local<input type="text" class="ei-field" data-idx="${idx}" data-field="local_prova" value="${escapeHtml(info.local_prova)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;">Taxa Inscrição<input type="text" class="ei-field" data-idx="${idx}" data-field="taxa_inscricao" value="${escapeHtml(info.taxa_inscricao)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;grid-column:span 2;">Link Edital<input type="url" class="ei-field" data-idx="${idx}" data-field="link_edital" value="${escapeHtml(info.link_edital)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;"></label>
        <label style="color:#9399b2;grid-column:span 2;">Observações<textarea class="ei-field" data-idx="${idx}" data-field="observacoes" rows="2" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 6px;margin-top:2px;font-size:0.78rem;resize:vertical;">${escapeHtml(info.observacoes)}</textarea></label>
      </div>
    </div>
  `).join('');

  overlay.innerHTML = `<div style="background:#313244;border-radius:16px;padding:24px;max-width:700px;width:100%;max-height:90vh;overflow-y:auto;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <h3 style="color:#cba6f7;margin:0;">✏️ Editar: ${escapeHtml(editalNome)}</h3>
      <button onclick="document.getElementById('editar-edital-modal').remove()" style="background:none;border:none;color:#f38ba8;font-size:1.2rem;cursor:pointer;">✕</button>
    </div>
    <div style="background:#1e1e2e;border:1px solid #f9e2af;border-radius:8px;padding:12px;margin-bottom:16px;">
      <label style="color:#f9e2af;font-size:0.85rem;font-weight:600;">📝 Nome do Edital (aplica para todos os cargos)
        <input type="text" id="edital-nome-global" value="${escapeHtml(editalNome)}" style="width:100%;background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:6px;padding:8px 10px;margin-top:6px;font-size:0.9rem;font-weight:600;">
      </label>
    </div>
    ${cardsHtml}
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
      <button onclick="document.getElementById('editar-edital-modal').remove()" style="background:#45475a;color:#cdd6f4;border:none;border-radius:8px;padding:10px 20px;cursor:pointer;">Cancelar</button>
      <button onclick="salvarEdicaoEdital('${editalNome.replace(/'/g, "\\'")}', ${JSON.stringify(infosData.map(i => i.id))})" style="background:#a6e3a1;color:#1e1e2e;border:none;border-radius:8px;padding:10px 20px;font-weight:600;cursor:pointer;">💾 Salvar</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

export async function salvarEdicaoEdital(editalNomeOriginal, ids) {
  // Get global name (single rename for all cargos)
  const globalNameEl = document.getElementById('edital-nome-global');
  const novoNome = globalNameEl ? globalNameEl.value.trim() : editalNomeOriginal;

  // Rename edital first (cascades to all cargos)
  if (novoNome && novoNome !== editalNomeOriginal) {
    await fetch('/api/edital/renomear', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ antigo: editalNomeOriginal, novo: novoNome }) });
  }

  // Save per-cargo metadata
  const groups = {};
  document.querySelectorAll('.ei-field').forEach(el => {
    const idx = el.dataset.idx;
    const field = el.dataset.field;
    if (field === 'edital_nome') return; // Skip per-card edital_nome (use global)
    if (!groups[idx]) groups[idx] = {};
    groups[idx][field] = el.value;
  });
  let saved = 0;
  for (const [idx, data] of Object.entries(groups)) {
    data.edital_nome = novoNome; // Use the global name
    const id = ids[parseInt(idx)];
    if (id) { await fetch(`/api/edital/info/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) }); }
    else { await fetch('/api/edital/info', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) }); }
    saved++;
  }
  document.getElementById('editar-edital-modal').remove();
  toast(`Metadados salvos (${saved} cargos)`, 'success');
  await loadEdital();
}

export function initEdital(deps) {
  _loadMetas = deps.loadMetas;
  _loadStreakBadge = deps.loadStreakBadge;
  _getConfigSessoes = deps.getConfigSessoes;
  _linkPdfToTopic = deps.linkPdfToTopic;
  _linkPdfToMateria = deps.linkPdfToMateria;
  _openNoteModal = deps.openNoteModal;

  const editalBtnStart = document.getElementById('edital-btn-start');
  const editalBtnStop = document.getElementById('edital-btn-stop');

  if (editalBtnStart) {
    editalBtnStart.addEventListener('click', () => {
      if (!state.editalSelectedId) { toast('Selecione um tópico no accordion abaixo.', 'warning'); return; }
      if (editalTimer) {
        clearInterval(editalTimer); editalTimer = null; editalPaused = true;
        editalElapsed = Math.floor((Date.now() - editalStartedAt) / 1000);
        editalStartedAt = null;
        editalBtnStart.textContent = '▶ Iniciar';
        editalBtnStop.style.display = 'inline-block';
      } else {
        if (editalPaused) { editalStartedAt = Date.now() - (editalElapsed * 1000); }
        else { editalStartedAt = Date.now(); editalElapsed = 0; }
        editalPaused = false;
        editalTimer = setInterval(editalTick, 250);
        editalBtnStart.textContent = '⏸ Pausar';
        editalBtnStop.style.display = 'inline-block';
        editalTick();
      }
    });
  }

  if (editalBtnStop) {
    editalBtnStop.addEventListener('click', async () => {
      clearInterval(editalTimer); editalTimer = null;
      if (editalStartedAt) editalElapsed = Math.floor((Date.now() - editalStartedAt) / 1000);
      const hours = editalElapsed / 3600;
      if (state.editalSelectedId && editalElapsed > 0) {
        await fetch(`/api/edital/${state.editalSelectedId}/horas`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ horas: hours }) });
        loadEdital();
        if (_loadStreakBadge) _loadStreakBadge();
      }
      editalElapsed = 0; editalStartedAt = null; editalPaused = false;
      const display = document.getElementById('edital-timer-display');
      if (display) display.textContent = '00:00:00';
      editalBtnStart.textContent = '▶ Iniciar';
      editalBtnStop.style.display = 'none';
    });
  }

  loadEdital();
}

// ==================== VÍDEO YOUTUBE ====================

window.linkVideoToTopic = function(editalId, topico) {
  // Modal para colar link do YouTube
  const existing = document.getElementById('modal-video-link');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'modal-video-link';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.9);z-index:99999;display:flex;align-items:center;justify-content:center;padding:20px;';
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
  modal.innerHTML = `
    <div style="background:var(--bg-surface);border-radius:16px;padding:24px;max-width:480px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
      <h3 style="margin:0 0 8px;font-size:1rem;color:var(--accent);">🎬 Vincular Vídeo YouTube</h3>
      <p style="font-size:0.82rem;color:var(--text-sub);margin:0 0 16px;">Tópico: <strong style="color:var(--text);">${escapeHtml(topico)}</strong></p>
      <input id="video-link-input" type="url" placeholder="Cole o link do YouTube aqui..." 
        style="width:100%;padding:12px 14px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9rem;outline:none;box-sizing:border-box;"
        autofocus>
      <p id="video-link-preview" style="font-size:0.75rem;color:var(--text-sub);margin:8px 0 0;min-height:18px;"></p>
      <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end;">
        <button onclick="document.getElementById('modal-video-link').remove()" style="background:var(--bg-elevated);color:var(--text);border:none;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:0.85rem;">Cancelar</button>
        <button onclick="confirmVideoLink(${editalId})" style="background:var(--green);color:var(--bg);border:none;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:0.85rem;font-weight:600;">✓ Vincular</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  // Preview de thumbnail ao colar
  const input = document.getElementById('video-link-input');
  input.addEventListener('input', () => {
    const val = input.value.trim();
    const id = extractYouTubeId(val);
    const preview = document.getElementById('video-link-preview');
    if (id) {
      preview.innerHTML = `<img src="https://img.youtube.com/vi/${id}/mqdefault.jpg" style="width:120px;border-radius:6px;margin-top:4px;">`;
    } else if (val) {
      preview.textContent = '⚠️ Link inválido — use um link do YouTube';
      preview.style.color = 'var(--red)';
    } else {
      preview.textContent = '';
    }
  });
  input.focus();
};

window.confirmVideoLink = function(editalId) {
  const input = document.getElementById('video-link-input');
  const link = input?.value?.trim();
  if (!link) { input.style.borderColor = 'var(--red)'; return; }
  if (!link.includes('youtu')) {
    toast('Link deve ser do YouTube', 'error');
    input.style.borderColor = 'var(--red)';
    return;
  }
  fetch(`/api/edital/${editalId}/video`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_link: link })
  }).then(r => r.json()).then(res => {
    if (res.ok) {
      document.getElementById('modal-video-link')?.remove();
      toast('🎬 Vídeo vinculado!', 'success');
      loadEdital();
    } else {
      toast(res.detail || 'Erro ao vincular', 'error');
    }
  }).catch(() => toast('Erro de conexão', 'error'));
};

window.openVideoPlayer = function(editalId, videoLink, topico) {
  // Extrair ID do YouTube
  const videoId = extractYouTubeId(videoLink);
  if (!videoId) {
    toast('Link de vídeo inválido', 'error');
    return;
  }

  // Criar modal com player embed
  const existing = document.getElementById('video-player-modal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'video-player-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.95);z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;';
  modal.innerHTML = `
    <div style="width:100%;max-width:800px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <span style="color:var(--text);font-weight:600;font-size:0.9rem;">🎬 ${escapeHtml(topico)}</span>
        <button onclick="closeVideoPlayer(${editalId})" style="background:var(--bg-elevated);color:var(--text);border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:0.85rem;">✕ Fechar</button>
      </div>
      <div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:12px;">
        <iframe id="yt-player" src="https://www.youtube.com/embed/${videoId}?rel=0" 
          style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;" 
          allow="accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture" 
          allowfullscreen></iframe>
      </div>
      <div style="margin-top:8px;text-align:center;">
        <a href="https://www.youtube.com/watch?v=${videoId}" target="_blank" style="font-size:0.75rem;color:var(--blue);text-decoration:none;">Se o vídeo não carregar, clique aqui para abrir no YouTube ↗</a>
      </div>
      <div style="margin-top:12px;display:flex;align-items:center;gap:12px;">
        <span style="color:var(--text-sub);font-size:0.78rem;" id="video-timer">⏱ 0:00</span>
        <button onclick="removeVideoLink(${editalId})" style="margin-left:auto;background:none;border:none;color:var(--red);cursor:pointer;font-size:0.78rem;">🗑 Desvincular</button>
      </div>
    </div>
  `;
  modal.onclick = (e) => { if (e.target === modal) closeVideoPlayer(editalId); };
  document.body.appendChild(modal);

  // Timer de tempo assistido
  window._videoStartTime = Date.now();
  window._videoTimerInterval = setInterval(() => {
    const elapsed = Math.round((Date.now() - window._videoStartTime) / 1000);
    const min = Math.floor(elapsed / 60);
    const sec = String(elapsed % 60).padStart(2, '0');
    const el = document.getElementById('video-timer');
    if (el) el.textContent = `⏱ ${min}:${sec}`;
  }, 1000);
};

window.closeVideoPlayer = function(editalId) {
  // Calcular tempo assistido
  if (window._videoTimerInterval) clearInterval(window._videoTimerInterval);
  const elapsed = Math.round((Date.now() - (window._videoStartTime || Date.now())) / 1000);
  const minutos = Math.round(elapsed / 60);

  // Remover modal
  document.getElementById('video-player-modal')?.remove();

  // Registrar sessão se assistiu >= 1 minuto
  if (minutos >= 1) {
    fetch(`/api/edital/${editalId}/video-session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ minutos })
    }).then(r => r.json()).then(res => {
      if (res.ok) {
        toast(`📹 ${minutos}min registrados como estudo de ${res.materia}`, 'success');
      }
    }).catch(() => {});
  }
};

window.removeVideoLink = function(editalId) {
  if (!confirm('Remover vídeo vinculado?')) return;
  fetch(`/api/edital/${editalId}/video`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_link: '' })
  }).then(r => r.json()).then(res => {
    if (res.ok) {
      toast('Vídeo removido', 'info');
      document.getElementById('video-player-modal')?.remove();
      if (window._videoTimerInterval) clearInterval(window._videoTimerInterval);
      loadEdital();
    }
  });
};

function extractYouTubeId(url) {
  if (!url) return null;
  // Formatos: youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
    /[?&]v=([a-zA-Z0-9_-]{11})/,
  ];
  for (const p of patterns) {
    const match = url.match(p);
    if (match) return match[1];
  }
  return null;
}

// ============================================================
// KNOWLEDGE GRAPH — Visualização interativa
// ============================================================

let _kgData = null;

export async function loadKnowledgeGraph() {
  const panel = document.getElementById('knowledge-graph-panel');
  if (!panel) return;

  const materia = document.getElementById('kg-filtro-materia')?.value || '';
  const params = materia ? `?materia=${encodeURIComponent(materia)}` : '';

  try {
    const data = await fetch(`/api/knowledge-graph${params}`).then(r => r.json());
    _kgData = data;

    if (data.stats.total_nodes === 0) {
      panel.style.display = 'none';
      return;
    }

    panel.style.display = 'block';

    const statsEl = document.getElementById('kg-stats');
    statsEl.textContent = `${data.stats.total_nodes} tópicos · ${data.stats.total_edges} dependências`;

    renderKnowledgeGraph(data);
  } catch (e) {
    panel.style.display = 'none';
  }
}

function renderKnowledgeGraph(data) {
  const container = document.getElementById('kg-container');
  if (!container) return;

  const width = container.clientWidth;
  const height = 350;

  // Limitar nodes para visualização (max 50 para performance)
  const nodes = data.nodes.slice(0, 50);
  const nodeIds = new Set(nodes.map(n => n.id));
  const edges = data.edges.filter(e => nodeIds.has(e.topic_id) && nodeIds.has(e.depends_on_id));

  // Layout simples: grid com deslocamento aleatório baseado em matéria
  const materias = [...new Set(nodes.map(n => n.materia))];
  const matColors = {};
  const palette = ['#89b4fa', '#a6e3a1', '#f9e2af', '#f38ba8', '#cba6f7', '#89dceb', '#fab387', '#94e2d5'];
  materias.forEach((m, i) => { matColors[m] = palette[i % palette.length]; });

  const nodePositions = {};
  const cols = Math.ceil(Math.sqrt(nodes.length));
  nodes.forEach((n, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    nodePositions[n.id] = {
      x: 40 + col * ((width - 80) / cols) + (Math.random() * 20 - 10),
      y: 30 + row * ((height - 60) / Math.ceil(nodes.length / cols)) + (Math.random() * 10 - 5),
    };
  });

  // Render SVG
  let svg = `<svg width="${width}" height="${height}" style="width:100%;height:100%;">`;

  // Edges
  edges.forEach(e => {
    const from = nodePositions[e.depends_on_id];
    const to = nodePositions[e.topic_id];
    if (!from || !to) return;
    const dash = e.relationship === 'related' ? 'stroke-dasharray="4"' : '';
    svg += `<line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="#585b70" stroke-width="1" ${dash} marker-end="url(#arrow)"/>`;
  });

  // Arrow marker
  svg += `<defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="#585b70"/></marker></defs>`;

  // Nodes
  nodes.forEach(n => {
    const pos = nodePositions[n.id];
    const color = n.status === 'Concluído' ? '#a6e3a1' : n.status === 'Em Andamento' ? '#f9e2af' : '#6c7086';
    const label = n.topico.length > 18 ? n.topico.slice(0, 18) + '…' : n.topico;
    svg += `<circle cx="${pos.x}" cy="${pos.y}" r="6" fill="${color}" stroke="${matColors[n.materia]}" stroke-width="2" style="cursor:pointer;" onclick="showKgNodeInfo(${n.id})"/>`;
    svg += `<text x="${pos.x}" y="${pos.y + 14}" text-anchor="middle" font-size="7" fill="#9399b2">${label}</text>`;
  });

  svg += '</svg>';
  container.innerHTML = svg;
}

export async function showKgSuggestions() {
  const materia = document.getElementById('kg-filtro-materia')?.value || '';
  const params = materia ? `?materia=${encodeURIComponent(materia)}&limit=15` : '?limit=15';

  try {
    const data = await fetch(`/api/knowledge-graph/suggest${params}`).then(r => r.json());
    const sugs = data.suggestions || [];
    if (!sugs.length) { showToast('Nenhuma sugestão disponível', 'info'); return; }

    let html = sugs.map(s => `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);">
        <div style="flex:1;min-width:0;">
          <div style="font-size:0.8rem;">${s.topic_name} <span style="color:var(--text-sub);">←</span> ${s.depends_on_name}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">${s.materia} · ${s.reason} · ${Math.round(s.confidence * 100)}% confiança</div>
        </div>
        <button onclick="acceptKgSuggestion(${s.topic_id},${s.depends_on_id},'${s.relationship}',this)" 
          style="background:var(--green);color:var(--bg);border:none;border-radius:4px;padding:3px 8px;font-size:0.72rem;cursor:pointer;" aria-label="Aceitar sugestão">✓</button>
      </div>`).join('');

    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `
      <div style="background:var(--bg-elevated);border-radius:16px;padding:20px;max-width:500px;width:92%;max-height:80vh;overflow-y:auto;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <h3 style="font-size:1rem;">💡 Sugestões de Dependência</h3>
          <button onclick="this.closest('div[style*=fixed]').remove()" style="background:none;border:none;color:var(--text-sub);cursor:pointer;font-size:1.2rem;" aria-label="Fechar">✕</button>
        </div>
        <p style="font-size:0.78rem;color:var(--text-sub);margin-bottom:12px;">${data.total_available} sugestões disponíveis. Aceite as que fazem sentido.</p>
        ${html}
      </div>`;
    document.body.appendChild(modal);
  } catch (e) { showToast('Erro ao carregar sugestões', 'error'); }
}

export async function acceptKgSuggestion(topicId, dependsOnId, relationship, btn) {
  try {
    await fetch('/api/knowledge-graph/edges', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic_id: topicId, depends_on_id: dependsOnId, relationship })
    });
    btn.textContent = '✓';
    btn.disabled = true;
    btn.style.opacity = '0.5';
    loadKnowledgeGraph();
  } catch (e) {}
}

export async function showKgNodeInfo(topicId) {
  try {
    const data = await fetch(`/api/knowledge-graph/prerequisites/${topicId}`).then(r => r.json());
    if (data.prerequisites.length === 0) {
      showToast('Nenhum pré-requisito cadastrado', 'info');
      return;
    }
    let html = data.prerequisites.map(p => {
      const statusIcon = p.status === 'Concluído' ? '✅' : p.status === 'Em Andamento' ? '🟡' : '⬜';
      return `<div style="padding:4px 0;font-size:0.82rem;">${'  '.repeat(p.depth)}${statusIcon} ${p.topico} <span style="color:var(--text-sub);font-size:0.72rem;">(${p.materia})</span></div>`;
    }).join('');

    showToast(`${data.all_completed ? '✅' : '⚠️'} ${data.total} pré-requisitos${data.all_completed ? ' — todos concluídos!' : ''}`, data.all_completed ? 'success' : 'warning');
  } catch (e) {}
}
