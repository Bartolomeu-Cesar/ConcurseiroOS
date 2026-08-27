// ==================== TAB 3: CICLO ====================
import { state } from './state.js';
import { escapeHtml, toast, showLoading, showEmpty, undoableDelete, confirmModal } from './utils.js';
import { openSelectModal } from './modal-selecao.js';

let cicloTimerInterval = null, cicloStartedAt = null, cicloElapsed = 0, cicloPaused = false;
let cicloProximoId = null, cicloProximoMateria = '';
let _loadStreakBadge = null;

export async function loadCiclo() {
  showLoading('ciclo-list');
  try {
    const [ciclo, proximo] = await Promise.all([
      fetch('/api/ciclo').then(r => r.json()),
      fetch('/api/ciclo/proximo').then(r => r.json())
    ]);
    cicloProximoId = proximo.id || null;
    cicloProximoMateria = proximo.materia || '—';
    document.getElementById('ciclo-focus-materia').textContent = cicloProximoMateria;
    const pctProx = proximo.horas_alvo > 0 ? Math.round((proximo.horas_cumpridas || 0) / proximo.horas_alvo * 100) : 0;
    document.getElementById('ciclo-focus-sub').textContent = `${(proximo.horas_cumpridas || 0).toFixed(1)}h / ${(proximo.horas_alvo || 0).toFixed(1)}h (${pctProx}%)`;
    const list = document.getElementById('ciclo-list');
    if (ciclo.length === 0) {
      list.innerHTML = '<div class="empty-state"><div class="empty-icon">🔄</div><div class="empty-msg">Nenhuma matéria no ciclo. Adicione matérias ou importe do edital para começar o estudo intercalado.</div></div>';
      return;
    }
    const totalHoras = ciclo.reduce((a, c) => a + c.horas_alvo, 0);
    const totalCumpridas = ciclo.reduce((a, c) => a + c.horas_cumpridas, 0);
    const pctGeral = totalHoras > 0 ? Math.round(totalCumpridas / totalHoras * 100) : 0;
    let html = `<div style="font-size:0.8rem;color:#9399b2;margin-bottom:8px;display:flex;justify-content:space-between;"><span>${ciclo.length} matérias no ciclo</span><span>Progresso geral: ${pctGeral}% (${totalCumpridas.toFixed(1)}h / ${totalHoras.toFixed(1)}h)</span></div>`;
    html += ciclo.map(c => {
      const pct = c.horas_alvo > 0 ? Math.min(100, (c.horas_cumpridas / c.horas_alvo) * 100) : 0;
      const isNext = c.id === cicloProximoId;
      return `<div class="ciclo-item ${isNext ? 'is-next' : ''}">
        ${isNext ? '<span style="color:#a6e3a1;font-size:0.8rem;">▶</span>' : '<span style="width:14px;"></span>'}
        <span class="ciclo-materia">${escapeHtml(c.materia)}</span>
        <div class="ciclo-bar"><div class="ciclo-bar-fill" style="width:${pct}%;${pct >= 100 ? 'background:#a6e3a1;' : ''}"></div></div>
        <span class="ciclo-pct">${Math.round(pct)}%</span>
        <span class="ciclo-hours">${c.horas_cumpridas.toFixed(1)}h / ${c.horas_alvo.toFixed(1)}h</span>
        <button class="ciclo-delete" onclick="deleteCiclo(${c.id})" aria-label="Excluir ciclo">🗑</button>
      </div>`;
    }).join('');
    list.innerHTML = html;
  } catch (e) {
    toast('Erro ao carregar ciclo', 'error');
    showEmpty('ciclo-list', '🔄', 'Erro ao carregar ciclo.');
  }
}

