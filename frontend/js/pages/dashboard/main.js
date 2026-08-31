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
import { handleAuthNav } from '../../modules/auth.js';
import { renderCatStartCard } from '../../modules/cat-session.js';
import { renderAnxietyCard } from '../../modules/anxiety-exposure.js';
import { confirmModal, alertModal, toast } from '../../modules/utils.js';

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
      <span class="card-sub">${dash.questoes.percentual}% acerto geral</span>
      ${(() => {
        const hj = dash.questoes.hoje || 0;
        const pct = dash.questoes.percentual_hoje || 0;
        const cor = hj === 0 ? '#9399b2' : (pct >= 70 ? '#a6e3a1' : pct >= 50 ? '#f9e2af' : '#f38ba8');
        const emoji = hj === 0 ? '📝' : (pct >= 70 ? '🎯' : pct >= 50 ? '💪' : '⚠️');
        const label = hj === 0 ? 'Nenhuma questão hoje' : `Hoje: ${hj}q · ${pct}% de acerto`;
        return `<div class="card-today-badge" style="margin-top:8px;display:inline-flex;align-items:center;gap:6px;background:${cor}22;border:1px solid ${cor};color:${cor};border-radius:999px;padding:4px 12px;font-size:0.82rem;font-weight:700;">
          <span>${emoji}</span><span>${label}</span>
        </div>`;
      })()}
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
      <span class="card-sub">${streaks.hoje.questoes_resolvidas || 0}q${dash.questoes.hoje ? ` (${dash.questoes.percentual_hoje || 0}%)` : ''} · ${streaks.hoje.flashcards_revisados || 0}fc</span>
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
  if (!materia) { toast('Preencha a matéria!', 'warning'); return; }
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
  if (!await confirmModal('Confirmar', 'Limpar todo o planejador manual?', { type: 'danger', confirmText: 'Limpar' })) return;
  const items = await fetch('/api/planejador').then(r => r.json());
  for (const it of items) {
    await fetch(`/api/planejador/${it.id}`, { method: 'DELETE' });
  }
  loadPlanejadorSemanal();
}

async function regenerarPlanejador() {
  if (planMode === 'manual') {
    await alertModal('O modo manual não regenera automaticamente. Mude para o modo Auto ou adicione matérias manualmente.', { type: 'info' });
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
    const icons = {revisao:'🧠', estudo:'📚', questoes:'❓', pausa:'☕', 'pre-test':'⚡', consolidacao:'📝', ensinar:'🎓', trilha:'🧭'};
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

          html += `<div class="cal-activity${ativ.tipo === 'trilha' ? ' cal-activity--trilha' : ''}" data-key="${ativKey}" data-materia="${materia}" data-tipo="${ativ.tipo}" data-topico="${(detail || '').replace(/"/g,'&quot;')}" data-tempo="${ativ.tempo_min}" data-date="${dia.data}" data-diasemana="${dia.dia_semana}" data-total="${dia.atividades.length}">`;
          html += `<input type="checkbox" class="cal-check" data-key="${ativKey}" onchange="toggleAtivConcluida(this)" title="Marcar como concluída">`;
          html += `<span class="cal-activity-icon">${icon}</span>`;
          html += `<div class="cal-activity-info">`;
          if (materia) html += `<div class="cal-activity-materia truncated" onclick="this.classList.toggle('truncated');this.classList.toggle('expanded');" title="${materia}${detail ? ' — ' + detail.replace(/"/g,'&quot;') : ''}">${materia}</div>`;
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
            html += `<button class="cal-delete-btn" onclick="removeCalItem(${ativ.id})" aria-label="Remover atividade">❌</button>`;
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
    const res = await fetch('/api/calendario/atividade-concluida', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ data: dataStr, dia_semana: parseInt(el.dataset.diasemana), materia, tipo, tempo_min: parseInt(el.dataset.tempo), total_atividades: total, topico: el.dataset.topico || '' })
    });
    concluidasHoje.add(key);
    // Feedback quando a etapa da trilha é concluída automaticamente
    if (tipo === 'trilha') {
      try {
        const data = await res.json();
        if (data && data.trilha_etapa_concluida) {
          toast('🧭 Etapa da trilha concluída! +25 XP', 'success');
        }
      } catch (_e) { /* silencioso */ }
    }
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
  if (!await confirmModal('Confirmar', 'Deseja regerar o calendário?', { type: 'warning', confirmText: 'Regerar' })) return;
  try {
    await fetch('/api/calendario-personalizado', { method: 'DELETE' });
    calendarMode = 'auto';
    document.querySelectorAll('.cal-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === 'auto'));
    document.getElementById('cal-manual-form').style.display = 'none';
    document.getElementById('cal-hibrido-info').style.display = 'none';
    const actionsEl = document.getElementById('cal-actions');
    if (actionsEl) actionsEl.style.display = 'none';
    await loadCalendario();
  } catch(e) { toast('Erro ao regerar calendário: ' + e.message, 'error'); }
}

async function regenerarInteligente() {
  if (!await confirmModal('Regenerar calendário', '🧠 Regenerar calendário usando análise inteligente?\n\nIsso irá apagar o calendário atual e criar um novo otimizado com base em:\n• Peso da banca\n• Caderno de erros\n• Performance por matéria\n• Dias sem estudar\n• Revisão espaçada\n• Tópicos pendentes', { type: 'warning', confirmText: 'Regenerar' })) return;
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
      await alertModal(`✅ ${data.message}\n\n📊 ${data.stats.total_materias} matérias · ${data.stats.horas_semana}h/semana`, { type: 'success' });
    } else {
      await alertModal('⚠️ ' + (data.message || 'Erro ao gerar calendário inteligente'), { type: 'warning' });
    }
  } catch(e) { toast('Erro ao regenerar inteligente: ' + e.message, 'error'); }
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
  if (!await confirmModal('Confirmar', 'Limpar todo o calendário personalizado?', { type: 'danger', confirmText: 'Limpar' })) return;
  await fetch('/api/calendario-personalizado', { method: 'DELETE' });
  loadCalendario();
}

// Pomodoro
let pomoInterval = null, pomoSeconds = 0, pomoTotal = 0, pomoPaused = false;
function startPomodoro(materia, tempoMin, tipo) {
  // Iniciar timer global (widget flutuante que persiste entre páginas)
  if (window.startGlobalTimer) {
    window.startGlobalTimer(materia || 'Estudo', tempoMin, tipo || 'estudo');
  }

  // Navegar para o conteúdo baseado no tipo
  if (tipo === 'revisao') {
    // Flashcards
    window.location.href = '/#flashcards';
    return;
  } else if (tipo === 'questoes') {
    // Questões da matéria
    window.location.href = `/questoes.html?materia=${encodeURIComponent(materia || '')}`;
    return;
  } else if (tipo === 'estudo' || tipo === 'teoria') {
    // Buscar PDF vinculado à matéria
    fetch(`/api/edital?edital_nome=&cargo=&limit=1&page=1`)
      .then(r => r.json())
      .then(() => {
        // Buscar tópico com PDF vinculado para essa matéria
        fetch(`/api/edital?limit=50`)
          .then(r => r.json())
          .then(data => {
            const items = data.items || data || [];
            const comPdf = items.find(t => t.materia === materia && t.pdf_link);
            if (comPdf) {
              const page = comPdf.pdf_pagina > 0 ? `&page=${comPdf.pdf_pagina}` : '';
              window.location.href = `/viewer.html?file=${encodeURIComponent(comPdf.pdf_link)}${page}`;
            } else {
              // Sem PDF, mostrar aviso
              if (window.toast) {
                window.toast(`📎 Nenhum PDF vinculado a "${materia}". Vincule em Edital → tópico → Vincular PDF.`, 'warning', 5000);
              }
            }
          }).catch(() => {});
      }).catch(() => {});
    return;
  }

  // Fallback: abrir pomodoro overlay (comportamento antigo)
  _startPomoOverlay(materia, tempoMin, tipo);
}

function _startPomoOverlay(materia, tempoMin, tipo) {
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
      const vapidKey = await fetch('/api/push/vapid-key').then(r => r.json()).then(d => d.vapid_public_key).catch(() => null);
      if (vapidKey) {
        // Convert base64url to Uint8Array for applicationServerKey
        const applicationServerKey = _urlBase64ToUint8Array(vapidKey);
        const subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true, applicationServerKey
        });
        const headers = { 'Content-Type': 'application/json' };
        const token = localStorage.getItem('auth_token');
        if (token) headers['Authorization'] = `Bearer ${token}`;
        await fetch('/api/push/subscribe', {
          method: 'POST', headers,
          body: JSON.stringify(subscription.toJSON())
        });
        if (typeof showToast === 'function') showToast('🔔 Notificações ativadas!', 'success');
        // Refresh modal status if open
        const overlay = document.getElementById('notif-prefs-overlay');
        if (overlay) { overlay.remove(); window.showNotificationPrefs(); }
        return;
      } else {
        if (typeof showToast === 'function') showToast('Erro: VAPID key não disponível', 'error');
      }
    } catch(e) {
      console.error('Push subscription error:', e);
      if (typeof showToast === 'function') showToast('Erro ao ativar push: ' + e.message, 'error');
    }
  } else {
    if (typeof showToast === 'function') showToast('Permissão negada pelo navegador', 'warning');
  }
}

// Helper: Convert base64url string to Uint8Array for Push API
function _urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
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
      loadErrorAnalysisPatterns();
      // Render CAT start card
      const catContainer = document.getElementById('cat-session-container');
      if (catContainer) renderCatStartCard(catContainer, { showTitle: false });
      // Render Anxiety Management card
      const anxietyContainer = document.getElementById('anxiety-container');
      if (anxietyContainer) renderAnxietyCard(anxietyContainer);
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
      loadRoiMaterias();
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

