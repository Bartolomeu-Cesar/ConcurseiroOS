// ==================== TAB: SÚMULAS (SRS) ====================
import { escapeHtml, toast, showLoading, showEmpty, api } from './utils.js';

let sumulasToday = [], currentSumulaIndex = 0;
let sumulaSessao = [], sumulaSessaoIndex = 0;

export async function loadSumulasToday() {
  try {
    sumulasToday = await fetch('/api/sumulas/today').then(r => r.json());
    currentSumulaIndex = 0;
    showCurrentSumula();
    loadSumulaStats();
  } catch (e) { toast('Erro ao carregar súmulas de hoje', 'error'); }
}

function showCurrentSumula() {
  const front = document.getElementById('sumula-front');
  const back = document.getElementById('sumula-back');
  const rb = document.getElementById('sumula-reveal-btn');
  const rv = document.getElementById('sumula-review-btns');
  const progressEl = document.getElementById('sumula-progress');
  const total = sumulasToday.length;

  if (progressEl && total > 0) {
    progressEl.style.display = 'block';
    const done = currentSumulaIndex;
    const pct = Math.round((done / total) * 100);
    document.getElementById('sumula-progress-text').textContent = `${done}/${total} revisadas`;
    document.getElementById('sumula-progress-pct').textContent = `${pct}%`;
    document.getElementById('sumula-progress-bar').style.width = `${pct}%`;
    document.getElementById('sumula-progress-bar').style.background = pct >= 100 ? '#a6e3a1' : pct >= 50 ? '#f9e2af' : '#cba6f7';
  } else if (progressEl) { progressEl.style.display = 'none'; }

  if (currentSumulaIndex >= total) {
    front.innerHTML = total > 0
      ? `<span style="color:#a6e3a1;font-size:1.3rem;font-weight:600;">🎉 Parabéns! ${total} súmulas revisadas!</span>`
      : `<span style="color:#9399b2;font-size:0.9rem;">Nenhuma súmula pendente para revisão hoje. Adicione súmulas ou inicie uma sessão!</span>`;
    back.style.display = 'none'; rb.style.display = 'none'; rv.style.display = 'none';
    if (progressEl && total > 0) {
      document.getElementById('sumula-progress-text').textContent = `${total}/${total} revisadas ✓`;
      document.getElementById('sumula-progress-pct').textContent = '100%';
      document.getElementById('sumula-progress-bar').style.width = '100%';
      document.getElementById('sumula-progress-bar').style.background = '#a6e3a1';
    }
    return;
  }

  const s = sumulasToday[currentSumulaIndex];
  const vinc = s.vinculante ? '<span style="background:#f38ba8;color:#1e1e2e;padding:1px 6px;border-radius:4px;font-size:0.65rem;font-weight:700;margin-left:6px;">VINCULANTE</span>' : '';
  front.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <span style="font-size:0.75rem;background:#45475a;color:#cba6f7;padding:2px 8px;border-radius:4px;">🏛️ ${s.tribunal} — Súmula nº ${s.numero}${vinc}</span>
      ${s.tema ? `<span style="font-size:0.7rem;color:#89b4fa;">📚 ${s.tema}</span>` : ''}
    </div>
    <div style="font-size:1rem;font-weight:600;color:#f9e2af;">Qual é o enunciado da Súmula ${s.tribunal} nº ${s.numero}?</div>
  `;
  back.textContent = s.enunciado;
  if (s.observacao) {
    back.innerHTML = escapeHtml(s.enunciado) + `<br><br><span style="color:#89b4fa;font-size:0.8rem;">💡 ${escapeHtml(s.observacao)}</span>`;
  }
  back.style.display = 'none';
  rb.style.display = 'inline-block';
  rv.style.display = 'none';
}

export function revealSumula() {
  document.getElementById('sumula-back').style.display = 'block';
  document.getElementById('sumula-reveal-btn').style.display = 'none';
  const rv = document.getElementById('sumula-review-btns');
  rv.style.display = 'flex';
  rv.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;width:100%;">
      <button onclick="reviewSumula(0)" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">0•Esqueci</button>
      <button onclick="reviewSumula(1)" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">1•Errei</button>
      <button onclick="reviewSumula(2)" style="background:#fab387;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">2•Quase</button>
      <button onclick="reviewSumula(3)" style="background:#f9e2af;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">3•Difícil</button>
      <button onclick="reviewSumula(4)" style="background:#a6e3a1;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">4•Bom</button>
      <button onclick="reviewSumula(5)" style="background:#a6e3a1;color:#1e1e2e;border:none;border-radius:6px;padding:8px 4px;font-size:0.75rem;font-weight:600;cursor:pointer;">5•Fácil</button>
    </div>
  `;
}

