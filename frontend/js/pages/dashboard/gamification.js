// gamification.js — Gamification (loadGamification, challenges, achievements, XP, streak-freeze, missoes, share)
import { getCSSVar } from './helpers.js';

export async function loadGamification() {
  const data = await fetch('/api/gamification').then(r => r.json());
  const box = document.getElementById('gamification-box');
  box.innerHTML = `
    <div class="gam-level">
      <span class="level-num">Lv.${data.nivel}</span>
      <div class="level-info">
        <div class="gam-xp-bar"><div class="gam-xp-fill" style="width:${data.pct_nivel}%"></div></div>
        <div class="gam-xp-text">${data.xp_no_nivel} / ${data.xp_para_proximo} XP</div>
      </div>
    </div>
    <div class="gam-stats">
      <div class="gam-stat"><div class="num">${data.xp}</div><div class="lbl">XP Total</div></div>
      <div class="gam-stat"><div class="num">${data.stats.streak}🔥</div><div class="lbl">Streak</div></div>
      <div class="gam-stat"><div class="num">${data.badges_earned.length}/${data.badges_total}</div><div class="lbl">Badges</div></div>
    </div>
    <div class="gam-badges">
      ${data.badges_earned.map(b => `<div class="gam-badge" title="${b.desc}"><span class="badge-icon">${b.icon}</span><span class="badge-name">${b.name}</span></div>`).join('')}
      ${data.badges_earned.length === 0 ? '<span style="color:var(--text-sub);font-size:0.82rem;">Continue estudando para desbloquear badges!</span>' : ''}
    </div>
  `;
}

// ===== CHALLENGE CELEBRATION =====
function showChallengeCelebration(completedChallenges) {
  const challenge = completedChallenges[0];
  const overlay = document.createElement('div');
  overlay.id = 'challenge-celebration-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.92);z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;animation:fadeInCelebration 0.3s ease;';
  overlay.innerHTML = `
    <style>
      @keyframes fadeInCelebration { from { opacity: 0; } to { opacity: 1; } }
      @keyframes bounceIn { 0% { transform: scale(0) rotate(-10deg); } 60% { transform: scale(1.1) rotate(2deg); } 100% { transform: scale(1) rotate(0); } }
      @keyframes confettiDrop { 0% { transform: translateY(-100vh) rotate(0deg); opacity: 1; } 100% { transform: translateY(100vh) rotate(720deg); opacity: 0; } }
      @keyframes shine { 0% { background-position: -200% center; } 100% { background-position: 200% center; } }
      .confetti-piece { position: absolute; width: 10px; height: 10px; animation: confettiDrop 3s ease-out forwards; }
    </style>
    <div id="challenge-confetti" style="position:absolute;inset:0;overflow:hidden;pointer-events:none;"></div>
    <div style="animation:bounceIn 0.6s ease;text-align:center;z-index:1;max-width:360px;">
      <div style="font-size:4.5rem;margin-bottom:12px;">🏆</div>
      <h2 style="color:var(--yellow);font-size:1.6rem;margin:0 0 8px;background:linear-gradient(90deg,#f9e2af,#fab387,#f9e2af);background-size:200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shine 2s linear infinite;">Desafio Completo!</h2>
      <p style="color:var(--text);font-size:1.1rem;margin:0 0 6px;font-weight:600;">${challenge.titulo}</p>
      <p style="color:var(--green);font-size:0.9rem;margin:0 0 20px;">✅ Meta atingida: ${challenge.meta_valor} ${challenge.meta_tipo}</p>
      ${completedChallenges.length > 1 ? `<p style="color:var(--accent);font-size:0.8rem;margin:0 0 16px;">+${completedChallenges.length - 1} outro(s) desafio(s) concluído(s)!</p>` : ''}
      <button onclick="document.getElementById('challenge-celebration-overlay').remove()" style="background:linear-gradient(135deg,#cba6f7,#89b4fa);color:var(--bg);border:none;border-radius:8px;padding:12px 32px;font-size:1rem;font-weight:700;cursor:pointer;box-shadow:0 4px 15px rgba(203,166,247,0.3);">🎉 Excelente!</button>
    </div>
  `;
  document.body.appendChild(overlay);

  // Spawn confetti
  const container = overlay.querySelector('#challenge-confetti');
  const colors = [getCSSVar('--red')||'#f38ba8',getCSSVar('--green')||'#a6e3a1',getCSSVar('--blue')||'#89b4fa',getCSSVar('--yellow')||'#f9e2af',getCSSVar('--accent')||'#cba6f7',getCSSVar('--peach')||'#fab387','#94e2d5'];
  for (let i = 0; i < 80; i++) {
    const piece = document.createElement('div');
    piece.className = 'confetti-piece';
    piece.style.left = Math.random() * 100 + '%';
    piece.style.background = colors[Math.floor(Math.random() * colors.length)];
    piece.style.borderRadius = Math.random() > 0.5 ? '50%' : '2px';
    piece.style.width = (6 + Math.random() * 8) + 'px';
    piece.style.height = (6 + Math.random() * 8) + 'px';
    piece.style.animationDelay = Math.random() * 2 + 's';
    piece.style.animationDuration = (2 + Math.random() * 2) + 's';
    container.appendChild(piece);
  }

  // Play celebration sound
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const notes = [523.25, 659.25, 783.99, 1046.5];
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.type = 'sine'; osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.2, ctx.currentTime + i * 0.15);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + i * 0.15 + 0.4);
      osc.start(ctx.currentTime + i * 0.15);
      osc.stop(ctx.currentTime + i * 0.15 + 0.4);
    });
  } catch(e) {}

  // Auto-dismiss after 8 seconds
  setTimeout(() => { if (overlay.parentNode) overlay.remove(); }, 8000);
}