// Export for sidebar goPanel access (module scope is not global)
window.loadActivePanel = loadActivePanel;

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
      else toast('Planejador regenerado com inteligência!', 'success');
    } else {
      if (typeof showToast === 'function') showToast(data.message || 'Erro ao regenerar', 'error');
      else await alertModal('⚠️ ' + (data.message || 'Erro ao gerar calendário inteligente'), { type: 'warning' });
    }
  } catch(e) {
    if (typeof showToast === 'function') showToast('Erro: ' + e.message, 'error');
    else toast('Erro ao regenerar inteligente: ' + e.message, 'error');
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
  else toast(`Inicie ${s.tempo_min}min de ${s.materia} (${s.tipo})`, 'info');
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

// Profile menu toggle — usa menu padronizado do auth.js
window.toggleDashProfileMenu = function() {
  handleAuthNav();
};

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
        // Dia de hoje: fundo accent com destaque forte
        const todayBg = dia.is_today ? 'background:rgba(203,166,247,0.15);' : '';
        const border = dia.is_today ? 'border:2px solid var(--accent);box-shadow:0 0 6px rgba(203,166,247,0.4);' : '';
        const labelWeight = dia.is_today ? 'font-weight:800;' : 'font-weight:400;';
        bars += `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;padding:3px 0;border-radius:6px;${todayBg}">
          <div style="width:100%;height:${h}px;background:${color};border-radius:3px;${border}transition:height 0.3s;"></div>
          <span style="font-size:0.6rem;color:${dia.is_today ? 'var(--accent)' : 'var(--text-sub)'};${labelWeight}">${dia.is_today ? '● ' + (dia.nome || '') : dia.nome || ''}</span>
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
  t.style.cssText = 'position:fixed;bottom:96px;right:24px;padding:12px 20px;border-radius:10px;background:var(--bg-surface,#313244);color:var(--text,#cdd6f4);font-size:0.85rem;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,0.3);z-index:99999;animation:fadeIn 0.3s ease;';
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
      toast('📎 Nenhum PDF vinculado. Vincule um PDF ao tópico no Edital.', 'warning');
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
    const manualAtivo = m.manual_ativo;

    content.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;">
        <span style="font-size:0.7rem;padding:2px 8px;border-radius:999px;font-weight:700;background:${manualAtivo ? 'rgba(203,166,247,0.18)' : 'rgba(166,227,161,0.15)'};color:${manualAtivo ? 'var(--accent)' : 'var(--green)'};">
          ${manualAtivo ? '✏️ Meta manual' : '🤖 Meta automática'}
        </span>
        <button onclick="window.showMetaSemanalConfig()" style="background:var(--bg-elevated);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:4px 10px;font-size:0.72rem;cursor:pointer;">⚙️ Configurar</button>
      </div>
      <div style="margin-bottom:10px;font-size:0.85rem;color:var(--text);font-weight:600;">${data.mensagem}</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">
        <div style="text-align:center;padding:8px;background:var(--bg);border-radius:8px;">
          <div style="font-size:1.1rem;font-weight:700;color:${p.pct_horas >= 100 ? 'var(--green)' : p.pct_horas >= 70 ? 'var(--blue)' : 'var(--text)'};">${p.horas}/${m.horas}h</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Horas${m.origem && m.origem.horas === 'manual' ? ' ✏️' : ''}</div>
          <div style="height:3px;background:var(--border);border-radius:2px;margin-top:4px;"><div style="height:100%;width:${p.pct_horas}%;background:var(--blue);border-radius:2px;"></div></div>
        </div>
        <div style="text-align:center;padding:8px;background:var(--bg);border-radius:8px;">
          <div style="font-size:1.1rem;font-weight:700;color:${p.pct_questoes >= 100 ? 'var(--green)' : p.pct_questoes >= 70 ? 'var(--blue)' : 'var(--text)'};">${p.questoes}/${m.questoes}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Questões${m.origem && m.origem.questoes === 'manual' ? ' ✏️' : ''}</div>
          <div style="height:3px;background:var(--border);border-radius:2px;margin-top:4px;"><div style="height:100%;width:${p.pct_questoes}%;background:var(--accent);border-radius:2px;"></div></div>
        </div>
        <div style="text-align:center;padding:8px;background:var(--bg);border-radius:8px;">
          <div style="font-size:1.1rem;font-weight:700;color:${p.pct_flashcards >= 100 ? 'var(--green)' : p.pct_flashcards >= 70 ? 'var(--blue)' : 'var(--text)'};">${p.flashcards}/${m.flashcards}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Flashcards${m.origem && m.origem.flashcards === 'manual' ? ' ✏️' : ''}</div>
          <div style="height:3px;background:var(--border);border-radius:2px;margin-top:4px;"><div style="height:100%;width:${p.pct_flashcards}%;background:var(--green);border-radius:2px;"></div></div>
        </div>
      </div>
      <div style="text-align:center;font-size:0.72rem;color:var(--text-sub);margin-bottom:12px;" title="Meta semanal dividida por 7 dias — os valores acima são da semana toda, não do dia.">
        📆 Meta semanal • equivale a <strong style="color:var(--text);">≈ ${(m.horas / 7).toFixed(1)} h/dia</strong>, ${Math.round(m.questoes / 7)} questões/dia e ${Math.round(m.flashcards / 7)} flashcards/dia
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

// Modal para sobrescrever manualmente a Meta da Semana (ou voltar ao automático)
window.showMetaSemanalConfig = async function() {
  let atual = { horas: 0, questoes: 0, flashcards: 0, manual_ativo: false };
  try {
    const r = await fetch('/api/metas/adaptativa/override');
    if (r.ok) atual = await r.json();
  } catch(e) {}

  const overlay = document.createElement('div');
  overlay.id = 'meta-semanal-config-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.innerHTML = `
    <div style="background:var(--bg-surface);border:1px solid var(--border);border-radius:16px;padding:22px;max-width:400px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
      <h3 style="color:var(--text);margin:0 0 4px;font-size:1rem;">🎯 Meta da Semana (manual)</h3>
      <p style="color:var(--text-sub);font-size:0.78rem;margin:0 0 14px;">Defina valores fixos para sobrescrever a meta automática. Deixe <strong>0</strong> em um campo para mantê-lo automático (derivado do seu desempenho).</p>
      <div style="display:flex;flex-direction:column;gap:10px;">
        <label style="font-size:0.8rem;color:var(--text);">⏱ Horas por semana
          <input type="number" id="ms-horas" min="0" max="168" step="0.5" value="${atual.horas || 0}" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.9rem;">
        </label>
        <label style="font-size:0.8rem;color:var(--text);">❓ Questões por semana
          <input type="number" id="ms-questoes" min="0" max="10000" step="1" value="${atual.questoes || 0}" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.9rem;">
        </label>
        <label style="font-size:0.8rem;color:var(--text);">🧠 Flashcards por semana
          <input type="number" id="ms-flashcards" min="0" max="10000" step="1" value="${atual.flashcards || 0}" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.9rem;">
        </label>
      </div>
      <div style="display:flex;gap:8px;margin-top:16px;">
        <button onclick="window.limparMetaSemanal()" style="flex:1;padding:10px;background:var(--bg-elevated);color:var(--text);border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:0.82rem;">🤖 Voltar ao automático</button>
        <button onclick="window.salvarMetaSemanal()" style="flex:1;padding:10px;background:var(--accent);color:#1e1e2e;border:none;border-radius:8px;cursor:pointer;font-weight:700;font-size:0.82rem;">💾 Salvar</button>
      </div>
    </div>`;
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.appendChild(overlay);
};

window.salvarMetaSemanal = async function() {
  const horas = parseFloat(document.getElementById('ms-horas').value) || 0;
  const questoes = parseInt(document.getElementById('ms-questoes').value) || 0;
  const flashcards = parseInt(document.getElementById('ms-flashcards').value) || 0;
  try {
    const r = await fetch('/api/metas/adaptativa/override', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ horas, questoes, flashcards })
    });
    if (!r.ok) { const e = await r.json().catch(() => ({})); toast(e.detail || 'Erro ao salvar', 'error'); return; }
    document.getElementById('meta-semanal-config-overlay')?.remove();
    toast('Meta da semana atualizada!', 'success');
    loadMetaAdaptativa();
  } catch(e) { toast('Erro ao salvar meta', 'error'); }
};

window.limparMetaSemanal = async function() {
  try {
    const r = await fetch('/api/metas/adaptativa/override', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ horas: 0, questoes: 0, flashcards: 0 })
    });
    if (!r.ok) { toast('Erro ao limpar', 'error'); return; }
    document.getElementById('meta-semanal-config-overlay')?.remove();
    toast('Meta voltou ao modo automático', 'success');
    loadMetaAdaptativa();
  } catch(e) { toast('Erro ao limpar meta', 'error'); }
};

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

// Modal de seleção de disciplinas do simulado. Resolve com a lista escolhida
// (array de materias) ou null se cancelado. Sem matérias → retorna [] (todas).
function _escolherMateriasSimulado(materias) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;animation:fadeIn 0.2s ease;';
    // Aceita tanto lista de strings quanto de objetos {materia, questoes_com_gabarito}.
    const mats = (materias || []).map(m =>
      typeof m === 'string' ? { materia: m, questoes_com_gabarito: null } : m
    ).filter(m => m && m.materia);
    const temMaterias = mats.length > 0;
    overlay.innerHTML = `
      <div style="background:var(--bg-surface,#313244);border:1px solid var(--border,#45475a);border-radius:16px;padding:22px;max-width:420px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.5);max-height:90vh;overflow-y:auto;">
        <h3 style="color:var(--text);margin:0 0 4px;font-size:1rem;">⚡ Gerar Simulado</h3>
        <p style="color:var(--text-sub);font-size:0.8rem;margin:0 0 12px;">Configure o simulado. ${temMaterias ? 'Disciplinas: padrão todas, proporcional ao edital.' : ''}</p>
        <div style="display:flex;gap:8px;margin-bottom:12px;">
          <label style="flex:1;font-size:0.78rem;color:var(--text);">❓ Nº de questões
            <input type="number" id="sim-total-q" min="5" max="200" step="1" value="40" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.9rem;">
          </label>
          <label style="flex:1;font-size:0.78rem;color:var(--text);">⏱ Tempo (min)
            <input type="number" id="sim-tempo" min="5" max="600" step="5" value="120" style="width:100%;margin-top:4px;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.9rem;">
          </label>
        </div>
        ${temMaterias ? `
        <div style="display:flex;gap:8px;margin-bottom:8px;">
          <button id="sim-todas" style="flex:1;background:var(--bg,#1e1e2e);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:6px;font-size:0.75rem;cursor:pointer;">Todas</button>
          <button id="sim-nenhuma" style="flex:1;background:var(--bg,#1e1e2e);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:6px;font-size:0.75rem;cursor:pointer;">Limpar</button>
        </div>
        <div id="sim-materias" style="max-height:220px;overflow-y:auto;margin-bottom:16px;display:flex;flex-direction:column;gap:4px;">
          ${mats.map((m) => {
            const nome = m.materia;
            const n = m.questoes_com_gabarito;
            const label = (n === null || n === undefined) ? nome : `${nome} (${n})`;
            return `
            <label style="display:flex;align-items:center;gap:8px;padding:8px 10px;background:var(--bg,#1e1e2e);border-radius:8px;cursor:pointer;font-size:0.82rem;color:var(--text);">
              <input type="checkbox" class="sim-mat-chk" value="${nome.replace(/"/g,'&quot;')}" checked style="width:16px;height:16px;">
              <span>${label}</span>
            </label>`;
          }).join('')}
        </div>` : '<div style="margin-bottom:8px;"></div>'}
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button id="sim-cancel" style="background:var(--bg,#1e1e2e);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:8px 16px;font-size:0.82rem;cursor:pointer;">Cancelar</button>
          <button id="sim-ok" style="background:var(--accent,#cba6f7);color:#1e1e2e;border:none;border-radius:8px;padding:8px 16px;font-weight:700;font-size:0.82rem;cursor:pointer;">Gerar</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const lerConfig = () => {
      let totalQ = parseInt(overlay.querySelector('#sim-total-q').value) || 40;
      let tempo = parseInt(overlay.querySelector('#sim-tempo').value) || 120;
      totalQ = Math.min(200, Math.max(5, totalQ));
      tempo = Math.min(600, Math.max(5, tempo));
      return { total_questoes: totalQ, tempo_limite_min: tempo };
    };
    const chks = () => Array.from(overlay.querySelectorAll('.sim-mat-chk'));
    if (temMaterias) {
      overlay.querySelector('#sim-todas').onclick = () => chks().forEach(c => { c.checked = true; });
      overlay.querySelector('#sim-nenhuma').onclick = () => chks().forEach(c => { c.checked = false; });
    }
    const close = (val) => { overlay.remove(); resolve(val); };
    overlay.querySelector('#sim-cancel').onclick = () => close(null);
    overlay.onclick = (e) => { if (e.target === overlay) close(null); };
    overlay.querySelector('#sim-ok').onclick = () => {
      const cfg = lerConfig();
      let sel = [];
      if (temMaterias) {
        sel = chks().filter(c => c.checked).map(c => c.value);
        if (sel.length === 0) { _toastDash('Selecione pelo menos uma disciplina.'); return; }
      }
      close({ materias: sel, ...cfg });
    };
  });
}

