// main.js — Main orchestrator for the dashboard
// Imports all sub-modules and initializes the dashboard

import { getCSSVar, COLORS } from './helpers.js';
import {
  renderChartHoras, renderChartAcertos, renderChartMaterias, renderChartEdital,
  loadRadar, loadEvolucao, loadHeatmapErros, loadMetasRealizado, loadHeatmap,
  loadProjecaoNota, loadRaioX, loadAnaliseErros, renderPratica, renderRelatorio,
  loadVelocidade, loadConsistencia, loadRankingMaterias
} from './charts.js';
import { renderMetas } from './metas.js';
import {
  loadGamification, loadDesafios, renderStreak,
  loadMissoes, loadShareBox
} from './gamification.js';
import {
  loadTreinador, loadTrilha, loadCurvaEsquecimento, loadRevisoesPendentes,
  loadDailyChallenge, loadIntercalacao, loadPraticaDelib, loadFeynmanMaterias,
  loadPontosFragcos, loadConexoes, loadTempoResultado, loadDissertMaterias,
  loadSpacing, loadStudyIntelligence
} from './treinador.js';
import { loadDesafioDiarioCard } from './desafio.js';

// ===== Dashboard Tab Navigation =====
document.querySelectorAll('.dash-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.dash-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.dash-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.panel).classList.add('active');
    loadActivePanel();
  });
});

// ===== Countdown =====
async function loadDashCountdown() {
  try {
    const provas = await fetch('/api/countdown').then(r => r.json());
    const el = document.getElementById('dash-countdown');
    if (!el) return;
    const now = new Date();
    const favorito = localStorage.getItem('countdown_favorito');
    const futuras = provas.map(p => {
      if (!p.data_objetiva) return null;
      const parts = p.data_objetiva.match(/(\d+)[-\/](\d+)[-\/](\d+)/);
      if (!parts) return null;
      let d;
      if (parts[3].length === 4) d = new Date(parts[3], parts[2]-1, parts[1]);
      else d = new Date(parts[1], parts[2]-1, parts[3]);
      const dias = Math.ceil((d - now) / 86400000);
      return dias > 0 ? {...p, dias} : null;
    }).filter(Boolean).sort((a,b) => a.dias - b.dias);

    let prox = null;
    if (favorito) {
      // Try to find in futuras (provas with dates)
      prox = futuras.find(p => `${p.edital}|${p.cargo}` === favorito);
      // If not found (cargo without date), show it anyway
      if (!prox) {
        const [editalFav, cargoFav] = favorito.split('|');
        if (cargoFav) {
          prox = { edital: editalFav, cargo: cargoFav, dias: null };
        }
      }
    }
    if (!prox && futuras.length) prox = futuras[0];
    if (!prox) { el.textContent = ''; return; }

    if (prox.dias) {
      const cor = prox.dias <= 30 ? 'var(--red)' : prox.dias <= 60 ? 'var(--peach)' : 'var(--yellow)';
      el.style.color = cor;
      el.innerHTML = `⏳ <strong>${prox.cargo}</strong>: ${prox.dias} dias ⭐`;
    } else {
      el.style.color = 'var(--text-muted)';
      el.innerHTML = `⏳ <strong>${prox.cargo}</strong>: aguardando data ⭐`;
    }
    el.style.cursor = 'pointer';
    el.title = 'Clique para trocar a prova favorita';
    el.onclick = function() { showCountdownSelector(futuras); };
  } catch(e) {}
}

function showCountdownSelector(futuras) {
  const existing = document.getElementById('countdown-selector-modal');
  if (existing) existing.remove();

  // Fetch ALL cargos (including those without dates)
  fetch('/api/countdown?include_all=true').then(r => r.json()).then(allProvas => {
    const now = new Date();
    const all = allProvas.map(p => {
      if (!p.data_objetiva) return { ...p, dias: null };
      const parts = p.data_objetiva.match(/(\d+)[-\/](\d+)[-\/](\d+)/);
      if (!parts) return { ...p, dias: null };
      let d;
      if (parts[3].length === 4) d = new Date(parts[3], parts[2]-1, parts[1]);
      else d = new Date(parts[1], parts[2]-1, parts[3]);
      const dias = Math.ceil((d - now) / 86400000);
      return { ...p, dias: dias > 0 ? dias : null };
    });

    _renderCountdownModal(all);
  }).catch(() => {
    // Fallback: use only futuras
    _renderCountdownModal(futuras);
  });
}

function _renderCountdownModal(allProvas) {
  const existing = document.getElementById('countdown-selector-modal');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'countdown-selector-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };

  const favorito = localStorage.getItem('countdown_favorito') || '';

  let html = '<div style="background:var(--bg-surface);border-radius:12px;padding:20px;max-width:440px;width:95%;max-height:80vh;display:flex;flex-direction:column;">';
  html += `<h3 style="color:var(--accent);margin:0 0 12px;">⏳ Escolher Prova (${allProvas.length} cargos)</h3>`;
  html += '<input type="text" id="countdown-filter-input" placeholder="Filtrar por nome, cargo ou edital..." style="width:100%;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.88rem;margin-bottom:12px;font-family:inherit;" autocomplete="off">';
  html += '<div id="countdown-items-list" style="overflow-y:auto;flex:1;display:grid;gap:8px;">';
  html += _buildCountdownItems(allProvas, favorito);
  html += '</div>';
  html += '<button onclick="selectCountdownFavorito(\'\')" style="display:block;width:100%;margin-top:10px;padding:10px;background:var(--bg-elevated);color:var(--text);border:none;border-radius:8px;cursor:pointer;font-size:0.82rem;">🔄 Automático (mais próxima)</button>';
  html += '</div>';
  overlay.innerHTML = html;
  document.body.appendChild(overlay);

  // Focus search input
  const input = document.getElementById('countdown-filter-input');
  setTimeout(() => input.focus(), 100);

  // Filter on input
  input.oninput = function() {
    const q = input.value.toLowerCase();
    const filtered = allProvas.filter(p =>
      p.edital.toLowerCase().includes(q) || p.cargo.toLowerCase().includes(q)
    );
    document.getElementById('countdown-items-list').innerHTML = _buildCountdownItems(filtered, favorito);
  };
}

function _buildCountdownItems(provas, favorito) {
  // Group by edital
  const groups = {};
  provas.forEach(p => {
    if (!groups[p.edital]) groups[p.edital] = [];
    groups[p.edital].push(p);
  });

  let html = '';
  Object.keys(groups).sort().forEach(edital => {
    html += `<div style="font-size:0.72rem;font-weight:700;color:var(--text-muted);padding:6px 4px 2px;text-transform:uppercase;letter-spacing:0.5px;">📋 ${edital} (${groups[edital].length})</div>`;
    groups[edital].forEach(p => {
      const key = `${p.edital}|${p.cargo}`;
      const isFav = key === favorito;
      const cor = p.dias ? (p.dias <= 30 ? 'var(--red)' : p.dias <= 60 ? 'var(--peach)' : 'var(--yellow)') : 'var(--text-muted)';
      const diasText = p.dias ? `${p.dias}d` : '—';
      html += `<button onclick="selectCountdownFavorito('${key}')" style="display:flex;align-items:center;gap:10px;padding:10px 12px;background:${isFav ? 'var(--bg-elevated)' : 'var(--bg)'};border:2px solid ${isFav ? 'var(--accent)' : 'var(--bg-elevated)'};border-radius:10px;cursor:pointer;text-align:left;width:100%;">
        <span style="font-size:1.1rem;">${isFav ? '⭐' : (p.dias ? '📅' : '📌')}</span>
        <div style="flex:1;">
          <div style="font-size:0.85rem;font-weight:600;color:var(--text);">${p.cargo}</div>
          <div style="font-size:0.72rem;color:var(--text-sub);">${p.data_objetiva || 'Data a definir'}</div>
        </div>
        <span style="font-size:0.88rem;font-weight:700;color:${cor};">${diasText}</span>
      </button>`;
    });
  });
  return html;
}

window.selectCountdownFavorito = function(key) {
  if (key) {
    localStorage.setItem('countdown_favorito', key);
  } else {
    localStorage.removeItem('countdown_favorito');
  }
  document.getElementById('countdown-selector-modal')?.remove();
  loadDashCountdown();
};

loadDashCountdown();

document.getElementById('date-label').textContent = new Date().toLocaleDateString('pt-BR', {
  weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
});

// ===== Main Dashboard Load =====
async function loadDashboard() {
  try {
    const [dashboard, streaks, metas] = await Promise.all([
      fetch('/api/dashboard').then(r => r.json()),
      fetch('/api/streaks').then(r => r.json()),
      fetch('/api/metas').then(r => r.json())
    ]);

    renderStreak(streaks);
    renderCards(dashboard, streaks);
    renderMetas(metas);
    renderChartHoras(dashboard.horas_por_dia);
    renderChartAcertos(dashboard.acertos_por_dia);
    renderChartMaterias(dashboard.horas_por_materia);
    renderChartEdital(dashboard.edital);
  } catch(e) { console.error('Erro loadDashboard:', e); }
}

