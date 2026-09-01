// charts.js — Chart.js related rendering (horas, acertos, materias, edital, radar, evolucao, heatmap-erros, metas-realizado)
import { getCSSVar, COLORS } from './helpers.js';

export function renderChartHoras(data) {
  if (typeof Chart === 'undefined') { setTimeout(() => renderChartHoras(data), 200); return; }
  if (!data || data.length === 0) {
    document.getElementById('chart-horas').parentElement.innerHTML = '<p style="color:var(--text-sub);font-size:0.82rem;text-align:center;padding:20px;">Estude para gerar o gráfico de horas.</p>';
    return;
  }
  const ctx = document.getElementById('chart-horas')?.getContext('2d');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.map(d => d.data.slice(5)),
      datasets: [{
        label: 'Horas',
        data: data.map(d => d.total_horas),
        backgroundColor: COLORS.blue + '99',
        borderColor: COLORS.blue,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true } }
    }
  });
}

export function renderChartAcertos(data) {
  if (typeof Chart === 'undefined') { setTimeout(() => renderChartAcertos(data), 200); return; }
  if (!data || data.length === 0) return;
  const ctx = document.getElementById('chart-acertos')?.getContext('2d');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.map(d => d.data.slice(5)),
      datasets: [{
        label: '% Acerto',
        data: data.map(d => d.total > 0 ? Math.round(d.acertos / d.total * 100) : 0),
        borderColor: COLORS.green,
        backgroundColor: COLORS.green + '33',
        fill: true,
        tension: 0.3,
        pointRadius: 4,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, max: 100 } }
    }
  });
}

export function renderChartMaterias(data) {
  if (typeof Chart === 'undefined') { setTimeout(() => renderChartMaterias(data), 200); return; }
  if (!data || data.length === 0) return;
  const ctx = document.getElementById('chart-materias')?.getContext('2d');
  if (!ctx) return;
  const colors = [COLORS.blue, COLORS.green, COLORS.peach, COLORS.pink, COLORS.mauve, COLORS.teal, COLORS.yellow];
  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: data.map(d => d.materia),
      datasets: [{
        data: data.map(d => d.total),
        backgroundColor: data.map((_, i) => colors[i % colors.length] + 'CC'),
        borderColor: getCSSVar('--bg') || '#1e1e2e',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { position: 'right', labels: { boxWidth: 12, padding: 8, font: { size: 11 } } } }
    }
  });
}

export function renderChartEdital(data) {
  if (typeof Chart === 'undefined') { setTimeout(() => renderChartEdital(data), 200); return; }
  if (!data) return;
  const ctx = document.getElementById('chart-edital')?.getContext('2d');
  if (!ctx) return;
  const pendente = data.total - data.concluido;
  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Concluído', 'Pendente'],
      datasets: [{
        data: [data.concluido, pendente],
        backgroundColor: [COLORS.green + 'CC', COLORS.surface],
        borderColor: getCSSVar('--bg') || '#1e1e2e',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { position: 'bottom' } }
    }
  });
}