window.gerarSimuladoAutomatico = async function() {
  // Primeiro deixa o usuário escolher as disciplinas (uma, várias ou todas).
  // Só aparecem matérias ELEGÍVEIS: com no mínimo 3 questões com gabarito.
  let materiasElegiveis = [];  // [{materia, questoes_com_gabarito}]
  try {
    const resp = await fetch('/api/simulado/materias-elegiveis').then(r => r.json());
    materiasElegiveis = (resp.materias || []).filter(m => m && m.materia);
  } catch (e) { /* segue sem seletor se falhar */ }
  const materiasCiclo = materiasElegiveis.map(m => m.materia);

  if (materiasCiclo.length === 0) {
    await alertModal(
      'Nenhuma disciplina do seu ciclo tem ao menos 3 questões com gabarito. Importe questões com resposta correta para gerar o simulado.',
      { title: 'Simulado do dia', type: 'warning' }
    );
    return;
  }

  const escolha = await _escolherMateriasSimulado(materiasElegiveis);
  if (escolha === null) return; // cancelou
  const materiasEscolhidas = escolha.materias || [];

  try {
    const body = {
      total_questoes: escolha.total_questoes || 40,
      tempo_limite_min: escolha.tempo_limite_min || 120,
    };
    // Se selecionou um subconjunto (não todas), envia o filtro
    if (materiasEscolhidas.length && materiasEscolhidas.length < materiasCiclo.length) {
      body.materias = materiasEscolhidas;
    }
    const res = await fetch('/api/simulado/auto-gerar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      await alertModal(err.detail || 'Não foi possível gerar o simulado.', {
        title: 'Simulado não gerado',
        type: 'warning',
      });
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
    await alertModal('Erro ao gerar simulado: ' + e.message, {
      title: 'Erro',
      type: 'error',
    });
  }
};

loadSimuladoPendente();


// ============================================================
// STUDY INTELLIGENCE WIDGETS (Sleep Consolidation + Milestones + Intentions)
// ============================================================

async function loadStudyIntelligenceWidgets() {
  const box = document.getElementById('study-intelligence-box');
  if (!box) return;

  let html = '';

  // 1. Sleep Consolidation (se no horário certo)
  try {
    const sc = await fetch('/api/study-intelligence/sleep-consolidation').then(r => r.ok ? r.json() : null);
    if (sc && sc.modo !== 'fora_janela' && (sc.total_flashcards > 0 || sc.total_questoes > 0)) {
      html += `
        <div style="background:var(--bg-surface);border-radius:var(--radius-lg);padding:16px;margin-bottom:12px;border-left:4px solid ${sc.modo === 'noturno' ? 'var(--accent)' : 'var(--yellow)'};">
          <div style="font-size:0.88rem;font-weight:700;color:var(--text);margin-bottom:6px;">${sc.modo === 'noturno' ? '🌙' : '☀️'} ${sc.modo === 'noturno' ? 'Revisão Pré-Sono' : 'Revisão Matinal'}</div>
          <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:10px;">${sc.mensagem}</div>
          ${sc.flashcards.length > 0 ? `<div style="margin-bottom:8px;">
            <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:4px;">🧠 ${sc.total_flashcards} flashcards para consolidar:</div>
            ${sc.flashcards.slice(0, 3).map(f => `<div style="font-size:0.75rem;color:var(--text);padding:4px 8px;background:var(--bg);border-radius:6px;margin-bottom:3px;">${f.pergunta?.substring(0, 60) || ''}${(f.pergunta?.length || 0) > 60 ? '...' : ''}</div>`).join('')}
            ${sc.total_flashcards > 3 ? `<div style="font-size:0.7rem;color:var(--text-sub);">+${sc.total_flashcards - 3} mais</div>` : ''}
          </div>` : ''}
          ${sc.questoes.length > 0 ? `<div style="font-size:0.72rem;color:var(--text-sub);">❓ ${sc.total_questoes} questões erradas para revisar</div>` : ''}
          <button onclick="window.location.href='/#flashcards'" style="margin-top:8px;background:var(--accent);color:#1e1e2e;border:none;border-radius:6px;padding:6px 14px;font-size:0.78rem;font-weight:600;cursor:pointer;">Revisar Agora</button>
          ${sc.dica ? `<div style="font-size:0.68rem;color:var(--text-sub);margin-top:6px;font-style:italic;">${sc.dica}</div>` : ''}
        </div>`;
    }
  } catch(e) {}

  // 2. Milestones (próximos marcos)
  try {
    const ms = await fetch('/api/study-intelligence/milestones').then(r => r.ok ? r.json() : null);
    if (ms && ms.proximos_marcos && ms.proximos_marcos.length > 0) {
      html += `
        <div style="background:var(--bg-surface);border-radius:var(--radius-lg);padding:16px;margin-bottom:12px;">
          <div style="font-size:0.88rem;font-weight:700;color:var(--text);margin-bottom:8px;">🏆 Próximos Marcos</div>
          ${ms.proximos_marcos.slice(0, 3).map(m => `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
              <span style="font-size:1rem;">${m.icone}</span>
              <div style="flex:1;">
                <div style="font-size:0.78rem;color:var(--text);">${m.titulo}</div>
                <div style="height:4px;background:var(--border);border-radius:2px;margin-top:3px;overflow:hidden;">
                  <div style="height:100%;width:${m.pct}%;background:${m.pct >= 80 ? 'var(--green)' : m.pct >= 50 ? 'var(--yellow)' : 'var(--blue)'};border-radius:2px;transition:width 0.3s;"></div>
                </div>
              </div>
              <span style="font-size:0.7rem;color:var(--text-sub);min-width:35px;text-align:right;">${m.pct}%</span>
            </div>`).join('')}
          ${ms.mensagem_motivacional ? `<div style="font-size:0.72rem;color:var(--accent);margin-top:6px;">${ms.mensagem_motivacional}</div>` : ''}
        </div>`;
    }
  } catch(e) {}

  // 3. Implementation Intentions (compromissos de hoje)
  try {
    const intentions = await fetch('/api/study-intelligence/intention/hoje').then(r => r.ok ? r.json() : null);
    if (intentions) {
      html += `
        <div style="background:var(--bg-surface);border-radius:var(--radius-lg);padding:16px;margin-bottom:12px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <span style="font-size:0.88rem;font-weight:700;color:var(--text);">📋 Compromissos Hoje</span>
            <span style="font-size:0.72rem;color:var(--text-sub);">${intentions.concluidas}/${intentions.total} feitos</span>
          </div>
          ${intentions.total === 0 ? `
            <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:8px;">Nenhum compromisso registrado. Declare uma intenção para +200% execução!</div>
            <button onclick="window._showIntentionModal()" style="background:var(--accent);color:#1e1e2e;border:none;border-radius:6px;padding:6px 14px;font-size:0.78rem;font-weight:600;cursor:pointer;">+ Nova Intenção</button>
          ` : `
            ${intentions.intencoes.slice(0, 3).map(i => `
              <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);">
                <span style="font-size:0.9rem;">${i.concluido ? '✅' : '⬜'}</span>
                <div style="flex:1;font-size:0.78rem;color:var(--text);">${i.materia} · ${i.duracao_min}min · ${i.atividade}</div>
              </div>`).join('')}
            <button onclick="window._showIntentionModal()" style="margin-top:8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 14px;font-size:0.75rem;cursor:pointer;">+ Adicionar</button>
          `}
        </div>`;
    }
  } catch(e) {}

  if (html) box.innerHTML = html;
}