export function cicloTimerToggle() {
  if (!cicloProximoId) { toast('Adicione matérias ao ciclo primeiro.', 'warning'); return; }
  const btn = document.getElementById('ciclo-btn-start');
  const stopBtn = document.getElementById('ciclo-btn-stop');
  if (cicloTimerInterval) {
    clearInterval(cicloTimerInterval); cicloTimerInterval = null; cicloPaused = true;
    cicloElapsed = Math.floor((Date.now() - cicloStartedAt) / 1000);
    cicloStartedAt = null;
    btn.textContent = '▶ Continuar'; btn.style.background = '#fab387';
  } else {
    if (cicloPaused) { cicloStartedAt = Date.now() - (cicloElapsed * 1000); }
    else { cicloStartedAt = Date.now(); cicloElapsed = 0; }
    cicloPaused = false;
    cicloTimerInterval = setInterval(cicloTimerTick, 250);
    btn.textContent = '⏸ Pausar'; btn.style.background = '#fab387';
    stopBtn.style.display = 'inline-block';
    cicloTimerTick();
  }
}

function cicloTimerTick() {
  if (!cicloStartedAt) return;
  cicloElapsed = Math.floor((Date.now() - cicloStartedAt) / 1000);
  const h = String(Math.floor(cicloElapsed / 3600)).padStart(2, '0');
  const m = String(Math.floor((cicloElapsed % 3600) / 60)).padStart(2, '0');
  const s = String(cicloElapsed % 60).padStart(2, '0');
  document.getElementById('ciclo-timer-display').textContent = `${h}:${m}:${s}`;
}

export async function cicloTimerStop() {
  clearInterval(cicloTimerInterval); cicloTimerInterval = null;
  if (cicloStartedAt) cicloElapsed = Math.floor((Date.now() - cicloStartedAt) / 1000);
  const hours = cicloElapsed / 3600;
  if (cicloProximoId && cicloElapsed > 30) {
    await fetch(`/api/ciclo/${cicloProximoId}/horas`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ horas: hours }) });
  }
  cicloElapsed = 0; cicloStartedAt = null; cicloPaused = false;
  document.getElementById('ciclo-timer-display').textContent = '00:00:00';
  document.getElementById('ciclo-btn-start').textContent = '▶ Estudar';
  document.getElementById('ciclo-btn-start').style.background = '#a6e3a1';
  document.getElementById('ciclo-btn-stop').style.display = 'none';
  loadCiclo();
  if (_loadStreakBadge) _loadStreakBadge();
}

export async function importarCicloDoEdital() {
  if (state.editalData.length === 0) { toast('Nenhuma matéria no edital.', 'warning'); return; }

  // Listar concursos disponíveis
  const concursos = [...new Set(state.editalData.map(e => e.edital_nome || 'Geral'))].sort();

  const items = concursos.map(c => ({
    icon: '📋',
    label: c,
    sub: `${state.editalData.filter(e => (e.edital_nome || 'Geral') === c).length} tópicos`,
    value: c
  }));
  items.unshift({ icon: '📚', label: 'Todos os concursos', sub: `${state.editalData.length} tópicos no total`, value: '__todos__' });

  openSelectModal('📋 Importar de qual concurso?', items, async (choice) => {
    let dadosFiltrados;
    if (choice.value === '__todos__') {
      dadosFiltrados = state.editalData;
    } else {
      dadosFiltrados = state.editalData.filter(e => (e.edital_nome || 'Geral') === choice.value);
    }

    // Se tem mais de um cargo, perguntar qual
    const cargos = [...new Set(dadosFiltrados.map(e => e.cargo || 'Geral'))].sort();
    if (cargos.length > 1) {
      const cargoItems = cargos.map(c => ({
        icon: '👤',
        label: c,
        sub: `${dadosFiltrados.filter(e => (e.cargo || 'Geral') === c).length} tópicos`,
        value: c
      }));
      cargoItems.unshift({ icon: '📚', label: 'Todos os cargos', sub: `${dadosFiltrados.length} tópicos`, value: '__todos_cargos__' });

      openSelectModal('👤 De qual cargo?', cargoItems, async (cargoChoice) => {
        let filtrado;
        if (cargoChoice.value === '__todos_cargos__') {
          filtrado = dadosFiltrados;
        } else {
          filtrado = dadosFiltrados.filter(e => (e.cargo || 'Geral') === cargoChoice.value);
        }
        await _importarMateriasCiclo(filtrado);
      });
    } else {
      await _importarMateriasCiclo(dadosFiltrados);
    }
  });
}