export async function loadRadar() {
  const data = await fetch('/api/radar').then(r => r.json());
  if (!data.length) return;
  const ctx = document.getElementById('chart-radar').getContext('2d');
  const sorted = data.sort((a,b) => b.topicos_total - a.topicos_total).slice(0, 10);
  new Chart(ctx, {
    type: 'radar',
    data: {
      labels: sorted.map(d => d.materia.length > 20 ? d.materia.substring(0,20)+'...' : d.materia),
      datasets: [{
        label: 'Score (%)',
        data: sorted.map(d => d.score),
        borderColor: getCSSVar('--accent') || '#cba6f7',
        backgroundColor: '#cba6f733',
        pointBackgroundColor: getCSSVar('--accent') || '#cba6f7',
        pointRadius: 4,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { r: { beginAtZero: true, max: 100, grid: { color: getCSSVar('--bg-elevated') || '#45475a' }, angleLines: { color: getCSSVar('--bg-elevated') || '#45475a' }, pointLabels: { font: { size: 9 }, color: getCSSVar('--text-sub') || '#a6adc8' }, ticks: { display: false } } }
    }
  });
}

export async function loadEvolucao() {
  try {
    const data = await fetch('/api/evolucao?semanas=8').then(r => r.json());
    if (!data.evolucao || data.evolucao.length === 0) {
      document.getElementById('evolucao-chart').parentElement.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;text-align:center;padding:20px;">Resolva questões para gerar o gráfico de evolução semanal.</p>';
      return;
    }
    const labels = data.evolucao.map(e => e.semana);
    const geral = data.evolucao.map(e => e.geral.pct);
    const questoes = data.evolucao.map(e => e.geral.questoes);
    const horas = data.evolucao.map(e => e.geral.horas);
    const ctx = document.getElementById('evolucao-chart');
    if (!ctx) return;
    new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Acerto %',
          data: geral,
          borderColor: getCSSVar('--accent') || '#cba6f7',
          backgroundColor: 'rgba(203,166,247,0.1)',
          fill: true,
          tension: 0.3,
          yAxisID: 'y'
        },{
          label: 'Questões',
          data: questoes,
          borderColor: 'var(--blue)',
          backgroundColor: 'rgba(137,180,250,0.1)',
          fill: false,
          tension: 0.3,
          yAxisID: 'y1'
        },{
          label: 'Horas',
          data: horas,
          borderColor: 'var(--green)',
          backgroundColor: 'rgba(166,227,161,0.1)',
          fill: false,
          tension: 0.3,
          yAxisID: 'y1'
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#cdd6f4' } } },
        scales: {
          y: { min: 0, max: 100, position: 'left', title: { display: true, text: '% Acerto', color: 'var(--text-sub)' }, ticks: { color: 'var(--text-sub)' }, grid: { color: 'var(--bg-elevated)' } },
          y1: { min: 0, position: 'right', title: { display: true, text: 'Qtd', color: 'var(--text-sub)' }, ticks: { color: 'var(--text-sub)' }, grid: { display: false } },
          x: { ticks: { color: 'var(--text-sub)' }, grid: { color: 'var(--bg-elevated)' } }
        }
      }
    });
  } catch(e) { console.error('Evolucao error:', e); }
}

export async function loadHeatmapErros() {
  try {
    const data = await fetch('/api/heatmap-erros').then(r => r.json());
    const el = document.getElementById('heatmap-erros-box');
    if (!data.materias || !data.materias.length) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Resolva questões para gerar o mapa de erros.</p>'; return; }
    const intensityColors = ['var(--bg-surface)','var(--green)','var(--yellow)','var(--peach)','var(--red)'];
    let html = '';
    data.materias.slice(0, 5).forEach(m => {
      html += `<div style="margin-bottom:10px;"><div style="font-size:0.82rem;font-weight:600;margin-bottom:4px;">${m.materia} <span style="color:var(--text-sub);font-weight:400;">(${m.pct_erro.toFixed(0)}% erro)</span></div>`;
      html += `<div style="display:flex;flex-wrap:wrap;gap:3px;">`;
      m.topicos.slice(0, 8).forEach(t => {
        html += `<div title="${t.topico}: ${t.erros}/${t.total} erros (${t.pct_erro.toFixed(0)}%)" style="width:28px;height:28px;border-radius:4px;background:${intensityColors[t.intensidade]};cursor:help;" ></div>`;
      });
      html += `</div></div>`;
    });
    el.innerHTML = html;
  } catch(e) { console.error('HeatmapErros error:', e); }
}

export async function loadMetasRealizado() {
  try {
    const data = await fetch('/api/analytics/metas-realizado').then(r => r.json());
    if (!data.semanas || data.semanas.length === 0) return;
    if (typeof Chart === 'undefined') { setTimeout(loadMetasRealizado, 200); return; }
    const ctx = document.getElementById('chart-metas-realizado')?.getContext('2d');
    if (!ctx) return;
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.semanas.map(s => s.semana),
        datasets: [
          { label: 'Horas (real)', data: data.semanas.map(s => s.horas_real), backgroundColor: '#89b4fa99', borderColor: 'var(--blue)', borderWidth: 1, borderRadius: 3 },
          { label: 'Horas (meta)', data: data.semanas.map(s => s.horas_meta), backgroundColor: '#89b4fa22', borderColor: '#89b4fa55', borderWidth: 1, borderRadius: 3, borderDash: [3, 3] },
        ]
      },
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#a6adc8', font: { size: 10 } } } },
        scales: {
          y: { beginAtZero: true, ticks: { color: 'var(--text-sub)' }, grid: { color: 'var(--bg-elevated)' } },
          x: { ticks: { color: 'var(--text-sub)', font: { size: 9 } }, grid: { color: 'var(--bg-elevated)' } }
        }
      }
    });
  } catch(e) { console.error('MetasRealizado error:', e); }
}

