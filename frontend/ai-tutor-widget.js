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
  const fab = document.createElement('button');
  fab.id = 'ai-tutor-fab';
  fab.innerHTML = '🤖';
  fab.title = 'AI Tutor — Tire dúvidas a qualquer momento';
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
    fab.addEventListener('click', toggleAITutor);

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

  window.toggleAITutor = function() {
    const isOpen = panel.classList.toggle('show');
    fab.classList.toggle('open', isOpen);
    fab.innerHTML = isOpen ? '✕' : '🤖';
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
      `<div class="ai-msg ${m.role}">${escapeHtml(m.text)}<div class="ai-msg-time">${m.time || ''}</div></div>`
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
      container.innerHTML += `<div class="ai-msg ai">${escapeHtml(reply)}<div class="ai-msg-time">${replyTime}</div></div>`;

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
