// studyroom.js - Enhanced Study Room with goals, ambient sounds, stats, todos, pomodoro visuals, focus mode

import { confirmModal, alertModal, promptModal } from '../modules/utils.js';
import { toast } from '../modules/toast.js';

const API = '/api/studyroom';
const token = localStorage.getItem('auth_token');
const headers = { 'Content-Type': 'application/json' };
if (token) headers['Authorization'] = `Bearer ${token}`;

let currentRoom = null;
let pollInterval = null;
let pomodoroTimer = null;
let pomodoroSeconds = 0;
let pomodoroPhase = 'focus'; // 'focus' or 'break'
let pomodoroCycle = 1;
const TOTAL_CYCLES = 4;
let myStatus = 'focando';
let modoFoco = false;
let roomTecnica = 'pomodoro';

// Ambient sound state
let ambientCtx = null;
let ambientNode = null;
let ambientGain = null;
let activeAmbient = null;

// Todo state
let todos = [];

// ============================================================
// API HELPERS
// ============================================================

async function apiPost(path, body) {
  const res = await fetch(API + path, { method: 'POST', headers, body: JSON.stringify(body) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Erro desconhecido' }));
    throw new Error(err.detail || 'Erro');
  }
  return res.json();
}

async function apiGet(path) {
  const res = await fetch(API + path, { headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Erro desconhecido' }));
    throw new Error(err.detail || 'Erro');
  }
  return res.json();
}

// ============================================================
// CRIAR SALA
// ============================================================

async function criarSala() {
  try {
    const titulo = document.getElementById('input-titulo').value.trim() || 'Sala de Estudos';
    const tecnica = document.getElementById('select-tecnica').value;
    const duracao_min = parseInt(document.getElementById('input-duracao').value) || 50;
    const max_participantes = parseInt(document.getElementById('input-max').value) || 10;
    const meta = document.getElementById('input-goal-criar').value.trim() || '';

    const data = await apiPost('/criar', { titulo, tecnica, duracao_min, max_participantes, meta });
    currentRoom = data.codigo;
    roomTecnica = tecnica;
    modoFoco = tecnica === 'pomodoro';
    enterRoomView(data.codigo);
  } catch (e) {
    toast('Erro ao criar sala: ' + e.message, 'error');
  }
}
window.criarSala = criarSala;

// ============================================================
// ENTRAR SALA
// ============================================================

async function entrarSala() {
  try {
    const codigo = document.getElementById('input-codigo').value.trim().toUpperCase();
    if (!codigo) { toast('Digite o código da sala', 'warning'); return; }
    const meta = document.getElementById('input-goal-entrar').value.trim() || '';
    await apiPost('/entrar', { codigo, meta });
    currentRoom = codigo;
    enterRoomView(codigo);
  } catch (e) {
    toast('Erro: ' + e.message, 'error');
  }
}
window.entrarSala = entrarSala;

// ============================================================
// ROOM VIEW
// ============================================================

function enterRoomView(codigo) {
  document.getElementById('view-lobby').classList.add('hidden');
  document.getElementById('view-room').classList.remove('hidden');
  document.getElementById('room-code').textContent = codigo;
  currentRoom = codigo;
  myStatus = 'focando';
  pomodoroCycle = 1;
  elaborationShownCycle = 0;
  breakCardsLoaded = false;
  srSessionMetrics = { flashcards: 0, questoes: 0, sumulas: 0, acertos: 0 };
  updateStatusButtons();
  startPolling();
  startPomodoro();
  loadTodos();
  loadCommitments();
  loadFocusScore();
  loadDiscussions();
  loadSrFlashcards(); // Load study activities
  updateFocusMode();
  // Refresh focus score every 60s
  setInterval(() => { if (currentRoom) loadFocusScore(); }, 60000);
}

function sairSala() {
  // Registrar tempo focado antes de sair (muda status para 'ausente' que aciona award_focus_xp no backend)
  if (currentRoom) {
    fetch(`/api/studyroom/status/${currentRoom}`, {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'ausente' })
    }).catch(() => {});
  }
  // Show session summary before leaving
  showSessionSummary();
  stopPolling();
  stopPomodoro();
  stopAmbient();
  currentRoom = null;
  todos = [];
  breakCardsLoaded = false;
  document.getElementById('view-room').classList.add('hidden');
  document.getElementById('view-lobby').classList.remove('hidden');
  loadMinhasSalas();
}
window.sairSala = sairSala;

function copiarCodigo() {
  navigator.clipboard.writeText(currentRoom).then(() => {
    const btn = event.target;
    btn.textContent = '✅ copiado!';
    setTimeout(() => btn.textContent = '📋 copiar', 1500);
  });
}
window.copiarCodigo = copiarCodigo;

// ============================================================
// POLLING
// ============================================================

function startPolling() {
  pollRoom();
  pollInterval = setInterval(pollRoom, 3000);
}

function stopPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = null;
}

async function pollRoom() {
  if (!currentRoom) return;
  try {
    const data = await apiGet(`/sala/${currentRoom}`);
    renderRoom(data);
  } catch (e) {
    console.error('Poll error:', e);
  }
}

function renderRoom(data) {
  document.getElementById('room-title').textContent = data.titulo;
  roomTecnica = data.tecnica || 'pomodoro';
  modoFoco = data.modo_foco !== undefined ? data.modo_foco : (roomTecnica === 'pomodoro');

  // Participants
  const grid = document.getElementById('participants-grid');
  grid.innerHTML = data.participantes.map(p => {
    const statusIcon = p.status === 'focando' ? '🟢' : p.status === 'pausando' ? '🟡' : '⚫';
    const tempo = formatTime(p.tempo_estudado);
    const meClass = p.is_me ? ' me' : '';
    const goalHtml = p.meta ? `<div class="participant-goal">🎯 ${escHtml(p.meta)}</div>` : '';
    const nudgeBtn = !p.is_me && p.status !== 'focando' ? `<button onclick="sendNudge(${p.user_id})" style="font-size:0.65rem;background:var(--yellow);color:var(--bg);border:none;border-radius:4px;padding:2px 6px;cursor:pointer;margin-top:2px;" title="Enviar incentivo">🔔</button>` : '';
    return `<div class="participant-card${meClass}">
      <div class="participant-status">${statusIcon}</div>
      <div class="participant-info">
        <div class="participant-name">${escHtml(p.nome)}${p.is_me ? ' (eu)' : ''}</div>
        ${goalHtml}
        <div class="participant-time">⏱️ ${tempo} ${nudgeBtn}</div>
      </div>
    </div>`;
  }).join('');

  // Stats
  document.getElementById('stat-participantes').textContent = data.participantes.length;
  document.getElementById('stat-focando').textContent = data.participantes.filter(p => p.status === 'focando').length;
  const totalSeg = data.participantes.reduce((sum, p) => sum + (p.tempo_estudado || 0), 0);
  document.getElementById('stat-total-tempo').textContent = formatTime(totalSeg);

  // Real-time ranking
  renderRanking(data.participantes);

  // Chat
  renderChat(data.chat_messages);

  // Timer phase label (for livre mode)
  if (data.tecnica === 'livre') {
    document.getElementById('timer-phase').textContent = '⏱️ LIVRE';
    document.getElementById('timer-phase').className = 'timer-phase focus';
    document.getElementById('pomodoro-cycle').style.display = 'none';
  } else {
    document.getElementById('pomodoro-cycle').style.display = 'flex';
  }

  // Update focus mode
  updateFocusMode();
}

// ============================================================
// REAL-TIME STATS / RANKING
// ============================================================

