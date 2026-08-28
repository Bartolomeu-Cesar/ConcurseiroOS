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
      ${plan === 'free' || plan === 'guest' ? `<button onclick="showUpgradeModal()" style="background:#f9e2af;color:#1e1e2e;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.82rem;font-weight:600;">👑 Fazer Upgrade</button>` : `<button onclick="showUpgradeModal()" style="background:#45475a;color:#cdd6f4;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:0.82rem;">⚙️ Gerenciar Plano</button>`}
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
          ${currentPlan === 'free' ? '<div style="margin-top:10px;padding:6px;border:1px solid #cba6f7;border-radius:6px;font-size:0.75rem;color:#cba6f7;font-weight:600;">✓ Plano Atual</div>' : `<button onclick="doUpgrade('free')" style="width:100%;margin-top:10px;padding:10px;border:none;border-radius:6px;background:#45475a;color:#cdd6f4;font-size:0.82rem;cursor:pointer;">Mudar para Gratuito</button>`}
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
          ${currentPlan === 'ilimitado' ? '<div style="margin-top:10px;padding:6px;border:1px solid #a6e3a1;border-radius:6px;font-size:0.75rem;color:#a6e3a1;font-weight:600;">✓ Plano Atual</div>' : `<div id="vitalicio-btn-container" style="margin-top:10px;"><button disabled style="width:100%;padding:10px;border:none;border-radius:6px;background:#45475a;color:#9399b2;font-size:0.78rem;cursor:wait;">⏳ Verificando disponibilidade...</button></div>`}
        </div>
      </div>
      <p style="text-align:center;font-size:0.72rem;color:#585b70;margin-top:12px;">Pagamento seguro • Cancele quando quiser • Satisfação garantida</p>
      <div id="creditos-section" style="margin-top:16px;padding:16px;background:#1e1e2e;border:1px solid #89b4fa;border-radius:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <div>
            <span style="font-size:1.1rem;">🎟️</span>
            <strong style="color:#89b4fa;font-size:0.9rem;"> Créditos (Pague por Uso)</strong>
          </div>
          <span id="creditos-saldo-badge" style="background:#89b4fa;color:#1e1e2e;padding:2px 8px;border-radius:10px;font-size:0.72rem;font-weight:700;">...</span>
        </div>
        <p style="font-size:0.72rem;color:#9399b2;margin-bottom:10px;">1 crédito = 3 dias de Premium. Compre na quantidade que quiser, ative quando precisar. Créditos não expiram!</p>
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(90px, 1fr));gap:6px;margin-bottom:10px;">
          <button onclick="comprarCreditos(1)" style="padding:8px 4px;background:#313244;border:1px solid #45475a;border-radius:6px;color:#cdd6f4;cursor:pointer;font-size:0.7rem;text-align:center;">
            <div style="font-weight:700;">1 créd</div><div style="color:#89b4fa;">R$4,90</div><div style="color:#585b70;font-size:0.6rem;">3 dias</div>
          </button>
          <button onclick="comprarCreditos(5)" style="padding:8px 4px;background:#313244;border:1px solid #45475a;border-radius:6px;color:#cdd6f4;cursor:pointer;font-size:0.7rem;text-align:center;">
            <div style="font-weight:700;">5 créd</div><div style="color:#89b4fa;">R$19,90</div><div style="color:#a6e3a1;font-size:0.6rem;">15d • -19%</div>
          </button>
          <button onclick="comprarCreditos(10)" style="padding:8px 4px;background:#313244;border:1px solid #f9e2af;border-radius:6px;color:#cdd6f4;cursor:pointer;font-size:0.7rem;text-align:center;">
            <div style="font-weight:700;">10 créd</div><div style="color:#89b4fa;">R$34,90</div><div style="color:#a6e3a1;font-size:0.6rem;">30d • -29%</div>
          </button>
          <button onclick="comprarCreditos(20)" style="padding:8px 4px;background:#313244;border:1px solid #45475a;border-radius:6px;color:#cdd6f4;cursor:pointer;font-size:0.7rem;text-align:center;">
            <div style="font-weight:700;">20 créd</div><div style="color:#89b4fa;">R$59,90</div><div style="color:#a6e3a1;font-size:0.6rem;">60d • -39%</div>
          </button>
          <button onclick="comprarCreditos(50)" style="padding:8px 4px;background:#313244;border:1px solid #a6e3a1;border-radius:6px;color:#cdd6f4;cursor:pointer;font-size:0.7rem;text-align:center;">
            <div style="font-weight:700;">50 créd</div><div style="color:#89b4fa;">R$119,90</div><div style="color:#a6e3a1;font-size:0.6rem;">150d • -51%</div>
          </button>
        </div>
        <div id="creditos-ativar-section" style="display:none;padding:8px;background:#313244;border-radius:6px;margin-bottom:8px;">
          <div style="font-size:0.75rem;color:#cdd6f4;margin-bottom:6px;">Ativar créditos:</div>
          <div style="display:flex;gap:6px;align-items:center;">
            <input id="creditos-ativar-input" type="number" min="1" value="10" style="width:60px;padding:6px;background:#1e1e2e;border:1px solid #45475a;border-radius:4px;color:#cdd6f4;font-size:0.82rem;">
            <span style="font-size:0.7rem;color:#9399b2;">créditos =</span>
            <span id="creditos-dias-preview" style="font-size:0.82rem;color:#a6e3a1;font-weight:600;">30 dias</span>
            <button onclick="ativarCreditos()" style="padding:6px 12px;background:#89b4fa;color:#1e1e2e;border:none;border-radius:4px;font-size:0.75rem;font-weight:600;cursor:pointer;">Ativar</button>
          </div>
        </div>
      </div>
      <button onclick="document.getElementById('upgrade-modal').remove()" style="display:block;width:100%;margin-top:12px;padding:10px;background:#45475a;color:#cdd6f4;border:none;border-radius:8px;cursor:pointer;">Fechar</button>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  _loadCreditosSaldo();
  _loadVitalicioStatus();
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


