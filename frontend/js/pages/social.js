// social.js - Extracted from social.html inline scripts
import { showToast } from '../modules/toast.js';
import { confirmModal } from '../modules/utils.js';
import { renderMarkdown } from '../modules/markdown.js';
window.showToast = showToast;

// ===== PRESENÇA SOCIAL (amigos ativos) =====
import { startPresence, renderFriendsPresence, getPresenceResumo } from '../modules/presence.js';

async function _loadPresenceWidget() {
  await renderFriendsPresence('friends-presence');
  const resumo = await getPresenceResumo();
  const el = document.getElementById('presence-resumo');
  if (el && resumo && resumo.mensagem) el.textContent = resumo.mensagem;
}

// Iniciar heartbeat + widget ao carregar a página social
if (localStorage.getItem('auth_token')) {
  startPresence();
  _loadPresenceWidget();
  // Não faz polling quando a aba está em segundo plano (economia de rede/bateria).
  setInterval(() => { if (!document.hidden) _loadPresenceWidget(); }, 60 * 1000);
}

// ===== TAB SWITCHING =====
function switchTab(tab, ev) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => {
    el.classList.remove('active');
    el.setAttribute('aria-selected', 'false');
  });
  const content = document.getElementById('tab-' + tab);
  if (content) content.classList.add('active');
  // Ativa o botão correspondente pelo data-tab (funciona tanto no clique quanto
  // em chamadas programáticas, ex.: restaurar aba salva). Antes dependia de
  // event.target global, que quebrava fora de um handler de clique e só existia
  // no Chromium.
  const btn = (ev && ev.currentTarget)
    || document.querySelector(`.tab-btn[data-tab="${tab}"]`);
  if (btn) {
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
  }
}
window.switchTab = switchTab;

// ===== LEAGUE =====
const tierIcons = { bronze: '🥉', prata: '🥈', ouro: '🥇', diamante: '💎' };
const tierNames = { bronze: 'Bronze', prata: 'Prata', ouro: 'Ouro', diamante: 'Diamante' };