export async function reviewSumula(quality) {
  const s = sumulasToday[currentSumulaIndex];
  if (!s) return;
  try {
    const data = await api(`/api/sumulas/${s.id}/review-sm2`, { method: 'POST', body: { quality } });
    const msgs = ['Esqueceu — recomeçar','Errou — recomeçar','Quase — recomeçar','Difícil — +1d','Bom — +' + data.intervalo_dias + 'd','Fácil — +' + data.intervalo_dias + 'd'];
    toast(`${msgs[quality]} (EF: ${data.easiness_factor.toFixed(2)})`, quality >= 3 ? 'success' : 'warning', 3000);
    currentSumulaIndex++;
    showCurrentSumula();
    loadAllSumulas();
  } catch (e) { toast('Erro ao revisar', 'error'); }
}

export async function addSumula() {
  const tribunal = document.getElementById('sumula-add-tribunal').value;
  const numero = document.getElementById('sumula-add-numero').value;
  const enunciado = document.getElementById('sumula-add-enunciado').value.trim();
  const tema = document.getElementById('sumula-add-tema').value.trim();
  const obs = document.getElementById('sumula-add-obs').value.trim();
  if (!numero || !enunciado) { toast('Preencha número e enunciado.', 'warning'); return; }
  const realTribunal = tribunal === 'STF-V' ? 'STF' : tribunal;
  const vinculante = tribunal === 'STF-V';
  await api('/api/sumulas', { method: 'POST', body: { tribunal: realTribunal, numero: parseInt(numero), enunciado, tema, observacao: obs, vinculante } });
  document.getElementById('sumula-add-numero').value = '';
  document.getElementById('sumula-add-enunciado').value = '';
  document.getElementById('sumula-add-tema').value = '';
  document.getElementById('sumula-add-obs').value = '';
  toast('Súmula adicionada!', 'success');
  loadSumulasToday();
  loadAllSumulas();
}

export async function loadAllSumulas() {
  showLoading('sumula-list');
  try {
    const tribunal = document.getElementById('sumula-filter-tribunal')?.value || '';
    const tema = document.getElementById('sumula-filter-tema')?.value || '';
    let url = '/api/sumulas?';
    if (tribunal) url += `tribunal=${encodeURIComponent(tribunal)}&`;
    if (tema) url += `tema=${encodeURIComponent(tema)}&`;
    const all = await fetch(url).then(r => r.json());
    document.getElementById('sumula-count').textContent = `Total: ${all.length} súmula(s)${tribunal ? ' em ' + tribunal : ''}`;
    if (all.length === 0) {
      showEmpty('sumula-list', '⚖️', 'Nenhuma súmula cadastrada. Adicione súmulas do STF/STJ para revisar com repetição espaçada!');
    } else {
      // Agrupar por tribunal
      const grouped = {};
      all.forEach(s => { const t = s.tribunal || 'Outros'; if (!grouped[t]) grouped[t] = []; grouped[t].push(s); });
      let html = '';
      if (!tribunal && Object.keys(grouped).length > 1) {
        for (const [trib, items] of Object.entries(grouped).sort((a,b) => b[1].length - a[1].length)) {
          const grpId = 'sumula-group-' + trib.replace(/[^a-zA-Z0-9]/g, '_');
          const vincCount = items.filter(s => s.vinculante).length;
          const vincLabel = vincCount > 0 ? ` · ${vincCount} vinculante${vincCount > 1 ? 's' : ''}` : '';
          html += `<div style="margin-top:8px;">
            <div onclick="toggleSumulaGroup('${grpId}')" style="font-size:0.8rem;font-weight:600;color:#cba6f7;padding:6px 10px;background:#45475a;border-radius:6px;margin-bottom:2px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;user-select:none;">
              <span><span class="flash-chevron" id="chev-${grpId}">▶</span> 🏛️ ${trib} (${items.length}${vincLabel})</span>
            </div>
            <div id="${grpId}" style="display:none;">`;
          html += items.map(s => renderSumulaItem(s)).join('');
          html += '</div></div>';
        }
      } else {
        html = all.map(s => renderSumulaItem(s)).join('');
      }
      document.getElementById('sumula-list').innerHTML = html;
    }
    loadSumulaFilters();
  } catch (e) { toast('Erro ao carregar súmulas', 'error'); }
}

function renderSumulaItem(s) {
  const vinc = s.vinculante ? ' 🔴' : '';
  const temaLabel = s.tema ? `<span style="font-size:0.7rem;color:#89b4fa;margin-left:6px;">${s.tema}</span>` : '';
  return `<div class="flash-list-item">
    <span style="flex:1;color:#cdd6f4;font-size:0.82rem;">
      <strong style="color:#cba6f7;">${s.tribunal} ${s.numero}</strong>${vinc}${temaLabel}
      — ${escapeHtml(s.enunciado.substring(0, 80))}${s.enunciado.length > 80 ? '...' : ''}
    </span>
    <button class="flash-list-edit" onclick="editSumula(${s.id})" title="Editar">✏️</button>
    <button class="flash-list-delete" onclick="deleteSumula(${s.id})">🗑</button>
  </div>`;
}

export function toggleSumulaGroup(id) {
  const el = document.getElementById(id);
  const chev = document.getElementById('chev-' + id);
  if (!el) return;
  if (el.style.display === 'none') { el.style.display = 'block'; if (chev) chev.textContent = '▼'; }
  else { el.style.display = 'none'; if (chev) chev.textContent = '▶'; }
}