// ==================== SISTEMA DE CRÉDITOS (UI) ====================

export async function comprarCreditos(quantidade) {
  try {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    // Criar cobrança PIX via Mercado Pago
    const res = await fetch('/api/pagamentos/pix/criar', {
      method: 'POST', headers,
      body: JSON.stringify({ creditos: quantidade })
    });
    const data = await res.json();

    if (data.ok && data.pix) {
      _showPixQRCode(data);
    } else if (data.detail && data.detail.includes('Token')) {
      // Fallback: creditar direto (modo dev/sandbox sem token configurado)
      const resFallback = await fetch('/api/auth/creditos/comprar', {
        method: 'POST', headers,
        body: JSON.stringify({ quantidade })
      });
      const dataFallback = await resFallback.json();
      if (dataFallback.ok) {
        const _toast = window.toast || window.showToast;
        if (_toast) _toast(`✅ ${quantidade} crédito(s) adicionados (modo sandbox)! Saldo: ${dataFallback.saldo_posterior}`, 'success');
        _loadCreditosSaldo();
      } else {
        const _toast = window.toast || window.showToast;
        if (_toast) _toast(dataFallback.detail || 'Erro ao comprar créditos', 'error');
      }
    } else {
      const _toast = window.toast || window.showToast;
      if (_toast) _toast(data.detail || 'Erro ao criar pagamento', 'error');
    }
  } catch(e) {
    const _toast = window.toast || window.showToast;
    if (_toast) _toast('Erro de conexão', 'error');
  }
}