function renderCards(dash, streaks) {
  const cards = document.getElementById('cards');
  cards.innerHTML = `
    <div class="card">
      <span class="card-label">Horas Estudadas (total)</span>
      <span class="card-value blue">${dash.total_horas}h</span>
      <span class="card-sub">📚 ${dash.horas_estudo || 0}h leitura/teoria · ❓ ${dash.horas_questoes || 0}h questões</span>
    </div>
    <div class="card">
      <span class="card-label">Questões Resolvidas</span>
      <span class="card-value green">${dash.questoes.total}</span>
      <span class="card-sub">${dash.questoes.percentual}% de acerto</span>
    </div>
    <div class="card">
      <span class="card-label">Edital Concluído</span>
      <span class="card-value peach">${dash.edital.total > 0 ? Math.round(dash.edital.concluido / dash.edital.total * 100) : 0}%</span>
      <span class="card-sub">${dash.edital.concluido}/${dash.edital.total} tópicos</span>
    </div>
    <div class="card">
      <span class="card-label">Flashcards</span>
      <span class="card-value pink">${streaks.hoje.flashcards_revisados || 0}</span>
      <span class="card-sub">revisados hoje (${dash.flashcards.pendentes} pendentes)</span>
    </div>
    <div class="card">
      <span class="card-label">Hoje</span>
      <span class="card-value">${((h)=>{const hrs=Math.floor(h);const mins=Math.round((h-hrs)*60);if(hrs===0)return mins+'min';if(mins===0)return hrs+'h';return hrs+'h '+mins+'min';})(streaks.hoje.horas_estudadas||0)}</span>
      <span class="card-sub">${streaks.hoje.questoes_resolvidas || 0}q · ${streaks.hoje.flashcards_revisados || 0}fc</span>
    </div>
  `;
}

function exportStats() {
  const a = document.createElement('a');
  a.href = '/api/exportar-stats';
  a.download = 'estatisticas_completas.json';
  a.click();
}

async function loadResumoDiario() {
  try {
    const data = await fetch('/api/resumo-diario').then(r => r.json());
    const el = document.getElementById('resumo-diario');
    const hFmt = (h) => { const hrs = Math.floor(h); const mins = Math.round((h - hrs) * 60); if (hrs === 0) return `${mins}min`; if (mins === 0) return `${hrs}h`; return `${hrs}h ${mins}min`; };
    el.innerHTML = `<div style="font-size:0.85rem;line-height:1.8;"><div>⏱ <strong>${hFmt(data.horas || 0)}</strong> estudadas</div><div>❓ <strong>${data.questoes || 0}</strong> questões resolvidas</div><div>🧠 <strong>${data.flashcards || 0}</strong> flashcards revisados</div>${data.sugestao_amanha?.length ? `<div style="margin-top:8px;padding:8px;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;font-size:0.78rem;color:var(--text);">💡 Amanhã foque em: <strong style="color:var(--yellow);">${data.sugestao_amanha.join(', ')}</strong></div>` : ''}</div>`;
  } catch(e) {}
}

