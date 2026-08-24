// questoes.js — extracted from questoes.html inline scripts
// ES module (strict mode by default)

// Tab navigation
document.querySelectorAll('.qtab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.qtab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.qtab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});

// State
let questoesPool = [];
let currentQuestao = null;
let respondida = false;
let questaoStartTime = null;

// Simulado state
let simAtivo = null;
let simQuestoes = [];
let simIndex = 0;
let simTimer = null;
let simStartTime = null;
let simLimite = 0;

// ==================== RESOLVER ====================
async function loadMaterias() {
  const materias = await fetch('/api/questoes/materias').then(r => r.json());
  const selects = ['filtro-materia', 'sim-materia-filtro', 'banco-filtro-materia'];
  selects.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const val = el.value;
    // Keep first option
    while (el.options.length > 1) el.remove(1);
    materias.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m;
      el.appendChild(opt);
    });
    el.value = val;
  });
  // Popular checkboxes do simulado
  const cbContainer = document.getElementById('sim-materias-checkboxes');
  if (cbContainer && materias.length > 0) {
    cbContainer.innerHTML = materias.map(m => `
      <label style="display:flex;align-items:center;gap:6px;font-size:0.8rem;color:#cdd6f4;cursor:pointer;padding:2px 4px;border-radius:4px;" 
             onmouseover="this.style.background='#45475a'" onmouseout="this.style.background='transparent'">
        <input type="checkbox" class="sim-mat-cb" value="${m}" checked style="accent-color:#cba6f7;">
        ${m}
      </label>
    `).join('');
  } else if (cbContainer) {
    cbContainer.innerHTML = '<span style="color:#9399b2;font-size:0.8rem;">Nenhuma disciplina disponível. Adicione questões primeiro.</span>';
  }
}

function simToggleAll(checked) {
  document.querySelectorAll('.sim-mat-cb').forEach(cb => cb.checked = checked);
}
window.simToggleAll = simToggleAll;

function getSimMateriasSelecionadas() {
  const checked = [...document.querySelectorAll('.sim-mat-cb:checked')].map(cb => cb.value);
  return checked;
}

async function loadBancas() {
  try {
    const bancas = await fetch('/api/questoes/bancas').then(r => r.json());
    const el = document.getElementById('filtro-banca');
    if (!el) return;
    while (el.options.length > 1) el.remove(1);
    bancas.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b;
      opt.textContent = b;
      el.appendChild(opt);
    });
  } catch(e) {}
}

async function loadTempoMedio() {
  try {
    const data = await fetch('/api/questoes/stats/tempo').then(r => r.json());
    document.getElementById('tempo-medio-val').textContent = data.tempo_medio_formatado + '/questão';
    const el = document.getElementById('tempo-vs-prova');
    const color = data.analise.seu_tempo_vs_prova === 'dentro_do_limite' ? '#a6e3a1' : '#f38ba8';
    el.innerHTML = `<span style="color:${color};">${data.analise.mensagem}</span>`;
  } catch(e) {}
}

async function loadQuestoesResolver() {
  const materia = document.getElementById('filtro-materia').value;
  const banca = document.getElementById('filtro-banca').value;
  const status = document.getElementById('filtro-status').value;
  let url = '/api/questoes?';
  if (materia) url += `materia=${encodeURIComponent(materia)}&`;
  if (banca) url += `banca=${encodeURIComponent(banca)}&`;
  if (status) url += `status=${encodeURIComponent(status)}&`;
  questoesPool = await fetch(url).then(r => r.json());

  const dificuldade = document.getElementById('filtro-dificuldade').value;
  if (dificuldade) {
    questoesPool = questoesPool.filter(q => q.dificuldade === dificuldade);
  }

  if (questoesPool.length === 0) {
    document.getElementById('resolver-area').innerHTML = '<p style="color:#9399b2;">Nenhuma questão encontrada. Cadastre questões na aba "Cadastrar".</p>';
    return;
  }

  // Sortear uma questão aleatória
  const rand = Math.floor(Math.random() * questoesPool.length);
  showQuestao(questoesPool[rand]);
}
window.loadQuestoesResolver = loadQuestoesResolver;

