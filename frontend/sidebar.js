/**
 * Sidebar global — injeta em qualquer página do ConcurseiroOS.
 * Incluir em cada página: <script src="/sidebar.js"></script>
 */

// Apply saved theme immediately (before render to avoid flash)
(function() {
  const theme = localStorage.getItem('theme');
  function applyTheme() {
    if (!document.body) return;
    if (theme === 'light') {
      document.body.classList.add('light-theme', 'theme-forced');
    } else {
      document.body.classList.add('theme-forced');
    }
  }
  // Try immediately (works if script is after <body>)
  if (document.body) {
    applyTheme();
  } else {
    // If body doesn't exist yet, wait for DOMContentLoaded
    document.addEventListener('DOMContentLoaded', applyTheme);
  }
})();

(function () {
  // Guard: don't inject sidebar twice
  if (document.getElementById('sidebar')) return;

  function initSidebar() {
    // Double-check guard after DOMContentLoaded
    if (document.getElementById('sidebar')) return;
    if (!document.body) return;

  const currentPath = window.location.pathname;

  function isActive(path) {
    if (path === '/' && currentPath === '/') return true;
    if (path === '/' && currentPath === '/index.html') return true;
    if (path !== '/' && currentPath.startsWith(path)) return true;
    return false;
  }

  function activeClass(path) {
    return isActive(path) ? 'active' : '';
  }

  const collapsed = localStorage.getItem('sidebar_collapsed') === 'true';

  const sidebarHTML = `
    <div class="sidebar-overlay" id="sidebar-overlay" onclick="closeSidebar()"></div>
    <aside class="sidebar ${collapsed ? 'collapsed' : ''}" id="sidebar">
      <div class="sidebar-brand">
        <span class="brand-icon">📚</span>
        <span class="brand-text">ConcurseiroOS</span>
        <button class="sidebar-collapse-btn" onclick="toggleCollapse()" title="Recolher menu" aria-label="Recolher/expandir menu">◀</button>
      </div>

      <!-- CTA: Iniciar Sessão -->
      <div class="sidebar-cta" id="sidebar-cta">
        <button onclick="iniciarSessaoRapida()" class="cta-btn" title="Inicia estudo com a matéria sugerida pelo treinador">
          <span class="cta-icon">▶</span>
          <span class="cta-text">Iniciar Sessão</span>
        </button>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Hoje</div>
        <ul class="sidebar-nav">
          <li><a href="/dashboard.html" class="${activeClass('/dashboard')}"><span class="nav-icon" aria-hidden="true">⚡</span><span class="nav-label">Meu Dia</span></a></li>
          <li><a href="/dashboard.html#calendario" onclick="return goPanel('panel-calendario')"><span class="nav-icon" aria-hidden="true">📅</span><span class="nav-label">Calendário</span></a></li>
        </ul>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Estudar</div>
        <ul class="sidebar-nav">
          <li><a href="/" class="${activeClass('/')}"><span class="nav-icon" aria-hidden="true">📖</span><span class="nav-label">PDFs / Leitura</span></a></li>
          <li><a href="/#videos" onclick="goSection('tab-videos', event)"><span class="nav-icon" aria-hidden="true">🎬</span><span class="nav-label">Vídeos</span></a></li>
          <li><a href="/#edital" onclick="goSection('tab-edital', event)"><span class="nav-icon" aria-hidden="true">📋</span><span class="nav-label">Edital</span></a></li>
          <li><a href="/#ciclo" onclick="goSection('tab-ciclo', event)"><span class="nav-icon" aria-hidden="true">🔄</span><span class="nav-label">Ciclo</span></a></li>
          <li><a href="/#trilha" onclick="goSection('tab-trilha', event)"><span class="nav-icon" aria-hidden="true">🧭</span><span class="nav-label">Trilha</span></a></li>
          <li><a href="/vademecum.html" class="${activeClass('/vademecum')}"><span class="nav-icon" aria-hidden="true">⚖️</span><span class="nav-label">Vade Mecum</span></a></li>
          <li><a href="/catalogo.html" class="${activeClass('/catalogo')}"><span class="nav-icon" aria-hidden="true">📚</span><span class="nav-label">Catálogo</span></a></li>
        </ul>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Praticar</div>
        <ul class="sidebar-nav">
          <li><a href="/questoes.html" class="${activeClass('/questoes')}"><span class="nav-icon" aria-hidden="true">❓</span><span class="nav-label">Questões</span><span class="nav-badge" id="badge-questoes"></span></a></li>
          <li><a href="/caderno-erros.html" class="${activeClass('/caderno-erros')}"><span class="nav-icon" aria-hidden="true">📕</span><span class="nav-label">Caderno de Erros</span><span class="nav-badge" id="badge-caderno-erros"></span></a></li>
          <li><a href="/#flashcards" onclick="goSection('tab-flashcards', event)"><span class="nav-icon" aria-hidden="true">🧠</span><span class="nav-label">Flashcards</span><span class="nav-badge" id="badge-flashcards"></span></a></li>
          <li><a href="/#sumulas" onclick="goSection('tab-sumulas', event)"><span class="nav-icon" aria-hidden="true">⚖️</span><span class="nav-label">Súmulas</span><span class="nav-badge" id="badge-sumulas"></span></a></li>
          <li><a href="/social.html#ai" onclick="goSocialTab('ai')"><span class="nav-icon" aria-hidden="true">🤖</span><span class="nav-label">AI Tutor</span></a></li>
          <li><a href="/batalha.html" class="${activeClass('/batalha')}"><span class="nav-icon" aria-hidden="true">⚔️</span><span class="nav-label">Batalha</span></a></li>
          <li><a href="/studyroom.html" class="${activeClass('/studyroom')}"><span class="nav-icon" aria-hidden="true">🏠</span><span class="nav-label">Sala de Estudos</span></a></li>
        </ul>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Progresso</div>
        <ul class="sidebar-nav">
          <li><a href="/mastery.html" class="${activeClass('/mastery')}"><span class="nav-icon" aria-hidden="true">📈</span><span class="nav-label">Domínio</span></a></li>
          <li><a href="/dashboard.html#analytics" onclick="return goPanel('panel-analytics')"><span class="nav-icon" aria-hidden="true">📊</span><span class="nav-label">Analytics</span></a></li>
          <li><a href="/raio-x.html" class="${activeClass('/raio-x')}"><span class="nav-icon" aria-hidden="true">🎯</span><span class="nav-label">Raio-X Bancas</span></a></li>
          <li><a href="/social.html" class="${activeClass('/social')}"><span class="nav-icon" aria-hidden="true">🏆</span><span class="nav-label">Liga & Social</span></a></li>
        </ul>
      </div>

      <div class="sidebar-footer">
        ${(() => { try { const u = JSON.parse(localStorage.getItem('auth_user') || '{}'); return u.role === 'admin' ? '<a href="/admin.html" class="' + activeClass('/admin') + '" style="display:block;padding:6px 12px;font-size:0.75rem;color:#585b70;text-decoration:none;margin-bottom:4px;">⚙️ <span class=\\"nav-label\\">Admin</span></a>' : ''; } catch(e) { return ''; } })()}
        <a href="#" onclick="localStorage.removeItem('auth_token');localStorage.removeItem('auth_user');window.location.href='/login.html';return false;" style="display:block;padding:6px 12px;font-size:0.75rem;color:#f38ba8;text-decoration:none;margin-bottom:4px;">🚪 <span class="nav-label">Sair</span></a>
        <div class="sidebar-gamify">
          <div class="streak-box"><span class="fire">🔥</span><span class="num" id="sidebar-streak">0</span></div>
          <div class="freeze-box" id="sidebar-freeze" title="Streak Freezes">🧊 <span id="sidebar-freeze-count">0</span></div>
          <div class="xp-box" id="sidebar-xp">⭐ Nv.1</div>
        </div>
      </div>
    </aside>

    <!-- Bottom Navigation Mobile -->
    <nav class="bottom-nav" id="bottom-nav" aria-label="Navegação principal">
      <a href="/dashboard.html" class="${activeClass('/dashboard')}"><span class="bnav-icon" aria-hidden="true">⚡</span><span class="bnav-label">Hoje</span></a>
      <a href="/" class="${activeClass('/')}"><span class="bnav-icon" aria-hidden="true">📖</span><span class="bnav-label">Estudar</span></a>
      <a href="/questoes.html" class="${activeClass('/questoes')}"><span class="bnav-icon" aria-hidden="true">❓</span><span class="bnav-label">Praticar</span><span class="bnav-badge" id="bnav-badge-praticar"></span></a>
      <a href="/dashboard.html#analytics" onclick="return goPanel('panel-analytics')"><span class="bnav-icon" aria-hidden="true">📊</span><span class="bnav-label">Progresso</span></a>
      <a href="/social.html" class="${activeClass('/social')}"><span class="bnav-icon" aria-hidden="true">👤</span><span class="bnav-label">Perfil</span></a>
    </nav>
  `;

  // Inject skip-link for accessibility (all pages)
  if (!document.querySelector('.skip-link')) {
    const skipTarget = document.getElementById('page-content') ? '#page-content' : '#main-content';
    document.body.insertAdjacentHTML('afterbegin', `<a href="${skipTarget}" class="skip-link">Pular para conteúdo</a>`);
  }

  // Inject sidebar after skip-link
  const skipEl = document.querySelector('.skip-link');
  if (skipEl) {
    skipEl.insertAdjacentHTML('afterend', sidebarHTML);
  } else {
    document.body.insertAdjacentHTML('afterbegin', sidebarHTML);
  }

  // Wrap existing content in main-content div if not already wrapped
  if (!document.querySelector('.main-content')) {
    const scripts = [];
    const children = [];
    Array.from(document.body.children).forEach(el => {
      if (el.classList.contains('sidebar') || el.classList.contains('sidebar-overlay')) return;
      if (el.classList.contains('skip-link')) return;
      if (el.id === 'bottom-nav' || el.classList.contains('bottom-nav')) return;
      if (el.tagName === 'SCRIPT') { scripts.push(el); return; }
      children.push(el);
    });
    const wrapper = document.createElement('div');
    wrapper.className = 'main-content';
    wrapper.id = 'main-content';
    children.forEach(child => wrapper.appendChild(child));
    // Insert before scripts
    if (scripts.length > 0) {
      document.body.insertBefore(wrapper, scripts[0]);
    } else {
      document.body.appendChild(wrapper);
    }
  } else {
    // Ensure existing wrapper has id for skip-link target
    const existing = document.querySelector('.main-content');
    if (existing && !existing.id) existing.id = 'main-content';
  }

  // Add collapsed class to body if saved
  if (collapsed) {
    document.body.classList.add('sidebar-collapsed');
  }

  // Inject mobile toggle button if page doesn't have one
  if (!document.querySelector('.sidebar-toggle')) {
    const header = document.querySelector('.header, .top-bar');
    if (header) {
      const toggle = document.createElement('button');
      toggle.className = 'sidebar-toggle';
      toggle.onclick = function() { document.getElementById('sidebar')?.classList.toggle('open'); document.getElementById('sidebar-overlay')?.classList.toggle('active'); };
      toggle.setAttribute('aria-label', 'Abrir menu');
      toggle.textContent = '☰';
      header.insertBefore(toggle, header.firstChild);
    }
  }

  // Load streak/XP/freezes
  // Restore cached sidebar data immediately (prevents flicker between pages)
  const cachedSidebar = JSON.parse(localStorage.getItem('sidebar_data') || '{}');
  if (cachedSidebar.streak !== undefined) {
    const el = document.getElementById('sidebar-streak');
    if (el) el.textContent = cachedSidebar.streak || 0;
  }
  if (cachedSidebar.nivel) {
    const el = document.getElementById('sidebar-xp');
    if (el) el.textContent = `⭐ Nv.${cachedSidebar.nivel}`;
  }
  if (cachedSidebar.freezes_available !== undefined) {
    const el = document.getElementById('sidebar-freeze-count');
    if (el) el.textContent = cachedSidebar.freezes_available;
  }
  if (cachedSidebar.badges) {
    const b = cachedSidebar.badges;
    const elF = document.getElementById('badge-flashcards');
    const elS = document.getElementById('badge-sumulas');
    const elC = document.getElementById('badge-caderno-erros');
    const elBnav = document.getElementById('bnav-badge-praticar');
    if (elF) elF.textContent = b.flashcards > 0 ? b.flashcards : '';
    if (elS) elS.textContent = b.sumulas > 0 ? b.sumulas : '';
    if (elC) elC.textContent = b.caderno > 0 ? b.caderno : '';
    if (elBnav) elBnav.textContent = b.flashcards > 0 ? b.flashcards : '';
  }

  // Single consolidated fetch for all sidebar data
  fetch('/api/sidebar-data').then(r => r.json()).then(data => {
    // Streak
    const elStreak = document.getElementById('sidebar-streak');
    if (elStreak) elStreak.textContent = data.streak || 0;

    // Level
    const elXp = document.getElementById('sidebar-xp');
    if (elXp) elXp.textContent = `⭐ Nv.${data.nivel || 1}`;

    // Freezes
    const elFreeze = document.getElementById('sidebar-freeze-count');
    if (elFreeze) elFreeze.textContent = data.freezes_available || 0;

    // Badges
    const b = data.badges || {};
    const elF = document.getElementById('badge-flashcards');
    const elS = document.getElementById('badge-sumulas');
    const elC = document.getElementById('badge-caderno-erros');
    const elBnav = document.getElementById('bnav-badge-praticar');
    if (elF) elF.textContent = b.flashcards > 0 ? b.flashcards : '';
    if (elS) elS.textContent = b.sumulas > 0 ? b.sumulas : '';
    if (elC) elC.textContent = b.caderno > 0 ? b.caderno : '';
    if (elBnav) elBnav.textContent = b.flashcards > 0 ? b.flashcards : '';

    // CTA sugestão
    const cta = document.getElementById('sidebar-cta');
    if (cta && data.sugestao && data.sugestao.materia) {
      cta.setAttribute('data-materia', data.sugestao.materia);
      cta.setAttribute('data-tempo', data.sugestao.tempo_min || 25);
    }

    // Cache for next page load
    localStorage.setItem('sidebar_data', JSON.stringify(data));
  }).catch(() => {});

  // Global functions
  window.toggleSidebar = function () {
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('sidebar-overlay').classList.toggle('open');
  };

  window.closeSidebar = function () {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-overlay').classList.remove('open');
  };

  window.toggleCollapse = function () {
    const sidebar = document.getElementById('sidebar');
    const isCollapsed = sidebar.classList.toggle('collapsed');
    document.body.classList.toggle('sidebar-collapsed', isCollapsed);
    localStorage.setItem('sidebar_collapsed', isCollapsed);
  };

  window.goSection = function (tabId, event) {
    // Prevent default link navigation to avoid double-redirect
    if (event) event.preventDefault();

    // If we're on the main page, navigate to section directly
    if (currentPath === '/' || currentPath === '/index.html') {
      if (typeof navigateTo === 'function') {
        navigateTo(tabId);
      }
      closeSidebar();
      return false;
    }
    // If on another page, save target tab and redirect to index
    // Using localStorage ensures the tab activates after page load (no hash race condition)
    localStorage.setItem('concurseiro_active_tab', tabId);
    localStorage.setItem('concurseiro_tab_redirect', '1');
    const hashMap = {'tab-ciclo':'ciclo','tab-trilha':'trilha','tab-edital':'edital','tab-flashcards':'flashcards','tab-sumulas':'sumulas','tab-pdfs':'pdfs','tab-videos':'videos'};
    window.location.href = '/#' + (hashMap[tabId] || '');
    return false;
  };

  window.goPanel = function (panelId) {
    // If we're on dashboard, switch panel directly
    if (currentPath === '/dashboard.html' || currentPath.includes('dashboard')) {
      const tab = document.querySelector(`.dash-tab[data-panel="${panelId}"]`);
      if (tab) {
        // Simulate click: remove active from all, add to target
        document.querySelectorAll('.dash-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.dash-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        const panel = document.getElementById(panelId);
        if (panel) panel.classList.add('active');
        // Trigger panel load
        if (typeof loadActivePanel === 'function') loadActivePanel();
      }
      closeSidebar();
      return false; // prevent href navigation
    }
    // If on another page, save target and navigate
    localStorage.setItem('concurseiro_dash_panel', panelId);
    window.location.href = '/dashboard.html';
    return false;
  };

  window.goSocialTab = function (tabName) {
    if (currentPath === '/social.html' || currentPath.includes('social')) {
      if (typeof switchTab === 'function') switchTab(tabName);
      closeSidebar();
      return false;
    }
    localStorage.setItem('concurseiro_social_tab', tabName);
    window.location.href = '/social.html';
    return false;
  };

  // CTA: Iniciar sessão rápida com a matéria sugerida
  window.iniciarSessaoRapida = function () {
    const cta = document.getElementById('sidebar-cta');
    const materia = cta?.getAttribute('data-materia') || 'Estudos';
    const tempo = parseInt(cta?.getAttribute('data-tempo') || '25');

    // If startGlobalTimer exists (timer-global.js loaded), use it
    if (typeof startGlobalTimer === 'function') {
      startGlobalTimer(materia, tempo, 'estudo');
      closeSidebar();
    } else {
      // Redirect to dashboard and start there
      localStorage.setItem('concurseiro_start_timer', JSON.stringify({ materia, tempo }));
      window.location.href = '/dashboard.html';
    }
  };

  } // end initSidebar

  // Run sidebar init when DOM is ready
  if (document.body && document.readyState !== 'loading') {
    initSidebar();
  } else {
    document.addEventListener('DOMContentLoaded', initSidebar);
  }
})();


// ===== OFFLINE INDICATOR =====
(function initOfflineIndicator() {
  let indicator = null;

  function createIndicator() {
    if (indicator) return indicator;
    indicator = document.createElement('div');
    indicator.id = 'offline-indicator';
    indicator.setAttribute('role', 'status');
    indicator.setAttribute('aria-live', 'polite');
    indicator.style.cssText = `
      position: fixed;
      bottom: 96px;
      right: 16px;
      padding: 10px 18px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 500;
      z-index: 99999;
      display: flex;
      align-items: center;
      gap: 8px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      transition: opacity 0.3s, transform 0.3s;
      transform: translateY(0);
      opacity: 1;
    `;
    document.body.appendChild(indicator);
    return indicator;
  }

  function forceSyncNow() {
    const btn = document.getElementById('force-sync-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Sincronizando...'; }
    const token = localStorage.getItem('auth_token');
    const sw = navigator.serviceWorker?.controller;
    if (!sw) {
      if (btn) { btn.disabled = false; btn.textContent = 'Sincronizar agora'; }
      return;
    }
    // Envia o token ATUAL para o SW reprocessar a fila (resolve itens
    // enfileirados sem login que estavam sendo recusados com 401).
    sw.postMessage({ type: 'FORCE_SYNC', token });
  }

  function updateStatus(online, pending = 0) {    const el = createIndicator();
    if (!online) {
      el.style.background = '#ff6b35';
      el.style.color = '#fff';
      el.innerHTML = `<span>⚡</span><span>Offline${pending > 0 ? ` · ${pending} pendente${pending > 1 ? 's' : ''}` : ''}</span>`;
      el.style.display = 'flex';
      el.style.opacity = '1';
      el.style.transform = 'translateY(0)';
    } else if (pending > 0) {
      el.style.background = '#f59e0b';
      el.style.color = '#fff';
      el.innerHTML = `<span>🔄</span><span>Sincronizando... ${pending} pendente${pending > 1 ? 's' : ''}</span>`
        + `<button id="force-sync-btn" title="Tentar sincronizar agora" style="margin-left:6px;background:rgba(255,255,255,0.25);border:none;color:#fff;border-radius:6px;padding:3px 8px;font-size:12px;font-weight:600;cursor:pointer;">Sincronizar agora</button>`;
      el.style.display = 'flex';
      el.style.opacity = '1';
      el.style.transform = 'translateY(0)';
      const btn = el.querySelector('#force-sync-btn');
      if (btn) btn.onclick = forceSyncNow;
    } else {
      // Online with nothing pending — hide after brief "synced" message
      el.style.background = '#10b981';
      el.style.color = '#fff';
      el.innerHTML = `<span>✓</span><span>Sincronizado</span>`;
      el.style.display = 'flex';
      el.style.opacity = '1';
      setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(10px)';
        setTimeout(() => { el.style.display = 'none'; }, 300);
      }, 2500);
    }
  }

  function showSyncToast(count) {
    const toast = document.createElement('div');
    toast.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      padding: 12px 20px;
      background: #10b981;
      color: #fff;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 500;
      z-index: 10001;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      animation: slideIn 0.3s ease;
    `;
    toast.textContent = `✓ ${count} item${count > 1 ? 'ns' : ''} sincronizado${count > 1 ? 's' : ''}`;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.3s';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  window.addEventListener('online', () => updateStatus(true));
  window.addEventListener('offline', () => updateStatus(false));

  // Listen for SW sync messages
  navigator.serviceWorker?.addEventListener('message', (event) => {
    if (event.data?.type === 'SYNC_COMPLETE' || event.data?.type === 'FORCE_SYNC_DONE') {
      const { replayed = 0, discarded = 0, pending = 0 } = event.data;
      updateStatus(navigator.onLine, pending);
      if (replayed > 0) showSyncToast(replayed);
      if (discarded > 0 && typeof window.toast === 'function') {
        window.toast(`${discarded} ação(ões) pendente(s) foram descartadas (rejeitadas pelo servidor — ex: sessão expirada).`, 'warning', 5000);
      }
    }
    if (event.data?.type === 'PENDING_COUNT') {
      updateStatus(navigator.onLine, event.data.count);
    }
  });

  // Check on load
  if (!navigator.onLine) updateStatus(false);
  // Ask SW for pending count
  navigator.serviceWorker?.controller?.postMessage({ type: 'GET_PENDING_COUNT' });
  // Se online e logado, tenta reprocessar a fila com o token atual — resolve
  // itens que foram enfileirados antes do login (evita ficarem presos por 401).
  if (navigator.onLine && localStorage.getItem('auth_token')) {
    setTimeout(forceSyncNow, 1500);
  }
})();

// Load battle notification system (global)
(function() {
  function loadBattleNotify() {
    if (!document.body) return;
    const s = document.createElement('script');
    s.src = '/battle-notify.js';
    s.defer = true;
    document.body.appendChild(s);
  }
  if (document.body) loadBattleNotify();
  else document.addEventListener('DOMContentLoaded', loadBattleNotify);
})();

// Load AI Tutor floating widget (global)
(function() {
  function loadAITutor() {
    if (!document.body) return;
    const s = document.createElement('script');
    s.src = '/ai-tutor-widget.js';
    s.defer = true;
    document.body.appendChild(s);
  }
  if (document.body) loadAITutor();
  else document.addEventListener('DOMContentLoaded', loadAITutor);
})();

// ==================== NOTIFICAÇÃO "HORA DE ESTUDAR" ====================
(function() {
  if (!('Notification' in window)) return;
  if (!localStorage.getItem('auth_token')) return;

  // Só checar uma vez por sessão
  const key = 'study_notif_' + new Date().toISOString().slice(0, 13); // por hora
  if (sessionStorage.getItem(key)) return;

  setTimeout(async () => {
    try {
      // Pedir permissão se necessário
      if (Notification.permission === 'default') {
        await Notification.requestPermission();
      }
      if (Notification.permission !== 'granted') return;

      const hora = new Date().getHours();
      const streaks = await fetch('/api/streaks').then(r => r.json());
      const metas = await fetch('/api/metas').then(r => r.json());

      const horasHoje = metas.progresso?.horas || 0;
      const questoesHoje = metas.progresso?.questoes || 0;
      const flashcardsPendentes = parseInt(document.getElementById('badge-flashcards')?.textContent || '0');

      let msg = null;

      // Streak em risco (após 20h e sem atividade)
      if (hora >= 20 && horasHoje === 0 && questoesHoje === 0) {
        msg = '🔥 Seu streak vai quebrar! Estude pelo menos 5 minutos para manter.';
      }
      // Flashcards acumulando (> 10 pendentes)
      else if (flashcardsPendentes > 10) {
        msg = `🧠 ${flashcardsPendentes} flashcards pendentes — revisão espaçada perde efeito se acumular!`;
      }
      // Horário ótimo (entre 6-9h ou 19-22h — picos de estudo típicos)
      else if ((hora >= 6 && hora <= 8) || (hora >= 19 && hora <= 21)) {
        if (horasHoje < 1 && questoesHoje < 5) {
          msg = '📚 Bom horário para estudar! Seu cérebro está pronto.';
        }
      }

      if (msg) {
        new Notification('ConcurseiroOS', { body: msg, icon: '/icon.svg', tag: 'study-reminder' });
        sessionStorage.setItem(key, '1');
      }
    } catch (e) {}
  }, 5000); // Delay 5s para não atrapalhar carregamento
})();

// ==================== WEEKLY WRAP (Resumo Semanal) ====================
(function() {
  if (!localStorage.getItem('auth_token')) return;
  const today = new Date();
  const dayOfWeek = today.getDay(); // 0 = domingo
  const lastShown = localStorage.getItem('weekly_wrap_shown');
  const weekId = today.toISOString().slice(0, 10); // YYYY-MM-DD

  // Mostrar no domingo, ou se nunca mostrou esta semana
  if (dayOfWeek !== 0 && lastShown && lastShown >= new Date(today - 7*24*60*60*1000).toISOString().slice(0,10)) return;
  if (lastShown === weekId) return; // Já mostrou hoje

  setTimeout(async () => {
    try {
      const data = await fetch('/api/insights/weekly-wrap').then(r => { if (!r.ok) throw new Error(); return r.json(); });
      if (!data.resumo || data.resumo.horas_estudadas === 0 && data.resumo.questoes_resolvidas === 0) return;

      localStorage.setItem('weekly_wrap_shown', weekId);
      const r = data.resumo;
      const c = data.comparativo;
      const arrow = (trend) => trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→';
      const color = (trend) => trend === 'up' ? '#a6e3a1' : trend === 'down' ? '#f38ba8' : '#9399b2';

      const modal = document.createElement('div');
      modal.id = 'weekly-wrap-modal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.92);z-index:99999;display:flex;align-items:center;justify-content:center;padding:20px;animation:fadeIn 0.3s ease;';
      modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
      modal.innerHTML = `
        <div style="background:var(--bg-surface,#313244);border-radius:16px;padding:28px;max-width:420px;width:100%;box-shadow:0 12px 40px rgba(0,0,0,0.5);border:1px solid var(--border,#45475a);">
          <div style="text-align:center;margin-bottom:16px;">
            <div style="font-size:2rem;margin-bottom:4px;">📊</div>
            <h3 style="margin:0;color:var(--accent,#cba6f7);font-size:1.1rem;">Resumo da Semana</h3>
            <p style="font-size:0.72rem;color:var(--text-sub,#9399b2);margin:4px 0 0;">${data.periodo}</p>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px;">
            <div style="background:var(--bg,#1e1e2e);border-radius:10px;padding:12px;text-align:center;">
              <div style="font-size:1.4rem;font-weight:700;color:var(--blue,#89b4fa);">${r.horas_estudadas}h</div>
              <div style="font-size:0.7rem;color:var(--text-sub);">Horas ${c.delta_horas !== null ? `<span style="color:${color(c.tendencia_horas)}">${arrow(c.tendencia_horas)}${Math.abs(c.delta_horas)}h</span>` : ''}</div>
            </div>
            <div style="background:var(--bg,#1e1e2e);border-radius:10px;padding:12px;text-align:center;">
              <div style="font-size:1.4rem;font-weight:700;color:var(--green,#a6e3a1);">${r.questoes_resolvidas}</div>
              <div style="font-size:0.7rem;color:var(--text-sub);">Questões ${c.delta_questoes !== null ? `<span style="color:${color(c.tendencia_questoes)}">${arrow(c.tendencia_questoes)}${Math.abs(c.delta_questoes)}</span>` : ''}</div>
            </div>
            <div style="background:var(--bg,#1e1e2e);border-radius:10px;padding:12px;text-align:center;">
              <div style="font-size:1.4rem;font-weight:700;color:var(--peach,#fab387);">${r.pct_acerto}%</div>
              <div style="font-size:0.7rem;color:var(--text-sub);">Acerto</div>
            </div>
            <div style="background:var(--bg,#1e1e2e);border-radius:10px;padding:12px;text-align:center;">
              <div style="font-size:1.4rem;font-weight:700;color:var(--red,#f38ba8);">🔥${r.streak_atual}</div>
              <div style="font-size:0.7rem;color:var(--text-sub);">${r.dias_ativos}/7 dias ativos</div>
            </div>
          </div>
          ${data.conquistas.length ? `<div style="margin-bottom:12px;"><div style="font-size:0.75rem;color:var(--text-sub);margin-bottom:6px;font-weight:600;">🏆 Conquistas:</div><div style="display:flex;flex-wrap:wrap;gap:6px;">${data.conquistas.map(c => `<span style="background:var(--bg);padding:4px 8px;border-radius:6px;font-size:0.72rem;">${c.icon} ${c.label}</span>`).join('')}</div></div>` : ''}
          ${data.destaques.melhor_materia ? `<div style="font-size:0.75rem;margin-bottom:4px;color:var(--green);">✅ Melhor: ${data.destaques.melhor_materia.materia} (${data.destaques.melhor_materia.pct}%)</div>` : ''}
          ${data.destaques.pior_materia ? `<div style="font-size:0.75rem;margin-bottom:12px;color:var(--red);">⚠️ Focar: ${data.destaques.pior_materia.materia} (${data.destaques.pior_materia.pct}%)</div>` : ''}
          <button onclick="document.getElementById('weekly-wrap-modal').remove()" style="width:100%;background:var(--accent,#cba6f7);color:var(--bg,#1e1e2e);border:none;border-radius:8px;padding:10px;font-weight:600;font-size:0.9rem;cursor:pointer;">👍 Fechar</button>
        </div>
      `;
      document.body.appendChild(modal);
    } catch(e) {}
  }, 3000);
})();