export async function loadDesafios() {
  try {
    const progressResult = await fetch('/api/desafios/atualizar-progresso', { method: 'POST' }).then(r => r.json()).catch(() => ({just_completed: []}));

    if (progressResult.just_completed && progressResult.just_completed.length > 0) {
      showChallengeCelebration(progressResult.just_completed);
    }

    const [desafios, sugestoes] = await Promise.all([
      fetch('/api/desafios').then(r => r.json()),
      fetch('/api/desafios/sugestoes').then(r => r.json()).catch(() => [])
    ]);
    const el = document.getElementById('desafios-box');

    let html = '';

    const ativos = desafios.filter(d => !d.finalizado && !d.expirado);
    const concluidos = desafios.filter(d => d.finalizado);

    if (ativos.length > 0) {
      html += ativos.map(d => {
        const cor = d.pct >= 100 ? 'var(--green)' : d.pct >= 50 ? 'var(--yellow)' : 'var(--blue)';
        return `<div style="padding:8px;margin-bottom:6px;background:var(--bg);border-radius:8px;border-left:3px solid ${cor};">
          <div style="display:flex;align-items:center;gap:6px;font-size:0.82rem;">
            <span style="flex:1;color:var(--text);font-weight:500;">${d.titulo}</span>
            <span style="font-size:0.72rem;color:var(--text-sub);">${d.dias_restantes}d restantes</span>
            <button onclick="editarDesafio(${d.id},'${d.titulo.replace(/'/g,"\\'")}','${d.meta_tipo}',${d.meta_valor},'${(d.materia||'').replace(/'/g,"\\'")}',${d.dias})" style="background:none;border:none;color:var(--blue)88;cursor:pointer;font-size:0.8rem;" title="Editar" aria-label="Editar desafio">✏️</button>
            <button onclick="deleteDesafio(${d.id})" style="background:none;border:none;color:var(--red)55;cursor:pointer;font-size:0.8rem;" title="Remover" aria-label="Remover desafio">×</button>
          </div>
          <div style="display:flex;align-items:center;gap:6px;margin-top:4px;">
            <div style="flex:1;height:6px;background:var(--bg-elevated);border-radius:3px;overflow:hidden;">
              <div style="width:${d.pct}%;height:100%;background:${cor};border-radius:3px;transition:width 0.3s;"></div>
            </div>
            <span style="font-size:0.72rem;color:${cor};font-weight:600;min-width:60px;text-align:right;">${d.progresso}/${d.meta_valor}</span>
          </div>
          ${d.materia ? `<div style="font-size:0.68rem;color:var(--text-muted);margin-top:2px;">📚 ${d.materia}</div>` : ''}
        </div>`;
      }).join('');
    }

    if (concluidos.length > 0) {
      html += `<div style="margin-top:8px;font-size:0.72rem;color:var(--green);font-weight:600;">✅ Concluídos</div>`;
      html += concluidos.slice(0, 3).map(d => `<div style="padding:4px 8px;font-size:0.75rem;color:var(--text-sub);display:flex;align-items:center;gap:4px;"><span>✓</span><span style="flex:1;text-decoration:line-through;">${d.titulo}</span><button onclick="deleteDesafio(${d.id})" style="background:none;border:none;color:var(--red)55;cursor:pointer;" aria-label="Remover desafio">×</button></div>`).join('');
    }

    if (sugestoes.length > 0 && ativos.length < 3) {
      html += `<div style="margin-top:10px;padding-top:8px;border-top:1px solid var(--border);">
        <div style="font-size:0.75rem;color:var(--accent);font-weight:600;margin-bottom:6px;">💡 Desafios Sugeridos</div>`;
      html += sugestoes.slice(0, 3).map(s => `<div style="display:flex;align-items:center;gap:6px;padding:6px;background:var(--bg-surface);border-radius:6px;margin-bottom:4px;font-size:0.78rem;">
        <span style="font-size:1rem;">${s.icon}</span>
        <div style="flex:1;">
          <div style="color:var(--text);font-weight:500;">${s.titulo}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">${s.descricao}</div>
        </div>
        <button onclick="aceitarDesafio('${s.titulo.replace(/'/g,"\\'")}','${s.meta_tipo}',${s.meta_valor},'${s.materia}',${s.dias})" style="background:var(--accent);color:var(--bg);border:none;border-radius:4px;padding:4px 8px;font-size:0.7rem;font-weight:600;cursor:pointer;white-space:nowrap;">Aceitar</button>
      </div>`).join('');
      html += '</div>';
    }

    html += `<button onclick="showCriarDesafioModal()" style="width:100%;margin-top:8px;padding:8px;background:var(--bg-elevated);color:var(--text);border:none;border-radius:6px;cursor:pointer;font-size:0.8rem;">+ Criar Desafio</button>`;

    el.innerHTML = html;
  } catch(e) { console.error('Desafios error:', e); }
}