function showQuestao(q) {
  currentQuestao = q;
  respondida = false;
  questaoStartTime = Date.now();

  // Timer visual — limpar anterior e iniciar novo
  if (window._questaoTimerInterval) clearInterval(window._questaoTimerInterval);
  window._questaoTimerInterval = setInterval(() => {
    const el = document.getElementById('questao-timer');
    if (!el || respondida) { clearInterval(window._questaoTimerInterval); return; }
    const seg = Math.round((Date.now() - questaoStartTime) / 1000);
    const min = Math.floor(seg / 60);
    const s = String(seg % 60).padStart(2, '0');
    el.textContent = `⏱ ${min}:${s}`;
    // Indicar se está demorando
    if (seg > 120) el.style.color = '#f38ba8';
    else if (seg > 60) el.style.color = '#f9e2af';
    else el.style.color = '#89b4fa';
  }, 1000);

  const area = document.getElementById('resolver-area');

  const isCertoErrado = !q.alternativa_c && !q.alternativa_d;
  const alternativas = isCertoErrado
    ? [{ letter: 'A', text: 'CERTO' }, { letter: 'B', text: 'ERRADO' }]
    : [
        { letter: 'A', text: q.alternativa_a },
        { letter: 'B', text: q.alternativa_b },
        { letter: 'C', text: q.alternativa_c },
        { letter: 'D', text: q.alternativa_d },
        ...(q.alternativa_e ? [{ letter: 'E', text: q.alternativa_e }] : []),
      ];

  const altsHtml = isCertoErrado
    ? `<div style="display:flex;gap:16px;justify-content:center;max-width:280px;margin:0 auto;">
        <div class="alternativa ce-btn" data-letter="A" onclick="selecionarAlternativa(this, 'A')" style="flex:1;text-align:center;padding:10px 16px;border:2px solid #a6e3a1;border-radius:8px;cursor:pointer;font-weight:700;font-size:0.85rem;color:#a6e3a1;">✓ CERTO</div>
        <div class="alternativa ce-btn" data-letter="B" onclick="selecionarAlternativa(this, 'B')" style="flex:1;text-align:center;padding:10px 16px;border:2px solid #f38ba8;border-radius:8px;cursor:pointer;font-weight:700;font-size:0.85rem;color:#f38ba8;">✗ ERRADO</div>
      </div>`
    : alternativas.map(a => `
        <div class="alternativa" data-letter="${a.letter}" onclick="selecionarAlternativa(this, '${a.letter}')">
          <span class="alt-letter">${a.letter})</span>
          <span class="alt-text">${a.text}</span>
        </div>
      `).join('');

  area.innerHTML = `
    <div class="questao-card">
      <div class="questao-meta">
        <span>${q.materia}</span>
        ${q.topico ? `<span>${q.topico}</span>` : ''}
        <span>${q.dificuldade}</span>
        <span id="questao-timer" style="margin-left:auto;font-family:monospace;font-size:0.85rem;color:#89b4fa;font-weight:600;">⏱ 0:00</span>
      </div>
      <div class="questao-enunciado">${isCertoErrado ? '<span style="color:#89b4fa;font-weight:600;">Julgue o item:</span> ' : ''}${q.enunciado}</div>
      <div class="questao-alternativas">
        ${altsHtml}
      </div>
      <div style="margin-top:12px;display:flex;gap:8px;">
        <button class="btn btn-success" id="btn-confirmar" onclick="confirmarResposta()">Confirmar Resposta</button>
        <button class="btn btn-primary" id="btn-proxima" style="display:none;" onclick="loadQuestoesResolver()">Próxima →</button>
      </div>
      <div class="explicacao-box" id="explicacao-box">
        <strong>Explicação:</strong> ${q.explicacao || 'Sem explicação cadastrada.'}
      </div>
    </div>
  `;
}

function selecionarAlternativa(el, letter) {
  if (respondida) return;
  document.querySelectorAll('.alternativa').forEach(a => a.classList.remove('selected'));
  el.classList.add('selected');
}
window.selecionarAlternativa = selecionarAlternativa;