function _showPixQRCode(data) {
  const section = document.getElementById('creditos-section');
  if (!section) return;

  const { payment_id, valor, creditos, dias, pix } = data;

  section.innerHTML = `
    <div style="text-align:center;">
      <div style="font-size:1.2rem;margin-bottom:6px;">📱 PIX - Escaneie para pagar</div>
      <div style="font-size:0.82rem;color:#a6e3a1;font-weight:600;margin-bottom:10px;">R$${valor.toFixed(2)} → ${creditos} créditos (${dias} dias Premium)</div>
      ${pix.qr_code_base64 ? `<img src="data:image/png;base64,${pix.qr_code_base64}" style="width:200px;height:200px;border-radius:8px;margin-bottom:10px;" alt="QR Code PIX">` : ''}
      <div style="margin-bottom:10px;">
        <div style="font-size:0.72rem;color:#9399b2;margin-bottom:4px;">Ou copie o código PIX:</div>
        <div style="display:flex;gap:6px;">
          <input id="pix-code-input" type="text" value="${pix.qr_code}" readonly style="flex:1;padding:8px;background:#1e1e2e;border:1px solid #45475a;border-radius:6px;color:#cdd6f4;font-size:0.7rem;font-family:monospace;">
          <button onclick="navigator.clipboard.writeText(document.getElementById('pix-code-input').value);(window.toast||window.showToast)('📋 Código PIX copiado!','success')" style="padding:8px 12px;background:#89b4fa;color:#1e1e2e;border:none;border-radius:6px;font-size:0.75rem;font-weight:600;cursor:pointer;">Copiar</button>
        </div>
      </div>
      <div style="font-size:0.68rem;color:#585b70;margin-bottom:10px;">⏱ Expira em 30 minutos</div>
      <button onclick="_checkPixStatus('${payment_id}')" id="pix-check-btn" style="padding:8px 16px;background:#a6e3a1;color:#1e1e2e;border:none;border-radius:6px;font-size:0.82rem;font-weight:600;cursor:pointer;">🔄 Verificar Pagamento</button>
      <button onclick="_loadCreditosSaldo();location.reload()" style="margin-left:8px;padding:8px 12px;background:#45475a;color:#9399b2;border:none;border-radius:6px;font-size:0.75rem;cursor:pointer;">Cancelar</button>
      <div id="pix-status" style="margin-top:8px;font-size:0.78rem;"></div>
    </div>
  `;

  // Auto-check a cada 5s
  window._pixCheckInterval = setInterval(() => _checkPixStatus(payment_id), 5000);
}

async function _checkPixStatus(paymentId) {
  try {
    const token = getToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(`/api/pagamentos/status/${paymentId}`, { headers });
    const data = await res.json();

    const statusEl = document.getElementById('pix-status');
    if (statusEl) statusEl.innerHTML = `<span style="color:${data.aprovado ? '#a6e3a1' : '#f9e2af'};">${data.status_label}</span>`;

    if (data.aprovado) {
      // Pagamento aprovado!
      clearInterval(window._pixCheckInterval);
      const _toast = window.toast || window.showToast;
      if (_toast) _toast('✅ Pagamento confirmado! Créditos adicionados.', 'success');
      setTimeout(() => {
        _loadCreditosSaldo();
        // Recarregar modal
        document.getElementById('upgrade-modal')?.remove();
        showUpgradeModal();
      }, 1500);
    }
  } catch(e) {}
}
window._checkPixStatus = _checkPixStatus;

export async function ativarCreditos() {
  const input = document.getElementById('creditos-ativar-input');
  const creditos = parseInt(input?.value || '0');
  if (creditos < 1) {
    const _toast = window.toast || window.showToast;
    if (_toast) _toast('Mínimo 1 crédito', 'warning');
    return;
  }

  try {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch('/api/auth/creditos/ativar', {
      method: 'POST', headers,
      body: JSON.stringify({ creditos })
    });
    const data = await res.json();
    if (data.ok) {
      const _toast = window.toast || window.showToast;
      if (_toast) _toast(data.mensagem, 'success');
      _loadCreditosSaldo();
    } else {
      const _toast = window.toast || window.showToast;
      if (_toast) _toast(data.detail || 'Erro ao ativar créditos', 'error');
    }
  } catch(e) {
    const _toast = window.toast || window.showToast;
    if (_toast) _toast('Erro de conexão', 'error');
  }
}