export async function aceitarDesafio(titulo, metaTipo, metaValor, materia, dias) {
  await fetch('/api/desafios', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ titulo, meta_tipo: metaTipo, meta_valor: metaValor, materia, dias })
  });
  loadDesafios();
}

export async function deleteDesafio(id) {
  await fetch(`/api/desafios/${id}`, { method: 'DELETE' });
  loadDesafios();
}

export function showCriarDesafioModal() {
  const overlay = document.createElement('div');
  overlay.id = 'criar-desafio-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.innerHTML = `<div style="background:var(--bg-surface);border-radius:12px;padding:24px;max-width:400px;width:100%;">
    <h3 style="color:var(--accent);margin-bottom:12px;">🏆 Criar Desafio</h3>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <label style="font-size:0.8rem;color:var(--text-sub);">Título
        <input id="desafio-titulo" type="text" placeholder="Ex: Dominar Direito Constitucional" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
      </label>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <label style="font-size:0.8rem;color:var(--text-sub);">Tipo
          <select id="desafio-tipo" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
            <option value="questoes">❓ Questões</option>
            <option value="horas">⏱ Horas</option>
            <option value="flashcards">🧠 Flashcards</option>
            <option value="topicos">📋 Tópicos</option>
          </select>
        </label>
        <label style="font-size:0.8rem;color:var(--text-sub);">Meta (quantidade)
          <input id="desafio-meta" type="number" value="30" min="1" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
        </label>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <label style="font-size:0.8rem;color:var(--text-sub);">Matéria (opcional)
          <input id="desafio-materia" type="text" placeholder="Todas" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
        </label>
        <label style="font-size:0.8rem;color:var(--text-sub);">Prazo (dias)
          <input id="desafio-dias" type="number" value="7" min="1" max="30" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
        </label>
      </div>
    </div>
    <div style="display:flex;gap:8px;margin-top:16px;">
      <button onclick="document.getElementById('criar-desafio-modal').remove()" style="flex:1;padding:10px;background:var(--bg-elevated);color:var(--text);border:none;border-radius:6px;cursor:pointer;">Cancelar</button>
      <button onclick="criarDesafioManual()" style="flex:1;padding:10px;background:var(--accent);color:var(--bg);border:none;border-radius:6px;font-weight:600;cursor:pointer;">Criar</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

export async function criarDesafioManual() {
  const titulo = document.getElementById('desafio-titulo').value.trim();
  const tipo = document.getElementById('desafio-tipo').value;
  const meta = parseInt(document.getElementById('desafio-meta').value) || 30;
  const materia = document.getElementById('desafio-materia').value.trim();
  const dias = parseInt(document.getElementById('desafio-dias').value) || 7;
  if (!titulo) return;
  await fetch('/api/desafios', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ titulo, meta_tipo: tipo, meta_valor: meta, materia, dias })
  });
  document.getElementById('criar-desafio-modal').remove();
  loadDesafios();
}