async function confirmarResposta() {
  if (respondida) return;
  const selected = document.querySelector('.alternativa.selected');
  if (!selected) { alert('Selecione uma alternativa.'); return; }

  const letra = selected.dataset.letter;
  const tempoSegundos = questaoStartTime ? Math.round((Date.now() - questaoStartTime) / 1000) : 0;
  const res = await fetch(`/api/questoes/${currentQuestao.id}/responder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resposta: letra, tempo_segundos: tempoSegundos })
  }).then(r => r.json());

  respondida = true;

  // Marcar correta/errada
  document.querySelectorAll('.alternativa').forEach(a => {
    if (a.dataset.letter === res.resposta_correta) a.classList.add('correct');
    if (a.dataset.letter === letra && !res.acertou) a.classList.add('wrong');
  });

  document.getElementById('explicacao-box').classList.add('show');
  document.getElementById('btn-confirmar').style.display = 'none';
  document.getElementById('btn-proxima').style.display = 'inline-block';

  loadStats();
}
window.confirmarResposta = confirmarResposta;

async function loadStats() {
  const stats = await fetch('/api/questoes/stats/geral').then(r => r.json());
  const grid = document.getElementById('stats-grid');
  grid.innerHTML = `
    <div class="stat-card"><div class="stat-num" style="color:#89b4fa">${stats.total_resolvidas}</div><div class="stat-lbl">Resolvidas</div></div>
    <div class="stat-card"><div class="stat-num" style="color:#a6e3a1">${stats.total_acertos}</div><div class="stat-lbl">Acertos</div></div>
    <div class="stat-card"><div class="stat-num" style="color:#fab387">${stats.percentual}%</div><div class="stat-lbl">Aproveitamento</div></div>
  `;
}

// ==================== SIMULADOS ====================
async function criarSimulado() {
  const titulo = document.getElementById('sim-titulo').value.trim() || `Simulado ${new Date().toLocaleDateString('pt-BR')}`;
  const tempo = parseInt(document.getElementById('sim-tempo').value) || 60;
  const materiasSelecionadas = getSimMateriasSelecionadas();
  const qtd = parseInt(document.getElementById('sim-qtd').value) || 10;

  if (materiasSelecionadas.length === 0) {
    alert('Selecione pelo menos uma disciplina!');
    return;
  }

  // Buscar questões de todas as matérias selecionadas
  let pool = [];
  const todasMaterias = document.querySelectorAll('.sim-mat-cb').length;
  if (materiasSelecionadas.length === todasMaterias) {
    // Todas selecionadas = buscar tudo
    pool = await fetch('/api/questoes').then(r => r.json());
  } else {
    // Buscar por cada matéria selecionada
    for (const mat of materiasSelecionadas) {
      const qs = await fetch(`/api/questoes?materia=${encodeURIComponent(mat)}`).then(r => r.json());
      pool = pool.concat(qs);
    }
  }

  if (pool.length === 0) { alert('Nenhuma questão disponível para as disciplinas selecionadas.'); return; }

  // Shufflar e pegar qtd
  pool = pool.sort(() => Math.random() - 0.5).slice(0, qtd);
  const ids = pool.map(q => q.id);

  const res = await fetch('/api/simulados', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ titulo, tempo_limite_min: tempo, questao_ids: ids })
  }).then(r => r.json());

  // Iniciar simulado
  iniciarSimulado(res.id);
}
window.criarSimulado = criarSimulado;

async function iniciarSimulado(id) {
  const data = await fetch(`/api/simulados/${id}`).then(r => r.json());
  simAtivo = data.simulado;
  simQuestoes = data.questoes;
  simIndex = 0;
  simLimite = simAtivo.tempo_limite_min * 60;
  simStartTime = Date.now();

  document.getElementById('simulado-ativo-panel').style.display = 'block';
  clearInterval(simTimer);
  simTimer = setInterval(updateSimTimer, 1000);

  showSimQuestao();
}
window.iniciarSimulado = iniciarSimulado;

function updateSimTimer() {
  const elapsed = Math.floor((Date.now() - simStartTime) / 1000);
  const remaining = Math.max(0, simLimite - elapsed);
  const h = String(Math.floor(remaining / 3600)).padStart(2, '0');
  const m = String(Math.floor((remaining % 3600) / 60)).padStart(2, '0');
  const s = String(remaining % 60).padStart(2, '0');
  const el = document.getElementById('sim-timer');
  el.textContent = `${h}:${m}:${s}`;
  el.className = 'sim-timer' + (remaining < 300 ? ' danger' : remaining < 600 ? ' warning' : '');

  if (remaining <= 0) {
    finalizarSimulado();
  }
}

function showSimQuestao() {
  const q = simQuestoes[simIndex];
  document.getElementById('sim-progress').textContent = `Questão ${simIndex + 1} de ${simQuestoes.length}`;

  const isCertoErrado = !q.alternativa_c && !q.alternativa_d;
  const alternativas = isCertoErrado
    ? [{ letter: 'A', text: 'CERTO' }, { letter: 'B', text: 'ERRADO' }]
    : [
        { letter: 'A', text: q.alternativa_a },
        { letter: 'B', text: q.alternativa_b },
        { letter: 'C', text: q.alternativa_c },
        { letter: 'D', text: q.alternativa_d },
        ...(q.alternativa_e ? [{ letter: 'E', text: q.alternativa_e }] : []),
      ];

  const selected = q.resposta_usuario || '';
  const altsHtml = isCertoErrado
    ? `<div style="display:flex;gap:16px;justify-content:center;max-width:280px;margin:0 auto;">
        <div class="alternativa ce-btn ${selected === 'A' ? 'selected' : ''}" data-letter="A" onclick="simSelectAlt(this, 'A')" style="flex:1;text-align:center;padding:10px 16px;border:2px solid #a6e3a1;border-radius:8px;cursor:pointer;font-weight:700;font-size:0.85rem;color:#a6e3a1;">✓ CERTO</div>
        <div class="alternativa ce-btn ${selected === 'B' ? 'selected' : ''}" data-letter="B" onclick="simSelectAlt(this, 'B')" style="flex:1;text-align:center;padding:10px 16px;border:2px solid #f38ba8;border-radius:8px;cursor:pointer;font-weight:700;font-size:0.85rem;color:#f38ba8;">✗ ERRADO</div>
      </div>`
    : alternativas.map(a => `
        <div class="alternativa ${selected === a.letter ? 'selected' : ''}" data-letter="${a.letter}" onclick="simSelectAlt(this, '${a.letter}')">
          <span class="alt-letter">${a.letter})</span>
            <span class="alt-text">${a.text}</span>
          </div>
        `).join('');

  document.getElementById('sim-questao-area').innerHTML = `
    <div class="questao-card">
      <div class="questao-meta"><span>${q.materia}</span></div>
      <div class="questao-enunciado">${isCertoErrado ? '<span style="color:#89b4fa;font-weight:600;">Julgue o item:</span> ' : ''}${q.enunciado}</div>
      <div class="questao-alternativas">
        ${altsHtml}
      </div>
    </div>
  `;

  document.getElementById('sim-prev-btn').disabled = simIndex === 0;
  document.getElementById('sim-next-btn').textContent = simIndex === simQuestoes.length - 1 ? 'Finalizar →' : 'Próxima →';
}

async function simSelectAlt(el, letter) {
  document.querySelectorAll('#sim-questao-area .alternativa').forEach(a => a.classList.remove('selected'));
  el.classList.add('selected');

  simQuestoes[simIndex].resposta_usuario = letter;

  await fetch(`/api/simulados/${simAtivo.id}/responder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ questao_id: simQuestoes[simIndex].questao_id, resposta: letter })
  });
}
window.simSelectAlt = simSelectAlt;

function simNext() {
  if (simIndex < simQuestoes.length - 1) {
    simIndex++;
    showSimQuestao();
  } else {
    finalizarSimulado();
  }
}
window.simNext = simNext;

