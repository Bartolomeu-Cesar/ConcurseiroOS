// batalha.js — ES module extracted from batalha.html

import { confirmModal, alertModal, promptModal } from '../modules/utils.js';
import { toast } from '../modules/toast.js';

const view = document.getElementById('battle-view');
let state = { screen: 'menu', battle: null, timer: null, timeLeft: 0, selectedAnswer: null };

// ========== SCREENS ==========

function showMenu() {
  state.screen = 'menu';
  view.innerHTML = `
    <h1 style="text-align:center;font-size:1.6rem;margin-bottom:24px;">⚔️ Batalha de Questões</h1>

    <div class="lobby-card">
      <h2>🎮 Criar Nova Batalha</h2>
      <div class="config-row"><label>Título:</label><input id="cfg-titulo" value="Batalha de Questões" placeholder="Nome da sala" aria-label="Título da sala"></div>
      <div class="config-row"><label>Matérias:</label>
        <div id="materias-autocomplete" style="flex:1;position:relative;">
          <div id="materias-tags" style="display:flex;flex-wrap:wrap;gap:4px;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;min-height:38px;align-items:center;cursor:text;" onclick="document.getElementById('cfg-materias').focus()">
            <input id="cfg-materias" placeholder="Digite para buscar... (vazio = todas)" aria-label="Buscar matérias" style="border:none;background:transparent;color:var(--text);font-size:0.85rem;outline:none;flex:1;min-width:120px;padding:2px 0;" autocomplete="off">
          </div>
          <div id="materias-dropdown" style="display:none;position:absolute;top:100%;left:0;right:0;background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;margin-top:4px;max-height:180px;overflow-y:auto;z-index:100;box-shadow:0 4px 12px rgba(0,0,0,0.4);"></div>
        </div>
      </div>
      <div class="config-row"><label>Rodadas:</label><select id="cfg-rodadas" aria-label="Número de rodadas">${[3,5,7,10,15,20].map(n => `<option value="${n}" ${n===5?'selected':''}>${n} rodadas</option>`).join('')}</select></div>
      <div class="config-row"><label>Tempo/questão:</label><select id="cfg-tempo" aria-label="Tempo por questão">${[15,20,30,45,60].map(n => `<option value="${n}" ${n===30?'selected':''}>${n} segundos</option>`).join('')}</select></div>
      <div class="config-row"><label>Jogadores:</label><select id="cfg-max" aria-label="Número de jogadores">${[2,3,4,5].map(n => `<option value="${n}" ${n===5?'selected':''}>${n} jogadores</option>`).join('')}</select></div>
      <button class="btn-battle" onclick="criarBatalha()">⚔️ Criar Sala</button>
    </div>

    <div class="lobby-card">
      <h2>🚪 Entrar em Sala</h2>
      <input class="input-battle" id="join-code" placeholder="CÓDIGO" aria-label="Código da sala" maxlength="6" style="margin-bottom:12px;" onkeyup="this.value=this.value.toUpperCase()">
      <button class="btn-battle secondary" onclick="entrarBatalha()">Entrar</button>
    </div>

    <div class="lobby-card">
      <h2>📋 Minhas Batalhas</h2>
      <div id="my-battles" style="color:var(--text-sub);font-size:0.85rem;">Carregando...</div>
    </div>
  `;
  loadMyBattles();
}

function showLobby(data) {
  state.screen = 'lobby';
  state.battle = data;
  const isCreator = data.criador_id === 1 || (data.coautores || []).includes(1); // user_id=1 in single-user mode

  view.innerHTML = `
    <h1 style="text-align:center;">🏟️ Sala de Batalha</h1>
    <div class="lobby-card" style="text-align:center;">
      <div style="font-size:0.82rem;color:var(--text-sub);">Compartilhe o código:</div>
      <div class="code-display">${data.codigo}</div>
      <div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:12px;">
        ${data.titulo} · ${data.total_rodadas} rodadas · ${data.tempo_por_questao}s/questão
        ${data.materias.length ? '<br>📚 ' + data.materias.join(', ') : ''}
      </div>
      <div class="players-list" id="lobby-players"></div>
      <div id="lobby-status" style="color:var(--yellow);font-size:0.82rem;margin-top:8px;">⏳ Atualizando automaticamente...</div>
      <div style="margin-top:16px;">
        ${isCreator ? '<button class="btn-battle" onclick="iniciarBatalha()">🚀 Iniciar Batalha</button><button class="btn-battle secondary" style="margin-top:8px;" onclick="reconfigurarBatalha()">🔄 Reconfigurar</button>' : '<div style="color:var(--yellow);font-size:0.85rem;">Aguardando o moderador iniciar...</div>'}
      </div>
    </div>
  `;
  renderPlayers(data.jogadores || []);
  // Start auto-polling lobby
  startLobbyPolling(data.codigo);
}

let _lobbyPollInterval = null;
function startLobbyPolling(codigo) {
  stopLobbyPolling();
  _lobbyPollInterval = setInterval(async () => {
    if (state.screen !== 'lobby') { stopLobbyPolling(); return; }
    try {
      const sala = await fetch(`/api/batalha/sala/${codigo}`).then(r => r.json());
      if (sala.status === 'em_andamento') {
        stopLobbyPolling();
        showBatalhaToast('🚀 Batalha iniciada!', 'success');
        showQuestion(sala);
      } else if (sala.status === 'finalizada') {
        stopLobbyPolling();
        const rk = await fetch(`/api/batalha/ranking/${codigo}`).then(r => r.json());
        showRanking(rk);
      } else {
        // Atualizar lista de jogadores
        renderPlayers(sala.jogadores || []);
        state.battle = sala;
      }
    } catch(e) {}
  }, 3000); // A cada 3 segundos
}

