// studyroom.js - Extracted from studyroom.html inline script

const API = '/api/studyroom';
const token = localStorage.getItem('auth_token');
const headers = { 'Content-Type': 'application/json' };
if (token) headers['Authorization'] = `Bearer ${token}`;

let currentRoom = null;
let pollInterval = null;
let pomodoroTimer = null;
let pomodoroSeconds = 0;
let pomodoroPhase = 'focus'; // 'focus' or 'break'
let pomodoroPaused = false;
let myStatus = 'focando';

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

    const data = await apiPost('/criar', { titulo, tecnica, duracao_min, max_participantes });
    currentRoom = data.codigo;
    enterRoomView(data.codigo);
  } catch (e) {
    alert('Erro ao criar sala: ' + e.message);
  }
}
window.criarSala = criarSala;

// ============================================================
// ENTRAR SALA
// ============================================================

async function entrarSala() {
  try {
    const codigo = document.getElementById('input-codigo').value.trim().toUpperCase();
    if (!codigo) return alert('Digite o código da sala');
    await apiPost('/entrar', { codigo });
    currentRoom = codigo;
    enterRoomView(codigo);
  } catch (e) {
    alert('Erro: ' + e.message);
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
  updateStatusButtons();
  startPolling();
  startPomodoro();
}

function sairSala() {
  stopPolling();
  stopPomodoro();
  currentRoom = null;
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

  // Participants
  const grid = document.getElementById('participants-grid');
  grid.innerHTML = data.participantes.map(p => {
    const statusIcon = p.status === 'focando' ? '🟢' : p.status === 'pausando' ? '🟡' : '⚫';
    const tempo = formatTime(p.tempo_estudado);
    const meClass = p.is_me ? ' me' : '';
    return `<div class="participant-card${meClass}">
      <div class="participant-status">${statusIcon}</div>
      <div class="participant-info">
        <div class="participant-name">${escHtml(p.nome)}${p.is_me ? ' (eu)' : ''}</div>
        <div class="participant-time">⏱️ ${tempo}</div>
      </div>
    </div>`;
  }).join('');

  // Stats
  document.getElementById('stat-participantes').textContent = data.participantes.length;
  document.getElementById('stat-focando').textContent = data.participantes.filter(p => p.status === 'focando').length;
  const totalSeg = data.participantes.reduce((sum, p) => sum + (p.tempo_estudado || 0), 0);
  document.getElementById('stat-total-tempo').textContent = formatTime(totalSeg);

  // Chat
  renderChat(data.chat_messages);

  // Timer phase label (for pomodoro)
  if (data.tecnica === 'livre') {
    document.getElementById('timer-phase').textContent = '⏱️ LIVRE';
    document.getElementById('timer-phase').className = 'timer-phase focus';
  }
}

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

function startPomodoro() {
  pomodoroSeconds = 0;
  pomodoroPhase = 'focus';
  pomodoroPaused = false;
  updateTimerDisplay();
  pomodoroTimer = setInterval(tickPomodoro, 1000);
}

function stopPomodoro() {
  if (pomodoroTimer) clearInterval(pomodoroTimer);
  pomodoroTimer = null;
}

function tickPomodoro() {
  if (myStatus === 'ausente') return; // don't tick when absent

  pomodoroSeconds++;

  // Pomodoro cycle: 25min focus, 5min break
  const focusDuration = 25 * 60;
  const breakDuration = 5 * 60;
  const cycleDuration = focusDuration + breakDuration;
  const posInCycle = pomodoroSeconds % cycleDuration;

  if (posInCycle < focusDuration) {
    if (pomodoroPhase !== 'focus') {
      pomodoroPhase = 'focus';
      document.getElementById('timer-phase').textContent = '🍅 FOCO';
      document.getElementById('timer-phase').className = 'timer-phase focus';
      // Auto-set status
      if (myStatus === 'pausando') setStatus('focando');
    }
  } else {
    if (pomodoroPhase !== 'break') {
      pomodoroPhase = 'break';
      document.getElementById('timer-phase').textContent = '☕ PAUSA';
      document.getElementById('timer-phase').className = 'timer-phase break';
      // Notify
      if (Notification.permission === 'granted') {
        new Notification('☕ Hora da pausa!', { body: '5 minutos de descanso.' });
      }
    }
  }

  updateTimerDisplay();
}

function updateTimerDisplay() {
  const focusDuration = 25 * 60;
  const breakDuration = 5 * 60;
  const cycleDuration = focusDuration + breakDuration;
  const posInCycle = pomodoroSeconds % cycleDuration;

  let remaining;
  if (pomodoroPhase === 'focus') {
    remaining = focusDuration - posInCycle;
  } else {
    remaining = cycleDuration - posInCycle;
  }

  const min = Math.floor(remaining / 60);
  const sec = remaining % 60;
  document.getElementById('timer-display').textContent =
    String(min).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
}

// ============================================================
// CHAT
// ============================================================

async function enviarMsg() {
  const input = document.getElementById('chat-input');
  const mensagem = input.value.trim();
  if (!mensagem || !currentRoom) return;
  input.value = '';
  try {
    await apiPost(`/chat/${currentRoom}`, { mensagem });
    pollRoom(); // refresh immediately
  } catch (e) {
    alert('Erro: ' + e.message);
  }
}
window.enviarMsg = enviarMsg;

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
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ============================================================
// INIT
// ============================================================

// Request notification permission
if ('Notification' in window && Notification.permission === 'default') {
  Notification.requestPermission();
}
loadMinhasSalas();

// Check if coming from a link with code
const params = new URLSearchParams(window.location.search);
const code = params.get('code') || params.get('codigo');
if (code) {
  document.getElementById('input-codigo').value = code.toUpperCase();
  entrarSala();
}
