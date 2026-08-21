/**
 * Auth Interceptor — Injeta token JWT em todas as chamadas fetch para /api/
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
    return _originalFetch.call(this, url, options);
  };
})();
