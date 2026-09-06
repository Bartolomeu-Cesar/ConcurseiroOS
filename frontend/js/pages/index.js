// index.js - Extracted from index.html inline scripts
import { alertModal, escapeHtml, escapeAttr } from '../modules/utils.js';

// ===== Sidebar navigation =====
function navigateTo(tabId, btn) {
  // Hide all tabs
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  // Show target
  const target = document.getElementById(tabId);
  if (target) target.classList.add('active');
  // Update sidebar active state
  document.querySelectorAll('.sidebar-nav button, .sidebar-nav a').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  // Update bottom nav active state
  document.querySelectorAll('.bottom-nav-items button, .bottom-nav-items a').forEach(b => b.classList.remove('active'));
  const bottomBtn = document.querySelector(`.bottom-nav-items [data-nav="${tabId}"]`);
  if (bottomBtn) bottomBtn.classList.add('active');
  // Close sidebar on mobile
  closeSidebar();
  // Save state
  localStorage.setItem('concurseiro_active_tab', tabId);
}
window.navigateTo = navigateTo;

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebar-overlay').classList.toggle('open');
}
window.toggleSidebar = toggleSidebar;

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (sidebar) sidebar.classList.remove('open');
  if (overlay) overlay.classList.remove('open');
}
window.closeSidebar = closeSidebar;

// Restore last active tab
// Restore active tab from hash or localStorage
// Modules are deferred, so DOM is ready when this runs
(function initTabNavigation() {
  const hash = window.location.hash.replace('#', '');
  const hashTabMap = {
    'ciclo': 'tab-ciclo',
    'trilha': 'tab-trilha',
    'edital': 'tab-edital',
    'flashcards': 'tab-flashcards',
    'sumulas': 'tab-sumulas',
    'pdfs': 'tab-pdfs',
  };

  if (hash && hashTabMap[hash]) {
    const tabId = hashTabMap[hash];
    navigateTo(tabId);
    // Clean hash from URL without reload
    history.replaceState(null, '', '/');
    // Clean redirect markers
    localStorage.removeItem('concurseiro_active_tab');
    localStorage.removeItem('concurseiro_tab_redirect');
  } else {
    const saved = localStorage.getItem('concurseiro_active_tab');
    const marker = localStorage.getItem('concurseiro_tab_redirect');
    if (saved && marker) {
      navigateTo(saved);
      // Clear after use
      localStorage.removeItem('concurseiro_active_tab');
      localStorage.removeItem('concurseiro_tab_redirect');
    }
  }
  // Load user info for avatar
  loadUserAvatar();
  // Load recent PDFs
  loadRecentPdfs();
  // Load CTA "Continuar Estudando"
  loadCtaContinuarEstudando();
  // Check milestones (celebration modal para marcos não-vistos)
  checkNewMilestones();
})();

// ===== CTA: Continuar Estudando =====
function loadCtaContinuarEstudando() {
  const container = document.getElementById('cta-continuar-estudando');
  if (!container) return;

  // Priorizar sugestão do calendário (consistente com o grid), fallback para ciclo
  fetch('/api/calendario/agora')
    .then(r => r.ok ? r.json() : null)
    .then(agora => {
      if (agora && agora.sugestao && agora.sugestao.tipo !== 'pausa') {
        container.style.display = 'block';
        const materiaEl = document.getElementById('cta-materia');
        const detailEl = document.getElementById('cta-detail');
        const subtitleEl = document.getElementById('cta-subtitle');
        const iconEl = document.getElementById('cta-icon');

        materiaEl.textContent = agora.sugestao.materia;
        detailEl.textContent = agora.sugestao.motivo || `${agora.sugestao.tempo_min}min planejados`;

        const hour = new Date().getHours();
        if (hour < 12) { subtitleEl.textContent = '☀️ Bom dia! Próxima atividade:'; iconEl.textContent = '📖'; }
        else if (hour < 18) { subtitleEl.textContent = '☀️ Boa tarde! Continue de onde parou:'; iconEl.textContent = '📚'; }
        else { subtitleEl.textContent = '🌙 Boa noite! Sessão noturna:'; iconEl.textContent = '🌟'; }

        container.dataset.materia = agora.sugestao.materia;
        return;
      }
      // Fallback: usar ciclo/proximo
      return fetch('/api/ciclo/proximo').then(r => r.json()).then(data => {
        if (!data || !data.materia || data.materia === 'Nenhuma matéria no ciclo') {
          container.style.display = 'none';
          return;
        }
        container.style.display = 'block';
        document.getElementById('cta-materia').textContent = data.materia;
        const horasCumpridas = data.horas_cumpridas || 0;
        const horasAlvo = data.horas_alvo || 1;
        const pct = Math.min(100, Math.round((horasCumpridas / horasAlvo) * 100));
        document.getElementById('cta-detail').textContent = `${horasCumpridas.toFixed(1)}h / ${horasAlvo}h no ciclo (${pct}%)`;

        const hour = new Date().getHours();
        if (hour < 12) { document.getElementById('cta-subtitle').textContent = '☀️ Bom dia! Próxima matéria:'; document.getElementById('cta-icon').textContent = '📖'; }
        else if (hour < 18) { document.getElementById('cta-subtitle').textContent = '☀️ Boa tarde! Continue:'; document.getElementById('cta-icon').textContent = '📚'; }
        else { document.getElementById('cta-subtitle').textContent = '🌙 Boa noite! Sessão noturna:'; document.getElementById('cta-icon').textContent = '🌟'; }
        container.dataset.materia = data.materia;
      });
    })
    .catch(() => { container.style.display = 'none'; });
}

