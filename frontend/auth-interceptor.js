/**
 * Auth Interceptor — Injeta token JWT em todas as chamadas fetch para /api/
 * e, em resposta 401, tenta RENOVAR o access token via /api/auth/refresh ANTES
 * de deslogar. Só redireciona para o login se o refresh também falhar.
 *
 * Isso evita o logout no meio de uma sessão de estudo: o access token expira em
 * ~1h, mas o refresh token dura vários dias — a renovação é transparente e a
 * requisição original é reexecutada com o novo token.
 *
 * Incluir ANTES de qualquer outro script nas páginas.
 */
(function() {
  const _originalFetch = window.fetch;

  // Garante um único refresh em voo mesmo com várias requisições recebendo 401
  // simultaneamente (evita corrida de múltiplos refresh / logout duplicado).
  let _refreshPromise = null;

  function _isApiUrl(url) {
    return typeof url === 'string' && (url.startsWith('/api/') || url.includes('/api/'));
  }

  function _logout() {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_user');
    localStorage.removeItem('refresh_token');
    if (window.location.pathname !== '/login.html') {
      window.location.href = '/login.html';
    }
  }

  // Tenta renovar o access token. Retorna o novo token ou null. Compartilhado
  // entre chamadas concorrentes via _refreshPromise.
  function _tryRefresh() {
    if (_refreshPromise) return _refreshPromise;
    const refresh = localStorage.getItem('refresh_token');
    if (!refresh) return Promise.resolve(null);
    _refreshPromise = _originalFetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (data && data.access_token) {
          localStorage.setItem('auth_token', data.access_token);
          if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
          return data.access_token;
        }
        return null;
      })
      .catch(() => null)
      .finally(() => { _refreshPromise = null; });
    return _refreshPromise;
  }

  function _withAuth(url, options, token) {
    if (!token || !_isApiUrl(url)) return options;
    const opts = Object.assign({}, options);
    opts.headers = Object.assign({}, opts.headers || {});
    if (!opts.headers['Authorization'] && !opts.headers['authorization']) {
      opts.headers['Authorization'] = 'Bearer ' + token;
    }
    return opts;
  }

  window.fetch = function(url, options) {
    const token = localStorage.getItem('auth_token');
    const finalOpts = _withAuth(url, options, token);

    return _originalFetch.call(this, url, finalOpts).then(response => {
      // 401 → token expirado/inválido. Tenta renovar UMA vez e reexecutar.
      // Nunca tenta renovar a própria rota de refresh (evita loop).
      const isRefreshCall = typeof url === 'string' && url.includes('/api/auth/refresh');
      if (response.status !== 401 || isRefreshCall || window.location.pathname === '/login.html') {
        return response;
      }
      // Sem refresh token disponível → logout direto (comportamento antigo).
      if (!localStorage.getItem('refresh_token')) {
        _logout();
        return response;
      }
      return _tryRefresh().then(newToken => {
        if (!newToken) {
          // Refresh falhou (expirado/revogado): agora sim desloga.
          _logout();
          return response;
        }
        // Reexecuta a requisição original com o novo token (transparente).
        const retryOpts = _withAuth(url, options, newToken);
        return _originalFetch.call(this, url, retryOpts);
      });
    });
  };

  // Auth guard: verificar se precisa estar logado (apenas no carregamento da página)
  if (window.location.pathname !== '/login.html') {
    _originalFetch('/api/auth/status')
      .then(r => r.json())
      .then(status => {
        if (status.auth_enabled && !localStorage.getItem('auth_token')) {
          window.location.href = '/login.html';
        }
      })
      .catch(() => { /* offline — permitir acesso */ });
  }
})();