// Modal rápido para criar intenção
window._showIntentionModal = function() {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;';
  overlay.innerHTML = `
    <div style="background:var(--bg-surface);border-radius:var(--radius-lg);padding:24px;max-width:360px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
      <h3 style="color:var(--text);margin:0 0 12px;font-size:1rem;">📋 Nova Intenção de Estudo</h3>
      <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:12px;">Declare O QUE vai estudar para +200% chance de executar</div>
      <select id="intention-materia" style="width:100%;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--text);margin-bottom:8px;font-size:0.85rem;">
        <option value="">Escolha a matéria...</option>
      </select>
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <input id="intention-duracao" type="number" value="30" min="10" max="180" style="flex:1;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.85rem;">
        <span style="align-self:center;font-size:0.8rem;color:var(--text-sub);">min</span>
      </div>
      <select id="intention-atividade" style="width:100%;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--text);margin-bottom:12px;font-size:0.85rem;">
        <option value="teoria">📖 Estudar teoria</option>
        <option value="questoes">❓ Resolver questões</option>
        <option value="revisao">🔄 Revisão (flashcards)</option>
        <option value="simulado">📝 Simulado</option>
      </select>
      <div style="display:flex;gap:8px;">
        <button onclick="this.closest('div[style*=fixed]').remove()" style="flex:1;padding:10px;background:var(--border);color:var(--text);border:none;border-radius:8px;cursor:pointer;">Cancelar</button>
        <button onclick="window._saveIntention()" style="flex:1;padding:10px;background:var(--accent);color:#1e1e2e;border:none;border-radius:8px;cursor:pointer;font-weight:600;">Começar! 🚀</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  // Carregar matérias
  fetch('/api/edital/materias-disponiveis').then(r => r.json()).then(mats => {
    const sel = document.getElementById('intention-materia');
    mats.forEach(m => { const opt = document.createElement('option'); opt.value = m; opt.textContent = m; sel.appendChild(opt); });
  }).catch(() => {});
};

window._saveIntention = async function() {
  const materia = document.getElementById('intention-materia').value;
  const duracao = parseInt(document.getElementById('intention-duracao').value) || 30;
  const atividade = document.getElementById('intention-atividade').value;
  if (!materia) { _toastDash('Escolha uma matéria'); return; }
  try {
    await fetch('/api/study-intelligence/intention', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ materia, duracao_min: duracao, atividade })
    });
    document.querySelector('div[style*="position:fixed"][style*="inset:0"]')?.remove();
    _toastDash('✅ Compromisso registrado! Agora COMECE.');
    loadStudyIntelligenceWidgets();
  } catch(e) { _toastDash('Erro ao salvar intenção'); }
};

// Load on dashboard init
setTimeout(loadStudyIntelligenceWidgets, 500);


// ============================================================
// STUDY INTELLIGENCE — Técnicas Adicionais (Alertas Proativos)
// ============================================================

async function loadSiTechniquesAlerts() {
  const box = document.getElementById('si-techniques-alerts');
  if (!box) return;

  let html = '';

  // 1. Burnout Detection
  try {
    const burnout = await fetch('/api/study-intelligence/burnout').then(r => r.ok ? r.json() : null);
    if (burnout && burnout.risk) {
      const borderColor = burnout.risk === 'alto' ? 'var(--red, #f38ba8)' : 'var(--yellow, #f9e2af)';
      const icon = burnout.risk === 'alto' ? '🛑' : '⚠️';
      html += `
        <div style="background:var(--bg-surface);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid ${borderColor};">
          <div style="font-size:0.85rem;font-weight:700;color:var(--text);">${icon} Alerta de Burnout (${burnout.risk})</div>
          <div style="font-size:0.78rem;color:var(--text-sub);margin-top:4px;">${burnout.sugestao}</div>
          <div style="font-size:0.72rem;color:var(--text-sub);margin-top:6px;">📊 Média 7 dias: ${burnout.media_horas_7d}h/dia | Meta: ${burnout.meta_horas}h | Overwork: ${burnout.dias_overwork} dias</div>
        </div>`;
    }
  } catch(e) {}

  // 2. Overlearning Detection
  try {
    const overlearn = await fetch('/api/study-intelligence/overlearning').then(r => r.ok ? r.json() : null);
    if (overlearn && overlearn.itens_overlearned && overlearn.itens_overlearned.length > 0) {
      html += `
        <div style="background:var(--bg-surface);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--blue, #89b4fa);">
          <div style="font-size:0.85rem;font-weight:700;color:var(--text);">📚 Overlearning Detectado</div>
          <div style="font-size:0.78rem;color:var(--text-sub);margin-top:4px;">${overlearn.itens_overlearned.length} tópico(s) com stability > 60 dias sendo revisados. Seu tempo é melhor investido em tópicos novos!</div>
          <div style="font-size:0.72rem;color:var(--text-sub);margin-top:6px;">${overlearn.itens_overlearned.slice(0, 3).map(i => `• ${i.materia}: ${i.topico}`).join('<br>')}</div>
        </div>`;
    }
  } catch(e) {}

  // 3. Calibration (metacognição)
  try {
    const calib = await fetch('/api/study-intelligence/calibration').then(r => r.ok ? r.json() : null);
    if (calib && calib.status && calib.status !== 'calibrado') {
      const icon = calib.status === 'overconfident' ? '⚠️' : '💡';
      const msg = calib.status === 'overconfident'
        ? 'Você tende a superestimar seu domínio. Faça pré-testes antes de avançar para novos tópicos.'
        : 'Você subestima o que sabe. Tente resolver questões difíceis — pode se surpreender!';
      html += `
        <div style="background:var(--bg-surface);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--accent, #cba6f7);">
          <div style="font-size:0.85rem;font-weight:700;color:var(--text);">${icon} Calibração: ${calib.status}</div>
          <div style="font-size:0.78rem;color:var(--text-sub);margin-top:4px;">${msg}</div>
          ${calib.gap_medio ? `<div style="font-size:0.72rem;color:var(--text-sub);margin-top:4px;">Gap médio: ${calib.gap_medio > 0 ? '+' : ''}${calib.gap_medio.toFixed(1)} (confiança vs resultado)</div>` : ''}
        </div>`;
    }
  } catch(e) {}

  // 4. Adaptive Break Suggestion
  try {
    const brk = await fetch('/api/study-intelligence/adaptive-break').then(r => r.ok ? r.json() : null);
    if (brk && brk.sugerir_pausa) {
      html += `
        <div style="background:var(--bg-surface);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--green, #a6e3a1);">
          <div style="font-size:0.85rem;font-weight:700;color:var(--text);">☕ Pausa Recomendada</div>
          <div style="font-size:0.78rem;color:var(--text-sub);margin-top:4px;">${brk.mensagem || 'Ritmo ultradian sugere pausa agora. Descanse 15min para otimizar retenção.'}</div>
          <div style="font-size:0.72rem;color:var(--text-sub);margin-top:4px;">⏱ Próxima pausa ideal em: ${brk.minutos_ate_pausa || '?'}min</div>
        </div>`;
    }
  } catch(e) {}

  // 5. Successive Relearning (tópicos para reaprender)
  try {
    const sr = await fetch('/api/study-intelligence/successive-relearning').then(r => r.ok ? r.json() : null);
    if (sr && sr.topicos_para_reaprender && sr.topicos_para_reaprender.length > 0) {
      html += `
        <div style="background:var(--bg-surface);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--yellow, #f9e2af);">
          <div style="font-size:0.85rem;font-weight:700;color:var(--text);">🔁 Reaprendizado Necessário</div>
          <div style="font-size:0.78rem;color:var(--text-sub);margin-top:4px;">${sr.topicos_para_reaprender.length} tópico(s) com retenção em queda que precisam de revisão ativa:</div>
          <div style="font-size:0.72rem;color:var(--text-sub);margin-top:6px;">
            ${sr.topicos_para_reaprender.slice(0, 4).map(t => `• ${t.materia}: ${t.topico} (${t.retencao_pct || '?'}%)`).join('<br>')}
          </div>
        </div>`;
    }
  } catch(e) {}

  // 6. Banca Profile (se disponível)
  try {
    const banca = await fetch('/api/study-intelligence/banca-profile').then(r => r.ok ? r.json() : null);
    if (banca && banca.banca && banca.estilo) {
      html += `
        <div style="background:var(--bg-surface);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--accent, #cba6f7);">
          <div style="font-size:0.85rem;font-weight:700;color:var(--text);">🎯 Perfil da Banca: ${banca.banca}</div>
          <div style="font-size:0.78rem;color:var(--text-sub);margin-top:4px;">${banca.estilo}</div>
          ${banca.dicas ? `<div style="font-size:0.72rem;color:var(--text-sub);margin-top:6px;">${banca.dicas.slice(0, 2).map(d => `💡 ${d}`).join('<br>')}</div>` : ''}
        </div>`;
    }
  } catch(e) {}

  if (html) {
    box.innerHTML = html;
  }
}

// Load after main widgets (give time for session to register)
setTimeout(loadSiTechniquesAlerts, 1200);


// ============================================================
// PUSH NOTIFICATIONS — Preferences UI + Auto-check
// ============================================================

// Auto-check triggers on page load (inline alerts)
(async function autoCheckNotifications() {
  try {
    const data = await fetch('/api/push/auto-check').then(r => r.ok ? r.json() : null);
    if (!data || !data.alertas || data.alertas.length === 0) return;

    // Mostrar alertas inline no topo do dashboard
    const target = document.querySelector('.panel-visao .charts') || document.querySelector('.panel-visao');
    if (!target) return;

    const alertsHtml = data.alertas.map(a => `
      <a href="${a.acao}" style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--bg-surface);border-radius:10px;text-decoration:none;border-left:3px solid var(--accent);transition:background 0.2s;" onmouseover="this.style.background='var(--bg-elevated)'" onmouseout="this.style.background='var(--bg-surface)'">
        <span style="font-size:1.2rem;">${a.icone}</span>
        <span style="font-size:0.82rem;color:var(--text);flex:1;">${a.msg}</span>
        <span style="font-size:0.75rem;color:var(--accent);">→</span>
      </a>
    `).join('');

    const container = document.createElement('div');
    container.id = 'push-alerts-inline';
    container.style.cssText = 'display:flex;flex-direction:column;gap:6px;margin-bottom:16px;';
    container.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
        <span style="font-size:0.82rem;font-weight:700;color:var(--text);">🔔 Alertas</span>
        <button onclick="document.getElementById('push-alerts-inline').remove()" style="background:none;border:none;color:var(--text-sub);font-size:0.75rem;cursor:pointer;">Fechar</button>
      </div>
      ${alertsHtml}
    `;
    target.insertBefore(container, target.firstChild);
  } catch(e) {}
})();