function ctaContinuarEstudando() {
  // Navegar para a aba Ciclo e iniciar timer
  navigateTo('tab-ciclo');
  // Dar tempo para o tab renderizar
  setTimeout(() => {
    // Tentar selecionar a matéria no ciclo
    const materia = document.getElementById('cta-continuar-estudando')?.dataset?.materia;
    if (materia && window.startCicloTimer) {
      window.startCicloTimer(materia);
    }
  }, 300);
}
window.ctaContinuarEstudando = ctaContinuarEstudando;

// ===== MILESTONES: Celebration Modal =====
async function checkNewMilestones() {
  try {
    const data = await fetch('/api/milestones/check').then(r => r.json());
    if (data.new_milestones && data.new_milestones.length > 0) {
      // Delay para não conflitar com CTA loading
      setTimeout(() => {
        data.new_milestones.forEach((m, i) => {
          setTimeout(() => showMilestoneCelebration(m), i * 3000);
        });
      }, 1500);
    }
  } catch (e) {}
}

function showMilestoneCelebration(milestone) {
  const overlay = document.createElement('div');
  overlay.className = 'milestone-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.3s ease;';
  overlay.innerHTML = `
    <div style="background:var(--bg-elevated, #45475a);border-radius:20px;padding:32px;max-width:400px;width:90%;text-align:center;animation:scaleIn 0.4s ease;">
      <div style="font-size:3.5rem;margin-bottom:12px;animation:bounce 0.6s ease;">${milestone.emoji}</div>
      <h2 style="color:var(--accent, #cba6f7);margin-bottom:8px;font-size:1.3rem;">${milestone.titulo}</h2>
      <p style="color:var(--text, #cdd6f4);font-size:0.92rem;margin-bottom:6px;">${milestone.msg}</p>
      <div style="font-size:2.2rem;font-weight:800;color:var(--green, #a6e3a1);margin:12px 0;">${milestone.pct}%</div>
      <button onclick="this.closest('.milestone-overlay').remove()"
        style="background:var(--accent, #cba6f7);color:var(--bg, #1e1e2e);border:none;border-radius:10px;padding:12px 28px;font-weight:700;cursor:pointer;font-size:0.95rem;">
        Continuar 💪
      </button>
    </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  // Auto-remove após 10s
  setTimeout(() => { if (overlay.parentNode) overlay.remove(); }, 10000);
}

function loadRecentPdfs() {
  fetch('/api/progress/recentes?limit=5')
    .then(r => r.json())
    .then(data => {
      const list = document.getElementById('recent-pdfs-list');
      const count = document.getElementById('recent-pdfs-count');
      if (!list) return;
      if (!data || !data.length) {
        list.innerHTML = '<div style="color:var(--text-muted, #6c7086);font-size:0.82rem;">Nenhum PDF lido ainda. Abra um PDF para começar!</div>';
        return;
      }
      if (count) count.textContent = data.length + ' recentes';
      list.innerHTML = data.map(pdf => {
        const pct = pdf.progresso_pct;
        const barColor = pct >= 80 ? 'var(--green, #a6e3a1)' : pct >= 40 ? 'var(--blue, #89b4fa)' : 'var(--yellow, #f9e2af)';
        return `<a href="viewer.html?path=${encodeURIComponent(pdf.path)}" style="display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--bg, #1e1e2e);border-radius:8px;text-decoration:none;transition:background 0.2s;cursor:pointer;" title="${escapeAttr(pdf.nome)}" onmouseover="this.style.background='var(--bg-elevated, #45475a)'" onmouseout="this.style.background='var(--bg, #1e1e2e)'">
          <div style="font-size:1.2rem;">📄</div>
          <div style="flex:1;min-width:0;">
            <div style="font-size:0.82rem;font-weight:600;color:var(--text, #cdd6f4);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(pdf.nome)}</div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:4px;">
              <div style="flex:1;height:4px;background:var(--bg-elevated, #45475a);border-radius:2px;overflow:hidden;">
                <div style="height:100%;width:${pct}%;background:${barColor};border-radius:2px;"></div>
              </div>
              <span style="font-size:0.7rem;color:var(--text-sub, #9399b2);white-space:nowrap;">${pdf.current_page}/${pdf.total_pages} (${pct}%)</span>
            </div>
          </div>
        </a>`;
      }).join('');
    })
    .catch(() => {
      const list = document.getElementById('recent-pdfs-list');
      if (list) list.innerHTML = '<div style="color:var(--text-muted, #6c7086);font-size:0.82rem;">Não foi possível carregar os PDFs recentes. Verifique a conexão.</div>';
    });
}

function loadUserAvatar() {
  fetch('/api/auth/me')
    .then(r => r.json())
    .then(user => {
      // Atualizar auth_user no localStorage com role atualizado
      const stored = JSON.parse(localStorage.getItem('auth_user') || '{}');
      if (user.role) stored.role = user.role;
      if (user.plano) stored.plano = user.plano;
      localStorage.setItem('auth_user', JSON.stringify({...stored, ...user}));

      const nameEl = document.getElementById('user-name-display');
      const avatarEl = document.getElementById('user-avatar-initials');
      const nome = user.nome || user.email || 'Estudante';
      // Show first name
      const firstName = nome.split(' ')[0];
      if (nameEl) nameEl.textContent = firstName;
      // Show initials in avatar circle
      if (avatarEl) {
        const initials = nome.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
        avatarEl.textContent = initials || '👤';
      }
    })
    .catch(() => {});
}

// Global search
function globalSearch(query) {
  if (!query.trim()) return;
  fetch(`/api/search?q=${encodeURIComponent(query)}`)
    .then(r => r.json())
    .then(async results => {
      if (results.length === 0) {
        if (window.toast) window.toast('Nenhum resultado encontrado.', 'warning');
        return;
      }
      // Show results in a modal
      const text = results.slice(0, 10).map(r =>
        `[${r.source}] ${r.title || ''}: ${r.snippet || ''}`
      ).join('\n\n');
      await alertModal(`🔍 ${results.length} resultado(s):\n\n${text}`, { title: 'Resultados da Busca', type: 'info' });
    });
}
window.globalSearch = globalSearch;

// ===== CICLO VISÕES — moved to modules/ciclo.js =====
// switchCicloView is now exported from ciclo.js and registered in app.js

// Load ciclo "ontem" card
function loadCicloOntem() {
  fetch('/api/ciclo/ontem')
    .then(r => r.json())
    .then(data => {
      const panel = document.getElementById('ciclo-ontem-panel');
      if (!panel) return;
      if (!data.teve_plano && !data.estudou) { panel.style.display = 'none'; return; }

      panel.style.display = 'flex';
      document.getElementById('ciclo-ontem-dia').textContent = data.dia_semana;
      document.getElementById('ciclo-ontem-msg').textContent = data.mensagem;
      document.getElementById('ciclo-ontem-horas').textContent = data.total_estudado;
      document.getElementById('ciclo-ontem-plan').textContent = data.total_planejado;
      document.getElementById('ciclo-ontem-quest').textContent = data.questoes;
      document.getElementById('ciclo-ontem-flash').textContent = data.flashcards;

      const scoreEl = document.getElementById('ciclo-ontem-score');
      scoreEl.textContent = data.score_dia + '%';
      scoreEl.style.color = data.score_dia >= 80 ? '#a6e3a1' : data.score_dia >= 50 ? '#fab387' : '#f38ba8';
      panel.style.borderLeftColor = data.score_dia >= 80 ? '#a6e3a1' : data.score_dia >= 50 ? '#fab387' : '#f38ba8';

      const materiasEl = document.getElementById('ciclo-ontem-materias');
      if (data.comparativo.length > 0) {
        materiasEl.innerHTML = data.comparativo.map(m => `
          <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #313244;">
            <span>${m.status}</span>
            <span style="flex:1;font-size:0.85rem;font-weight:500;">${m.materia}</span>
            <span style="font-size:0.78rem;color:#9399b2;">${m.horas_estudadas}/${m.horas_planejadas}h</span>
            <div style="width:60px;height:5px;background:#45475a;border-radius:3px;overflow:hidden;">
              <div style="height:100%;width:${m.pct_cumprido}%;background:${m.pct_cumprido >= 80 ? '#a6e3a1' : m.pct_cumprido >= 40 ? '#fab387' : '#f38ba8'};border-radius:3px;"></div>
            </div>
          </div>
        `).join('');
      } else {
        materiasEl.innerHTML = '';
      }
      if (data.extras.length > 0) {
        materiasEl.innerHTML += '<div style="margin-top:8px;font-size:0.78rem;color:#89b4fa;">📌 Extra: ' +
          data.extras.map(e => `${e.materia} (${e.horas_estudadas}h)`).join(', ') + '</div>';
      }
    })
    .catch(() => {});
}

// Load ontem when ciclo tab is shown
const _origNav = navigateTo;
window.navigateTo = function(tabId, btn) {
  _origNav(tabId, btn);
  if (tabId === 'tab-ciclo') { loadCicloOntem(); }
  if (tabId === 'tab-videos') { loadVideosList(); }
  if (tabId === 'tab-trilha' && typeof window.loadTrilha === 'function') { window.loadTrilha(); }
};

// Auto-load ciclo ontem if tab-ciclo is currently visible
setTimeout(() => {
  const cicloTab = document.getElementById('tab-ciclo');
  if (cicloTab && cicloTab.classList.contains('active')) {
    loadCicloOntem();
  }
}, 300);

// ===== VIDEOS LIST =====
async function loadVideosList() {
  const el = document.getElementById('videos-list');
  if (!el) return;
  try {
    const data = await fetch('/api/edital?arquivado=0').then(r => r.json());
    const items = (data.items || data).filter(t => t.video_link);
    if (!items.length) {
      el.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text-sub);">
        <div style="font-size:2.5rem;margin-bottom:12px;">🎬</div>
        <p style="font-size:0.95rem;font-weight:600;color:var(--text);margin-bottom:8px;">Nenhum vídeo vinculado ainda</p>
        <p style="font-size:0.82rem;margin-bottom:16px;">Vincule vídeos YouTube aos tópicos do edital para assistir aqui.</p>
        <div style="text-align:left;background:var(--bg);border-radius:10px;padding:14px;font-size:0.82rem;max-width:400px;margin:0 auto;">
          <p style="font-weight:600;color:var(--accent);margin-bottom:8px;">Como vincular:</p>
          <ol style="margin:0;padding-left:18px;color:var(--text);line-height:1.8;">
            <li>Vá na aba <strong>Edital</strong></li>
            <li>Encontre o tópico desejado</li>
            <li>Clique no botão <strong>🎬</strong> ao lado do tópico</li>
            <li>Cole o link do YouTube</li>
          </ol>
        </div>
      </div>`;
      return;
    }
    // Agrupar por matéria
    const grouped = {};
    items.forEach(t => {
      if (!grouped[t.materia]) grouped[t.materia] = [];
      grouped[t.materia].push(t);
    });
    let html = '';
    for (const [materia, topics] of Object.entries(grouped)) {
      html += `<div style="margin-bottom:16px;">
        <div style="font-size:0.85rem;font-weight:700;color:var(--accent);margin-bottom:6px;">${materia} (${topics.length})</div>`;
      for (const t of topics) {
        const videoId = extractYTId(t.video_link);
        const thumb = videoId ? `https://img.youtube.com/vi/${videoId}/mqdefault.jpg` : '';
        html += `<div style="display:flex;align-items:center;gap:10px;padding:8px;background:var(--bg);border-radius:8px;margin-bottom:6px;cursor:pointer;" onclick="openVideoPlayer(${t.id},'${t.video_link.replace(/'/g,"\\'")}','${(t.topico||'').replace(/'/g,"\\'")}')">
          ${thumb ? `<img src="${thumb}" style="width:80px;height:45px;border-radius:6px;object-fit:cover;flex-shrink:0;" alt="">` : ''}
          <div style="flex:1;min-width:0;">
            <div style="font-size:0.82rem;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${t.topico || 'Sem tópico'}</div>
            <div style="font-size:0.72rem;color:var(--text-sub);">${t.status} · ${t.horas_estudadas || 0}h estudadas</div>
          </div>
          <span style="font-size:1.2rem;">▶️</span>
        </div>`;
      }
      html += '</div>';
    }
    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = '<div style="color:var(--red);font-size:0.85rem;">Erro ao carregar vídeos.</div>';
  }
}

