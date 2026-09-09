// ==================== MEUS CADERNOS DE REVISÃO ====================
// Visualiza cadernos de revisão do usuário — inclusive os comprados/importados
// do catálogo, cujo PDF de origem ele pode não ter. Modo leitura (sem edição).
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

const _TAGS = {
  '': { label: '', cor: '#9399b2' },
  decorar: { label: '🔴 Decorar', cor: '#f38ba8' },
  entender: { label: '🔵 Entender', cor: '#89b4fa' },
  pegadinha: { label: '🟡 Pegadinha', cor: '#f9e2af' },
  revisar: { label: '🟢 Revisar', cor: '#a6e3a1' },
};

async function carregarCadernos() {
  const grid = document.getElementById('cadernos-grid');
  try {
    const data = await fetch('/api/revisao-cadernos', { headers: _headers() }).then(r => r.json());
    const cadernos = data.cadernos || [];
    if (!cadernos.length) {
      grid.innerHTML = '<div class="empty">📭 Você ainda não tem cadernos de revisão.<br>Compre um no Catálogo ou crie o seu a partir de um PDF!</div>';
      return;
    }
    grid.innerHTML = cadernos.map(c => `
      <div class="cad-card" onclick="abrirCaderno('${encodeURIComponent(c.pdf_path)}', '${esc(c.nome).replace(/'/g, "\\'")}')">
        <div class="cad-nome">🗂️ ${esc(c.nome)}</div>
        <div class="cad-meta">
          <span>${c.blocos} bloco(s)</span>
          <span>${c.tem_pdf ? '📄 com PDF' : '📦 importado'}</span>
        </div>
        ${c.proxima_revisao ? `<div style="font-size:0.72rem;color:#89b4fa;">Próx. revisão: ${esc(c.proxima_revisao)}</div>` : ''}
      </div>
    `).join('');
  } catch (e) {
    grid.innerHTML = '<div class="empty">⚠️ Erro ao carregar os cadernos.</div>';
  }
}

window.abrirCaderno = async function(pdfPathEnc, nome) {
  const pdfPath = decodeURIComponent(pdfPathEnc);
  const grid = document.getElementById('cadernos-grid');
  const leitura = document.getElementById('caderno-leitura');
  const alvo = document.getElementById('caderno-blocos');
  document.getElementById('caderno-titulo').textContent = `🗂️ ${nome}`;
  alvo.innerHTML = '<div class="empty">Carregando blocos…</div>';
  grid.style.display = 'none';
  leitura.style.display = 'block';
  window.scrollTo({ top: 0, behavior: 'smooth' });

  try {
    const blocos = await fetch(`/api/revisao/${pdfPath}`, { headers: _headers() }).then(r => r.json());
    if (!Array.isArray(blocos) || !blocos.length) {
      alvo.innerHTML = '<div class="empty">Este caderno não tem blocos.</div>';
      return;
    }
    alvo.innerHTML = blocos.map(b => _renderBloco(b)).join('');
  } catch (e) {
    alvo.innerHTML = '<div class="empty">⚠️ Erro ao carregar os blocos.</div>';
  }
};

function _renderBloco(b) {
  const tag = _TAGS[b.tag || ''] || _TAGS[''];
  const borda = b.tag ? `border-left:3px solid ${tag.cor};` : '';
  const titulo = b.titulo
    ? `<div style="font-weight:600;color:var(--teal,#94e2d5);font-size:0.9rem;margin-bottom:6px;">${esc(b.titulo)}</div>` : '';
  const img = (b.tipo === 'recorte' && b.imagem_data)
    ? `<img src="${b.imagem_data}" alt="Recorte p.${b.pagina}" style="max-width:100%;border-radius:6px;display:block;margin-bottom:6px;border:1px solid var(--border,#45475a);">` : '';
  const conteudo = b.conteudo
    ? `<div style="font-size:0.86rem;color:var(--text,#cdd6f4);line-height:1.5;white-space:pre-wrap;">${esc(b.conteudo)}</div>` : '';
  const tagBadge = b.tag ? `<span style="font-size:0.68rem;color:${tag.cor};">${tag.label}</span>` : '';
  return `<div style="background:var(--bg-surface,#313244);border-radius:10px;padding:14px;margin-bottom:12px;${borda}">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
      <span style="font-size:0.7rem;color:var(--text-sub,#9399b2);">p.${b.pagina}</span>
      ${tagBadge}
    </div>
    ${titulo}${img}${conteudo}
  </div>`;
}

window.voltarCadernos = function() {
  document.getElementById('caderno-leitura').style.display = 'none';
  document.getElementById('cadernos-grid').style.display = 'grid';
};

// Init
carregarCadernos();