function renderRanking(participantes) {
  const sorted = [...participantes].sort((a, b) => (b.tempo_estudado || 0) - (a.tempo_estudado || 0));
  const rankingEl = document.getElementById('stats-ranking');

  rankingEl.innerHTML = sorted.map((p, i) => {
    const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i + 1}.`;
    return `<li>
      <span class="rank-pos">${medal}</span>
      <span class="rank-name">${escHtml(p.nome)}${p.is_me ? ' (eu)' : ''}</span>
      <span class="rank-time">${formatTime(p.tempo_estudado)}</span>
    </li>`;
  }).join('');

  // Longest focused
  const focando = participantes.filter(p => p.status === 'focando');
  const longestEl = document.getElementById('stats-longest');
  if (focando.length > 0) {
    const longest = focando.reduce((a, b) => (b.tempo_estudado || 0) > (a.tempo_estudado || 0) ? b : a);
    longestEl.textContent = `🔥 Mais tempo focando agora: ${longest.nome} (${formatTime(longest.tempo_estudado)})`;
  } else {
    longestEl.textContent = 'Ninguém focando no momento';
  }
}

// ============================================================
// FOCUS MODE INDICATOR
// ============================================================

function updateFocusMode() {
  const timerSection = document.getElementById('timer-section');
  const chatInput = document.getElementById('chat-input');
  const chatSendBtn = document.getElementById('chat-send-btn');
  const chatFocusMsg = document.getElementById('chat-focus-msg');

  // Remove previous state classes
  timerSection.classList.remove('focus-active', 'break-active');

  if (modoFoco && roomTecnica === 'pomodoro') {
    if (pomodoroPhase === 'focus') {
      timerSection.classList.add('focus-active');
      // Disable chat during focus
      chatInput.disabled = true;
      chatInput.placeholder = '🔒 Chat disponível no intervalo';
      chatSendBtn.disabled = true;
      chatFocusMsg.classList.add('visible');
    } else {
      timerSection.classList.add('break-active');
      // Enable chat during break
      chatInput.disabled = false;
      chatInput.placeholder = 'Mensagem...';
      chatSendBtn.disabled = false;
      chatFocusMsg.classList.remove('visible');
    }
  } else {
    // No focus mode restriction
    chatInput.disabled = false;
    chatInput.placeholder = 'Mensagem...';
    chatSendBtn.disabled = false;
    chatFocusMsg.classList.remove('visible');
  }
}

// ============================================================
// CHAT
// ============================================================

function renderChat(messages) {
  const container = document.getElementById('chat-messages');
  const wasAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;

  container.innerHTML = messages.map(m => {
    const time = m.created_at ? new Date(m.created_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '';
    return `<div class="chat-msg">
      <div class="chat-msg-name">${escHtml(m.nome)}</div>
      <div class="chat-msg-text">${escHtml(m.mensagem)}</div>
      <div class="chat-msg-time">${time}</div>
    </div>`;
  }).join('');

  if (wasAtBottom) container.scrollTop = container.scrollHeight;
}

async function enviarMsg() {
  const input = document.getElementById('chat-input');
  if (input.disabled) return;
  const mensagem = input.value.trim();
  if (!mensagem || !currentRoom) return;
  input.value = '';
  try {
    await apiPost(`/chat/${currentRoom}`, { mensagem });
    pollRoom(); // refresh immediately
  } catch (e) {
    toast('Erro: ' + e.message, 'error');
  }
}
window.enviarMsg = enviarMsg;

// ============================================================
// STATUS
// ============================================================

async function setStatus(status) {
  if (!currentRoom) return;
  myStatus = status;
  updateStatusButtons();
  try {
    await apiPost(`/status/${currentRoom}`, { status });
  } catch (e) {
    console.error('Status error:', e);
  }
}
window.setStatus = setStatus;

function updateStatusButtons() {
  document.getElementById('btn-focando').className = 'status-btn' + (myStatus === 'focando' ? ' active-focando' : '');
  document.getElementById('btn-pausando').className = 'status-btn' + (myStatus === 'pausando' ? ' active-pausando' : '');
  document.getElementById('btn-ausente').className = 'status-btn' + (myStatus === 'ausente' ? ' active-ausente' : '');
}

// ============================================================
// POMODORO TIMER
// ============================================================

const FOCUS_DURATION = 25 * 60;
const BREAK_DURATION = 5 * 60;
const CYCLE_DURATION = FOCUS_DURATION + BREAK_DURATION;

function startPomodoro() {
  pomodoroSeconds = 0;
  pomodoroPhase = 'focus';
  pomodoroCycle = 1;
  updateTimerDisplay();
  updateCycleDisplay();
  pomodoroTimer = setInterval(tickPomodoro, 1000);
}

function stopPomodoro() {
  if (pomodoroTimer) clearInterval(pomodoroTimer);
  pomodoroTimer = null;
}

function tickPomodoro() {
  if (myStatus === 'ausente') return; // don't tick when absent

  pomodoroSeconds++;

  const posInCycle = pomodoroSeconds % CYCLE_DURATION;
  const prevPhase = pomodoroPhase;

  if (posInCycle < FOCUS_DURATION) {
    if (pomodoroPhase !== 'focus') {
      pomodoroPhase = 'focus';
      document.getElementById('timer-phase').textContent = '🍅 FOCO';
      document.getElementById('timer-phase').className = 'timer-phase focus';
      updateFocusMode();
      hideBreakCards();
      if (myStatus === 'pausando') setStatus('focando');
    }
  } else {
    if (pomodoroPhase !== 'break') {
      pomodoroPhase = 'break';
      document.getElementById('timer-phase').textContent = '☕ PAUSA';
      document.getElementById('timer-phase').className = 'timer-phase break';
      updateFocusMode();
      showBreakCards();
      // Play beep notification
      playBeep();
      // Notify
      if (Notification.permission === 'granted') {
        new Notification('☕ Hora da pausa!', { body: '5 minutos de descanso. Revise seus cards!' });
      }
    }
  }

  // Detect cycle end (transition from break back to focus)
  if (prevPhase === 'break' && pomodoroPhase === 'focus' && pomodoroSeconds > 0) {
    pomodoroCycle = Math.min(pomodoroCycle + 1, TOTAL_CYCLES);
    playBeep();
    if (Notification.permission === 'granted') {
      new Notification('🍅 Novo ciclo!', { body: `Ciclo ${pomodoroCycle}/${TOTAL_CYCLES} - Hora de focar!` });
    }
    // Elaboration prompt every 2 cycles
    if (pomodoroCycle - elaborationShownCycle >= 2) {
      elaborationShownCycle = pomodoroCycle;
      showElaborationPrompt();
    }
    // Show mindfulness on last cycle's break (long break)
    if (pomodoroCycle >= TOTAL_CYCLES) {
      showMindfulness();
    }
  }

  // Detect full cycle count based on total time
  pomodoroCycle = Math.min(Math.floor(pomodoroSeconds / CYCLE_DURATION) + 1, TOTAL_CYCLES);

  updateTimerDisplay();
  updateCycleDisplay();
  // Check for cognitive fatigue every 30 seconds
  if (pomodoroSeconds % 30 === 0) checkAdaptiveFatigue();
}

function updateTimerDisplay() {
  const posInCycle = pomodoroSeconds % CYCLE_DURATION;

  let remaining;
  if (pomodoroPhase === 'focus') {
    remaining = FOCUS_DURATION - posInCycle;
  } else {
    remaining = CYCLE_DURATION - posInCycle;
  }

  const min = Math.floor(remaining / 60);
  const sec = remaining % 60;
  document.getElementById('timer-display').textContent =
    String(min).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
}

function updateCycleDisplay() {
  const cycleLabel = document.getElementById('cycle-label');
  cycleLabel.textContent = `Ciclo ${pomodoroCycle}/${TOTAL_CYCLES}`;

  // Progress ring
  const posInCycle = pomodoroSeconds % CYCLE_DURATION;
  const phaseDuration = pomodoroPhase === 'focus' ? FOCUS_DURATION : BREAK_DURATION;
  const phaseElapsed = pomodoroPhase === 'focus' ? posInCycle : posInCycle - FOCUS_DURATION;
  const progress = Math.min(phaseElapsed / phaseDuration, 1);

  const circumference = 2 * Math.PI * 26; // r=26
  const offset = circumference * (1 - progress);

  const ringFill = document.getElementById('progress-ring-fill');
  ringFill.style.strokeDashoffset = offset;
  ringFill.classList.toggle('break', pomodoroPhase === 'break');

  const ringText = document.getElementById('progress-ring-text');
  ringText.textContent = Math.round(progress * 100) + '%';
}

// ============================================================
// BEEP NOTIFICATION SOUND
// ============================================================

function playBeep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = ctx.createOscillator();
    const gainNode = ctx.createGain();
    oscillator.connect(gainNode);
    gainNode.connect(ctx.destination);
    oscillator.frequency.value = 880;
    oscillator.type = 'sine';
    gainNode.gain.setValueAtTime(0.3, ctx.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
    oscillator.start(ctx.currentTime);
    oscillator.stop(ctx.currentTime + 0.5);
    // Second beep
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.frequency.value = 1100;
    osc2.type = 'sine';
    gain2.gain.setValueAtTime(0.3, ctx.currentTime + 0.3);
    gain2.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
    osc2.start(ctx.currentTime + 0.3);
    osc2.stop(ctx.currentTime + 0.8);
  } catch (e) {
    // Audio not available
  }
}

// ============================================================
// AMBIENT SOUNDS (Web Audio API - zero external files)
// ============================================================

function toggleAmbient(type) {
  // Update button states
  const buttons = document.querySelectorAll('.ambient-btn');
  buttons.forEach(btn => btn.classList.remove('active'));

  if (type === 'silence' || type === activeAmbient) {
    stopAmbient();
    if (type === 'silence') {
      document.querySelector('[data-sound="silence"]').classList.add('active');
    }
    activeAmbient = null;
    return;
  }

  stopAmbient();
  activeAmbient = type;
  document.querySelector(`[data-sound="${type}"]`).classList.add('active');

  startAmbientNoise(type);
}
window.toggleAmbient = toggleAmbient;

function startAmbientNoise(type) {
  try {
    ambientCtx = new (window.AudioContext || window.webkitAudioContext)();
    const bufferSize = 2 * ambientCtx.sampleRate;
    const buffer = ambientCtx.createBuffer(1, bufferSize, ambientCtx.sampleRate);
    const data = buffer.getChannelData(0);

    switch (type) {
      case 'rain': // White noise - rain-like
        for (let i = 0; i < bufferSize; i++) {
          data[i] = Math.random() * 2 - 1;
        }
        break;
      case 'cafe': // Brown noise - café ambiance
        {
          let last = 0;
          for (let i = 0; i < bufferSize; i++) {
            const white = Math.random() * 2 - 1;
            last = (last + (0.02 * white)) / 1.02;
            data[i] = last * 3.5;
          }
        }
        break;
      case 'waves': // Pink noise - ocean waves
        {
          let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
          for (let i = 0; i < bufferSize; i++) {
            const white = Math.random() * 2 - 1;
            b0 = 0.99886 * b0 + white * 0.0555179;
            b1 = 0.99332 * b1 + white * 0.0750759;
            b2 = 0.96900 * b2 + white * 0.1538520;
            b3 = 0.86650 * b3 + white * 0.3104856;
            b4 = 0.55000 * b4 + white * 0.5329522;
            b5 = -0.7616 * b5 - white * 0.0168980;
            data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11;
            b6 = white * 0.115926;
          }
        }
        break;
      case 'lofi': // Filtered pink noise with gentle modulation for lo-fi feel
        {
          let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
          for (let i = 0; i < bufferSize; i++) {
            const white = Math.random() * 2 - 1;
            b0 = 0.99886 * b0 + white * 0.0555179;
            b1 = 0.99332 * b1 + white * 0.0750759;
            b2 = 0.96900 * b2 + white * 0.1538520;
            b3 = 0.86650 * b3 + white * 0.3104856;
            b4 = 0.55000 * b4 + white * 0.5329522;
            b5 = -0.7616 * b5 - white * 0.0168980;
            const pink = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11;
            b6 = white * 0.115926;
            // Add gentle sine modulation for warmth
            const mod = Math.sin(i / (ambientCtx.sampleRate * 0.8)) * 0.3;
            data[i] = pink * (0.7 + mod * 0.3);
          }
        }
        break;
      default:
        for (let i = 0; i < bufferSize; i++) {
          data[i] = Math.random() * 2 - 1;
        }
    }

    ambientNode = ambientCtx.createBufferSource();
    ambientNode.buffer = buffer;
    ambientNode.loop = true;

    ambientGain = ambientCtx.createGain();
    const vol = parseInt(document.getElementById('ambient-volume').value) / 100;
    ambientGain.gain.value = vol * 0.5; // Keep it subtle

    // Low-pass filter to smooth noise
    const filter = ambientCtx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = type === 'rain' ? 8000 : type === 'cafe' ? 1200 : type === 'waves' ? 2000 : 3000;

    ambientNode.connect(filter);
    filter.connect(ambientGain);
    ambientGain.connect(ambientCtx.destination);
    ambientNode.start();
  } catch (e) {
    console.error('Ambient audio error:', e);
  }
}

function stopAmbient() {
  try {
    if (ambientNode) {
      ambientNode.stop();
      ambientNode.disconnect();
    }
    if (ambientCtx) {
      ambientCtx.close();
    }
  } catch (e) { /* ignore */ }
  ambientNode = null;
  ambientGain = null;
  ambientCtx = null;
}

function setAmbientVolume(val) {
  if (ambientGain) {
    ambientGain.gain.value = (val / 100) * 0.5;
  }
}
window.setAmbientVolume = setAmbientVolume;

// ============================================================
// TODO LIST
// ============================================================

function toggleTodo() {
  const body = document.getElementById('todo-body');
  const toggle = document.getElementById('todo-toggle');
  body.classList.toggle('collapsed');
  toggle.classList.toggle('collapsed');
}
window.toggleTodo = toggleTodo;

async function loadTodos() {
  if (!currentRoom) return;
  try {
    const data = await apiGet(`/todos/${currentRoom}`);
    todos = data.todos || [];
    renderTodos();
  } catch (e) {
    // API might not support todos yet; use local state
    todos = [];
    renderTodos();
  }
}

async function addTodo() {
  const input = document.getElementById('todo-input');
  const text = input.value.trim();
  if (!text || !currentRoom) return;
  input.value = '';

  const todo = { id: Date.now().toString(), text, completed: false };
  todos.push(todo);
  renderTodos();

  try {
    await apiPost(`/todos/${currentRoom}`, { text });
  } catch (e) {
    // API may not exist yet, keep local
  }
}
window.addTodo = addTodo;

async function toggleTodoItem(id) {
  const todo = todos.find(t => t.id === id);
  if (!todo) return;
  todo.completed = !todo.completed;
  renderTodos();

  if (todo.completed) {
    // Send celebration to chat
    try {
      await apiPost(`/chat/${currentRoom}`, { mensagem: `🎉 Completou: ${todo.text}` });
      pollRoom();
    } catch (e) { /* ignore */ }
  }

  try {
    await apiPost(`/todos/${currentRoom}/toggle`, { id });
  } catch (e) { /* ignore */ }
}
window.toggleTodoItem = toggleTodoItem;

function renderTodos() {
  const list = document.getElementById('todo-list');
  list.innerHTML = todos.map(t => {
    const completedClass = t.completed ? ' completed' : '';
    const checked = t.completed ? 'checked' : '';
    return `<li class="todo-item${completedClass}">
      <input type="checkbox" ${checked} onchange="toggleTodoItem('${t.id}')">
      <span class="todo-item-text">${escHtml(t.text)}</span>
    </li>`;
  }).join('');
}

// ============================================================
// MINHAS SALAS
// ============================================================

async function loadMinhasSalas() {
  try {
    const data = await apiGet('/minhas');
    const container = document.getElementById('minhas-salas-list');
    if (!data.salas || data.salas.length === 0) {
      container.innerHTML = '<div style="text-align:center; color:var(--text-muted); font-size:0.82rem; padding:16px;">Nenhuma sala encontrada</div>';
      return;
    }
    container.innerHTML = data.salas.map(s => {
      const tecLabel = s.tecnica === 'pomodoro' ? '🍅 Pomodoro' : '⏱️ Livre';
      return `<div class="room-item" onclick="rejoinRoom('${s.codigo}')">
        <div class="room-item-info">
          <div class="room-item-title">${escHtml(s.titulo)}</div>
          <div class="room-item-meta">${tecLabel} • ${s.num_participantes}/${s.max_participantes} pessoas • ${s.codigo}</div>
        </div>
        <div class="room-item-badge">${s.status}</div>
      </div>`;
    }).join('');
  } catch (e) {
    console.error('Error loading rooms:', e);
  }
}

function rejoinRoom(codigo) {
  currentRoom = codigo;
  enterRoomView(codigo);
}
window.rejoinRoom = rejoinRoom;

// ============================================================
// UTILS
// ============================================================

function formatTime(seg) {
  if (!seg || seg < 0) return '0m';
  const h = Math.floor(seg / 3600);
  const m = Math.floor((seg % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ============================================================
// STUDY ACTIVITIES: In-Room Study (Flashcards, Questões, Súmulas, PDF)
// ============================================================

let srFlashcards = [], srFcIdx = 0;
let srQuestoes = [], srQIdx = 0;
let srSumulas = [], srSmIdx = 0;
let srSessionMetrics = { flashcards: 0, questoes: 0, sumulas: 0, acertos: 0 };

function switchStudyTab(tab) {
  document.querySelectorAll('.study-tab-content').forEach(el => el.classList.add('hidden'));
  document.getElementById('study-tab-' + tab).classList.remove('hidden');
  document.querySelectorAll('#study-tabs button').forEach(btn => btn.classList.remove('active'));
  document.querySelector(`#study-tabs [data-tab="${tab}"]`).classList.add('active');

  // Lazy load content
  if (tab === 'flashcards' && srFlashcards.length === 0) loadSrFlashcards();
  if (tab === 'questoes' && srQuestoes.length === 0) loadSrQuestoes();
  if (tab === 'sumulas' && srSumulas.length === 0) loadSrSumulas();
  if (tab === 'pdf') loadSrPdfs();
}
window.switchStudyTab = switchStudyTab;

function updateSessionStats() {
  const el = document.getElementById('study-session-stats');
  if (el) {
    el.textContent = `🃏${srSessionMetrics.flashcards} ❓${srSessionMetrics.questoes} ⚖️${srSessionMetrics.sumulas} ✓${srSessionMetrics.acertos}`;
  }
}

// --- FLASHCARDS ---

async function loadSrFlashcards() {
  try {
    const res = await fetch('/api/flashcards/today', { headers });
    if (!res.ok) return;
    srFlashcards = await res.json();
    srFcIdx = 0;
    showSrFlashcard();
  } catch (e) {
    document.getElementById('sr-fc-container').innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem;text-align:center;padding:20px;">Erro ao carregar flashcards</div>';
  }
}

function showSrFlashcard() {
  const container = document.getElementById('sr-fc-container');
  if (srFcIdx >= srFlashcards.length) {
    container.innerHTML = srFlashcards.length > 0
      ? `<div style="text-align:center;padding:20px;color:var(--green);font-weight:600;">🎉 ${srFlashcards.length} flashcards revisados nesta sessão!</div>`
      : `<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:0.82rem;">Nenhum flashcard pendente para hoje.</div>`;
    return;
  }
  const card = srFlashcards[srFcIdx];
  container.innerHTML = `
    <div class="sr-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:0.72rem;color:var(--accent);">${card.materia || 'Geral'}</span>
        <span style="font-size:0.72rem;color:var(--text-muted);">${srFcIdx + 1}/${srFlashcards.length}</span>
      </div>
      <div class="sr-card-front">${escHtml(card.pergunta)}</div>
      <div class="sr-card-back" id="sr-fc-back">${escHtml(card.resposta)}</div>
      <button id="sr-fc-reveal-btn" onclick="revealSrFlashcard()" style="margin-top:10px;background:var(--accent);color:var(--bg);border:none;border-radius:var(--radius-md);padding:8px 16px;font-size:0.82rem;font-weight:600;cursor:pointer;width:100%;">👁 Revelar Resposta</button>
      <div class="sr-rating-btns" id="sr-fc-rating" style="display:none;">
        <button onclick="rateSrFlashcard(0)" style="background:#f38ba8;">Esqueci</button>
        <button onclick="rateSrFlashcard(2)" style="background:#fab387;">Difícil</button>
        <button onclick="rateSrFlashcard(3)" style="background:#f9e2af;color:#1e1e2e;">Ok</button>
        <button onclick="rateSrFlashcard(4)" style="background:#a6e3a1;color:#1e1e2e;">Bom</button>
        <button onclick="rateSrFlashcard(5)" style="background:#a6e3a1;color:#1e1e2e;">Fácil</button>
      </div>
    </div>`;
}

function revealSrFlashcard() {
  document.getElementById('sr-fc-back').classList.add('visible');
  document.getElementById('sr-fc-reveal-btn').style.display = 'none';
  document.getElementById('sr-fc-rating').style.display = 'flex';
}
window.revealSrFlashcard = revealSrFlashcard;

async function rateSrFlashcard(quality) {
  const card = srFlashcards[srFcIdx];
  try {
    const res = await fetch(`/api/flashcards/${card.id}/review-sm2`, {
      method: 'POST', headers, body: JSON.stringify({ quality })
    });
    if (res.ok) {
      srSessionMetrics.flashcards++;
      if (quality >= 3) srSessionMetrics.acertos++;
      updateSessionStats();
    } else {
      console.error('Flashcard review failed:', res.status);
    }
  } catch (e) { console.error('Flashcard review error:', e); }
  srFcIdx++;
  showSrFlashcard();
}
window.rateSrFlashcard = rateSrFlashcard;

// --- QUESTÕES ---

async function loadSrQuestoes() {
  try {
    const res = await fetch('/api/questoes?limit=20', { headers });
    if (!res.ok) return;
    const data = await res.json();
    srQuestoes = Array.isArray(data) ? data : (data.items || []);
    // Shuffle for variety
    srQuestoes.sort(() => Math.random() - 0.5);
    srQIdx = 0;
    showSrQuestao();
  } catch (e) {
    document.getElementById('sr-q-container').innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem;text-align:center;padding:20px;">Erro ao carregar questões</div>';
  }
}

function showSrQuestao() {
  const container = document.getElementById('sr-q-container');
  if (srQIdx >= srQuestoes.length) {
    container.innerHTML = srQuestoes.length > 0
      ? `<div style="text-align:center;padding:20px;color:var(--green);font-weight:600;">🎉 ${srSessionMetrics.questoes} questões respondidas!</div>`
      : `<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:0.82rem;">Nenhuma questão disponível. Importe questões primeiro.</div>`;
    return;
  }
  const q = srQuestoes[srQIdx];
  const letters = ['A', 'B', 'C', 'D', 'E'];
  const alts = letters.filter(l => q['alternativa_' + l.toLowerCase()]);
  container.innerHTML = `
    <div class="sr-card">
      <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
        <span style="font-size:0.72rem;color:var(--blue);">${q.materia || ''} ${q.banca ? '• ' + q.banca : ''}</span>
        <span style="font-size:0.72rem;color:var(--text-muted);">${srQIdx + 1}/${srQuestoes.length}</span>
      </div>
      <div style="font-size:0.85rem;color:var(--text);margin-bottom:10px;">${escHtml(q.enunciado)}</div>
      <div id="sr-q-options">
        ${alts.map(l => `<button class="sr-q-option" id="sr-q-opt-${l}" onclick="answerSrQuestao('${l}')">${l}) ${escHtml(q['alternativa_' + l.toLowerCase()])}</button>`).join('')}
      </div>
      <div id="sr-q-feedback" style="display:none;margin-top:10px;padding:10px;border-radius:var(--radius-md);font-size:0.82rem;"></div>
      <button id="sr-q-next" onclick="nextSrQuestao()" style="display:none;margin-top:8px;background:var(--accent);color:var(--bg);border:none;border-radius:var(--radius-md);padding:8px 16px;font-size:0.82rem;font-weight:600;cursor:pointer;width:100%;">Próxima →</button>
    </div>`;
}