function extractYTId(url) {
  if (!url) return null;
  const m = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/) || url.match(/[?&]v=([a-zA-Z0-9_-]{11})/);
  return m ? m[1] : null;
}

// Auto-load videos if tab is active
setTimeout(() => {
  const videosTab = document.getElementById('tab-videos');
  if (videosTab && videosTab.classList.contains('active')) {
    loadVideosList();
  }
}, 300);

// Also load when tab becomes visible (backup for goSection)
const _videosObserver = new MutationObserver(() => {
  const videosTab = document.getElementById('tab-videos');
  if (videosTab && videosTab.classList.contains('active')) {
    const el = document.getElementById('videos-list');
    if (el && el.textContent.includes('Carregando')) loadVideosList();
  }
});
setTimeout(() => {
  const videosTab = document.getElementById('tab-videos');
  if (videosTab) _videosObserver.observe(videosTab, { attributes: true, attributeFilter: ['class'] });
}, 500);

// ===== SERVICE WORKER REGISTRATION =====
if ('serviceWorker' in navigator) {
  window.addEventListener('load', async () => {
    try {
      const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      console.log('[App] SW registered, scope:', registration.scope);

      // Check for updates periodically (every 5 minutes)
      setInterval(() => registration.update(), 5 * 60 * 1000);

      // Also check when returning from background
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') registration.update();
      });

      // Handle SW updates
      registration.addEventListener('updatefound', () => {
        const newWorker = registration.installing;
        if (!newWorker) return;

        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            // New SW installed, show update prompt
            showUpdateBanner(newWorker);
          }
        });
      });

      // Listen for controller change (after skipWaiting)
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        window.location.reload();
      });

      // Listen for sync completion messages
      navigator.serviceWorker.addEventListener('message', (event) => {
        const { type, replayed, pending } = event.data || {};
        if (type === 'SYNC_COMPLETE') {
          if (replayed > 0) {
            if (window.toast) {
              window.toast(`✅ ${replayed} ação(ões) sincronizada(s)${pending > 0 ? ` (${pending} pendente(s))` : ''}`, 'success', 4000);
            }
          }
        }
      });

      // Request persistent storage for offline data
      if (navigator.storage && navigator.storage.persist) {
        const persisted = await navigator.storage.persist();
        console.log('[App] Persistent storage:', persisted ? 'granted' : 'denied');
      }

      // Register periodic background sync if supported
      if ('periodicSync' in registration) {
        try {
          await registration.periodicSync.register('refresh-dashboard', {
            minInterval: 12 * 60 * 60 * 1000 // 12 hours
          });
        } catch (e) {
          // Periodic sync requires permission, not critical
        }
      }

    } catch (error) {
      console.error('[App] SW registration failed:', error);
    }
  });
}

