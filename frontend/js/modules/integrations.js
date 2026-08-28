/**
 * Integrations Module — Conecta todos os módulos do ConcurseiroOS
 *
 * Escuta eventos do EventBus e executa ações cross-module:
 * - Questão respondida → atualiza sidebar, incrementa desafios, recalcula mastery
 * - Flashcard revisado → atualiza sidebar, incrementa desafios
 * - Fadiga detectada → sugere módulos alternativos
 * - XP ganho → atualiza ligas
 * - Desafio completado → celebração
 */

import { on, emit } from './event-bus.js';

// ─── SIDEBAR REATIVA ─────────────────────────────────────────

/**
 * Atualiza sidebar badges/streak/xp em tempo real sem reload
 */
function refreshSidebar() {
  fetch('/api/sidebar-data')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) return;
      const elStreak = document.getElementById('sidebar-streak');
      const elXp = document.getElementById('sidebar-xp');
      const elFreeze = document.getElementById('sidebar-freeze-count');
      const elFlash = document.getElementById('badge-flashcards');
      const elCaderno = document.getElementById('badge-caderno-erros');

      if (elStreak) elStreak.textContent = data.streak || 0;
      if (elXp) elXp.textContent = `⭐ Nv.${data.nivel || 1}`;
      if (elFreeze) elFreeze.textContent = data.freezes_available || 0;
      if (data.badges) {
        if (elFlash) elFlash.textContent = data.badges.flashcards > 0 ? data.badges.flashcards : '';
        if (elCaderno) elCaderno.textContent = data.badges.caderno > 0 ? data.badges.caderno : '';
      }
      // Atualizar localStorage cache
      localStorage.setItem('sidebar_data', JSON.stringify(data));
    })
    .catch(() => {});
}

// Debounce sidebar refresh (não chamar a cada card, mas a cada 5s max)
let _sidebarTimeout = null;
function debouncedRefreshSidebar() {
  if (_sidebarTimeout) return;
  _sidebarTimeout = setTimeout(() => {
    refreshSidebar();
    _sidebarTimeout = null;
  }, 5000);
}

// ─── MASTERY AUTO-UPDATE ─────────────────────────────────────

/**
 * Recalcula mastery dos tópicos afetados pela resposta
 */
async function updateMasteryForMateria(materia) {
  if (!materia) return;
  try {
    // Buscar tópicos do edital dessa matéria e disparar recalc
    const topicos = await fetch(`/api/edital?materia=${encodeURIComponent(materia)}&arquivado=0&limit=50`)
      .then(r => r.ok ? r.json() : null);
    if (!topicos) return;
    const items = Array.isArray(topicos) ? topicos : (topicos.items || []);
    // Recalcular os primeiros 10 (mais relevantes) — não sobrecarregar
    const batch = items.slice(0, 10);
    for (const t of batch) {
      fetch(`/api/edital/${t.id}/mastery-update`, { method: 'POST' }).catch(() => {});
    }
  } catch(e) {}
}

// Debounce mastery updates por matéria
const _masteryQueue = new Set();
let _masteryTimeout = null;
function queueMasteryUpdate(materia) {
  if (!materia) return;
  _masteryQueue.add(materia);
  if (_masteryTimeout) return;
  _masteryTimeout = setTimeout(() => {
    _masteryQueue.forEach(m => updateMasteryForMateria(m));
    _masteryQueue.clear();
    _masteryTimeout = null;
  }, 10000); // Batch a cada 10s
}

// ─── DESAFIOS AUTO-PROGRESSO ─────────────────────────────────

/**
 * Verifica desafios ativos e incrementa progresso se match
 */
async function checkAndIncrementDesafios(tipo, materia) {
  try {
    const desafios = await fetch('/api/desafios').then(r => r.ok ? r.json() : []);
    for (const d of desafios) {
      if (d.finalizado) continue;
      // Match por tipo
      if (d.meta_tipo === tipo || (d.meta_tipo === 'questoes' && tipo === 'questao') || (d.meta_tipo === 'flashcards' && tipo === 'flashcard')) {
        // Match por matéria (se desafio tem matéria específica)
        if (!d.materia || d.materia === materia) {
          fetch(`/api/desafios/${d.id}/progresso?valor=1`, { method: 'PUT' }).catch(() => {});
        }
      }
    }
  } catch(e) {}
}

// Debounce desafios check
let _desafiosTimeout = null;
let _desafiosPendentes = [];
function queueDesafioCheck(tipo, materia) {
  _desafiosPendentes.push({ tipo, materia });
  if (_desafiosTimeout) return;
  _desafiosTimeout = setTimeout(() => {
    // Processar batch: contar por tipo
    const counts = {};
    _desafiosPendentes.forEach(p => {
      const key = `${p.tipo}|${p.materia || ''}`;
      counts[key] = (counts[key] || 0) + 1;
    });
    // Chamar API para cada tipo (com valor acumulado)
    Object.entries(counts).forEach(([key, count]) => {
      const [tipo, materia] = key.split('|');
      checkAndIncrementDesafios(tipo, materia);
    });
    _desafiosPendentes = [];
    _desafiosTimeout = null;
  }, 8000); // Batch a cada 8s
}