async function answerSrQuestao(resposta) {
  const q = srQuestoes[srQIdx];
  // Disable all options
  document.querySelectorAll('.sr-q-option').forEach(btn => { btn.disabled = true; btn.style.cursor = 'default'; });

  try {
    const res = await fetch(`/api/questoes/${q.id}/responder`, {
      method: 'POST', headers, body: JSON.stringify({ resposta })
    });
    const data = await res.json();
    const acertou = data.acertou;

    // Highlight correct/wrong
    document.getElementById('sr-q-opt-' + resposta).classList.add(acertou ? 'correct' : 'wrong');
    if (!acertou && q.resposta_correta) {
      const correctBtn = document.getElementById('sr-q-opt-' + q.resposta_correta);
      if (correctBtn) correctBtn.classList.add('correct');
    }

    // Feedback
    const fb = document.getElementById('sr-q-feedback');
    fb.style.display = 'block';
    fb.style.background = acertou ? 'rgba(166,227,161,0.1)' : 'rgba(243,139,168,0.1)';
    fb.style.color = acertou ? 'var(--green)' : 'var(--red)';
    fb.textContent = acertou ? '✓ Correto!' : `✗ Errou. Resposta: ${q.resposta_correta || data.resposta_correta || '?'}`;

    srSessionMetrics.questoes++;
    if (acertou) srSessionMetrics.acertos++;
    updateSessionStats();
  } catch (e) {
    // Fallback: compare locally if API fails
    const acertou = resposta === q.resposta_correta;
    document.getElementById('sr-q-opt-' + resposta).classList.add(acertou ? 'correct' : 'wrong');
    srSessionMetrics.questoes++;
    if (acertou) srSessionMetrics.acertos++;
    updateSessionStats();
  }
  document.getElementById('sr-q-next').style.display = 'block';
}
window.answerSrQuestao = answerSrQuestao;