async function _importarMateriasCiclo(dados) {
  const materias = [...new Set(dados.map(e => e.materia))].sort();
  if (materias.length === 0) { toast('Nenhuma matéria encontrada.', 'warning'); return; }

  const cicloAtual = await fetch('/api/ciclo').then(r => r.json());
  const jaNoCliclo = new Set(cicloAtual.map(c => c.materia));
  const novas = materias.filter(m => !jaNoCliclo.has(m));

  if (novas.length === 0) { toast('Todas as matérias já estão no ciclo.', 'info'); return; }
  const ok = await confirmModal('Importar Matérias', `Importar <strong>${novas.length}</strong> matérias para o ciclo?<br><br>${novas.slice(0, 8).map(m => `• ${m}`).join('<br>')}${novas.length > 8 ? '<br>...' : ''}`, { confirmText: 'Importar', type: 'info', icon: '📋' });
  if (!ok) return;

  for (const m of novas) {
    await fetch('/api/ciclo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ materia: m, horas_alvo: 2.0 }) });
  }
  toast(`${novas.length} matérias importadas!`, 'success');
  loadCiclo();
}

export async function addCiclo() {
  const m = document.getElementById('ciclo-materia-input').value.trim();
  const h = parseFloat(document.getElementById('ciclo-horas-input').value) || 2;
  if (!m) { toast('Preencha a matéria.', 'warning'); return; }
  await fetch('/api/ciclo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ materia: m, horas_alvo: h }) });
  document.getElementById('ciclo-materia-input').value = '';
  loadCiclo();
}

export async function deleteCiclo(id) {
  undoableDelete('Matéria do ciclo', `/api/ciclo/${id}`, (deleted) => { if (deleted) loadCiclo(); });
}

export async function resetarCiclo() {
  const ok = await confirmModal('Resetar Horas', 'Zerar todas as horas cumpridas no ciclo?<br><br>As matérias serão mantidas.', { confirmText: 'Resetar', type: 'warning', icon: '🔁' });
  if (ok) {
    await fetch('/api/ciclo/resetar', { method: 'POST' });
    loadCiclo();
    toast('Horas resetadas!', 'success');
  }
}

export async function limparCiclo() {
  const ok = await confirmModal('Limpar Ciclo', 'Remover <strong>TODAS</strong> as matérias do ciclo?<br><br>Isso permite reimportar de outro edital.', { confirmText: 'Limpar Tudo', type: 'danger', icon: '🗑️' });
  if (!ok) return;
  const res = await fetch('/api/ciclo/limpar', { method: 'DELETE' }).then(r => r.json());
  loadCiclo();
  toast(`Ciclo limpo! ${res.removidos} matérias removidas.`, 'success');
}

export function initCiclo(deps) {
  _loadStreakBadge = deps.loadStreakBadge;
  loadCiclo();
  // Load ciclo visões (Diário/Semanal/Mensal/Completo)
  _loadCicloVisaoFromModule();
}

// ============================================================
// CICLO VISÕES — carregamento integrado ao módulo
// ============================================================
let _cicloVisaoData = null;
let _cicloViewAtual = 'diario';

function _loadCicloVisaoFromModule() {
  const el = document.getElementById('ciclo-view-content');
  if (!el) return;
  el.innerHTML = '<p style="color:#9399b2;font-size:0.85rem;">Carregando plano de estudos...</p>';
  fetch('/api/ciclo/visao')
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => {
      _cicloVisaoData = data;
      _renderCicloView(_cicloViewAtual);
    })
    .catch(() => {
      // Retry after 2s (token may not be ready)
      setTimeout(() => {
        fetch('/api/ciclo/visao')
          .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
          .then(data => { _cicloVisaoData = data; _renderCicloView(_cicloViewAtual); })
          .catch(e => { if (el) el.innerHTML = `<p style="color:#f38ba8;">Erro: ${e.message}. Recarregue a página.</p>`; });
      }, 2000);
    });
}

export function switchCicloView(view, btn) {
  _cicloViewAtual = view;
  document.querySelectorAll('.ciclo-view-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const el = document.getElementById('ciclo-view-content');
  if (!el) return;
  if (_cicloVisaoData && (_cicloVisaoData.diario || _cicloVisaoData.sem_dados)) {
    _renderCicloView(view);
  } else {
    el.innerHTML = '<p style="color:#9399b2;font-size:0.85rem;">Carregando...</p>';
    fetch('/api/ciclo/visao')
      .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(data => { _cicloVisaoData = data; _renderCicloView(view); })
      .catch(e => { el.innerHTML = `<p style="color:#f38ba8;">Erro: ${e.message}</p>`; });
  }
}

function _renderCicloView(view) {
  const el = document.getElementById('ciclo-view-content');
  if (!el || !_cicloVisaoData) return;
  if (_cicloVisaoData.sem_dados) { el.innerHTML = '<p style="color:#9399b2;">Adicione matérias ao edital para gerar o ciclo.</p>'; return; }
  if (view === 'diario') _renderDiario(el, _cicloVisaoData.diario);
  else if (view === 'semanal') _renderSemanal(el, _cicloVisaoData.semanal);
  else if (view === 'mensal') _renderMensal(el, _cicloVisaoData.mensal);
  else _renderCompleto(el, _cicloVisaoData.completo, _cicloVisaoData.stats);
}

function _renderDiario(el, items) {
  if (!items || !items.length) { el.innerHTML = '<p style="color:#9399b2;">Nenhuma matéria no ciclo. Importe do edital.</p>'; return; }
  el.innerHTML = items.map(m => `
    <div style="background:var(--bg);border-radius:10px;padding:14px;margin-bottom:8px;border-left:4px solid ${m.prioridade==='alta'?'var(--red)':'var(--peach)'};">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <strong style="font-size:0.95rem;color:var(--text);">${m.materia}</strong>
        <span style="font-size:0.82rem;background:var(--bg-surface);border-radius:12px;padding:3px 10px;color:var(--text-sub);">${m.horas}h</span>
      </div>
      <div style="font-size:0.82rem;color:var(--green);margin-bottom:4px;">→ ${m.acao}</div>
      ${m.atividades && m.atividades.length ? `<div style="margin:8px 0;padding:8px;background:var(--bg-surface);border-radius:8px;">
        ${m.atividades.map(a => `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:0.78rem;">
          <span style="color:${a.tipo==='teoria'?'var(--blue)':a.tipo==='questoes'?'var(--accent)':'var(--green)'};">${a.tipo==='teoria'?'📖':a.tipo==='questoes'?'❓':'🔄'}</span>
          <span style="flex:1;color:var(--text);">${a.descricao}</span>
          <span style="color:var(--text-sub);white-space:nowrap;">${a.tempo_min}min</span>
        </div>`).join('')}
      </div>` : ''}
      <div style="font-size:0.75rem;color:var(--text-sub);">${m.motivo}</div>
      <div style="display:flex;gap:12px;margin-top:6px;font-size:0.75rem;color:var(--text-sub);">
        <span>📊 ${m.pct_acerto}% acerto</span><span>📋 ${m.pendentes} pendentes</span>
      </div>
    </div>`).join('');
}

function _renderSemanal(el, dias) {
  if (!dias || !dias.length) { el.innerHTML = '<p style="color:var(--text-sub);">Sem dados semanais.</p>'; return; }
  el.innerHTML = dias.map(d => `
    <div style="margin-bottom:10px;${d.is_hoje?'background:var(--bg);border:1px solid var(--accent);border-radius:10px;padding:10px;':''}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <strong style="font-size:0.88rem;${d.is_hoje?'color:var(--accent);':'color:var(--text);'}">${d.dia}${d.is_hoje?' (HOJE)':''}</strong>
        <span style="font-size:0.78rem;color:var(--text-sub);">${d.horas_total}h · ${d.tipo_dia || ''}</span>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;">
        ${(d.materias||[]).map(m => `<span style="font-size:0.78rem;background:var(--bg-surface);border-radius:6px;padding:4px 10px;border-left:3px solid ${m.prioridade==='alta'?'var(--red)':m.prioridade==='media'?'var(--peach)':'var(--green)'};">${m.materia} <span style="color:var(--text-sub);">(${m.horas}h)</span></span>`).join('')}
      </div>
    </div>`).join('');
}

function _renderMensal(el, semanas) {
  if (!semanas || !semanas.length) { el.innerHTML = '<p style="color:var(--text-sub);">Sem dados mensais.</p>'; return; }
  el.innerHTML = semanas.map(s => `
    <div style="background:var(--bg);border-radius:10px;padding:14px;margin-bottom:10px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <strong style="color:var(--text);">Semana ${s.semana}</strong>
        <span style="font-size:0.78rem;color:var(--text-sub);">${s.foco} · ${s.horas_total}h</span>
      </div>
      <div style="height:4px;background:var(--bg-surface);border-radius:2px;margin-bottom:8px;overflow:hidden;">
        <div style="height:100%;width:${s.fator_questoes}%;background:var(--blue);border-radius:2px;"></div>
      </div>
      <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:6px;">Teoria ${100-s.fator_questoes}% | Questões ${s.fator_questoes}%</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;">
        ${(s.materias||[]).slice(0,5).map(m => `<span style="font-size:0.75rem;background:var(--bg-surface);border-radius:6px;padding:3px 8px;color:var(--text);">${m.materia} <span style="color:var(--text-sub);">${m.horas_teoria}h+${m.questoes_meta}q</span></span>`).join('')}
        ${(s.materias||[]).length>5?`<span style="font-size:0.75rem;color:var(--text-sub);">+${s.materias.length-5}</span>`:''}
      </div>
    </div>`).join('');
}

function _renderCompleto(el, items, stats) {
  if (!items || !items.length || !stats) { el.innerHTML = '<p style="color:var(--text-sub);">Sem dados disponíveis.</p>'; return; }
  let h = `<div style="display:flex;gap:16px;margin-bottom:14px;flex-wrap:wrap;align-items:center;">
    <div style="font-size:0.85rem;color:var(--text);"><strong style="font-size:1.3rem;color:var(--accent);">${stats.pct_geral}%</strong> completo</div>
    <div style="font-size:0.78rem;color:var(--text-sub);">${stats.horas_cumpridas}/${stats.horas_alvo}h</div>
    ${stats.dias_prova!==null?`<div style="font-size:0.78rem;color:var(--red);font-weight:600;">📅 ${stats.dias_prova} dias p/ prova</div>`:''}
    <div style="font-size:0.78rem;color:var(--green);">✅ ${stats.dominadas} dominadas</div>
    <div style="font-size:0.78rem;color:var(--red);">⚠️ ${stats.criticas} críticas</div></div>`;
  h += items.map(m => `
    <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);">
      <div style="width:8px;height:8px;border-radius:50%;background:${m.cor};flex-shrink:0;"></div>
      <span style="flex:1;font-size:0.85rem;font-weight:500;color:var(--text);">${m.materia}</span>
      <span style="font-size:0.72rem;color:var(--text-sub);min-width:55px;">${m.pct_acerto}%</span>
      <div style="width:80px;height:6px;background:var(--bg-surface);border-radius:3px;overflow:hidden;">
        <div style="height:100%;width:${m.pct_ciclo}%;background:${m.cor};border-radius:3px;"></div>
      </div>
      <span style="font-size:0.72rem;color:var(--text-sub);min-width:35px;text-align:right;">${m.pct_ciclo}%</span>
    </div>`).join('');
  el.innerHTML = h;
}