function stopLobbyPolling() {
  if (_lobbyPollInterval) { clearInterval(_lobbyPollInterval); _lobbyPollInterval = null; }
}

function showQuestion(data) {
  state.screen = 'question';
  state.battle = data;
  state.selectedAnswer = null;
  const r = data.rodada;
  if (!r) { refreshBattle(); return; }

  const alts = r.alternativas;
  const letters = ['a','b','c','d','e'].filter(l => alts[l]);
  const diff = r.dificuldade || {};

  view.innerHTML = `
    <div class="question-card">
      <div class="round-badge">Rodada ${data.rodada_atual}/${data.total_rodadas}</div>
      <div class="timer-bar"><div class="timer-fill" id="timer-fill" style="width:100%;"></div></div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <div style="font-size:0.82rem;color:var(--text-sub);" id="timer-text">${data.tempo_por_questao}s</div>
        <div style="font-size:0.72rem;padding:3px 10px;border-radius:12px;background:${diff.cor || '#45475a'}22;color:${diff.cor || '#9399b2'};border:1px solid ${diff.cor || '#45475a'}44;font-weight:600;">${diff.emoji || ''} ${diff.nivel || ''}</div>
      </div>
      <div class="materia-badge">📚 ${r.materia}</div>
      <div class="question-text">${r.enunciado}</div>
      <div class="options">
        ${letters.map(l => `
          <button class="option-btn" data-letter="${l}" onclick="selectAnswer('${l}')">
            <span class="option-letter">${l.toUpperCase()}</span>
            <span>${alts[l]}</span>
          </button>
        `).join('')}
      </div>
      <button class="btn-battle" style="margin-top:16px;opacity:0.5;" id="btn-confirm" onclick="confirmarResposta()" disabled>Confirmar</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;" id="round-players"></div>
  `;

  // Start timer
  startTimer(data.tempo_por_questao);
  renderRoundPlayers(r.responderam || [], data.jogadores);
}

function showRanking(data) {
  state.screen = 'ranking';
  launchConfetti();

  const ranking = data.ranking || [];
  const top3 = ranking.slice(0, 3);

  // Prêmio surpresa FIXO (1v1) — vem do backend, igual para os dois participantes
  // e persistente em toda visita. O papel (paga/recebe) é definido pelo servidor.
  let premioHtml = '';
  const premio = data.premio;
  if (premio && premio.texto) {
    let titulo, detalhe;
    if (premio.meu_papel === 'paga') {
      titulo = `${premio.quem_paga_nome}, você deve entregar a ${premio.quem_recebe_nome}:`;
      detalhe = 'Valide a entrega com o vencedor! 🤝';
    } else if (premio.meu_papel === 'recebe') {
      titulo = `${premio.quem_recebe_nome}, você venceu! ${premio.quem_paga_nome} deve lhe entregar:`;
      detalhe = 'Combine a entrega com quem perdeu! 🤝';
    } else {
      titulo = `${premio.quem_paga_nome} deve entregar a ${premio.quem_recebe_nome}:`;
      detalhe = 'Prêmio da batalha 🤝';
    }
    premioHtml = `
      <div style="background:linear-gradient(135deg, var(--bg), var(--bg-surface));border:2px solid var(--yellow);border-radius:14px;padding:20px;margin:16px 0;text-align:center;">
        <div style="font-size:1.3rem;margin-bottom:8px;">🎁 Prêmio Surpresa!</div>
        <div style="color:var(--yellow);font-size:0.95rem;font-weight:600;margin-bottom:6px;">${titulo}</div>
        <div style="color:var(--text);font-size:1.1rem;padding:12px;background:var(--bg-elevated);border-radius:10px;margin:8px 0;">
          ${premio.emoji} ${premio.texto} para ${premio.quem_recebe_nome}!
        </div>
        <div style="font-size:0.75rem;color:var(--text-sub);margin-top:8px;">${detalhe}</div>
      </div>
    `;
  }

  // Podium order: 2nd, 1st, 3rd
  const podiumOrder = top3.length >= 3 ? [top3[1], top3[0], top3[2]] : top3;
  const podiumClasses = top3.length >= 3 ? ['second', 'first', 'third'] : ['first', 'second', 'third'];

  view.innerHTML = `
    <div class="ranking-card">
      <h1 style="font-size:1.4rem;margin-bottom:4px;">🏆 Resultado Final</h1>
      <div style="font-size:0.82rem;color:var(--text-sub);margin-bottom:8px;">${data.titulo} · ${data.total_rodadas} rodadas</div>

      <div class="podium">
        ${podiumOrder.map((p, i) => p ? `
          <div class="podium-place">
            <div class="podium-bar ${podiumClasses[i]}">
              <div class="podium-emoji">${p.emoji}</div>
              <div class="podium-name">${p.nome}</div>
              <div class="podium-points">${p.pontos} pts</div>
            </div>
          </div>
        ` : '').join('')}
      </div>

      <div class="ranking-list">
        ${ranking.map(r => `
          <div class="rank-row">
            <div class="rank-pos">${r.emoji}</div>
            <div class="rank-info">
              <div class="rank-name">${r.nome}</div>
              <div class="rank-stats">${r.acertos}/${r.acertos + r.erros} acertos (${r.pct_acerto}%) · ⏱ ${r.tempo_medio_seg}s/q</div>
            </div>
            <div class="rank-points">${r.pontos}</div>
          </div>
        `).join('')}
      </div>

      <button class="btn-battle" style="margin-top:20px;" onclick="showMenu()">🔙 Voltar ao Menu</button>
      <button class="btn-battle secondary" style="margin-top:8px;" onclick="criarRevanche('${data.codigo}')">🔄 Revanche</button>
      <button class="btn-battle" style="margin-top:8px;background:var(--bg-elevated);color:var(--text);" onclick="showReview('${data.codigo}')">📖 Revisar Questões</button>
      ${premioHtml}
    </div>
  `;
}