export async function loadHeatmap() {
  try {
    const data = await fetch('/api/heatmap').then(r => r.json());
    const el = document.getElementById('heatmap-box');
    if (!data.length) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Estude para gerar o heatmap.</p>'; return; }
    const dateMap = {};
    data.forEach(d => { dateMap[d.data] = d.intensidade; });
    let html = '<div class="heatmap-grid">';
    const today = new Date();
    // Janela deslizante de 1 ano (últimos 365 dias até hoje) — alinhada ao backend
    // (/api/heatmap retorna date.today()-365). Antes começava no 1º dia do mês
    // atual, o que "zerava" os dias do passado na virada de mês.
    const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    start.setDate(start.getDate() - 364);
    const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const totalDays = Math.round((end - start) / 86400000) + 1;
    for (let i = 0; i < totalDays; i++) {
      const d = new Date(start); d.setDate(d.getDate() + i);
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      const key = `${yyyy}-${mm}-${dd}`;  // data local (evita shift de fuso do toISOString)
      const level = dateMap[key] || 0;
      html += `<div class="heatmap-cell ${level > 0 ? 'l'+level : ''}" title="${key}: ${level > 0 ? 'estudou' : 'sem estudo'}"></div>`;
    }
    html += '</div>';
    el.innerHTML = html;
  } catch(e) {}
}

export async function loadProjecaoNota() {
  try {
    const data = await fetch('/api/projecao-nota').then(r => r.json());
    const el = document.getElementById('projecao-nota');
    const color = data.aprovado_estimado ? 'var(--green)' : 'var(--red)';
    let html = `<div style="text-align:center;margin-bottom:12px;"><div style="font-size:2rem;font-weight:700;color:${color};">${data.nota_projetada}%</div><div style="font-size:0.8rem;color:var(--text-sub);">Nota projetada (corte: ${data.nota_corte_estimada}%)</div><div style="font-size:0.85rem;color:${color};font-weight:600;">${data.aprovado_estimado ? '\u2705 Dentro da zona de aprova\u00e7\u00e3o' : '\u26a0\ufe0f Abaixo do corte estimado'}</div></div>`;
    html += data.materias.slice(0,6).map(m => `<div style="display:flex;align-items:center;gap:6px;padding:3px 0;font-size:0.78rem;"><span style="flex:1;">${m.materia}</span><span style="color:${m.pct_acerto>=60?'var(--green)':'var(--red)'};font-weight:600;">${m.pct_acerto}%</span></div>`).join('');
    el.innerHTML = html;
  } catch(e) {}
}

export async function loadRaioX() {
  try {
    const data = await fetch('/api/raio-x').then(r => r.json());
    const el = document.getElementById('raio-x-box');
    if (!data.materias || !data.materias.length) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Adicione questões para gerar o Raio-X.</p>'; return; }
    let html = `<div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:8px;">${data.total_questoes} questões analisadas</div>`;
    data.materias.forEach(m => {
      const balColor = m.balanceamento === 'equilibrado' ? 'var(--green)' : m.balanceamento === 'subestudado' ? 'var(--red)' : 'var(--peach)';
      html += `<div style="margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:0.8rem;margin-bottom:3px;">
          <span>${m.materia}</span>
          <span style="color:${balColor};font-size:0.72rem;font-weight:600;">${m.balanceamento}</span>
        </div>
        <div style="display:flex;gap:4px;align-items:center;">
          <div style="flex:1;height:6px;background:var(--bg-elevated);border-radius:3px;overflow:hidden;">
            <div style="width:${m.peso_pct}%;height:100%;background:var(--accent);border-radius:3px;"></div>
          </div>
          <span style="font-size:0.7rem;color:var(--text-sub);min-width:35px;">${m.peso_pct.toFixed(0)}%</span>
        </div>
      </div>`;
    });
    el.innerHTML = html;
  } catch(e) { console.error('RaioX error:', e); }
}

export async function loadAnaliseErros() {
  try {
    const data = await fetch('/api/analise-erros').then(r => r.json());
    const el = document.getElementById('analise-erros');
    if (!data.erros_por_materia.length) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Resolva questões para gerar análise.</p>'; return; }
    let html = '';
    data.erros_por_materia.slice(0, 5).forEach(m => {
      const color = m.pct_erro > 60 ? 'var(--red)' : m.pct_erro > 40 ? 'var(--peach)' : 'var(--green)';
      html += `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;font-size:0.82rem;"><span style="flex:1;">${m.materia}</span><span style="color:${color};font-weight:700;">${m.pct_erro}% erro</span></div>`;
    });
    if (data.sugestoes.length) html += `<div style="margin-top:8px;padding:8px;background:var(--bg-elevated);border-radius:6px;font-size:0.78rem;color:var(--peach);">💡 ${data.sugestoes[0]}</div>`;
    el.innerHTML = html;
  } catch(e) {}
}