function simPrev() {
  if (simIndex > 0) {
    simIndex--;
    showSimQuestao();
  }
}
window.simPrev = simPrev;

async function finalizarSimulado() {
  clearInterval(simTimer);
  const tempo = Math.floor((Date.now() - simStartTime) / 1000);

  const res = await fetch(`/api/simulados/${simAtivo.id}/finalizar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tempo_gasto_seg: tempo })
  }).then(r => r.json());

  document.getElementById('simulado-ativo-panel').style.display = 'none';
  alert(`Simulado finalizado!\nNota: ${res.nota}%\nAcertos: ${res.acertos}/${res.total}`);
  simAtivo = null;
  loadSimulados();
}
window.finalizarSimulado = finalizarSimulado;

async function loadSimulados() {
  const sims = await fetch('/api/simulados').then(r => r.json());
  const list = document.getElementById('simulados-list');
  if (sims.length === 0) {
    list.innerHTML = '<p style="color:#9399b2;font-size:0.85rem;">Nenhum simulado realizado ainda.</p>';
    return;
  }
  list.innerHTML = sims.map(s => `
    <div class="sim-card">
      <span class="sim-title">${s.titulo}</span>
      <span class="sim-status ${s.status}">${s.status}</span>
      ${s.status === 'finalizado' ? `<span class="sim-nota">${s.nota}%</span>` : `<button class="btn btn-primary" style="font-size:0.78rem;padding:4px 10px;" onclick="iniciarSimulado(${s.id})">Continuar</button>`}
      <button class="btn btn-secondary" style="font-size:0.78rem;padding:4px 8px;" onclick="deleteSimulado(${s.id})">🗑</button>
    </div>
  `).join('');
}

async function deleteSimulado(id) {
  if (!confirm('Excluir este simulado?')) return;
  await fetch(`/api/simulados/${id}`, { method: 'DELETE' });
  loadSimulados();
}
window.deleteSimulado = deleteSimulado;

// ==================== CADERNO DE ERROS ====================
async function loadErros() {
  const erros = await fetch('/api/questoes/erros/caderno').then(r => r.json());
  const list = document.getElementById('erros-list');
  if (erros.length === 0) {
    list.innerHTML = '<p style="color:#9399b2;font-size:0.85rem;">Nenhum erro registrado. Continue resolvendo questões!</p>';
    return;
  }

  // Agrupar por matéria
  const grouped = {};
  erros.forEach(e => {
    if (!grouped[e.materia]) grouped[e.materia] = [];
    grouped[e.materia].push(e);
  });

  let html = '';
  const materias = Object.keys(grouped).sort();
  for (const materia of materias) {
    const items = grouped[materia];
    html += `<div class="acc-group">
      <div class="acc-header" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">
        <span class="acc-chevron">▶</span>
        <span class="acc-name">${materia}</span>
        <span class="acc-count">${items.length} erro(s)</span>
      </div>
      <div class="acc-body">`;
    items.forEach(e => {
      html += `
        <div class="erro-item">
          <div class="erro-enunciado">${e.enunciado.substring(0, 150)}${e.enunciado.length > 150 ? '...' : ''}</div>
          <div class="erro-meta">
            <span>Sua: ${e.resposta_usuario}</span>
            <span>Correta: ${e.resposta_correta}</span>
            <span>${e.data}</span>
          </div>
        </div>`;
    });
    html += `</div></div>`;
  }
  list.innerHTML = html;
}

// ==================== IMPORTAR PDF/OCR ====================
async function importarQuestoesPDF() {
  const fileInput = document.getElementById('pdf-import-file');
  const file = fileInput.files[0];
  if (!file) {
    toast('Selecione o PDF da prova primeiro.', 'error');
    return;
  }

  const statusEl = document.getElementById('pdf-import-status');
  statusEl.style.display = 'block';
  statusEl.style.background = '#45475a';
  statusEl.style.color = '#cdd6f4';
  statusEl.innerHTML = '⏳ Processando PDF... (isso pode levar alguns segundos para OCR)';

  const materia = document.getElementById('pdf-import-materia').value.trim();
  const banca = document.getElementById('pdf-import-banca').value.trim();

  const formData = new FormData();
  formData.append('file', file);

  // Adicionar gabarito separado se fornecido
  const gabInput = document.getElementById('pdf-import-gabarito');
  if (gabInput && gabInput.files[0]) {
    formData.append('gabarito_file', gabInput.files[0]);
  }

  let url = '/api/questoes/importar-pdf';
  const params = [];
  if (materia) params.push(`materia=${encodeURIComponent(materia)}`);
  if (banca) params.push(`banca=${encodeURIComponent(banca)}`);
  if (params.length) url += '?' + params.join('&');

  try {
    const res = await fetch(url, { method: 'POST', body: formData });
    const data = await res.json();

    if (data.ok) {
      statusEl.style.background = '#1e3a2e';
      statusEl.style.color = '#a6e3a1';
      statusEl.innerHTML = `✅ ${data.mensagem}<br><small>Detectadas: ${data.total_detectadas} | Importadas: ${data.importadas}${data.sem_gabarito ? ' | Sem gabarito: ' + data.sem_gabarito : ''}</small>`;
      // Recarregar banco
      if (typeof loadBanco === 'function') loadBanco();
      if (typeof loadMaterias === 'function') loadMaterias();
    } else {
      statusEl.style.background = '#3a1e1e';
      statusEl.style.color = '#f38ba8';
      let msg = `⚠️ ${data.erro || data.detail || 'Erro desconhecido'}`;
      if (data.dica) msg += `<br><small>${data.dica}</small>`;
      if (data.texto_extraido_preview) {
        msg += `<br><details style="margin-top:6px;"><summary style="cursor:pointer;font-size:0.75rem;">Ver texto extraído (preview)</summary><pre style="font-size:0.7rem;max-height:200px;overflow:auto;white-space:pre-wrap;margin-top:4px;padding:6px;background:#1e1e2e;border-radius:4px;">${data.texto_extraido_preview}</pre></details>`;
      }
      statusEl.innerHTML = msg;
    }
  } catch (e) {
    statusEl.style.background = '#3a1e1e';
    statusEl.style.color = '#f38ba8';
    statusEl.innerHTML = `❌ Erro: ${e.message}`;
  }

  // Limpar input
  input.value = '';
}
window.importarQuestoesPDF = importarQuestoesPDF;

async function aplicarGabaritoPDF() {
  const gabInput = document.getElementById('pdf-import-gabarito');
  const file = gabInput?.files[0];
  if (!file) {
    toast('Selecione o PDF do gabarito primeiro.', 'error');
    return;
  }

  // Buscar provas importadas para seleção
  const provasRes = await fetch('/api/questoes/provas').then(r => r.json());
  const provasSemGab = provasRes.filter(p => p.sem_gabarito > 0);

  let provaOrigem = '';
  if (provasSemGab.length === 0) {
    toast('Nenhuma prova sem gabarito encontrada. Importe a prova primeiro.', 'error');
    return;
  } else if (provasSemGab.length === 1) {
    provaOrigem = provasSemGab[0].prova;
  } else {
    // Mostrar modal de seleção
    const options = provasSemGab.map(p => `<option value="${p.prova}">${p.prova} (${p.sem_gabarito} sem gabarito)</option>`).join('');
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;';
    overlay.innerHTML = `
      <div style="background:#313244;border:1px solid #45475a;border-radius:16px;padding:24px;max-width:400px;width:90%;">
        <h3 style="color:#cdd6f4;margin:0 0 12px;">Selecione a prova</h3>
        <p style="color:#a6adc8;font-size:0.82rem;margin:0 0 12px;">Para qual prova este gabarito se aplica?</p>
        <select id="gab-prova-select" style="width:100%;padding:10px;background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;border-radius:8px;font-size:0.9rem;margin-bottom:16px;">
          ${options}
        </select>
        <div style="display:flex;gap:8px;">
          <button id="gab-cancel" style="flex:1;padding:10px;background:#45475a;color:#cdd6f4;border:none;border-radius:8px;cursor:pointer;">Cancelar</button>
          <button id="gab-confirm" style="flex:1;padding:10px;background:#a6e3a1;color:#1e1e2e;border:none;border-radius:8px;cursor:pointer;font-weight:700;">Aplicar</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    provaOrigem = await new Promise(resolve => {
      overlay.querySelector('#gab-cancel').onclick = () => { overlay.remove(); resolve(''); };
      overlay.querySelector('#gab-confirm').onclick = () => { resolve(overlay.querySelector('#gab-prova-select').value); overlay.remove(); };
      overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(''); } };
    });

    if (!provaOrigem) return;
  }

  const statusEl = document.getElementById('pdf-import-status');
  statusEl.style.display = 'block';
  statusEl.style.background = '#45475a';
  statusEl.style.color = '#cdd6f4';
  statusEl.innerHTML = `⏳ Aplicando gabarito em "${provaOrigem}"...`;

  const formData = new FormData();
  formData.append('file', file);

  let url = `/api/questoes/aplicar-gabarito?prova_origem=${encodeURIComponent(provaOrigem)}`;

  try {
    const res = await fetch(url, { method: 'POST', body: formData });
    const data = await res.json();

    if (data.ok) {
      statusEl.style.background = '#1e3a2e';
      statusEl.style.color = '#a6e3a1';
      statusEl.innerHTML = `✅ ${data.mensagem}<br><small>Prova: ${data.prova} | Aplicadas: ${data.aplicadas} | Anuladas: ${data.anuladas || 0}</small>`;
      if (typeof loadBanco === 'function') loadBanco();
    } else {
      statusEl.style.background = '#3a1e1e';
      statusEl.style.color = '#f38ba8';
      statusEl.innerHTML = `❌ ${data.erro || 'Erro ao aplicar gabarito.'}`;
    }
  } catch (e) {
    statusEl.style.background = '#3a1e1e';
    statusEl.style.color = '#f38ba8';
    statusEl.innerHTML = '❌ Erro de conexão.';
  }
}
window.aplicarGabaritoPDF = aplicarGabaritoPDF;