async function loadSumulaFilters() {
  try {
    const tribunais = await fetch('/api/sumulas/tribunais').then(r => r.json());
    const sel = document.getElementById('sumula-filter-tribunal');
    const current = sel.value;
    sel.innerHTML = '<option value="">Todos os Tribunais</option>' +
      tribunais.map(t => `<option value="${t.tribunal}" ${t.tribunal === current ? 'selected' : ''}>${t.tribunal} (${t.total})</option>`).join('');

    const temas = await fetch('/api/sumulas/temas').then(r => r.json());
    const selT = document.getElementById('sumula-filter-tema');
    const currentT = selT.value;
    selT.innerHTML = '<option value="">Todos os Temas</option>' +
      temas.map(t => `<option value="${t.tema}" ${t.tema === currentT ? 'selected' : ''}>${t.tema} (${t.total})</option>`).join('');
  } catch(e) {}
}

async function loadSumulaStats() {
  try {
    const stats = await fetch('/api/sumulas/stats').then(r => r.json());
    const el = document.getElementById('sumula-stats');
    if (el) {
      el.innerHTML = `📊 ${stats.total} súmulas | 📅 ${stats.pendentes_hoje} pendentes hoje | ✅ ${stats.dominadas} dominadas`;
    }
  } catch(e) {}
}

export async function iniciarSessaoSumulas(mode) {
  if (mode === 'revisao') { loadSumulasToday(); toast('📅 Revisão SRS ativada!', 'success'); return; }

  if (mode === 'tribunal') {
    const tribunais = await fetch('/api/sumulas/tribunais').then(r => r.json());
    if (tribunais.length === 0) { toast('Nenhuma súmula disponível', 'warning'); return; }
    // Usar primeiro tribunal como default ou pedir seleção
    const escolha = prompt('Tribunal (STF, STJ, TST, TSE):');
    if (!escolha) return;
    sumulaSessao = await fetch(`/api/sumulas/aleatorio?tribunal=${encodeURIComponent(escolha)}&quantidade=15`).then(r => r.json());
    if (sumulaSessao.length === 0) { toast('Nenhuma súmula desse tribunal', 'warning'); return; }
    sumulaSessaoIndex = 0;
    sumulasToday = sumulaSessao;
    currentSumulaIndex = 0;
    showCurrentSumula();
    toast(`🏛️ Sessão: ${escolha} (${sumulaSessao.length} súmulas)`, 'success');
    return;
  }

  if (mode === 'tema') {
    const temas = await fetch('/api/sumulas/temas').then(r => r.json());
    if (temas.length === 0) { toast('Nenhuma súmula com tema definido', 'warning'); return; }
    const escolha = prompt('Tema: ' + temas.map(t => t.tema).join(', '));
    if (!escolha) return;
    sumulaSessao = await fetch(`/api/sumulas/aleatorio?tema=${encodeURIComponent(escolha)}&quantidade=15`).then(r => r.json());
    if (sumulaSessao.length === 0) { toast('Nenhuma súmula nesse tema', 'warning'); return; }
    sumulasToday = sumulaSessao;
    currentSumulaIndex = 0;
    showCurrentSumula();
    toast(`📚 Sessão: ${escolha} (${sumulaSessao.length} súmulas)`, 'success');
    return;
  }

  if (mode === 'aleatorio') {
    sumulaSessao = await fetch('/api/sumulas/aleatorio?quantidade=15').then(r => r.json());
    if (sumulaSessao.length === 0) { toast('Nenhuma súmula disponível', 'warning'); return; }
    sumulasToday = sumulaSessao;
    currentSumulaIndex = 0;
    showCurrentSumula();
    toast(`🎲 Sessão Aleatória (${sumulaSessao.length} súmulas)`, 'success');
    return;
  }
}

export async function deleteSumula(id) {
  if (!confirm('Excluir esta súmula?')) return;
  await api(`/api/sumulas/${id}`, { method: 'DELETE' });
  toast('Súmula excluída', 'success');
  loadAllSumulas();
  loadSumulasToday();
}

export async function editSumula(id) {
  // Reusar o modal de edição simples via prompt
  const all = await fetch('/api/sumulas').then(r => r.json());
  const s = all.find(x => x.id === id);
  if (!s) return;
  const novoEnunciado = prompt('Editar enunciado:', s.enunciado);
  if (novoEnunciado === null) return;
  const novoTema = prompt('Tema:', s.tema || '');
  const novaObs = prompt('Observação/Dica:', s.observacao || '');
  await api(`/api/sumulas/${id}`, { method: 'PUT', body: {
    enunciado: novoEnunciado || s.enunciado,
    tema: novoTema || '',
    observacao: novaObs || ''
  }});
  toast('Súmula atualizada!', 'success');
  loadAllSumulas();
}

export function initSumulas() {
  loadSumulasToday();
  loadAllSumulas();
}
