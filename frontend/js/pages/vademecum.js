// vademecum.js — Vade Mecum Digital page logic
// ES module
import { toast } from '../modules/toast.js';
import { confirmModal } from '../modules/utils.js';
import { handleAuthNav } from '../modules/auth.js';
window.handleAuthNav = handleAuthNav;

// ==================== STATE ====================
let leisCache = [];
let currentArtigoId = null;
let currentArtigoDestacado = false;
let importLeiId = null;

// ==================== TAB NAVIGATION ====================
function switchTab(tabId) {
  document.querySelectorAll('.vm-tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.vm-tab-content').forEach(c => c.classList.remove('active'));
  const btn = document.querySelector(`.vm-tab-btn[data-tab="${tabId}"]`);
  if (btn) btn.classList.add('active');
  const content = document.getElementById(tabId);
  if (content) content.classList.add('active');

  // Lazy load data
  if (tabId === 'tab-leis') loadLeis();
  if (tabId === 'tab-destaques') loadDestaques();
}
window.switchTab = switchTab;

// ==================== BUSCA ====================
async function vmBuscar() {
  const q = document.getElementById('vm-search-input').value.trim();
  if (!q) {
    toast('Digite um termo para buscar.', 'warning');
    return;
  }
  const leiId = document.getElementById('vm-search-lei').value || '0';
  const container = document.getElementById('vm-search-results');
  container.innerHTML = '<div class="vm-loading">Buscando...</div>';

  try {
    const res = await fetch(`/api/vademecum/busca?q=${encodeURIComponent(q)}&lei_id=${leiId}`);
    if (!res.ok) throw new Error('Erro na busca');
    const data = await res.json();

    if (!data.length) {
      container.innerHTML = `<div class="vm-empty"><div class="vm-empty-icon">🤷</div><p>Nenhum resultado para "<strong>${escapeHtml(q)}</strong>".</p></div>`;
      return;
    }

    container.innerHTML = data.map(art => `
      <div class="vm-result-card" onclick="openArtigoDetail(${art.id}, '${escapeAttr(art.lei_nome || '')}')">
        <div class="vm-result-lei">${escapeHtml(art.lei_nome || 'Lei')}</div>
        <div class="vm-result-num">Art. ${escapeHtml(art.numero)}</div>
        <div class="vm-result-caput">${highlightTerm(escapeHtml(art.caput || ''), q)}</div>
        <div class="vm-result-actions">
          <button class="vm-btn-star" onclick="event.stopPropagation();quickHighlight(${art.id}, true)" title="Destacar" aria-label="Destacar artigo">⭐</button>
          <button class="vm-btn-note" onclick="event.stopPropagation();openArtigoDetail(${art.id}, '${escapeAttr(art.lei_nome || '')}')" title="Anotar" aria-label="Anotar no artigo">📝</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = `<div class="vm-empty"><div class="vm-empty-icon">❌</div><p>Erro ao buscar: ${escapeHtml(err.message)}</p></div>`;
  }
}
window.vmBuscar = vmBuscar;

// ==================== LEIS ====================
async function loadLeis() {
  const container = document.getElementById('vm-leis-list');
  try {
    const res = await fetch('/api/vademecum/leis');
    if (!res.ok) throw new Error('Erro ao carregar leis');
    leisCache = await res.json();
    renderLeis();
    populateLeiSelect();
  } catch (err) {
    container.innerHTML = `<div class="vm-empty"><div class="vm-empty-icon">❌</div><p>${escapeHtml(err.message)}</p></div>`;
  }
}

function renderLeis() {
  const container = document.getElementById('vm-leis-list');
  if (!leisCache.length) {
    container.innerHTML = `<div class="vm-empty"><div class="vm-empty-icon">📚</div><p>Nenhuma lei cadastrada. Clique em "+ Nova Lei" para começar.</p></div>`;
    return;
  }
  container.innerHTML = leisCache.map(lei => `
    <div class="vm-lei-card" id="lei-card-${lei.id}">
      <div class="vm-lei-header" onclick="toggleLeiArtigos(${lei.id})">
        <span class="vm-lei-chevron" id="chevron-${lei.id}">▶</span>
        <span class="vm-lei-sigla">${escapeHtml(lei.sigla || '')}</span>
        <span class="vm-lei-name">${escapeHtml(lei.nome)}</span>
        <span class="vm-lei-count">${lei.total_artigos || 0} artigos</span>
      </div>
      <div class="vm-lei-actions">
        <button class="vm-btn-import" onclick="openModalImportar(${lei.id})">📥 Importar Texto</button>
        <button class="vm-btn-delete" onclick="deletarLei(${lei.id}, '${escapeAttr(lei.nome)}')">🗑️ Excluir</button>
      </div>
      <div class="vm-artigos-list" id="artigos-${lei.id}"></div>
    </div>
  `).join('');
}

async function toggleLeiArtigos(leiId) {
  const list = document.getElementById(`artigos-${leiId}`);
  const chevron = document.getElementById(`chevron-${leiId}`);
  if (list.classList.contains('open')) {
    list.classList.remove('open');
    chevron.classList.remove('open');
    return;
  }

  // Load artigos
  list.innerHTML = '<div class="vm-loading">Carregando artigos...</div>';
  list.classList.add('open');
  chevron.classList.add('open');

  try {
    const res = await fetch(`/api/vademecum/leis/${leiId}/artigos`);
    if (!res.ok) throw new Error('Erro');
    const artigos = await res.json();

    if (!artigos.length) {
      list.innerHTML = '<div style="padding:12px;color:var(--text-sub);font-size:0.82rem;">Nenhum artigo cadastrado. Use "Importar Texto" para adicionar.</div>';
      return;
    }

    const leiNome = leisCache.find(l => l.id === leiId)?.nome || '';
    list.innerHTML = artigos.map(art => `
      <div class="vm-artigo-item" onclick="openArtigoDetail(${art.id}, '${escapeAttr(leiNome)}')">
        <span class="vm-artigo-num">Art. ${escapeHtml(art.numero)}</span>
        <span class="vm-artigo-caput">${escapeHtml((art.caput || '').slice(0, 120))}${(art.caput || '').length > 120 ? '...' : ''}</span>
      </div>
    `).join('');
  } catch (err) {
    list.innerHTML = '<div style="padding:12px;color:var(--red);font-size:0.82rem;">Erro ao carregar artigos.</div>';
  }
}
window.toggleLeiArtigos = toggleLeiArtigos;

function populateLeiSelect() {
  const sel = document.getElementById('vm-search-lei');
  const val = sel.value;
  // Keep first option
  while (sel.options.length > 1) sel.remove(1);
  leisCache.forEach(lei => {
    const opt = document.createElement('option');
    opt.value = lei.id;
    opt.textContent = `${lei.sigla || ''} - ${lei.nome}`;
    sel.appendChild(opt);
  });
  sel.value = val;
}

// ==================== MODAL NOVA LEI ====================
function openModalLei() {
  document.getElementById('modal-nova-lei').classList.add('open');
  document.getElementById('lei-nome').focus();
}
window.openModalLei = openModalLei;

function closeModalLei() {
  document.getElementById('modal-nova-lei').classList.remove('open');
  document.getElementById('lei-nome').value = '';
  document.getElementById('lei-sigla').value = '';
  document.getElementById('lei-numero').value = '';
  document.getElementById('lei-ementa').value = '';
}
window.closeModalLei = closeModalLei;

async function salvarLei() {
  const nome = document.getElementById('lei-nome').value.trim();
  const sigla = document.getElementById('lei-sigla').value.trim();
  const numero = document.getElementById('lei-numero').value.trim();
  const ementa = document.getElementById('lei-ementa').value.trim();

  if (!nome) {
    toast('Nome da lei é obrigatório.', 'warning');
    return;
  }

  try {
    const res = await fetch('/api/vademecum/leis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome, sigla, numero, ementa })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Erro ao salvar');
    }
    toast('Lei cadastrada com sucesso!', 'success');
    closeModalLei();
    loadLeis();
  } catch (err) {
    toast(err.message, 'error');
  }
}
window.salvarLei = salvarLei;

async function deletarLei(leiId, nome) {
  if (!await confirmModal('Excluir lei', `Excluir "${nome}" e todos os seus artigos?`, { type: 'danger', confirmText: 'Excluir' })) return;
  try {
    const res = await fetch(`/api/vademecum/leis/${leiId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Erro ao excluir');
    toast('Lei excluída.', 'success');
    loadLeis();
  } catch (err) {
    toast(err.message, 'error');
  }
}
window.deletarLei = deletarLei;

// ==================== MODAL IMPORTAR ====================
function openModalImportar(leiId) {
  importLeiId = leiId;
  document.getElementById('importar-texto').value = '';
  const pdfInput = document.getElementById('importar-pdf');
  if (pdfInput) pdfInput.value = '';
  document.getElementById('modal-importar').classList.add('open');
  document.getElementById('importar-texto').focus();
}
window.openModalImportar = openModalImportar;

function closeModalImportar() {
  document.getElementById('modal-importar').classList.remove('open');
  importLeiId = null;
}
window.closeModalImportar = closeModalImportar;

async function importarTexto() {
  const texto = document.getElementById('importar-texto').value.trim();
  if (!texto) {
    toast('Cole o texto da lei para importar.', 'warning');
    return;
  }
  if (!importLeiId) {
    toast('Lei não selecionada.', 'error');
    return;
  }

  const btn = document.getElementById('btn-importar');
  btn.disabled = true;
  btn.textContent = '⏳ Importando...';

  try {
    const res = await fetch(`/api/vademecum/leis/${importLeiId}/importar-texto`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texto })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Erro ao importar');
    }
    const data = await res.json();
    const count = data.artigos_importados ?? data.importados ?? 'vários';
    toast(`✅ ${count} artigos importados com sucesso!`, 'success');
    closeModalImportar();
    loadLeis();
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '🚀 Importar do texto';
  }
}