async function loadLeague() {
  try {
    const res = await fetch('/api/liga');
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Erro');

    const tier = data.liga_atual || 'bronze';
    const badge = document.getElementById('tier-badge');
    badge.className = 'tier-badge ' + tier;
    badge.textContent = (tierIcons[tier] || '🏆') + ' ' + (tierNames[tier] || tier);

    // Week info
    const weekInfo = document.getElementById('liga-semana-info');
    if (data.semana_inicio && data.semana_fim) {
      const start = new Date(data.semana_inicio + 'T00:00:00').toLocaleDateString('pt-BR', {day:'2-digit',month:'short'});
      const end = new Date(data.semana_fim + 'T00:00:00').toLocaleDateString('pt-BR', {day:'2-digit',month:'short'});
      weekInfo.textContent = `${start} — ${end}`;
    }

    // Days remaining
    const diasEl = document.getElementById('dias-restantes');
    if (data.dias_restantes !== undefined) {
      diasEl.textContent = data.dias_restantes === 0 ? '⏰ Último dia!' :
                           data.dias_restantes === 1 ? '⏰ 1 dia restante' :
                           `⏰ ${data.dias_restantes} dias restantes`;
    }

    // Progress bar for promotion
    const promoContainer = document.getElementById('promo-progress-container');
    const posLabel = document.getElementById('user-pos-label');
    const promoLabel = document.getElementById('xp-para-promo-label');
    const promoBar = document.getElementById('promo-progress-bar');

    promoContainer.style.display = 'block';
    posLabel.textContent = `#${data.posicao || '—'}`;

    if (data.xp_para_promocao > 0) {
      promoLabel.textContent = `${data.xp_para_promocao} XP para promoção`;
      promoLabel.style.color = 'var(--green)';
      // Calculate progress as percentage towards promotion zone
      const totalNeeded = data.xp_semana + data.xp_para_promocao;
      const pct = totalNeeded > 0 ? Math.min(100, (data.xp_semana / totalNeeded) * 100) : 0;
      promoBar.style.width = pct + '%';
    } else if (data.posicao <= data.zona_promocao) {
      promoLabel.textContent = '🎉 Zona de promoção!';
      promoLabel.style.color = 'var(--green)';
      promoBar.style.width = '100%';
      promoBar.style.background = 'linear-gradient(90deg, var(--green), var(--teal, #94e2d5))';
    } else {
      promoLabel.textContent = `${data.xp_semana} XP esta semana`;
      promoLabel.style.color = 'var(--text-sub)';
      promoBar.style.width = '60%';
    }

    // XP Breakdown
    const breakdownContainer = document.getElementById('xp-breakdown');
    const breakdownItems = document.getElementById('xp-breakdown-items');
    if (data.xp_breakdown) {
      const bd = data.xp_breakdown;
      const totalXP = Object.values(bd).reduce((a,b) => a+b, 0);
      if (totalXP > 0) {
        breakdownContainer.style.display = 'block';
        const sources = [
          { label: '📝 Questões', value: bd.questoes || 0, color: 'var(--blue)' },
          { label: '📖 Estudo', value: bd.horas_estudo || 0, color: 'var(--green)' },
          { label: '🃏 Flashcards', value: bd.flashcards || 0, color: 'var(--mauve, #cba6f7)' },
          { label: '🎯 Desafios', value: bd.desafios || 0, color: 'var(--yellow)' },
          { label: '⚔️ Batalhas', value: bd.batalhas || 0, color: 'var(--red)' },
          { label: '🐉 Boss Battle', value: bd.boss_battles || 0, color: 'var(--mauve, #cba6f7)' },
          { label: '🔥 Streak', value: bd.streak || 0, color: 'var(--peach, #fab387)' },
        ].filter(s => s.value > 0);

        breakdownItems.innerHTML = sources.map(s => `
          <div style="display:flex;align-items:center;gap:6px;font-size:0.78rem;">
            <span>${s.label}</span>
            <span style="color:${s.color};font-weight:600;">${s.value} XP</span>
          </div>
        `).join('');
      } else {
        breakdownContainer.style.display = 'none';
      }
    }

    // Leaderboard
    const tbody = document.getElementById('leaderboard-body');
    const ranking = data.ranking || [];
    const total = ranking.length;
    const zonaPromo = data.zona_promocao || 3;
    const zonaDemo = data.zona_rebaixamento || 3;

    if (!ranking.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-state" style="padding:24px;"><div class="emoji">🏆</div><p>Liga será calculada no fim da semana</p></td></tr>';
      return;
    }

    tbody.innerHTML = ranking.map((s) => {
      const pos = s.posicao;
      let cls = '';
      if (s.is_current_user) cls = 'me';
      else if (pos <= zonaPromo) cls = 'promo';
      else if (pos > total - zonaDemo) cls = 'demo';

      let zone = '';
      if (pos <= zonaPromo) zone = '<span class="zone-label zone-promo">↑</span>';
      else if (pos > total - zonaDemo) zone = '<span class="zone-label zone-demo">↓</span>';

      const nameDisplay = s.is_current_user ? `<strong>${escapeHtml(s.nome)}</strong> <span style="font-size:0.72rem;color:var(--blue);">(você)</span>` : escapeHtml(s.nome);

      return `<tr class="${cls}">
        <td class="pos">${pos}</td>
        <td>${nameDisplay}</td>
        <td class="xp">${(s.xp_semana || 0).toLocaleString()} XP</td>
        <td>${zone}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    document.getElementById('leaderboard-body').innerHTML =
      `<tr><td colspan="4" style="text-align:center;padding:24px;color:var(--red);">${e.message}</td></tr>`;
  }
}

async function loadLeagueHistory() {
  try {
    const res = await fetch('/api/liga/historico');
    const data = await res.json();
    const items = data.historico || [];
    const container = document.getElementById('league-history');

    if (!items.length) {
      container.innerHTML = '<div class="empty-state" style="padding:20px;"><div class="emoji">📜</div><p>Nenhum histórico ainda</p><p class="hint">Complete uma semana para ver seu progresso</p></div>';
      return;
    }

    container.innerHTML = items.slice(0, 8).map(h => {
      const icon = tierIcons[h.liga] || '🏆';
      const label = tierNames[h.liga] || h.liga;
      const resultColor = h.resultado === 'promoted' ? 'var(--green)' :
                          h.resultado === 'demoted' ? 'var(--red)' : 'var(--text-sub)';
      const resultText = h.resultado === 'promoted' ? '↑ Promovido' :
                         h.resultado === 'demoted' ? '↓ Rebaixado' : '— Manteve';
      return `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border);font-size:0.85rem;">
          <div>
            <span>${icon} ${label}</span>
            <span style="color:var(--text-sub);margin-left:8px;">#${h.posicao_final} · ${(h.xp_final || 0).toLocaleString()} XP</span>
          </div>
          <span style="color:${resultColor};font-weight:600;font-size:0.8rem;">${resultText}</span>
        </div>
      `;
    }).join('');
  } catch (e) {
    document.getElementById('league-history').innerHTML = '<p style="color:var(--red);font-size:0.85rem;">Erro ao carregar histórico</p>';
  }
}

// ===== AI TUTOR =====
const providerInfo = {
  openai: { name: 'OpenAI', keyPrefix: 'sk-', models: 'gpt-4o-mini, gpt-4o, o1-mini', link: 'https://platform.openai.com/api-keys' },
  claude: { name: 'Anthropic Claude', keyPrefix: 'sk-ant-', models: 'claude-3-5-sonnet, claude-3-5-haiku', link: 'https://console.anthropic.com/settings/keys' },
  gemini: { name: 'Google Gemini', keyPrefix: 'AIza', models: 'gemini-2.0-flash, gemini-1.5-pro', link: 'https://aistudio.google.com/apikey' },
  grok: { name: 'xAI Grok', keyPrefix: 'xai-', models: 'grok-2, grok-2-mini', link: 'https://console.x.ai/' },
  deepseek: { name: 'DeepSeek', keyPrefix: 'sk-', models: 'deepseek-chat, deepseek-reasoner', link: 'https://platform.deepseek.com/api_keys' },
  mistral: { name: 'Mistral AI', keyPrefix: '', models: 'mistral-small-latest, mistral-large-latest', link: 'https://console.mistral.ai/api-keys/' },
  groq: { name: 'Groq', keyPrefix: 'gsk_', models: 'llama-3.1-70b-versatile, mixtral-8x7b-32768', link: 'https://console.groq.com/keys' },
  together: { name: 'Together AI', keyPrefix: '', models: 'Meta-Llama-3.1-70B-Instruct-Turbo', link: 'https://api.together.xyz/settings/api-keys' },
  cohere: { name: 'Cohere', keyPrefix: '', models: 'command-r-plus, command-r', link: 'https://dashboard.cohere.com/api-keys' },
  perplexity: { name: 'Perplexity', keyPrefix: 'pplx-', models: 'sonar-large (com busca web)', link: 'https://www.perplexity.ai/settings/api' },
  kimi: { name: 'Kimi / Moonshot', keyPrefix: 'sk-', models: 'moonshot-v1-8k, moonshot-v1-32k', link: 'https://platform.moonshot.cn/console/api-keys' },
  glm: { name: 'GLM / ZhipuAI', keyPrefix: '', models: 'glm-4-flash, glm-4', link: 'https://open.bigmodel.cn/usercenter/apikeys' },
  bedrock: { name: 'Amazon Bedrock', keyPrefix: '', models: 'claude-3-haiku, titan, llama', link: 'https://console.aws.amazon.com/bedrock/' },
  ollama: { name: 'Ollama (Local)', keyPrefix: '', models: 'llama3.1, mistral, phi3', link: 'https://ollama.com/download' },
};

async function checkAIStatus() {
  try {
    const res = await fetch('/api/ai/status');
    const data = await res.json();
    const el = document.getElementById('ai-status');
    if (data.disponivel) {
      el.innerHTML = `<span class="status-dot online"></span><span>${data.provider_label || data.provider} — ${data.modelo}</span>`;
    } else {
      el.innerHTML = `<span class="status-dot offline"></span><span>Offline — <a href="#" onclick="openAIConfig();return false;" style="color:#89b4fa;">Configurar provider</a></span>`;
    }
  } catch {
    document.getElementById('ai-status').innerHTML = '<span class="status-dot offline"></span><span>Erro de conexão</span>';
  }
}

function openAIConfig() {
  // Load current config
  fetch('/api/ai/config').then(r => r.json()).then(config => {
    document.getElementById('ai-config-provider').value = config.provider || 'auto';
    document.getElementById('ai-config-key').value = '';
    document.getElementById('ai-config-key').placeholder = config.has_key ? `Chave atual: ${config.api_key_masked} (deixe vazio para manter)` : 'Cole sua API key aqui...';
    document.getElementById('ai-config-model').value = config.model_override || '';
    onProviderChange();
  }).catch(() => {
    onProviderChange();
  });
  document.getElementById('modal-ai-config').classList.add('open');
}
window.openAIConfig = openAIConfig;

function onProviderChange() {
  const provider = document.getElementById('ai-config-provider').value;
  const infoEl = document.getElementById('ai-config-info');
  const keyInput = document.getElementById('ai-config-key');

  if (provider === 'auto') {
    infoEl.style.display = 'none';
    keyInput.placeholder = 'Cole a API key do provider que deseja usar...';
    return;
  }

  const info = providerInfo[provider];
  if (info) {
    infoEl.style.display = 'block';
    infoEl.innerHTML = `
      <div style="margin-bottom:6px;"><strong style="color:#cba6f7;">${info.name}</strong></div>
      <div>📋 Modelos: ${info.models}</div>
      <div>🔑 Obter key: <a href="${info.link}" target="_blank" style="color:#89b4fa;">${info.link.replace('https://','').split('/')[0]}</a></div>
      ${provider === 'ollama' ? '<div style="margin-top:4px;">💡 Não precisa de API key — basta rodar <code style="background:#1e1e2e;padding:2px 6px;border-radius:4px;">ollama serve</code></div>' : ''}
      ${provider === 'bedrock' ? '<div style="margin-top:4px;">💡 Usa credenciais AWS IAM — configure via <code>aws configure</code></div>' : ''}
    `;
    keyInput.placeholder = info.keyPrefix ? `${info.keyPrefix}...` : 'API key...';
    if (provider === 'ollama' || provider === 'bedrock') {
      keyInput.placeholder = provider === 'ollama' ? 'http://localhost:11434 (URL do Ollama)' : 'us-east-1 (região AWS)';
    }
  }
}
window.onProviderChange = onProviderChange;

function toggleKeyVisibility() {
  const input = document.getElementById('ai-config-key');
  input.type = input.type === 'password' ? 'text' : 'password';
}
window.toggleKeyVisibility = toggleKeyVisibility;

async function testAIConfig() {
  const statusEl = document.getElementById('ai-config-status');
  statusEl.innerHTML = '<span style="color:#f9e2af;">🔄 Testando conexão...</span>';

  const provider = document.getElementById('ai-config-provider').value;
  const key = document.getElementById('ai-config-key').value;
  const model = document.getElementById('ai-config-model').value;

  try {
    const res = await fetch('/api/ai/config/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: key, model })
    });
    const data = await res.json();
    if (data.ok) {
      statusEl.innerHTML = `<span style="color:#a6e3a1;">✅ Conexão OK! Provider: ${data.provider_label}, Modelo: ${data.model}</span>`;
    } else {
      statusEl.innerHTML = `<span style="color:#f38ba8;">❌ ${data.error || 'Falha na conexão'}</span>`;
    }
  } catch (e) {
    statusEl.innerHTML = `<span style="color:#f38ba8;">❌ Erro: ${e.message}</span>`;
  }
}
window.testAIConfig = testAIConfig;

async function saveAIConfig() {
  const provider = document.getElementById('ai-config-provider').value;
  const key = document.getElementById('ai-config-key').value.trim();
  const model = document.getElementById('ai-config-model').value;

  // Only send api_key if user typed a new one (not empty = keep existing)
  const payload = { provider, model };
  if (key) payload.api_key = key;

  try {
    const res = await fetch('/api/ai/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok) {
      showToast('✅ Provider configurado com sucesso!', 'success');
      closeModal('modal-ai-config');
      checkAIStatus();
    } else {
      showToast(data.error || 'Erro ao salvar', 'error');
    }
  } catch (e) {
    showToast('Erro ao salvar configuração', 'error');
  }
}
window.saveAIConfig = saveAIConfig;

function addTypingIndicator() {
  const messages = document.getElementById('chat-messages');
  const indicator = document.createElement('div');
  indicator.className = 'typing-indicator';
  indicator.id = 'typing-indicator';
  indicator.innerHTML = '<span></span><span></span><span></span>';
  messages.appendChild(indicator);
  messages.scrollTop = messages.scrollHeight;
}

function removeTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');
  if (indicator) indicator.remove();
}

function getTimeStr() {
  return new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;

  const messages = document.getElementById('chat-messages');
  const btn = document.getElementById('chat-send-btn');

  // Add user message
  messages.innerHTML += `<div class="chat-msg user">${escapeHtml(msg)}<div class="msg-time">${getTimeStr()}</div></div>`;
  input.value = '';
  btn.disabled = true;

  // Add typing indicator
  addTypingIndicator();

  try {
    const res = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mensagem: msg })
    });
    const data = await res.json();
    removeTypingIndicator();

    const reply = data.resposta || data.detail || 'Sem resposta';
    messages.innerHTML += `<div class="chat-msg ai md-content">${renderMarkdown(reply)}<div class="msg-time">${getTimeStr()}</div></div>`;
  } catch (e) {
    removeTypingIndicator();
    messages.innerHTML += `<div class="chat-msg ai" style="border-left:3px solid #f38ba8;">Erro: ${e.message}<div class="msg-time">${getTimeStr()}</div></div>`;
  }

  btn.disabled = false;
  messages.scrollTop = messages.scrollHeight;
  input.focus();
}
window.sendChat = sendChat;

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ===== SOCIAL =====
async function loadFriends() {
  try {
    const res = await fetch('/api/social/friends');
    const data = await res.json();
    const friends = data.friends || data || [];
    const container = document.getElementById('friends-list');

    if (!friends.length) {
      container.innerHTML = '<div class="empty-state"><div class="emoji">👋</div><p>Nenhum amigo ainda</p><p class="hint">Convide alguém para estudar junto!</p></div>';
    } else {
      container.innerHTML = friends.map(f => {
        // Usa o status de presença REAL vindo do backend (mesma fonte do widget
        // "Amigos ativos"). Antes caía no fallback fixo 'online', divergindo do
        // widget. `online` é boolean; `status_label` traz o rótulo humano.
        const online = f.online === true;
        const label = online ? (f.status_label || 'Online') : 'Offline';
        const emoji = f.status_emoji || (online ? '🟢' : '💤');
        const dotColor = online ? '#a6e3a1' : '#6c7086';
        return `
        <div class="friend-item" style="opacity:${online ? '1' : '0.6'};">
          <div class="avatar" style="position:relative;">${escapeHtml(f.avatar || '👤')}
            <span style="position:absolute;bottom:-2px;right:-2px;width:10px;height:10px;border-radius:50%;background:${dotColor};border:2px solid var(--bg,#1e1e2e);"></span>
          </div>
          <div class="info">
            <div class="name">${escapeHtml(f.nome || f.username || f.email || 'Amigo')}</div>
            <div class="sub">${emoji} ${escapeHtml(label)}${online && f.materia ? ' · ' + escapeHtml(f.materia) : ''}</div>
          </div>
        </div>`;
      }).join('');
    }
  } catch {
    document.getElementById('friends-list').innerHTML = '<div class="empty-state"><div class="emoji">⚠️</div><p>Erro ao carregar amigos</p></div>';
  }

  // Always load pending requests (even if no friends yet)
  loadPendingRequests();
}

let _lastPendingCount = 0;

async function loadPendingRequests() {
  try {
    const res = await fetch('/api/social/friends/pending');
    const data = await res.json();
    const pending = data.pending || [];
    const sent = data.sent || [];

    // Toast notification if new pending requests appeared
    if (pending.length > _lastPendingCount && _lastPendingCount > 0) {
      const diff = pending.length - _lastPendingCount;
      showToast(`🔔 ${diff} novo${diff > 1 ? 's' : ''} convite${diff > 1 ? 's' : ''} de amizade!`);
    }
    _lastPendingCount = pending.length;

    // Render pending section
    const container = document.getElementById('friends-list');
    if (!pending.length && !sent.length) return;

    let html = '';

    // Received pending requests
    if (pending.length) {
      html += `
        <div class="pending-section">
          <div class="pending-title">📬 Convites recebidos (${pending.length})</div>
          ${pending.map(p => `
            <div class="pending-item">
              <div class="avatar">👤</div>
              <div class="info">
                <div class="name">${escapeHtml(p.nome || p.username || p.email)}</div>
                <div class="sub">Quer ser seu amigo</div>
              </div>
              <div class="pending-actions">
                <button class="pending-btn pending-btn--accept" onclick="acceptFriend(${p.friendship_id})">✓ Aceitar</button>
                <button class="pending-btn pending-btn--reject" onclick="rejectFriend(${p.friendship_id})" aria-label="Rejeitar solicitação de amizade">✗</button>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }

    // Sent pending requests (awaiting response)
    if (sent.length) {
      html += `
        <div class="pending-section" style="border-color: rgba(137, 180, 250, 0.2); background: rgba(137, 180, 250, 0.05);">
          <div class="pending-title" style="color: var(--blue, #89b4fa);">📤 Convites enviados (${sent.length})</div>
          ${sent.map(s => `
            <div class="pending-item">
              <div class="avatar">👤</div>
              <div class="info">
                <div class="name">${escapeHtml(s.nome || s.username || s.email)}</div>
                <div class="sub">Aguardando resposta...</div>
              </div>
              <span style="font-size:0.75rem;color:var(--text-sub);">⏳</span>
            </div>
          `).join('')}
        </div>
      `;
    }

    // Insert pending section before friends list content
    container.insertAdjacentHTML('afterbegin', html);
  } catch (e) {
    // Silently fail — pending requests are non-critical
  }
}

window.acceptFriend = async function(friendshipId) {
  try {
    await fetch(`/api/social/friends/${friendshipId}/accept`, { method: 'POST' });
    showToast('✅ Amizade aceita!');
    loadFriends();
  } catch (e) {
    showToast('Erro ao aceitar convite', 'error');
  }
};

window.rejectFriend = async function(friendshipId) {
  try {
    await fetch(`/api/social/friends/${friendshipId}/reject`, { method: 'POST' });
    showToast('Convite recusado');
    loadFriends();
  } catch (e) {
    showToast('Erro ao recusar convite', 'error');
  }
};

async function loadGroups() {
  try {
    const res = await fetch('/api/social/groups');
    const data = await res.json();
    const groups = data.groups || data || [];
    const container = document.getElementById('groups-list');

    if (!groups.length) {
      container.innerHTML = '<div class="empty-state"><div class="emoji">📖</div><p>Nenhum grupo ainda</p><p class="hint">Crie um grupo e convide seus colegas!</p></div>';
      return;
    }

    container.innerHTML = groups.map(g => `
      <div class="group-item" onclick="openGroupDetail(${g.id || g.group_id})" style="cursor:pointer;" title="Clique para ver membros">
        <div class="avatar">📚</div>
        <div class="info">
          <div class="name">${escapeHtml(g.nome || g.name)}</div>
          <div class="sub">${g.membros || g.member_count || 0} membros · ${g.edital_nome || 'Geral'}</div>
        </div>
        <span style="font-size:0.75rem;color:#9399b2;">👥</span>
      </div>
    `).join('');
  } catch {
    document.getElementById('groups-list').innerHTML = '<div class="empty-state"><div class="emoji">⚠️</div><p>Erro ao carregar grupos</p></div>';
  }
}

async function loadFeed() {
  try {
    const res = await fetch('/api/social/feed');
    const data = await res.json();
    const items = data.feed || data || [];
    const container = document.getElementById('activity-feed');

    if (!items.length) {
      container.innerHTML = '<div class="empty-state"><div class="emoji">📭</div><p>Nenhuma atividade</p><p class="hint">Atividades dos seus amigos aparecerão aqui</p></div>';
      return;
    }

    container.innerHTML = items.slice(0, 20).map(item => `
      <div class="feed-item">
        <div class="feed-time">${item.created_at || ''}</div>
        <div class="feed-text">${escapeHtml(item.descricao || item.description || '')}</div>
      </div>
    `).join('');
  } catch {
    document.getElementById('activity-feed').innerHTML = '<div class="empty-state"><div class="emoji">⚠️</div><p>Erro ao carregar atividade</p></div>';
  }
}

// Modals
function openAddFriend() { document.getElementById('modal-add-friend').classList.add('open'); }
window.openAddFriend = openAddFriend;

function doLogout() {
  localStorage.removeItem('auth_token');
  localStorage.removeItem('auth_user');
  document.getElementById('profile-modal')?.remove();
  window.location.href = '/login.html';
}
window.doLogout = doLogout;

function openCreateGroup() { document.getElementById('modal-create-group').classList.add('open'); }
window.openCreateGroup = openCreateGroup;

function closeModal(id) { document.getElementById(id).classList.remove('open'); }
window.closeModal = closeModal;

// Group Detail & Member Management
let _currentGroupId = null;

async function openGroupDetail(groupId) {
  _currentGroupId = groupId;
  document.getElementById('modal-group-detail').classList.add('open');
  const container = document.getElementById('group-detail-members');
  container.innerHTML = '<div style="text-align:center;color:#9399b2;padding:20px;">Carregando...</div>';

  try {
    const res = await fetch(`/api/social/groups/${groupId}/members`);
    const data = await res.json();
    document.getElementById('group-detail-title').textContent = `📚 ${data.group_name}`;

    if (!data.members.length) {
      container.innerHTML = '<div style="text-align:center;color:#9399b2;padding:20px;">Nenhum membro</div>';
      return;
    }

    const roleIcons = {creator: '👑', admin: '⭐', member: '👤'};
    const roleLabels = {creator: 'Criador', admin: 'Admin', member: 'Membro'};

    container.innerHTML = `
      <div style="font-size:0.75rem;color:#9399b2;margin-bottom:8px;">${data.total}/${data.max_membros} membros</div>
      ${data.members.map(m => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;background:#1e1e2e;border-radius:8px;margin-bottom:6px;">
          <div style="width:36px;height:36px;border-radius:50%;background:#45475a;display:flex;align-items:center;justify-content:center;font-size:1rem;">
            ${m.avatar ? `<img src="${m.avatar}" alt="Avatar de ${escapeHtml(m.nome)}" style="width:36px;height:36px;border-radius:50%;">` : roleIcons[m.role]}
          </div>
          <div style="flex:1;">
            <div style="font-size:0.85rem;font-weight:600;color:#cdd6f4;">${escapeHtml(m.nome)}</div>
            <div style="font-size:0.72rem;color:#9399b2;">${m.username ? '@' + m.username + ' · ' : ''}${roleLabels[m.role]} · desde ${m.joined_at || '—'}</div>
          </div>
          ${m.role !== 'creator' ? `
            <div style="display:flex;gap:4px;">
              <button onclick="promoteMember(${m.user_id}, '${m.role === 'admin' ? 'member' : 'admin'}')" 
                style="background:none;border:1px solid #45475a;border-radius:4px;padding:3px 6px;font-size:0.68rem;color:#f9e2af;cursor:pointer;"
                title="${m.role === 'admin' ? 'Rebaixar para membro' : 'Promover a admin'}">
                ${m.role === 'admin' ? '↓' : '↑'}
              </button>
              <button onclick="removeMember(${m.user_id}, '${escapeHtml(m.nome)}')" 
                style="background:none;border:1px solid #45475a;border-radius:4px;padding:3px 6px;font-size:0.68rem;color:#f38ba8;cursor:pointer;"
                title="Remover do grupo" aria-label="Remover membro do grupo">✕</button>
            </div>
          ` : ''}
        </div>
      `).join('')}
    `;
  } catch(e) {
    container.innerHTML = '<div style="text-align:center;color:#f38ba8;padding:20px;">Erro ao carregar membros</div>';
  }
}
window.openGroupDetail = openGroupDetail;

function openAddMember() {
  document.getElementById('modal-add-member').classList.add('open');
  document.getElementById('add-member-input').value = '';
  document.getElementById('add-member-feedback').textContent = '';
  document.getElementById('add-member-input').focus();
}
window.openAddMember = openAddMember;

async function addMemberToGroup() {
  const input = document.getElementById('add-member-input').value.trim();
  const feedback = document.getElementById('add-member-feedback');
  if (!input) { feedback.textContent = '⚠️ Informe email ou username.'; feedback.style.color = '#f9e2af'; return; }

  const body = input.includes('@') ? {email: input} : {username: input};
  feedback.textContent = 'Adicionando...';
  feedback.style.color = '#9399b2';

  try {
    const res = await fetch(`/api/social/groups/${_currentGroupId}/add-member`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    const data = await res.json();
    if (res.ok) {
      feedback.textContent = `✅ ${data.nome || 'Membro'} adicionado com sucesso!`;
      feedback.style.color = '#a6e3a1';
      document.getElementById('add-member-input').value = '';
      // Refresh member list
      setTimeout(() => openGroupDetail(_currentGroupId), 1000);
      loadGroups();
    } else {
      feedback.textContent = `❌ ${data.detail || 'Erro ao adicionar.'}`;
      feedback.style.color = '#f38ba8';
    }
  } catch(e) {
    feedback.textContent = '❌ Erro de conexão.';
    feedback.style.color = '#f38ba8';
  }
}
window.addMemberToGroup = addMemberToGroup;

async function promoteMember(userId, newRole) {
  try {
    const res = await fetch(`/api/social/groups/${_currentGroupId}/members/${userId}/role`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({role: newRole})
    });
    if (res.ok) {
      openGroupDetail(_currentGroupId);
    } else {
      const data = await res.json();
      showToast(data.detail || 'Erro ao alterar role.', 'error');
    }
  } catch(e) { showToast('Erro de conexão.', 'error'); }
}
window.promoteMember = promoteMember;

async function removeMember(userId, nome) {
  if (!await confirmModal('Remover Membro', `Remover ${nome} do grupo?`, { type: 'danger', confirmText: 'Remover' })) return;
  try {
    const res = await fetch(`/api/social/groups/${_currentGroupId}/members/${userId}`, {method: 'DELETE'});
    if (res.ok) {
      openGroupDetail(_currentGroupId);
      loadGroups();
    } else {
      const data = await res.json();
      showToast(data.detail || 'Erro ao remover.', 'error');
    }
  } catch(e) { showToast('Erro de conexão.', 'error'); }
}
window.removeMember = removeMember;

// Close modal on Escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach(m => m.classList.remove('open'));
  }
});

async function addFriend() {
  const email = document.getElementById('friend-email').value.trim();
  if (!email) return;
  try {
    await fetch('/api/social/friends/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });
    closeModal('modal-add-friend');
    document.getElementById('friend-email').value = '';
    showToast('✉️ Convite enviado!');
    loadFriends();
  } catch (e) {
    showToast('Erro: ' + e.message, 'error');
  }
}
window.addFriend = addFriend;

async function createGroup() {
  const nome = document.getElementById('group-name').value.trim();
  if (!nome) return;
  const descricao = document.getElementById('group-desc').value.trim();
  const edital_nome = document.getElementById('group-edital').value.trim();
  try {
    await fetch('/api/social/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome, descricao, edital_nome })
    });
    closeModal('modal-create-group');
    document.getElementById('group-name').value = '';
    document.getElementById('group-desc').value = '';
    document.getElementById('group-edital').value = '';
    showToast('📚 Grupo criado!');
    loadGroups();
  } catch (e) {
    showToast('Erro: ' + e.message, 'error');
  }
}
window.createGroup = createGroup;

// ===== USER PROFILE =====
async function loadUserProfile() {
  try {
    // Load from /api/social/profile (has streak, xp, level)
    const profile = await fetch('/api/social/profile').then(r => r.json());
    const nome = profile.username || 'Concurseiro';
    const initials = nome.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();

    document.getElementById('user-avatar').textContent = initials || '👤';
    document.getElementById('user-name').textContent = nome;
    document.getElementById('user-stats-mini').textContent = `🔥 ${profile.streak || 0}d · ⭐ Nível ${profile.level || 1}`;

    // Plan badge
    const planBadge = document.getElementById('user-plan-badge');
    const planLabels = { ilimitado: '👑 Ilimitado', premium: '⭐ Premium', free: '🆓 Free' };
    const planColors = { ilimitado: '#f9e2af', premium: '#cba6f7', free: '#9399b2' };

    // Get plan from auth/me (graceful on 401)
    let plano = 'ilimitado';
    try {
      const meRes = await fetch('/api/auth/me');
      if (meRes.ok) {
        const me = await meRes.json();
        if (me.plano && me.plano !== 'free') plano = me.plano;
      }
    } catch { }

    planBadge.textContent = planLabels[plano] || '⭐ ' + plano;
    planBadge.style.background = (planColors[plano] || '#9399b2') + '22';
    planBadge.style.color = planColors[plano] || '#9399b2';
    planBadge.style.border = `1px solid ${planColors[plano] || '#9399b2'}44`;
  } catch (e) {
    document.getElementById('user-avatar').textContent = '👤';
    document.getElementById('user-name').textContent = 'Estudante';
  }
}

// Perfil do usuário: o avatar da top bar usa o menu ÚNICO showProfileMenu()
// (auth.js), acionado por handleAuthNav() — o mesmo do "Meu Dia". A antiga
// showProfileModal() foi removida para não haver duas UIs de perfil divergentes.

// Restore tab from sidebar navigation (if redirected)
const savedTab = localStorage.getItem('concurseiro_social_tab');
if (savedTab) {
  localStorage.removeItem('concurseiro_social_tab');
  switchTab(savedTab);
}

// ===== INIT =====
loadUserProfile();
loadLeague();
loadLeagueHistory();
checkAIStatus();
loadFriends();
loadGroups();
loadFeed();

// ============================================================
// CHAT DIRETO
// ============================================================

let _chatFriendId = null;
let _chatPollInterval = null;
let _lastMsgId = 0;

async function loadChatConversations() {
  try {
    const res = await fetch('/api/social/chat/conversations');
    const data = await res.json();
    const conversations = data.conversations || [];
    const totalUnread = data.total_unread || 0;

    // Update badge
    const badge = document.getElementById('chat-badge');
    if (badge) {
      if (totalUnread > 0) {
        badge.textContent = totalUnread;
        badge.style.display = 'inline';
      } else {
        badge.style.display = 'none';
      }
    }

    const container = document.getElementById('chat-conversations');

    if (!conversations.length) {
      container.innerHTML = '<div class="empty-state"><div class="emoji">💬</div><p>Nenhuma conversa ainda</p><p class="hint">Adicione amigos para começar a conversar!</p></div>';
      return;
    }

    container.innerHTML = conversations.map(c => {
      const preview = c.ultima_mensagem
        ? (c.ultima_mensagem_minha ? 'Você: ' : '') + c.ultima_mensagem
        : 'Iniciar conversa...';
      const time = c.created_at ? new Date(c.created_at).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'}) : '';
      return `
        <div class="chat-conv-item" onclick="openChat(${c.friend_id}, '${escapeHtml(c.nome)}')">
          <div class="avatar">👤</div>
          <div class="conv-info">
            <div class="conv-name">${escapeHtml(c.nome)}</div>
            <div class="conv-preview">${escapeHtml(preview)}</div>
          </div>
          ${c.nao_lidas > 0 ? `<span class="conv-badge">${c.nao_lidas}</span>` : `<span class="conv-time">${time}</span>`}
        </div>
      `;
    }).join('');
  } catch(e) {
    document.getElementById('chat-conversations').innerHTML = '<div class="empty-state"><div class="emoji">⚠️</div><p>Erro ao carregar conversas</p></div>';
  }
}

window.openChat = async function(friendId, nome) {
  _chatFriendId = friendId;
  _lastMsgId = 0;

  document.getElementById('chat-conversations').style.display = 'none';
  document.getElementById('chat-window').style.display = 'flex';
  document.getElementById('chat-friend-name').textContent = nome;
  document.getElementById('dm-messages').innerHTML = '';
  document.getElementById('dm-input').value = '';
  document.getElementById('dm-input').focus();

  await loadMessages();
  startChatPolling();
};

window.closeChatWindow = function() {
  stopChatPolling();
  _chatFriendId = null;
  document.getElementById('chat-window').style.display = 'none';
  document.getElementById('chat-conversations').style.display = 'block';
  loadChatConversations(); // Refresh unread counts
};
window.loadChatConversations = loadChatConversations;

async function loadMessages() {
  if (!_chatFriendId) return;
  try {
    const res = await fetch(`/api/social/chat/${_chatFriendId}?limit=50`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      console.error('loadMessages error:', err);
      return;
    }
    const data = await res.json();
    const messages = data.messages || [];

    const container = document.getElementById('dm-messages');
    container.innerHTML = messages.map(m => {
      const time = new Date(m.created_at).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'});
      const content = m.tipo === 'audio' && m.audio_url
        ? `<audio controls preload="none" src="${m.audio_url}"></audio>`
        : escapeHtml(m.mensagem);
      return `
        <div class="chat-msg ${m.is_mine ? 'chat-msg--mine' : 'chat-msg--theirs'}">
          <div>${content}</div>
          <div class="chat-msg__time">${time}</div>
        </div>
      `;
    }).join('');

    // Scroll to bottom
    container.scrollTop = container.scrollHeight;

    // Track last message id for polling
    if (messages.length) {
      _lastMsgId = messages[messages.length - 1].id;
    }
  } catch(e) {
    // Silent fail
  }
}

window.sendChatMessage = async function() {
  const input = document.getElementById('dm-input');
  const msg = input.value.trim();
  if (!msg || !_chatFriendId) return;

  input.value = '';
  input.disabled = true;

  try {
    const res = await fetch('/api/social/chat/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ receiver_id: parseInt(_chatFriendId), mensagem: msg })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Erro ${res.status}`);
    }
    await loadMessages();
  } catch(e) {
    showToast('Erro: ' + e.message, 'error');
    input.value = msg; // Restore message
  }

  input.disabled = false;
  input.focus();
};

// ===== AUDIO RECORDING =====
let _mediaRecorder = null;
let _audioChunks = [];
let _isRecording = false;

window.toggleAudioRecording = async function() {
  if (_isRecording) {
    stopRecording();
  } else {
    await startRecording();
  }
};

async function startRecording() {
  // Verificar se mediaDevices está disponível (requer HTTPS ou localhost)
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showToast('Gravação requer HTTPS ou localhost. Acesse via localhost:8000', 'error');
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    // Verificar mimeType suportado
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : 'audio/ogg';

    _mediaRecorder = new MediaRecorder(stream, { mimeType });
    _audioChunks = [];

    _mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) _audioChunks.push(e.data);
    };

    _mediaRecorder.onstop = async () => {
      // Parar tracks do microfone
      stream.getTracks().forEach(t => t.stop());

      const blob = new Blob(_audioChunks, { type: 'audio/webm' });
      if (blob.size < 1000) {
        showToast('Áudio muito curto, tente novamente', 'error');
        return;
      }
      await sendAudioMessage(blob);
    };

    _mediaRecorder.start();
    _isRecording = true;

    const btn = document.getElementById('dm-record-btn');
    btn.classList.add('recording');
    btn.textContent = '⏹';
    btn.title = 'Parar gravação';
  } catch(e) {
    if (e.name === 'NotAllowedError') {
      showToast('Permissão do microfone negada. Permita nas configurações do browser.', 'error');
    } else if (e.name === 'NotFoundError') {
      showToast('Nenhum microfone encontrado no dispositivo.', 'error');
    } else {
      showToast('Não foi possível acessar o microfone. Use localhost ou HTTPS.', 'error');
    }
  }
}

