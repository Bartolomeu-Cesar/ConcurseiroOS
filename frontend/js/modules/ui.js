// ==================== UI ====================
// PWA, countdown, theme, gamification, notifications, focus mode, accessibility, confetti, onboarding
import { escapeHtml, toast, confirmModal } from './utils.js';
import { openSelectModal } from './modal-selecao.js';

// ==================== PWA ====================
export function initPwa() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
}

// ==================== COUNTDOWN ====================
export async function loadCountdown() {
  try {
    const provas = await fetch('/api/countdown').then(r => r.json());
    if (!provas.length) return;
    const now = new Date();
    const favorito = localStorage.getItem('countdown_favorito');
    const parsed = provas.map(p => {
      let parts = p.data_objetiva.match(/(\d+)[\/\-](\d+)[\/\-](\d+)/);
      if (!parts) return null;
      let d;
      if (parts[3].length === 4) d = new Date(parts[3], parts[2] - 1, parts[1]);
      else d = new Date(parts[1], parts[2] - 1, parts[3]);
      const diff = Math.ceil((d - now) / 86400000);
      return diff > 0 ? { ...p, date: d, days: diff } : null;
    }).filter(Boolean);
    if (!parsed.length) return;
    let selected = null;
    if (favorito) { selected = parsed.find(p => `${p.edital}|${p.cargo}` === favorito); }
    if (!selected) { selected = parsed.sort((a, b) => a.days - b.days)[0]; }
    const el = document.getElementById('countdown-badge');
    if (el) {
      el.innerHTML = `<span class="countdown-icon">⏳</span><span class="countdown-text">${escapeHtml(selected.cargo)}: <strong>${selected.days}d</strong></span><span class="countdown-fav" title="Alterar cargo favorito">⭐</span>`;
      el.onclick = () => showCountdownPicker(parsed);
    }
  } catch (e) {}
}

function showCountdownPicker(provas) {
  openSelectModal('⏳ Escolher prova para countdown', provas.map((p, i) => ({
    icon: '📅', label: `${p.edital} - ${p.cargo}`, sub: `${p.days} dias restantes`, value: i
  })).concat([{ icon: '🔄', label: 'Automático (mais próxima)', sub: 'Seleciona sempre a prova mais próxima', value: -1 }]), (choice) => {
    if (choice.value === -1) { localStorage.removeItem('countdown_favorito'); }
    else { const p = provas[choice.value]; localStorage.setItem('countdown_favorito', `${p.edital}|${p.cargo}`); }
    loadCountdown();
  });
}

// ==================== THEME TOGGLE ====================
export function toggleTheme() {
  const body = document.body;
  body.classList.add('theme-forced');
  const isLight = body.classList.toggle('light-theme');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
  const metaTheme = document.querySelector('meta[name=theme-color]');
  if (metaTheme) metaTheme.content = isLight ? '#eff1f5' : '#1e1e2e';
}

export function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved === 'light') { document.body.classList.add('light-theme', 'theme-forced'); }
  else if (saved === 'dark') { document.body.classList.add('theme-forced'); }
}

// ==================== GAMIFICATION BADGE ====================
export async function loadXpBadge() {
  try {
    const data = await fetch('/api/gamification').then(r => r.json());
    const el = document.getElementById('xp-badge');
    if (el) el.innerHTML = `<span class="xp-level">Lv.${data.nivel}</span><div class="xp-bar-mini"><div class="xp-bar-mini-fill" style="width:${data.pct_nivel}%"></div></div><span style="color:#9399b2;">${data.xp}xp</span>`;
  } catch (e) {}
}

// ==================== BROWSER NOTIFICATIONS ====================
export async function checkNotifications() {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') { Notification.requestPermission(); }
  if (Notification.permission !== 'granted') return;
  try {
    const notifs = await fetch('/api/notificacoes').then(r => r.json());
    if (notifs.length > 0 && !sessionStorage.getItem('notif_shown_today')) {
      const alta = notifs.find(n => n.prioridade === 'alta');
      if (alta) {
        new Notification('ConcurseiroOS', { body: alta.msg, icon: '/icon.svg' });
        sessionStorage.setItem('notif_shown_today', '1');
      }
    }
  } catch (e) {}
}

