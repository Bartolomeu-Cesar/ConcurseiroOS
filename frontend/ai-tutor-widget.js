/**
 * AI Tutor Widget — Chat flutuante disponível em todas as páginas.
 * Carregado via sidebar.js em qualquer página do ConcurseiroOS.
 */
(function() {
  'use strict';

  // Don't inject if already exists or if on social page (has its own AI tab)
  if (document.getElementById('ai-tutor-widget')) return;

  const STORAGE_KEY = 'ai_tutor_history';
  const MAX_HISTORY = 50;

  function getHistory() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
    catch { return []; }
  }

  function saveHistory(msgs) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(msgs.slice(-MAX_HISTORY)));
  }

  function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  // Renderiza markdown de forma segura. Usa window.renderMarkdown (módulo) se
  // disponível; senão aplica um fallback mínimo (negrito/itálico/quebras).
  function renderMd(text) {
    if (typeof window.renderMarkdown === 'function') return window.renderMarkdown(text);
    let t = escapeHtml(String(text || ''));
    t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
         .replace(/(^|[^*])\*([^*\n]+)\*([^*]|$)/g, '$1<em>$2</em>$3')
         .replace(/`([^`\n]+)`/g, '<code>$1</code>')
         .replace(/\n/g, '<br>');
    return t;
  }

  function timeStr() {
    return new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }

  // Inject CSS
  const style = document.createElement('style');
  style.textContent = `
    #ai-tutor-fab {
      position: fixed; bottom: 24px; right: 24px; z-index: 99990;
      width: 56px; height: 56px; border-radius: 50%;
      background: linear-gradient(135deg, var(--accent, #cba6f7), var(--blue, #89b4fa));
      border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
      font-size: 1.6rem; box-shadow: 0 4px 16px rgba(203,166,247,0.4);
      transition: transform 0.2s, box-shadow 0.2s;
      animation: ai-fab-pulse 3s infinite;
    }
    #ai-tutor-fab:hover { transform: scale(1.1); box-shadow: 0 6px 24px rgba(203,166,247,0.5); }
    #ai-tutor-fab.open { animation: none; transform: rotate(45deg) scale(1.05); }
    /* Estado oculto temporário: some do caminho para liberar cliques em botões atrás */
    #ai-tutor-fab.hidden-temp {
      opacity: 0; transform: scale(0.4) translateY(10px);
      pointer-events: none; animation: none;
      transition: opacity 0.3s ease, transform 0.3s ease;
    }
    @keyframes ai-fab-pulse {
      0%, 100% { box-shadow: 0 4px 16px rgba(203,166,247,0.4); }
      50% { box-shadow: 0 4px 24px rgba(203,166,247,0.6); }
    }

    #ai-tutor-panel {
      position: fixed; bottom: 90px; right: 24px; z-index: 99991;
      width: 380px; max-width: calc(100vw - 32px); height: 500px; max-height: 70vh;
      background: var(--bg-surface, #313244); border: 1px solid var(--border, #45475a);
      border-radius: 16px; display: none; flex-direction: column;
      box-shadow: 0 8px 40px rgba(0,0,0,0.4);
      animation: ai-panel-in 0.25s ease;
      overflow: hidden;
    }
    #ai-tutor-panel.show { display: flex; }
    @keyframes ai-panel-in {
      from { opacity: 0; transform: translateY(20px) scale(0.95); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }

    .ai-panel-header {
      display: flex; align-items: center; gap: 10px;
      padding: 14px 16px; border-bottom: 1px solid var(--border, #45475a);
      background: var(--bg, #1e1e2e);
    }
    .ai-panel-header h4 { margin: 0; font-size: 0.92rem; color: var(--text, #cdd6f4); flex: 1; }
    .ai-panel-header button {
      background: none; border: none; color: var(--text-sub, #9399b2);
      font-size: 1.1rem; cursor: pointer; padding: 4px; border-radius: 4px;
      transition: color 0.2s, background 0.2s;
    }
    .ai-panel-header button:hover { color: var(--text, #cdd6f4); background: var(--bg-elevated, #45475a); }

    .ai-panel-messages {
      flex: 1; overflow-y: auto; padding: 12px; display: flex;
      flex-direction: column; gap: 10px; scroll-behavior: smooth;
    }
    .ai-panel-messages::-webkit-scrollbar { width: 4px; }
    .ai-panel-messages::-webkit-scrollbar-thumb { background: var(--border, #45475a); border-radius: 2px; }

    .ai-msg {
      max-width: 85%; padding: 10px 14px; border-radius: 12px;
      font-size: 0.85rem; line-height: 1.5; word-wrap: break-word;
      animation: ai-msg-in 0.2s ease;
    }
    @keyframes ai-msg-in {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .ai-msg.user {
      align-self: flex-end; background: var(--blue, #89b4fa); color: var(--bg, #1e1e2e);
      border-bottom-right-radius: 4px;
    }
    .ai-msg.ai {
      align-self: flex-start; background: var(--bg-elevated, #45475a); color: var(--text, #cdd6f4);
      border-bottom-left-radius: 4px;
    }
    .ai-msg .ai-msg-time {
      font-size: 0.6rem; opacity: 0.6; margin-top: 4px; text-align: right;
    }
    .ai-msg.ai .ai-msg-time { text-align: left; }

    .ai-typing { display: flex; gap: 4px; padding: 10px 14px; align-self: flex-start;
      background: var(--bg-elevated, #45475a); border-radius: 12px; border-bottom-left-radius: 4px; }
    .ai-typing span { width: 7px; height: 7px; background: var(--text-sub, #9399b2);
      border-radius: 50%; animation: ai-bounce 1.4s infinite ease-in-out; }
    .ai-typing span:nth-child(2) { animation-delay: 0.2s; }
    .ai-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes ai-bounce { 0%,60%,100% { transform: translateY(0); } 30% { transform: translateY(-6px); } }

    .ai-panel-input {
      display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--border, #45475a);
      background: var(--bg, #1e1e2e);
    }
    .ai-panel-input input {
      flex: 1; background: var(--bg-surface, #313244); border: 1px solid var(--border, #45475a);
      border-radius: 8px; padding: 10px 12px; color: var(--text, #cdd6f4);
      font-size: 0.85rem; font-family: inherit; outline: none;
      transition: border-color 0.2s;
    }
    .ai-panel-input input:focus { border-color: var(--accent, #cba6f7); }
    .ai-panel-input input::placeholder { color: var(--text-sub, #9399b2); }
    .ai-panel-input button {
      background: var(--accent, #cba6f7); color: var(--bg, #1e1e2e); border: none;
      border-radius: 8px; padding: 10px 16px; font-weight: 700; font-size: 0.82rem;
      cursor: pointer; transition: opacity 0.2s;
    }
    .ai-panel-input button:hover { opacity: 0.9; }
    .ai-panel-input button:disabled { opacity: 0.5; cursor: not-allowed; }

    @media (max-width: 480px) {
      #ai-tutor-panel { width: calc(100vw - 16px); right: 8px; bottom: 80px; height: 60vh; }
      #ai-tutor-fab { bottom: 16px; right: 16px; width: 50px; height: 50px; font-size: 1.4rem; }
    }
  `;
  document.head.appendChild(style);

  // Create FAB button
  // Ícone "megamente": cabeça grande azul estilizada (SVG original, próprio —
  // remete a um tutor genial de cabeçorra, sem copiar personagem protegido).
  const MEGA_HEAD_SVG = `<svg viewBox="0 0 48 48" width="30" height="30" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <ellipse cx="24" cy="17" rx="15" ry="14" fill="#dbe9ff"/>
    <path d="M24 3c8.8 0 15 5.8 15 14 0 5.2-3 8.6-6 10.5V29c0 1.1-.9 2-2 2H17c-1.1 0-2-.9-2-2v-1.5C12 25.6 9 22.2 9 17 9 8.8 15.2 3 24 3z" fill="#eaf2ff"/>
    <path d="M16 33c0-1.1.9-2 2-2h12c1.1 0 2 .9 2 2l1.5 8c.2 1.3-.8 2.5-2 2.5H16.5c-1.2 0-2.2-1.2-2-2.5L16 33z" fill="#89b4fa"/>
    <ellipse cx="18" cy="18" rx="3.2" ry="3.6" fill="#1e2333"/>
    <ellipse cx="30" cy="18" rx="3.2" ry="3.6" fill="#1e2333"/>
    <circle cx="19.1" cy="16.9" r="1" fill="#fff"/>
    <circle cx="31.1" cy="16.9" r="1" fill="#fff"/>
    <path d="M19 25c1.8 1.6 8.2 1.6 10 0" stroke="#5b6178" stroke-width="1.6" stroke-linecap="round"/>
    <path d="M13.5 11.5c2-2 4.5-3 7-3M34.5 11.5c-2-2-4.5-3-7-3" stroke="#b9cdf0" stroke-width="1.4" stroke-linecap="round"/>
  </svg>`;
  const fab = document.createElement('button');
  fab.id = 'ai-tutor-fab';
  fab.innerHTML = MEGA_HEAD_SVG;
  fab.title = 'AI Tutor — clique para abrir · duplo clique (ou segurar) para ocultar por alguns segundos';
  fab.setAttribute('aria-label', 'Abrir AI Tutor');

  // Create panel
  const panel = document.createElement('div');
  panel.id = 'ai-tutor-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'AI Tutor Chat');
  panel.innerHTML = `
    <div class="ai-panel-header">
      <span style="font-size:1.3rem;">🤖</span>
      <h4>AI Tutor</h4>
      <button onclick="document.getElementById('ai-tutor-widget-clear').click()" title="Limpar histórico">🗑️</button>
      <button onclick="toggleAITutor()" title="Fechar">✕</button>
    </div>
    <div class="ai-panel-messages" id="ai-widget-messages"></div>
    <div class="ai-panel-input">
      <input type="text" id="ai-widget-input" placeholder="Pergunte algo ao tutor..." autocomplete="off">
      <button id="ai-widget-send">Enviar</button>
    </div>
    <button id="ai-tutor-widget-clear" style="display:none;"></button>
  `;

  // Wrap
  const widget = document.createElement('div');
  widget.id = 'ai-tutor-widget';
  widget.appendChild(fab);
  widget.appendChild(panel);

  function inject() {
    if (!document.body) return;
    document.body.appendChild(widget);
    setupEvents();
    loadChatHistory();
  }

  function setupEvents() {
    // Distingue clique simples (abrir chat) de duplo clique (ocultar), e evita
    // que um long-press dispare o clique de abrir. Um único handler de clique
    // com debounce curto resolve o single-vs-double de forma robusta.
    let clickTimer = null;
    let suppressClick = false;

    fab.addEventListener('click', () => {
      if (suppressClick) { suppressClick = false; return; }
      if (clickTimer) return; // já há um clique pendente (será tratado como parte do dblclick)
      clickTimer = setTimeout(() => { clickTimer = null; toggleAITutor(); }, 220);
    });

    fab.addEventListener('dblclick', (e) => {
      e.preventDefault();
      if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
      hideFabTemporarily();
    });

    // Long-press (mobile): segurar ~600ms oculta o FAB.
    let pressTimer = null;
    const startPress = () => {
      pressTimer = setTimeout(() => {
        pressTimer = null;
        suppressClick = true; // impede que o clique subsequente abra o chat
        if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
        hideFabTemporarily();
      }, 600);
    };
    const cancelPress = () => { if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; } };
    fab.addEventListener('touchstart', startPress, { passive: true });
    fab.addEventListener('touchend', cancelPress);
    fab.addEventListener('touchmove', cancelPress);

    const input = document.getElementById('ai-widget-input');
    const sendBtn = document.getElementById('ai-widget-send');
    const clearBtn = document.getElementById('ai-tutor-widget-clear');

    sendBtn.addEventListener('click', sendMessage);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) sendMessage(); });
    clearBtn.addEventListener('click', clearChat);

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && panel.classList.contains('show')) {
        toggleAITutor();
      }
    });
  }

  // Oculta o botão flutuante por alguns segundos e o traz de volta automaticamente.
  // Se o painel do chat estiver aberto, fecha primeiro. Duração padrão: 5s.
  let hideTimer = null;
  window.hideAITutorFab = function(seconds = 5) {
    if (panel.classList.contains('show')) toggleAITutor();
    fab.classList.add('hidden-temp');
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      fab.classList.remove('hidden-temp');
      hideTimer = null;
    }, Math.max(1, seconds) * 1000);
  };
  function hideFabTemporarily() { window.hideAITutorFab(5); }

  window.toggleAITutor = function() {
    const isOpen = panel.classList.toggle('show');
    fab.classList.toggle('open', isOpen);
    fab.innerHTML = isOpen ? '✕' : MEGA_HEAD_SVG;
    if (isOpen) {
      setTimeout(() => document.getElementById('ai-widget-input').focus(), 200);
      const msgs = document.getElementById('ai-widget-messages');
      msgs.scrollTop = msgs.scrollHeight;
    }
  };

  function loadChatHistory() {
    const history = getHistory();
    const container = document.getElementById('ai-widget-messages');
    if (!history.length) {
      container.innerHTML = `<div class="ai-msg ai">Olá! Sou seu tutor. Pergunte qualquer dúvida sobre sua matéria de estudo. 🎓<div class="ai-msg-time">Agora</div></div>`;
      return;
    }
    container.innerHTML = history.map(m =>
      `<div class="ai-msg ${m.role}${m.role === 'ai' ? ' md-content' : ''}">${m.role === 'ai' ? renderMd(m.text) : escapeHtml(m.text)}<div class="ai-msg-time">${m.time || ''}</div></div>`
    ).join('');
    container.scrollTop = container.scrollHeight;
  }

  function clearChat() {
    localStorage.removeItem(STORAGE_KEY);
    const container = document.getElementById('ai-widget-messages');
    container.innerHTML = `<div class="ai-msg ai">Histórico limpo. Como posso ajudar? 🎓<div class="ai-msg-time">${timeStr()}</div></div>`;
  }

  async function sendMessage() {
    const input = document.getElementById('ai-widget-input');
    const msg = input.value.trim();
    if (!msg) return;

    const container = document.getElementById('ai-widget-messages');
    const sendBtn = document.getElementById('ai-widget-send');
    const time = timeStr();

    // Add user message
    container.innerHTML += `<div class="ai-msg user">${escapeHtml(msg)}<div class="ai-msg-time">${time}</div></div>`;
    input.value = '';
    sendBtn.disabled = true;

    // Save to history
    const history = getHistory();
    history.push({ role: 'user', text: msg, time });

    // Typing indicator
    container.innerHTML += `<div class="ai-typing" id="ai-widget-typing"><span></span><span></span><span></span></div>`;
    container.scrollTop = container.scrollHeight;

    try {
      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mensagem: msg })
      });
      const data = await res.json();

      // Remove typing
      document.getElementById('ai-widget-typing')?.remove();

      const reply = data.resposta || data.detail || 'Sem resposta disponível. Verifique a configuração do provider de IA.';
      const replyTime = timeStr();
      container.innerHTML += `<div class="ai-msg ai md-content">${renderMd(reply)}<div class="ai-msg-time">${replyTime}</div></div>`;

      history.push({ role: 'ai', text: reply, time: replyTime });
    } catch (e) {
      document.getElementById('ai-widget-typing')?.remove();
      const errTime = timeStr();
      container.innerHTML += `<div class="ai-msg ai" style="border-left:3px solid var(--red);">Erro de conexão: ${escapeHtml(e.message)}<div class="ai-msg-time">${errTime}</div></div>`;
      history.push({ role: 'ai', text: `Erro: ${e.message}`, time: errTime });
    }

    saveHistory(history);
    sendBtn.disabled = false;
    container.scrollTop = container.scrollHeight;
    input.focus();
  }

  // Inject when DOM is ready
  if (document.body) inject();
  else document.addEventListener('DOMContentLoaded', inject);
})();
