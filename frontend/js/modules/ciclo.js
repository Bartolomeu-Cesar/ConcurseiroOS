// ==================== TAB 3: CICLO ====================
import { state } from './state.js';
import { escapeHtml, toast, showLoading, showEmpty, undoableDelete } from './utils.js';

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
        <button class="ciclo-delete" onclick="deleteCiclo(${c.id})">🗑</button>
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
  const materias = [...new Set(state.editalData.map(e => e.materia))].sort();
  if (materias.length === 0) { toast('Nenhuma matéria no edital.', 'warning'); return; }
  const cicloAtual = await fetch('/api/ciclo').then(r => r.json());
  const jaNoCliclo = new Set(cicloAtual.map(c => c.materia));
  const novas = materias.filter(m => !jaNoCliclo.has(m));
  if (novas.length === 0) { toast('Todas as matérias do edital já estão no ciclo.', 'info'); return; }
  if (!confirm(`Importar ${novas.length} matérias do edital para o ciclo?\n\n${novas.slice(0, 10).join('\n')}${novas.length > 10 ? '\n...' : ''}`)) return;
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
  if (confirm('Resetar todas as horas cumpridas?')) {
    await fetch('/api/ciclo/resetar', { method: 'POST' });
    loadCiclo();
    toast('Horas resetadas!', 'success');
  }
}

export function initCiclo(deps) {
  _loadStreakBadge = deps.loadStreakBadge;
  loadCiclo();
}