// ==================== MODO FOCO ====================
export function enterFocusMode(targetTab) {
  if (!targetTab) {
    const options = [
      { tab: 'tab-edital', label: '📋 Edital', desc: 'Estudar tópicos do edital' },
      { tab: 'tab-pdf', label: '📚 Leitor PDF', desc: 'Leitura focada de material' },
      { tab: 'tab-flashcards', label: '🧠 Flashcards', desc: 'Revisão com repetição espaçada' },
      { tab: 'tab-metas', label: '🎯 Metas', desc: 'Acompanhar progresso do dia' },
    ];
    const modal = document.createElement('div');
    modal.id = 'focus-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `<div style="background:#313244;border-radius:16px;padding:24px;max-width:360px;width:90%;">
      <h3 style="color:#cba6f7;margin-bottom:12px;text-align:center;">🎯 Modo Foco</h3>
      <p style="font-size:0.8rem;color:#9399b2;text-align:center;margin-bottom:16px;">Escolha em que deseja focar. Tela cheia, sem distrações.</p>
      ${options.map(o => `<button onclick="document.getElementById('focus-modal').remove();enterFocusMode('${o.tab}')" style="display:block;width:100%;padding:12px;margin-bottom:8px;background:#1e1e2e;border:1px solid #45475a;border-radius:8px;color:#cdd6f4;cursor:pointer;text-align:left;font-size:0.85rem;">
        <strong>${o.label}</strong><br><span style="font-size:0.75rem;color:#9399b2;">${o.desc}</span>
      </button>`).join('')}
      <button onclick="document.getElementById('focus-modal').remove()" style="display:block;width:100%;padding:8px;background:#45475a;border:none;border-radius:6px;color:#cdd6f4;cursor:pointer;margin-top:4px;font-size:0.82rem;">Cancelar</button>
      <p style="font-size:0.7rem;color:#585b70;text-align:center;margin-top:8px;">Dica: do Calendário, use o botão ▶ para iniciar com timer.</p>
    </div>`;
    document.body.appendChild(modal);
    return;
  }
  const el = document.documentElement;
  if (el.requestFullscreen) el.requestFullscreen();
  else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
  document.body.classList.add('focus-mode');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  const tabBtn = document.querySelector(`[data-tab="${targetTab}"]`);
  if (tabBtn) tabBtn.classList.add('active');
  const tabContent = document.getElementById(targetTab);
  if (tabContent) tabContent.classList.add('active');
  document.getElementById('header').style.display = 'none';
  const navLinks = document.querySelector('.nav-links');
  if (navLinks) navLinks.style.display = 'none';
  document.getElementById('tab-bar').style.display = 'none';
  if (!document.getElementById('exit-focus-btn')) {
    const btn = document.createElement('button');
    btn.id = 'exit-focus-btn'; btn.className = 'iobtn';
    btn.style.cssText = 'position:fixed;top:12px;right:12px;z-index:9999;background:#f38ba8;color:#1e1e2e;font-weight:600;';
    btn.textContent = '✕ Sair do Foco';
    btn.onclick = exitFocusMode;
    document.body.appendChild(btn);
  }
}

export function exitFocusMode() {
  if (document.exitFullscreen) document.exitFullscreen();
  else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
  document.body.classList.remove('focus-mode');
  document.getElementById('header').style.display = '';
  document.querySelector('.nav-links').style.display = '';
  document.getElementById('tab-bar').style.display = '';
  const btn = document.getElementById('exit-focus-btn');
  if (btn) btn.remove();
}

// ==================== REVISÃO ESPAÇADA UI ====================
export function initRevisaoEspacada() {
  document.addEventListener('dblclick', async (e) => {
    const leaf = e.target.closest('.tree-leaf');
    if (!leaf) return;
    const id = leaf.dataset.id;
    if (!id) return;
    const ok = await confirmModal('Revisão Espaçada', 'Agendar revisão espaçada para este tópico?', { confirmText: 'Agendar', type: 'info', icon: '🔄' });
    if (ok) {
      const res = await fetch(`/api/edital/${id}/agendar-revisao`, { method: 'POST' }).then(r => r.json());
      toast(`Revisão agendada para: ${res.proxima_revisao} (intervalo: ${res.intervalo} dias)`, 'success');
    }
  });
}

// ==================== ACCESSIBILITY: FOCUS MANAGEMENT ====================
export function trapFocus(element) {
  const focusable = element.querySelectorAll('button, input, textarea, select, a[href], [tabindex]:not([tabindex="-1"])');
  if (focusable.length === 0) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  first.focus();
  element.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    if (e.shiftKey) { if (document.activeElement === first) { e.preventDefault(); last.focus(); } }
    else { if (document.activeElement === last) { e.preventDefault(); first.focus(); } }
  });
}

// ==================== CONFETTI EFFECT ====================
export function launchConfetti(duration = 2000) {
  const canvas = document.createElement('canvas');
  canvas.id = 'confetti-canvas';
  document.body.appendChild(canvas);
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  const colors = ['#a6e3a1', '#f38ba8', '#89b4fa', '#fab387', '#cba6f7', '#f9e2af'];
  const particles = Array.from({ length: 80 }, () => ({
    x: Math.random() * canvas.width, y: Math.random() * canvas.height - canvas.height,
    size: Math.random() * 8 + 4, color: colors[Math.floor(Math.random() * colors.length)],
    speed: Math.random() * 3 + 2, angle: Math.random() * Math.PI * 2, spin: (Math.random() - 0.5) * 0.2
  }));
  const start = Date.now();
  function draw() {
    if (Date.now() - start > duration) { canvas.remove(); return; }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of particles) {
      p.y += p.speed; p.x += Math.sin(p.angle) * 0.5; p.angle += p.spin;
      ctx.fillStyle = p.color;
      ctx.fillRect(p.x, p.y, p.size, p.size * 0.6);
    }
    requestAnimationFrame(draw);
  }
  draw();
}

// ==================== ONBOARDING / FIRST USE ====================
export function checkFirstUse() {
  if (localStorage.getItem('concurseiro_onboarded')) return;
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.style.display = 'flex';
  overlay.id = 'onboarding-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.innerHTML = `
    <div class="modal-box" style="max-width:500px;text-align:center;">
      <div style="font-size:3rem;margin-bottom:12px;">🎓</div>
      <h2 style="color:#cba6f7;margin-bottom:12px;">Bem-vindo ao ConcurseiroOS!</h2>
      <p style="color:#9399b2;margin-bottom:20px;line-height:1.6;">
        Seu sistema completo de estudos para concursos públicos.<br>
        Aqui você pode ler PDFs, gerenciar editais, criar flashcards,<br>
        resolver questões e acompanhar seu progresso.
      </p>
      <div style="text-align:left;background:#1e1e2e;border-radius:8px;padding:16px;margin-bottom:20px;font-size:0.85rem;">
        <div style="margin-bottom:8px;"><strong>🚀 Dicas rápidas:</strong></div>
        <div style="margin-bottom:6px;">• <kbd>Ctrl+K</kbd> — Busca rápida em tópicos</div>
        <div style="margin-bottom:6px;">• <kbd>Alt+1-5</kbd> — Trocar entre abas</div>
        <div style="margin-bottom:6px;">• <kbd>Shift+?</kbd> — Ver todos os atalhos</div>
        <div>• O timer registra horas de estudo automaticamente</div>
      </div>
      <button class="iobtn" style="background:#cba6f7;color:#1e1e2e;padding:10px 32px;font-size:1rem;" onclick="dismissOnboarding()">Começar a Estudar! 💪</button>
    </div>
  `;
  document.body.appendChild(overlay);
  trapFocus(overlay);
}

export function dismissOnboarding() {
  localStorage.setItem('concurseiro_onboarded', '1');
  const el = document.getElementById('onboarding-overlay');
  if (el) el.remove();
  toast('Bons estudos! Use Shift+? para ver os atalhos.', 'info', 5000);
}

export function initUI() {
  initPwa();
  initTheme();
  loadXpBadge();
  loadCountdown();
  setInterval(loadCountdown, 60000);
  setTimeout(checkNotifications, 3000);
  initRevisaoEspacada();
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) exitFocusMode(); });
  setTimeout(checkFirstUse, 500);
}