// ===== Plans Panel =====
async function loadPlanejadorAprovacao() {
  const data = await fetch('/api/planejador-aprovacao').then(r => r.json());
  const container = document.getElementById('planejador-aprov');
  if (!container) return;
  if (!data.materias.length) { container.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Estude e resolva questões para gerar o planejador.</p>'; return; }
  let html = `<p style="font-size:0.82rem;color:var(--text-sub);margin-bottom:8px;">Meta: ${data.meta_edital}% edital + ${data.meta_questoes}% questões por matéria</p>`;
  data.materias.slice(0, 12).forEach(m => {
    const color = m.status === 'ok' ? 'var(--green)' : m.status === 'atencao' ? 'var(--peach)' : 'var(--red)';
    html += `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);font-size:0.82rem;">
      <span style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;"></span>
      <span style="flex:1;">${m.materia}</span>
      <span style="color:var(--text-sub);">${m.pct_edital}%ed</span>
      <span style="color:var(--text-sub);">${m.pct_questoes}%q</span>
    </div>`;
  });
  container.innerHTML = html;
}

async function loadComparador() {
  const data = await fetch('/api/comparador-progresso').then(r => r.json());
  const container = document.getElementById('comparador-prog');
  if (!container) return;
  if (!data.length) { container.innerHTML = '<p style="color:var(--text-sub);">Sem dados.</p>'; return; }
  let html = '';
  data.forEach(d => {
    html += `<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);font-size:0.82rem;">
      <span style="flex:1;font-weight:600;">${d.cargo}</span>
      <span style="color:var(--text-sub);">${d.horas}h</span>
      <div style="width:60px;height:6px;background:var(--bg-elevated);border-radius:3px;overflow:hidden;"><div style="height:100%;width:${d.pct}%;background:var(--green);border-radius:3px;"></div></div>
      <span style="min-width:36px;text-align:right;color:var(--green);font-weight:700;">${d.pct}%</span>
    </div>`;
  });
  container.innerHTML = html;
}

async function loadPrevisaoData() {
  try {
    const data = await fetch('/api/previsao-data-aprovacao').then(r => r.json());
    const el = document.getElementById('previsao-data');
    if (!data.data_prevista) { el.innerHTML = `<p style="color:var(--text-sub);font-size:0.85rem;">${data.message}</p>`; return; }
    el.innerHTML = `<div style="text-align:center;"><div style="font-size:1.5rem;font-weight:700;color:var(--green);">${data.data_prevista}</div><div style="font-size:0.82rem;color:var(--text-sub);margin-top:4px;">${data.semanas_restantes} semanas restantes</div><div style="font-size:0.78rem;color:var(--text-sub);margin-top:4px;">Ritmo: ${data.ritmo_semanal} tópicos/semana (${data.horas_semana}h/sem)</div><div style="font-size:0.78rem;color:var(--text-sub);">${data.restantes} tópicos restantes</div></div>`;
  } catch(e) {}
}

async function loadPlanoAuto() {
  try {
    const data = await fetch('/api/plano-automatico').then(r => r.json());
    const el = document.getElementById('plano-auto');
    let html = `<div style="font-size:0.82rem;color:var(--text-sub);margin-bottom:8px;">${data.dias_ate_prova} dias | ${data.horas_dia}h/dia | ${data.topicos_restantes} tópicos</div>`;
    html += data.plano.slice(0,8).map(p => `<div style="display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid var(--border);font-size:0.8rem;"><span style="flex:1;">${p.materia}</span><span style="color:var(--blue);">${p.horas_semana}h/sem</span></div>`).join('');
    el.innerHTML = html;
  } catch(e) {}
}

async function loadLinhaTempo() {
  try {
    const data = await fetch('/api/linha-tempo').then(r => r.json());
    const el = document.getElementById('linha-tempo');
    if (!data.length) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Sem sessões registradas.</p>'; return; }
    el.innerHTML = data.slice(0,8).map(s => `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--border);font-size:0.8rem;"><span style="color:var(--text-sub);min-width:70px;">${s.data}</span><span style="flex:1;">${s.materia}</span><span style="color:var(--blue);">${s.horas?.toFixed?.(1) || s.horas}h</span></div>`).join('');
  } catch(e) {}
}

// ===== Planejador Semanal =====
const DIAS_NOMES = ['Seg','Ter','Qua','Qui','Sex','Sáb','Dom'];
const DIAS_CORES = ['var(--blue)','var(--green)','var(--yellow)','var(--peach)','var(--accent)','var(--red)','#94e2d5'];
let planMode = 'auto';

function setPlanMode(mode) {
  planMode = mode;
  document.querySelectorAll('.plan-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  document.getElementById('plan-manual-form').style.display = mode === 'manual' ? 'block' : 'none';
  document.getElementById('plan-descricao').textContent = mode === 'auto'
    ? 'O modo automático distribui matérias do edital inteligentemente com base no desempenho.'
    : 'Adicione manualmente as matérias e horários para cada dia da semana.';
  loadPlanejadorSemanal();
}

async function loadPlanejadorSemanal() {
  try {
    const grid = document.getElementById('planejador-grid');
    const resumo = document.getElementById('planejador-resumo');

    const mats = await fetch('/api/questoes/materias').then(r => r.json()).catch(() => []);
    const dl = document.getElementById('plan-materias-list');
    if (dl) dl.innerHTML = mats.map(m => `<option value="${m}">`).join('');

    let items = [];

    if (planMode === 'auto') {
      const horas = document.getElementById('plan-horas-dia')?.value || '3';
      const calData = await fetch(`/api/calendario-semanal?horas_dia=${horas}`).then(r => r.json()).catch(() => null);
      if (calData && calData.dias) {
        const materiasPorDia = {};
        calData.dias.forEach(dia => {
          if (!materiasPorDia[dia.dia_semana]) materiasPorDia[dia.dia_semana] = {};
          dia.atividades.forEach(a => {
            if (a.materia) {
              if (!materiasPorDia[dia.dia_semana][a.materia]) materiasPorDia[dia.dia_semana][a.materia] = 0;
              materiasPorDia[dia.dia_semana][a.materia] += a.tempo_min / 60;
            }
          });
        });
        for (const [dia, mats2] of Object.entries(materiasPorDia)) {
          for (const [mat, horas2] of Object.entries(mats2)) {
            items.push({ dia_semana: parseInt(dia), materia: mat, horas: Math.round(horas2 * 10) / 10 });
          }
        }
      }
    } else {
      items = await fetch('/api/planejador').then(r => r.json());
    }

    const porDia = {};
    for (let i = 0; i < 7; i++) porDia[i] = [];
    items.forEach(it => {
      if (!porDia[it.dia_semana]) porDia[it.dia_semana] = [];
      porDia[it.dia_semana].push(it);
    });

    let html = '';
    let totalHoras = 0;
    let materiasSet = new Set();

    for (let dia = 0; dia < 7; dia++) {
      const diaItems = porDia[dia];
      const horasDia = diaItems.reduce((a, i) => a + i.horas, 0);
      totalHoras += horasDia;

      html += `<div style="background:var(--bg-surface);border-radius:8px;padding:8px;min-height:120px;border-top:3px solid ${DIAS_CORES[dia]};">`;
      html += `<div style="font-size:0.75rem;font-weight:700;color:${DIAS_CORES[dia]};margin-bottom:6px;text-align:center;">${DIAS_NOMES[dia]}</div>`;

      if (diaItems.length === 0) {
        html += `<div style="color:var(--text-muted);font-size:0.7rem;text-align:center;padding:10px 0;">Livre</div>`;
      } else {
        for (const it of diaItems) {
          materiasSet.add(it.materia);
          html += `<div style="display:flex;align-items:center;gap:4px;padding:3px 0;border-bottom:1px solid var(--border);font-size:0.72rem;">
            <span style="flex:1;color:var(--text);cursor:pointer;" onclick="this.style.whiteSpace = this.style.whiteSpace === 'normal' ? 'nowrap' : 'normal'; this.style.overflow = this.style.whiteSpace === 'nowrap' ? 'hidden' : 'visible'; this.style.textOverflow = this.style.whiteSpace === 'nowrap' ? 'ellipsis' : 'unset';" title="${it.materia}${it.topicos ? ' — ' + it.topicos : ''}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${it.materia}${it.topicos ? ' <span style=&quot;color:var(--text-sub);font-size:0.65rem;&quot;>(' + it.topicos + ')</span>' : ''}</span>
            <span style="color:var(--blue);font-size:0.68rem;white-space:nowrap;">${it.horas}h</span>
            ${planMode === 'manual' && it.id ? `<button onclick="removePlanejadorItem(${it.id})" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:0.7rem;padding:0 2px;" title="Remover">&#10005;</button>` : ''}
          </div>`;
        }
      }

      html += `<div style="margin-top:4px;padding-top:4px;border-top:1px solid var(--border);font-size:0.68rem;color:var(--text-sub);text-align:center;">${horasDia.toFixed(1)}h</div>`;
      html += `</div>`;
    }

    grid.innerHTML = html;

    const diasAtivos = Object.values(porDia).filter(d => d.length > 0).length;
    resumo.innerHTML = `
      <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;">
        <span>📚 <strong>${materiasSet.size}</strong> matérias</span>
        <span>⏰ <strong>${totalHoras.toFixed(1)}h</strong>/semana</span>
        <span>📅 <strong>${diasAtivos}</strong> dias ativos</span>
        <span>∅ <strong>${diasAtivos > 0 ? (totalHoras / diasAtivos).toFixed(1) : 0}h</strong>/dia</span>
        ${planMode === 'auto' ? '<span style="color:var(--green);font-size:0.75rem;">🤖 Gerado automaticamente</span>' : '<span style="color:var(--blue);font-size:0.75rem;">✏️ Configurado manualmente</span>'}
      </div>
    `;
  } catch(e) {
    console.error('Planejador error:', e);
  }
}

async function addPlanejadorItem() {
  const dia = parseInt(document.getElementById('plan-dia').value);
  const materia = document.getElementById('plan-materia').value.trim();
  const horas = parseFloat(document.getElementById('plan-horas').value) || 1.0;
  if (!materia) { alert('Preencha a matéria!'); return; }
  await fetch('/api/planejador', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ dia_semana: dia, materia, horas })
  });
  document.getElementById('plan-materia').value = '';
  loadPlanejadorSemanal();
}

async function removePlanejadorItem(id) {
  await fetch(`/api/planejador/${id}`, { method: 'DELETE' });
  loadPlanejadorSemanal();
}

async function limparPlanejador() {
  if (!confirm('Limpar todo o planejador manual?')) return;
  const items = await fetch('/api/planejador').then(r => r.json());
  for (const it of items) {
    await fetch(`/api/planejador/${it.id}`, { method: 'DELETE' });
  }
  loadPlanejadorSemanal();
}

function regenerarPlanejador() {
  if (planMode === 'manual') {
    alert('O modo manual não regenera automaticamente. Mude para o modo Auto ou adicione matérias manualmente.');
    return;
  }
  loadPlanejadorSemanal();
}

// ===== Calendario (large block, kept in main for simplicity) =====
// NOTE: The full calendar code is complex - importing from a dedicated file would be ideal
// but for this split we keep it here to avoid excessive file count.
let calendarMode = 'auto';
let calendarData = null;
let concluidasHoje = new Set();

function setCalMode(mode) {
  calendarMode = mode;
  document.querySelectorAll('.cal-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  document.getElementById('cal-manual-form').style.display = (mode === 'manual' || mode === 'hibrido') ? 'block' : 'none';
  document.getElementById('cal-hibrido-info').style.display = mode === 'hibrido' ? 'block' : 'none';
  document.getElementById('cal-actions').style.display = (mode === 'manual' || mode === 'hibrido') ? 'flex' : 'none';
  loadCalendario();
}

async function loadCalendario() {
  const el = document.getElementById('calendario-grid');
  const resumoEl = document.getElementById('calendario-resumo');
  const horas = document.getElementById('cal-horas')?.value || '3';
  el.innerHTML = '<div style="text-align:center;color:var(--text-sub);padding:20px;">Gerando calendário...</div>';

  try {
    let data;
    if (calendarMode === 'auto') {
      data = await fetch(`/api/calendario-semanal?horas_dia=${horas}`).then(r => r.json());
    } else if (calendarMode === 'manual') {
      data = await fetch('/api/calendario-personalizado').then(r => r.json());
    } else {
      const custom = await fetch('/api/calendario-personalizado').then(r => r.json());
      const hasData = custom.dias.some(d => d.atividades.length > 0);
      if (hasData) {
        data = custom;
      } else {
        data = await fetch(`/api/calendario-semanal?horas_dia=${horas}`).then(r => r.json());
        const items = [];
        data.dias.forEach(dia => {
          dia.atividades.forEach((a, idx) => {
            items.push({
              dia_semana: dia.dia_semana,
              materia: a.materia || a.descricao || 'Revisão',
              topicos: (a.topicos || []).join(', '),
              tempo_min: a.tempo_min,
              tipo: a.tipo,
              ordem: idx
            });
          });
        });
        await fetch('/api/calendario-personalizado/salvar-completo', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(items)
        });
        data = await fetch('/api/calendario-personalizado').then(r => r.json());
      }
    }

    calendarData = data;
    // Simplified calendar render
    let html = '<div class="cal-grid">';
    const diasNomes = ['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo'];
    const icons = {revisao:'🧠', estudo:'📚', questoes:'❓', pausa:'☕', 'pre-test':'⚡', consolidacao:'📝', ensinar:'🎓'};
    const _now = new Date();
    const hoje = `${_now.getFullYear()}-${String(_now.getMonth()+1).padStart(2,'0')}-${String(_now.getDate()).padStart(2,'0')}`;
    const horaAtual = _now.getHours();

    for (const dia of data.dias) {
      const isToday = dia.data === hoje;
      const nome = dia.nome || diasNomes[dia.dia_semana] || '';
      let dataFormatada = '';
      if (dia.data) {
        const [, mes, d] = dia.data.split('-');
        dataFormatada = `${d}/${mes}`;
      }

      html += `<div class="cal-day ${isToday ? 'today' : ''}" data-date="${dia.data}" data-diasemana="${dia.dia_semana}">`;
      html += `<div class="cal-day-header">${nome} <span class="cal-date">${dataFormatada}</span></div>`;

      if (dia.atividades.length === 0) {
        html += `<div style="color:var(--text-sub);font-size:0.75rem;padding:8px 0;text-align:center;">Descanso</div>`;
      } else {
        // Distribuir atividades em turnos (Manhã: 6-12, Tarde: 12-18, Noite: 18-23)
        const turnos = _distribuirEmTurnos(dia.atividades, isToday, horaAtual);
        html += `<div class="cal-activities-list" data-date="${dia.data}" data-total="${dia.atividades.length}">`;

        // Linha do tempo com hora atual (só no dia de hoje)
        let timelineInserida = false;
        const turnoAtualNome = isToday ? _getTurnoAtual(horaAtual) : '';
        const turnoIcons = {manha: '🌅', tarde: '☀️', noite: '🌙'};
        const turnoNomes = {manha: 'Manhã', tarde: 'Tarde', noite: 'Noite'};
        const turnoCores = {manha: 'var(--yellow)', tarde: 'var(--peach)', noite: 'var(--blue)'};

        for (const turno of ['manha', 'tarde', 'noite']) {
          const ativsTurno = turnos[turno];

          // Inserir linha do tempo ANTES do turno ativo
          if (isToday && !timelineInserida && turno === turnoAtualNome) {
            const agora = new Date();
            const horaStr = `${String(agora.getHours()).padStart(2,'0')}:${String(agora.getMinutes()).padStart(2,'0')}`;
            const turnoInicio = turno === 'manha' ? 6 : turno === 'tarde' ? 12 : 18;
            const turnoFim = turno === 'manha' ? 12 : turno === 'tarde' ? 18 : 23;
            const minutosNoTurno = (horaAtual - turnoInicio) * 60 + agora.getMinutes();
            const totalMinTurno = (turnoFim - turnoInicio) * 60;
            const pctPos = Math.min(95, Math.max(5, (minutosNoTurno / totalMinTurno) * 100));

            html += `<div class="cal-timeline" style="position:relative;margin:8px 0;height:14px;">
              <div style="position:absolute;top:6px;left:0;right:0;height:2px;background:var(--bg-elevated);border-radius:1px;"></div>
              <div style="position:absolute;top:6px;left:0;width:${pctPos}%;height:2px;background:var(--green);border-radius:1px;"></div>
              <div style="position:absolute;top:0;left:${pctPos}%;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;">
                <span style="font-size:0.6rem;color:var(--green);font-weight:700;background:var(--bg-surface);padding:0 3px;border-radius:2px;white-space:nowrap;">${horaStr}</span>
                <div style="width:2px;height:6px;background:var(--green);border-radius:1px;"></div>
              </div>
            </div>`;
            timelineInserida = true;
          }

          if (ativsTurno.length === 0) continue;

          // Header do turno
          const turnoAtivo = isToday && _getTurnoAtual(horaAtual) === turno;
          html += `<div class="cal-turno-header" style="display:flex;align-items:center;gap:4px;padding:3px 6px;margin:4px 0 2px;background:${turnoAtivo ? 'rgba(166,227,161,0.15)' : 'rgba(69,71,90,0.3)'};border-radius:4px;border-left:3px solid ${turnoCores[turno]};">
            <span style="font-size:0.7rem;">${turnoIcons[turno]}</span>
            <span style="font-size:0.68rem;font-weight:600;color:${turnoCores[turno]};">${turnoNomes[turno]}</span>
            ${turnoAtivo ? '<span style="font-size:0.6rem;color:var(--green);margin-left:auto;">● agora</span>' : ''}
          </div>`;

          for (let i = 0; i < ativsTurno.length; i++) {
            const ativ = ativsTurno[i];
          const icon = icons[ativ.tipo] || '📌';
          const materia = ativ.materia || '';
          let detail = '';
          if (ativ.topicos) {
            detail = typeof ativ.topicos === 'string' ? ativ.topicos : (ativ.topicos || []).join(', ');
          } else if (ativ.qtd) {
            detail = `${ativ.qtd} questões`;
          } else if (ativ.descricao) {
            detail = ativ.descricao;
          }
          const ativKey = `${dia.data}|${materia}|${ativ.tipo}`;

          html += `<div class="cal-activity" data-key="${ativKey}" data-materia="${materia}" data-tipo="${ativ.tipo}" data-tempo="${ativ.tempo_min}" data-date="${dia.data}" data-diasemana="${dia.dia_semana}" data-total="${dia.atividades.length}">`;
          html += `<input type="checkbox" class="cal-check" data-key="${ativKey}" onchange="toggleAtivConcluida(this)" title="Marcar como concluída">`;
          html += `<span class="cal-activity-icon">${icon}</span>`;
          html += `<div class="cal-activity-info">`;
          if (materia) html += `<div class="cal-activity-materia">${materia}</div>`;
          if (detail) {
            if (detail.length > 60) {
              const truncated = detail.slice(0,55) + '...';
              html += `<div class="cal-activity-detail cal-expandable" onclick="this.textContent = this.dataset.expanded === '1' ? '${truncated.replace(/'/g,"\\'")}' : this.dataset.full; this.dataset.expanded = this.dataset.expanded === '1' ? '0' : '1';" data-full="${detail.replace(/"/g,'&quot;')}" data-expanded="0" title="Clique para expandir" style="cursor:pointer;">${truncated}</div>`;
            } else {
              html += `<div class="cal-activity-detail">${detail}</div>`;
            }
          }
          html += `</div>`;
          html += `<span class="cal-activity-time">${ativ.tempo_min}min</span>`;
          if (ativ.tempo_min > 0) {
            const pomoLabel = materia || (ativ.tipo === 'revisao' ? 'Flashcards (Revisão)' : detail);
            html += `<button class="cal-pomo-btn" onclick="startPomodoro('${pomoLabel.replace(/'/g, "\\'")}', ${ativ.tempo_min}, '${ativ.tipo}')" title="Iniciar Timer">▶</button>`;
          }
          if ((calendarMode !== 'auto') && ativ.id) {
            html += `<button class="cal-delete-btn" onclick="removeCalItem(${ativ.id})">❌</button>`;
          }
          html += `</div>`;
        }
        } // end turno loop
        html += `</div>`;
      }
      html += `<div class="cal-day-footer">⏱ ${dia.tempo_total_min}min</div>`;
      html += `</div>`;
    }
    html += '</div>';
    el.innerHTML = html;

    // Resumo
    if (data.resumo) {
      resumoEl.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:12px;font-size:0.8rem;"><span style="color:var(--text-sub);">📚 ${data.resumo.total_materias || '?'} matérias</span><span style="color:var(--text-sub);">⏰ ${data.resumo.horas_semana || '?'}h/semana</span></div>`;
    } else {
      const totalMin = data.dias.reduce((a, d) => a + d.tempo_total_min, 0);
      resumoEl.innerHTML = `<div style="font-size:0.8rem;color:var(--text-sub);">⏰ ${Math.round(totalMin/60*10)/10}h/semana planejadas</div>`;
    }

    // Load concluidas
    loadConcluidasHoje();
    // Load extras (banner "agora" + progresso semanal)
    loadCalendarExtras();
  } catch(e) {
    el.innerHTML = '<div style="color:var(--red);text-align:center;padding:20px;">Erro ao gerar calendário.</div>';
    console.error('Calendario error:', e);
  }
}

async function loadConcluidasHoje() {
  try {
    const data = await fetch('/api/calendario/concluidas').then(r => r.json());
    concluidasHoje = new Set(data.map(a => `${a.data}|${a.materia}|${a.tipo}`));
    document.querySelectorAll('.cal-check').forEach(cb => {
      if (concluidasHoje.has(cb.dataset.key)) {
        cb.checked = true;
        cb.closest('.cal-activity')?.classList.add('concluida');
      }
    });
  } catch(e) {}
}

async function toggleAtivConcluida(checkbox) {
  const el = checkbox.closest('.cal-activity');
  const key = checkbox.dataset.key;
  const [dataStr, materia, tipo] = key.split('|');
  const total = parseInt(el.dataset.total) || 1;

  if (checkbox.checked) {
    el.classList.add('concluida');
    await fetch('/api/calendario/atividade-concluida', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ data: dataStr, dia_semana: parseInt(el.dataset.diasemana), materia, tipo, tempo_min: parseInt(el.dataset.tempo), total_atividades: total })
    });
    concluidasHoje.add(key);
  } else {
    el.classList.remove('concluida');
    await fetch('/api/calendario/atividade-concluida', {
      method: 'DELETE', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ data: dataStr, materia, tipo, total_atividades: total })
    });
    concluidasHoje.delete(key);
  }
}