// ========== ACTIONS ==========

window.criarBatalha = async function() {
  const titulo = document.getElementById('cfg-titulo').value.trim() || 'Batalha';
  const materias = [..._selectedMaterias];
  const total_rodadas = parseInt(document.getElementById('cfg-rodadas').value);
  const tempo_por_questao = parseInt(document.getElementById('cfg-tempo').value);
  const max_jogadores = parseInt(document.getElementById('cfg-max').value);

  try {
    const res = await fetch('/api/batalha/criar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ titulo, materias, total_rodadas, tempo_por_questao, max_jogadores })
    });
    const data = await res.json();
    if (res.ok) {
      // Mostrar aviso se poucas/nenhuma questão
      if (data.aviso) {
        showBatalhaToast(data.aviso, data.questoes_disponiveis === 0 ? 'error' : 'warning');
      }
      if (data.questoes_disponiveis === 0) {
        // Abrir modal de sem questões direto
        state.battle = data;
        showNoQuestionsModal(`Sem questões disponíveis para as matérias: ${materias.length ? materias.join(', ') : 'todas'}`);
      } else {
        // Go to lobby normalmente
        const sala = await fetch(`/api/batalha/sala/${data.codigo}`).then(r => r.json());
        showLobby(sala);
      }
    } else {
      showBatalhaToast(data.detail || 'Erro ao criar sala.', 'error');
    }
  } catch(e) { showBatalhaToast('Erro de conexão.', 'error'); }
};

window.entrarBatalha = async function() {
  const codigo = document.getElementById('join-code').value.trim().toUpperCase();
  if (!codigo || codigo.length < 4) { toast('Informe um código válido.', 'warning'); return; }
  try {
    const res = await fetch('/api/batalha/entrar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ codigo })
    });
    const data = await res.json();
    if (res.ok) {
      const sala = await fetch(`/api/batalha/sala/${codigo}`).then(r => r.json());
      if (sala.status === 'em_andamento') showQuestion(sala);
      else if (sala.status === 'finalizada') { const rk = await fetch(`/api/batalha/ranking/${codigo}`).then(r=>r.json()); showRanking(rk); }
      else showLobby(sala);
    } else {
      toast(data.detail || 'Erro ao entrar.', 'error');
    }
  } catch(e) { toast('Erro de conexão.', 'error'); }
};

