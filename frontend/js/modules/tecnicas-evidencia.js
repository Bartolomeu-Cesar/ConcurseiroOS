/**
 * Técnicas de estudo baseadas em evidência (frontend).
 * Expõe 5 técnicas no painel Treinador do dashboard:
 * - JOL preditivo (Judgment of Learning)
 * - Closed-book antes de open-book
 * - Interpolated Testing (mini-teste na leitura)
 * - Elaborative Interrogation encadeada (cadeia de "por quê")
 * - Retrieval-Induced Forgetting (alerta)
 *
 * Padrão: cada função renderX(container) monta a UI; funções usadas em onclick
 * inline são expostas em window. Toasts via showToast.
 */
import { showToast } from './toast.js';

const SI = '/api/study-intelligence';

function authHeaders() {
  const token = localStorage.getItem('auth_token');
  return { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function getJSON(url) {
  const r = await fetch(url, { headers: authHeaders() });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function postJSON(url, body) {
  const r = await fetch(url, { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) });
  return r;
}

// Cache das matérias (compartilhado entre os cards).
let _materiasCache = null;
async function getMaterias() {
  if (_materiasCache) return _materiasCache;
  try {
    _materiasCache = await getJSON('/api/questoes/materias');
  } catch {
    _materiasCache = [];
  }
  return _materiasCache;
}

function materiaSelectHtml(id) {
  return `<select id="${id}" aria-label="Matéria" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px;font-size:0.82rem;">
    <option value="">Escolha uma matéria...</option>
  </select>`;
}

async function fillMateriaSelect(id) {
  const sel = document.getElementById(id);
  if (!sel) return;
  const materias = await getMaterias();
  sel.innerHTML = '<option value="">Escolha uma matéria...</option>' +
    materias.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
}

// ─── 1. JOL preditivo ────────────────────────────────────────────────────────
export async function renderJolCard(container) {
  if (!container) return;
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:8px;">
      <input id="jol-item" type="text" placeholder="Tópico/conceito (ex: Princípios da Adm.)"
        aria-label="Item do JOL" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px;font-size:0.82rem;">
      <label style="font-size:0.8rem;color:var(--text-sub);">Chance de lembrar no futuro: <strong id="jol-val">70</strong>%</label>
      <input id="jol-pred" type="range" min="0" max="100" value="70" step="5"
        oninput="document.getElementById('jol-val').textContent=this.value" style="width:100%;accent-color:var(--accent);">
      <button onclick="window._jolRegistrar()" style="background:var(--accent);color:var(--bg);border:none;border-radius:6px;padding:7px 12px;font-size:0.82rem;font-weight:600;cursor:pointer;">💾 Registrar previsão</button>
      <div id="jol-resumo" style="font-size:0.8rem;color:var(--text-sub);margin-top:4px;"></div>
    </div>`;
  _carregarResumoJol();
}

async function _carregarResumoJol() {
  const el = document.getElementById('jol-resumo');
  if (!el) return;
  try {
    const r = await getJSON(`${SI}/jol/resumo`);
    if (r.total_confrontadas > 0) {
      el.innerHTML = `📊 ${r.total_confrontadas} confrontadas · erro médio ${r.erro_medio}% · viés: <strong>${esc(r.vies)}</strong> · ${r.pendentes} pendente(s)`;
    } else {
      el.textContent = `Nenhuma previsão confrontada ainda${r.pendentes ? ` · ${r.pendentes} pendente(s)` : ''}.`;
    }
  } catch { el.textContent = ''; }
}

window._jolRegistrar = async function () {
  const item = (document.getElementById('jol-item') || {}).value || '';
  const pred = parseInt((document.getElementById('jol-pred') || {}).value || '70', 10);
  if (!item.trim()) { showToast('Informe o tópico/conceito.', 'warning'); return; }
  const r = await postJSON(`${SI}/jol`, { item_tipo: 'topico', item_ref: item.trim(), predicao: pred });
  if (!r.ok) { showToast('Não foi possível registrar.', 'error'); return; }
  showToast('🔮 Previsão registrada! Confronte após estudar/testar.', 'success');
  _carregarResumoJol();
};

// ─── 2. Closed-book ────────────────────────────────────────────────────────────
export async function renderClosedBookCard(container) {
  if (!container) return;
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:8px;">
      ${materiaSelectHtml('cb-materia')}
      <button onclick="window._cbIniciar()" style="background:var(--blue);color:var(--bg);border:none;border-radius:6px;padding:7px 12px;font-size:0.82rem;font-weight:600;cursor:pointer;">📕 Iniciar recall (livro fechado)</button>
      <div id="cb-area" style="font-size:0.82rem;color:var(--text-sub);"></div>
    </div>`;
  fillMateriaSelect('cb-materia');
}

window._cbIniciar = async function () {
  const materia = (document.getElementById('cb-materia') || {}).value || '';
  if (!materia) { showToast('Escolha uma matéria.', 'warning'); return; }
  const area = document.getElementById('cb-area');
  try {
    const d = await getJSON(`${SI}/closed-book?materia=${encodeURIComponent(materia)}`);
    const ancoras = (d.ancoras || []).map(a => `<li>${esc(a.texto)}</li>`).join('');
    area.innerHTML = `
      <p style="margin:8px 0;color:var(--text);">${esc(d.instrucao)}</p>
      ${ancoras ? `<ul style="margin:6px 0 8px 1.1rem;">${ancoras}</ul>` : ''}
      <label style="font-size:0.8rem;">Quanto você lembrou? <strong id="cb-val">50</strong>%</label>
      <input id="cb-recall" type="range" min="0" max="100" value="50" step="5"
        oninput="document.getElementById('cb-val').textContent=this.value" style="width:100%;accent-color:var(--blue);">
      <button onclick="window._cbLiberar('${esc(materia)}')" style="background:var(--green);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;font-size:0.8rem;font-weight:600;cursor:pointer;margin-top:6px;">📖 Liberar material (open-book)</button>`;
  } catch { showToast('Erro ao iniciar closed-book.', 'error'); }
};

window._cbLiberar = async function (materia) {
  const recall = parseInt((document.getElementById('cb-recall') || {}).value || '0', 10);
  const r = await postJSON(`${SI}/closed-book/resultado`, { materia, auto_recall: recall });
  if (!r.ok) { showToast('Erro ao registrar.', 'error'); return; }
  const d = await r.json();
  showToast(d.mensagem || 'Material liberado!', 'success', 4000);
  const area = document.getElementById('cb-area');
  if (area) area.innerHTML = `<p style="color:var(--green);">${esc(d.mensagem)}</p>`;
};

// ─── 3. Interpolated Testing ────────────────────────────────────────────────────
export async function renderInterpolatedCard(container) {
  if (!container) return;
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:8px;">
      ${materiaSelectHtml('it-materia')}
      <button onclick="window._itGerar()" style="background:var(--peach,#fab387);color:var(--bg);border:none;border-radius:6px;padding:7px 12px;font-size:0.82rem;font-weight:600;cursor:pointer;">⏸️ Puxar mini-teste</button>
      <div id="it-area" style="font-size:0.82rem;color:var(--text-sub);"></div>
    </div>`;
  fillMateriaSelect('it-materia');
}

window._itGerar = async function () {
  const materia = (document.getElementById('it-materia') || {}).value || '';
  if (!materia) { showToast('Escolha uma matéria.', 'warning'); return; }
  const area = document.getElementById('it-area');
  try {
    const d = await getJSON(`${SI}/interpolated-test?materia=${encodeURIComponent(materia)}`);
    if (!d.disponivel) { area.innerHTML = `<p>${esc(d.mensagem)}</p>`; return; }
    const itens = d.itens.map((it, i) => `
      <div style="border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:6px;">
        <div style="font-weight:600;color:var(--text);">${i + 1}. ${esc(it.pergunta)}</div>
        <button onclick="this.nextElementSibling.style.display='block';this.style.display='none';" style="background:var(--surface1,#45475a);color:var(--text);border:none;border-radius:6px;padding:4px 10px;font-size:0.78rem;cursor:pointer;margin-top:6px;">Revelar resposta</button>
        <div style="display:none;margin-top:6px;color:var(--green);">${esc(it.resposta)}</div>
      </div>`).join('');
    area.innerHTML = `<p style="margin:8px 0;color:var(--text);">${esc(d.instrucao)}</p>${itens}`;
  } catch { showToast('Erro ao puxar mini-teste.', 'error'); }
};

// ─── 4. Elaborative Interrogation encadeada ─────────────────────────────────────
export function renderElaborativeChainCard(container) {
  if (!container) return;
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:8px;">
      <input id="ec-conceito" type="text" placeholder="Conceito (ex: Controle de constitucionalidade)"
        aria-label="Conceito" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px;font-size:0.82rem;">
      <button onclick="window._ecGerar()" style="background:var(--mauve,#cba6f7);color:var(--bg);border:none;border-radius:6px;padding:7px 12px;font-size:0.82rem;font-weight:600;cursor:pointer;">❓ Gerar cadeia de "por quê"</button>
      <div id="ec-area" style="font-size:0.82rem;color:var(--text-sub);"></div>
    </div>`;
}

window._ecGerar = async function () {
  const conceito = (document.getElementById('ec-conceito') || {}).value || '';
  if (!conceito.trim()) { showToast('Informe um conceito.', 'warning'); return; }
  const area = document.getElementById('ec-area');
  try {
    const d = await getJSON(`${SI}/elaborative-chain?conceito=${encodeURIComponent(conceito.trim())}`);
    const niveis = (d.niveis || []).map(n => `
      <div style="border-left:3px solid var(--mauve,#cba6f7);padding:6px 10px;margin-top:6px;">
        <div style="font-weight:600;color:var(--text);">Nível ${n.nivel}</div>
        <div>${esc(n.prompt)}</div>
      </div>`).join('');
    area.innerHTML = niveis;
  } catch { showToast('Erro ao gerar cadeia.', 'error'); }
};

// ─── 5. RIF alert ────────────────────────────────────────────────────────────
export async function renderRifCard(container) {
  if (!container) return;
  container.innerHTML = `<p style="font-size:0.82rem;color:var(--text-sub);">Carregando alertas...</p>`;
  try {
    const d = await getJSON(`${SI}/retrieval-induced-forgetting`);
    if (!d.total_alertas) {
      container.innerHTML = `<p style="font-size:0.82rem;color:var(--green);">${esc(d.mensagem)}</p>`;
      return;
    }
    const linhas = d.alertas.map(a => `
      <div style="border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:6px;">
        <div style="font-weight:600;color:var(--text);">${esc(a.materia)} · ${esc(a.topico)}</div>
        <div style="font-size:0.78rem;color:var(--text-sub);">${a.praticas} prática(s) vs ${a.praticas_dominante} do irmão dominante</div>
        <div style="font-size:0.8rem;color:var(--peach,#fab387);">${esc(a.sugestao)}</div>
      </div>`).join('');
    container.innerHTML = `<p style="font-size:0.82rem;color:var(--text-sub);">${esc(d.mensagem)}</p>${linhas}`;
  } catch {
    container.innerHTML = `<p style="font-size:0.82rem;color:var(--red,#f38ba8);">Erro ao carregar alertas.</p>`;
  }
}

// Orquestrador: renderiza todos os cards das técnicas novas.
export function renderTecnicasEvidencia() {
  renderJolCard(document.getElementById('jol-container'));
  renderClosedBookCard(document.getElementById('closedbook-container'));
  renderInterpolatedCard(document.getElementById('interpolated-container'));
  renderElaborativeChainCard(document.getElementById('elaborative-chain-container'));
  renderRifCard(document.getElementById('rif-container'));
}
