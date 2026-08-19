// ==================== ESTADO GLOBAL COMPARTILHADO ====================
// Centraliza variáveis que múltiplos módulos precisam acessar/modificar

export const state = {
  editalData: [],
  isOffline: false,
  noteCurrentId: null,
  selectModalCallback: null,
  editalSelectedId: null,
};