window.iniciarBatalha = async function() {
  if (!state.battle) return;
  try {
    const res = await fetch(`/api/batalha/iniciar/${state.battle.codigo}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
    const data = await res.json();
    if (res.ok) {
      stopLobbyPolling();
      const sala = await fetch(`/api/batalha/sala/${state.battle.codigo}`).then(r => r.json());
      showQuestion(sala);
    } else if (data.detail && data.detail.includes('Sem questões')) {
      showNoQuestionsModal(data.detail);
    } else {
      showBatalhaToast(data.detail || 'Erro ao iniciar.', 'error');
    }
  } catch(e) { showBatalhaToast('Erro de conexão.', 'error'); }
};

function showBatalhaToast(msg, type = 'info') {
  const t = document.createElement('div');
  t.style.cssText = 'position:fixed;top:20px;right:20px;padding:12px 20px;border-radius:10px;font-size:0.88rem;z-index:99999;animation:fadeIn 0.3s;max-width:320px;box-shadow:0 4px 12px rgba(0,0,0,0.4);';
  t.style.background = type === 'error' ? '#f38ba8' : type === 'success' ? '#a6e3a1' : '#89b4fa';
  t.style.color = '#1e1e2e';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

function showNoQuestionsModal(detail) {
  const materias = state.battle?.materias?.length ? state.battle.materias.join(', ') : 'todas';
  const overlay = document.createElement('div');
  overlay.id = 'no-questions-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.innerHTML = `
    <div style="background:var(--bg-surface);border-radius:16px;padding:28px;max-width:480px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <h3 style="color:var(--red);margin:0;font-size:1.1rem;">⚠️ Sem questões disponíveis</h3>
        <span onclick="document.getElementById('no-questions-modal').remove()" style="cursor:pointer;color:var(--text-sub);font-size:1.4rem;">&times;</span>
      </div>
      <p style="color:var(--text);font-size:0.9rem;margin-bottom:8px;">
        Não há questões suficientes para as matérias: <strong style="color:var(--blue);">${materias}</strong>
      </p>
      <p style="color:var(--text-sub);font-size:0.82rem;margin-bottom:20px;">
        Reconfigure a batalha com filtros diferentes ou selecione questões do banco manualmente.
      </p>
      
      <div style="display:flex;flex-direction:column;gap:10px;">
        <button onclick="document.getElementById('no-questions-modal').remove(); openQuestionPoolSelector()" style="width:100%;padding:12px;background:var(--green);color:#1e1e2e;border:none;border-radius:10px;font-weight:600;font-size:0.9rem;cursor:pointer;">
          🎯 Selecionar Questões do Banco
        </button>
        <button onclick="document.getElementById('no-questions-modal').remove(); reconfigurarBatalha()" style="width:100%;padding:12px;background:var(--yellow);color:#1e1e2e;border:none;border-radius:10px;font-weight:600;font-size:0.9rem;cursor:pointer;">
          🔄 Reconfigurar Batalha (alterar matérias)
        </button>
        <a href="/questoes.html" style="display:block;width:100%;padding:12px;background:var(--bg-elevated);color:var(--text);border:none;border-radius:10px;font-size:0.85rem;cursor:pointer;text-align:center;text-decoration:none;">
          📚 Ir para Banco de Questões (adicionar novas)
        </a>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
}

// ===== MODAL: Selecionar Pool de Questões =====
window.openQuestionPoolSelector = async function() {
  // Buscar questões disponíveis
  let questoes = [];
  try {
    const res = await fetch('/api/questoes?limit=500');
    const data = await res.json();
    questoes = (data.items || data || []).filter(q => q.resposta_correta);
  } catch(e) { showBatalhaToast('Erro ao carregar questões', 'error'); return; }

  if (!questoes.length) { showBatalhaToast('Nenhuma questão com gabarito no banco.', 'error'); return; }

  // Extrair filtros
  const materiasList = [...new Set(questoes.map(q => q.materia).filter(Boolean))].sort();
  const bancasList = [...new Set(questoes.map(q => q.banca).filter(Boolean))].sort();
  const dificuldades = ['Fácil', 'Médio', 'Difícil'];

  const overlay = document.createElement('div');
  overlay.id = 'pool-selector-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;overflow-y:auto;';
  overlay.innerHTML = `
    <div style="background:var(--bg-surface);border-radius:16px;padding:24px;max-width:600px;width:100%;max-height:90vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <h3 style="color:var(--green);margin:0;">🎯 Selecionar Questões para a Batalha</h3>
        <span onclick="document.getElementById('pool-selector-modal').remove()" style="cursor:pointer;color:var(--text-sub);font-size:1.4rem;">&times;</span>
      </div>
      
      <p style="color:var(--text-sub);font-size:0.82rem;margin-bottom:16px;">
        Filtre as questões por matéria, banca ou dificuldade. As selecionadas formarão o pool — o sistema sorteará aleatoriamente entre elas, com alternativas embaralhadas por jogador.
      </p>

      <!-- Filtros -->
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
        <select id="pool-filter-materia" aria-label="Filtrar por matéria" onchange="filterPoolQuestions()" style="padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.82rem;">
          <option value="">Todas matérias</option>
          ${materiasList.map(m => '<option value="' + m + '">' + m + '</option>').join('')}
        </select>
        <select id="pool-filter-banca" aria-label="Filtrar por banca" onchange="filterPoolQuestions()" style="padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.82rem;">
          <option value="">Todas bancas</option>
          ${bancasList.map(b => '<option value="' + b + '">' + b + '</option>').join('')}
        </select>
        <select id="pool-filter-dif" aria-label="Filtrar por dificuldade" onchange="filterPoolQuestions()" style="padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.82rem;">
          <option value="">Todas dificuldades</option>
          ${dificuldades.map(d => '<option value="' + d + '">' + d + '</option>').join('')}
        </select>
      </div>

      <!-- Ações em massa -->
      <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">
        <button onclick="toggleAllPool(true)" style="padding:6px 12px;background:var(--blue);color:#1e1e2e;border:none;border-radius:6px;font-size:0.78rem;cursor:pointer;font-weight:600;">✅ Selecionar todos</button>
        <button onclick="toggleAllPool(false)" style="padding:6px 12px;background:var(--bg-elevated);color:var(--text);border:none;border-radius:6px;font-size:0.78rem;cursor:pointer;">❌ Desmarcar todos</button>
        <span id="pool-count" style="margin-left:auto;color:var(--green);font-size:0.82rem;font-weight:600;">0 selecionadas</span>
      </div>

      <!-- Lista de questões -->
      <div id="pool-questions-list" style="max-height:300px;overflow-y:auto;border:1px solid var(--border);border-radius:10px;background:var(--bg);"></div>

      <!-- Confirmar -->
      <div style="display:flex;gap:8px;margin-top:16px;">
        <button onclick="document.getElementById('pool-selector-modal').remove()" style="flex:1;padding:10px;background:var(--bg-elevated);color:var(--text);border:none;border-radius:8px;cursor:pointer;">Cancelar</button>
        <button onclick="confirmPoolSelection()" style="flex:1;padding:10px;background:var(--green);color:#1e1e2e;border:none;border-radius:8px;font-weight:600;cursor:pointer;">🎲 Confirmar e Iniciar</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  // Armazenar questões e renderizar
  window._poolQuestions = questoes;
  window._poolSelected = new Set(questoes.map(q => q.id)); // Todas selecionadas por padrão
  filterPoolQuestions();
};

window.filterPoolQuestions = function() {
  const materia = document.getElementById('pool-filter-materia')?.value || '';
  const banca = document.getElementById('pool-filter-banca')?.value || '';
  const dif = document.getElementById('pool-filter-dif')?.value || '';

  let filtered = window._poolQuestions || [];
  if (materia) filtered = filtered.filter(q => q.materia === materia);
  if (banca) filtered = filtered.filter(q => q.banca === banca);
  if (dif) filtered = filtered.filter(q => q.dificuldade === dif);

  const listEl = document.getElementById('pool-questions-list');
  if (!listEl) return;

  listEl.innerHTML = filtered.map(q => {
    const checked = window._poolSelected.has(q.id) ? 'checked' : '';
    const enunciado = (q.enunciado || '').substring(0, 80) + (q.enunciado?.length > 80 ? '...' : '');
    return `<label style="display:flex;align-items:flex-start;gap:8px;padding:10px 12px;border-bottom:1px solid #313244;cursor:pointer;font-size:0.82rem;color:var(--text);" onmouseover="this.style.background='#313244'" onmouseout="this.style.background='transparent'">
      <input type="checkbox" ${checked} onchange="togglePoolQuestion(${q.id}, this.checked)" style="margin-top:2px;accent-color:var(--green);">
      <div style="flex:1;">
        <div>${enunciado}</div>
        <div style="font-size:0.72rem;color:var(--text-sub);margin-top:3px;">${q.materia || ''} · ${q.banca || ''} · ${q.dificuldade || 'Médio'}</div>
      </div>
    </label>`;
  }).join('');

  updatePoolCount();
};

window.togglePoolQuestion = function(id, checked) {
  if (checked) window._poolSelected.add(id);
  else window._poolSelected.delete(id);
  updatePoolCount();
};

window.toggleAllPool = function(selectAll) {
  const materia = document.getElementById('pool-filter-materia')?.value || '';
  const banca = document.getElementById('pool-filter-banca')?.value || '';
  const dif = document.getElementById('pool-filter-dif')?.value || '';

  let filtered = window._poolQuestions || [];
  if (materia) filtered = filtered.filter(q => q.materia === materia);
  if (banca) filtered = filtered.filter(q => q.banca === banca);
  if (dif) filtered = filtered.filter(q => q.dificuldade === dif);

  filtered.forEach(q => {
    if (selectAll) window._poolSelected.add(q.id);
    else window._poolSelected.delete(q.id);
  });
  filterPoolQuestions();
};

function updatePoolCount() {
  const el = document.getElementById('pool-count');
  if (el) el.textContent = `${window._poolSelected.size} selecionadas`;
}

window.confirmPoolSelection = async function() {
  const selected = [...window._poolSelected];
  if (selected.length < 3) {
    showBatalhaToast('Selecione pelo menos 3 questões para a batalha.', 'error');
    return;
  }

  if (!state.battle || !state.battle.codigo) {
    showBatalhaToast('Nenhuma sala ativa. Crie uma primeiro.', 'error');
    return;
  }

  // Reconfigurar com o pool selecionado e iniciar
  try {
    const res = await fetch(`/api/batalha/iniciar/${state.battle.codigo}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ questao_ids: selected })
    });
    const data = await res.json();
    if (res.ok) {
      document.getElementById('pool-selector-modal')?.remove();
      const sala = await fetch(`/api/batalha/sala/${state.battle.codigo}`).then(r => r.json());
      showQuestion(sala);
    } else {
      showBatalhaToast(data.detail || 'Erro ao iniciar.', 'error');
    }
  } catch(e) { showBatalhaToast('Erro de conexão.', 'error'); }
};

