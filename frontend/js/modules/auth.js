// ==================== AUTH ====================
// Gerencia token JWT, estado de login, perfil e planos de acesso

const PLAN_LABELS = {
  guest: { nome: 'Visitante', cor: '#585b70', icon: '👁' },
  free: { nome: 'Gratuito', cor: '#9399b2', icon: '⭐' },
  premium: { nome: 'Premium', cor: '#f9e2af', icon: '👑' },
  ilimitado: { nome: 'Ilimitado', cor: '#a6e3a1', icon: '💎' },
};

export function getToken() {
  return localStorage.getItem('auth_token');
}

export function getUser() {
  try {
    const raw = localStorage.getItem('auth_user');
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export function getUserPlan() {
  const user = getUser();
  return user?.plano || (isLoggedIn() ? 'free' : 'guest');
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
    showProfileMenu();
  } else {
    window.location.href = '/login.html';
  }
}

function showProfileMenu() {
  const existing = document.getElementById('profile-menu');
  if (existing) { existing.remove(); return; }

  const user = getUser();
  const plan = getUserPlan();
  const planInfo = PLAN_LABELS[plan] || PLAN_LABELS.free;
  const menu = document.createElement('div');
  menu.id = 'profile-menu';
  menu.style.cssText = 'position:fixed;top:50px;right:16px;background:#313244;border:1px solid #45475a;border-radius:12px;padding:16px;z-index:9999;min-width:240px;box-shadow:0 8px 24px rgba(0,0,0,0.4);';
  menu.innerHTML = `
    <div style="text-align:center;margin-bottom:12px;">
      <div style="font-size:2rem;margin-bottom:4px;">${user?.avatar || '👤'}</div>
      <div style="font-weight:600;color:#cdd6f4;">${user?.nome || 'Estudante'}</div>
      <div style="font-size:0.75rem;color:#9399b2;margin-bottom:6px;">${user?.email || ''}</div>
      <span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:0.72rem;font-weight:600;background:${planInfo.cor}22;color:${planInfo.cor};border:1px solid ${planInfo.cor}55;">
        ${planInfo.icon} ${planInfo.nome}
      </span>
    </div>
    <div style="border-top:1px solid #45475a;padding-top:8px;display:flex;flex-direction:column;gap:6px;">
      ${plan === 'free' || plan === 'guest' ? `<button onclick="showUpgradeModal()" style="background:#f9e2af;color:#1e1e2e;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.82rem;font-weight:600;">👑 Fazer Upgrade</button>` : ''}
      <button onclick="showEditProfileModal()" style="background:#45475a;color:#cdd6f4;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.82rem;">✏️ Editar Perfil</button>
      <button onclick="logout();document.getElementById('profile-menu')?.remove()" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.82rem;font-weight:600;">🚪 Sair</button>
    </div>
  `;
  document.body.appendChild(menu);

  setTimeout(() => {
    document.addEventListener('click', function closeMenu(e) {
      if (!menu.contains(e.target) && e.target.id !== 'auth-nav-link') {
        menu.remove();
        document.removeEventListener('click', closeMenu);
      }
    });
  }, 100);
}

export function showUpgradeModal() {
  // Fechar profile menu se aberto
  document.getElementById('profile-menu')?.remove();

  const currentPlan = getUserPlan();
  const overlay = document.createElement('div');
  overlay.id = 'upgrade-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.innerHTML = `
    <div style="background:#313244;border-radius:16px;padding:28px;max-width:700px;width:100%;max-height:90vh;overflow-y:auto;">
      <div style="text-align:center;margin-bottom:20px;">
        <h2 style="color:#cba6f7;margin-bottom:4px;">🚀 Escolha seu Plano</h2>
        <p style="font-size:0.82rem;color:#9399b2;">Compare com QConcursos (R$19,90/mês) e Quizlet (R$35,99/ano)</p>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:12px;">
        <!-- Estudante (Free) -->
        <div style="background:#1e1e2e;border:1px solid ${currentPlan === 'free' ? '#cba6f7' : '#45475a'};border-radius:12px;padding:16px;text-align:center;">
          <div style="font-size:1.5rem;margin-bottom:4px;">⭐</div>
          <div style="font-weight:600;color:#9399b2;">Estudante</div>
          <div style="font-size:1.4rem;font-weight:700;color:#cdd6f4;margin:8px 0;">Grátis</div>
          <ul style="text-align:left;font-size:0.7rem;color:#9399b2;list-style:none;padding:0;line-height:1.9;">
            <li>✓ 2 editais</li>
            <li>✓ 150 flashcards</li>
            <li>✓ 15 questões/dia</li>
            <li>✓ 10 PDFs</li>
            <li>✓ Dashboard completo</li>
            <li>✓ Revisão espaçada (SM-2)</li>
            <li>✓ Treinador (3 técnicas)</li>
            <li>✓ Gamificação + Streak</li>
            <li>✗ Export/Import</li>
            <li>✗ Relatórios avançados</li>
            <li>✗ Conteúdo ilimitado</li>
          </ul>
          ${currentPlan === 'free' ? '<div style="margin-top:10px;padding:6px;border:1px solid #cba6f7;border-radius:6px;font-size:0.75rem;color:#cba6f7;font-weight:600;">✓ Plano Atual</div>' : ''}
        </div>
        <!-- Premium -->
        <div style="background:#1e1e2e;border:2px solid #f9e2af;border-radius:12px;padding:16px;text-align:center;position:relative;">
          <div style="position:absolute;top:-10px;left:50%;transform:translateX(-50%);background:#f9e2af;color:#1e1e2e;font-size:0.6rem;font-weight:700;padding:2px 10px;border-radius:10px;">MAIS POPULAR</div>
          <div style="font-size:1.5rem;margin-bottom:4px;">👑</div>
          <div style="font-weight:600;color:#f9e2af;">Premium</div>
          <div style="font-size:1.4rem;font-weight:700;color:#cdd6f4;margin:8px 0;">R$14<span style="font-size:0.75rem;color:#9399b2;">,90/mês</span></div>
          <div style="font-size:0.65rem;color:#a6e3a1;margin-bottom:4px;">25% mais barato que QConcursos</div>
          <ul style="text-align:left;font-size:0.7rem;color:#cdd6f4;list-style:none;padding:0;line-height:1.9;">
            <li>✓ Editais <strong>ilimitados</strong></li>
            <li>✓ Flashcards <strong>ilimitados</strong></li>
            <li>✓ Questões <strong>ilimitadas</strong></li>
            <li>✓ PDFs <strong>ilimitados</strong></li>
            <li>✓ Simulados <strong>ilimitados</strong></li>
            <li>✓ Treinador (14 técnicas)</li>
            <li>✓ Export/Import completo</li>
            <li>✓ Relatórios de desempenho</li>
            <li>✓ Backup automático</li>
            <li>✓ Calendário personalizado</li>
          </ul>
          ${currentPlan === 'premium' ? '<div style="margin-top:10px;padding:6px;border:1px solid #f9e2af;border-radius:6px;font-size:0.75rem;color:#f9e2af;font-weight:600;">✓ Plano Atual</div>' : `<button onclick="doUpgrade('premium')" style="width:100%;margin-top:10px;padding:10px;border:none;border-radius:6px;background:#f9e2af;color:#1e1e2e;font-size:0.82rem;font-weight:600;cursor:pointer;">Assinar Premium</button>`}
        </div>
        <!-- Vitalício -->
        <div style="background:#1e1e2e;border:1px solid #a6e3a1;border-radius:12px;padding:16px;text-align:center;position:relative;">
          <div style="position:absolute;top:-10px;left:50%;transform:translateX(-50%);background:#a6e3a1;color:#1e1e2e;font-size:0.6rem;font-weight:700;padding:2px 10px;border-radius:10px;">MELHOR CUSTO</div>
          <div style="font-size:1.5rem;margin-bottom:4px;">💎</div>
          <div style="font-weight:600;color:#a6e3a1;">Vitalício</div>
          <div style="font-size:1.4rem;font-weight:700;color:#cdd6f4;margin:8px 0;">R$97<span style="font-size:0.75rem;color:#9399b2;"> único</span></div>
          <div style="font-size:0.65rem;color:#a6e3a1;margin-bottom:4px;">≈ 6,5 meses de Premium</div>
          <ul style="text-align:left;font-size:0.7rem;color:#cdd6f4;list-style:none;padding:0;line-height:1.9;">
            <li>✓ <strong>Tudo</strong> do Premium</li>
            <li>✓ Pague <strong>uma vez só</strong></li>
            <li>✓ Sem mensalidade</li>
            <li>✓ Acesso <strong>permanente</strong></li>
            <li>✓ Todas atualizações futuras</li>
            <li>✓ Suporte prioritário</li>
            <li>&nbsp;</li>
            <li>&nbsp;</li>
            <li>&nbsp;</li>
            <li>&nbsp;</li>
          </ul>
          ${currentPlan === 'ilimitado' ? '<div style="margin-top:10px;padding:6px;border:1px solid #a6e3a1;border-radius:6px;font-size:0.75rem;color:#a6e3a1;font-weight:600;">✓ Plano Atual</div>' : `<button onclick="doUpgrade('ilimitado')" style="width:100%;margin-top:10px;padding:10px;border:none;border-radius:6px;background:#a6e3a1;color:#1e1e2e;font-size:0.82rem;font-weight:600;cursor:pointer;">Comprar Vitalício</button>`}
        </div>
      </div>
      <p style="text-align:center;font-size:0.72rem;color:#585b70;margin-top:12px;">Pagamento seguro • Cancele quando quiser • Satisfação garantida</p>
      <button onclick="document.getElementById('upgrade-modal').remove()" style="display:block;width:100%;margin-top:12px;padding:10px;background:#45475a;color:#cdd6f4;border:none;border-radius:8px;cursor:pointer;">Fechar</button>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

export async function doUpgrade(plano) {
  const token = getToken();
  if (!token) { window.location.href = '/login.html'; return; }

  try {
    const res = await fetch('/api/auth/upgrade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ plano })
    });
    const data = await res.json();
    if (data.ok) {
      // Atualizar user local
      const user = getUser();
      user.plano = plano;
      localStorage.setItem('auth_user', JSON.stringify(user));
      document.getElementById('upgrade-modal')?.remove();
      updateAuthUI();
      // Toast de sucesso (se disponível)
      if (window.toast) window.toast(`🎉 Upgrade para ${PLAN_LABELS[plano].nome} ativado!`, 'success');
    } else {
      if (window.toast) window.toast(data.detail || 'Erro no upgrade', 'error');
    }
  } catch(e) {
    if (window.toast) window.toast('Erro de conexão', 'error');
  }
}

export async function checkPlanLimit(recurso) {
  // Verifica limite no backend e mostra upgrade se necessário
  try {
    const token = getToken();
    const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
    const res = await fetch(`/api/auth/check-limit/${recurso}`, { headers });
    const data = await res.json();
    if (!data.pode) {
      showUpgradeModal();
      return false;
    }
    return true;
  } catch { return true; } // Em caso de erro, permite
}

export function updateAuthUI() {
  const link = document.getElementById('auth-nav-link');
  if (!link) return;

  if (isLoggedIn()) {
    const user = getUser();
    const plan = getUserPlan();
    const planInfo = PLAN_LABELS[plan] || PLAN_LABELS.free;
    link.innerHTML = `${planInfo.icon} ${user?.nome || user?.email?.split('@')[0] || 'Perfil'}`;
  } else {
    link.textContent = '👤 Login';
  }
}

export function showEditProfileModal() {
  document.getElementById('profile-menu')?.remove();
  const user = getUser();
  const avatars = ['👤','👨‍💻','👩‍💻','🧑‍🎓','👨‍🎓','👩‍🎓','🦸','🧠','📚','⚖️','🔬','💼'];

  const overlay = document.createElement('div');
  overlay.id = 'edit-profile-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.innerHTML = `
    <div style="background:#313244;border-radius:16px;padding:28px;max-width:400px;width:100%;">
      <h3 style="color:#cba6f7;margin:0 0 16px;text-align:center;">✏️ Editar Perfil</h3>
      <div style="margin-bottom:14px;">
        <label style="font-size:0.8rem;color:#9399b2;display:block;margin-bottom:4px;">Nome</label>
        <input id="edit-profile-nome" type="text" value="${user?.nome || ''}" style="width:100%;padding:10px;border-radius:8px;border:1px solid #45475a;background:#1e1e2e;color:#cdd6f4;font-size:0.9rem;">
      </div>
      <div style="margin-bottom:14px;">
        <label style="font-size:0.8rem;color:#9399b2;display:block;margin-bottom:4px;">Avatar</label>
        <div id="edit-profile-avatars" style="display:flex;flex-wrap:wrap;gap:6px;">
          ${avatars.map(a => `<span onclick="document.getElementById('edit-profile-avatar-val').value='${a}';document.querySelectorAll('#edit-profile-avatars span').forEach(s=>s.style.border='2px solid transparent');this.style.border='2px solid #cba6f7'" style="font-size:1.5rem;cursor:pointer;padding:4px;border-radius:8px;border:2px solid ${a === (user?.avatar || '👤') ? '#cba6f7' : 'transparent'};">${a}</span>`).join('')}
        </div>
        <input type="hidden" id="edit-profile-avatar-val" value="${user?.avatar || '👤'}">
      </div>
      <div style="display:flex;gap:8px;margin-top:16px;">
        <button onclick="document.getElementById('edit-profile-modal').remove()" style="flex:1;padding:10px;background:#45475a;color:#cdd6f4;border:none;border-radius:8px;cursor:pointer;">Cancelar</button>
        <button onclick="saveProfile()" style="flex:1;padding:10px;background:#a6e3a1;color:#1e1e2e;border:none;border-radius:8px;font-weight:600;cursor:pointer;">💾 Salvar</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

export async function saveProfile() {
  const nome = document.getElementById('edit-profile-nome').value.trim();
  const avatar = document.getElementById('edit-profile-avatar-val').value;
  const token = getToken();
  if (!token) return;

  try {
    const res = await fetch('/api/auth/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ nome, avatar })
    });
    const data = await res.json();
    if (data.ok) {
      // Atualizar localStorage
      const user = getUser();
      user.nome = data.nome;
      user.avatar = data.avatar;
      localStorage.setItem('auth_user', JSON.stringify(user));
      document.getElementById('edit-profile-modal')?.remove();
      updateAuthUI();
      if (window.toast) window.toast('Perfil atualizado!', 'success');
    } else {
      if (window.toast) window.toast(data.detail || 'Erro ao salvar', 'error');
    }
  } catch(e) {
    if (window.toast) window.toast('Erro de conexão', 'error');
  }
}

export async function initAuth() {
  updateAuthUI();

  // Verificar se auth está habilitado no backend
  try {
    const res = await fetch('/api/auth/status');
    const status = await res.json();
    if (status.auth_enabled && !isLoggedIn()) {
      // Auth ativo + não logado → redirecionar para login
      window.location.href = '/login.html';
      return;
    }
  } catch(e) {
    // Se falhar (offline), permitir acesso
  }
}