export function editarDesafio(id, titulo, metaTipo, metaValor, materia, dias) {
  const overlay = document.createElement('div');
  overlay.id = 'editar-desafio-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;';
  overlay.innerHTML = `<div style="background:var(--bg-surface);border-radius:12px;padding:24px;max-width:400px;width:100%;">
    <h3 style="color:var(--accent);margin-bottom:12px;">✏️ Editar Desafio</h3>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <label style="font-size:0.8rem;color:var(--text-sub);">Título
        <input id="edit-desafio-titulo" type="text" value="${titulo}" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
      </label>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <label style="font-size:0.8rem;color:var(--text-sub);">Tipo
          <select id="edit-desafio-tipo" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
            <option value="questoes" ${metaTipo==='questoes'?'selected':''}>❓ Questões</option>
            <option value="horas" ${metaTipo==='horas'?'selected':''}>⏱ Horas</option>
            <option value="flashcards" ${metaTipo==='flashcards'?'selected':''}>🧠 Flashcards</option>
            <option value="topicos" ${metaTipo==='topicos'?'selected':''}>📋 Tópicos</option>
          </select>
        </label>
        <label style="font-size:0.8rem;color:var(--text-sub);">Meta (quantidade)
          <input id="edit-desafio-meta" type="number" value="${metaValor}" min="1" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
        </label>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <label style="font-size:0.8rem;color:var(--text-sub);">Matéria (opcional)
          <input id="edit-desafio-materia" type="text" value="${materia}" placeholder="Todas" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
        </label>
        <label style="font-size:0.8rem;color:var(--text-sub);">Prazo (dias)
          <input id="edit-desafio-dias" type="number" value="${dias}" min="1" max="30" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-top:4px;">
        </label>
      </div>
    </div>
    <div style="display:flex;gap:8px;margin-top:16px;">
      <button onclick="document.getElementById('editar-desafio-modal').remove()" style="flex:1;padding:10px;background:var(--bg-elevated);color:var(--text);border:none;border-radius:6px;cursor:pointer;">Cancelar</button>
      <button onclick="salvarEdicaoDesafio(${id})" style="flex:1;padding:10px;background:var(--accent);color:var(--bg);border:none;border-radius:6px;font-weight:600;cursor:pointer;">💾 Salvar</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

export async function salvarEdicaoDesafio(id) {
  const titulo = document.getElementById('edit-desafio-titulo').value.trim();
  const tipo = document.getElementById('edit-desafio-tipo').value;
  const meta = parseInt(document.getElementById('edit-desafio-meta').value) || 30;
  const materia = document.getElementById('edit-desafio-materia').value.trim();
  const dias = parseInt(document.getElementById('edit-desafio-dias').value) || 7;
  if (!titulo) return;
  await fetch(`/api/desafios/${id}`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ titulo, meta_tipo: tipo, meta_valor: meta, materia, dias })
  });
  document.getElementById('editar-desafio-modal').remove();
  loadDesafios();
}

// ===== STREAK FREEZE =====
export function showStreakFreezeOffer(freezesAvailable) {
  if (sessionStorage.getItem('freeze_offered')) return;
  sessionStorage.setItem('freeze_offered', '1');

  const overlay = document.createElement('div');
  overlay.id = 'streak-freeze-offer';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.9);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeInCelebration 0.3s ease;';
  overlay.innerHTML = `
    <div style="background:var(--bg-surface);border-radius:16px;padding:32px;max-width:360px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.5);border:2px solid #89dceb;">
      <div style="font-size:3.5rem;margin-bottom:12px;">🧊</div>
      <h3 style="color:#94e2d5;margin:0 0 8px;font-size:1.3rem;">Streak em risco!</h3>
      <p style="color:var(--text);font-size:0.9rem;margin:0 0 16px;">Você não estudou ontem. Quer usar um <strong>Streak Freeze</strong> para proteger seu streak?</p>
      <p style="color:var(--text-sub);font-size:0.8rem;margin:0 0 20px;">Freezes disponíveis: ${freezesAvailable}</p>
      <div style="display:flex;gap:10px;justify-content:center;">
        <button onclick="useStreakFreeze()" style="background:#89dceb;color:var(--bg);border:none;border-radius:8px;padding:10px 24px;font-weight:600;cursor:pointer;font-size:0.9rem;">🧊 Usar Freeze</button>
        <button onclick="document.getElementById('streak-freeze-offer').remove()" style="background:var(--bg-elevated);color:var(--text);border:none;border-radius:8px;padding:10px 24px;cursor:pointer;font-size:0.9rem;">Deixar quebrar</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
}