// Notification Preferences Modal
window.showNotificationPrefs = async function() {
  const _headers = () => {
    const h = { 'Content-Type': 'application/json' };
    const token = localStorage.getItem('auth_token');
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
  };

  try {
    const prefs = await fetch('/api/push/preferences', { headers: _headers() }).then(r => r.json());
    const status = await fetch('/api/push/status', { headers: _headers() }).then(r => r.json()).catch(() => ({ subscribed: false }));

    const overlay = document.createElement('div');
    overlay.id = 'notif-prefs-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;';
    overlay.innerHTML = `
      <div style="background:var(--bg-elevated, #45475a);border-radius:16px;padding:24px;max-width:400px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
          <h3 style="color:var(--text);margin:0;font-size:1.05rem;">🔔 Preferências de Notificação</h3>
          <button onclick="document.getElementById('notif-prefs-overlay').remove()" style="background:none;border:none;color:var(--text-sub);font-size:1.3rem;cursor:pointer;">✕</button>
        </div>

        <div style="margin-bottom:16px;padding:10px;background:var(--bg);border-radius:8px;font-size:0.78rem;color:var(--text-sub);">
          Status: ${status.subscribed ? '✅ Push ativo' : '❌ Push inativo'}.
          ${!status.subscribed ? '<button onclick="window.requestPushPermission()" style="margin-left:8px;background:var(--accent);color:#1e1e2e;border:none;border-radius:6px;padding:4px 10px;font-size:0.75rem;cursor:pointer;">Ativar</button>' : ''}
        </div>

        <div style="display:flex;flex-direction:column;gap:12px;">
          <label style="display:flex;align-items:center;gap:10px;cursor:pointer;">
            <input type="checkbox" id="pref-streak" ${prefs.streak_reminders ? 'checked' : ''} style="width:18px;height:18px;accent-color:var(--accent);">
            <div><div style="font-size:0.85rem;color:var(--text);">🔥 Lembretes de Streak</div><div style="font-size:0.72rem;color:var(--text-sub);">Avisa quando streak está em risco</div></div>
          </label>
          <label style="display:flex;align-items:center;gap:10px;cursor:pointer;">
            <input type="checkbox" id="pref-flashcard" ${prefs.flashcard_reminders ? 'checked' : ''} style="width:18px;height:18px;accent-color:var(--accent);">
            <div><div style="font-size:0.85rem;color:var(--text);">🧠 Flashcards Pendentes</div><div style="font-size:0.72rem;color:var(--text-sub);">Avisa quando há >10 flashcards atrasados</div></div>
          </label>
          <label style="display:flex;align-items:center;gap:10px;cursor:pointer;">
            <input type="checkbox" id="pref-exam" ${prefs.exam_reminders ? 'checked' : ''} style="width:18px;height:18px;accent-color:var(--accent);">
            <div><div style="font-size:0.85rem;color:var(--text);">📅 Provas Próximas</div><div style="font-size:0.72rem;color:var(--text-sub);">Countdown quando prova está em 30 dias</div></div>
          </label>
          <label style="display:flex;align-items:center;gap:10px;cursor:pointer;">
            <input type="checkbox" id="pref-challenge" ${prefs.challenge_reminders ? 'checked' : ''} style="width:18px;height:18px;accent-color:var(--accent);">
            <div><div style="font-size:0.85rem;color:var(--text);">🎯 Desafios Expirando</div><div style="font-size:0.72rem;color:var(--text-sub);">Avisa quando desafio expira em <1 dia</div></div>
          </label>

          <div style="border-top:1px solid var(--border);margin-top:4px;padding-top:12px;">
            <div style="font-size:0.82rem;font-weight:600;color:var(--text);margin-bottom:8px;">🌙 Horário Silencioso</div>
            <div style="display:flex;align-items:center;gap:8px;">
              <input type="number" id="pref-quiet-start" value="${prefs.quiet_hours_start}" min="0" max="23" style="width:50px;padding:6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.85rem;text-align:center;">
              <span style="color:var(--text-sub);font-size:0.8rem;">h até</span>
              <input type="number" id="pref-quiet-end" value="${prefs.quiet_hours_end}" min="0" max="23" style="width:50px;padding:6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:0.85rem;text-align:center;">
              <span style="color:var(--text-sub);font-size:0.8rem;">h</span>
            </div>
          </div>
        </div>

        <button onclick="window._saveNotifPrefs()" style="width:100%;margin-top:16px;padding:12px;background:var(--accent);color:#1e1e2e;border:none;border-radius:10px;font-weight:700;font-size:0.9rem;cursor:pointer;">
          Salvar Preferências
        </button>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  } catch(e) {
    if (typeof _toastDash === 'function') _toastDash('Erro ao carregar preferências');
  }
};

window._saveNotifPrefs = async function() {
  const body = {
    streak_reminders: document.getElementById('pref-streak').checked,
    flashcard_reminders: document.getElementById('pref-flashcard').checked,
    exam_reminders: document.getElementById('pref-exam').checked,
    challenge_reminders: document.getElementById('pref-challenge').checked,
    quiet_hours_start: parseInt(document.getElementById('pref-quiet-start').value) || 22,
    quiet_hours_end: parseInt(document.getElementById('pref-quiet-end').value) || 7,
  };

  const headers = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem('auth_token');
  if (token) headers['Authorization'] = `Bearer ${token}`;

  try {
    const res = await fetch('/api/push/preferences', {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    document.getElementById('notif-prefs-overlay')?.remove();
    if (typeof _toastDash === 'function') _toastDash('✅ Preferências salvas!');
  } catch(e) {
    if (typeof _toastDash === 'function') _toastDash('Erro ao salvar: ' + e.message);
  }
};


// ============================================================
// ROI POR MATÉRIA — Retorno sobre investimento de tempo
// ============================================================

async function loadRoiMaterias() {
  const box = document.getElementById('roi-materias-box');
  if (!box) return;

  try {
    const data = await fetch('/api/analytics/roi-materias').then(r => r.json());
    if (!data.materias || data.materias.length === 0) {
      box.innerHTML = '<div style="font-size:0.82rem;color:var(--text-sub);padding:12px;">Sem dados suficientes. Resolva questões de diferentes matérias para calcular o ROI.</div>';
      return;
    }

    const maxRoi = Math.max(...data.materias.map(m => m.roi), 1);

    let html = `
      <div style="display:flex;gap:8px;margin-bottom:12px;font-size:0.72rem;">
        <span style="color:var(--green);">● Alto ROI (${data.resumo.alto_roi})</span>
        <span style="color:var(--yellow);">● Médio (${data.resumo.medio})</span>
        <span style="color:var(--text-sub);">● Baixo (${data.resumo.baixo})</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
    `;

    data.materias.slice(0, 10).forEach((m, i) => {
      const barWidth = Math.max(5, Math.round((m.roi / maxRoi) * 100));
      const color = m.classificacao === 'Alto ROI' ? 'var(--green, #a6e3a1)' :
                    m.classificacao === 'Médio' ? 'var(--yellow, #f9e2af)' : 'var(--text-sub, #6c7086)';
      const badge = m.classificacao === 'Alto ROI' ? '🔥' : m.classificacao === 'Médio' ? '' : '📉';

      html += `
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:0.72rem;color:var(--text-sub);min-width:18px;text-align:right;">${i + 1}.</span>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
              <span style="font-size:0.78rem;color:var(--text);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${badge} ${m.materia}</span>
              <span style="font-size:0.68rem;color:var(--text-sub);white-space:nowrap;margin-left:8px;">${m.horas_investidas}h | ${m.pct_atual}% acerto</span>
            </div>
            <div style="height:6px;background:var(--border, #45475a);border-radius:3px;overflow:hidden;">
              <div style="height:100%;width:${barWidth}%;background:${color};border-radius:3px;transition:width 0.4s;"></div>
            </div>
          </div>
          <span style="font-size:0.72rem;font-weight:700;color:${color};min-width:40px;text-align:right;">${m.roi.toFixed(1)}</span>
        </div>
      `;
    });

    html += '</div>';

    // Recomendação
    const topMat = data.materias[0];
    if (topMat && topMat.classificacao === 'Alto ROI') {
      html += `
        <div style="margin-top:12px;padding:10px;background:rgba(166,227,161,0.08);border:1px solid var(--green);border-radius:8px;font-size:0.78rem;color:var(--text);">
          💡 <strong>Recomendação:</strong> Invista mais tempo em <strong>${topMat.materia}</strong> — peso ${topMat.peso_banca}% na banca, acerto atual ${topMat.pct_atual}%, com apenas ${topMat.horas_investidas}h investidas. Alto potencial de ganho!
        </div>
      `;
    }

    box.innerHTML = html;
  } catch(e) {
    box.innerHTML = '<div style="font-size:0.78rem;color:var(--text-sub);">Erro ao carregar ROI</div>';
  }
}


// ============================================================
// ERROR ANALYSIS PATTERNS — Widget de Análise de Padrões de Erro
// ============================================================

async function loadErrorAnalysisPatterns() {
  const container = document.getElementById('si-techniques-alerts');
  if (!container) return;

  const PATTERN_COLORS = {
    desatencao: '#f38ba8',
    conceito: '#89b4fa',
    interpretacao: '#f9e2af',
    pegadinha: '#cba6f7',
    'exceção': '#94e2d5'
  };

  const PATTERN_ICONS = {
    desatencao: '⚡',
    conceito: '📖',
    interpretacao: '🔍',
    pegadinha: '🪤',
    'exceção': '⚠️'
  };

  try {
    const res = await fetch('/api/study-intelligence/error-patterns');
    if (!res.ok) return;
    const data = await res.json();

    if (!data || !data.distribuicao || data.total_erros === 0) return;

    // Build horizontal bars for each pattern
    const maxPct = Math.max(...Object.values(data.distribuicao).map(d => d.pct), 1);

    let barsHtml = '';
    for (const [padrao, info] of Object.entries(data.distribuicao)) {
      const color = PATTERN_COLORS[padrao] || 'var(--text-sub)';
      const icon = PATTERN_ICONS[padrao] || '●';
      const barWidth = Math.max(5, Math.round((info.pct / maxPct) * 100));
      const isDominant = padrao === data.padrao_dominante;
      const descricao = data.detalhes_padroes?.[padrao]?.descricao || '';

      barsHtml += `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;${isDominant ? 'background:rgba(255,255,255,0.03);border-radius:8px;padding:6px 8px;border:1px solid ' + color + ';' : ''}">
          <span style="font-size:1rem;min-width:20px;text-align:center;" title="${descricao}">${icon}</span>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
              <span style="font-size:0.78rem;color:var(--text);font-weight:${isDominant ? '700' : '500'};text-transform:capitalize;">
                ${padrao}${isDominant ? ' <span style="font-size:0.65rem;color:' + color + ';margin-left:4px;">★ dominante</span>' : ''}
              </span>
              <span style="font-size:0.7rem;color:var(--text-sub);">${info.count} erros (${info.pct.toFixed(1)}%)</span>
            </div>
            <div style="height:8px;background:var(--bg-elevated, #45475a);border-radius:4px;overflow:hidden;">
              <div style="height:100%;width:${barWidth}%;background:${color};border-radius:4px;transition:width 0.4s ease;"></div>
            </div>
            ${descricao ? `<div style="font-size:0.68rem;color:var(--text-sub);margin-top:2px;">${descricao}</div>` : ''}
          </div>
        </div>`;
    }

    // Recomendações
    let recsHtml = '';
    if (data.recomendacoes && data.recomendacoes.length > 0) {
      recsHtml = `
        <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border, #45475a);">
          <div style="font-size:0.78rem;font-weight:600;color:var(--text);margin-bottom:6px;">💡 Recomendações</div>
          ${data.recomendacoes.map(r => `
            <div style="display:flex;align-items:flex-start;gap:6px;margin-bottom:5px;">
              <span style="color:var(--accent);font-size:0.75rem;margin-top:1px;">→</span>
              <span style="font-size:0.75rem;color:var(--text-sub);line-height:1.4;">${r}</span>
            </div>`).join('')}
        </div>`;
    }

    // Matérias mais afetadas (top 3)
    let materiasHtml = '';
    if (data.por_materia && Object.keys(data.por_materia).length > 0) {
      const materiasSorted = Object.entries(data.por_materia)
        .map(([materia, padroes]) => ({
          materia,
          total: Object.values(padroes).reduce((a, b) => a + b, 0),
          padroes
        }))
        .sort((a, b) => b.total - a.total)
        .slice(0, 3);

      if (materiasSorted.length > 0) {
        materiasHtml = `
          <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border, #45475a);">
            <div style="font-size:0.78rem;font-weight:600;color:var(--text);margin-bottom:6px;">📚 Matérias Mais Afetadas</div>
            ${materiasSorted.map(m => {
              const topPadrao = Object.entries(m.padroes).sort((a, b) => b[1] - a[1])[0];
              const topColor = PATTERN_COLORS[topPadrao[0]] || 'var(--text-sub)';
              return `
                <div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border, #45475a);">
                  <span style="width:6px;height:6px;border-radius:50%;background:${topColor};flex-shrink:0;"></span>
                  <span style="flex:1;font-size:0.75rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${m.materia}</span>
                  <span style="font-size:0.68rem;color:var(--text-sub);">${m.total} erros</span>
                  <span style="font-size:0.65rem;color:${topColor};text-transform:capitalize;">${topPadrao[0]}</span>
                </div>`;
            }).join('')}
          </div>`;
      }
    }

    // Mount full widget HTML
    const widgetHtml = `
      <div style="background:var(--bg-surface);border-radius:10px;padding:16px;margin-bottom:12px;border-left:4px solid ${PATTERN_COLORS[data.padrao_dominante] || 'var(--accent)'};">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <div style="font-size:0.88rem;font-weight:700;color:var(--text);">🔍 Análise de Padrões de Erro</div>
          <span style="font-size:0.7rem;color:var(--text-sub);">${data.total_erros} erros · ${data.periodo_dias} dias</span>
        </div>
        ${barsHtml}
        ${recsHtml}
        ${materiasHtml}
      </div>
    `;

    // Append (não substituir, pois outros widgets podem já estar no container)
    const wrapper = document.createElement('div');
    wrapper.id = 'error-analysis-widget';
    wrapper.innerHTML = widgetHtml;

    // Remove old widget if re-loaded
    const oldWidget = document.getElementById('error-analysis-widget');
    if (oldWidget) oldWidget.remove();

    container.insertBefore(wrapper, container.firstChild);
  } catch (e) {
    console.error('Erro ao carregar Error Analysis Patterns:', e);
  }
}


// ============================================================
// FORGETTING CURVE ALERTS — Widget de alertas de retenção
// ============================================================

async function loadForgettingAlerts() {
  const container = document.getElementById('si-techniques-alerts');
  if (!container) return;

  try {
    const res = await fetch('/api/study-intelligence/alerts');
    if (!res.ok) return;
    const data = await res.json();

    const urgenciaColor = (u) => {
      switch (u) {
        case 'alta': return 'var(--red, #f38ba8)';
        case 'media': return 'var(--yellow, #f9e2af)';
        case 'baixa': return 'var(--green, #a6e3a1)';
        default: return 'var(--text-sub)';
      }
    };

    let html = '';

    if (data.total_em_risco === 0) {
      html = `
        <div style="background:var(--bg-surface);border-radius:10px;padding:16px;margin-top:10px;border-left:4px solid var(--green, #a6e3a1);">
          <div style="font-size:0.88rem;color:var(--text);text-align:center;">✅ Nenhum item em risco. Tudo sob controle!</div>
        </div>`;
    } else {
      // Header
      html += `
        <div style="background:var(--bg-surface);border-radius:10px;padding:16px;margin-top:10px;border-left:4px solid var(--red, #f38ba8);">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
            <span style="font-size:0.92rem;font-weight:700;color:var(--text);">⚠️ Alertas de Retenção</span>
            <span style="background:var(--red, #f38ba8);color:#1e1e2e;font-size:0.68rem;font-weight:700;padding:2px 8px;border-radius:10px;">${data.total_em_risco}</span>
          </div>

          <!-- Cards por matéria -->
          <div style="display:flex;flex-direction:column;gap:8px;">
            ${data.alerts.map(alert => {
              const cor = urgenciaColor(alert.urgencia);
              const retencaoPct = Math.max(0, Math.min(100, alert.retencao_media));
              const barColor = retencaoPct >= 80 ? 'var(--green, #a6e3a1)' :
                               retencaoPct >= 60 ? 'var(--yellow, #f9e2af)' :
                               retencaoPct >= 40 ? 'var(--peach, #fab387)' : 'var(--red, #f38ba8)';
              return `
                <div style="background:var(--bg);border-radius:8px;padding:12px;border-left:3px solid ${cor};">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                    <span style="font-size:0.82rem;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%;">${alert.materia}</span>
                    <span style="font-size:0.68rem;font-weight:600;color:${cor};text-transform:uppercase;">${alert.urgencia}</span>
                  </div>
                  <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                    <span style="font-size:0.72rem;color:var(--text-sub);">${alert.items_em_risco} itens em risco</span>
                    <span style="font-size:0.72rem;color:var(--text-sub);">·</span>
                    <span style="font-size:0.72rem;color:var(--text-sub);">⏱ ${alert.tempo_revisao_min}min</span>
                  </div>
                  <div style="display:flex;align-items:center;gap:8px;">
                    <div style="flex:1;height:6px;background:var(--border, #45475a);border-radius:3px;overflow:hidden;">
                      <div style="height:100%;width:${retencaoPct}%;background:${barColor};border-radius:3px;transition:width 0.4s;"></div>
                    </div>
                    <span style="font-size:0.68rem;font-weight:600;color:${barColor};min-width:32px;text-align:right;">${retencaoPct.toFixed(0)}%</span>
                  </div>
                </div>`;
            }).join('')}
          </div>

          <!-- Footer -->
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid var(--border, #45475a);">
            <span style="font-size:0.75rem;color:var(--text-sub);">Tempo total para revisar tudo: <strong style="color:var(--text);">${data.tempo_total_min}min</strong></span>
            <button onclick="window.location.href='/#flashcards'" style="background:var(--accent, #cba6f7);color:#1e1e2e;border:none;border-radius:8px;padding:8px 14px;font-size:0.78rem;font-weight:700;cursor:pointer;white-space:nowrap;">Revisar Agora</button>
          </div>
        </div>`;
    }

    // Appendar (não substituir)
    const wrapper = document.createElement('div');
    wrapper.id = 'forgetting-alerts-widget';
    wrapper.innerHTML = html;
    // Remover widget anterior se existir (evitar duplicação em reloads)
    const existing = document.getElementById('forgetting-alerts-widget');
    if (existing) existing.remove();
    container.appendChild(wrapper);

  } catch(e) {
    console.error('Erro loadForgettingAlerts:', e);
  }
}

// Chamar após loadSiTechniquesAlerts (que usa setTimeout 1200ms)
setTimeout(loadForgettingAlerts, 1800);


// ============================================================
// MINIMUM DOSE — Quanto estudar por dia no mínimo
// ============================================================

async function loadMinimumDose() {
  const box = document.getElementById('si-techniques-alerts');
  if (!box) return;

  try {
    const data = await fetch('/api/study-intelligence/minimum-dose').then(r => r.ok ? r.json() : null);
    if (!data || !data.materias || data.materias.length === 0) return;

    const catEmoji = { intensivo: '🔴', investimento: '🟠', inicial: '🟡', reforco: '🔵', manutencao: '🟢' };
    const catLabel = { intensivo: 'Intensivo', investimento: 'Investimento', inicial: 'Inicial', reforco: 'Reforço', manutencao: 'Manutenção' };

    const widget = document.createElement('div');
    widget.id = 'minimum-dose-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--green, #a6e3a1);';
    widget.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <span style="font-size:0.85rem;font-weight:700;color:var(--text);">💊 Dose Mínima por Matéria</span>
        <span style="font-size:0.68rem;color:var(--text-sub);background:var(--bg);padding:3px 8px;border-radius:6px;">${data.total_minutos_alocados}min total</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        ${data.materias.slice(0, 6).map(m => `
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:0.75rem;">${catEmoji[m.categoria] || '⚪'}</span>
            <span style="flex:1;font-size:0.78rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${m.materia}</span>
            <span style="font-size:0.72rem;font-weight:700;color:var(--accent);min-width:40px;text-align:right;">${m.minutos_alocados}min</span>
            <span style="font-size:0.65rem;color:var(--text-sub);min-width:50px;">${catLabel[m.categoria]}</span>
          </div>
        `).join('')}
      </div>
      ${data.dica ? `<div style="font-size:0.72rem;color:var(--text-sub);margin-top:8px;font-style:italic;">💡 ${data.dica}</div>` : ''}
    `;
    // Remove anterior se existir
    document.getElementById('minimum-dose-widget')?.remove();
    box.appendChild(widget);
  } catch(e) {}
}

setTimeout(loadMinimumDose, 2000);

// ============================================================
// KNOWLEDGE GRAPH OPTIMAL ORDER — Ordem ótima de estudo
// ============================================================

async function loadOptimalOrder() {
  const box = document.getElementById('si-techniques-alerts');
  if (!box) return;

  try {
    const data = await fetch('/api/knowledge-graph/optimal-order?limit=8').then(r => r.ok ? r.json() : null);
    if (!data || !data.ordem || data.ordem.length === 0) return;

    const widget = document.createElement('div');
    widget.id = 'optimal-order-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--accent, #cba6f7);';

    const statusIcon = { 'Não iniciado': '⬜', 'Em andamento': '🟡', 'Concluído': '✅' };

    widget.innerHTML = `
      <div style="font-size:0.85rem;font-weight:700;color:var(--text);margin-bottom:10px;">🗺️ Ordem Ótima de Estudo (por dependências)</div>
      <div style="display:flex;flex-direction:column;gap:5px;">
        ${data.ordem.slice(0, 8).map((t, i) => `
          <div style="display:flex;align-items:center;gap:8px;padding:4px 0;${t.bloqueado ? 'opacity:0.5;' : ''}">
            <span style="font-size:0.72rem;color:var(--text-sub);min-width:20px;text-align:right;font-weight:600;">${i + 1}.</span>
            <span style="font-size:0.8rem;">${statusIcon[t.status] || '⬜'}</span>
            <div style="flex:1;min-width:0;">
              <div style="font-size:0.78rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${t.topico}</div>
              <div style="font-size:0.65rem;color:var(--text-sub);">${t.materia}${t.desbloqueios > 0 ? ` · 🔓 desbloqueia ${t.desbloqueios}` : ''}</div>
            </div>
            ${t.bloqueado ? '<span style="font-size:0.65rem;color:var(--red, #f38ba8);">🔒</span>' : ''}
          </div>
        `).join('')}
      </div>
      <div style="font-size:0.68rem;color:var(--text-sub);margin-top:8px;">📐 Baseado em pré-requisitos + impacto de desbloqueio + status atual</div>
    `;
    document.getElementById('optimal-order-widget')?.remove();
    box.appendChild(widget);
  } catch(e) {}
}

setTimeout(loadOptimalOrder, 2200);

// ============================================================
// OVERCONFIDENCE DETECTION — Alerta de calibração metacognitiva
// ============================================================

async function loadOverconfidenceAlert() {
  const box = document.getElementById('si-techniques-alerts');
  if (!box) return;

  try {
    const data = await fetch('/api/study-intelligence/overconfidence').then(r => r.ok ? r.json() : null);
    if (!data || data.ilusoes_de_saber === 0) return;  // Só mostra se há problema

    const widget = document.createElement('div');
    widget.id = 'overconfidence-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--red, #f38ba8);';

    const top3 = data.top5_overconfidence.slice(0, 3);

    widget.innerHTML = `
      <div style="font-size:0.85rem;font-weight:700;color:var(--text);margin-bottom:6px;">🎭 Alerta: Ilusão de Saber</div>
      <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:10px;">${data.alerta_geral}</div>
      <div style="display:flex;flex-direction:column;gap:8px;">
        ${top3.map(m => {
          const barConf = Math.round(m.confianca_pct);
          const barAcerto = Math.round(m.pct_acerto);
          return `
            <div style="padding:8px;background:var(--bg, #1e1e2e);border-radius:8px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                <span style="font-size:0.78rem;font-weight:600;color:var(--text);">${m.materia}</span>
                <span style="font-size:0.68rem;padding:2px 6px;border-radius:4px;background:${m.status === 'ilusão de saber' ? 'rgba(243,139,168,0.2)' : 'rgba(249,226,175,0.2)'};color:${m.status === 'ilusão de saber' ? 'var(--red)' : 'var(--yellow)'};">${m.status}</span>
              </div>
              <div style="display:flex;gap:4px;align-items:center;margin-bottom:3px;">
                <span style="font-size:0.65rem;color:var(--text-sub);min-width:55px;">Confiança:</span>
                <div style="flex:1;height:5px;background:var(--border);border-radius:3px;overflow:hidden;">
                  <div style="height:100%;width:${barConf}%;background:var(--accent, #cba6f7);border-radius:3px;"></div>
                </div>
                <span style="font-size:0.65rem;color:var(--text-sub);min-width:30px;text-align:right;">${barConf}%</span>
              </div>
              <div style="display:flex;gap:4px;align-items:center;">
                <span style="font-size:0.65rem;color:var(--text-sub);min-width:55px;">Acerto real:</span>
                <div style="flex:1;height:5px;background:var(--border);border-radius:3px;overflow:hidden;">
                  <div style="height:100%;width:${barAcerto}%;background:var(--green, #a6e3a1);border-radius:3px;"></div>
                </div>
                <span style="font-size:0.65rem;color:var(--text-sub);min-width:30px;text-align:right;">${barAcerto}%</span>
              </div>
              ${m.sugestoes.length > 0 ? `<div style="font-size:0.68rem;color:var(--yellow);margin-top:6px;">${m.sugestoes[0]}</div>` : ''}
            </div>`;
        }).join('')}
      </div>
      <div style="font-size:0.68rem;color:var(--text-sub);margin-top:8px;">💡 ${data.dica_metodologica}</div>
    `;
    document.getElementById('overconfidence-widget')?.remove();
    box.appendChild(widget);
  } catch(e) {}
}

setTimeout(loadOverconfidenceAlert, 2400);


// ============================================================
// PEER TEACHING — Sugestões de tópicos para ensinar
// ============================================================

async function loadPeerTeaching() {
  const box = document.getElementById('si-techniques-alerts');
  if (!box) return;

  try {
    const data = await fetch('/api/study-intelligence/peer-teaching').then(r => r.ok ? r.json() : null);
    if (!data || !data.sugestoes || data.sugestoes.length === 0) return;

    const widget = document.createElement('div');
    widget.id = 'peer-teaching-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--green, #a6e3a1);';
    widget.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:0.85rem;font-weight:700;color:var(--text);">🎓 Ensine para Aprender (Peer Teaching)</span>
        ${data.xp_ensino_semana > 0 ? `<span style="font-size:0.68rem;color:var(--green);font-weight:600;">+${data.xp_ensino_semana} XP esta semana</span>` : ''}
      </div>
      <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:10px;">${data.mensagem}</div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        ${data.sugestoes.slice(0, 3).map(s => `
          <div style="display:flex;align-items:center;gap:10px;padding:8px 10px;background:var(--bg, #1e1e2e);border-radius:8px;">
            <div style="flex:1;min-width:0;">
              <div style="font-size:0.8rem;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${s.materia}</div>
              ${s.topico_sugerido ? `<div style="font-size:0.7rem;color:var(--text-sub);">📌 ${s.topico_sugerido}</div>` : ''}
              <div style="font-size:0.65rem;color:var(--text-sub);">Acerto: ${s.pct_acerto}% (${s.total_questoes}q)</div>
            </div>
            <button onclick="window._initPeerTeach('${s.materia.replace(/'/g, "\\'")}')" style="background:var(--green, #a6e3a1);color:#1e1e2e;border:none;border-radius:6px;padding:6px 10px;font-size:0.72rem;font-weight:600;cursor:pointer;white-space:nowrap;">Ensinar 🎤</button>
          </div>
        `).join('')}
      </div>
      <div style="font-size:0.65rem;color:var(--text-sub);margin-top:8px;">📊 Pirâmide: ensinar = 90% retenção vs 10% de leitura. +30 XP por sessão.</div>
    `;
    document.getElementById('peer-teaching-widget')?.remove();
    box.appendChild(widget);
  } catch(e) {}
}

window._initPeerTeach = function(materia) {
  // Redirecionar para study room ou mostrar prompt
  const msg = `Tente explicar "${materia}" como se fosse para alguém que não sabe nada do assunto. Use exemplos simples.`;
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;';
  overlay.innerHTML = `
    <div style="background:var(--bg-elevated, #45475a);border-radius:16px;padding:24px;max-width:420px;width:90%;">
      <div style="font-size:1.5rem;text-align:center;margin-bottom:8px;">🎓</div>
      <h3 style="color:var(--text);text-align:center;margin-bottom:12px;">Ensine: ${materia}</h3>
      <p style="font-size:0.82rem;color:var(--text-sub);margin-bottom:16px;line-height:1.5;">${msg}</p>
      <textarea id="peer-teach-text" placeholder="Escreva sua explicação aqui... (mínimo 50 caracteres)" style="width:100%;min-height:120px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;color:var(--text);font-size:0.85rem;font-family:inherit;resize:vertical;"></textarea>
      <div style="display:flex;gap:8px;margin-top:12px;">
        <button onclick="this.closest('div[style*=fixed]').remove()" style="flex:1;padding:10px;background:var(--border);color:var(--text);border:none;border-radius:8px;cursor:pointer;">Cancelar</button>
        <button onclick="window._submitPeerTeach('${materia.replace(/'/g, "\\'")}')" style="flex:1;padding:10px;background:var(--green);color:#1e1e2e;border:none;border-radius:8px;font-weight:600;cursor:pointer;">Registrar ✅</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
};

window._submitPeerTeach = async function(materia) {
  const text = document.getElementById('peer-teach-text')?.value || '';
  if (text.length < 50) { if (typeof _toastDash === 'function') _toastDash('Escreva pelo menos 50 caracteres para registrar.'); return; }
  try {
    await fetch('/api/study-intelligence/peer-teaching/registrar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ materia, explicacao: text }),
    });
    document.querySelector('div[style*="position:fixed"][style*="99999"]')?.remove();
    if (typeof _toastDash === 'function') _toastDash('🎓 Ensino registrado! +30 XP');
  } catch(e) {
    if (typeof _toastDash === 'function') _toastDash('Erro ao registrar');
  }
};

setTimeout(loadPeerTeaching, 2600);

// ============================================================
// SPACING CALCULATOR — Gap ideal entre revisões por matéria
// ============================================================

async function loadSpacingCalculator() {
  const box = document.getElementById('si-techniques-alerts');
  if (!box) return;

  try {
    // Usar dados de flashcards + edital para calcular spacing ideal
    // Gap ideal = 10-20% do período de retenção desejado (Cepeda 2008)
    const flashcards = await fetch('/api/flashcards').then(r => r.ok ? r.json() : []);
    if (!flashcards || flashcards.length === 0) return;

    // Agrupar por matéria e calcular spacing médio
    const materiaMap = {};
    flashcards.forEach(fc => {
      const mat = fc.materia || 'Geral';
      if (!materiaMap[mat]) materiaMap[mat] = { total: 0, stabilities: [], pendentes: 0 };
      materiaMap[mat].total++;
      if (fc.stability > 0) materiaMap[mat].stabilities.push(fc.stability);
      if (fc.proxima_revisao && new Date(fc.proxima_revisao) <= new Date()) materiaMap[mat].pendentes++;
    });

    // Calcular gap ideal por matéria
    const spacingData = Object.entries(materiaMap).map(([mat, data]) => {
      const avgStability = data.stabilities.length > 0
        ? data.stabilities.reduce((a, b) => a + b, 0) / data.stabilities.length
        : 1;
      // Gap ideal (Cepeda 2008): ~10-20% do intervalo atual
      // Se stability = 10 dias → revisar a cada 1-2 dias para manter 90%
      const gapIdeal = Math.max(1, Math.round(avgStability * 0.15));
      const proximaRevisaoIdeal = gapIdeal;
      return { mat, total: data.total, avgStability: Math.round(avgStability * 10) / 10, gapIdeal, pendentes: data.pendentes };
    }).sort((a, b) => a.gapIdeal - b.gapIdeal);

    if (spacingData.length === 0) return;

    const widget = document.createElement('div');
    widget.id = 'spacing-calc-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--blue, #89b4fa);';
    widget.innerHTML = `
      <div style="font-size:0.85rem;font-weight:700;color:var(--text);margin-bottom:8px;">📐 Spacing Calculator (Gap Ideal)</div>
      <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:10px;">Cepeda (2008): o intervalo ótimo entre revisões é ~10-20% do período de retenção.</div>
      <div style="display:flex;flex-direction:column;gap:5px;">
        ${spacingData.slice(0, 6).map(s => {
          const urgencia = s.pendentes > 0 ? 'var(--red, #f38ba8)' : s.gapIdeal <= 2 ? 'var(--yellow, #f9e2af)' : 'var(--green, #a6e3a1)';
          return `
            <div style="display:flex;align-items:center;gap:8px;">
              <div style="width:6px;height:6px;border-radius:50%;background:${urgencia};"></div>
              <span style="flex:1;font-size:0.78rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${s.mat}</span>
              <span style="font-size:0.72rem;font-weight:600;color:var(--accent);min-width:55px;text-align:right;">a cada ${s.gapIdeal}d</span>
              ${s.pendentes > 0 ? `<span style="font-size:0.65rem;color:var(--red);min-width:45px;">${s.pendentes} atrasados</span>` : `<span style="font-size:0.65rem;color:var(--text-sub);min-width:45px;">Stab: ${s.avgStability}d</span>`}
            </div>`;
        }).join('')}
      </div>
      <div style="font-size:0.65rem;color:var(--text-sub);margin-top:8px;">💡 Matérias com gap menor precisam de revisão mais frequente para manter 90%+ de retenção.</div>
    `;
    document.getElementById('spacing-calc-widget')?.remove();
    box.appendChild(widget);
  } catch(e) {}
}

setTimeout(loadSpacingCalculator, 2800);


// ============================================================
// CONTEXTUAL VARIATION — Variação de formato de estudo
// ============================================================

async function loadContextualVariation() {
  const container = document.getElementById('si-techniques-alerts');
  if (!container) return;

  try {
    // Get first available materia from edital
    const mats = await fetch('/api/edital/materias-disponiveis').then(r => r.ok ? r.json() : []);
    if (!mats || mats.length === 0) return;
    const materia = mats[Math.floor(Math.random() * Math.min(mats.length, 5))];

    const data = await fetch(`/api/study-intelligence/contextual-variation?materia=${encodeURIComponent(materia)}`).then(r => r.ok ? r.json() : null);
    if (!data || !data.variacoes || data.variacoes.length === 0) return;

    // Pick a random variation that's NOT flashcard/questao (prioritize novel formats)
    const novelFormats = data.variacoes.filter(v => ['dissertativa', 'ensinar', 'conexoes'].includes(v.formato));
    const chosen = novelFormats.length > 0 ? novelFormats[Math.floor(Math.random() * novelFormats.length)] : data.variacoes[0];

    const widget = document.createElement('div');
    widget.id = 'si-contextual-variation-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--mauve, #cba6f7);';
    widget.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:0.85rem;font-weight:700;color:var(--text);">🔀 Varie o formato!</span>
        <span style="font-size:0.68rem;color:var(--text-sub);background:var(--bg);padding:2px 8px;border-radius:6px;">${data.materia}</span>
      </div>
      <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:8px;">
        ${chosen.icone} <strong style="color:var(--text);">${chosen.formato.charAt(0).toUpperCase() + chosen.formato.slice(1)}</strong> — ${chosen.instrucao}
      </div>
      ${chosen.conteudo?.prompt ? `<div style="font-size:0.75rem;color:var(--accent);background:var(--bg);padding:8px 10px;border-radius:8px;margin-bottom:8px;font-style:italic;">"${chosen.conteudo.prompt}"</div>` : ''}
      <div style="font-size:0.68rem;color:var(--text-sub);margin-top:4px;">💡 ${data.instrucao_geral?.slice(0, 120) || 'Estudar em formatos variados melhora a transferência de conhecimento.'}</div>
    `;
    document.getElementById('si-contextual-variation-widget')?.remove();
    container.appendChild(widget);
  } catch(e) { /* graceful */ }
}

