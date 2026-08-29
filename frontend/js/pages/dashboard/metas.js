// metas.js — Metas section (renderMetas, loadMetaDetails, toggleMetaDetail)
import { COLORS } from './helpers.js';

export function renderMetas(data) {
  const container = document.getElementById('metas-container');
  const cfg = data.config;
  const prog = data.progresso;

  const metas = [
    { id: 'horas', icon: '⏱', title: `Horas de estudo`, value: `${prog.horas.toFixed(1)}h / ${cfg.meta_horas}h`, pct: Math.min(100, (prog.horas / cfg.meta_horas) * 100), color: COLORS.blue },
    { id: 'questoes', icon: '❓', title: `Questões`, value: `${prog.questoes} / ${cfg.meta_questoes}`, pct: Math.min(100, (prog.questoes / cfg.meta_questoes) * 100), color: COLORS.green },
    { id: 'flashcards', icon: '🧠', title: `Flashcards`, value: `${prog.flashcards} / ${cfg.meta_flashcards}`, pct: Math.min(100, (prog.flashcards / cfg.meta_flashcards) * 100), color: COLORS.mauve },
  ];

  container.innerHTML = metas.map(m => `
    <div class="meta-row" style="cursor:pointer;transition:background 0.2s;border-radius:8px;padding:6px 4px;" onclick="toggleMetaDetail('${m.id}')" title="Clique para ver detalhes">
      <span class="meta-icon">${m.icon}</span>
      <div class="meta-info">
        <div class="meta-title">${m.title}: <strong style="color:${m.color}">${m.value}</strong></div>
        <div class="meta-progress-bar">
          <div class="meta-progress-fill" style="width:${m.pct}%;background:${m.color};"></div>
        </div>
      </div>
      <span class="meta-pct" style="color:${m.color}">${Math.round(m.pct)}%</span>
      <span style="font-size:0.7rem;color:var(--text-sub);margin-left:4px;">▼</span>
    </div>
    <div id="meta-detail-${m.id}" style="display:none;padding:8px 12px 12px 36px;font-size:0.8rem;color:var(--text-sub);background:var(--bg);border-radius:8px;margin:-2px 0 8px;animation:slideDown 0.2s ease;">
      <div style="text-align:center;padding:8px;"><span style="opacity:0.5;">Carregando...</span></div>
    </div>
  `).join('');

  // Load details immediately (but hidden)
  loadMetaDetails();
}