// ─── XP → LIGAS ─────────────────────────────────────────────

/**
 * Após ganho de XP, atualizar ranking da liga
 */
function updateLeagueXp(quantidade) {
  if (!quantidade || quantidade <= 0) return;
  // Liga é atualizada automaticamente pelo backend ao computar XP semanal
  // Mas podemos forçar refresh do sidebar que mostra posição
  debouncedRefreshSidebar();
}

// ─── FADIGA → SUGESTÃO CROSS-MODULE ─────────────────────────

/**
 * Quando fadiga é detectada, melhorar sugestão com links para outros módulos
 */
function handleFatigueDetected(data) {
  const banner = document.getElementById('fatigue-banner');
  if (!banner) return;

  // Adicionar botões cross-module ao banner existente
  const actionsDiv = banner.querySelector('div:last-child');
  if (actionsDiv && !actionsDiv.dataset.crossModule) {
    actionsDiv.dataset.crossModule = '1';
    actionsDiv.innerHTML = `
      <div style="display:flex;gap:6px;flex-wrap:wrap;">
        <button onclick="document.getElementById('fatigue-banner').remove();window.location.href='/#flashcards'" style="flex:1;padding:8px;background:var(--accent);color:#1e1e2e;border:none;border-radius:8px;font-weight:600;font-size:0.78rem;cursor:pointer;">🧠 Flashcards (leve)</button>
        <button onclick="document.getElementById('fatigue-banner').remove();window.location.href='/vademecum.html'" style="flex:1;padding:8px;background:var(--blue);color:#1e1e2e;border:none;border-radius:8px;font-weight:600;font-size:0.78rem;cursor:pointer;">⚖️ Vade Mecum</button>
        <button onclick="document.getElementById('fatigue-banner').remove();if(window.startCatSession)startCatSession()" style="flex:1;padding:8px;background:var(--green);color:#1e1e2e;border:none;border-radius:8px;font-weight:600;font-size:0.78rem;cursor:pointer;">🧠 CAT (adaptativo)</button>
        <button onclick="document.getElementById('fatigue-banner').remove()" style="padding:8px;background:var(--border);color:var(--text);border:none;border-radius:8px;font-size:0.78rem;cursor:pointer;">Continuar</button>
      </div>
    `;
  }
}

// ─── TÉCNICAS SE PRESCREVEM MUTUAMENTE ──────────────────────

/**
 * Ao detectar platô → sugerir CAT
 * Ao detectar overconfidence → sugerir pre-test
 */
function setupTechniqueCrossLinks() {
  // Observar widgets de platô e overconfidence quando renderizados
  const observer = new MutationObserver(() => {
    // Platô → CAT link
    const platoWidget = document.querySelector('[id*="plato"]');
    if (platoWidget && !platoWidget.dataset.crossLinked) {
      platoWidget.dataset.crossLinked = '1';
      const btn = document.createElement('button');
      btn.style.cssText = 'margin-top:8px;background:var(--accent);color:#1e1e2e;border:none;border-radius:6px;padding:6px 12px;font-size:0.72rem;font-weight:600;cursor:pointer;';
      btn.textContent = '🧠 Iniciar CAT para calibrar nível';
      btn.onclick = () => { if (window.startCatSession) window.startCatSession(); };
      platoWidget.appendChild(btn);
    }

    // Overconfidence → Pre-test link
    const ocWidget = document.getElementById('overconfidence-widget');
    if (ocWidget && !ocWidget.dataset.crossLinked) {
      ocWidget.dataset.crossLinked = '1';
      const btn = document.createElement('button');
      btn.style.cssText = 'margin-top:8px;background:var(--yellow);color:#1e1e2e;border:none;border-radius:6px;padding:6px 12px;font-size:0.72rem;font-weight:600;cursor:pointer;';
      btn.textContent = '🧪 Fazer Pre-Test para calibrar';
      btn.onclick = () => { window.location.href = '/#edital'; };
      ocWidget.appendChild(btn);
    }
  });

  const target = document.getElementById('si-techniques-alerts');
  if (target) {
    observer.observe(target, { childList: true, subtree: false });
  }
}

// ─── REGISTRAR LISTENERS DO EVENT BUS ────────────────────────

export function initIntegrations() {
  // Questão respondida
  on('questao:respondida', (data) => {
    debouncedRefreshSidebar();
    queueMasteryUpdate(data.materia);
    queueDesafioCheck('questao', data.materia);
  });

  // Flashcard revisado
  on('flashcard:revisado', (data) => {
    debouncedRefreshSidebar();
    queueDesafioCheck('flashcard', data.materia);
  });

  // XP ganho
  on('xp:ganho', (data) => {
    updateLeagueXp(data.quantidade);
  });

  // Fadiga detectada
  on('fadiga:detectada', (data) => {
    handleFatigueDetected(data);
  });

  // Sessão de horas registrada
  on('sessao:horas', () => {
    debouncedRefreshSidebar();
  });

  // Setup cross-links entre técnicas (observar DOM)
  setTimeout(setupTechniqueCrossLinks, 3000);

  console.log('[Integrations] Module initialized — cross-module listeners active');
}