function nextSrQuestao() {
  srQIdx++;
  showSrQuestao();
}
window.nextSrQuestao = nextSrQuestao;

// --- SÚMULAS ---

async function loadSrSumulas() {
  try {
    const res = await fetch('/api/sumulas/today', { headers });
    if (!res.ok) return;
    srSumulas = await res.json();
    srSmIdx = 0;
    showSrSumula();
  } catch (e) {
    document.getElementById('sr-sm-container').innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem;text-align:center;padding:20px;">Erro ao carregar súmulas</div>';
  }
}

function showSrSumula() {
  const container = document.getElementById('sr-sm-container');
  if (srSmIdx >= srSumulas.length) {
    container.innerHTML = srSumulas.length > 0
      ? `<div style="text-align:center;padding:20px;color:var(--green);font-weight:600;">🎉 ${srSessionMetrics.sumulas} súmulas revisadas!</div>`
      : `<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:0.82rem;">Nenhuma súmula pendente para hoje.</div>`;
    return;
  }
  const s = srSumulas[srSmIdx];
  const vinc = s.vinculante ? '<span style="background:#f38ba8;color:#1e1e2e;padding:1px 5px;border-radius:3px;font-size:0.6rem;font-weight:700;margin-left:6px;">VINCULANTE</span>' : '';
  container.innerHTML = `
    <div class="sr-card">
      <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
        <span style="font-size:0.72rem;color:var(--accent);">🏛️ ${s.tribunal} — nº ${s.numero}${vinc}</span>
        <span style="font-size:0.72rem;color:var(--text-muted);">${srSmIdx + 1}/${srSumulas.length}</span>
      </div>
      <div class="sr-card-front" style="color:var(--yellow);">Qual é o enunciado da Súmula ${s.tribunal} nº ${s.numero}?</div>
      <div class="sr-card-back" id="sr-sm-back">${escHtml(s.enunciado)}${s.observacao ? '<br><br><span style="color:var(--blue);font-size:0.78rem;">💡 ' + escHtml(s.observacao) + '</span>' : ''}</div>
      <button id="sr-sm-reveal-btn" onclick="revealSrSumula()" style="margin-top:10px;background:var(--accent);color:var(--bg);border:none;border-radius:var(--radius-md);padding:8px 16px;font-size:0.82rem;font-weight:600;cursor:pointer;width:100%;">👁 Revelar Enunciado</button>
      <div class="sr-rating-btns" id="sr-sm-rating" style="display:none;">
        <button onclick="rateSrSumula(0)" style="background:#f38ba8;">Esqueci</button>
        <button onclick="rateSrSumula(2)" style="background:#fab387;">Difícil</button>
        <button onclick="rateSrSumula(3)" style="background:#f9e2af;color:#1e1e2e;">Ok</button>
        <button onclick="rateSrSumula(4)" style="background:#a6e3a1;color:#1e1e2e;">Bom</button>
        <button onclick="rateSrSumula(5)" style="background:#a6e3a1;color:#1e1e2e;">Fácil</button>
      </div>
    </div>`;
}