export function renderPratica(data) {
  const list = document.getElementById('pratica-list');
  if (data.materias_para_focar.length === 0 && data.materias_nao_estudadas.length === 0) {
    list.innerHTML = '<p style="color:var(--text-sub);font-size:0.9rem;padding:12px;">Resolva mais questões para obter recomendações de prática deliberada.</p>';
    return;
  }

  let html = '';
  for (const m of data.materias_para_focar) {
    html += `
      <div class="pratica-item">
        <span class="pratica-badge ${m.prioridade === 'ALTA' ? 'alta' : 'media'}">${m.prioridade}</span>
        <span class="pratica-materia">${m.materia}</span>
        <span class="pratica-pct" style="color:${m.percentual < 50 ? COLORS.pink : COLORS.peach}">${m.percentual}%</span>
      </div>
    `;
  }
  if (data.materias_nao_estudadas.length > 0) {
    html += `<div style="padding:10px 12px;font-size:0.85rem;color:var(--text-sub);border-top:1px solid var(--border);margin-top:8px;">
      ⚠ Matérias sem questões respondidas: ${data.materias_nao_estudadas.join(', ')}
    </div>`;
  }
  list.innerHTML = html;
}

export function renderRelatorio(data) {
  const grid = document.getElementById('relatorio-grid');
  grid.innerHTML = `
    <div class="relatorio-item"><div class="r-label">Período</div><div class="r-value">${data.periodo}</div></div>
    <div class="relatorio-item"><div class="r-label">Dias Estudados</div><div class="r-value">${data.dias_estudados}/7</div></div>
    <div class="relatorio-item"><div class="r-label">Horas Totais</div><div class="r-value" style="color:${COLORS.blue}">${data.total_horas}h</div></div>
    <div class="relatorio-item"><div class="r-label">Questões</div><div class="r-value">${data.questoes_total} (${data.questoes_percentual}% acerto)</div></div>
  `;

  const box = document.getElementById('sugestao-box');
  if (data.sugestao_foco.length > 0) {
    box.innerHTML = `
      <h4>💡 Sugestão de Foco para a Próxima Semana:</h4>
      <ul>${data.sugestao_foco.map(s => `<li>${s}</li>`).join('')}</ul>
    `;
  } else {
    box.innerHTML = '<h4>💡 Continue estudando para gerar sugestões personalizadas!</h4>';
  }
}

export async function loadVelocidade() {
  try {
    const data = await fetch('/api/analytics/velocidade').then(r => r.json());
    const el = document.getElementById('velocidade-box');
    if (!data.por_materia || data.por_materia.length === 0) {
      el.innerHTML = '<p style="color:var(--text-sub);font-size:0.82rem;">Responda questões para gerar análise de velocidade.</p>';
      return;
    }
    const mediaGeral = data.media_geral_seg;
    const fmtTime = (s) => s >= 60 ? `${Math.floor(s/60)}:${String(Math.round(s%60)).padStart(2,'0')}` : `${Math.round(s)}s`;
    let html = `<div style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap;">
      <div style="background:var(--bg);border-radius:8px;padding:10px 16px;text-align:center;">
        <div style="font-size:1.4rem;font-weight:700;color:var(--blue);">${fmtTime(mediaGeral)}</div>
        <div style="font-size:0.72rem;color:var(--text-sub);">Média geral/questão</div>
      </div>
      <div style="background:var(--bg);border-radius:8px;padding:10px 16px;text-align:center;">
        <div style="font-size:1.4rem;font-weight:700;color:var(--green);">${data.por_materia.length}</div>
        <div style="font-size:0.72rem;color:var(--text-sub);">Matérias analisadas</div>
      </div>
    </div>`;
    html += '<div style="display:flex;flex-direction:column;gap:6px;">';
    data.por_materia.slice(0, 10).forEach(m => {
      const pctBar = Math.min(100, (m.media_seg / (mediaGeral * 2)) * 100);
      const cor = m.media_seg <= mediaGeral ? 'var(--green)' : m.media_seg <= mediaGeral * 1.5 ? 'var(--yellow)' : 'var(--red)';
      html += `<div style="display:flex;align-items:center;gap:8px;font-size:0.78rem;">
        <span style="min-width:120px;color:var(--text);">${m.materia.length > 18 ? m.materia.slice(0,18)+'…' : m.materia}</span>
        <div style="flex:1;height:6px;background:var(--bg-elevated);border-radius:3px;overflow:hidden;">
          <div style="width:${pctBar}%;height:100%;background:${cor};border-radius:3px;"></div>
        </div>
        <span style="min-width:45px;text-align:right;color:${cor};font-weight:600;">${fmtTime(m.media_seg)}</span>
        <span style="min-width:40px;text-align:right;color:var(--text-sub);">${m.pct_acerto}%</span>
      </div>`;
    });
    html += '</div>';
    el.innerHTML = html;
  } catch(e) { console.error('Velocidade error:', e); }
}