// ==================== CADASTRAR ====================
async function cadastrarQuestao() {
  const materia = document.getElementById('cad-materia').value.trim();
  const enunciado = document.getElementById('cad-enunciado').value.trim();
  const a = document.getElementById('cad-a').value.trim();
  const b = document.getElementById('cad-b').value.trim();
  const c = document.getElementById('cad-c').value.trim();
  const d = document.getElementById('cad-d').value.trim();
  const resposta = document.getElementById('cad-resposta').value;

  if (!materia || !enunciado || !a || !b || !c || !d || !resposta) {
    alert('Preencha todos os campos obrigatórios (*).');
    return;
  }

  await fetch('/api/questoes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      materia,
      topico: document.getElementById('cad-topico').value.trim(),
      enunciado,
      alternativa_a: a,
      alternativa_b: b,
      alternativa_c: c,
      alternativa_d: d,
      alternativa_e: document.getElementById('cad-e').value.trim(),
      resposta_correta: resposta,
      explicacao: document.getElementById('cad-explicacao').value.trim(),
      dificuldade: document.getElementById('cad-dificuldade').value
    })
  });

  alert('Questão cadastrada com sucesso!');
  // Limpar form
  ['cad-materia', 'cad-topico', 'cad-enunciado', 'cad-a', 'cad-b', 'cad-c', 'cad-d', 'cad-e', 'cad-explicacao'].forEach(id => {
    document.getElementById(id).value = '';
  });
  document.getElementById('cad-resposta').value = '';
  loadMaterias();
}
window.cadastrarQuestao = cadastrarQuestao;