function revealSrSumula() {
  document.getElementById('sr-sm-back').classList.add('visible');
  document.getElementById('sr-sm-reveal-btn').style.display = 'none';
  document.getElementById('sr-sm-rating').style.display = 'flex';
}
window.revealSrSumula = revealSrSumula;

async function rateSrSumula(quality) {
  const s = srSumulas[srSmIdx];
  try {
    const res = await fetch(`/api/sumulas/${s.id}/review-sm2`, {
      method: 'POST', headers, body: JSON.stringify({ quality })
    });
    if (res.ok) {
      srSessionMetrics.sumulas++;
      if (quality >= 3) srSessionMetrics.acertos++;
      updateSessionStats();
    } else {
      console.error('Sumula review failed:', res.status);
    }
  } catch (e) { console.error('Sumula review error:', e); }
  srSmIdx++;
  showSrSumula();
}
window.rateSrSumula = rateSrSumula;

// --- PDF READER ---

async function loadSrPdfs() {
  const container = document.getElementById('sr-pdf-container');
  try {
    const res = await fetch('/api/tree', { headers });
    if (!res.ok) { container.innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem;text-align:center;padding:20px;">Nenhum PDF encontrado. Faça upload primeiro.</div>'; return; }
    const tree = await res.json();
    const pdfs = extractPdfs(tree);
    if (pdfs.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem;text-align:center;padding:20px;">Nenhum PDF encontrado.</div>';
      return;
    }
    container.innerHTML = `
      <div style="max-height:200px;overflow-y:auto;margin-bottom:8px;">
        ${pdfs.slice(0, 20).map(p => `<div class="sr-pdf-item" onclick="openSrPdf('${escHtml(p)}')">
          <span>📄</span>
          <span style="font-size:0.82rem;color:var(--text);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtml(p.split('/').pop())}</span>
          <span style="font-size:0.68rem;color:var(--text-muted);">Abrir</span>
        </div>`).join('')}
      </div>
      <div id="sr-pdf-viewer" style="display:none;">
        <iframe id="sr-pdf-iframe" style="width:100%;height:500px;border:1px solid var(--border);border-radius:var(--radius-md);background:white;"></iframe>
        <button onclick="closeSrPdf()" style="margin-top:6px;background:var(--red);color:var(--bg);border:none;border-radius:var(--radius-md);padding:6px 14px;font-size:0.78rem;cursor:pointer;">✕ Fechar PDF</button>
      </div>`;
  } catch (e) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem;text-align:center;padding:20px;">Erro ao carregar PDFs</div>';
  }
}

function extractPdfs(tree, prefix = '') {
  let pdfs = [];
  if (Array.isArray(tree)) {
    for (const node of tree) {
      if (node.type === 'pdf' || (node.name && node.name.endsWith('.pdf'))) {
        pdfs.push(prefix ? prefix + '/' + node.name : node.name);
      } else if (node.children) {
        pdfs = pdfs.concat(extractPdfs(node.children, prefix ? prefix + '/' + node.name : node.name));
      }
    }
  } else if (tree && tree.children) {
    pdfs = extractPdfs(tree.children, tree.name || '');
  }
  return pdfs;
}

function openSrPdf(path) {
  const viewer = document.getElementById('sr-pdf-viewer');
  const iframe = document.getElementById('sr-pdf-iframe');
  iframe.src = `/viewer.html?file=${encodeURIComponent(path)}`;
  viewer.style.display = 'block';
}
window.openSrPdf = openSrPdf;

function closeSrPdf() {
  document.getElementById('sr-pdf-viewer').style.display = 'none';
  document.getElementById('sr-pdf-iframe').src = '';
}
window.closeSrPdf = closeSrPdf;

// ============================================================
// COMMITMENT CONTRACT
// ============================================================

async function submitCommitment() {
  if (!currentRoom) return;
  const commitment = document.getElementById('commitment-input').value.trim();
  const xp_stake = parseInt(document.getElementById('commitment-xp').value) || 50;
  if (!commitment) { toast('Digite seu compromisso', 'warning'); return; }
  try {
    await apiPost(`/commitment/${currentRoom}`, { commitment, xp_stake });
    document.getElementById('commitment-input').value = '';
    loadCommitments();
  } catch (e) { toast('Erro: ' + e.message, 'error'); }
}
window.submitCommitment = submitCommitment;

async function loadCommitments() {
  if (!currentRoom) return;
  try {
    const data = await apiGet(`/commitment/${currentRoom}`);
    const el = document.getElementById('commitment-display');
    if (!data.commitments || data.commitments.length === 0) {
      el.innerHTML = '<div style="font-size:0.78rem;color:var(--text-muted);">Nenhum compromisso ainda. Seja o primeiro!</div>';
      return;
    }
    el.innerHTML = data.commitments.map(c => {
      const status = c.cumprida === null ? '⏳' : c.cumprida ? '✅' : '❌';
      return `<div style="display:flex;align-items:center;gap:8px;padding:6px;background:var(--bg);border-radius:var(--radius-md);margin-bottom:4px;">
        <span>${status}</span>
        <div style="flex:1;font-size:0.8rem;color:var(--text);">${escHtml(c.nome)}: ${escHtml(c.commitment)}</div>
        <span style="font-size:0.7rem;color:var(--yellow);font-weight:700;">${c.xp_stake}XP</span>
        ${c.is_mine && c.cumprida === null ? `<button onclick="resolveCommitment(true)" style="font-size:0.65rem;background:var(--green);color:var(--bg);border:none;border-radius:4px;padding:2px 6px;cursor:pointer;">✓</button><button onclick="resolveCommitment(false)" style="font-size:0.65rem;background:var(--red);color:var(--bg);border:none;border-radius:4px;padding:2px 6px;cursor:pointer;">✗</button>` : ''}
      </div>`;
    }).join('');
  } catch (e) { /* ignore */ }
}