export async function loadConsistencia() {
  try {
    const data = await fetch('/api/analytics/consistencia').then(r => r.json());
    const el = document.getElementById('consistencia-box');
    const pct = data.pct_consistencia;
    const corPct = pct >= 80 ? 'var(--green)' : pct >= 50 ? 'var(--yellow)' : 'var(--red)';
    let html = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
        <div style="background:var(--bg);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.3rem;font-weight:700;color:${corPct};">${data.dias_estudados}/${data.dias_totais}</div>
          <div style="font-size:0.7rem;color:var(--text-sub);">Dias estudados</div>
        </div>
        <div style="background:var(--bg);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.3rem;font-weight:700;color:var(--blue);">${data.media_horas_dia}h</div>
          <div style="font-size:0.7rem;color:var(--text-sub);">Média/dia</div>
        </div>
        <div style="background:var(--bg);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.3rem;font-weight:700;color:var(--accent);">${data.horas_total}h</div>
          <div style="font-size:0.7rem;color:var(--text-sub);">Total 4 semanas</div>
        </div>
        <div style="background:var(--bg);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.3rem;font-weight:700;color:var(--peach);">🔥 ${data.streak_atual}</div>
          <div style="font-size:0.7rem;color:var(--text-sub);">Streak atual</div>
        </div>
      </div>
      <div style="font-size:0.75rem;color:var(--text-sub);margin-bottom:6px;">Distribuição semanal (horas)</div>
      <div style="display:flex;gap:4px;align-items:flex-end;height:60px;">`;
    const maxH = Math.max(...data.distribuicao_semana, 1);
    data.distribuicao_semana.forEach((h, i) => {
      const altura = Math.max(4, (h / maxH) * 55);
      html += `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;">
        <div style="width:100%;height:${altura}px;background:var(--blue)88;border-radius:3px;"></div>
        <span style="font-size:0.6rem;color:var(--text-sub);">${data.dias_semana_nomes[i]}</span>
      </div>`;
    });
    html += '</div>';
    el.innerHTML = html;
  } catch(e) { console.error('Consistencia error:', e); }
}

export async function loadRankingMaterias() {
  try {
    const data = await fetch('/api/analytics/ranking-materias').then(r => r.json());
    const el = document.getElementById('ranking-materias-box');
    if (!data.ranking || data.ranking.length === 0) {
      el.innerHTML = '<p style="color:var(--text-sub);font-size:0.82rem;">Responda pelo menos 3 questões por matéria para gerar o ranking.</p>';
      return;
    }
    const statusColors = { forte: 'var(--green)', medio: 'var(--yellow)', fraco: 'var(--red)' };
    let html = `<div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap;">
      <span style="font-size:0.75rem;color:var(--green);background:var(--green)22;padding:3px 8px;border-radius:4px;">💪 Fortes: ${data.fortes}</span>
      <span style="font-size:0.75rem;color:var(--yellow);background:var(--yellow)22;padding:3px 8px;border-radius:4px;">⚡ Médias: ${data.medias}</span>
      <span style="font-size:0.75rem;color:var(--red);background:var(--red)22;padding:3px 8px;border-radius:4px;">⚠️ Fracas: ${data.fracas}</span>
    </div>`;
    html += '<div style="display:flex;flex-direction:column;gap:6px;">';
    data.ranking.forEach((m, i) => {
      const cor = statusColors[m.status];
      html += `<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;background:var(--bg);border-radius:6px;border-left:3px solid ${cor};font-size:0.78rem;">
        <span style="min-width:20px;color:var(--text-muted);font-weight:600;">#${i+1}</span>
        <span style="flex:1;color:var(--text);">${m.materia}</span>
        <span style="font-weight:700;color:${cor};">${m.pct_acerto}%</span>
        <span style="font-size:0.68rem;color:var(--text-sub);min-width:50px;text-align:right;">${m.total}q</span>
        <span style="font-size:0.65rem;color:var(--text-muted);min-width:100px;text-align:right;">${m.acao}</span>
      </div>`;
    });
    html += '</div>';
    el.innerHTML = html;
  } catch(e) { console.error('Ranking error:', e); }
}