async function regenerarCalendario() {
  if (!confirm('Deseja regerar o calendário?')) return;
  try {
    await fetch('/api/calendario-personalizado', { method: 'DELETE' });
    calendarMode = 'auto';
    document.querySelectorAll('.cal-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === 'auto'));
    document.getElementById('cal-manual-form').style.display = 'none';
    document.getElementById('cal-hibrido-info').style.display = 'none';
    const actionsEl = document.getElementById('cal-actions');
    if (actionsEl) actionsEl.style.display = 'none';
    await loadCalendario();
  } catch(e) { alert('Erro ao regerar calendário: ' + e.message); }
}

async function regenerarInteligente() {
  if (!confirm('🧠 Regenerar calendário usando análise inteligente?\n\nIsso irá apagar o calendário atual e criar um novo otimizado com base em:\n• Peso da banca\n• Caderno de erros\n• Performance por matéria\n• Dias sem estudar\n• Revisão espaçada\n• Tópicos pendentes')) return;
  try {
    const horasSelect = document.getElementById('cal-horas-dia');
    const horas_dia = horasSelect ? parseFloat(horasSelect.value) : null;
    const res = await fetch('/api/planejador/reset-inteligente', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ horas_dia })
    });
    const data = await res.json();
    if (data.ok) {
      calendarMode = 'personalizado';
      document.querySelectorAll('.cal-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === 'personalizado'));
      document.getElementById('cal-manual-form').style.display = 'none';
      const actionsEl = document.getElementById('cal-actions');
      if (actionsEl) actionsEl.style.display = 'none';
      await loadCalendario();
      alert(`✅ ${data.message}\n\n📊 ${data.stats.total_materias} matérias · ${data.stats.horas_semana}h/semana`);
    } else {
      alert('⚠️ ' + (data.message || 'Erro ao gerar calendário inteligente'));
    }
  } catch(e) { alert('Erro ao regenerar inteligente: ' + e.message); }
}

async function addCalendarioItem() {
  const dia = parseInt(document.getElementById('cal-add-dia').value);
  const tipo = document.getElementById('cal-add-tipo').value;
  const materia = document.getElementById('cal-add-materia').value.trim();
  const topicos = document.getElementById('cal-add-topicos').value.trim();
  const tempo = parseInt(document.getElementById('cal-add-tempo').value) || 60;
  if (!materia) return;
  await fetch('/api/calendario-personalizado', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ dia_semana: dia, materia, topicos, tempo_min: tempo, tipo, ordem: 0 })
  });
  document.getElementById('cal-add-materia').value = '';
  document.getElementById('cal-add-topicos').value = '';
  loadCalendario();
}

async function removeCalItem(id) {
  await fetch(`/api/calendario-personalizado/${id}`, { method: 'DELETE' });
  loadCalendario();
}

async function salvarCalendario() { /* no-op, saved on action */ }

async function limparCalendario() {
  if (!confirm('Limpar todo o calendário personalizado?')) return;
  await fetch('/api/calendario-personalizado', { method: 'DELETE' });
  loadCalendario();
}