// ==================== BANCO COMPLETO ====================
async function loadBanco() {
  const materia = document.getElementById('banco-filtro-materia').value;
  const url = materia ? `/api/questoes?materia=${encodeURIComponent(materia)}` : '/api/questoes';
  const questoes = await fetch(url).then(r => r.json());

  document.getElementById('banco-count').textContent = `${questoes.length} questão(ões)`;
  const list = document.getElementById('banco-list');

  if (questoes.length === 0) {
    list.innerHTML = '<p style="color:#9399b2;font-size:0.85rem;">Nenhuma questão cadastrada.</p>';
    return;
  }

  // Agrupar por matéria
  const grouped = {};
  questoes.forEach(q => {
    if (!grouped[q.materia]) grouped[q.materia] = [];
    grouped[q.materia].push(q);
  });

  const materias = Object.keys(grouped).sort();
  let html = '';
  for (const mat of materias) {
    const items = grouped[mat];
    html += `<div class="acc-group">
      <div class="acc-header" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">
        <span class="acc-chevron">▶</span>
        <span class="acc-name">${mat}</span>
        <span class="acc-count">${items.length} questão(ões)</span>
      </div>
      <div class="acc-body">`;
    items.forEach(q => {
      html += `<div class="q-list-item">
        <span class="q-list-text">${q.enunciado.substring(0, 100)}${q.enunciado.length > 100 ? '...' : ''}</span>
        <span class="q-list-meta" style="font-size:0.7rem;color:#9399b2;margin-left:4px;">${q.banca || ''} · ${q.dificuldade || ''}</span>
        <button class="q-list-edit" onclick="editQuestao(${q.id})" title="Editar" style="background:none;border:none;color:#89b4fa;cursor:pointer;font-size:1rem;margin-right:4px;">✏️</button>
        <button class="q-list-delete" onclick="deleteQuestao(${q.id})" title="Excluir">🗑</button>
      </div>`;
    });
    html += `</div></div>`;
  }
  list.innerHTML = html;
}
window.loadBanco = loadBanco;

async function deleteQuestao(id) {
  if (!confirm('Excluir esta questão?')) return;
  await fetch(`/api/questoes/${id}`, { method: 'DELETE' });
  loadBanco();
  loadMaterias();
}
window.deleteQuestao = deleteQuestao;

