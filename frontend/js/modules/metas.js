// ==================== TAB 5: METAS ====================
import { toast } from './utils.js';

export async function loadMetas() {
  try {
    const data = await fetch('/api/metas').then(r => r.json());
    const cfg = data.config;
    const prog = data.progresso;
    const metaHoras = document.getElementById('meta-horas');
    const metaQuestoes = document.getElementById('meta-questoes');
    const metaFlashcards = document.getElementById('meta-flashcards');
    const metaPaginas = document.getElementById('meta-paginas');
    if (metaHoras) metaHoras.value = cfg.meta_horas;
    if (metaQuestoes) metaQuestoes.value = cfg.meta_questoes;
    if (metaFlashcards) metaFlashcards.value = cfg.meta_flashcards;
    if (metaPaginas) metaPaginas.value = cfg.meta_paginas;
    const progEl = document.getElementById('metas-progresso');
    const items = [
      { icon: '⏱', label: 'Horas', val: (prog.horas || 0).toFixed(1), meta: cfg.meta_horas, pct: Math.min(100, ((prog.horas || 0) / cfg.meta_horas) * 100), color: '#89b4fa' },
      { icon: '❓', label: 'Questões', val: prog.questoes || 0, meta: cfg.meta_questoes, pct: Math.min(100, ((prog.questoes || 0) / cfg.meta_questoes) * 100), color: '#a6e3a1' },
      { icon: '🧠', label: 'Flashcards', val: prog.flashcards || 0, meta: cfg.meta_flashcards, pct: Math.min(100, ((prog.flashcards || 0) / cfg.meta_flashcards) * 100), color: '#cba6f7' },
    ];
    if (progEl) {
      progEl.innerHTML = items.map(m => `
        <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #45475a;">
          <span style="font-size:1.2rem;">${m.icon}</span>
          <span style="min-width:80px;font-size:0.88rem;">${m.label}</span>
          <div style="flex:1;height:8px;background:#45475a;border-radius:4px;overflow:hidden;"><div style="height:100%;width:${m.pct}%;background:${m.color};border-radius:4px;"></div></div>
          <span style="font-size:0.85rem;font-weight:700;color:${m.color};min-width:70px;text-align:right;">${m.val}/${m.meta}</span>
        </div>
      `).join('');
    }
    const dotH = document.getElementById('meta-dot-h');
    const dotQ = document.getElementById('meta-dot-q');
    const dotF = document.getElementById('meta-dot-f');
    if (dotH) dotH.className = 'meta-dot' + (items[0].pct >= 100 ? ' done' : items[0].pct > 0 ? ' partial' : '');
    if (dotQ) dotQ.className = 'meta-dot' + (items[1].pct >= 100 ? ' done' : items[1].pct > 0 ? ' partial' : '');
    if (dotF) dotF.className = 'meta-dot' + (items[2].pct >= 100 ? ' done' : items[2].pct > 0 ? ' partial' : '');
  } catch (e) { /* Silently handle */ }
}

export async function salvarMetas() {
  try {
    await fetch('/api/metas', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      meta_horas: parseFloat(document.getElementById('meta-horas').value),
      meta_questoes: parseInt(document.getElementById('meta-questoes').value),
      meta_flashcards: parseInt(document.getElementById('meta-flashcards').value),
      meta_paginas: parseInt(document.getElementById('meta-paginas').value),
    }) });
    toast('Metas salvas!', 'success');
    loadMetas();
  } catch (e) {
    toast('Erro ao salvar metas', 'error');
  }
}

// Configurações de sessão (localStorage)
export function getConfigSessoes() {
  const raw = localStorage.getItem('config_sessoes');
  if (raw) try { return JSON.parse(raw); } catch(e) {}
  return { questoes_dia: 10, flashcards_sessao: 15, pomodoro_min: 25 };
}

export function salvarConfigSessoes() {
  const cfg = {
    questoes_dia: parseInt(document.getElementById('cfg-questoes-dia').value) || 10,
    flashcards_sessao: parseInt(document.getElementById('cfg-flashcards-sessao').value) || 15,
    pomodoro_min: parseInt(document.getElementById('cfg-pomodoro-min').value) || 25,
  };
  localStorage.setItem('config_sessoes', JSON.stringify(cfg));
  toast('Configurações de sessão salvas!', 'success');
}

export function loadConfigSessoes() {
  const cfg = getConfigSessoes();
  const el1 = document.getElementById('cfg-questoes-dia');
  const el2 = document.getElementById('cfg-flashcards-sessao');
  const el3 = document.getElementById('cfg-pomodoro-min');
  if (el1) el1.value = cfg.questoes_dia;
  if (el2) el2.value = cfg.flashcards_sessao;
  if (el3) el3.value = cfg.pomodoro_min;
}

export async function loadStreakBadge() {
  try {
    const data = await fetch('/api/streaks').then(r => r.json());
    document.getElementById('streak-num').textContent = data.streak_atual;
    const streakEl = document.getElementById('metas-streak');
    if (streakEl) {
      streakEl.innerHTML = `
        <div style="display:flex;align-items:center;gap:16px;">
          <span style="font-size:2.5rem;">🔥</span>
          <div><div style="font-size:1.6rem;font-weight:700;color:#fab387;">${data.streak_atual} dias</div><div style="font-size:0.85rem;color:#9399b2;">consecutivos de estudo</div></div>
          <div style="margin-left:auto;text-align:right;"><div style="font-size:1.2rem;font-weight:700;color:#a6e3a1;">${data.melhor_streak}</div><div style="font-size:0.75rem;color:#9399b2;">recorde</div></div>
        </div>
      `;
    }
  } catch (e) { /* Silently fail */ }
}

export function initMetas() {
  loadConfigSessoes();
  loadMetas();
  loadStreakBadge();
}