export async function loadMetaDetails() {
  try {
    const resumo = await fetch('/api/resumo-diario').then(r => r.json());

    // Horas detail
    const horasEl = document.getElementById('meta-detail-horas');
    if (horasEl) {
      if (resumo.sessoes && resumo.sessoes.length > 0) {
        // Formata o tempo de forma legível: "Xh Ymin", "Xh" ou "Ymin".
        // Sessões curtas (ex: 2min de questões) não devem aparecer como "0h".
        const fmtDur = (horas) => {
          const totalMin = Math.round((horas || 0) * 60);
          if (totalMin < 1) return '<1min';
          const h = Math.floor(totalMin / 60);
          const m = totalMin % 60;
          if (h === 0) return `${m}min`;
          if (m === 0) return `${h}h`;
          return `${h}h ${m}min`;
        };
        const totalHoras = resumo.sessoes.reduce((a, s) => a + (s.horas || 0), 0);
        horasEl.innerHTML = `
          <div style="font-weight:600;color:var(--text);margin-bottom:6px;">📚 Sessões de hoje:</div>
          ${resumo.sessoes.map(s => `
            <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border);">
              <span>${s.materia}</span>
              <span style="color:var(--blue);font-weight:600;">${fmtDur(s.horas)}</span>
            </div>
          `).join('')}
          <div style="margin-top:8px;font-size:0.75rem;color:var(--text-muted);">Total: ${fmtDur(totalHoras)} em ${resumo.sessoes.length} matéria(s)</div>
        `;
      } else {
        horasEl.innerHTML = '<div style="color:var(--text-muted);font-style:italic;">Nenhuma sessão registrada hoje. Inicie um timer ou registre estudo manual.</div>';
      }
    }

    // Questões detail
    const questoesEl = document.getElementById('meta-detail-questoes');
    if (questoesEl) {
      if (resumo.questoes_detalhes && resumo.questoes_detalhes.length > 0) {
        const totalQ = resumo.questoes_detalhes.reduce((a,q) => a + q.total, 0);
        const totalA = resumo.questoes_detalhes.reduce((a,q) => a + q.acertos, 0);
        const pctGeral = totalQ > 0 ? Math.round(totalA / totalQ * 100) : 0;
        questoesEl.innerHTML = `
          <div style="font-weight:600;color:var(--text);margin-bottom:6px;">📊 Desempenho por matéria:</div>
          ${resumo.questoes_detalhes.map(q => {
            const pct = q.total > 0 ? Math.round(q.acertos / q.total * 100) : 0;
            const cor = pct >= 70 ? 'var(--green)' : pct >= 50 ? 'var(--yellow)' : 'var(--red)';
            return `
              <div style="display:flex;align-items:center;gap:8px;padding:3px 0;border-bottom:1px solid var(--border);">
                <span style="flex:1;">${q.materia}</span>
                <span style="font-size:0.75rem;">${q.acertos}/${q.total}</span>
                <span style="color:${cor};font-weight:600;min-width:36px;text-align:right;">${pct}%</span>
              </div>
            `;
          }).join('')}
          <div style="margin-top:8px;display:flex;justify-content:space-between;padding-top:6px;border-top:1px solid var(--border);">
            <span style="font-weight:600;color:var(--text);">Total: ${totalQ} questões</span>
            <span style="font-weight:600;color:${pctGeral >= 70 ? 'var(--green)' : pctGeral >= 50 ? 'var(--yellow)' : 'var(--red)'};">${pctGeral}% acerto geral</span>
          </div>
        `;
      } else {
        questoesEl.innerHTML = '<div style="color:var(--text-muted);font-style:italic;">Nenhuma questão resolvida hoje. Vá para o Banco de Questões!</div>';
      }
    }

    // Flashcards detail
    const flashEl = document.getElementById('meta-detail-flashcards');
    if (flashEl) {
      const pendentes = await fetch('/api/flashcards/today').then(r => r.json()).catch(() => []);
      const revisados = resumo.flashcards || 0;
      const totalPendentes = pendentes.length;
      const materias = {};
      pendentes.forEach(f => { const m = f.materia || 'Sem matéria'; materias[m] = (materias[m] || 0) + 1; });

      // Total original por matéria (pendentes + revisados = original)
      // Buscar do streak quantos por matéria já foram revisados (aproximação)
      const totalOriginal = totalPendentes + revisados;

      let html = `<div style="font-weight:600;color:var(--text);margin-bottom:6px;">🧠 Status dos flashcards:</div>`;
      html += `<div style="display:flex;gap:16px;margin-bottom:8px;">
        <div style="background:var(--bg-surface);border-radius:8px;padding:8px 12px;flex:1;text-align:center;">
          <div style="font-size:1.1rem;font-weight:700;color:var(--green);">${revisados}</div>
          <div style="font-size:0.7rem;">Revisados hoje</div>
        </div>
        <div style="background:var(--bg-surface);border-radius:8px;padding:8px 12px;flex:1;text-align:center;">
          <div style="font-size:1.1rem;font-weight:700;color:var(--yellow);">${totalPendentes}</div>
          <div style="font-size:0.7rem;">Restantes</div>
        </div>
        <div style="background:var(--bg-surface);border-radius:8px;padding:8px 12px;flex:1;text-align:center;">
          <div style="font-size:1.1rem;font-weight:700;color:var(--blue);">${totalOriginal}</div>
          <div style="font-size:0.7rem;">Total do dia</div>
        </div>
      </div>`;

      if (Object.keys(materias).length > 0) {
        html += '<div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:4px;">Restantes por matéria <span style="font-size:0.65rem;">(clique para revisar)</span>:</div>';
        html += Object.entries(materias).sort((a,b) => b[1]-a[1]).slice(0, 5).map(([m, c]) =>
          `<div onclick="window._startFlashByMateria('${m.replace(/'/g, "\\'")}')" style="display:flex;justify-content:space-between;align-items:center;padding:4px 6px;cursor:pointer;border-radius:6px;transition:background 0.2s;" onmouseover="this.style.background='var(--bg-elevated)'" onmouseout="this.style.background='transparent'" title="Revisar ${c} flashcards restantes de ${m}"><span>📚 ${m}</span><span style="color:var(--accent);font-weight:600;">${c} restantes</span></div>`
        ).join('');
      }

      if (totalPendentes === 0 && revisados > 0) {
        html += `<div style="text-align:center;padding:8px;color:var(--green);font-weight:600;font-size:0.85rem;">🎉 Todos revisados hoje! Parabéns!</div>`;
      }

      flashEl.innerHTML = html;
    }
  } catch (e) {
    console.error('Meta details error:', e);
  }
}

export function toggleMetaDetail(id) {
  const el = document.getElementById('meta-detail-' + id);
  if (!el) return;
  const isVisible = el.style.display !== 'none';
  // Close all others
  document.querySelectorAll('[id^="meta-detail-"]').forEach(e => e.style.display = 'none');
  // Toggle this one
  if (!isVisible) el.style.display = 'block';
}

// Assign to window for HTML onclick
window.toggleMetaDetail = toggleMetaDetail;

// Navegar para a página principal e iniciar revisão de flashcards por matéria
window._startFlashByMateria = function(materia) {
  // Salvar matéria no sessionStorage para que o app.js inicie a revisão ao carregar
  sessionStorage.setItem('flash_start_materia', materia);
  // Forçar navegação completa (não apenas hash change)
  const target = window.location.origin + '/#flashcards';
  if (window.location.pathname === '/' || window.location.pathname === '/index.html') {
    // Já está na index — forçar reload com hash
    window.location.hash = '#flashcards';
    window.location.reload();
  } else {
    // Vem de outra página (dashboard) — navegar normalmente
    window.location.href = target;
  }
};
