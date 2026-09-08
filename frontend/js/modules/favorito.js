// favorito.js — Edital favorito de estudos, persistido no BANCO (sincroniza entre
// estações) com cache em localStorage para leitura síncrona rápida e offline.
//
// Formato do valor: "edital|cargo" (mantém compatibilidade com o antigo
// localStorage `countdown_favorito`). Vazio = modo automático (prova mais próxima).

const LS_KEY = 'countdown_favorito';

/**
 * Leitura SÍNCRONA do cache local (localStorage). Use quando precisar do valor
 * imediatamente na renderização. O cache é mantido em dia por syncFavorito()/setFavorito().
 * @returns {string} "edital|cargo" ou "".
 */
export function getFavoritoCache() {
  try { return localStorage.getItem(LS_KEY) || ''; } catch (e) { return ''; }
}

/**
 * Busca o favorito no BANCO e atualiza o cache local. Faz a MIGRAÇÃO automática:
 * se o banco estiver vazio mas houver valor no localStorage (usuário antigo),
 * grava esse valor no banco. Retorna o valor efetivo ("edital|cargo" ou "").
 */
export async function syncFavorito() {
  const local = getFavoritoCache();
  try {
    const res = await fetch('/api/config/edital-favorito');
    if (!res.ok) return local; // backend indisponível → usa cache
    const data = await res.json();
    const doBanco = data && data.valor ? data.valor : '';
    if (doBanco) {
      // Banco é a fonte de verdade: atualiza o cache local.
      try { localStorage.setItem(LS_KEY, doBanco); } catch (e) {}
      return doBanco;
    }
    // Banco vazio: migra o valor local existente (uma única vez).
    if (local) {
      const [edital, cargo] = local.split('|');
      await setFavorito(edital || '', cargo || '');
      return local;
    }
    return '';
  } catch (e) {
    return local; // erro de rede → cache
  }
}

/**
 * Define o favorito no BANCO e atualiza o cache local. Passe strings vazias para
 * limpar (modo automático). Retorna o valor efetivo ("edital|cargo" ou "").
 * @param {string} edital
 * @param {string} cargo
 */
export async function setFavorito(edital, cargo) {
  const valor = edital ? `${edital}|${cargo || ''}` : '';
  // Atualiza o cache local imediatamente (UX responsiva mesmo se a rede falhar).
  try {
    if (valor) localStorage.setItem(LS_KEY, valor);
    else localStorage.removeItem(LS_KEY);
  } catch (e) {}
  try {
    await fetch('/api/config/edital-favorito', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ edital_nome: edital || '', cargo: cargo || '' }),
    });
  } catch (e) { /* offline: fica só no cache; sincroniza no próximo syncFavorito */ }
  return valor;
}