// Pomodoro
let pomoInterval = null, pomoSeconds = 0, pomoTotal = 0, pomoPaused = false;
function startPomodoro(materia, tempoMin, tipo) {
  pomoSeconds = tempoMin * 60;
  pomoTotal = pomoSeconds;
  pomoPaused = false;
  document.getElementById('pomo-materia').textContent = materia;
  document.getElementById('pomodoro-overlay').style.display = 'block';
  document.getElementById('pomo-toggle-btn').textContent = '⏸ Pausar';
  updatePomoDisplay();
  clearInterval(pomoInterval);
  pomoInterval = setInterval(() => {
    if (!pomoPaused) {
      pomoSeconds--;
      updatePomoDisplay();
      if (pomoSeconds <= 0) {
        clearInterval(pomoInterval);
        document.getElementById('pomo-timer').textContent = '🎉 FIM!';
        document.getElementById('pomo-timer').style.color = 'var(--green)';
        if (Notification.permission === 'granted') new Notification('⏰ Pomodoro finalizado!', {body: `Sessão de ${materia} concluída!`});
        const horasEstudadas = pomoTotal / 3600;
        if (materia && horasEstudadas > 0) {
          fetch('/api/sessoes-estudo/registrar', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ horas: Math.round(horasEstudadas * 100) / 100, materia, tipo: 'pomodoro' })
          }).then(() => { loadConcluidasHoje(); }).catch(() => {});
        }
      }
    }
  }, 1000);
  localStorage.setItem('pomo_timer', JSON.stringify({
    materia, tipo: tipo || 'estudo', totalSeconds: pomoTotal,
    endTime: Date.now() + pomoTotal * 1000, paused: false, remainingWhenPaused: 0
  }));
  if (tipo === 'revisao' || tipo === 'flashcard') window.location.href = '/#tab-flashcards';
  else if (tipo === 'questoes') window.location.href = '/questoes.html';
  else if (tipo === 'estudo') window.location.href = '/';
  if (Notification.permission === 'default') Notification.requestPermission();
}
function updatePomoDisplay() {
  const m = Math.floor(pomoSeconds / 60), s = pomoSeconds % 60;
  document.getElementById('pomo-timer').textContent = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  document.getElementById('pomo-timer').style.color = pomoSeconds < 60 ? 'var(--red)' : '#cdd6f4';
}
function togglePomodoro() {
  pomoPaused = !pomoPaused;
  document.getElementById('pomo-toggle-btn').textContent = pomoPaused ? '▶ Retomar' : '⏸ Pausar';
}
function resetPomodoro() { pomoSeconds = pomoTotal; pomoPaused = false; updatePomoDisplay(); document.getElementById('pomo-toggle-btn').textContent = '⏸ Pausar'; }
function closePomodoro() { clearInterval(pomoInterval); document.getElementById('pomodoro-overlay').style.display = 'none'; }

// ===== Mastery & League =====
async function loadMasteryOverview() {
  try {
    const data = await fetch('/api/edital/mastery-overview').then(r => r.json());
    const el = document.getElementById('mastery-overview');
    if (!el) return;
    if (!data.materias || data.materias.length === 0) {
      el.innerHTML = '<span style="color:var(--text-sub);font-size:0.8rem;">Responda questões para ver seu domínio</span>';
      return;
    }
    el.innerHTML = data.materias.slice(0, 8).map(m => {
      const pct = Math.round(m.avg_mastery || 0);
      const color = pct >= 80 ? 'var(--green)' : pct >= 50 ? 'var(--yellow)' : pct >= 20 ? 'var(--peach)' : 'var(--red)';
      const label = pct >= 80 ? 'Consolidado' : pct >= 50 ? 'Dominado' : pct >= 20 ? 'Em Progresso' : 'Não Dominado';
      return `<div style="margin-bottom:6px;">
        <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:var(--text);">
          <span style="max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${m.materia}</span>
          <span style="color:${color};font-weight:600;">${pct}% ${label}</span>
        </div>
        <div style="height:4px;background:var(--bg-elevated);border-radius:2px;overflow:hidden;">
          <div style="width:${pct}%;height:100%;background:${color};border-radius:2px;transition:width 0.5s;"></div>
        </div>
      </div>`;
    }).join('');
  } catch(e) {
    const el = document.getElementById('mastery-overview');
    if (el) el.innerHTML = '<span style="color:var(--text-sub);font-size:0.8rem;">Responda questões para ver seu domínio</span>';
  }
}