// ===== RECONFIGURAR BATALHA =====
window.reconfigurarBatalha = async function() {
  document.getElementById('no-questions-modal')?.remove();
  if (!state.battle || !state.battle.codigo) { showMenu(); return; }

  // Volta ao menu para o criador reconfigurar
  showMenu();
  showBatalhaToast('🔄 Sala resetada. Reconfigure as matérias e clique em Criar novamente.', 'info');

  // Deletar a sala antiga (reconfigurar = criar nova)
  try {
    await fetch(`/api/batalha/reconfigurar/${state.battle.codigo}`, { method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
  } catch(e) {}
  state.battle = null;
  setTimeout(setupAutocomplete, 50);
};

window.selectAnswer = function(letter) {
  state.selectedAnswer = letter;
  document.querySelectorAll('.option-btn').forEach(b => b.classList.remove('selected'));
  document.querySelector(`.option-btn[data-letter="${letter}"]`).classList.add('selected');
  const btn = document.getElementById('btn-confirm');
  btn.disabled = false;
  btn.style.opacity = '1';
};

window.confirmarResposta = async function() {
  if (!state.selectedAnswer || !state.battle) return;
  const btn = document.getElementById('btn-confirm');
  btn.disabled = true;
  btn.textContent = '⏳ Enviando...';

  const tempoUsado = state.battle.tempo_por_questao - state.timeLeft;

  // Enviar a letra VISUAL (o backend traduz via mapping)
  try {
    const res = await fetch(`/api/batalha/responder/${state.battle.codigo}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ resposta: state.selectedAnswer, tempo_seg: tempoUsado })
    });
    const data = await res.json();
    stopTimer();

    // Show result — resposta_correta agora é a letra VISUAL
    const correctVisual = data.resposta_correta.toLowerCase();
    document.querySelectorAll('.option-btn').forEach(b => {
      if (b.dataset.letter === correctVisual) b.classList.add('correct');
      if (b.dataset.letter === state.selectedAnswer && !data.acertou) b.classList.add('wrong');
      b.style.pointerEvents = 'none';
    });

    let feedbackText = data.acertou ? `✅ +${data.pontos_ganhos} pontos!` : `❌ Resposta: ${data.resposta_correta}`;
    if (data.streak_bonus) feedbackText += ` ${data.streak_bonus}`;
    btn.textContent = feedbackText;
    btn.style.background = data.acertou ? '#a6e3a1' : '#f38ba8';

    // Show streak fire animation
    if (data.streak >= 3) {
      const streakEl = document.createElement('div');
      streakEl.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);font-size:3rem;z-index:9999;animation:confetti-fall 1.5s ease-out forwards;';
      streakEl.textContent = data.streak >= 5 ? '🔥🔥 2x!' : '⚡ 1.5x!';
      document.body.appendChild(streakEl);
      setTimeout(() => streakEl.remove(), 2000);
    }

    // Wait and advance
    setTimeout(async () => {
      if (data.batalha_finalizada) {
        const rk = await fetch(`/api/batalha/ranking/${state.battle.codigo}`).then(r => r.json());
        showRanking(rk);
      } else if (data.rodada_completa) {
        const sala = await fetch(`/api/batalha/sala/${state.battle.codigo}`).then(r => r.json());
        showQuestion(sala);
      } else {
        // Aguardar outros jogadores
        btn.textContent = '⏳ Aguardando outros jogadores...';
        btn.style.background = '#45475a';
        pollForNextRound();
      }
    }, 2000);

  } catch(e) { toast('Erro ao enviar resposta.', 'error'); }
};

// Poll para esperar outros jogadores responderem
function pollForNextRound() {
  const poll = setInterval(async () => {
    try {
      const sala = await fetch(`/api/batalha/sala/${state.battle.codigo}`).then(r => r.json());
      if (sala.status === 'finalizada') {
        clearInterval(poll);
        const rk = await fetch(`/api/batalha/ranking/${state.battle.codigo}`).then(r => r.json());
        showRanking(rk);
      } else if (sala.rodada_atual > state.battle.rodada_atual) {
        clearInterval(poll);
        showQuestion(sala);
      }
    } catch(e) {}
  }, 2000);
  // Timeout after 60s
  setTimeout(() => clearInterval(poll), 60000);
}

window.refreshLobby = async function() {
  if (!state.battle) return;
  const sala = await fetch(`/api/batalha/sala/${state.battle.codigo}`).then(r => r.json());
  if (sala.status === 'em_andamento') showQuestion(sala);
  else showLobby(sala);
};

window.refreshBattle = async function() {
  if (!state.battle) return;
  const sala = await fetch(`/api/batalha/sala/${state.battle.codigo}`).then(r => r.json());
  if (sala.status === 'em_andamento') showQuestion(sala);
  else if (sala.status === 'finalizada') { const rk = await fetch(`/api/batalha/ranking/${state.battle.codigo}`).then(r=>r.json()); showRanking(rk); }
  else showLobby(sala);
};

window.openBattle = async function(codigo) {
  try {
    const sala = await fetch(`/api/batalha/sala/${codigo}`).then(r => r.json());
    if (sala.status === 'em_andamento') showQuestion(sala);
    else if (sala.status === 'finalizada') { const rk = await fetch(`/api/batalha/ranking/${codigo}`).then(r=>r.json()); showRanking(rk); }
    else showLobby(sala);
  } catch(e) { toast('Erro ao abrir sala.', 'error'); }
};

window.criarRevanche = async function(codigo) {
  try {
    const res = await fetch(`/api/batalha/revanche/${codigo}`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      await alertModal(`Revanche criada! Código: ${data.codigo}`, { type: 'success' });
      const sala = await fetch(`/api/batalha/sala/${data.codigo}`).then(r => r.json());
      showLobby(sala);
    } else {
      toast(data.detail || 'Erro ao criar revanche.', 'error');
    }
  } catch(e) { toast('Erro.', 'error'); }
};

window.showReview = async function(codigo) {
  try {
    const data = await fetch(`/api/batalha/review/${codigo}`).then(r => r.json());
    view.innerHTML = `
      <h1 style="text-align:center;">📖 Revisão da Batalha</h1>
      <div class="lobby-card" style="text-align:center;margin-bottom:16px;">
        <div style="font-size:1.6rem;font-weight:700;color:${data.resumo.pct_acerto >= 70 ? '#a6e3a1' : '#f9e2af'};">${data.resumo.pct_acerto}%</div>
        <div style="font-size:0.82rem;color:var(--text-sub);">${data.resumo.acertos}/${data.resumo.total} acertos</div>
      </div>
      ${data.questoes.map((q, i) => `
        <div class="lobby-card" style="margin-bottom:10px;border-left:4px solid ${q.acertei ? '#a6e3a1' : '#f38ba8'};">
          <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
            <span class="materia-badge">${q.materia}</span>
            <span style="font-size:0.75rem;color:${q.acertei ? '#a6e3a1' : '#f38ba8'};">${q.acertei ? '✅' : '❌'} ${q.pontos}pts · ${q.tempo_seg}s</span>
          </div>
          <div style="font-size:0.88rem;margin-bottom:8px;line-height:1.4;">${q.enunciado}</div>
          <div style="font-size:0.8rem;color:var(--green);background:var(--bg);padding:8px;border-radius:6px;">
            <strong>Correta:</strong> ${q.resposta_correta.toUpperCase()}) ${q.alternativas[q.resposta_correta] || ''}
          </div>
          ${!q.acertei && q.minha_resposta ? `<div style="font-size:0.78rem;color:var(--red);margin-top:4px;">Sua resposta: ${q.minha_resposta.toUpperCase()}) ${q.alternativas[q.minha_resposta] || ''}</div>` : ''}
          ${q.explicacao ? `<div style="font-size:0.78rem;color:var(--blue);margin-top:6px;padding:6px;background:var(--bg-elevated);border-radius:4px;">💡 ${q.explicacao}</div>` : ''}
        </div>
      `).join('')}
      <button class="btn-battle" onclick="showMenu()">🔙 Voltar</button>
    `;
  } catch(e) { toast('Erro ao carregar revisão.', 'error'); }
};

// ========== HELPERS ==========

function renderPlayers(players) {
  const el = document.getElementById('lobby-players');
  if (!el) return;
  el.innerHTML = players.map(p => `
    <div class="player-chip">
      <div class="avatar">${p.avatar || '👤'}</div>
      <span class="name">${p.nome}</span>
      <span style="font-size:0.72rem;color:var(--green);">${p.pontos || 0}pts</span>
    </div>
  `).join('') || '<div style="color:var(--text-sub);font-size:0.82rem;">Aguardando jogadores...</div>';
}

function renderRoundPlayers(responderam, jogadores) {
  const el = document.getElementById('round-players');
  if (!el || !jogadores) return;
  el.innerHTML = jogadores.map(p => {
    const answered = responderam.find(r => r.user_id === p.user_id);
    const status = answered ? (answered.acertou ? '✅' : '❌') : '⏳';
    return `<div class="player-chip"><span class="name" style="font-size:0.75rem;">${status} ${p.nome}</span></div>`;
  }).join('');
}

function startTimer(seconds) {
  state.timeLeft = seconds;
  state.timeMax = seconds;
  const fill = document.getElementById('timer-fill');
  const text = document.getElementById('timer-text');
  if (fill) fill.style.width = '100%';

  state.timer = setInterval(() => {
    state.timeLeft--;
    const absTime = Math.abs(state.timeLeft);
    if (text) text.textContent = (state.timeLeft < 0 ? '-' : '') + absTime + 's';
    
    if (state.timeLeft > 0) {
      if (fill) fill.style.width = (state.timeLeft / seconds * 100) + '%';
      if (fill && state.timeLeft <= 5) fill.style.background = '#f38ba8';
    } else {
      // Timer zerou — barra vazia, cor vermelha, mas NÃO bloqueia resposta
      if (fill) { fill.style.width = '0%'; fill.style.background = '#f38ba8'; }
      // Piscar o timer para indicar perda de pontos
      if (text) text.style.color = state.timeLeft % 2 === 0 ? '#f38ba8' : '#f9e2af';
    }

    // Limite máximo: 2x o tempo original (auto-submit forçado)
    if (state.timeLeft <= -(seconds)) {
      stopTimer();
      if (!state.selectedAnswer) state.selectedAnswer = 'x';
      window.confirmarResposta();
    }
  }, 1000);
}

function stopTimer() {
  if (state.timer) { clearInterval(state.timer); state.timer = null; }
}

let _myBattlesPage = 0;
let _myBattlesData = [];

async function loadMyBattles() {
  try {
    _myBattlesData = await fetch('/api/batalha/minhas').then(r => r.json());
    _myBattlesPage = 0;
    renderMyBattles();
  } catch(e) {}
}

function renderMyBattles() {
  const el = document.getElementById('my-battles');
  if (!el) return;
  if (!_myBattlesData.length) { el.innerHTML = '<div style="color:var(--text-muted);">Nenhuma batalha ainda</div>'; return; }

  const perPage = 3;
  const totalPages = Math.ceil(_myBattlesData.length / perPage);
  const start = _myBattlesPage * perPage;
  const page = _myBattlesData.slice(start, start + perPage);

  let html = page.map(b => {
    const statusIcon = b.status === 'finalizada' ? '🏁' : b.status === 'em_andamento' ? '⚔️' : '⏳';
    const posText = b.posicao ? ` · ${b.posicao}º lugar` : '';
    return `<div onclick="openBattle('${b.codigo}')" style="display:flex;align-items:center;gap:10px;padding:8px;background:var(--bg);border-radius:8px;margin-bottom:6px;cursor:pointer;">
      <span style="font-size:1.1rem;">${statusIcon}</span>
      <div style="flex:1;"><div style="font-size:0.82rem;font-weight:600;">${b.titulo}</div><div style="font-size:0.7rem;color:var(--text-sub);">${b.codigo} · ${b.total_rodadas} rodadas${posText}</div></div>
      <span style="font-size:0.85rem;font-weight:700;color:var(--yellow);">${b.pontos || 0}pts</span>
    </div>`;
  }).join('');

  if (totalPages > 1) {
    html += `<div style="display:flex;justify-content:center;align-items:center;gap:12px;margin-top:8px;">
      <button onclick="myBattlesNav(-1)" ${_myBattlesPage === 0 ? 'disabled' : ''} style="padding:4px 10px;background:${_myBattlesPage === 0 ? '#45475a' : '#89b4fa'};color:${_myBattlesPage === 0 ? '#585b70' : '#1e1e2e'};border:none;border-radius:6px;font-size:0.75rem;cursor:pointer;" aria-label="Página anterior">◀</button>
      <span style="font-size:0.75rem;color:var(--text-sub);">${_myBattlesPage + 1}/${totalPages}</span>
      <button onclick="myBattlesNav(1)" ${_myBattlesPage >= totalPages - 1 ? 'disabled' : ''} style="padding:4px 10px;background:${_myBattlesPage >= totalPages - 1 ? '#45475a' : '#89b4fa'};color:${_myBattlesPage >= totalPages - 1 ? '#585b70' : '#1e1e2e'};border:none;border-radius:6px;font-size:0.75rem;cursor:pointer;">▶</button>
    </div>`;
  }

  el.innerHTML = html;
}

window.myBattlesNav = function(dir) {
  const totalPages = Math.ceil(_myBattlesData.length / 3);
  _myBattlesPage = Math.max(0, Math.min(totalPages - 1, _myBattlesPage + dir));
  renderMyBattles();
};

function launchConfetti() {
  const colors = ['#f38ba8','#a6e3a1','#89b4fa','#f9e2af','#cba6f7','#fab387'];
  for (let i = 0; i < 60; i++) {
    const piece = document.createElement('div');
    piece.className = 'confetti-piece';
    piece.style.left = Math.random() * 100 + 'vw';
    piece.style.background = colors[Math.floor(Math.random() * colors.length)];
    piece.style.animationDelay = Math.random() * 2 + 's';
    piece.style.animationDuration = (2 + Math.random() * 2) + 's';
    document.body.appendChild(piece);
    setTimeout(() => piece.remove(), 5000);
  }
}

// ========== AUTOCOMPLETE MATÉRIAS ==========
const _selectedMaterias = [];
let _allMaterias = [];

// Carregar matérias disponíveis da API
fetch('/api/questoes/materias').then(r => r.json()).then(list => {
  _allMaterias = list.filter(m => m && m.trim());
}).catch(() => {});

let _input, _dropdown, _tagsContainer;

function renderTags() {
  if (!_tagsContainer || !_input) return;
  _tagsContainer.querySelectorAll('.mat-tag').forEach(el => el.remove());
  _selectedMaterias.forEach((mat, i) => {
    const tag = document.createElement('span');
    tag.className = 'mat-tag';
    tag.style.cssText = 'display:inline-flex;align-items:center;gap:4px;background:var(--bg-elevated);color:var(--blue);padding:3px 8px;border-radius:6px;font-size:0.78rem;white-space:nowrap;';
    tag.innerHTML = `${mat} <span style="cursor:pointer;color:var(--red);font-weight:bold;" onclick="removeMateria(${i})">&times;</span>`;
    _tagsContainer.insertBefore(tag, _input);
  });
  _input.placeholder = _selectedMaterias.length ? '' : 'Digite para buscar... (vazio = todas)';
}

window.removeMateria = function(index) {
  _selectedMaterias.splice(index, 1);
  renderTags();
};

function showDropdown(filter) {
  if (!_dropdown) return;
  const filtered = _allMaterias.filter(m =>
    !_selectedMaterias.includes(m) &&
    m.toLowerCase().includes(filter.toLowerCase())
  );
  if (!filtered.length) { _dropdown.style.display = 'none'; return; }
  _dropdown.innerHTML = filtered.map((m, idx) =>
    `<div style="padding:8px 12px;cursor:pointer;font-size:0.85rem;color:var(--text);border-bottom:1px solid var(--border);" 
          onmouseover="this.style.background='#45475a'" onmouseout="this.style.background='transparent'"
          data-idx="${idx}">${m}</div>`
  ).join('');
  _dropdown.querySelectorAll('[data-idx]').forEach(el => {
    el.onclick = () => selectMateria(filtered[parseInt(el.dataset.idx)]);
  });
  _dropdown.style.display = 'block';
}

window.selectMateria = function(mat) {
  if (!_selectedMaterias.includes(mat)) {
    _selectedMaterias.push(mat);
    renderTags();
  }
  if (_input) _input.value = '';
  if (_dropdown) _dropdown.style.display = 'none';
  if (_input) _input.focus();
};

function setupAutocomplete() {
  _input = document.getElementById('cfg-materias');
  _dropdown = document.getElementById('materias-dropdown');
  _tagsContainer = document.getElementById('materias-tags');
  if (!_input || !_dropdown || !_tagsContainer) return;

  _input.addEventListener('input', () => {
    const val = _input.value.trim();
    if (val.length >= 1) { showDropdown(val); }
    else { _dropdown.style.display = 'none'; }
  });

  _input.addEventListener('focus', () => {
    if (_input.value.trim().length >= 1) showDropdown(_input.value.trim());
    else if (!_selectedMaterias.length) showDropdown('');
  });

  _input.addEventListener('keydown', (e) => {
    if (e.key === 'Backspace' && !_input.value && _selectedMaterias.length) {
      _selectedMaterias.pop();
      renderTags();
    }
    if (e.key === 'Escape') _dropdown.style.display = 'none';
  });

  document.addEventListener('click', (e) => {
    const ac = document.getElementById('materias-autocomplete');
    if (ac && !ac.contains(e.target)) {
      _dropdown.style.display = 'none';
    }
  });

  _tagsContainer.addEventListener('click', () => {
    if (!_input.value && !_selectedMaterias.length) showDropdown('');
  });
}

// Expose showMenu to window for onclick handlers
window.showMenu = showMenu;

// Init
showMenu();
setTimeout(setupAutocomplete, 0);

// Auto-join if ?code= param present (from battle notification)
const urlCode = new URLSearchParams(window.location.search).get('code');
if (urlCode) {
  setTimeout(async () => {
    try {
      // Try to enter the room first
      await fetch('/api/batalha/entrar', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ codigo: urlCode })
      });
      const sala = await fetch(`/api/batalha/sala/${urlCode}`).then(r => r.json());
      if (sala.status === 'em_andamento') showQuestion(sala);
      else if (sala.status === 'finalizada') { const rk = await fetch(`/api/batalha/ranking/${urlCode}`).then(r=>r.json()); showRanking(rk); }
      else showLobby(sala);
    } catch(e) { showBatalhaToast('Erro ao entrar na sala.', 'error'); }
  }, 100);
}