setTimeout(loadContextualVariation, 3000);

// ============================================================
// DUAL CODING — Representação visual sugerida
// ============================================================

async function loadDualCoding() {
  const container = document.getElementById('si-techniques-alerts');
  if (!container) return;

  try {
    const mats = await fetch('/api/edital/materias-disponiveis').then(r => r.ok ? r.json() : []);
    if (!mats || mats.length === 0) return;
    const materia = mats[Math.floor(Math.random() * Math.min(mats.length, 5))];

    const data = await fetch(`/api/study-intelligence/dual-coding?materia=${encodeURIComponent(materia)}`).then(r => r.ok ? r.json() : null);
    if (!data || !data.sugestao_principal) return;

    const sugestao = data.sugestao_principal;

    const widget = document.createElement('div');
    widget.id = 'si-dual-coding-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--teal, #94e2d5);';
    widget.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:0.85rem;font-weight:700;color:var(--text);">🎨 Represente visualmente</span>
        <span style="font-size:0.68rem;color:var(--text-sub);background:var(--bg);padding:2px 8px;border-radius:6px;">${data.materia}</span>
      </div>
      <div style="font-size:0.78rem;color:var(--text);margin-bottom:6px;">
        ${sugestao.icone} <strong>${sugestao.tipo.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</strong>
      </div>
      <div style="font-size:0.75rem;color:var(--text-sub);margin-bottom:6px;">${sugestao.instrucao}</div>
      ${sugestao.exemplo ? `<div style="font-size:0.72rem;color:var(--accent);background:var(--bg);padding:6px 10px;border-radius:6px;font-family:monospace;">${sugestao.exemplo}</div>` : ''}
      <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;">
        ${data.todas_opcoes.slice(0, 4).map(o => `<span style="font-size:0.68rem;background:var(--bg);padding:2px 6px;border-radius:4px;color:var(--text-sub);">${o.icone} ${o.tipo.replace(/_/g, ' ')}</span>`).join('')}
      </div>
      <div style="font-size:0.65rem;color:var(--text-sub);margin-top:8px;">💡 ${data.dica_geral?.slice(0, 100) || 'Dual Coding: texto + visual = 2 caminhos de memória.'}</div>
    `;
    document.getElementById('si-dual-coding-widget')?.remove();
    container.appendChild(widget);
  } catch(e) { /* graceful */ }
}

setTimeout(loadDualCoding, 3200);

// ============================================================
// CONCRETE EXAMPLES — Exemplos concretos para conceitos abstratos
// ============================================================

async function loadConcreteExamples() {
  const container = document.getElementById('si-techniques-alerts');
  if (!container) return;

  try {
    const mats = await fetch('/api/edital/materias-disponiveis').then(r => r.ok ? r.json() : []);
    if (!mats || mats.length === 0) return;
    const materia = mats[Math.floor(Math.random() * Math.min(mats.length, 5))];

    const data = await fetch(`/api/study-intelligence/concrete-examples?materia=${encodeURIComponent(materia)}`).then(r => r.ok ? r.json() : null);
    if (!data || (!data.exemplos_prontos?.length && !data.criar_proprio)) return;

    const exemplo = data.exemplos_prontos?.length > 0
      ? data.exemplos_prontos[Math.floor(Math.random() * data.exemplos_prontos.length)]
      : null;

    const widget = document.createElement('div');
    widget.id = 'si-concrete-examples-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--peach, #fab387);';
    widget.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:0.85rem;font-weight:700;color:var(--text);">💡 Exemplo Concreto</span>
        <span style="font-size:0.68rem;color:var(--text-sub);background:var(--bg);padding:2px 8px;border-radius:6px;">${data.materia}</span>
      </div>
      ${exemplo ? `
        <div style="font-size:0.78rem;color:var(--accent);font-weight:600;margin-bottom:4px;">${exemplo.conceito}</div>
        <div style="font-size:0.75rem;color:var(--text-sub);line-height:1.5;background:var(--bg);padding:8px 10px;border-radius:8px;">${exemplo.exemplo}</div>
      ` : `
        <div style="font-size:0.78rem;color:var(--text-sub);">Crie seus próprios exemplos concretos para ${data.materia}!</div>
      `}
      <div style="font-size:0.65rem;color:var(--text-sub);margin-top:8px;">🧠 ${data.por_que_funciona?.slice(0, 120) || 'Exemplos concretos ancoram conceitos abstratos na memória de longo prazo.'}</div>
    `;
    document.getElementById('si-concrete-examples-widget')?.remove();
    container.appendChild(widget);
  } catch(e) { /* graceful */ }
}

setTimeout(loadConcreteExamples, 3400);

// ============================================================
// MEMORY PALACE — Template de Palácio da Memória
// ============================================================

async function loadMemoryPalace() {
  const container = document.getElementById('si-techniques-alerts');
  if (!container) return;

  try {
    const mats = await fetch('/api/edital/materias-disponiveis').then(r => r.ok ? r.json() : []);
    if (!mats || mats.length === 0) return;
    const materia = mats[Math.floor(Math.random() * Math.min(mats.length, 5))];

    const data = await fetch(`/api/study-intelligence/memory-palace?materia=${encodeURIComponent(materia)}`).then(r => r.ok ? r.json() : null);
    if (!data || !data.palace_template) return;

    const palace = data.palace_template;

    const widget = document.createElement('div');
    widget.id = 'si-memory-palace-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--yellow, #f9e2af);';
    widget.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:0.85rem;font-weight:700;color:var(--text);">🏰 Palácio da Memória</span>
        <span style="font-size:0.68rem;color:var(--text-sub);background:var(--bg);padding:2px 8px;border-radius:6px;">${data.materia}</span>
      </div>
      <div style="font-size:0.75rem;color:var(--text-sub);margin-bottom:8px;">Use sua casa como palácio! Associe cada item a um local:</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;">
        ${palace.locais.map(l => `
          <div style="font-size:0.72rem;color:var(--text);display:flex;align-items:center;gap:4px;min-width:0;overflow:hidden;">
            <span style="font-size:0.68rem;color:var(--text-sub);min-width:14px;">${l.posicao}.</span>
            <span>${l.local}</span>
          </div>
        `).join('')}
      </div>
      ${data.items_para_memorizar?.length > 0 ? `
        <div style="font-size:0.72rem;color:var(--accent);margin-top:8px;padding-top:8px;border-top:1px solid var(--border, #45475a);">
          📋 Sugestão: memorize "${data.items_para_memorizar[0].pergunta?.slice(0, 60) || 'seus flashcards'}"
        </div>
      ` : ''}
      <div style="font-size:0.65rem;color:var(--text-sub);margin-top:6px;">💡 Imagens absurdas e exageradas são mais memoráveis!</div>
    `;
    document.getElementById('si-memory-palace-widget')?.remove();
    container.appendChild(widget);
  } catch(e) { /* graceful */ }
}

setTimeout(loadMemoryPalace, 3600);

// ============================================================
// TRANSFER TEST — Teste de Transferência
// ============================================================

async function loadTransferTest() {
  const container = document.getElementById('si-techniques-alerts');
  if (!container) return;

  try {
    const data = await fetch('/api/study-intelligence/transfer-test').then(r => r.ok ? r.json() : null);
    if (!data || data.total === 0) return;

    const widget = document.createElement('div');
    widget.id = 'si-transfer-test-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--blue, #89b4fa);';
    widget.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:0.85rem;font-weight:700;color:var(--text);">🔄 Teste de Transferência</span>
        <span style="font-size:0.68rem;color:var(--text-sub);background:var(--bg);padding:2px 8px;border-radius:6px;">${data.total} questões</span>
      </div>
      <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:8px;">${data.mensagem}</div>
      <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:10px;">
        Formato habitual: <strong style="color:var(--text);">${(data.formato_predominante || '').replace(/_/g, ' ')}</strong>
        → Transferir para: <strong style="color:var(--accent);">${(data.formato_transferencia || '').replace(/_/g, ' ')}</strong>
      </div>
      <button onclick="window.location.href='questoes.html?modo=transfer'" style="
        background:var(--blue, #89b4fa);color:var(--bg);border:none;border-radius:8px;
        padding:8px 16px;font-size:0.78rem;font-weight:600;cursor:pointer;width:100%;
        transition:opacity 0.2s;" onmouseover="this.style.opacity='0.85'" onmouseout="this.style.opacity='1'">
        ⚡ Iniciar Teste de Transferência
      </button>
      <div style="font-size:0.65rem;color:var(--text-sub);margin-top:8px;">🧠 ${data.tecnica?.slice(0, 130) || 'Variar formato testa se realmente entendeu o conceito.'}</div>
    `;
    document.getElementById('si-transfer-test-widget')?.remove();
    container.appendChild(widget);
  } catch(e) { /* graceful */ }
}

setTimeout(loadTransferTest, 3800);

// ============================================================
// BANCA TRAINING — Treino específico por banca
// ============================================================

async function loadBancaTraining() {
  const container = document.getElementById('si-techniques-alerts');
  if (!container) return;

  try {
    // First get the user's banca from banca-profile endpoint
    const profile = await fetch('/api/study-intelligence/banca-profile').then(r => r.ok ? r.json() : null);
    if (!profile || !profile.banca || !profile.profile) return;

    const banca = profile.banca;
    const p = profile.profile;

    const widget = document.createElement('div');
    widget.id = 'si-banca-training-widget';
    widget.style.cssText = 'background:var(--bg-surface, #313244);border-radius:10px;padding:14px;margin-bottom:10px;border-left:4px solid var(--red, #f38ba8);';
    widget.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:0.85rem;font-weight:700;color:var(--text);">🎯 Treino de Banca: ${banca}</span>
        <span style="font-size:0.68rem;color:${p.penalizacao ? 'var(--red)' : 'var(--green)'};background:var(--bg);padding:2px 8px;border-radius:6px;font-weight:600;">
          ${p.penalizacao ? '⚠️ Penalização' : '✅ Sem penalização'}
        </span>
      </div>
      <div style="font-size:0.75rem;color:var(--text-sub);margin-bottom:6px;">${p.estilo?.slice(0, 100) || ''}</div>
      <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:10px;">
        ${p.armadilhas_comuns?.slice(0, 2).map(a => `<div style="margin-bottom:3px;">⚠️ ${a.slice(0, 80)}</div>`).join('') || ''}
      </div>
      ${profile.stats_usuario ? `
        <div style="font-size:0.72rem;color:var(--text-sub);margin-bottom:8px;padding:6px 8px;background:var(--bg);border-radius:6px;">
          📊 Seu desempenho ${banca}: <strong style="color:var(--accent);">${profile.stats_usuario.pct_acerto}%</strong> (${profile.stats_usuario.total_questoes} questões)
        </div>
      ` : ''}
      <button onclick="window._startBancaTraining('${banca}')" style="
        background:var(--red, #f38ba8);color:var(--bg);border:none;border-radius:8px;
        padding:8px 16px;font-size:0.78rem;font-weight:600;cursor:pointer;width:100%;
        transition:opacity 0.2s;" onmouseover="this.style.opacity='0.85'" onmouseout="this.style.opacity='1'">
        ⚔️ Iniciar Sessão de Treino ${banca}
      </button>
      <div style="font-size:0.65rem;color:var(--text-sub);margin-top:6px;">💡 ${p.dicas_estrategicas?.[0]?.slice(0, 100) || 'Treine no estilo da banca para ganhar 15-20% no dia da prova.'}</div>
    `;
    document.getElementById('si-banca-training-widget')?.remove();
    container.appendChild(widget);
  } catch(e) { /* graceful */ }
}

// Helper: start banca training session
window._startBancaTraining = async function(banca) {
  try {
    const data = await fetch(`/api/study-intelligence/banca-training?banca=${encodeURIComponent(banca)}&quantidade=10`).then(r => r.ok ? r.json() : null);
    if (!data || !data.questao_ids || data.questao_ids.length === 0) {
      _toastDash?.('Sem questões disponíveis para treino de banca');
      return;
    }
    // Navigate to questoes page with banca training mode
    const ids = data.questao_ids.join(',');
    window.location.href = `questoes.html?modo=banca&banca=${encodeURIComponent(banca)}&ids=${ids}`;
  } catch(e) {
    _toastDash?.('Erro ao iniciar treino de banca');
  }
};

setTimeout(loadBancaTraining, 4000);