async function _loadCreditosSaldo() {
  try {
    const token = getToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch('/api/auth/creditos', { headers });
    const data = await res.json();

    const badge = document.getElementById('creditos-saldo-badge');
    if (badge) badge.textContent = `${data.saldo} créditos (${data.dias_disponiveis} dias)`;

    // Mostrar seção de ativar se tem saldo
    const ativarSection = document.getElementById('creditos-ativar-section');
    if (ativarSection) {
      ativarSection.style.display = data.saldo > 0 ? 'block' : 'none';
      const input = document.getElementById('creditos-ativar-input');
      if (input) input.max = data.saldo;
    }

    // Preview de dias ao mudar input
    const input = document.getElementById('creditos-ativar-input');
    if (input) {
      input.oninput = () => {
        const dias = parseInt(input.value || '0') * (data.dias_por_credito || 3);
        const preview = document.getElementById('creditos-dias-preview');
        if (preview) preview.textContent = `${dias} dias`;
      };
    }
  } catch(e) {}
}

// Carregar saldo quando modal abre (chamado pelo showUpgradeModal via event)
export function loadCreditosSaldo() { _loadCreditosSaldo(); }

// ==================== VITALÍCIO — JANELA DE VENDA ====================

async function _loadVitalicioStatus() {
  const container = document.getElementById('vitalicio-btn-container');
  if (!container) return;

  try {
    const res = await fetch('/api/auth/vitalicio-status');
    const data = await res.json();

    if (data.disponivel) {
      container.innerHTML = `
        <button onclick="comprarVitalicio()" style="width:100%;padding:10px;border:none;border-radius:6px;background:#a6e3a1;color:#1e1e2e;font-size:0.82rem;font-weight:600;cursor:pointer;">💎 Comprar Vitalício</button>
        ${data.dias_restantes != null ? `<div style="font-size:0.65rem;color:#f9e2af;margin-top:4px;text-align:center;">⏳ ${data.dias_restantes} dia(s) restantes!</div>` : ''}
      `;
    } else {
      container.innerHTML = `
        <div style="padding:8px;border:1px solid #45475a;border-radius:6px;text-align:center;">
          <div style="font-size:0.75rem;color:#9399b2;">${data.motivo}</div>
          ${data.inicio ? `<div style="font-size:0.65rem;color:#585b70;margin-top:4px;">Período: ${data.inicio} a ${data.fim}</div>` : ''}
        </div>
      `;
    }
  } catch(e) {
    // Erro de rede: permitir (fallback)
    container.innerHTML = `<button onclick="comprarVitalicio()" style="width:100%;padding:10px;border:none;border-radius:6px;background:#a6e3a1;color:#1e1e2e;font-size:0.82rem;font-weight:600;cursor:pointer;">💎 Comprar Vitalício</button>`;
  }
}

export async function comprarVitalicio() {
  try {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch('/api/pagamentos/pix/vitalicio', {
      method: 'POST', headers, body: JSON.stringify({})
    });
    const data = await res.json();

    if (res.status === 403) {
      const _toast = window.toast || window.showToast;
      if (_toast) _toast(data.detail || 'Vitalício não disponível no momento.', 'warning');
      return;
    }

    if (data.ok && data.pix) {
      _showPixQRCode({ ...data, creditos: 0, dias: '∞ (permanente)' });
    } else {
      const _toast = window.toast || window.showToast;
      if (_toast) _toast(data.detail || 'Erro ao criar pagamento', 'error');
    }
  } catch(e) {
    const _toast = window.toast || window.showToast;
    if (_toast) _toast('Erro de conexão', 'error');
  }
}

// ==================== EXPOR NO WINDOW ====================
// Funções usadas em onclick inline gerados dinamicamente (modais/menus).
// Necessário em TODAS as páginas que importem auth.js (regra #4).
Object.assign(window, {
  showUpgradeModal, doUpgrade, comprarCreditos, ativarCreditos, comprarVitalicio,
  showEditProfileModal, saveProfile, logout, handleAuthNav,
});