async function loadLeagueBadge() {
  try {
    const data = await fetch('/api/leagues/current').then(r => r.json());
    let badge = document.getElementById('league-badge');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'league-badge';
      badge.style.cssText = 'cursor:pointer;';
      badge.onclick = () => window.location.href = '/social.html';
      const streakBar = document.querySelector('.streak-bar');
      if (streakBar) streakBar.appendChild(badge);
    }
    const tierEmojis = {bronze:'🥉', prata:'🥈', ouro:'🥇', diamante:'💎', mestre:'👑'};
    const emoji = tierEmojis[data.tier] || '🏆';
    badge.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;" title="Liga ${data.tier} - #${data.user_rank}">
      <span style="font-size:1.2rem;">${emoji}</span>
      <span style="font-size:0.6rem;color:var(--accent);">#${data.user_rank}</span>
    </div>`;
  } catch(e) {}
}

// ===== Push Notifications =====
function initPushPermissionBanner() {
  if (typeof Notification === 'undefined') return;
  if (Notification.permission === 'default') {
    const banner = document.createElement('div');
    banner.id = 'push-permission-banner';
    banner.innerHTML = `
      <div style="background:var(--bg-surface);border:1px solid #cba6f7;border-radius:8px;padding:12px 16px;margin-bottom:12px;display:flex;align-items:center;gap:10px;">
        <span style="font-size:1.2rem;">🔔</span>
        <div style="flex:1;">
          <div style="color:var(--text);font-size:0.85rem;font-weight:500;">Ativar notificações?</div>
          <div style="color:var(--text-sub);font-size:0.75rem;">Receba lembretes de streak, flashcards e provas</div>
        </div>
        <button onclick="requestPushPermission()" style="background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:6px 14px;font-size:0.8rem;font-weight:600;cursor:pointer;">Ativar</button>
        <button onclick="this.parentNode.parentNode.remove()" style="background:none;border:none;color:var(--text-sub);cursor:pointer;">✕</button>
      </div>
    `;
    const main = document.querySelector('.main-content') || document.querySelector('.dash-panel.active');
    if (main) main.prepend(banner);
  }
}

async function requestPushPermission() {
  const result = await Notification.requestPermission();
  document.getElementById('push-permission-banner')?.remove();
  if (result === 'granted') {
    try {
      const registration = await navigator.serviceWorker.ready;
      const vapidKey = await fetch('/api/push/vapid-key').then(r => r.json()).then(d => d.key).catch(() => null);
      if (vapidKey) {
        const subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true, applicationServerKey: vapidKey
        });
        await fetch('/api/push/subscribe', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(subscription.toJSON())
        });
      }
    } catch(e) { console.error('Push subscription error:', e); }
    if (typeof showToast === 'function') showToast('🔔 Notificações ativadas!', 'success');
  }
}

// ===== User Profile =====
(async function loadDashUserProfile() {
  try {
    const profile = await fetch('/api/social/profile').then(r => r.json());
    const nome = profile.username || 'Estudante';
    const initials = nome.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
    const avatarEl = document.getElementById('dash-user-avatar');
    const nameEl = document.getElementById('dash-user-name');
    const planEl = document.getElementById('dash-user-plan');
    if (avatarEl) avatarEl.textContent = initials || '👤';
    if (nameEl) nameEl.textContent = nome.split(' ')[0];
    let plano = 'ilimitado';
    try {
      const meRes = await fetch('/api/auth/me');
      if (meRes.ok) {
        const me = await meRes.json();
        if (me.plano && me.plano !== 'free') plano = me.plano;
        if (me.nome && me.nome !== 'Estudante') {
          const authName = me.nome.split(' ')[0];
          if (nameEl) nameEl.textContent = authName;
          const authInitials = me.nome.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
          if (avatarEl) avatarEl.textContent = authInitials;
        }
      }
    } catch { }
    const labels = { ilimitado: '👑 Ilimitado', premium: '⭐ Premium', free: '🆓 Free' };
    if (planEl) planEl.textContent = labels[plano] || '⭐ ' + plano;
  } catch { }
})();

// ===== Load Active Panel =====
function loadActivePanel() {
  const active = document.querySelector('.dash-panel.active')?.id;
  switch(active) {
    case 'panel-overview':
      loadDashboard();
      loadResumoDiario();
      loadHeatmap();
      loadDashCountdown();
      loadDesafioDiarioCard();
      break;
    case 'panel-treinador':
      loadTreinador();
      loadTrilha();
      loadStudyIntelligence();
      loadCurvaEsquecimento();
      loadRevisoesPendentes();
      loadDailyChallenge();
      loadIntercalacao();
      loadPraticaDelib();
      loadFeynmanMaterias();
      loadPontosFragcos();
      loadConexoes();
      loadTempoResultado();
      loadDissertMaterias();
      loadSpacing();
      break;
    case 'panel-calendario':
      loadCalendario();
      break;
    case 'panel-analytics':
      loadEvolucao();
      loadRadar();
      loadHeatmapErros();
      loadRaioX();
      loadAnaliseErros();
      loadPraticaDeliberada();
      loadProjecaoNota();
      loadVelocidade();
      loadConsistencia();
      loadMetasRealizado();
      loadRankingMaterias();
      break;
    case 'panel-gamification':
      loadGamification();
      loadMissoes();
      loadDesafios();
      loadShareBox();
      break;
    case 'panel-plans':
      loadPlanejadorAprovacao();
      loadPlanoAuto();
      loadPrevisaoData();
      loadComparador();
      loadLinhaTempo();
      loadRelatorioSemanal();
      loadPlanejadorSemanal();
      break;
  }
}

function loadPraticaDeliberada() {
  fetch('/api/pratica-deliberada').then(r => r.json()).then(renderPratica).catch(() => {});
}
function loadRelatorioSemanal() {
  fetch('/api/relatorio-semanal').then(r => r.json()).then(renderRelatorio).catch(() => {});
}

// Restore panel from sidebar navigation
const savedPanel = localStorage.getItem('concurseiro_dash_panel');
if (savedPanel) {
  localStorage.removeItem('concurseiro_dash_panel');
  const tab = document.querySelector(`.dash-tab[data-panel="${savedPanel}"]`);
  if (tab) tab.click();
}

// Initial load
loadActivePanel();
loadMasteryOverview();
loadLeagueBadge();
setTimeout(initPushPermissionBanner, 2000);

// ===== Window assignments for HTML onclick/onchange =====
window.exportStats = exportStats;
window.setCalMode = setCalMode;
window.regenerarCalendario = regenerarCalendario;
window.regenerarInteligente = regenerarInteligente;
window.resetPlanejadorInteligente = async function() {
  try {
    const horasSelect = document.getElementById('cal-horas-dia');
    const horas_dia = horasSelect ? parseFloat(horasSelect.value) : 4;
    const res = await fetch('/api/planejador/reset-inteligente', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ horas_dia })
    });
    const data = await res.json();
    if (data.ok) {
      await loadCalendario();
      if (typeof showToast === 'function') showToast('Planejador regenerado com inteligência!', 'success');
      else alert('Planejador regenerado com inteligência!');
    } else {
      if (typeof showToast === 'function') showToast(data.message || 'Erro ao regenerar', 'error');
      else alert('⚠️ ' + (data.message || 'Erro ao gerar calendário inteligente'));
    }
  } catch(e) {
    if (typeof showToast === 'function') showToast('Erro: ' + e.message, 'error');
    else alert('Erro ao regenerar inteligente: ' + e.message);
  }
};
window.addCalendarioItem = addCalendarioItem;
window.removeCalItem = removeCalItem;
window.salvarCalendario = salvarCalendario;
window.limparCalendario = limparCalendario;
window.toggleAtivConcluida = toggleAtivConcluida;
window.startPomodoro = startPomodoro;
window.togglePomodoro = togglePomodoro;
window.resetPomodoro = resetPomodoro;
window.closePomodoro = closePomodoro;
window.iniciarAtividadeAgora = function() {
  const s = window._calAgoraSugestao;
  if (!s || s.tipo === 'pausa') return;
  if (window.startTimerGlobal) window.startTimerGlobal(s.tempo_min || 25, s.materia || 'Estudo');
  else alert(`Inicie ${s.tempo_min}min de ${s.materia} (${s.tipo})`);
};
window.setPlanMode = setPlanMode;
window.loadPlanejadorSemanal = loadPlanejadorSemanal;
window.regenerarPlanejador = regenerarPlanejador;
window.addPlanejadorItem = addPlanejadorItem;
window.removePlanejadorItem = removePlanejadorItem;
window.limparPlanejador = limparPlanejador;
window.requestPushPermission = requestPushPermission;
window.toggleCalCollapse = function(dateKey) {
  const container = document.getElementById('cal-more-' + dateKey);
  const btn = document.getElementById('cal-expand-' + dateKey);
  if (!container) return;
  if (container.style.display === 'none') {
    container.style.display = 'block';
    if (btn) { btn.textContent = '··· recolher'; btn.style.color = 'var(--text-sub)'; }
  } else {
    container.style.display = 'none';
    const extras = container.querySelectorAll('.cal-activity').length;
    if (btn) { btn.textContent = `··· ver mais (${extras})`; btn.style.color = 'var(--blue)'; }
  }
};
window.toggleDetailExpand = function(el) {
  const short = el.querySelector('.cal-detail-short');
  const full = el.querySelector('.cal-detail-full');
  if (full.style.display === 'none') {
    short.style.display = 'none';
    full.style.display = 'inline';
  } else {
    short.style.display = 'inline';
    full.style.display = 'none';
  }
};

// Profile menu toggle
window.toggleDashProfileMenu = function() {
  const menu = document.getElementById('dash-profile-menu');
  if (!menu) return;
  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
};

// Close profile menu on click outside
document.addEventListener('click', (e) => {
  const menu = document.getElementById('dash-profile-menu');
  const section = document.getElementById('dash-user-section');
  if (menu && section && !section.contains(e.target) && !menu.contains(e.target)) {
    menu.style.display = 'none';
  }
});

// ========== CALENDAR HELPERS: Turnos + Timeline ==========

function _getTurnoAtual(hora) {
  if (hora >= 6 && hora < 12) return 'manha';
  if (hora >= 12 && hora < 18) return 'tarde';
  return 'noite';
}

function _distribuirEmTurnos(atividades, isToday, horaAtual) {
  const turnos = { manha: [], tarde: [], noite: [] };
  if (!atividades || atividades.length === 0) return turnos;

  const tempoTotal = atividades.reduce((a, at) => a + (at.tempo_min || 0), 0);
  const proporcoes = { manha: 0.4, tarde: 0.35, noite: 0.25 };
  let turnoAtual = 'manha';
  let tempoAcumulado = 0;
  const limiteManha = tempoTotal * proporcoes.manha;
  const limiteTarde = tempoTotal * (proporcoes.manha + proporcoes.tarde);

  for (const ativ of atividades) {
    if (ativ.tipo === 'revisao' && turnoAtual === 'manha') {
      turnos.manha.push(ativ);
      tempoAcumulado += ativ.tempo_min || 0;
      continue;
    }
    if (tempoAcumulado >= limiteTarde) {
      turnoAtual = 'noite';
    } else if (tempoAcumulado >= limiteManha) {
      turnoAtual = 'tarde';
    }
    turnos[turnoAtual].push(ativ);
    tempoAcumulado += ativ.tempo_min || 0;
  }

  // Se é HOJE: mover atividades de turnos passados para o turno atual
  if (isToday) {
    const turnoAgora = _getTurnoAtual(horaAtual);
    const ordemTurnos = ['manha', 'tarde', 'noite'];
    const idxTurnoAtual = ordemTurnos.indexOf(turnoAgora);

    for (let i = 0; i < idxTurnoAtual; i++) {
      const turnoPassado = ordemTurnos[i];
      const naoFeitas = turnos[turnoPassado].filter(a => !a._concluida);
      if (naoFeitas.length > 0) {
        naoFeitas.forEach(a => { a._adiada = true; });
        turnos[turnoAgora] = [...naoFeitas, ...turnos[turnoAgora]];
        turnos[turnoPassado] = turnos[turnoPassado].filter(a => !a._adiada);
      }
    }
  }

  return turnos;
}

// ========== CALENDAR EXTRAS: Banner "Agora" + Progresso Semanal ==========

async function loadCalendarExtras() {
  // Load streak and alertas
  loadCalStreak();
  loadAlertasNegligenciadas();

  // Atualizar linha do tempo (agulha) a cada minuto
  clearInterval(window._calTimelineInterval);
  window._calTimelineInterval = setInterval(() => {
    const tl = document.querySelector('.cal-timeline');
    if (tl) {
      const agora = new Date();
      const h = agora.getHours();
      const horaStr = `${String(h).padStart(2,'0')}:${String(agora.getMinutes()).padStart(2,'0')}`;
      const turno = h >= 6 && h < 12 ? 'manha' : h >= 12 && h < 18 ? 'tarde' : 'noite';
      const turnoInicio = turno === 'manha' ? 6 : turno === 'tarde' ? 12 : 18;
      const turnoFim = turno === 'manha' ? 12 : turno === 'tarde' ? 18 : 23;
      const minutosNoTurno = (h - turnoInicio) * 60 + agora.getMinutes();
      const totalMinTurno = (turnoFim - turnoInicio) * 60;
      const pctPos = Math.min(95, Math.max(5, (minutosNoTurno / totalMinTurno) * 100));
      const needle = tl.querySelector('div:last-child');
      const bar = tl.querySelectorAll('div')[1];
      if (needle) needle.style.left = pctPos + '%';
      if (bar) bar.style.width = pctPos + '%';
      const label = tl.querySelector('span');
      if (label) label.textContent = horaStr;
    }
  }, 60000);

  // 1. Banner "O que estudar agora"
  try {
    const agora = await fetch('/api/calendario/agora').then(r => r.json());
    const banner = document.getElementById('cal-agora-banner');
    if (banner && agora.sugestao) {
      banner.style.display = 'block';
      const materiaEl = document.getElementById('cal-agora-materia');
      const motivoEl = document.getElementById('cal-agora-motivo');
      const pctEl = document.getElementById('cal-agora-pct');
      if (materiaEl) materiaEl.textContent = `${agora.turno_label || ''} — ${agora.sugestao.materia}`;
      if (motivoEl) motivoEl.textContent = agora.sugestao.motivo || '';
      if (agora.progresso_dia && pctEl) {
        const p = agora.progresso_dia.pct;
        pctEl.textContent = `${p}%`;
        pctEl.style.color = p >= 100 ? 'var(--green)' : p >= 50 ? 'var(--yellow)' : 'var(--blue)';
      }
      window._calAgoraSugestao = agora.sugestao;
    }
  } catch(e) {}

  // 2. Progresso semanal visual
  try {
    const prog = await fetch('/api/calendario/progresso-semanal').then(r => r.json());
    const container = document.getElementById('cal-week-progress');
    const barsEl = document.getElementById('cal-week-bars');
    if (container && prog.dias) {
      container.style.display = 'block';
      const pctTextEl = document.getElementById('cal-week-pct-text');
      if (pctTextEl) pctTextEl.textContent = `${prog.resumo?.pct_semanal || 0}% concluído`;
      let bars = '';
      for (const dia of prog.dias) {
        const h = Math.max(4, (dia.pct || 0) * 0.3);
        let color = 'var(--bg-elevated)';
        if (dia.status === 'completo') color = 'var(--green)';
        else if (dia.status === 'parcial') color = 'var(--yellow)';
        else if (dia.status === 'perdido') color = 'rgba(243,139,168,0.15)';
        const border = dia.is_today ? 'border:1px solid var(--accent);' : '';
        bars += `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;">
          <div style="width:100%;height:${h}px;background:${color};border-radius:3px;${border}transition:height 0.3s;"></div>
          <span style="font-size:0.6rem;color:${dia.is_today ? 'var(--accent)' : 'var(--text-sub)'};font-weight:${dia.is_today ? '700' : '400'};">${dia.nome || ''}</span>
        </div>`;
      }
      if (barsEl) barsEl.innerHTML = bars;
    }
  } catch(e) {}
}

// ========== RECOVERED FUNCTIONS (lost during modularization) ==========

// Iniciar atividade sugerida pelo banner "Agora"
window.iniciarAtividadeAgora = function() {
  const s = window._calAgoraSugestao;
  if (!s || s.tipo === 'pausa') return;
  if (window.startTimerGlobal) {
    window.startTimerGlobal(s.tempo_min || 25, s.materia || 'Estudo');
  } else if (window.startPomodoro) {
    window.startPomodoro(s.materia || 'Estudo', s.tempo_min || 25, s.tipo || 'estudo');
  }
};

// Calendar streak loader
async function loadCalStreak() {
  try {
    const data = await fetch('/api/calendario/streak').then(r => r.json());
    const streakEl = document.getElementById('cal-streak-num');
    const fillEl = document.getElementById('cal-progress-fill');
    const txtEl = document.getElementById('cal-progress-txt');
    if (streakEl) streakEl.textContent = `${data.streak_calendario || 0} dias seguindo o plano`;
    const pct = data.hoje?.pct_conclusao || 0;
    if (fillEl) fillEl.style.width = `${pct}%`;
    if (txtEl) txtEl.textContent = `${Math.round(pct)}% hoje`;
    if (pct >= 100 && streakEl) streakEl.textContent += ' 🎉 +50 XP';
  } catch(e) {}
}

// Alerta de matérias negligenciadas
async function loadAlertasNegligenciadas() {
  try {
    const data = await fetch('/api/calendario/materias-negligenciadas?dias_limite=5').then(r => r.json());
    const el = document.getElementById('cal-alertas');
    if (!el || data.total === 0) { if(el) el.style.display = 'none'; return; }
    el.style.display = 'block';
    const top3 = data.negligenciadas.slice(0, 3);
    el.innerHTML = `<div style="background:#3a2a1e;border:1px solid var(--yellow);border-radius:8px;padding:10px 12px;font-size:0.8rem;">
      <div style="color:var(--yellow);font-weight:600;margin-bottom:6px;">⚠️ Matérias negligenciadas</div>
      ${top3.map(m => `<div style="color:var(--text);padding:2px 0;">• <strong>${m.materia}</strong> — ${m.dias_sem_estudar} dias sem estudar${m.urgencia === 'alta' ? ' 🔴' : ' 🟡'}</div>`).join('')}
    </div>`;
  } catch(e) {}
}

// Toggle calendar day collapse (show more/less activities)
window.toggleCalCollapse = function(dateKey) {
  const container = document.getElementById('cal-more-' + dateKey);
  const btn = document.getElementById('cal-expand-' + dateKey);
  if (!container) return;
  if (container.style.display === 'none') {
    container.style.display = 'block';
    if (btn) { btn.textContent = '··· recolher'; btn.style.color = 'var(--text-sub)'; }
  } else {
    container.style.display = 'none';
    const extras = container.querySelectorAll('.cal-activity').length;
    if (btn) { btn.textContent = `··· ver mais (${extras})`; btn.style.color = 'var(--blue)'; }
  }
};

// Toggle detail text expand (truncated activity descriptions)
window.toggleDetailExpand = function(el) {
  const short = el.querySelector('.cal-detail-short');
  const full = el.querySelector('.cal-detail-full');
  if (!short || !full) return;
  if (full.style.display === 'none') {
    short.style.display = 'none';
    full.style.display = 'inline';
  } else {
    short.style.display = 'inline';
    full.style.display = 'none';
  }
};

// Drag & drop for calendar items (manual mode)
function initDragDrop() {
  const items = document.querySelectorAll('.cal-activity[draggable]');
  items.forEach(item => {
    item.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', item.dataset.key || '');
      item.style.opacity = '0.5';
    });
    item.addEventListener('dragend', () => { item.style.opacity = '1'; });
  });
  const days = document.querySelectorAll('.cal-day');
  days.forEach(day => {
    day.addEventListener('dragover', (e) => { e.preventDefault(); day.style.background = 'var(--bg-elevated)'; });
    day.addEventListener('dragleave', () => { day.style.background = ''; });
    day.addEventListener('drop', (e) => {
      e.preventDefault();
      day.style.background = '';
      // TODO: implement reorder API call
    });
  });
}


// ===== AGENDA DO DIA (Micro-planning) =====
function _toastDash(msg) {
  const t = document.createElement('div');
  t.style.cssText = 'position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:10px;background:var(--bg-surface,#313244);color:var(--text,#cdd6f4);font-size:0.85rem;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,0.3);z-index:9999;animation:fadeIn 0.3s ease;';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; setTimeout(() => t.remove(), 300); }, 3000);
}

async function loadAgendaHoje() {
  const container = document.getElementById('agenda-blocos');
  if (!container) return;
  try {
    const res = await fetch('/api/calendario/hoje');
    if (!res.ok) throw new Error('Erro ao carregar agenda');
    const data = await res.json();
    const blocos = data.blocos || [];
    window._agendaBlocos = blocos;

    if (!blocos.length) {
      container.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;text-align:center;padding:16px;">Adicione matérias ao ciclo para gerar sua agenda.</p>';
      return;
    }

    container.innerHTML = `
      <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:8px;display:flex;gap:12px;flex-wrap:wrap;">
        <span>⏱ ${data.resumo.tempo_estudo_min}min estudo</span>
        <span>☕ ${data.resumo.tempo_pausas_min}min pausas</span>
        <span>📚 ${data.resumo.materias.length} matérias</span>
        ${data.resumo.revisoes_preditivas > 0 ? `<span style="color:var(--yellow);">🔮 ${data.resumo.revisoes_preditivas} revisões preditivas</span>` : ''}
      </div>
      <div class="agenda-timeline">
        ${blocos.map((b, idx) => {
          const isPausa = b.tipo === 'pausa' || b.tipo === 'pausa_longa';
          const isStudy = !isPausa;
          const playBtn = isStudy ? `<button class="agenda-play-btn" data-idx="${idx}" title="Iniciar estudo">▶</button>` : '';
          return `
            <div class="agenda-bloco ${isPausa ? 'agenda-bloco--pausa' : ''}" style="border-left:4px solid ${b.cor};">
              <div class="agenda-bloco__hora">${b.hora_inicio}</div>
              <div class="agenda-bloco__content">
                <div class="agenda-bloco__desc">${b.descricao}</div>
                ${!isPausa ? `<div class="agenda-bloco__meta">${b.materia || ''} · ${b.duracao_min}min${b.tecnica ? ' · ' + b.tecnica : ''}</div>` : ''}
              </div>
              ${playBtn}
            </div>`;
        }).join('')}
      </div>
      <div style="margin-top:8px;font-size:0.68rem;color:var(--text-sub);text-align:right;">
        ${data.hora_inicio} – ${data.hora_fim} · ${data.tecnicas_aplicadas.length} técnicas ativas
      </div>
    `;
  } catch(e) {
    container.innerHTML = '<p style="color:var(--red);font-size:0.82rem;">Erro ao carregar agenda</p>';
  }
}
window.loadAgendaHoje = loadAgendaHoje;

// Ação do botão Play na agenda: inicia timer e navega para PDF
// Usa event delegation — os dados dos blocos ficam em window._agendaBlocos
window._agendaBlocos = [];

document.addEventListener('click', function(e) {
  const btn = e.target.closest('.agenda-play-btn');
  if (!btn) return;
  const idx = parseInt(btn.dataset.idx);
  const b = window._agendaBlocos[idx];
  if (!b) return;

  // 1. Iniciar timer global
  if (window.startGlobalTimer) {
    window.startGlobalTimer(b.materia || 'Estudo', b.duracao_min, 'estudo');
  }

  // 2. Navegar de acordo com o tipo
  if (b.pdf_link) {
    const page = b.pdf_pagina > 0 ? `&page=${b.pdf_pagina}` : '';
    window.location.href = `/viewer.html?file=${encodeURIComponent(b.pdf_link)}${page}`;
  } else if (b.tipo === 'questoes' || b.tipo === 'questoes_avancadas') {
    window.location.href = `/questoes.html?materia=${encodeURIComponent(b.materia || '')}`;
  } else if (b.edital_id) {
    // Sem PDF vinculado: informar e sugerir vincular
    if (window.toast) {
      window.toast('📎 Nenhum PDF vinculado a este tópico. Vá em Edital → clique no tópico → "Vincular PDF" para associar um material.', 'warning', 5000);
    } else {
      alert('📎 Nenhum PDF vinculado. Vincule um PDF ao tópico no Edital.');
    }
  }
});

window.openStudyPrefs = function() {
  const overlay = document.createElement('div');
  overlay.id = 'modal-study-prefs';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.2s ease;';
  overlay.innerHTML = `
    <div style="background:var(--bg-surface, #313244);border:1px solid var(--border, #45475a);border-radius:16px;padding:24px;max-width:360px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
      <h3 style="color:var(--text, #cdd6f4);margin:0 0 16px;font-size:1rem;">⚙️ Configurar Horário de Estudo</h3>
      <div style="display:flex;flex-direction:column;gap:12px;">
        <div style="display:flex;gap:8px;">
          <div style="flex:1;">
            <label style="font-size:0.72rem;color:var(--text-sub);">Início</label>
            <input type="time" id="pref-hora-inicio" value="08:00" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.85rem;">
          </div>
          <div style="flex:1;">
            <label style="font-size:0.72rem;color:var(--text-sub);">Fim</label>
            <input type="time" id="pref-hora-fim" value="12:00" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.85rem;">
          </div>
        </div>
        <div>
          <label style="font-size:0.72rem;color:var(--text-sub);">Bloco de estudo (minutos)</label>
          <input type="number" id="pref-bloco" value="25" min="15" max="60" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.85rem;">
        </div>
        <div style="display:flex;gap:8px;margin-top:8px;">
          <button onclick="document.getElementById('modal-study-prefs').remove()" style="flex:1;padding:10px;background:var(--border);color:var(--text);border:none;border-radius:8px;cursor:pointer;font-weight:600;">Cancelar</button>
          <button onclick="saveStudyPrefsModal()" style="flex:1;padding:10px;background:var(--accent);color:#1e1e2e;border:none;border-radius:8px;cursor:pointer;font-weight:600;">Salvar</button>
        </div>
      </div>
    </div>
  `;
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.appendChild(overlay);

  // Carregar valores atuais
  fetch('/api/calendario/preferencias').then(r => r.json()).then(data => {
    document.getElementById('pref-hora-inicio').value = data.hora_inicio || '08:00';
    document.getElementById('pref-hora-fim').value = data.hora_fim || '12:00';
    document.getElementById('pref-bloco').value = data.bloco_min || 25;
  }).catch(() => {});
};

window.saveStudyPrefsModal = function() {
  const hora_inicio = document.getElementById('pref-hora-inicio').value;
  const hora_fim = document.getElementById('pref-hora-fim').value;
  const bloco_min = parseInt(document.getElementById('pref-bloco').value) || 25;

  fetch('/api/calendario/preferencias', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      hora_inicio, hora_fim, bloco_min,
      pausa_min: 5, pausa_longa_min: 15, blocos_antes_pausa_longa: 4,
      dias_estudo: [0,1,2,3,4,5]
    })
  }).then(() => {
    document.getElementById('modal-study-prefs').remove();
    loadAgendaHoje();
  });
};

// Auto-load agenda
loadAgendaHoje();


// ===== META ADAPTATIVA SEMANAL =====
async function loadMetaAdaptativa() {
  try {
    const res = await fetch('/api/metas/adaptativa');
    if (!res.ok) return;
    const data = await res.json();
    const card = document.getElementById('meta-adaptativa-card');
    const content = document.getElementById('meta-adaptativa-content');
    if (!card || !content) return;

    card.style.display = 'block';

    const m = data.meta_semana;
    const p = data.progresso_semana;
    const proj = data.projecao;

    content.innerHTML = `
      <div style="margin-bottom:10px;font-size:0.85rem;color:var(--text);font-weight:600;">${data.mensagem}</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">
        <div style="text-align:center;padding:8px;background:var(--bg);border-radius:8px;">
          <div style="font-size:1.1rem;font-weight:700;color:${p.pct_horas >= 100 ? 'var(--green)' : p.pct_horas >= 70 ? 'var(--blue)' : 'var(--text)'};">${p.horas}/${m.horas}h</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Horas</div>
          <div style="height:3px;background:var(--border);border-radius:2px;margin-top:4px;"><div style="height:100%;width:${p.pct_horas}%;background:var(--blue);border-radius:2px;"></div></div>
        </div>
        <div style="text-align:center;padding:8px;background:var(--bg);border-radius:8px;">
          <div style="font-size:1.1rem;font-weight:700;color:${p.pct_questoes >= 100 ? 'var(--green)' : p.pct_questoes >= 70 ? 'var(--blue)' : 'var(--text)'};">${p.questoes}/${m.questoes}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Questões</div>
          <div style="height:3px;background:var(--border);border-radius:2px;margin-top:4px;"><div style="height:100%;width:${p.pct_questoes}%;background:var(--accent);border-radius:2px;"></div></div>
        </div>
        <div style="text-align:center;padding:8px;background:var(--bg);border-radius:8px;">
          <div style="font-size:1.1rem;font-weight:700;color:${p.pct_flashcards >= 100 ? 'var(--green)' : p.pct_flashcards >= 70 ? 'var(--blue)' : 'var(--text)'};">${p.flashcards}/${m.flashcards}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Flashcards</div>
          <div style="height:3px;background:var(--border);border-radius:2px;margin-top:4px;"><div style="height:100%;width:${p.pct_flashcards}%;background:var(--green);border-radius:2px;"></div></div>
        </div>
      </div>
      ${proj.dias_prova !== null ? `
        <div style="font-size:0.75rem;color:var(--text-sub);display:flex;gap:12px;flex-wrap:wrap;">
          <span>📅 ${proj.dias_prova} dias até a prova</span>
          <span>📊 ${proj.pct_cobertura_atual}% do edital coberto</span>
          ${proj.cobertura_projetada !== null ? `<span>🔮 Projeção: ${proj.cobertura_projetada}% até a prova</span>` : ''}
          ${proj.horas_semana_para_100 ? `<span style="color:var(--yellow);">⚡ Para 100%: ${proj.horas_semana_para_100}h/semana</span>` : ''}
        </div>
      ` : ''}
    `;
  } catch(e) {}
}

// ===== DETECÇÃO DE PLATÔ =====
async function loadPlatoDetection() {
  try {
    const res = await fetch('/api/inteligencia/plato');
    if (!res.ok) return;
    const data = await res.json();
    const card = document.getElementById('plato-card');
    const content = document.getElementById('plato-content');
    if (!card || !content || !data.platos_detectados) return;

    card.style.display = 'block';

    content.innerHTML = `
      <div style="margin-bottom:10px;font-size:0.85rem;color:var(--yellow);font-weight:600;">${data.mensagem}</div>
      ${data.platos.map(p => `
        <div style="background:var(--bg);border-radius:8px;padding:12px;margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <strong style="font-size:0.88rem;">${p.materia}</strong>
            <span style="font-size:0.72rem;color:var(--text-sub);">${p.media_pct}% · estagnado há ${p.semanas_estagnado} semanas</span>
          </div>
          ${p.topicos_fracos.length ? `<div style="font-size:0.72rem;color:var(--red);margin-bottom:8px;">Erros concentrados em: ${p.topicos_fracos.join(', ')}</div>` : ''}
          <div style="display:flex;flex-direction:column;gap:4px;">
            ${p.sugestoes.slice(0, 2).map(s => `
              <div style="display:flex;align-items:flex-start;gap:6px;padding:6px 8px;background:var(--bg-elevated);border-radius:6px;">
                <span style="font-size:0.82rem;">${s.titulo}</span>
              </div>
              <div style="font-size:0.7rem;color:var(--text-sub);padding:0 8px 4px;">${s.descricao}</div>
            `).join('')}
          </div>
        </div>
      `).join('')}
    `;
  } catch(e) {}
}

// Auto-load
loadMetaAdaptativa();
loadPlatoDetection();


// ===== SIMULADO PERIÓDICO AUTOMÁTICO =====
async function loadSimuladoPendente() {
  try {
    const res = await fetch('/api/simulado/pendente');
    if (!res.ok) return;
    const data = await res.json();

    if (!data.pendente) return;

    // Inserir alerta antes das metas
    const metas = document.querySelector('.metas-section');
    if (!metas) return;

    const alertDiv = document.createElement('div');
    alertDiv.className = 'card';
    alertDiv.style.cssText = 'margin-bottom:16px;border-left:4px solid var(--accent);animation:fadeIn 0.3s ease;';
    alertDiv.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;">
        <span style="font-size:2rem;">📝</span>
        <div style="flex:1;">
          <div style="font-weight:700;font-size:0.95rem;color:var(--text);">Hora do Simulado!</div>
          <div style="font-size:0.78rem;color:var(--text-sub);margin-top:2px;">
            ${data.dias_desde_ultimo >= 999 ? 'Você nunca fez um simulado completo.' : `Último há ${data.dias_desde_ultimo} dias${data.ultimo_simulado.nota !== null ? ` (nota: ${data.ultimo_simulado.nota}%)` : ''}.`}
            Faça um para calibrar seu progresso real.
          </div>
        </div>
        <button onclick="gerarSimuladoAutomatico()" style="background:var(--accent);color:#1e1e2e;border:none;border-radius:8px;padding:10px 16px;font-weight:700;font-size:0.82rem;cursor:pointer;white-space:nowrap;">
          ⚡ Gerar Simulado
        </button>
      </div>
    `;
    metas.parentElement.insertBefore(alertDiv, metas);
  } catch(e) {}
}