export async function useStreakFreeze() {
  const result = await fetch('/api/streak-freeze/use', { method: 'POST' }).then(r => r.json()).catch(() => null);
  const offer = document.getElementById('streak-freeze-offer');
  if (offer) offer.remove();
  if (result && result.ok) {
    if (typeof showToast === 'function') showToast('🧊 Streak protegido! Seu streak continua.', 'success');
    const streaks = await fetch('/api/streaks').then(r => r.json());
    renderStreak(streaks);
  } else {
    if (typeof showToast === 'function') showToast(result?.message || 'Não foi possível usar o freeze', 'error');
  }
}

export function showStreakFreezeModal() {
  fetch('/api/streak-freeze').then(r => r.json()).then(freeze => {
    const overlay = document.createElement('div');
    overlay.id = 'streak-freeze-modal';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;';
    overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `
      <div style="background:var(--bg-surface);border-radius:16px;padding:28px;max-width:340px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
        <div style="font-size:2.5rem;margin-bottom:8px;">🧊</div>
        <h3 style="color:#94e2d5;margin:0 0 12px;">Streak Freeze</h3>
        <p style="color:var(--text);font-size:0.85rem;margin:0 0 16px;">Protege seu streak se você perder 1 dia de estudo. O streak não será zerado!</p>
        <div style="display:flex;justify-content:center;gap:8px;margin-bottom:12px;">
          ${'🧊'.repeat(freeze.freezes_available)}${'<span style="opacity:0.3;font-size:1.3rem;">🧊</span>'.repeat(freeze.max_freezes - freeze.freezes_available)}
        </div>
        <p style="color:var(--green);font-size:0.8rem;margin:0 0 6px;">Disponíveis: ${freeze.freezes_available}/${freeze.max_freezes}</p>
        <p style="color:var(--text-sub);font-size:0.75rem;margin:0 0 6px;">Usados: ${freeze.freezes_used}</p>
        <p style="color:var(--accent);font-size:0.75rem;margin:0 0 16px;">Próximo ganho: streak de ${freeze.earn_next_at} dias</p>
        <button onclick="document.getElementById('streak-freeze-modal').remove()" style="background:var(--bg-elevated);color:var(--text);border:none;border-radius:8px;padding:8px 20px;cursor:pointer;">Fechar</button>
      </div>
    `;
    document.body.appendChild(overlay);
  });
}

