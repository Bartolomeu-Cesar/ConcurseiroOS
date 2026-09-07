/**
 * Raio-X Bancas Page
 * ConcurseiroOS
 */
(function() {
  'use strict';

  // State
  let chartTopics = null;
  let chartMaterias = null;
  let chartBancas = null;

  // DOM refs
  const filterBanca = document.getElementById('filter-banca');
  const filterMateria = document.getElementById('filter-materia');

  // Color palette
  const COLORS = [
    '#cba6f7', '#89b4fa', '#a6e3a1', '#f9e2af', '#f38ba8',
    '#94e2d5', '#fab387', '#74c7ec', '#f5c2e7', '#b4befe',
    '#89dceb', '#eba0ac', '#a6adc8', '#f5e0dc', '#cdd6f4'
  ];

  // ==================== Data Fetching ====================

  async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error('Erro ao carregar dados: ' + res.status);
    return res.json();
  }

  async function loadFilters() {
    try {
      const data = await fetchJSON('/api/analytics/raio-x?banca=&materia=');
      const filtros = data.filtros || {};

      // Populate banca filter
      (filtros.bancas || []).forEach(function(b) {
        const opt = document.createElement('option');
        opt.value = b;
        opt.textContent = b;
        filterBanca.appendChild(opt);
      });

      // Populate materia filter
      (filtros.materias || []).forEach(function(m) {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        filterMateria.appendChild(opt);
      });

      return data;
    } catch (e) {
      console.error('Erro ao carregar filtros:', e);
      return null;
    }
  }

  async function loadRaioX() {
    const banca = filterBanca.value;
    const materia = filterMateria.value;
    const params = new URLSearchParams({ banca: banca, materia: materia });
    try {
      const data = await fetchJSON('/api/analytics/raio-x?' + params.toString());
      renderTopicsChart(data.topicos || []);
      renderMateriasFromAnalytics(data.materias || []);
    } catch (e) {
      console.error('Erro raio-x:', e);
      showEmpty('topics-chart-container', 'Erro ao carregar tópicos');
      showEmpty('materias-chart-container', 'Erro ao carregar matérias');
    }
  }

  async function loadBancas() {
    try {
      const data = await fetchJSON('/api/analytics/raio-x/bancas');
      renderBancasChart(data || []);
    } catch (e) {
      console.error('Erro bancas:', e);
      showEmpty('bancas-chart-container', 'Erro ao carregar bancas');
    }
  }

  async function loadPrioridades() {
    const banca = filterBanca.value;
    const params = new URLSearchParams({ banca: banca, edital_nome: '', cargo: '' });
    try {
      const data = await fetchJSON('/api/analytics/raio-x/prioridades?' + params.toString());
      renderPrioridades(data.prioridades || [], !!data.tem_dados_ano);
    } catch (e) {
      console.error('Erro prioridades:', e);
      document.getElementById('priorities-container').innerHTML =
        '<div class="empty-state"><div class="icon">⚠️</div><p>Erro ao carregar prioridades</p></div>';
    }
  }

  async function loadBalance() {
    try {
      const data = await fetchJSON('/api/raio-x');
      renderBalance(data.materias || []);
    } catch (e) {
      console.error('Erro balance:', e);
    }
  }

  // ==================== Chart Rendering ====================

  function showEmpty(containerId, msg) {
    var container = document.getElementById(containerId);
    if (container) {
      container.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>' + msg + '</p></div>';
    }
  }

  function renderTopicsChart(topicos) {
    var container = document.getElementById('topics-chart-container');
    var canvas = document.getElementById('chart-topics');

    if (!topicos.length) {
      container.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>Nenhum tópico encontrado</p></div>';
      canvas.style.display = 'none';
      return;
    }

    // Sort by total_questoes desc and take top 15
    var sorted = topicos.slice().sort(function(a, b) { return b.total_questoes - a.total_questoes; });
    var top15 = sorted.slice(0, 15);

    var labels = top15.map(function(t) {
      var label = t.topico || t.materia;
      return label.length > 30 ? label.substring(0, 27) + '...' : label;
    });
    var values = top15.map(function(t) { return t.total_questoes; });

    container.style.display = 'none';
    canvas.style.display = 'block';

    if (chartTopics) chartTopics.destroy();

    chartTopics = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Questões',
          data: values,
          backgroundColor: COLORS.slice(0, top15.length),
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            ticks: { color: '#a6adc8', maxRotation: 45, font: { size: 11 } },
            grid: { color: 'rgba(69,71,90,0.3)' }
          },
          y: {
            ticks: { color: '#a6adc8' },
            grid: { color: 'rgba(69,71,90,0.3)' }
          }
        }
      }
    });
  }

  function renderMateriasFromAnalytics(materias) {
    var container = document.getElementById('materias-chart-container');
    var canvas = document.getElementById('chart-materias');

    if (!materias.length) {
      container.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>Nenhuma matéria encontrada</p></div>';
      canvas.style.display = 'none';
      return;
    }

    var sorted = materias.slice().sort(function(a, b) { return b.total - a.total; });
    var labels = sorted.map(function(m) {
      return m.materia.length > 25 ? m.materia.substring(0, 22) + '...' : m.materia;
    });
    var values = sorted.map(function(m) { return m.total; });

    container.style.display = 'none';
    canvas.style.display = 'block';

    if (chartMaterias) chartMaterias.destroy();

    chartMaterias = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Questões',
          data: values,
          backgroundColor: '#89b4fa',
          borderRadius: 4
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            ticks: { color: '#a6adc8' },
            grid: { color: 'rgba(69,71,90,0.3)' }
          },
          y: {
            ticks: { color: '#a6adc8', font: { size: 11 } },
            grid: { display: false }
          }
        }
      }
    });
  }

  function renderBancasChart(bancas) {
    var container = document.getElementById('bancas-chart-container');
    var canvas = document.getElementById('chart-bancas');

    if (!bancas.length) {
      container.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>Nenhuma banca encontrada</p></div>';
      canvas.style.display = 'none';
      return;
    }

    var labels = bancas.map(function(b) { return b.banca; });
    var values = bancas.map(function(b) { return b.pct_acerto; });

    container.style.display = 'none';
    canvas.style.display = 'block';

    if (chartBancas) chartBancas.destroy();

    chartBancas = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: COLORS.slice(0, bancas.length),
          borderColor: '#1e1e2e',
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              color: '#cdd6f4',
              padding: 12,
              font: { size: 12 }
            }
          },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                return ctx.label + ': ' + ctx.parsed.toFixed(1) + '% acerto';
              }
            }
          }
        }
      }
    });
  }

  // ==================== Balance Tags ====================

  function renderBalance(materias) {
    var section = document.getElementById('balance-section');
    var container = document.getElementById('balance-tags');

    if (!materias.length) {
      section.style.display = 'none';
      return;
    }

    section.style.display = 'block';
    container.innerHTML = '';

    materias.forEach(function(m) {
      var bal = (m.balanceamento || '').toLowerCase();
      var cssClass = 'equilibrado';
      var icon = '⚖️';

      if (bal.indexOf('sub') !== -1) {
        cssClass = 'subestudado';
        icon = '⬇️';
      } else if (bal.indexOf('super') !== -1 || bal.indexOf('sobre') !== -1) {
        cssClass = 'superestudado';
        icon = '⬆️';
      }

      var tag = document.createElement('span');
      tag.className = 'balance-tag ' + cssClass;
      tag.textContent = icon + ' ' + m.materia + ' (' + m.balanceamento + ')';
      container.appendChild(tag);
    });
  }

  // ==================== Priorities Table ====================

  function renderPrioridades(prioridades, temDadosAno) {
    var container = document.getElementById('priorities-container');

    if (!prioridades.length) {
      container.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>Nenhuma prioridade identificada — continue praticando!</p></div>';
      renderQuadrant([]);
      return;
    }

    function tendenciaHtml(t) {
      if (t === 'subindo') return '<span title="Cobrança subindo nas provas recentes" style="color:var(--red);font-weight:700;">↑ subindo</span>';
      if (t === 'caindo') return '<span title="Cobrança caindo" style="color:var(--green);">↓ caindo</span>';
      if (t === 'estavel') return '<span title="Cobrança estável" style="color:var(--text-sub);">→ estável</span>';
      return '<span style="color:var(--text-muted);">—</span>';
    }

    var html = '<table class="priorities-table">';
    html += '<thead><tr>';
    html += '<th>Matéria</th><th>Tópico</th><th>Domínio</th><th>Incidência (banca)</th><th>Seu acerto</th>';
    if (temDadosAno) html += '<th>Tendência</th>';
    html += '<th>Score</th><th>Recomendação</th>';
    html += '</tr></thead><tbody>';

    prioridades.forEach(function(p) {
      var rec = (p.recomendacao || '').toUpperCase();
      var badgeClass = 'normal';
      if (rec.indexOf('URGENTE') !== -1) badgeClass = 'urgente';
      else if (rec.indexOf('IMPORTANTE') !== -1) badgeClass = 'importante';

      var dominio = (p.mastery_level != null ? Math.round(p.mastery_level) + '%' : '-');
      var incid = (p.incidencia_banca != null ? p.incidencia_banca : (p.frequencia || 0));
      var acerto = (p.taxa_acerto != null ? p.taxa_acerto + '%' : '<span style="color:var(--text-muted);">n/r</span>');
      var vencidaBadge = p.revisao_vencida ? ' <span title="Revisão vencida" style="color:var(--red);">⏰</span>' : '';

      html += '<tr>';
      html += '<td>' + escapeHtml(p.materia) + '</td>';
      html += '<td>' + escapeHtml(p.topico) + vencidaBadge + '</td>';
      html += '<td>' + dominio + '</td>';
      html += '<td>' + incid + '</td>';
      html += '<td>' + acerto + '</td>';
      if (temDadosAno) html += '<td>' + tendenciaHtml(p.tendencia) + '</td>';
      html += '<td>' + (p.priority_score != null ? p.priority_score.toFixed(1) : '-') + '</td>';
      html += '<td><span class="rec-badge ' + badgeClass + '">' + escapeHtml(p.recomendacao) + '</span></td>';
      html += '</tr>';
    });

    html += '</tbody></table>';
    container.innerHTML = html;

    renderQuadrant(prioridades);
  }

  // Quadrante esforço × retorno: X = incidência (o quanto a banca cobra),
  // Y = domínio (o quanto você sabe). Foco imediato = alta incidência + baixo domínio.
  var chartQuadrant = null;
  function renderQuadrant(prioridades) {
    var container = document.getElementById('quadrant-chart-container');
    var canvas = document.getElementById('chart-quadrant');
    if (!canvas) return;

    var pts = (prioridades || []).filter(function(p) {
      return (p.incidencia_score || 0) > 0 || (p.mastery_level || 0) > 0;
    });
    if (!pts.length) {
      if (container) container.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>Sem dados suficientes</p></div>';
      canvas.style.display = 'none';
      return;
    }

    var dados = pts.slice(0, 40).map(function(p) {
      return {
        x: p.incidencia_score || 0,
        y: p.mastery_level || 0,
        label: (p.materia || '') + ' › ' + (p.topico || ''),
        rec: p.recomendacao
      };
    });
    var cores = dados.map(function(d) {
      // Alta incidência (x>=50) + baixo domínio (y<50) → vermelho (foco).
      if (d.x >= 50 && d.y < 50) return '#f38ba8';
      if (d.x >= 50) return '#f9e2af';
      return '#89b4fa';
    });

    if (container) container.style.display = 'none';
    canvas.style.display = 'block';
    if (chartQuadrant) chartQuadrant.destroy();

    chartQuadrant = new Chart(canvas, {
      type: 'scatter',
      data: { datasets: [{ data: dados, backgroundColor: cores, pointRadius: 6, pointHoverRadius: 9 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                var d = ctx.raw;
                return d.label + ' — incidência ' + Math.round(d.x) + ', domínio ' + Math.round(d.y) + '%';
              }
            }
          }
        },
        scales: {
          x: { title: { display: true, text: 'Incidência na banca →', color: '#a6adc8' }, min: 0, max: 100, ticks: { color: '#a6adc8' }, grid: { color: 'rgba(69,71,90,0.3)' } },
          y: { title: { display: true, text: 'Seu domínio →', color: '#a6adc8' }, min: 0, max: 100, ticks: { color: '#a6adc8' }, grid: { color: 'rgba(69,71,90,0.3)' } }
        }
      }
    });
  }

  // ==================== Insights acionáveis ====================
  async function loadInsights() {
    var container = document.getElementById('insights-container');
    if (!container) return;
    try {
      var banca = filterBanca.value;
      var data = await fetchJSON('/api/analytics/raio-x/insights?banca=' + encodeURIComponent(banca));
      var insights = data.insights || [];
      if (!insights.length) {
        container.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>Sem alertas.</p></div>';
        return;
      }
      var cor = { alta: 'var(--red)', media: 'var(--yellow)', baixa: 'var(--green)' };
      container.innerHTML = insights.map(function(i) {
        var borda = cor[i.prioridade] || 'var(--border)';
        // Converte **negrito** simples em <strong>.
        var txt = escapeHtml(i.texto).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        return '<div style="border-left:3px solid ' + borda + ';padding:8px 12px;margin-bottom:8px;background:var(--bg);border-radius:6px;font-size:0.88rem;color:var(--text);">' + txt + '</div>';
      }).join('');
    } catch (e) {
      container.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div><p>Erro ao carregar insights</p></div>';
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  // ==================== Event Listeners ====================

  filterBanca.addEventListener('change', function() {
    loadRaioX();
    loadPrioridades();
    loadInsights();
  });

  filterMateria.addEventListener('change', function() {
    loadRaioX();
  });

  // ==================== Init ====================

  async function init() {
    var initialData = await loadFilters();
    if (initialData) {
      renderTopicsChart(initialData.topicos || []);
      renderMateriasFromAnalytics(initialData.materias || []);
    }
    loadBancas();
    loadPrioridades();
    loadBalance();
    loadInsights();
  }

  init();
})();
