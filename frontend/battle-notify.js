/**
 * battle-notify.js — Notificação global de batalha ativa.
 * Incluir em todas as páginas (carregado pelo sidebar.js).
 * Faz polling a cada 10s para verificar se há batalha pendente/iniciada.
 * Mostra toast com opção de participar ou dispensar.
 */
(function() {
  'use strict';

  // Não rodar na própria página de batalha
  if (window.location.pathname.includes('batalha.html')) return;

  let _dismissed = sessionStorage.getItem('battle_dismissed') || '';
  let _notifying = false;

  function showBattleNotification(data, status) {
    _notifying = true;

    // Remove notificação anterior se existir
    document.getElementById('battle-global-notify')?.remove();

    const isStarted = status === 'em_andamento';
    const msg = isStarted
      ? `⚔️ Batalha "${data.titulo}" começou! Rodada ${data.rodada_atual}/${data.total_rodadas}`
      : `⚔️ Batalha "${data.titulo}" está pronta para iniciar!`;

    const el = document.createElement('div');
    el.id = 'battle-global-notify';
    el.style.cssText = `
      position: fixed; bottom: 96px; right: 20px; z-index: 99999;
      background: #313244; border: 2px solid ${isStarted ? '#a6e3a1' : '#f9e2af'};
      border-radius: 14px; padding: 16px 20px; max-width: 360px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      animation: slideInRight 0.3s ease-out;
      font-family: sans-serif;
    `;
    el.innerHTML = `
      <style>
        @keyframes slideInRight { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        #battle-global-notify .btn-notify { padding: 8px 14px; border: none; border-radius: 8px; font-size: 0.82rem; font-weight: 600; cursor: pointer; }
      </style>
      <div style="font-size:0.9rem;color:#cdd6f4;margin-bottom:10px;line-height:1.4;">${msg}</div>
      <div style="display:flex;gap:8px;">
        <button class="btn-notify" onclick="window._battleJoin('${data.codigo}')" style="background:#a6e3a1;color:#1e1e2e;flex:1;">
          ${isStarted ? '🎮 Participar Agora' : '👀 Ir para Sala'}
        </button>
        <button class="btn-notify" onclick="window._battleDismiss('${data.codigo}')" style="background:#45475a;color:#cdd6f4;">
          Dispensar
        </button>
      </div>
    `;
    document.body.appendChild(el);

    // Auto-remove after 30s
    setTimeout(() => {
      el.remove();
      _notifying = false;
    }, 30000);
  }

  window._battleJoin = function(codigo) {
    document.getElementById('battle-global-notify')?.remove();
    _notifying = false;
    window.location.href = `/batalha.html?code=${codigo}`;
  };

  window._battleDismiss = function(codigo) {
    document.getElementById('battle-global-notify')?.remove();
    _notifying = false;
    _dismissed = codigo;
    sessionStorage.setItem('battle_dismissed', codigo);
  };

  // ==================== POLLING ADAPTATIVO ====================
  // Reduz carga/logs: pausa quando a aba está oculta e espaça o polling
  // progressivamente quando não há batalha ativa (backoff).
  const INTERVAL_BASE = 15000;   // 15s quando há atividade recente
  const INTERVAL_MAX = 120000;   // até 2min quando ocioso
  let _intervalAtual = INTERVAL_BASE;
  let _vazios = 0;               // contagem de checks sem batalha
  let _timer = null;

  async function checkBatalhaAdaptativo() {
    // Não faz polling se aba oculta ou deslogado
    if (document.hidden || !localStorage.getItem('auth_token')) {
      _agendarProximo();
      return;
    }
    try {
      const r = await fetch('/api/batalha/pendente');
      if (r.ok) {
        const data = await r.json();
        if (data && data.ativa) {
          _vazios = 0;
          _intervalAtual = INTERVAL_BASE; // volta a checar rápido
          if (_dismissed !== data.codigo && !_notifying) {
            if (data.status === 'em_andamento') showBattleNotification(data, 'em_andamento');
            else if (data.status === 'aguardando' && !data.is_creator) showBattleNotification(data, 'aguardando');
          }
        } else {
          // Sem batalha: aumentar o intervalo progressivamente (backoff)
          _vazios++;
          if (_vazios >= 3) _intervalAtual = Math.min(_intervalAtual * 1.5, INTERVAL_MAX);
        }
      }
    } catch (e) { /* silencioso */ }
    _agendarProximo();
  }

  function _agendarProximo() {
    clearTimeout(_timer);
    _timer = setTimeout(checkBatalhaAdaptativo, _intervalAtual);
  }

  // Ao voltar para a aba, resetar para polling rápido e checar já
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      _vazios = 0;
      _intervalAtual = INTERVAL_BASE;
      clearTimeout(_timer);
      checkBatalhaAdaptativo();
    }
  });

  // Check inicial após 2s (dá tempo do app carregar)
  setTimeout(checkBatalhaAdaptativo, 2000);
})();