function stopRecording() {
  if (_mediaRecorder && _mediaRecorder.state !== 'inactive') {
    _mediaRecorder.stop();
  }
  _isRecording = false;

  const btn = document.getElementById('dm-record-btn');
  btn.classList.remove('recording');
  btn.textContent = '🎤';
  btn.title = 'Gravar áudio';
}

async function sendAudioMessage(blob) {
  if (!_chatFriendId) return;

  const formData = new FormData();
  formData.append('receiver_id', _chatFriendId);
  formData.append('audio', blob, 'audio.webm');

  try {
    const res = await fetch('/api/social/chat/send-audio', {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Erro ao enviar áudio');
    }
    await loadMessages();
  } catch(e) {
    showToast('Erro: ' + e.message, 'error');
  }
}

function startChatPolling() {
  stopChatPolling();
  _chatPollInterval = setInterval(async () => {
    if (_chatFriendId) await loadMessages();
  }, 3000); // Poll every 3s
}

function stopChatPolling() {
  if (_chatPollInterval) {
    clearInterval(_chatPollInterval);
    _chatPollInterval = null;
  }
}

// Poll for unread messages badge (every 30s)
let _unreadPollInterval = setInterval(async () => {
  if (document.hidden) return; // pausa polling em segundo plano
  try {
    const res = await fetch('/api/social/chat/unread/count');
    const data = await res.json();
    const badge = document.getElementById('chat-badge');
    if (badge) {
      if (data.unread > 0) {
        badge.textContent = data.unread;
        badge.style.display = 'inline';
      } else {
        badge.style.display = 'none';
      }
    }
  } catch(e) {}
}, 30000);

// Load chat when tab is switched to chat
const _origSwitchTab = window.switchTab;
if (typeof _origSwitchTab === 'function') {
  window.switchTab = function(tab) {
    _origSwitchTab(tab);
    if (tab === 'chat') loadChatConversations();
  };
} else {
  // switchTab not yet defined — patch later
  document.addEventListener('DOMContentLoaded', () => {
    const orig = window.switchTab;
    if (orig) {
      window.switchTab = function(tab) {
        orig(tab);
        if (tab === 'chat') loadChatConversations();
      };
    }
  });
}

// Initial load of chat badge
(async () => {
  try {
    const res = await fetch('/api/social/chat/unread/count');
    const data = await res.json();
    const badge = document.getElementById('chat-badge');
    if (badge && data.unread > 0) {
      badge.textContent = data.unread;
      badge.style.display = 'inline';
    }
  } catch(e) {}
})();
