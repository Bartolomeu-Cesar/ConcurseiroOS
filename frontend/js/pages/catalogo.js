// ==================== CATÁLOGO PÚBLICO ====================
import { showToast } from '../modules/toast.js';
window.showToast = showToast;

function _headers() {
  const token = localStorage.getItem('auth_token');
  const h = {};
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

async function carregarCatalogo() {
  const busca = document.getElementById('busca').value.trim();
  const categoria = document.getElementById('filtro-categoria').value;
  const tipo = document.getElementById('filtro-tipo').value;

  const params = new URLSearchParams();
  if (busca) params.set('busca', busca);
  if (categoria) params.set('categoria', categoria);
  if (tipo) params.set('tipo', tipo);

  const grid = document.getElementById('catalogo-grid');
  try {
    const res = await fetch('/api/catalogo?' + params, { headers: _headers() });
    const data = await res.json();

    // Popular categorias (uma vez)
    const catSel = document.getElementById('filtro-categoria');
    if (data.categorias && catSel.options.length <= 1) {
      data.categorias.forEach(c => {
        catSel.insertAdjacentHTML('beforeend', `<option value="${esc(c)}">${esc(c)}</option>`);
      });
      if (categoria) catSel.value = categoria;
    }

    if (!data.itens || !data.itens.length) {
      grid.innerHTML = '<div class="empty">📭 Nenhum material disponível no momento.<br>Volte em breve — novos materiais são adicionados regularmente!</div>';
      return;
    }

    grid.innerHTML = data.itens.map(it => `
      <div class="catalogo-card">
        <span class="cat-tipo">${it.tipo_emoji} ${esc(it.tipo_label)}</span>
        <div class="cat-titulo">${esc(it.titulo)}</div>
        <div class="cat-desc">${esc(it.descricao || 'Sem descrição.')}</div>
        <div class="cat-meta">
          <span>👤 ${esc(it.curador_nome)}</span>
          <span>⬇️ ${it.downloads}</span>
        </div>
        <button onclick="importarItem(${it.id}, this)">📥 Importar para minha conta</button>
      </div>
    `).join('');
  } catch (e) {
    grid.innerHTML = '<div class="empty">⚠️ Erro ao carregar o catálogo.</div>';
  }
}

window.aplicarFiltros = carregarCatalogo;

window.importarItem = async function(itemId, btn) {
  if (!localStorage.getItem('auth_token')) {
    showToast('Faça login para importar materiais.', 'warning');
    setTimeout(() => location.href = '/login.html', 1200);
    return;
  }
  if (!confirm('Importar este material para a sua conta? Uma cópia será criada e você poderá estudá-la.')) return;

  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = '⏳ Importando...';
  try {
    const res = await fetch(`/api/catalogo/${itemId}/importar`, { method: 'POST', headers: _headers() });
    const data = await res.json();
    if (res.ok) {
      showToast(`✅ "${data.titulo}" importado! (${data.importados} item(ns))`, 'success');
      btn.textContent = '✓ Importado';
      // Atualizar contador de downloads
      setTimeout(carregarCatalogo, 1500);
    } else {
      showToast(data.detail || 'Erro ao importar.', 'error');
      btn.disabled = false;
      btn.textContent = original;
    }
  } catch (e) {
    showToast('Erro de conexão.', 'error');
    btn.disabled = false;
    btn.textContent = original;
  }
};

// Init
carregarCatalogo();
