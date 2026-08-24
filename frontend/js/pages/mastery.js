/**
 * Mastery Page — Domínio do Edital
 * ConcurseiroOS
 */
import { showToast } from '../modules/toast.js';

// Expose showToast globally for legacy usage
window.showToast = showToast;

(function() {
  'use strict';

  // State
  let currentData = null;
  let editais = [];
  let cargos = [];

  // DOM refs
  const filterEdital = document.getElementById('filter-edital');
  const filterCargo = document.getElementById('filter-cargo');
  const btnRecalcular = document.getElementById('btn-recalcular');
  const container = document.getElementById('materia-container');
  const loadingState = document.getElementById('loading-state');

  // Utilities
  function getMasteryColor(level) {
    if (level <= 20) return '#f38ba8';
    if (level <= 50) return '#f9e2af';
    if (level <= 80) return '#89b4fa';
    return '#a6e3a1';
  }

  function getMasteryBadgeClass(level) {
    if (level <= 20) return 'badge-red';
    if (level <= 50) return 'badge-yellow';
    if (level <= 80) return 'badge-blue';
    return 'badge-green';
  }

  function getMasteryLabel(level) {
    if (level <= 20) return 'Não Dominado';
    if (level <= 50) return 'Em Progresso';
    if (level <= 80) return 'Dominado';
    return 'Consolidado';
  }

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    var d = new Date(dateStr);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' });
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  // Fetch data
  function fetchMastery() {
    var editalNome = filterEdital.value;
    var cargo = filterCargo.value;

    // Auto-select favorito on first load (same as countdown/treinador)
    if (!editalNome && !cargo && !fetchMastery._loaded) {
      var favorito = localStorage.getItem('countdown_favorito') || '';
      if (favorito) {
        var parts = favorito.split('|');
        if (parts[0]) editalNome = parts[0];
        if (parts[1]) cargo = parts[1];
        // Set dropdown values (will be populated later, but param goes to API)
        filterEdital.value = editalNome;
        filterCargo.value = cargo;
      }
      fetchMastery._loaded = true;
    }

    var params = new URLSearchParams();
    if (editalNome) params.set('edital_nome', editalNome);
    if (cargo) params.set('cargo', cargo);

    loadingState.style.display = 'block';
    container.querySelectorAll('.materia-card').forEach(function(el) { el.remove(); });

    fetch('/api/edital/mastery-overview?' + params.toString())
      .then(function(r) {
        if (!r.ok) throw new Error('Erro ' + r.status);
        return r.json();
      })
      .then(function(data) {
        currentData = data;
        loadingState.style.display = 'none';
        renderSummary(data.materias || []);
        renderMaterias(data.materias || []);
        extractFilters(data.materias || []);
      })
      .catch(function(err) {
        loadingState.style.display = 'none';
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><p>Erro ao carregar dados: ' + escapeHtml(err.message) + '</p></div>';
      });
  }

  // Extract unique editais/cargos for filters (from first load only)
  function extractFilters(materias) {
    var favorito = localStorage.getItem('countdown_favorito') || '';
    var favParts = favorito.split('|');
    var favEdital = favParts[0] || '';
    var favCargo = favParts[1] || '';

    // Only populate on first load if empty
    if (filterEdital.options.length <= 1) {
      fetch('/api/editais')
        .then(function(r) { return r.json(); })
        .then(function(data) {
          var list = Array.isArray(data) ? data : (data.editais || []);
          list.forEach(function(e) {
            var nome = e.nome || e.edital_nome || e;
            if (typeof nome === 'string' && nome) {
              var opt = document.createElement('option');
              opt.value = nome;
              opt.textContent = nome;
              if (nome === favEdital) opt.selected = true;
              filterEdital.appendChild(opt);
            }
          });
        })
        .catch(function() {});

      fetch('/api/editais/cargos')
        .then(function(r) { return r.json(); })
        .then(function(data) {
          var list = Array.isArray(data) ? data : (data.cargos || []);
          list.forEach(function(c) {
            var nome = c.cargo || c.nome || c;
            if (typeof nome === 'string' && nome) {
              var opt = document.createElement('option');
              opt.value = nome;
              opt.textContent = nome;
              if (nome === favCargo) opt.selected = true;
              filterCargo.appendChild(opt);
            }
          });
        })
        .catch(function() {});
    }
  }

  // Render summary
  function renderSummary(materias) {
    var totalTopics = 0;
    var sumMastery = 0;
    var countRed = 0, countYellow = 0, countBlue = 0, countGreen = 0;

    materias.forEach(function(m) {
      var topics = m.topics || [];
      totalTopics += topics.length;
      topics.forEach(function(t) {
        var lvl = t.mastery_level || 0;
        sumMastery += lvl;
        if (lvl <= 20) countRed++;
        else if (lvl <= 50) countYellow++;
        else if (lvl <= 80) countBlue++;
        else countGreen++;
      });
    });

    var avgMastery = totalTopics > 0 ? Math.round(sumMastery / totalTopics) : 0;

    document.getElementById('sum-topics').textContent = totalTopics;
    document.getElementById('sum-avg').textContent = avgMastery + '%';
    document.getElementById('sum-red').textContent = countRed;
    document.getElementById('sum-yellow').textContent = countYellow;
    document.getElementById('sum-blue').textContent = countBlue;
    document.getElementById('sum-green').textContent = countGreen;
  }

  // Render matérias
  function renderMaterias(materias) {
    if (!materias || materias.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><p>Nenhuma matéria encontrada. Selecione um edital ou cadastre tópicos.</p></div>';
      return;
    }

    var fragment = document.createDocumentFragment();

    materias.forEach(function(m, idx) {
      var card = document.createElement('div');
      card.className = 'materia-card';
      card.setAttribute('data-idx', idx);

      var avg = Math.round(m.avg_mastery || 0);
      var color = getMasteryColor(avg);
      var topicCount = (m.topics || []).length;

      // Header
      var header = document.createElement('div');
      header.className = 'materia-header';
      header.setAttribute('role', 'button');
      header.setAttribute('aria-expanded', 'false');
      header.setAttribute('tabindex', '0');
      header.innerHTML =
        '<span class="materia-expand-icon">▶</span>' +
        '<div class="materia-info">' +
          '<div class="materia-name">' + escapeHtml(m.materia) + '</div>' +
          '<div class="materia-meta">' + topicCount + ' tópico' + (topicCount !== 1 ? 's' : '') + ' • ' + escapeHtml(m.avg_mastery_label || getMasteryLabel(avg)) + '</div>' +
        '</div>' +
        '<div class="materia-progress-wrap">' +
          '<div class="progress-bar-container">' +
            '<div class="progress-bar-fill" style="width:' + avg + '%;background:' + color + '"></div>' +
          '</div>' +
          '<div class="materia-pct" style="color:' + color + '">' + avg + '%</div>' +
        '</div>';

      header.addEventListener('click', function() { toggleMateria(card); });
      header.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggleMateria(card);
        }
      });

      // Topics
      var topicsDiv = document.createElement('div');
      topicsDiv.className = 'materia-topics';

      (m.topics || []).forEach(function(t) {
        var tLvl = Math.round(t.mastery_level || 0);
        var tColor = getMasteryColor(tLvl);
        var tBadge = getMasteryBadgeClass(tLvl);

        var row = document.createElement('div');
        row.className = 'topic-row';
        row.innerHTML =
          '<div class="topic-name" title="' + escapeHtml(t.topico) + '">' + escapeHtml(t.topico) + '</div>' +
          '<div class="topic-progress-wrap">' +
            '<div class="progress-bar-container">' +
              '<div class="progress-bar-fill" style="width:' + tLvl + '%;background:' + tColor + '"></div>' +
            '</div>' +
          '</div>' +
          '<span class="topic-badge ' + tBadge + '">' + escapeHtml(t.mastery_label || getMasteryLabel(tLvl)) + '</span>' +
          '<span class="topic-date">' + formatDate(t.mastery_updated_at) + '</span>';
        topicsDiv.appendChild(row);
      });

      card.appendChild(header);
      card.appendChild(topicsDiv);
      fragment.appendChild(card);
    });

    // Remove old content and append
    container.querySelectorAll('.materia-card, .empty-state').forEach(function(el) { el.remove(); });
    container.appendChild(fragment);
  }

  // Toggle expand/collapse
  function toggleMateria(card) {
    var isExpanded = card.classList.contains('expanded');
    card.classList.toggle('expanded');
    var header = card.querySelector('.materia-header');
    header.setAttribute('aria-expanded', !isExpanded ? 'true' : 'false');
  }

  // Recalculate
  btnRecalcular.addEventListener('click', function() {
    btnRecalcular.disabled = true;
    btnRecalcular.textContent = '⏳ Recalculando...';

    fetch('/api/edital/mastery/recalculate', { method: 'POST' })
      .then(function(r) {
        if (!r.ok) throw new Error('Erro ' + r.status);
        return r.json();
      })
      .then(function() {
        showToast('Mastery recalculado com sucesso!', 'success');
        fetchMastery();
      })
      .catch(function(err) {
        showToast('Erro ao recalcular: ' + err.message, 'error');
      })
      .finally(function() {
        btnRecalcular.disabled = false;
        btnRecalcular.textContent = '🔄 Recalcular';
      });
  });

  // Filter change
  filterEdital.addEventListener('change', fetchMastery);
  filterCargo.addEventListener('change', fetchMastery);

  // Init
  fetchMastery();
})();