async function resolveCommitment(cumprida) {
  if (!currentRoom) return;
  try {
    const data = await apiPost(`/commitment/${currentRoom}/resolve`, { cumprida });
    if (data.xp_change > 0) await alertModal(`🎉 +${data.xp_change} XP! Compromisso cumprido!`, { type: 'success' });
    else await alertModal(`😞 ${data.xp_change} XP. Tente cumprir na próxima!`, { type: 'warning' });
    loadCommitments();
  } catch (e) { toast('Erro: ' + e.message, 'error'); }
}
window.resolveCommitment = resolveCommitment;

// ============================================================
// FOCUS SCORE
// ============================================================

async function loadFocusScore() {
  if (!currentRoom) return;
  try {
    const data = await apiGet(`/focus-score/${currentRoom}`);
    document.getElementById('focus-score-value').textContent = data.score;
    document.getElementById('focus-score-value').style.color =
      data.score >= 80 ? 'var(--green)' : data.score >= 50 ? 'var(--yellow)' : 'var(--red)';
    document.getElementById('focus-score-nivel').textContent = `Nível: ${data.nivel}`;
    const bd = data.breakdown;
    document.getElementById('focus-score-breakdown').innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;">
        <span>⏱ Foco: ${bd.pct_tempo_focando}%</span>
        <span>🍅 Ciclos: ${bd.ciclos_completos}</span>
        <span>🃏 Cards: ${bd.cards_revisados}</span>
        <span>🎯 Meta: ${bd.meta_definida ? '✓' : '✗'}</span>
      </div>`;
    if (data.dicas.length > 0) {
      document.getElementById('focus-score-dicas').innerHTML = data.dicas.map(d =>
        `<div style="color:var(--blue);margin-bottom:2px;">${d}</div>`
      ).join('');
    }
  } catch (e) { /* ignore */ }
}

// ============================================================
// ELABORATION PROMPTS
// ============================================================

let elaborationShownCycle = 0;

async function showElaborationPrompt() {
  try {
    const data = await apiGet('/elaboration-prompt');
    document.getElementById('elaboration-prompt').textContent = data.prompt;
    document.getElementById('elaboration-section').classList.remove('hidden');
    document.getElementById('elaboration-response').value = '';
  } catch (e) { /* ignore */ }
}

function dismissElaboration() {
  document.getElementById('elaboration-section').classList.add('hidden');
}
window.dismissElaboration = dismissElaboration;

// ============================================================
// MINDFULNESS BREAK
// ============================================================

let mindfulnessData = null;
let mindfulnessInterval = null;

async function loadMindfulness() {
  try {
    const res = await fetch('/api/studyroom/mindfulness', { headers });
    if (res.ok) mindfulnessData = await res.json();
  } catch (e) { /* ignore */ }
}

function showMindfulness() {
  document.getElementById('mindfulness-section').classList.remove('hidden');
  document.getElementById('mindfulness-instruction').textContent = '🧘 Pronto para relaxar?';
  document.getElementById('mindfulness-timer').textContent = '';
}

function startMindfulness() {
  if (!mindfulnessData) { loadMindfulness(); return; }
  let stepIdx = 0;
  let stepTime = 0;
  const steps = mindfulnessData.passos;

  function tick() {
    if (stepIdx >= steps.length) {
      document.getElementById('mindfulness-instruction').textContent = mindfulnessData.mensagem_motivacional;
      document.getElementById('mindfulness-timer').textContent = '✨';
      clearInterval(mindfulnessInterval);
      setTimeout(() => document.getElementById('mindfulness-section').classList.add('hidden'), 5000);
      return;
    }
    const step = steps[stepIdx];
    document.getElementById('mindfulness-instruction').textContent = step.instrucao;
    document.getElementById('mindfulness-timer').textContent = step.duracao_seg - stepTime + 's';
    stepTime++;
    if (stepTime > step.duracao_seg) { stepIdx++; stepTime = 0; }
  }
  tick();
  mindfulnessInterval = setInterval(tick, 1000);
}
window.startMindfulness = startMindfulness;

// ============================================================
// CHALLENGE MODE (BOSS FIGHT)
// ============================================================

let challengeId = null;
let challengeQuestoes = [];
let challengeIdx = 0;
let bossHpMax = 0;
let bossHpAtual = 0;

async function startChallenge() {
  if (!currentRoom) return;
  const materia = document.getElementById('challenge-materia').value.trim();
  const quantidade = parseInt(document.getElementById('challenge-qty').value) || 10;
  try {
    const data = await apiPost(`/challenge/${currentRoom}/start`, { materia, quantidade, tempo_limite_min: 15 });
    challengeId = data.challenge_id;
    challengeQuestoes = data.questoes;
    challengeIdx = 0;
    bossHpMax = data.boss_hp;
    bossHpAtual = data.boss_hp;
    document.getElementById('challenge-setup').classList.add('hidden');
    document.getElementById('challenge-active').classList.remove('hidden');
    document.getElementById('challenge-section').classList.remove('hidden');
    updateBossHP();
    showChallengeQuestion();
  } catch (e) { toast('Erro: ' + e.message, 'error'); }
}
window.startChallenge = startChallenge;

function updateBossHP() {
  const pct = (bossHpAtual / bossHpMax) * 100;
  document.getElementById('boss-hp-bar').style.width = pct + '%';
  document.getElementById('boss-hp-text').textContent = `${bossHpAtual}/${bossHpMax} HP`;
}

function showChallengeQuestion() {
  if (challengeIdx >= challengeQuestoes.length || bossHpAtual <= 0) {
    const won = bossHpAtual <= 0;
    document.getElementById('challenge-question').innerHTML = won
      ? `<div style="text-align:center;font-size:1.2rem;color:var(--green);font-weight:700;">🎉 Boss derrotado! Parabéns!</div>`
      : `<div style="text-align:center;font-size:1rem;color:var(--yellow);">⏱ Questões acabaram. Boss sobreviveu com ${bossHpAtual} HP.</div>`;
    return;
  }
  const q = challengeQuestoes[challengeIdx];
  const alts = ['A', 'B', 'C', 'D', 'E'].filter(l => q['alternativa_' + l.toLowerCase()]);
  document.getElementById('challenge-question').innerHTML = `
    <div style="font-size:0.82rem;color:var(--text);margin-bottom:8px;">${escHtml(q.enunciado)}</div>
    <div style="display:grid;gap:4px;">
      ${alts.map(l => `<button onclick="answerChallenge('${l}')" style="text-align:left;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-md);padding:8px 12px;color:var(--text);font-size:0.8rem;cursor:pointer;">${l}) ${escHtml(q['alternativa_' + l.toLowerCase()])}</button>`).join('')}
    </div>
  `;
}

async function answerChallenge(resposta) {
  if (!currentRoom || !challengeId) return;
  const q = challengeQuestoes[challengeIdx];
  try {
    const data = await apiPost(`/challenge/${currentRoom}/answer`, { challenge_id: challengeId, questao_id: q.id, resposta });
    bossHpAtual = data.boss_hp_atual;
    updateBossHP();
    challengeIdx++;
    if (data.derrotado) {
      document.getElementById('challenge-question').innerHTML = `<div style="text-align:center;font-size:1.2rem;color:var(--green);font-weight:700;">🎉 Boss derrotado! +${data.xp_ganho} XP!</div>`;
    } else {
      // Flash feedback
      const color = data.acertou ? 'var(--green)' : 'var(--red)';
      const msg = data.acertou ? '✓ Acertou! -1 HP' : '✗ Errou!';
      document.getElementById('challenge-question').innerHTML = `<div style="text-align:center;color:${color};font-weight:700;font-size:0.9rem;">${msg}</div>`;
      setTimeout(showChallengeQuestion, 800);
    }
  } catch (e) { toast('Erro: ' + e.message, 'error'); }
}
window.answerChallenge = answerChallenge;

// ============================================================
// PEER ACCOUNTABILITY NUDGE
// ============================================================

async function sendNudge(targetUserId) {
  if (!currentRoom) return;
  try {
    await apiPost(`/nudge/${currentRoom}/${targetUserId}`, {});
    pollRoom();
  } catch (e) { toast(e.message, 'error'); }
}
window.sendNudge = sendNudge;

// ============================================================
// COLLABORATIVE DISCUSSION
// ============================================================

function showNewDiscussion() {
  document.getElementById('new-discussion-form').classList.toggle('hidden');
}
window.showNewDiscussion = showNewDiscussion;

async function submitDiscussion() {
  if (!currentRoom) return;
  const enunciado = document.getElementById('disc-enunciado').value.trim();
  const materia = document.getElementById('disc-materia').value.trim();
  const alternativas = [
    document.getElementById('disc-alt-a').value.trim(),
    document.getElementById('disc-alt-b').value.trim(),
    document.getElementById('disc-alt-c').value.trim(),
    document.getElementById('disc-alt-d').value.trim(),
  ].filter(a => a);
  const resposta_correta = document.getElementById('disc-correta').value;
  if (!enunciado) { toast('Digite o enunciado', 'warning'); return; }
  try {
    await apiPost(`/discussion/${currentRoom}/start`, { enunciado, alternativas, resposta_correta, materia });
    document.getElementById('new-discussion-form').classList.add('hidden');
    document.getElementById('disc-enunciado').value = '';
    document.getElementById('disc-materia').value = '';
    document.getElementById('disc-alt-a').value = '';
    document.getElementById('disc-alt-b').value = '';
    document.getElementById('disc-alt-c').value = '';
    document.getElementById('disc-alt-d').value = '';
    loadDiscussions();
  } catch (e) { toast('Erro: ' + e.message, 'error'); }
}
window.submitDiscussion = submitDiscussion;

async function loadDiscussions() {
  if (!currentRoom) return;
  try {
    const data = await apiGet(`/discussion/${currentRoom}`);
    const el = document.getElementById('discussion-list');
    if (!data.discussions || data.discussions.length === 0) {
      el.innerHTML = '<div style="font-size:0.78rem;color:var(--text-muted);text-align:center;padding:8px;">Nenhuma discussão ativa. Inicie um debate!</div>';
      return;
    }
    el.innerHTML = data.discussions.map(d => {
      const statusBadge = d.status === 'aberta' ? '🟢 Aberta' : '🔒 Revelada';
      const altHtml = d.alternativas ? d.alternativas.map((a, i) =>
        `<div style="font-size:0.78rem;color:var(--text-sub);">${String.fromCharCode(65+i)}) ${escHtml(a)}</div>`
      ).join('') : '';
      const responsesHtml = d.responses.map(r =>
        `<div style="background:var(--bg-surface);border-radius:var(--radius-md);padding:6px 8px;margin-top:4px;">
          <div style="font-size:0.72rem;color:var(--accent);font-weight:600;">${escHtml(r.nome)} → ${r.resposta}</div>
          <div style="font-size:0.75rem;color:var(--text);">${escHtml(r.justificativa)}</div>
          ${r.comments.map(c => `<div style="margin-left:12px;font-size:0.7rem;color:var(--text-sub);margin-top:2px;">${c.concordo ? '👍' : '👎'} ${escHtml(c.nome)}: ${escHtml(c.comentario)}</div>`).join('')}
        </div>`
      ).join('');
      const correctHtml = d.status === 'revelada' && d.resposta_correta
        ? `<div style="margin-top:6px;padding:6px;background:rgba(166,227,161,0.15);border-radius:var(--radius-md);font-size:0.8rem;color:var(--green);font-weight:600;">✓ Resposta: ${d.resposta_correta}</div>` : '';
      return `<div style="background:var(--bg);border-radius:var(--radius-lg);padding:12px;margin-bottom:8px;border:1px solid var(--border);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <span style="font-size:0.72rem;color:var(--blue);">${d.materia || 'Geral'} • ${statusBadge}</span>
          ${d.status === 'aberta' ? `<button onclick="respondDiscussion(${d.id})" style="font-size:0.68rem;background:var(--accent);color:var(--bg);border:none;border-radius:4px;padding:2px 8px;cursor:pointer;">Responder</button>` : ''}
        </div>
        <div style="font-size:0.85rem;color:var(--text);margin-bottom:6px;">${escHtml(d.enunciado)}</div>
        ${altHtml}
        ${responsesHtml}
        ${correctHtml}
        ${d.status === 'aberta' ? `<button onclick="revealDiscussion(${d.id})" style="margin-top:6px;font-size:0.68rem;background:var(--green);color:var(--bg);border:none;border-radius:4px;padding:2px 8px;cursor:pointer;">Revelar Resposta</button>` : ''}
      </div>`;
    }).join('');
  } catch (e) { /* ignore */ }
}

async function respondDiscussion(discId) {
  const resposta = await promptModal('Sua resposta (letra ou texto):', { title: 'Responder' });
  if (!resposta) return;
  const justificativa = await promptModal('Justifique sua resposta:', { title: 'Justificativa', multiline: true }) || '';
  try {
    await apiPost(`/discussion/${currentRoom}/respond`, { discussion_id: discId, resposta, justificativa });
    loadDiscussions();
  } catch (e) { toast('Erro: ' + e.message, 'error'); }
}
window.respondDiscussion = respondDiscussion;

async function revealDiscussion(discId) {
  try {
    await apiPost(`/discussion/${currentRoom}/reveal`, { discussion_id: discId });
    loadDiscussions();
  } catch (e) { toast('Erro: ' + e.message, 'error'); }
}
window.revealDiscussion = revealDiscussion;

// ============================================================
// SESSION INTENTION
// ============================================================

async function submitIntention() {
  if (!currentRoom) return;
  const intencao = document.getElementById('intention-input').value.trim();
  const como = document.getElementById('intention-how').value.trim();
  if (!intencao) { toast('Defina sua intenção', 'warning'); return; }
  try {
    await apiPost(`/intention/${currentRoom}`, { intencao, como_vou_estudar: como });
    document.getElementById('intention-form').classList.add('hidden');
    document.getElementById('intention-display').innerHTML = `
      <div style="background:var(--bg);border-radius:var(--radius-md);padding:10px;">
        <div style="font-size:0.82rem;color:var(--text);font-weight:600;">🎯 ${escHtml(intencao)}</div>
        ${como ? `<div style="font-size:0.75rem;color:var(--text-sub);margin-top:4px;">📝 ${escHtml(como)}</div>` : ''}
      </div>`;
  } catch (e) { toast('Erro: ' + e.message, 'error'); }
}
window.submitIntention = submitIntention;

// ============================================================
// INIT
// ============================================================

// Request notification permission
if ('Notification' in window && Notification.permission === 'default') {
  Notification.requestPermission();
}
loadMinhasSalas();
loadGoalSuggestion();
loadMindfulness();

// Ensure study tab buttons work via event delegation (fallback for onclick)
document.getElementById('study-tabs')?.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-tab]');
  if (btn) switchStudyTab(btn.dataset.tab);
});

// ============================================================
// BREAK CARDS: Micro-Retrieval during Pomodoro breaks
// ============================================================

let breakCardsLoaded = false;

async function loadBreakCards() {
  if (breakCardsLoaded) return;
  try {
    const materia = document.getElementById('input-goal-criar')?.value?.trim() || '';
    const url = `/api/studyroom/break-cards?quantidade=5${materia ? '&materia=' + encodeURIComponent(materia) : ''}`;
    const res = await fetch(url, { headers });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.cards || data.cards.length === 0) return;

    const container = document.getElementById('break-cards-container');
    container.innerHTML = data.cards.map((card, i) => {
      const question = card.tipo === 'sumula'
        ? `🏛️ ${card.tribunal} — Súmula nº ${card.numero}: Qual é o enunciado?`
        : `🃏 ${escHtml(card.pergunta)}`;
      const answer = card.tipo === 'sumula'
        ? escHtml(card.enunciado)
        : escHtml(card.resposta);
      const meta = card.tipo === 'sumula'
        ? `${card.tribunal} • ${card.tema || 'Geral'}`
        : `${card.materia || 'Geral'}`;
      return `<div class="break-card">
        <div class="break-card-question">${question}</div>
        <button class="break-card-reveal" id="reveal-btn-${i}" onclick="revealBreakCard(${i})">👁 Revelar</button>
        <div class="break-card-answer" id="break-answer-${i}">${answer}</div>
        <div class="break-card-meta">${meta} • Intervalo: ${card.intervalo_dias || 1}d</div>
      </div>`;
    }).join('');

    document.getElementById('break-cards-count').textContent =
      `${data.cards.length} cards • ${data.total_pendentes} pendentes hoje`;
    breakCardsLoaded = true;
  } catch (e) {
    console.error('Break cards error:', e);
  }
}

function revealBreakCard(idx) {
  const answer = document.getElementById('break-answer-' + idx);
  const btn = document.getElementById('reveal-btn-' + idx);
  if (answer) { answer.classList.add('revealed'); }
  if (btn) { btn.style.display = 'none'; }
}
window.revealBreakCard = revealBreakCard;

function showBreakCards() {
  document.getElementById('break-cards-section')?.classList.remove('hidden');
  loadBreakCards();
}

function hideBreakCards() {
  document.getElementById('break-cards-section')?.classList.add('hidden');
}

// ============================================================
// SESSION SUMMARY: Modal when leaving room
// ============================================================

async function showSessionSummary() {
  if (!currentRoom) return;
  try {
    const res = await fetch(`/api/studyroom/session-summary/${currentRoom}`, { headers });
    if (!res.ok) return;
    const data = await res.json();

    const s = data.sessao;
    const p = data.progresso;
    const pendentes = data.pendentes;

    const medal = p.ranking_posicao === 1 ? '🥇' : p.ranking_posicao === 2 ? '🥈' : p.ranking_posicao === 3 ? '🥉' : `#${p.ranking_posicao}`;

    let html = `
      <div style="text-align:center;margin-bottom:16px;">
        <div style="font-size:2rem;font-weight:800;color:var(--green);">${s.tempo_focado_min} min</div>
        <div style="font-size:0.78rem;color:var(--text-sub);">de estudo focado</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px;">
        <div style="text-align:center;background:var(--bg);border-radius:var(--radius-md);padding:10px;">
          <div style="font-size:1.2rem;font-weight:700;color:var(--yellow);">${s.ciclos_completados}/${s.ciclos_total}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Ciclos</div>
        </div>
        <div style="text-align:center;background:var(--bg);border-radius:var(--radius-md);padding:10px;">
          <div style="font-size:1.2rem;font-weight:700;color:var(--accent);">${p.xp_ganho}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">XP ganho</div>
        </div>
        <div style="text-align:center;background:var(--bg);border-radius:var(--radius-md);padding:10px;">
          <div style="font-size:1.2rem;font-weight:700;color:var(--blue);">${medal}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Ranking</div>
        </div>
      </div>
      <div style="background:var(--bg);border-radius:var(--radius-md);padding:12px;margin-bottom:12px;">
        <div style="font-size:0.78rem;font-weight:600;color:var(--text);margin-bottom:6px;">📚 Revisões hoje</div>
        <div style="display:flex;gap:12px;font-size:0.8rem;color:var(--text-sub);">
          <span>🃏 ${p.flashcards_revisados} flashcards</span>
          <span>⚖️ ${p.sumulas_revisadas} súmulas</span>
          <span>❓ ${p.questoes_resolvidas} questões</span>
        </div>
      </div>`;

    if (data.meta.texto) {
      html += `<div style="background:var(--bg);border-radius:var(--radius-md);padding:12px;margin-bottom:12px;">
        <div style="font-size:0.78rem;font-weight:600;color:var(--text);">🎯 Meta: ${escHtml(data.meta.texto)}</div>
      </div>`;
    }

    if (pendentes.flashcards > 0 || pendentes.sumulas > 0) {
      html += `<div style="background:rgba(249,226,175,0.1);border:1px solid var(--yellow);border-radius:var(--radius-md);padding:10px;margin-bottom:12px;font-size:0.78rem;color:var(--yellow);">
        ⚠️ Ainda pendentes: ${pendentes.flashcards} flashcards + ${pendentes.sumulas} súmulas para hoje
      </div>`;
    }

    if (data.sugestoes.length > 0) {
      html += `<div style="margin-top:8px;"><div style="font-size:0.78rem;font-weight:600;color:var(--text);margin-bottom:6px;">💡 Sugestões</div>`;
      html += data.sugestoes.map(s => `<div style="font-size:0.75rem;color:var(--text-sub);margin-bottom:4px;">${s}</div>`).join('');
      html += '</div>';
    }

    document.getElementById('session-summary-content').innerHTML = html;
    document.getElementById('session-summary-modal').classList.remove('hidden');
    document.getElementById('session-summary-modal').style.display = 'flex';
  } catch (e) {
    console.error('Summary error:', e);
  }
}

