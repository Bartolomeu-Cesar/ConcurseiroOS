/**
 * Auth Interceptor — Injeta token JWT em todas as chamadas fetch para /api/
 * Também verifica se o usuário está autenticado quando AUTH_ENABLED=true.
 * Intercepta respostas 401 e redireciona para login.
 * Incluir ANTES de qualquer outro script nas páginas.
 */
(function() {
  const _originalFetch = window.fetch;
  window.fetch = function(url, options) {
    const token = localStorage.getItem('auth_token');
    if (token && typeof url === 'string' && (url.startsWith('/api/') || url.includes('/api/'))) {
      options = Object.assign({}, options);
      options.headers = Object.assign({}, options.headers || {});
      if (!options.headers['Authorization'] && !options.headers['authorization']) {
        options.headers['Authorization'] = 'Bearer ' + token;
      }
    }
    return _originalFetch.call(this, url, options).then(response => {
      // Se receber 401, token expirou ou é inválido → redirecionar para login
      if (response.status === 401 && window.location.pathname !== '/login.html') {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_user');
        window.location.href = '/login.html';
      }
      return response;
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