window.gerarSimuladoAutomatico = async function() {
  try {
    const res = await fetch('/api/simulado/auto-gerar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ total_questoes: 40, tempo_limite_min: 120 })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      _toastDash('Erro: ' + (err.detail || 'Não foi possível gerar'));
      return;
    }
    const data = await res.json();

    // Modal de confirmação com distribuição
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.2s ease;';
    overlay.innerHTML = `
      <div style="background:var(--bg-surface, #313244);border:1px solid var(--border, #45475a);border-radius:16px;padding:24px;max-width:400px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
        <div style="font-size:2rem;text-align:center;margin-bottom:8px;">✅</div>
        <h3 style="color:var(--text);margin:0 0 8px;text-align:center;font-size:1rem;">Simulado Gerado!</h3>
        <p style="color:var(--text-sub);font-size:0.82rem;text-align:center;margin:0 0 16px;">${data.total_questoes} questões · ${data.tempo_limite_min} minutos</p>
        <div style="max-height:200px;overflow-y:auto;margin-bottom:16px;">
          ${data.distribuicao.map(d => `
            <div style="display:flex;justify-content:space-between;padding:6px 8px;font-size:0.78rem;border-bottom:1px solid var(--border);">
              <span style="color:var(--text);">${d.materia}</span>
              <span style="color:var(--text-sub);">${d.questoes}q (${d.peso_pct}%)</span>
            </div>
          `).join('')}
        </div>
        <div style="display:flex;gap:8px;">
          <button onclick="this.closest('div[style*=fixed]').remove()" style="flex:1;padding:10px;background:var(--border);color:var(--text);border:none;border-radius:8px;cursor:pointer;font-weight:600;">Depois</button>
          <button onclick="this.closest('div[style*=fixed]').remove();window.location.href='/questoes.html#simulado-${data.id}'" style="flex:1;padding:10px;background:var(--accent);color:#1e1e2e;border:none;border-radius:8px;cursor:pointer;font-weight:600;">Iniciar Agora</button>
        </div>
      </div>
    `;
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    document.body.appendChild(overlay);
  } catch(e) {
    _toastDash('Erro ao gerar simulado: ' + e.message);
  }
};

loadSimuladoPendente();