function closeSummaryModal() {
  document.getElementById('session-summary-modal').classList.add('hidden');
  document.getElementById('session-summary-modal').style.display = 'none';
}
window.closeSummaryModal = closeSummaryModal;

// ============================================================
// GOAL SUGGESTION: SMART goals from ROI (shown in lobby)
// ============================================================

async function loadGoalSuggestion() {
  try {
    const res = await fetch('/api/studyroom/goal-suggestion', { headers });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.sugestao) return;

    const goalInput = document.getElementById('input-goal-criar');
    if (!goalInput) return;

    // Insert suggestion below input
    const existing = document.getElementById('goal-suggestion-box');
    if (existing) existing.remove();

    const div = document.createElement('div');
    div.id = 'goal-suggestion-box';
    div.className = 'goal-suggestion';
    div.innerHTML = `
      <div class="goal-suggestion-text">💡 ${data.sugestao.meta}</div>
      <div class="goal-suggestion-why">${data.motivo}</div>
      <button class="goal-suggestion-btn" onclick="useGoalSuggestion('${escHtml(data.sugestao.meta)}')">Usar esta meta</button>
    `;
    goalInput.parentNode.insertBefore(div, goalInput.nextSibling);
  } catch (e) {
    // Goal suggestion is optional, don't show error
  }
}