async function importarPDF() {
  const input = document.getElementById('importar-pdf');
  const file = input.files?.[0];
  if (!file) {
    toast('Selecione um arquivo PDF.', 'warning');
    return;
  }
  if (!importLeiId) {
    toast('Lei não selecionada.', 'error');
    return;
  }

  const btn = document.getElementById('btn-importar-pdf');
  const progress = document.getElementById('vm-import-progress');
  const progressLabel = document.getElementById('vm-import-progress-label');
  btn.disabled = true;
  btn.textContent = '⏳ Extraindo do PDF...';
  if (progress) progress.style.display = 'block';
  if (progressLabel) progressLabel.textContent = `Processando “${file.name}”…`;

  try {
    const formData = new FormData();
    formData.append('file', file);
    // O auth-interceptor global injeta o header Authorization automaticamente.
    const res = await fetch(`/api/vademecum/leis/${importLeiId}/importar-pdf`, {
      method: 'POST',
      body: formData,
    });
    if (res.status === 401) {
      // Token expirado/inválido — o interceptor global pode redirecionar; avisa antes.
      throw new Error('Sessão expirada. Faça login novamente e tente de novo.');
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Erro ao importar do PDF (HTTP ${res.status})`);
    }
    const data = await res.json();
    const count = data.artigos_importados ?? 0;
    if (count === 0) {
      toast('Nenhum artigo detectado no PDF. Verifique se o texto segue o padrão "Art. Nº ...".', 'warning', 6000);
    } else {
      toast(`✅ ${count} artigos importados do PDF!`, 'success');
      closeModalImportar();
      loadLeis();
    }
  } catch (err) {
    console.error('[vademecum] importarPDF falhou:', err);
    toast(err.message || 'Falha ao importar o PDF.', 'error', 6000);
  } finally {
    btn.disabled = false;
    btn.textContent = '📄 Importar do PDF';
    if (progress) progress.style.display = 'none';
  }
}
window.importarPDF = importarPDF;
window.importarTexto = importarTexto;

// ==================== DESTAQUES ====================
async function loadDestaques() {
  const container = document.getElementById('vm-destaques-list');
  container.innerHTML = '<div class="vm-loading">Carregando destaques...</div>';
  try {
    const res = await fetch('/api/vademecum/destaques');
    if (!res.ok) throw new Error('Erro ao carregar destaques');
    const data = await res.json();

    if (!data.length) {
      container.innerHTML = `<div class="vm-empty"><div class="vm-empty-icon">⭐</div><p>Nenhum artigo destacado ainda. Destaque artigos para revisá-los aqui.</p></div>`;
      return;
    }

    container.innerHTML = data.map(art => `
      <div class="vm-destaque-card" onclick="openArtigoDetail(${art.id}, '${escapeAttr(art.lei_nome || '')}')">
        <div class="vm-destaque-lei">${escapeHtml(art.lei_nome || 'Lei')}</div>
        <div class="vm-destaque-num">Art. ${escapeHtml(art.numero)}</div>
        <div class="vm-destaque-caput">${escapeHtml((art.caput || '').slice(0, 200))}${(art.caput || '').length > 200 ? '...' : ''}</div>
        ${art.anotacao ? `<div class="vm-destaque-nota">📝 ${escapeHtml(art.anotacao.slice(0, 100))}${art.anotacao.length > 100 ? '...' : ''}</div>` : ''}
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = `<div class="vm-empty"><div class="vm-empty-icon">❌</div><p>${escapeHtml(err.message)}</p></div>`;
  }
}

// ==================== ARTIGO DETAIL ====================
async function openArtigoDetail(artigoId, leiNome) {
  currentArtigoId = artigoId;
  const modal = document.getElementById('vm-artigo-detail');

  // Reset
  document.getElementById('detail-titulo').textContent = 'Carregando...';
  document.getElementById('detail-lei-info').textContent = leiNome || '';
  document.getElementById('detail-caput').textContent = '';
  document.getElementById('detail-paragrafos').innerHTML = '';
  document.getElementById('detail-incisos').innerHTML = '';
  document.getElementById('detail-paragrafos-container').style.display = 'none';
  document.getElementById('detail-incisos-container').style.display = 'none';
  document.getElementById('detail-capitulo').style.display = 'none';
  document.getElementById('detail-anotacao').value = '';
  document.getElementById('detail-questoes').innerHTML = '';
  document.getElementById('btn-destacar').classList.remove('active');
  currentArtigoDestacado = false;

  modal.classList.add('open');

  // We need artigo data — try from search results or fetch from lei
  // Use busca endpoint with the artigo ID to get full data
  // Actually, we need individual artigo fetch — let's search by id or use cached data
  // Since there's no GET /artigos/{id}, we'll use busca or the lei artigos list
  // For now, let's fetch via busca (if we have info) or use a workaround
  // Best approach: fetch all artigos from the lei and find the one we need
  // Alternative: use the data from the calling context

  try {
    // Try using busca with the article number — but we don't have it reliably
    // Instead, search destaques and full-text to get article info
    // Simplest: use the GET busca endpoint with a generic search
    // Actually the safest is to call destaques + all leis artigos
    // Let's try a different approach — get from DOM data or re-fetch
    const res = await fetch(`/api/vademecum/busca?q=&lei_id=0`);
    let artigo = null;

    if (res.ok) {
      const all = await res.json();
      artigo = all.find(a => a.id === artigoId);
    }

    // If not found via busca, try destaques
    if (!artigo) {
      const resD = await fetch('/api/vademecum/destaques');
      if (resD.ok) {
        const destaques = await resD.json();
        artigo = destaques.find(a => a.id === artigoId);
      }
    }

    // If still not found, try each lei's artigos
    if (!artigo && leisCache.length) {
      for (const lei of leisCache) {
        const resL = await fetch(`/api/vademecum/leis/${lei.id}/artigos`);
        if (resL.ok) {
          const artigos = await resL.json();
          artigo = artigos.find(a => a.id === artigoId);
          if (artigo) {
            artigo.lei_nome = lei.nome;
            break;
          }
        }
      }
    }

    if (!artigo) {
      document.getElementById('detail-titulo').textContent = 'Artigo não encontrado';
      return;
    }

    // Populate
    document.getElementById('detail-titulo').textContent = `Art. ${artigo.numero}`;
    document.getElementById('detail-lei-info').textContent = artigo.lei_nome || leiNome || '';
    document.getElementById('detail-caput').textContent = artigo.caput || '';

    if (artigo.capitulo || artigo.secao) {
      const capEl = document.getElementById('detail-capitulo');
      capEl.textContent = [artigo.capitulo, artigo.secao].filter(Boolean).join(' — ');
      capEl.style.display = 'block';
    }

    if (artigo.paragrafos) {
      const paras = typeof artigo.paragrafos === 'string' ? artigo.paragrafos : JSON.stringify(artigo.paragrafos);
      if (paras && paras !== '[]' && paras !== 'null') {
        document.getElementById('detail-paragrafos-container').style.display = 'block';
        const parsed = tryParseArray(paras);
        document.getElementById('detail-paragrafos').innerHTML = parsed.map(p => `<p>${escapeHtml(p)}</p>`).join('');
      }
    }

    if (artigo.incisos) {
      const incs = typeof artigo.incisos === 'string' ? artigo.incisos : JSON.stringify(artigo.incisos);
      if (incs && incs !== '[]' && incs !== 'null') {
        document.getElementById('detail-incisos-container').style.display = 'block';
        const parsed = tryParseArray(incs);
        document.getElementById('detail-incisos').innerHTML = parsed.map(i => `<p>${escapeHtml(i)}</p>`).join('');
      }
    }

    if (artigo.anotacao) {
      document.getElementById('detail-anotacao').value = artigo.anotacao;
    }

    if (artigo.destacado) {
      currentArtigoDestacado = true;
      document.getElementById('btn-destacar').classList.add('active');
      document.getElementById('btn-destacar').textContent = '⭐ Destacado';
    } else {
      document.getElementById('btn-destacar').textContent = '⭐ Destacar';
    }
  } catch (err) {
    document.getElementById('detail-caput').textContent = 'Erro ao carregar artigo.';
  }
}
window.openArtigoDetail = openArtigoDetail;

function closeDetail() {
  document.getElementById('vm-artigo-detail').classList.remove('open');
  currentArtigoId = null;
}
window.closeDetail = closeDetail;

// Close modals on backdrop click
document.getElementById('vm-artigo-detail').addEventListener('click', (e) => {
  if (e.target === document.getElementById('vm-artigo-detail')) closeDetail();
});
document.getElementById('modal-nova-lei').addEventListener('click', (e) => {
  if (e.target === document.getElementById('modal-nova-lei')) closeModalLei();
});
document.getElementById('modal-importar').addEventListener('click', (e) => {
  if (e.target === document.getElementById('modal-importar')) closeModalImportar();
});

// ==================== ANOTAR / DESTACAR ====================
async function salvarAnotacao() {
  if (!currentArtigoId) return;
  const anotacao = document.getElementById('detail-anotacao').value.trim();
  try {
    const res = await fetch(`/api/vademecum/artigos/${currentArtigoId}/anotar`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anotacao, destacado: currentArtigoDestacado })
    });
    if (!res.ok) throw new Error('Erro ao salvar');
    toast('Anotação salva!', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}