function showUpdateBanner(worker) {
  // Remove existing banner if any
  const existing = document.getElementById('sw-update-banner');
  if (existing) existing.remove();

  const banner = document.createElement('div');
  banner.id = 'sw-update-banner';
  banner.setAttribute('role', 'alert');
  banner.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:#313244;color:#cdd6f4;padding:12px 20px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.4);z-index:10000;display:flex;align-items:center;gap:12px;font-size:0.9rem;border:1px solid #cba6f7;max-width:90%;';
  banner.innerHTML = `
    <span>🆕 Nova versão disponível!</span>
    <button onclick="applyUpdate()" style="background:#cba6f7;color:#1e1e2e;border:none;border-radius:8px;padding:8px 16px;font-weight:600;cursor:pointer;font-size:0.85rem;white-space:nowrap;">Atualizar</button>
    <button onclick="this.parentElement.remove()" style="background:none;border:none;color:#9399b2;cursor:pointer;font-size:1.2rem;padding:4px;" aria-label="Fechar">✕</button>
  `;
  document.body.appendChild(banner);

  window._pendingWorker = worker;
}

function applyUpdate() {
  if (window._pendingWorker) {
    window._pendingWorker.postMessage({ type: 'SKIP_WAITING' });
  }
}
window.applyUpdate = applyUpdate;