function useGoalSuggestion(meta) {
  const input = document.getElementById('input-goal-criar');
  if (input) input.value = meta;
  const box = document.getElementById('goal-suggestion-box');
  if (box) box.style.opacity = '0.5';
}
window.useGoalSuggestion = useGoalSuggestion;

// ============================================================
// ADAPTIVE POMODORO: Integrates fatigue detection
// ============================================================

let adaptiveBreakSuggested = false;

function checkAdaptiveFatigue() {
  // Uses the _adaptivePomo from timer-global.js if available
  if (!window._adaptivePomo) return;

  const answers = window._adaptivePomo.sessionAnswers;
  if (answers.length < 5) return; // Need at least 5 answers to detect

  // Check last 5 answers: if accuracy < 50% or avg tempo > 2x initial
  const last5 = answers.slice(-5);
  const accuracy = last5.filter(a => a.correct).length / last5.length;
  const avgTempo = last5.reduce((s, a) => s + a.tempo_s, 0) / last5.length;

  // Compare with first 5 answers if available
  const first5 = answers.slice(0, 5);
  const initialTempo = first5.reduce((s, a) => s + a.tempo_s, 0) / first5.length;

  const fatigued = accuracy < 0.5 || (initialTempo > 0 && avgTempo > initialTempo * 1.8);

  if (fatigued && !adaptiveBreakSuggested && pomodoroPhase === 'focus') {
    adaptiveBreakSuggested = true;
    // Show suggestion to take a break early
    const timerSection = document.getElementById('timer-section');
    const existingBanner = document.getElementById('fatigue-banner');
    if (existingBanner) existingBanner.remove();

    const banner = document.createElement('div');
    banner.id = 'fatigue-banner';
    banner.style.cssText = 'background:rgba(243,139,168,0.15);border:1px solid var(--red);border-radius:var(--radius-md);padding:10px;margin-top:10px;font-size:0.78rem;color:var(--red);text-align:center;';
    banner.innerHTML = `⚠️ Fadiga detectada (acurácia caiu). Considere antecipar a pausa! <button onclick="this.parentNode.remove()" style="background:none;border:none;color:var(--red);cursor:pointer;font-weight:700;margin-left:8px;">✕</button>`;
    timerSection.appendChild(banner);
  }

  // Reset flag when break starts
  if (pomodoroPhase === 'break') {
    adaptiveBreakSuggested = false;
  }
}


// Check if coming from a link with code
const params = new URLSearchParams(window.location.search);
const code = params.get('code') || params.get('codigo');
if (code) {
  document.getElementById('input-codigo').value = code.toUpperCase();
  entrarSala();
}

// ============================================================
// PROTEÇÃO: Registrar tempo ao fechar aba/navegar para outra página
// ============================================================
window.addEventListener('beforeunload', () => {
  if (currentRoom && myStatus === 'focando') {
    // sendBeacon é mais confiável que fetch em beforeunload
    navigator.sendBeacon(
      `/api/studyroom/status/${currentRoom}`,
      new Blob([JSON.stringify({ status: 'ausente' })], { type: 'application/json' })
    );
  }
});

window.addEventListener('visibilitychange', () => {
  // Quando aba fica hidden por muito tempo (>30min), pausar para evitar tempo inflado
  if (document.hidden && currentRoom && myStatus === 'focando') {
    window._studyroomHiddenAt = Date.now();
  }
  if (!document.hidden && window._studyroomHiddenAt && currentRoom) {
    const hiddenMinutes = (Date.now() - window._studyroomHiddenAt) / 60000;
    if (hiddenMinutes > 30) {
      // Aba ficou oculta > 30min: pausar automaticamente
      fetch(`/api/studyroom/status/${currentRoom}`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ status: 'pausando' })
      }).catch(() => {});
      myStatus = 'pausando';
      updateStatusButtons();
    }
    window._studyroomHiddenAt = null;
  }
});
