// ==================== CATÁLOGO PÚBLICO ====================
import { showToast } from '../modules/toast.js';
import { confirmModal, alertModal, promptModal, escapeJsString } from '../modules/utils.js';
window.showToast = showToast;

function _headers(json = false) {
  const token = localStorage.getItem('auth_token');
  const h = json ? { 'Content-Type': 'application/json' } : {};
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

function estrelas(media, total) {
  const cheias = Math.round(media);
  let s = '';
  for (let i = 1; i <= 5; i++) s += i <= cheias ? '★' : '☆';
  return `<span style="color:#f9e2af;" title="${media} de 5">${s}</span> <span style="color:var(--text-sub,#9399b2);font-size:0.72rem;">${media > 0 ? media : '—'} (${total})</span>`;
}

async function carregarCatalogo() {
  const busca = document.getElementById('busca').value.trim();
  const categoria = document.getElementById('filtro-categoria').value;
  const tipo = document.getElementById('filtro-tipo').value;
  const ordenar = document.getElementById('filtro-ordenar')?.value || 'avaliacao';
  const cargo = document.getElementById('filtro-cargo')?.value.trim() || '';

  const params = new URLSearchParams();
  if (busca) params.set('busca', busca);
  if (categoria) params.set('categoria', categoria);
  if (tipo) params.set('tipo', tipo);
  if (cargo) params.set('cargo', cargo);
  params.set('ordenar', ordenar);

  const grid = document.getElementById('catalogo-grid');
  try {
    const res = await fetch('/api/catalogo?' + params, { headers: _headers() });
    const data = await res.json();

    const catSel = document.getElementById('filtro-categoria');
    if (data.categorias && catSel.options.length <= 1) {
      data.categorias.forEach(c => catSel.insertAdjacentHTML('beforeend', `<option value="${esc(c)}">${esc(c)}</option>`));
      if (categoria) catSel.value = categoria;
    }

    if (!data.itens || !data.itens.length) {
      grid.innerHTML = '<div class="empty">📭 Nenhum material disponível.<br>Volte em breve!</div>';
      return;
    }

    grid.innerHTML = data.itens.map(it => {
      const pago = (it.preco_creditos || 0) > 0 && !it.ja_comprado;
      const precoBadge = (it.preco_creditos || 0) > 0
        ? (it.ja_comprado
            ? '<span class="cat-preco" style="color:#a6e3a1;" title="Você já comprou este material">✓ Adquirido</span>'
            : `<span class="cat-preco" style="color:#f9e2af;" title="Preço em créditos">💎 ${it.preco_creditos}</span>`)
        : '<span class="cat-preco" style="color:#a6e3a1;">Grátis</span>';
      const cargoBadge = (it.concurso || it.cargo)
        ? `<div class="cat-cargo" style="font-size:0.72rem;color:#89b4fa;">🎯 ${esc([it.concurso, it.cargo].filter(Boolean).join(' · '))}</div>`
        : '';
      const btnLabel = pago ? `💎 Comprar (${it.preco_creditos})` : '📥 Importar';
      return `
      <div class="catalogo-card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
          <span class="cat-tipo">${it.tipo_emoji} ${esc(it.tipo_label)}</span>
          ${precoBadge}
        </div>
        <div class="cat-titulo">${esc(it.titulo)}</div>
        ${cargoBadge}
        <div class="cat-desc">${esc(it.descricao || 'Sem descrição.')}</div>
        <div style="font-size:0.85rem;">${estrelas(it.media_estrelas, it.total_avaliacoes)}</div>
        <div class="cat-meta">
          <span>👤 ${esc(it.curador_nome)}${it.curador_verificado ? ' <span title="Curador verificado" style="color:#89b4fa;">✔️</span>' : ''}</span>
          <span>⬇️ ${it.downloads}</span>
        </div>
        <div style="display:flex;gap:6px;">
          <button onclick="importarItem(${it.id}, this, ${it.preco_creditos || 0}, ${it.ja_comprado ? 'true' : 'false'})" style="flex:1;">${btnLabel}</button>
          <button onclick="abrirAvaliacoes(${it.id}, '${escapeJsString(it.titulo)}')" style="background:#45475a;color:#cdd6f4;flex:0 0 auto;padding:9px 12px;" aria-label="Ver avaliações">⭐</button>
        </div>
      </div>
    `;
    }).join('');
  } catch (e) {
    grid.innerHTML = '<div class="empty">⚠️ Erro ao carregar o catálogo.</div>';
  }
}
window.aplicarFiltros = carregarCatalogo;

window.importarItem = async function(itemId, btn, preco = 0, jaComprado = false) {
  if (!localStorage.getItem('auth_token')) {
    showToast('Faça login para importar materiais.', 'warning');
    setTimeout(() => location.href = '/login.html', 1200);
    return;
  }

  const ehCompra = (preco || 0) > 0 && !jaComprado;
  if (ehCompra) {
    // Buscar saldo atual para mostrar na confirmação
    let saldo = null;
    try {
      const rc = await fetch('/api/auth/creditos', { headers: _headers() });
      if (rc.ok) saldo = (await rc.json()).saldo;
    } catch (e) { /* segue sem saldo */ }

    if (saldo !== null && saldo < preco) {
      await alertModal(`Este material custa 💎 ${preco} crédito(s), mas você tem apenas 💎 ${saldo}.\n\nCompre créditos para adquiri-lo.`, { type: 'warning', title: 'Saldo insuficiente' });
      return;
    }
    const restante = saldo !== null ? ` Seu saldo passará de 💎 ${saldo} para 💎 ${saldo - preco}.` : '';
    const ok = await confirmModal(
      'Comprar material',
      `Você vai pagar 💎 ${preco} crédito(s) por este material. Uma cópia será criada na sua conta.${restante}`,
      { type: 'warning', confirmText: `Comprar (💎 ${preco})` }
    );
    if (!ok) return;
  } else if (!await confirmModal('Importar material', 'Uma cópia será criada na sua conta e você poderá estudá-la.', { type: 'info', confirmText: 'Importar' })) {
    return;
  }

  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = '⏳...';
  try {
    const res = await fetch(`/api/catalogo/${itemId}/importar`, { method: 'POST', headers: _headers() });
    const data = await res.json();
    if (res.ok) {
      const msg = data.cobrado
        ? `✅ "${data.titulo}" comprado! (💎 ${data.preco_creditos} · ${data.importados} item(ns))`
        : `✅ "${data.titulo}" importado! (${data.importados} item(ns))`;
      showToast(msg, 'success');
      btn.textContent = '✓ Concluído';
      setTimeout(carregarCatalogo, 1500);
    } else {
      showToast(data.detail || 'Erro ao importar.', 'error');
      btn.disabled = false; btn.textContent = original;
    }
  } catch (e) {
    showToast('Erro de conexão.', 'error');
    btn.disabled = false; btn.textContent = original;
  }
};

// ==================== AVALIAÇÕES ====================
window.abrirAvaliacoes = async function(itemId, titulo) {
  if (!localStorage.getItem('auth_token')) { showToast('Faça login para avaliar.', 'warning'); return; }
  const res = await fetch(`/api/catalogo/${itemId}/avaliacoes`, { headers: _headers() });
  const data = await res.json();

  const overlay = document.createElement('div');
  overlay.id = 'aval-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;';
  const minhaNota = data.minha_avaliacao?.nota || 0;
  const listaHtml = data.avaliacoes.length
    ? data.avaliacoes.map(a => `
        <div style="border-bottom:1px solid #45475a;padding:8px 0;">
          <div style="font-size:0.82rem;color:#cdd6f4;">${a.avatar} ${esc(a.nome)} <span style="color:#f9e2af;">${'★'.repeat(a.nota)}${'☆'.repeat(5 - a.nota)}</span></div>
          ${a.comentario ? `<div style="font-size:0.78rem;color:#9399b2;margin-top:2px;">${esc(a.comentario)}</div>` : ''}
        </div>`).join('')
    : '<div style="color:#9399b2;font-size:0.82rem;padding:8px 0;">Seja o primeiro a avaliar!</div>';

  overlay.innerHTML = `
    <div style="background:#313244;border-radius:16px;padding:24px;max-width:460px;width:100%;max-height:85vh;overflow-y:auto;">
      <h3 style="color:#cba6f7;margin:0 0 4px;">⭐ Avaliar: ${esc(titulo)}</h3>
      <div style="font-size:0.85rem;color:#f9e2af;margin-bottom:12px;">Média: ${data.media_estrelas} (${data.total_avaliacoes} avaliações)</div>
      <div style="margin-bottom:8px;">
        <div style="font-size:0.8rem;color:#9399b2;margin-bottom:4px;">Sua nota:</div>
        <div id="star-picker" style="font-size:1.8rem;cursor:pointer;">
          ${[1,2,3,4,5].map(n => `<span data-nota="${n}" style="color:${n <= minhaNota ? '#f9e2af' : '#585b70'};">★</span>`).join('')}
        </div>
      </div>
      <textarea id="aval-comentario" placeholder="Comentário (opcional)" aria-label="Comentário da avaliação" style="width:100%;min-height:60px;padding:8px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;font-size:0.85rem;margin-bottom:12px;">${esc(data.minha_avaliacao?.comentario || '')}</textarea>
      <div style="display:flex;gap:8px;margin-bottom:16px;">
        <button onclick="document.getElementById('aval-modal').remove()" style="flex:1;padding:9px;background:#45475a;color:#cdd6f4;border:none;border-radius:8px;cursor:pointer;">Fechar</button>
        <button id="aval-enviar" style="flex:1;padding:9px;background:#a6e3a1;color:#1e1e2e;border:none;border-radius:8px;font-weight:600;cursor:pointer;">Enviar avaliação</button>
      </div>
      <div style="font-size:0.8rem;color:#9399b2;font-weight:600;margin-bottom:4px;">Avaliações recentes:</div>
      ${listaHtml}
    </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

  let notaSel = minhaNota;
  overlay.querySelectorAll('#star-picker span').forEach(s => {
    s.onclick = () => {
      notaSel = parseInt(s.dataset.nota);
      overlay.querySelectorAll('#star-picker span').forEach(x => {
        x.style.color = parseInt(x.dataset.nota) <= notaSel ? '#f9e2af' : '#585b70';
      });
    };
  });
  overlay.querySelector('#aval-enviar').onclick = async () => {
    if (notaSel < 1) { showToast('Escolha uma nota (1-5 estrelas).', 'warning'); return; }
    const comentario = overlay.querySelector('#aval-comentario').value.trim();
    const r = await fetch(`/api/catalogo/${itemId}/avaliar`, {
      method: 'POST', headers: _headers(true), body: JSON.stringify({ nota: notaSel, comentario })
    });
    const d = await r.json();
    if (r.ok) { showToast('✅ Avaliação registrada!', 'success'); overlay.remove(); carregarCatalogo(); }
    else showToast(d.detail || 'Erro ao avaliar.', 'error');
  };
};

// ==================== PUBLICAR MEU MATERIAL (PREMIUM) ====================
window.abrirPublicar = async function() {
  if (!localStorage.getItem('auth_token')) { showToast('Faça login.', 'warning'); return; }
  const overlay = document.createElement('div');
  overlay.id = 'pub-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.innerHTML = `
    <div style="background:#313244;border-radius:16px;padding:24px;max-width:440px;width:100%;">
      <h3 style="color:#94e2d5;margin:0 0 4px;">📤 Publicar meu material</h3>
      <p style="font-size:0.75rem;color:#9399b2;margin-bottom:12px;">Compartilhe seus materiais com a comunidade. Materiais de usuários passam por moderação antes de aparecer.</p>
      <label style="font-size:0.75rem;color:#9399b2;">Tipo</label>
      <select id="pub-tipo" aria-label="Tipo de material" onchange="carregarMeusRefs()" style="width:100%;padding:9px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;margin-bottom:10px;">
        <option value="edital">📋 Edital verticalizado</option>
        <option value="caderno">📓 Caderno de questões</option>
        <option value="vademecum">📜 Lei (Vade Mécum)</option>
        <option value="deck_flashcards">🧠 Deck de flashcards</option>
        <option value="deck_questoes">❓ Pacote de questões</option>
        <option value="deck_sumulas">⚖️ Súmulas</option>
      </select>
      <label style="font-size:0.75rem;color:#9399b2;">Recurso</label>
      <select id="pub-ref" aria-label="Recurso a publicar" style="width:100%;padding:9px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;margin-bottom:10px;"><option value="">carregando...</option></select>
      <label style="font-size:0.75rem;color:#9399b2;">Título</label>
      <input id="pub-titulo" placeholder="Ex: Edital PF 2026 completo" aria-label="Título do material" style="width:100%;padding:9px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;margin-bottom:10px;">
      <label style="font-size:0.75rem;color:#9399b2;">Descrição</label>
      <input id="pub-descricao" placeholder="Breve descrição" aria-label="Descrição do material" style="width:100%;padding:9px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;margin-bottom:10px;">
      <label style="font-size:0.75rem;color:#9399b2;">Categoria</label>
      <input id="pub-categoria" value="Geral" aria-label="Categoria do material" style="width:100%;padding:9px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;margin-bottom:10px;">
      <div style="display:flex;gap:8px;">
        <div style="flex:1;">
          <label style="font-size:0.75rem;color:#9399b2;">Concurso (opcional)</label>
          <input id="pub-concurso" placeholder="Ex: PF 2026" aria-label="Concurso" style="width:100%;padding:9px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;margin-bottom:10px;">
        </div>
        <div style="flex:1;">
          <label style="font-size:0.75rem;color:#9399b2;">Cargo (opcional)</label>
          <input id="pub-cargo" placeholder="Ex: Delegado" aria-label="Cargo" style="width:100%;padding:9px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;margin-bottom:10px;">
        </div>
      </div>
      <label style="font-size:0.75rem;color:#9399b2;">Preço em créditos (0 = grátis)</label>
      <input id="pub-preco" type="number" min="0" step="1" value="0" aria-label="Preço em créditos" oninput="atualizarLiquidoVenda()" style="width:100%;padding:9px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;margin-bottom:4px;">
      <div id="pub-liquido" style="font-size:0.72rem;color:#9399b2;margin-bottom:14px;">Defina um preço para ver quanto você recebe.</div>
      <div id="pub-result" style="font-size:0.78rem;margin-bottom:8px;"></div>
      <div style="display:flex;gap:8px;">
        <button onclick="document.getElementById('pub-modal').remove()" style="flex:1;padding:9px;background:#45475a;color:#cdd6f4;border:none;border-radius:8px;cursor:pointer;">Cancelar</button>
        <button id="pub-enviar" onclick="enviarPublicacao()" style="flex:1;padding:9px;background:#94e2d5;color:#1e1e2e;border:none;border-radius:8px;font-weight:600;cursor:pointer;">Publicar</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  carregarMeusRefs();
  // Carrega a taxa da plataforma para mostrar o líquido do vendedor
  fetch('/api/catalogo/config', { headers: _headers() })
    .then(r => r.ok ? r.json() : null)
    .then(cfg => { _marketplaceTaxaPct = (cfg && typeof cfg.taxa_pct === 'number') ? cfg.taxa_pct : 20; atualizarLiquidoVenda(); })
    .catch(() => { _marketplaceTaxaPct = 20; });
};

// Taxa da plataforma (%) — carregada ao abrir o modal de publicar.
let _marketplaceTaxaPct = 20;

window.atualizarLiquidoVenda = function() {
  const el = document.getElementById('pub-liquido');
  if (!el) return;
  const preco = Math.max(0, parseInt(document.getElementById('pub-preco')?.value || '0', 10) || 0);
  if (preco <= 0) {
    el.textContent = 'Material gratuito — sem cobrança.';
    el.style.color = '#a6e3a1';
    return;
  }
  const liquido = Math.floor(preco * (1 - _marketplaceTaxaPct / 100));
  el.innerHTML = `Você recebe <strong style="color:#a6e3a1;">💎 ${liquido}</strong> por venda (taxa da plataforma: ${_marketplaceTaxaPct}%).`;
  el.style.color = '#9399b2';
};

window.carregarMeusRefs = async function() {
  const tipo = document.getElementById('pub-tipo').value;
  const refSel = document.getElementById('pub-ref');
  refSel.innerHTML = '<option value="">carregando...</option>';
  try {
    const res = await fetch(`/api/catalogo/meus/refs?tipo=${tipo}`, { headers: _headers() });
    if (res.status === 403) { document.getElementById('pub-result').innerHTML = '<span style="color:#f38ba8;">Apenas Premium pode publicar. Faça upgrade!</span>'; refSel.innerHTML = ''; return; }
    const data = await res.json();
    const refs = data.refs || [];
    refSel.innerHTML = refs.length ? refs.map(r => `<option value="${esc(r.ref)}">${esc(r.label)}</option>`).join('') : '<option value="">nenhum recurso deste tipo</option>';
  } catch (e) { refSel.innerHTML = '<option value="">erro</option>'; }
};

window.enviarPublicacao = async function() {
  const tipo = document.getElementById('pub-tipo').value;
  const ref = document.getElementById('pub-ref').value;
  const titulo = document.getElementById('pub-titulo').value.trim();
  const descricao = document.getElementById('pub-descricao').value.trim();
  const categoria = document.getElementById('pub-categoria').value.trim() || 'Geral';
  const concurso = document.getElementById('pub-concurso')?.value.trim() || '';
  const cargo = document.getElementById('pub-cargo')?.value.trim() || '';
  const preco_creditos = Math.max(0, parseInt(document.getElementById('pub-preco')?.value || '0', 10) || 0);
  if (tipo !== 'deck_sumulas' && !ref) { showToast('Selecione o recurso.', 'warning'); return; }
  if (!titulo) { showToast('Informe um título.', 'warning'); return; }

  const btn = document.getElementById('pub-enviar');
  btn.disabled = true; btn.textContent = '⏳...';
  try {
    const res = await fetch('/api/catalogo/publicar', {
      method: 'POST', headers: _headers(true),
      body: JSON.stringify({ tipo, titulo, descricao, categoria, ref, concurso, cargo, preco_creditos })
    });
    const data = await res.json();
    if (res.ok) {
      document.getElementById('pub-modal').remove();
      await alertModal(data.mensagem || 'Publicado!', { type: 'success', title: 'Sucesso' });
      carregarCatalogo();
    } else {
      document.getElementById('pub-result').innerHTML = `<span style="color:#f38ba8;">${esc(data.detail || 'Erro.')}</span>`;
      btn.disabled = false; btn.textContent = 'Publicar';
    }
  } catch (e) {
    showToast('Erro de conexão.', 'error');
    btn.disabled = false; btn.textContent = 'Publicar';
  }
};

// ==================== MINHAS VENDAS (VENDEDOR) ====================
window.abrirMinhasVendas = async function() {
  if (!localStorage.getItem('auth_token')) { showToast('Faça login para ver suas vendas.', 'warning'); return; }

  const overlay = document.createElement('div');
  overlay.id = 'vendas-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.innerHTML = `
    <div style="background:#313244;border-radius:16px;padding:24px;max-width:520px;width:100%;max-height:85vh;overflow-y:auto;">
      <h3 style="color:#f9e2af;margin:0 0 12px;">💰 Minhas vendas</h3>
      <div id="vendas-conteudo" style="font-size:0.85rem;color:#9399b2;">Carregando…</div>
      <div style="display:flex;justify-content:flex-end;margin-top:16px;">
        <button onclick="document.getElementById('vendas-modal').remove()" style="padding:9px 16px;background:#45475a;color:#cdd6f4;border:none;border-radius:8px;cursor:pointer;">Fechar</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

  const alvo = overlay.querySelector('#vendas-conteudo');
  try {
    const data = await fetch('/api/catalogo/vendas', { headers: _headers() }).then(r => r.json());
    const total = data.total_vendas || 0;
    const creditos = data.total_creditos_recebidos || 0;

    let html = `
      <div style="display:flex;gap:10px;margin-bottom:14px;">
        <div style="flex:1;background:#1e1e2e;border-radius:10px;padding:12px;text-align:center;">
          <div style="font-size:1.6rem;font-weight:700;color:#cdd6f4;">${total}</div>
          <div style="font-size:0.72rem;color:#9399b2;">venda(s)</div>
        </div>
        <div style="flex:1;background:#1e1e2e;border-radius:10px;padding:12px;text-align:center;">
          <div style="font-size:1.6rem;font-weight:700;color:#a6e3a1;">💎 ${creditos}</div>
          <div style="font-size:0.72rem;color:#9399b2;">créditos recebidos</div>
        </div>
      </div>`;

    if (!data.vendas || !data.vendas.length) {
      html += '<div style="text-align:center;padding:12px;color:#9399b2;">Você ainda não vendeu nenhum material.<br>Publique um pacote com preço para começar! 🚀</div>';
    } else {
      html += '<div style="font-size:0.78rem;color:#9399b2;font-weight:600;margin-bottom:6px;">Histórico</div>';
      html += data.vendas.map(v => {
        const quando = v.created_at ? new Date(v.created_at).toLocaleString('pt-BR') : '';
        return `
          <div style="border-bottom:1px solid #45475a;padding:8px 0;">
            <div style="color:#cdd6f4;font-size:0.85rem;font-weight:600;">${esc(v.titulo)}</div>
            <div style="font-size:0.74rem;color:#9399b2;">
              💎 ${v.creditos_recebidos} recebido(s) (de ${v.preco_creditos}) · comprador: ${esc(v.comprador_nome)} · ${esc(quando)}
            </div>
          </div>`;
      }).join('');
    }

    // Seção "Meus materiais publicados" com edição de preço.
    html += '<div id="meus-materiais-sec" style="margin-top:18px;"><div style="font-size:0.78rem;color:#9399b2;font-weight:600;margin-bottom:6px;">Meus materiais publicados</div><div style="color:#9399b2;font-size:0.8rem;">Carregando…</div></div>';
    alvo.innerHTML = html;

    // Carrega meus materiais (para permitir alterar preço)
    try {
      const meus = await fetch('/api/catalogo/meus', { headers: _headers() }).then(r => r.json());
      const sec = overlay.querySelector('#meus-materiais-sec');
      const itens = meus.itens || [];
      let mh = '<div style="font-size:0.78rem;color:#9399b2;font-weight:600;margin-bottom:6px;">Meus materiais publicados</div>';
      if (!itens.length) {
        mh += '<div style="color:#9399b2;font-size:0.8rem;">Você ainda não publicou materiais.</div>';
      } else {
        mh += itens.map(it => {
          const precoTxt = (it.preco_creditos || 0) > 0 ? `💎 ${it.preco_creditos}` : 'Grátis';
          const statusTxt = it.status && it.status !== 'aprovado' ? ` · <span style="color:#f9e2af;">${esc(it.status)}</span>` : '';
          return `
            <div style="display:flex;align-items:center;gap:8px;border-bottom:1px solid #45475a;padding:8px 0;">
              <div style="flex:1;min-width:0;">
                <div style="color:#cdd6f4;font-size:0.85rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${it.tipo_emoji} ${esc(it.titulo)}</div>
                <div style="font-size:0.74rem;color:#9399b2;">Preço: ${precoTxt} · ⬇️ ${it.downloads}${statusTxt}</div>
              </div>
              <button onclick="alterarPreco(${it.id}, ${it.preco_creditos || 0})" style="flex:0 0 auto;padding:6px 10px;background:#45475a;color:#cdd6f4;border:none;border-radius:6px;cursor:pointer;font-size:0.78rem;">💲 Preço</button>
            </div>`;
        }).join('');
      }
      if (sec) sec.innerHTML = mh;
    } catch (e) {
      const sec = overlay.querySelector('#meus-materiais-sec');
      if (sec) sec.innerHTML = '<span style="color:#f38ba8;">Erro ao carregar seus materiais.</span>';
    }
  } catch (e) {
    alvo.innerHTML = '<span style="color:#f38ba8;">Erro ao carregar suas vendas.</span>';
  }
};

// Altera o preço de um material publicado (grátis↔pago) via PATCH.
window.alterarPreco = async function(itemId, precoAtual) {
  const entrada = await promptModal(
    'Definir preço em créditos (0 = grátis):',
    { title: '💲 Alterar preço', defaultValue: String(precoAtual || 0) }
  );
  if (entrada === null) return;  // cancelado
  const novo = parseInt(entrada, 10);
  if (isNaN(novo) || novo < 0) { showToast('Informe um número válido (0 ou mais).', 'warning'); return; }
  try {
    const res = await fetch(`/api/catalogo/${itemId}`, {
      method: 'PATCH', headers: _headers(true), body: JSON.stringify({ preco_creditos: novo })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`✅ Preço atualizado: ${data.preco_creditos > 0 ? '💎 ' + data.preco_creditos : 'Grátis'}`, 'success');
      document.getElementById('vendas-modal')?.remove();
      abrirMinhasVendas();      // recarrega
      carregarCatalogo();       // reflete na grade
    } else {
      showToast(data.detail || 'Erro ao alterar preço.', 'error');
    }
  } catch (e) {
    showToast('Erro de conexão.', 'error');
  }
};

// Init
carregarCatalogo();