export function renderStreak(data) {
  document.getElementById('streak-atual').textContent = data.streak_atual;
  document.getElementById('streak-best').textContent = data.melhor_streak;

  fetch('/api/streak-freeze').then(r => r.json()).then(freeze => {
    let freezeEl = document.getElementById('streak-freeze-indicator');
    if (!freezeEl) {
      freezeEl = document.createElement('div');
      freezeEl.id = 'streak-freeze-indicator';
      freezeEl.style.cssText = 'display:flex;align-items:center;gap:4px;margin-left:auto;';
      const streakBar = document.querySelector('.streak-bar');
      if (streakBar) streakBar.insertBefore(freezeEl, streakBar.querySelector('.streak-best'));
    }
    const freezeIcons = '🧊'.repeat(freeze.freezes_available) + '<span style="opacity:0.3;">🧊</span>'.repeat(freeze.max_freezes - freeze.freezes_available);
    freezeEl.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;cursor:pointer;" title="Streak Freezes: ${freeze.freezes_available}/${freeze.max_freezes}\nProtege seu streak se perder 1 dia\nGanhe a cada ${freeze.earn_next_at - data.streak_atual > 0 ? freeze.earn_next_at - data.streak_atual + ' dias' : 'agora!'}" onclick="showStreakFreezeModal()">
        <div style="font-size:0.85rem;">${freezeIcons}</div>
        <div style="font-size:0.6rem;color:#94e2d5;">${freeze.freezes_available}/${freeze.max_freezes}</div>
      </div>
    `;

    if (freeze.can_earn_today) {
      fetch('/api/streak-freeze/earn', { method: 'POST' }).then(r => r.json()).then(res => {
        if (res.ok && typeof showToast === 'function') showToast('🧊 Streak Freeze ganho! Agora você tem proteção extra.', 'success');
      }).catch(() => {});
    }

    if (data.streak_atual === 0 && freeze.freezes_available > 0) {
      showStreakFreezeOffer(freeze.freezes_available);
    }
  }).catch(() => {});
}

export async function loadMissoes() {
  try {
    const data = await fetch('/api/conquistas-diarias').then(r => r.json());
    const el = document.getElementById('missoes-box');
    el.innerHTML = data.map(m => `<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);font-size:0.85rem;"><span style="font-size:1.1rem;">⭐</span><span style="flex:1;">${m.titulo}</span><span style="color:var(--yellow);font-size:0.75rem;">+${m.xp}xp</span></div>`).join('');
  } catch(e) {}
}

export async function loadShareBox() {
  try {
    const data = await fetch('/api/compartilhar').then(r => r.json());
    const el = document.getElementById('share-box');
    el.innerHTML = `<div class="share-card"><div class="share-text">${data.texto}</div><div class="share-btns"><button style="background:var(--green);color:var(--bg);" onclick="navigator.clipboard.writeText('${data.texto.replace(/'/g,"\\'")}')">\ud83d\udccb Copiar</button><button style="background:var(--bg-elevated);color:var(--text);" onclick="window.open('/api/exportar-tudo')">\u2b07 Backup JSON</button></div></div>`;
  } catch(e) {}
}

// Window assignments for HTML onclick
window.aceitarDesafio = aceitarDesafio;
window.deleteDesafio = deleteDesafio;
window.showCriarDesafioModal = showCriarDesafioModal;
window.criarDesafioManual = criarDesafioManual;
window.editarDesafio = editarDesafio;
window.salvarEdicaoDesafio = salvarEdicaoDesafio;
window.showStreakFreezeModal = showStreakFreezeModal;
window.useStreakFreeze = useStreakFreeze;