async function editQuestao(id) {
  // Buscar dados da questão
  const all = await fetch('/api/questoes?limit=9999').then(r => r.json());
  const q = all.find(x => x.id === id);
  if (!q) { alert('Questão não encontrada'); return; }

  // Buscar disciplinas do edital para o select
  let materias = [];
  try { materias = await fetch('/api/edital/materias-disponiveis').then(r => r.json()); } catch(e) {}

  const overlay = document.createElement('div');
  overlay.id = 'edit-questao-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;overflow-y:auto;';
  overlay.innerHTML = `
    <div style="background:#313244;border-radius:16px;padding:24px;max-width:550px;width:100%;max-height:90vh;overflow-y:auto;">
      <h3 style="color:#cba6f7;margin:0 0 16px;">✏️ Editar Questão #${id}</h3>
      <div style="margin-bottom:10px;">
        <label style="font-size:0.8rem;color:#9399b2;">📚 Disciplina</label>
        <select id="eq-materia" style="width:100%;padding:8px;border-radius:8px;border:1px solid #45475a;background:#1e1e2e;color:#cdd6f4;margin-top:4px;">
          <option value="">Sem disciplina</option>
          ${materias.map(m => `<option value="${m}" ${m === q.materia ? 'selected' : ''}>${m}</option>`).join('')}
          ${q.materia && !materias.includes(q.materia) ? `<option value="${q.materia}" selected>${q.materia}</option>` : ''}
        </select>
      </div>
      <div style="margin-bottom:10px;">
        <label style="font-size:0.8rem;color:#9399b2;">📝 Tópico</label>
        <input id="eq-topico" value="${q.topico || ''}" style="width:100%;padding:8px;border-radius:8px;border:1px solid #45475a;background:#1e1e2e;color:#cdd6f4;margin-top:4px;">
      </div>
      <div style="display:flex;gap:8px;margin-bottom:10px;">
        <div style="flex:1;">
          <label style="font-size:0.8rem;color:#9399b2;">🏛️ Banca</label>
          <input id="eq-banca" value="${q.banca || ''}" style="width:100%;padding:8px;border-radius:8px;border:1px solid #45475a;background:#1e1e2e;color:#cdd6f4;margin-top:4px;">
        </div>
        <div style="flex:1;">
          <label style="font-size:0.8rem;color:#9399b2;">⚡ Dificuldade</label>
          <select id="eq-dificuldade" style="width:100%;padding:8px;border-radius:8px;border:1px solid #45475a;background:#1e1e2e;color:#cdd6f4;margin-top:4px;">
            <option value="Fácil" ${q.dificuldade === 'Fácil' ? 'selected' : ''}>Fácil</option>
            <option value="Médio" ${q.dificuldade === 'Médio' ? 'selected' : ''}>Médio</option>
            <option value="Difícil" ${q.dificuldade === 'Difícil' ? 'selected' : ''}>Difícil</option>
          </select>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:10px;">
        <div style="flex:1;">
          <label style="font-size:0.8rem;color:#9399b2;">✅ Resposta Correta</label>
          <select id="eq-resposta" style="width:100%;padding:8px;border-radius:8px;border:1px solid #45475a;background:#1e1e2e;color:#cdd6f4;margin-top:4px;">
            ${['A','B','C','D','E'].map(l => `<option value="${l}" ${q.resposta_correta === l ? 'selected' : ''}>${l}</option>`).join('')}
          </select>
        </div>
      </div>
      <div style="margin-bottom:10px;">
        <label style="font-size:0.8rem;color:#9399b2;">💡 Explicação</label>
        <textarea id="eq-explicacao" rows="3" style="width:100%;padding:8px;border-radius:8px;border:1px solid #45475a;background:#1e1e2e;color:#cdd6f4;margin-top:4px;resize:vertical;">${q.explicacao || ''}</textarea>
      </div>
      <div style="display:flex;gap:8px;margin-top:16px;">
        <button onclick="document.getElementById('edit-questao-modal').remove()" style="flex:1;padding:10px;background:#45475a;color:#cdd6f4;border:none;border-radius:8px;cursor:pointer;">Cancelar</button>
        <button onclick="saveQuestaoEdit(${id})" style="flex:1;padding:10px;background:#a6e3a1;color:#1e1e2e;border:none;border-radius:8px;font-weight:600;cursor:pointer;">💾 Salvar</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}
window.editQuestao = editQuestao;

async function saveQuestaoEdit(id) {
  const body = {
    materia: document.getElementById('eq-materia').value,
    topico: document.getElementById('eq-topico').value.trim(),
    banca: document.getElementById('eq-banca').value.trim(),
    dificuldade: document.getElementById('eq-dificuldade').value,
    resposta_correta: document.getElementById('eq-resposta').value,
    explicacao: document.getElementById('eq-explicacao').value.trim(),
  };
  try {
    const res = await fetch(`/api/questoes/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (res.ok) {
      document.getElementById('edit-questao-modal').remove();
      alert('Questão atualizada!');
      loadBanco();
    } else {
      const err = await res.json();
      alert('Erro: ' + (err.detail || 'desconhecido'));
    }
  } catch(e) { alert('Erro de conexão'); }
}
window.saveQuestaoEdit = saveQuestaoEdit;

// ==================== VINCULAÇÃO EM LOTE ====================
async function loadLoteOptions() {
  try {
    const datas = await fetch('/api/questoes/datas-importacao').then(r => r.json());
    const sel = document.getElementById('lote-data');
    sel.innerHTML = '<option value="">Selecione...</option>' +
      datas.map(d => `<option value="${d.data}">${d.data} (${d.total} questões${d.bancas ? ' · ' + d.bancas.split(',').slice(0,3).join(', ') : ''})</option>`).join('');

    // Carregar disciplinas do edital
    const materias = await fetch('/api/edital/materias-disponiveis').then(r => r.json());
    const selMat = document.getElementById('lote-materia');
    selMat.innerHTML = '<option value="">Manter atual</option>' +
      materias.map(m => `<option value="${m}">${m}</option>`).join('');
  } catch(e) {}
}

async function previewLote() {
  const data = document.getElementById('lote-data').value;
  const el = document.getElementById('lote-preview');
  const selBanca = document.getElementById('lote-banca');
  if (!data) { el.innerHTML = ''; selBanca.innerHTML = '<option value="">Todas</option>'; return; }

  const questoes = await fetch(`/api/questoes?limit=9999`).then(r => r.json());
  const filtered = questoes.filter(q => q.created_at === data);

  // Popular bancas
  const bancas = [...new Set(filtered.map(q => q.banca).filter(b => b))];
  selBanca.innerHTML = '<option value="">Todas (' + filtered.length + ')</option>' +
    bancas.map(b => {
      const count = filtered.filter(q => q.banca === b).length;
      return `<option value="${b}">${b} (${count})</option>`;
    }).join('');

  const banca = selBanca.value;
  const final = banca ? filtered.filter(q => q.banca === banca) : filtered;
  const semMateria = final.filter(q => !q.materia).length;
  el.innerHTML = `📋 <strong>${final.length}</strong> questões selecionadas` +
    (semMateria > 0 ? ` (${semMateria} sem disciplina)` : ' (todas já vinculadas)');
}
window.previewLote = previewLote;

