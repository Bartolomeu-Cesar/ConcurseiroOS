/**
 * Sidebar global — injeta em qualquer página do ConcurseiroOS.
 * Incluir em cada página: <script src="/sidebar.js"></script>
 */
(function () {
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
          <li><a href="/dashboard.html" class="${activeClass('/dashboard')}"><span class="nav-icon">⚡</span><span class="nav-label">Meu Dia</span></a></li>
          <li><a href="/dashboard.html#calendario" onclick="return goPanel('panel-calendario')"><span class="nav-icon">📅</span><span class="nav-label">Calendário</span></a></li>
        </ul>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Estudar</div>
        <ul class="sidebar-nav">
          <li><a href="/" class="${activeClass('/')}"><span class="nav-icon">📖</span><span class="nav-label">PDFs / Leitura</span></a></li>
          <li><a href="/#edital" onclick="goSection('tab-edital')"><span class="nav-icon">📋</span><span class="nav-label">Edital</span></a></li>
          <li><a href="/#ciclo" onclick="goSection('tab-ciclo')"><span class="nav-icon">🔄</span><span class="nav-label">Ciclo</span></a></li>
        </ul>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Praticar</div>
        <ul class="sidebar-nav">
          <li><a href="/questoes.html" class="${activeClass('/questoes')}"><span class="nav-icon">❓</span><span class="nav-label">Questões</span><span class="nav-badge" id="badge-questoes"></span></a></li>
          <li><a href="/#flashcards" onclick="goSection('tab-flashcards')"><span class="nav-icon">🧠</span><span class="nav-label">Flashcards</span><span class="nav-badge" id="badge-flashcards"></span></a></li>
          <li><a href="/#sumulas" onclick="goSection('tab-sumulas')"><span class="nav-icon">⚖️</span><span class="nav-label">Súmulas</span><span class="nav-badge" id="badge-sumulas"></span></a></li>
          <li><a href="/social.html#ai" onclick="goSocialTab('ai')"><span class="nav-icon">🤖</span><span class="nav-label">AI Tutor</span></a></li>
          <li><a href="/batalha.html" class="${activeClass('/batalha')}"><span class="nav-icon">⚔️</span><span class="nav-label">Batalha</span></a></li>
        </ul>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Progresso</div>
        <ul class="sidebar-nav">
          <li><a href="/mastery.html" class="${activeClass('/mastery')}"><span class="nav-icon">📈</span><span class="nav-label">Domínio</span></a></li>
          <li><a href="/dashboard.html#analytics" onclick="return goPanel('panel-analytics')"><span class="nav-icon">📊</span><span class="nav-label">Analytics</span></a></li>
          <li><a href="/raio-x.html" class="${activeClass('/raio-x')}"><span class="nav-icon">🎯</span><span class="nav-label">Raio-X Bancas</span></a></li>
          <li><a href="/social.html" class="${activeClass('/social')}"><span class="nav-icon">🏆</span><span class="nav-label">Liga & Social</span></a></li>
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
      <a href="/dashboard.html" class="${activeClass('/dashboard')}"><span class="bnav-icon">⚡</span><span class="bnav-label">Hoje</span></a>
      <a href="/" class="${activeClass('/')}"><span class="bnav-icon">📖</span><span class="bnav-label">Estudar</span></a>
      <a href="/questoes.html" class="${activeClass('/questoes')}"><span class="bnav-icon">❓</span><span class="bnav-label">Praticar</span><span class="bnav-badge" id="bnav-badge-praticar"></span></a>
      <a href="/dashboard.html#analytics" onclick="return goPanel('panel-analytics')"><span class="bnav-icon">📊</span><span class="bnav-label">Progresso</span></a>
      <a href="/social.html" class="${activeClass('/social')}"><span class="bnav-icon">👤</span><span class="bnav-label">Perfil</span></a>
    </nav>
  `;

  // Inject sidebar before body content
  document.body.insertAdjacentHTML('afterbegin', sidebarHTML);

  // Wrap existing content in main-content div if not already wrapped
  if (!document.querySelector('.main-content')) {
    const scripts = [];
    const children = [];
    Array.from(document.body.children).forEach(el => {
      if (el.classList.contains('sidebar') || el.classList.contains('sidebar-overlay')) return;
      if (el.tagName === 'SCRIPT') { scripts.push(el); return; }
      children.push(el);
    });
    const wrapper = document.createElement('div');
    wrapper.className = 'main-content';
    children.forEach(child => wrapper.appendChild(child));
    // Insert before scripts
    if (scripts.length > 0) {
      document.body.insertBefore(wrapper, scripts[0]);
    } else {
      document.body.appendChild(wrapper);
    }
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
      toggle.onclick = toggleSidebar;
      toggle.setAttribute('aria-label', 'Abrir menu');
      toggle.textContent = '☰';
      header.insertBefore(toggle, header.firstChild);
    }
  }

  // Load streak/XP/freezes
  fetch('/api/streaks').then(r => r.json()).then(data => {
    const el = document.getElementById('sidebar-streak');
    if (el) el.textContent = data.streak_atual || 0;
  }).catch(() => {});

  fetch('/api/gamification').then(r => r.json()).then(data => {
    const el = document.getElementById('sidebar-xp');
    if (el) el.textContent = `⭐ Nv.${data.nivel || 1}`;
  }).catch(() => {});

  fetch('/api/streak-freeze').then(r => r.json()).then(data => {
    const el = document.getElementById('sidebar-freeze-count');
    if (el) el.textContent = data.freezes_available || 0;
  }).catch(() => {});

  // Load badges (pending counts)
  fetch('/api/flashcards/today').then(r => r.json()).then(data => {
    const count = data.length || 0;
    const el = document.getElementById('badge-flashcards');
    const bnavEl = document.getElementById('bnav-badge-praticar');
    if (el && count > 0) el.textContent = count;
    if (bnavEl && count > 0) bnavEl.textContent = count;
  }).catch(() => {});

  fetch('/api/sumulas/today').then(r => r.json()).then(data => {
    const count = Array.isArray(data) ? data.length : (data.pendentes || 0);
    const el = document.getElementById('badge-sumulas');
    if (el && count > 0) el.textContent = count;
  }).catch(() => {});

  // CTA: load suggested materia for quick session
  fetch('/api/treinador/sugestao-rapida').then(r => r.json()).then(data => {
    const cta = document.getElementById('sidebar-cta');
    if (cta && data.materia) {
      cta.setAttribute('data-materia', data.materia);
      cta.setAttribute('data-tempo', data.tempo_min || 25);
    }
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

  window.goSection = function (tabId) {
    // If we're on the main page, navigate to section
    if (currentPath === '/' || currentPath === '/index.html') {
      if (typeof navigateTo === 'function') {
        const btn = document.querySelector(`[data-nav="${tabId}"]`);
        navigateTo(tabId, btn);
      }
      closeSidebar();
      return false;
    }
    // If on another page, redirect
    localStorage.setItem('concurseiro_active_tab', tabId);
    window.location.href = '/';
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
      bottom: 16px;
      right: 16px;
      padding: 10px 18px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 500;
      z-index: 10000;
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

  function updateStatus(online, pending = 0) {
    const el = createIndicator();
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
      el.innerHTML = `<span>🔄</span><span>Sincronizando... ${pending} pendente${pending > 1 ? 's' : ''}</span>`;
      el.style.display = 'flex';
      el.style.opacity = '1';
      el.style.transform = 'translateY(0)';
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
    if (event.data?.type === 'SYNC_COMPLETE') {
      updateStatus(true, event.data.pending);
      if (event.data.replayed > 0) {
        showSyncToast(event.data.replayed);
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
})();