window.salvarAnotacao = salvarAnotacao;

async function toggleDestacar() {
  if (!currentArtigoId) return;
  currentArtigoDestacado = !currentArtigoDestacado;
  const btn = document.getElementById('btn-destacar');
  btn.classList.toggle('active', currentArtigoDestacado);
  btn.textContent = currentArtigoDestacado ? '⭐ Destacado' : '⭐ Destacar';

  const anotacao = document.getElementById('detail-anotacao').value.trim();
  try {
    const res = await fetch(`/api/vademecum/artigos/${currentArtigoId}/anotar`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anotacao, destacado: currentArtigoDestacado })
    });
    if (!res.ok) throw new Error('Erro ao atualizar');
    toast(currentArtigoDestacado ? 'Artigo destacado! ⭐' : 'Destaque removido.', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}
window.toggleDestacar = toggleDestacar;

async function quickHighlight(artigoId, destacado) {
  try {
    const res = await fetch(`/api/vademecum/artigos/${artigoId}/anotar`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anotacao: '', destacado })
    });
    if (!res.ok) throw new Error('Erro');
    toast('Artigo destacado! ⭐', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}
window.quickHighlight = quickHighlight;

// ==================== QUESTÕES RELACIONADAS ====================
async function verQuestoesRelacionadas() {
  if (!currentArtigoId) return;
  const container = document.getElementById('detail-questoes');
  container.innerHTML = '<div class="vm-loading">Buscando questões...</div>';

  try {
    const res = await fetch(`/api/vademecum/artigos/${currentArtigoId}/questoes-relacionadas`);
    if (!res.ok) throw new Error('Erro');
    const questoes = await res.json();

    if (!questoes.length) {
      container.innerHTML = '<div style="padding:10px;font-size:0.82rem;color:var(--text-sub);">Nenhuma questão relacionada encontrada.</div>';
      return;
    }

    container.innerHTML = questoes.map(q => `
      <div class="vm-questao-item">
        <strong>${escapeHtml(q.materia || '')}</strong> — ${escapeHtml((q.enunciado || '').slice(0, 150))}${(q.enunciado || '').length > 150 ? '...' : ''}
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = '<div style="padding:10px;font-size:0.82rem;color:var(--red);">Erro ao buscar questões.</div>';
  }
}
window.verQuestoesRelacionadas = verQuestoesRelacionadas;

// ==================== UTILITIES ====================
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escapeAttr(str) {
  if (!str) return '';
  return str.replace(/'/g, "\\'").replace(/"/g, '&quot;').replace(/\\/g, '\\\\');
}

function highlightTerm(text, term) {
  if (!term) return text;
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${escaped})`, 'gi');
  return text.replace(regex, '<mark>$1</mark>');
}

function tryParseArray(val) {
  if (Array.isArray(val)) return val;
  if (!val || val === 'null') return [];
  try {
    const parsed = JSON.parse(val);
    return Array.isArray(parsed) ? parsed : [String(parsed)];
  } catch {
    // Might be newline-separated text
    return val.split('\n').filter(l => l.trim());
  }
}

// ==================== INIT ====================
async function init() {
  // Load leis for the search select
  try {
    const res = await fetch('/api/vademecum/leis');
    if (res.ok) {
      leisCache = await res.json();
      populateLeiSelect();
    }
  } catch { /* silent */ }
}

// Keyboard shortcut: Escape closes modals
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (document.getElementById('vm-artigo-detail').classList.contains('open')) closeDetail();
    else if (document.getElementById('modal-nova-lei').classList.contains('open')) closeModalLei();
    else if (document.getElementById('modal-importar').classList.contains('open')) closeModalImportar();
  }
});

init();