async function aplicarLote() {
  const data = document.getElementById('lote-data').value;
  const banca = document.getElementById('lote-banca').value;
  const materia = document.getElementById('lote-materia').value;
  const topico = document.getElementById('lote-topico').value.trim();

  if (!data) { alert('Selecione uma data de importação.'); return; }
  if (!materia && !topico) { alert('Informe pelo menos a disciplina ou tópico.'); return; }

  const filtro = { created_at: data };
  if (banca) filtro.banca = banca;

  const atualizar = {};
  if (materia) atualizar.materia = materia;
  if (topico) atualizar.topico = topico;

  try {
    const res = await fetch('/api/questoes/vincular-lote', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filtro, atualizar })
    });
    const result = await res.json();
    if (result.ok) {
      alert(`✅ ${result.atualizadas} questões atualizadas!`);
      loadBanco();
      loadMaterias();
      previewLote();
    } else {
      alert('Erro: ' + (result.detail || 'desconhecido'));
    }
  } catch(e) { alert('Erro de conexão'); }
}
window.aplicarLote = aplicarLote;

// ==================== INIT ====================
loadMaterias();
loadBancas();
loadTempoMedio();
loadStats();
loadSimulados();
loadErros();
loadBanco();
loadLoteOptions();
loadQuestoesResolver();

// Load user profile in header
(async function() {
  try {
    const profile = await fetch('/api/social/profile').then(r => r.json());
    const nome = profile.username || 'Estudante';
    const initials = nome.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
    const avatarEl = document.getElementById('q-user-avatar');
    const nameEl = document.getElementById('q-user-name');
    if (avatarEl) avatarEl.textContent = initials || '👤';
    if (nameEl) nameEl.textContent = nome.split(' ')[0];
  } catch {}
})();

// ==================== CSV IMPORT ====================
// Inject CSV button into header
(function() {
  const headerLinks = document.querySelector('.header-links');
  if (headerLinks) {
    const csvBtn = document.createElement('button');
    csvBtn.className = 'btn btn-secondary';
    csvBtn.style.cssText = 'font-size:0.82rem;padding:6px 12px;';
    csvBtn.textContent = '📥 Importar CSV';
    csvBtn.onclick = () => document.getElementById('csv-import-modal').style.display = 'flex';
    headerLinks.insertBefore(csvBtn, headerLinks.firstChild);
  }
})();

function csvFileSelected(input) {
  const file = input.files[0];
  const el = document.getElementById('csv-import-filename');
  if (file) {
    el.textContent = `📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  } else {
    el.textContent = '';
  }
  // Ocultar resultados anteriores
  document.getElementById('csv-import-results').style.display = 'none';
}
window.csvFileSelected = csvFileSelected;

async function executarImportCSV() {
  const fileInput = document.getElementById('csv-import-file');
  const file = fileInput.files[0];
  if (!file) {
    alert('Selecione um arquivo CSV.');
    return;
  }

  const formato = document.getElementById('csv-import-formato').value;
  const resultsEl = document.getElementById('csv-import-results');

  // Mostrar loading
  resultsEl.style.display = 'block';
  resultsEl.style.background = '#45475a';
  resultsEl.style.color = '#cdd6f4';
  resultsEl.innerHTML = '⏳ Importando questões...';

  const formData = new FormData();
  formData.append('file', file);

  const url = `/api/questoes/importar-csv?formato=${encodeURIComponent(formato)}`;

  try {
    const res = await fetch(url, { method: 'POST', body: formData });
    const data = await res.json();

    if (res.ok) {
      resultsEl.style.background = '#1e3a2e';
      resultsEl.style.color = '#a6e3a1';
      let html = `✅ <strong>${data.imported}</strong> questões importadas com sucesso!<br>`;
      html += `<small>Formato: ${data.format_detected} · Total linhas: ${data.total_rows}</small><br>`;
      if (data.duplicates > 0) {
        html += `<span style="color:#fab387;">⚠️ ${data.duplicates} duplicata(s) ignorada(s)</span><br>`;
      }
      if (data.errors && data.errors.length > 0) {
        html += `<details style="margin-top:8px;"><summary style="cursor:pointer;color:#f38ba8;">❌ ${data.errors.length} erro(s)</summary>`;
        html += `<ul style="margin-top:6px;padding-left:16px;font-size:0.78rem;color:#f38ba8;">`;
        data.errors.slice(0, 20).forEach(e => { html += `<li>${e}</li>`; });
        if (data.errors.length > 20) html += `<li>... e mais ${data.errors.length - 20}</li>`;
        html += `</ul></details>`;
      }
      resultsEl.innerHTML = html;

      // Recarregar dados
      loadBanco();
      loadMaterias();
      loadLoteOptions();
    } else {
      resultsEl.style.background = '#3a1e1e';
      resultsEl.style.color = '#f38ba8';
      resultsEl.innerHTML = `❌ Erro: ${data.detail || 'Falha na importação'}`;
    }
  } catch (e) {
    resultsEl.style.background = '#3a1e1e';
    resultsEl.style.color = '#f38ba8';
    resultsEl.innerHTML = `❌ Erro de conexão: ${e.message}`;
  }

  // Limpar file input
  fileInput.value = '';
  document.getElementById('csv-import-filename').textContent = '';
}
window.executarImportCSV = executarImportCSV;

// ==================== THEME (imported via ES module at bottom of HTML) ====================
// toggleTheme is imported and assigned to window by the theme module script tag
