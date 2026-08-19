// ==================== AUTH ====================
// Gerencia token JWT, estado de login e UI do perfil

export function getToken() {
  return localStorage.getItem('auth_token');
}

export function getUser() {
  try {
    const raw = localStorage.getItem('auth_user');
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export function isLoggedIn() {
  return !!getToken();
}

export function logout() {
  localStorage.removeItem('auth_token');
  localStorage.removeItem('auth_user');
  updateAuthUI();
}

export function handleAuthNav() {
  if (isLoggedIn()) {
    // Mostrar menu de perfil
    showProfileMenu();
  } else {
    window.location.href = '/login.html';
  }
}

function showProfileMenu() {
  const existing = document.getElementById('profile-menu');
  if (existing) { existing.remove(); return; }

  const user = getUser();
  const menu = document.createElement('div');
  menu.id = 'profile-menu';
  menu.style.cssText = 'position:fixed;top:50px;right:16px;background:#313244;border:1px solid #45475a;border-radius:12px;padding:16px;z-index:9999;min-width:220px;box-shadow:0 8px 24px rgba(0,0,0,0.4);';
  menu.innerHTML = `
    <div style="text-align:center;margin-bottom:12px;">
      <div style="font-size:2rem;margin-bottom:4px;">${user?.avatar || '👤'}</div>
      <div style="font-weight:600;color:#cdd6f4;">${user?.nome || 'Estudante'}</div>
      <div style="font-size:0.75rem;color:#9399b2;">${user?.email || ''}</div>
    </div>
    <div style="border-top:1px solid #45475a;padding-top:8px;display:flex;flex-direction:column;gap:6px;">
      <button onclick="window.location.href='/login.html'" style="background:#45475a;color:#cdd6f4;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.82rem;">✏️ Editar Perfil</button>
      <button onclick="logout();document.getElementById('profile-menu')?.remove()" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.82rem;font-weight:600;">🚪 Sair</button>
    </div>
  `;
  document.body.appendChild(menu);

  // Fechar ao clicar fora
  setTimeout(() => {
    document.addEventListener('click', function closeMenu(e) {
      if (!menu.contains(e.target) && e.target.id !== 'auth-nav-link') {
        menu.remove();
        document.removeEventListener('click', closeMenu);
      }
    });
  }, 100);
}

export function updateAuthUI() {
  const link = document.getElementById('auth-nav-link');
  if (!link) return;

  if (isLoggedIn()) {
    const user = getUser();
    link.textContent = `👤 ${user?.nome || user?.email?.split('@')[0] || 'Perfil'}`;
  } else {
    link.textContent = '👤 Login';
  }
}

export function initAuth() {
  updateAuthUI();
}
