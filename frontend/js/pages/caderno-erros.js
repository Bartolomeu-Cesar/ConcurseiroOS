// caderno-erros.js — ES module extracted from caderno-erros.html

const API_BASE = '';
let dadosCaderno = null;
let revisadasHoje = new Set();
let filtroMateria = '';

async function fetchCaderno() {
  try {
    const res = await fetch(`${API_BASE}/api/questoes/erros/caderno`);
    if (!res.ok) throw new Error('Erro ao carregar caderno');
    const raw = await res.json();
    // Handle both old format (array) and new format (object)
    if (Array.isArray(raw)) {
      dadosCaderno = { pendentes_hoje: raw, total_erros: raw.length, por_materia: {}, padroes_erro: [] };
    } else {
      dadosCaderno = raw;
    }
    renderAll();
  } catch (err) {
    document.getElementById('lista-revisao').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <p>Erro ao carregar caderno de erros: ${err.message}</p>
      </div>`;
  }
}

function renderAll() {
  if (!dadosCaderno) return;

  const { pendentes_hoje, total_erros, por_materia, padroes_erro } = dadosCaderno;

  // Badge & stats
  document.getElementById('total-badge').textContent = pendentes_hoje.length;
  document.getElementById('stat-total').textContent = total_erros;
  document.getElementById('stat-pendentes').textContent = pendentes_hoje.length;
  document.getElementById('stat-materias').textContent = Object.keys(por_materia).length;
  document.getElementById('stat-padroes').textContent = padroes_erro.length;

  // Progress
  updateProgress();

  // Matérias chips
  renderMateriasChips(por_materia);

  // Questões
  renderRevisao(pendentes_hoje);

  // Padrões
  renderPadroes(padroes_erro);
}

function updateProgress() {
  const total = dadosCaderno.pendentes_hoje.length;
  const done = revisadasHoje.size;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const section = document.getElementById('progress-section');
  section.style.display = total > 0 ? 'block' : 'none';
  document.getElementById('progress-text').textContent = `${done}/${total} revisadas hoje`;
  document.getElementById('progress-pct').textContent = `${pct}%`;
  document.getElementById('progress-fill').style.width = `${pct}%`;
}

function renderMateriasChips(por_materia) {
  const container = document.getElementById('materias-chips');
  const sorted = Object.entries(por_materia).sort((a, b) => b[1] - a[1]);

  let html = `<button class="materia-chip ${!filtroMateria ? 'active' : ''}" onclick="setFiltroMateria('')">Todas</button>`;
  for (const [mat, count] of sorted) {
    const active = filtroMateria === mat ? 'active' : '';
    html += `<button class="materia-chip ${active}" onclick="setFiltroMateria('${mat.replace(/'/g, "\\'")}')">${mat} (${count})</button>`;
  }
  container.innerHTML = html;
}

window.setFiltroMateria = function(mat) {
  filtroMateria = mat;
  renderAll();
};

function renderRevisao(pendentes) {
  const container = document.getElementById('lista-revisao');
  let filtered = pendentes;

  if (filtroMateria) {
    filtered = filtered.filter(q => q.materia === filtroMateria);
  }

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🎉</div>
        <p>${filtroMateria ? 'Nenhuma revisão pendente nesta matéria!' : 'Nenhuma revisão pendente hoje! Volte amanhã.'}</p>
      </div>`;
    return;
  }

  let html = '';
  for (const q of filtered) {
    const revisada = revisadasHoje.has(q.id);
    const intervalos = ['1d', '3d', '7d', '14d', '30d'];
    const intervaloIdx = [1, 3, 7, 14, 30].indexOf(q.intervalo_atual);
    const intervaloLabel = intervaloIdx >= 0 ? intervalos[intervaloIdx] : '1d';

    html += `
      <div class="question-card" id="card-${q.id}" style="${revisada ? 'opacity:0.5;' : ''}">
        <div class="question-meta">
          <span class="tag tag-materia">${q.materia || 'Sem matéria'}</span>
          ${q.topico ? `<span class="tag">${q.topico}</span>` : ''}
          <span class="tag tag-intervalo">⏱ ${intervaloLabel}</span>
          <span class="tag">📅 ${q.data || ''}</span>
        </div>
        <div class="question-enunciado">${truncate(q.enunciado, 200)}</div>
        <div class="answers-box">
          <span class="answer-pill answer-wrong">❌ Sua: ${q.resposta_usuario}</span>
          <span class="answer-pill answer-correct">✅ Correta: ${q.resposta_correta}</span>
        </div>
        <div class="question-actions">
          <button class="btn-revisei btn-revisei-errei" onclick="revisar(${q.id}, false)" ${revisada ? 'disabled' : ''}>
            Errei de novo
          </button>
          <button class="btn-revisei btn-revisei-ok" onclick="revisar(${q.id}, true)" ${revisada ? 'disabled' : ''}>
            Revisei ✓
          </button>
        </div>
      </div>`;
  }
  container.innerHTML = html;
}

function renderPadroes(padroes) {
  const container = document.getElementById('lista-padroes');

  let filtered = padroes;
  if (filtroMateria) {
    filtered = filtered.filter(p => p.materia === filtroMateria);
  }

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📊</div>
        <p>Nenhum padrão de erro identificado ainda. Continue praticando!</p>
      </div>`;
    return;
  }

  let html = '';
  for (const p of filtered) {
    html += `
      <div class="padrao-card">
        <div class="padrao-header">
          <span class="padrao-text">${p.padrao}</span>
          <span class="padrao-count">${p.count}x</span>
        </div>
        <div class="padrao-detail">
          ${p.materia} → ${p.topico} | Resposta errada frequente: "${p.resposta_errada}"
        </div>
      </div>`;
  }
  container.innerHTML = html;
}

window.revisar = async function(questaoId, acertou) {
  try {
    const res = await fetch(`${API_BASE}/api/questoes/erros/revisar/${questaoId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acertou })
    });
    if (!res.ok) throw new Error('Erro ao registrar revisão');
    const data = await res.json();

    revisadasHoje.add(questaoId);

    // Visual feedback
    const card = document.getElementById(`card-${questaoId}`);
    if (card) {
      card.style.opacity = '0.5';
      card.querySelectorAll('button').forEach(b => b.disabled = true);
      // Show result toast
      const msg = acertou
        ? `✅ Próxima revisão em ${data.novo_intervalo} dia${data.novo_intervalo > 1 ? 's' : ''}`
        : `🔄 Voltará amanhã para revisão`;
      showToast(msg);
    }

    updateProgress();
  } catch (err) {
    showToast('❌ Erro: ' + err.message);
  }
};

function truncate(text, max) {
  if (!text) return '';
  return text.length > max ? text.substring(0, max) + '...' : text;
}

function showToast(msg) {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; bottom: 24px; right: 24px;
    padding: 12px 20px; border-radius: 10px;
    background: var(--ce-card); color: var(--ce-text);
    font-size: 0.85rem; font-weight: 600;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    z-index: 9999; animation: fadeIn 0.3s ease;
  `;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// Init
fetchCaderno();
