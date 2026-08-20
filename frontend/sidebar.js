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

      <div class="sidebar-section">
        <div class="sidebar-section-title">Estudos</div>
        <ul class="sidebar-nav">
          <li><a href="/" class="${activeClass('/')}"><span class="nav-icon">📖</span><span class="nav-label">PDFs</span></a></li>
          <li><a href="/#edital" onclick="goSection('tab-edital')" class="${currentPath === '/' ? '' : ''}"><span class="nav-icon">📋</span><span class="nav-label">Edital</span></a></li>
          <li><a href="/#ciclo" onclick="goSection('tab-ciclo')" class="${currentPath === '/' ? '' : ''}"><span class="nav-icon">🔄</span><span class="nav-label">Ciclo</span></a></li>
        </ul>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Prática</div>
        <ul class="sidebar-nav">
          <li><a href="/questoes.html" class="${activeClass('/questoes')}"><span class="nav-icon">❓</span><span class="nav-label">Questões</span></a></li>
          <li><a href="/#flashcards" onclick="goSection('tab-flashcards')"><span class="nav-icon">🧠</span><span class="nav-label">Flashcards</span></a></li>
          <li><a href="/#sumulas" onclick="goSection('tab-sumulas')"><span class="nav-icon">⚖️</span><span class="nav-label">Súmulas</span></a></li>
        </ul>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Progresso</div>
        <ul class="sidebar-nav">
          <li><a href="/dashboard.html" class="${activeClass('/dashboard')}"><span class="nav-icon">📊</span><span class="nav-label">Dashboard</span></a></li>
          <li><a href="/#metas" onclick="goSection('tab-metas')"><span class="nav-icon">🎯</span><span class="nav-label">Metas</span></a></li>
        </ul>
      </div>

      <div class="sidebar-footer">
        <div class="sidebar-gamify">
          <div class="streak-box"><span class="fire">🔥</span><span class="num" id="sidebar-streak">0</span></div>
          <div class="xp-box" id="sidebar-xp">⭐ Nv.1</div>
        </div>
      </div>
    </aside>
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

  // Load streak/XP
  fetch('/api/streaks').then(r => r.json()).then(data => {
    const el = document.getElementById('sidebar-streak');
    if (el) el.textContent = data.streak_atual || 0;
  }).catch(() => {});

  fetch('/api/gamification').then(r => r.json()).then(data => {
    const el = document.getElementById('sidebar-xp');
    if (el) el.textContent = `⭐ Nv.${data.nivel || 1}`;
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
})();
