// treinador.js — Treinador/recomendações panel and study technique helpers
import { getCSSVar, COLORS } from './helpers.js';

export async function loadTreinador() {
  try {
    const favorito = localStorage.getItem('countdown_favorito') || '';
    let url = '/api/treinador';
    if (favorito) {
      const [edital, cargo] = favorito.split('|');
      const params = new URLSearchParams();
      if (edital) params.set('edital_nome', edital);
      if (cargo) params.set('cargo', cargo);
      url += '?' + params.toString();
    }
    const data = await fetch(url).then(r => r.json());
    const el = document.getElementById('treinador-box');
    const scoreColor = data.score_prontidao >= 60 ? 'var(--green)' : data.score_prontidao >= 30 ? 'var(--peach)' : 'var(--red)';
    const intel = data.inteligencia || {};

    let html = `
      <div style="display:flex;align-items:center;gap:20px;margin-bottom:16px;flex-wrap:wrap;">
        <div style="text-align:center;">
          <div style="font-size:2.2rem;font-weight:700;color:${scoreColor};">${data.score_prontidao}</div>
          <div style="font-size:0.75rem;color:var(--text-sub);">Score de Prontidão</div>
          <div style="font-size:0.82rem;color:${scoreColor};font-weight:600;">${data.nivel}</div>
        </div>
        <div style="flex:1;min-width:200px;">
          <div style="background:var(--bg-elevated);border-radius:8px;height:10px;overflow:hidden;">
            <div style="width:${data.score_prontidao}%;height:100%;background:${scoreColor};border-radius:8px;transition:width 0.6s;"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:0.7rem;color:var(--text-sub);margin-top:4px;">
            <span>Iniciante</span><span>Intermediário</span><span>Avançado</span><span>Pronto</span>
          </div>
        </div>
        <div style="text-align:center;">
          <div style="font-size:0.8rem;color:var(--text-sub);">Revisões pendentes</div>
          <div style="font-size:1.2rem;font-weight:700;color:var(--blue);">🧠 ${data.revisoes_pendentes.flashcards} | 📝 ${data.revisoes_pendentes.topicos}</div>
        </div>
      </div>`;

    if (intel.ritmo_adaptativo) {
      const r = intel.ritmo_adaptativo;
      const ritmoColor = r.status === 'acima' ? 'var(--green)' : r.status === 'adequado' ? 'var(--blue)' : r.status === 'insuficiente' ? 'var(--peach)' : 'var(--red)';
      html += `<div style="background:var(--bg);border-radius:10px;padding:12px 16px;margin-bottom:12px;border-left:4px solid ${ritmoColor};">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
          <div>
            <div style="font-size:0.82rem;font-weight:600;color:${ritmoColor};">${r.msg}</div>
            <div style="font-size:0.72rem;color:var(--text-sub);margin-top:2px;">${r.topicos_pendentes} tópicos restantes • ${r.dias_restantes} dias até a prova</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:1.4rem;font-weight:700;color:${ritmoColor};">${r.pct_ritmo}%</div>
            <div style="font-size:0.68rem;color:var(--text-sub);">do ritmo ideal</div>
          </div>
        </div>
      </div>`;
    }

    if (intel.sprint_mode && intel.sprint_mode.ativo) {
      const sp = intel.sprint_mode;
      html += `<div style="background:linear-gradient(135deg,#f38ba822,#fab38722);border-radius:10px;padding:12px 16px;margin-bottom:12px;border:1px solid #f38ba844;">
        <div style="font-size:0.88rem;font-weight:700;color:var(--red);">🏃 MODO SPRINT — ${sp.dias_restantes} dias</div>
        <div style="font-size:0.75rem;color:var(--text);margin-top:4px;">${sp.estrategia}</div>
        <div style="display:flex;gap:12px;margin-top:8px;font-size:0.72rem;">
          <span style="color:var(--blue);">📖 ${sp.distribuicao.revisao_pct}% revisão</span>
          <span style="color:var(--accent);">❓ ${sp.distribuicao.questoes_pct}% questões</span>
          <span style="color:var(--peach);">📝 ${sp.distribuicao.simulado_pct}% simulado</span>
        </div>
      </div>`;
    }

    html += `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin-bottom:12px;">
        ${data.recomendacoes.map(r => {
          const icons = {revisar:'🧠',questoes:'❓',estudar:'📚',alerta:'🚨'};
          const colors = {revisar:'var(--blue)',questoes:'var(--accent)',estudar:'var(--green)',alerta:'var(--red)'};
          return `<div style="background:var(--bg);border-radius:8px;padding:10px 12px;display:flex;align-items:center;gap:8px;border-left:3px solid ${colors[r.tipo]||'var(--bg-elevated)'};">
            <span style="font-size:1.1rem;">${icons[r.tipo]||'💡'}</span>
            <span style="font-size:0.82rem;">${r.msg}</span>
          </div>`;
        }).join('')}
      </div>`;

    if (intel.forgetting_risk && intel.forgetting_risk.length > 0) {
      html += `<div style="margin-bottom:12px;">
        <div style="font-size:0.8rem;color:var(--text-sub);margin-bottom:6px;font-weight:600;">⚠️ Risco de Esquecimento (FSRS):</div>
        <div style="display:grid;gap:4px;">
          ${intel.forgetting_risk.slice(0, 5).map(item => {
            const urgColor = item.urgencia === 'critica' ? 'var(--red)' : item.urgencia === 'alta' ? 'var(--peach)' : 'var(--yellow)';
            const clickAction = item.tipo === 'flashcard'
              ? `onclick="window.location.href='/#flashcards';setTimeout(()=>{if(window.iniciarSessaoFlash)window.iniciarSessaoFlash('revisao')},500)" style="cursor:pointer;" title="Revisar flashcard"`
              : item.tipo === 'edital'
                ? `onclick="window.location.href='/#edital'" style="cursor:pointer;" title="Ver no edital"`
                : '';
            return `<div ${clickAction} style="display:flex;align-items:flex-start;gap:8px;font-size:0.78rem;padding:8px 10px;background:var(--bg);border-radius:6px;${clickAction ? 'cursor:pointer;transition:background 0.2s;' : ''}" ${clickAction ? 'onmouseover="this.style.background=\'var(--bg-elevated)\'" onmouseout="this.style.background=\'var(--bg)\'"' : ''}>
              <div style="min-width:44px;text-align:center;font-weight:700;color:${urgColor};padding-top:1px;">${item.recall_estimado}%</div>
              <div style="flex:1;color:var(--text);line-height:1.4;">${item.descricao}</div>
              <div style="font-size:0.68rem;color:var(--text-sub);min-width:55px;text-align:right;padding-top:1px;">${item.tipo}</div>
            </div>`;
          }).join('')}
        </div>
      </div>`;
    }

    if (intel.micro_metas && intel.micro_metas.length > 0) {
      html += `<div style="margin-bottom:12px;">
        <div style="font-size:0.8rem;color:var(--text-sub);margin-bottom:6px;font-weight:600;">🎯 Micro-Metas do Dia:</div>
        ${intel.micro_metas.map(mm => `<div style="font-size:0.78rem;padding:6px 10px;background:var(--bg);border-radius:6px;margin-bottom:3px;border-left:3px solid ${mm.prioridade==='ALTA'?'var(--red)':'var(--peach)'};">
          ${mm.meta}
        </div>`).join('')}
      </div>`;
    }

    if (intel.plateaus && intel.plateaus.length > 0) {
      html += `<div style="margin-bottom:12px;">
        <div style="font-size:0.8rem;color:var(--yellow);margin-bottom:6px;font-weight:600;">📊 Platôs Detectados:</div>
        ${intel.plateaus.map(p => `<div style="font-size:0.78rem;padding:6px 10px;background:var(--bg);border-radius:6px;margin-bottom:3px;border-left:3px solid #f9e2af;">
          <strong>${p.materia}</strong> (${p.pct_anterior}% → ${p.pct_atual}%): ${p.sugestao}
        </div>`).join('')}
      </div>`;
    }

    html += `<div style="display:flex;gap:12px;flex-wrap:wrap;">`;
    if (intel.horario_otimo) {
      html += `<div style="flex:1;min-width:180px;background:var(--bg);border-radius:8px;padding:10px 12px;">
        <div style="font-size:0.75rem;color:var(--text-sub);font-weight:600;">⏰ Seu Melhor Horário</div>
        <div style="font-size:0.9rem;font-weight:600;color:var(--blue);margin-top:4px;">${intel.horario_otimo.label}</div>
        <div style="font-size:0.7rem;color:#a6adc8;margin-top:2px;">${intel.horario_otimo.pct}% das sessões</div>
      </div>`;
    }
    if (data.materias_foco && data.materias_foco.length > 0) {
      html += `<div style="flex:2;min-width:200px;">
        <div style="font-size:0.8rem;color:var(--text-sub);margin-bottom:6px;font-weight:600;">🎯 Matérias Foco:</div>
        <div>${data.materias_foco.map(m => `<span style="display:inline-block;background:${m.prioridade==='ALTA'?'var(--red)':'var(--peach)'};color:var(--bg);padding:3px 10px;border-radius:12px;font-size:0.75rem;font-weight:600;margin:2px 4px;">${m.materia} (${m.pct_acerto}%)</span>`).join('')}</div>
      </div>`;
    }
    html += `</div>`;

    el.innerHTML = html;
  } catch(e) { console.error('Treinador error:', e); }
}

export async function loadTrilha() {
  try {
    const data = await fetch('/api/trilha-diaria').then(r => r.json());
    const el = document.getElementById('trilha-box');
    const icons = {revisao:'🧠',estudo:'📚',questoes:'❓',pausa:'☕'};
    const colors = {revisao:'var(--blue)',estudo:'var(--green)',questoes:'var(--accent)',pausa:'var(--text-sub)'};
    let html = `<div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:10px;">${data.tempo_total_min} min planejados | Foco: <strong style="color:var(--accent);">${data.foco_principal || 'Geral'}</strong></div>`;
    html += data.atividades.map((a, i) => `
      <div style="display:flex;align-items:center;gap:10px;padding:8px 0;${i < data.atividades.length-1 ? 'border-bottom:1px solid var(--border);':''}">
        <div style="width:24px;height:24px;border-radius:50%;background:${colors[a.tipo]||'var(--bg-elevated)'};display:flex;align-items:center;justify-content:center;font-size:0.7rem;color:var(--bg);font-weight:700;">${i+1}</div>
        <span style="font-size:1rem;">${icons[a.tipo]||'📌'}</span>
        <span style="flex:1;font-size:0.82rem;">${a.descricao || (a.materia + ': ' + (a.qtd ? a.qtd + ' questões' : a.topicos?.join(', ') || 'estudo'))}</span>
        <span style="font-size:0.75rem;color:var(--text-sub);min-width:40px;text-align:right;">${a.tempo_min}min</span>
      </div>
    `).join('');
    if (data.motivo) html += `<div style="margin-top:10px;font-size:0.75rem;color:var(--peach);font-style:italic;">💡 ${data.motivo}</div>`;
    el.innerHTML = html;
  } catch(e) { console.error('Trilha error:', e); }
}

export async function loadCurvaEsquecimento() {
  try {
    const data = await fetch('/api/curva-esquecimento').then(r => r.json());
    const el = document.getElementById('curva-box');
    if (!data.length) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Complete revisões para gerar a curva.</p>'; return; }
    data.sort((a, b) => a.retencao_pct - b.retencao_pct);
    el.innerHTML = data.slice(0, 8).map(t => {
      const color = t.retencao_pct >= 70 ? 'var(--green)' : t.retencao_pct >= 40 ? 'var(--peach)' : 'var(--red)';
      const urgente = t.retencao_pct < 40;
      return `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);${urgente?'background:var(--bg);border-radius:6px;padding:6px 8px;margin:2px 0;':''}">
        <div style="width:36px;height:36px;border-radius:50%;border:3px solid ${color};display:flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:700;color:${color};">${t.retencao_pct}%</div>
        <div style="flex:1;">
          <div style="font-size:0.8rem;font-weight:600;">${t.materia}</div>
          <div style="font-size:0.72rem;color:var(--text-sub);">${t.topico?.substring(0,40) || ''}</div>
        </div>
        <div style="font-size:0.7rem;color:var(--text-sub);text-align:right;">${t.dias_desde_revisao}d atrás${urgente ? '<br><span style="color:var(--red);font-weight:600;">URGENTE</span>' : ''}</div>
      </div>`;
    }).join('');
  } catch(e) { console.error('Curva error:', e); }
}

export async function loadRevisoesPendentes() {
  try {
    const data = await fetch('/api/edital/revisoes-pendentes').then(r => r.json());
    const container = document.getElementById('revisoes-pend');
    if (!container) return;
    if (!data.length) { container.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Nenhuma revisão pendente. Agende revisões nos tópicos do edital.</p>'; return; }
    container.innerHTML = data.slice(0, 10).map(d => `<div style="padding:6px 0;border-bottom:1px solid var(--border);font-size:0.83rem;"><span style="color:var(--peach);">${d.materia}</span> — ${d.topico}</div>`).join('');
  } catch(e) {}
}

export async function loadDailyChallenge() {
  try {
    const data = await fetch('/api/daily-challenge').then(r => r.json());
    const el = document.getElementById('daily-challenge');
    if (!data.questao) { el.innerHTML = `<p style="color:var(--green);font-size:0.9rem;">${data.message}</p>`; return; }
    const q = data.questao;
    el.innerHTML = `<div style="font-size:0.88rem;line-height:1.5;margin-bottom:10px;">${q.enunciado}</div><div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:10px;">${q.materia}${q.topico ? ' • '+q.topico : ''}</div><div style="display:flex;flex-direction:column;gap:6px;">${['A','B','C','D','E'].filter(l => q['alternativa_'+l.toLowerCase()]).map(l => `<button onclick="responderDailyChallenge(${q.id},'${l}',this)" style="background:var(--bg-elevated);border:none;color:var(--text);padding:8px 12px;border-radius:6px;cursor:pointer;font-size:0.82rem;text-align:left;"><strong>${l})</strong> ${q['alternativa_'+l.toLowerCase()]}</button>`).join('')}</div><div id="daily-feedback" style="margin-top:10px;display:none;"></div>`;
  } catch(e) {}
}

export async function responderDailyChallenge(qId, letra, btn) {
  try {
    const res = await fetch(`/api/questoes/${qId}/responder`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({resposta: letra, tempo_segundos: 0})
    }).then(r => r.json());
    const fb = document.getElementById('daily-feedback');
    fb.style.display = 'block';
    if (res.acertou) {
      fb.innerHTML = `<span style="color:var(--green);font-weight:600;">✓ Correto!</span>`;
      btn.style.background = 'var(--green)'; btn.style.color = 'var(--bg)';
    } else {
      const isCE = !document.querySelector(`button[onclick*=",'C',"]`);
      const resTexto = isCE ? (res.resposta_correta === 'A' ? 'CERTO' : 'ERRADO') : `Alternativa ${res.resposta_correta}`;
      fb.innerHTML = `<span style="color:var(--red);font-weight:600;">✗ Errado. Resposta: ${resTexto}</span>`;
      btn.style.background = 'var(--red)'; btn.style.color = 'var(--bg)';
    }
    btn.parentElement.querySelectorAll('button').forEach(b => { b.disabled = true; b.style.opacity = '0.6'; });
    btn.style.opacity = '1';
  } catch(e) {}
}

export async function loadIntercalacao() {
  try {
    const data = await fetch('/api/intercalacao').then(r => r.json());
    const el = document.getElementById('intercalacao-box');
    if (!data.topicos?.length) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Estudo intercalado requer tópicos não concluídos.</p>'; return; }
    el.innerHTML = `<p style="font-size:0.78rem;color:var(--text-sub);margin-bottom:8px;">Estude estes tópicos misturados (interleaving):</p>` +
      data.topicos.map(t => `<div style="padding:5px 0;border-bottom:1px solid var(--border);font-size:0.82rem;"><span style="color:var(--blue);">${t.materia}</span> — ${t.topico}</div>`).join('');
  } catch(e) {}
}

export async function loadPraticaDelib() {
  try {
    const data = await fetch('/api/pratica-deliberada').then(r => r.json()).catch(() => null);
    const el = document.getElementById('pratica-delib-box');
    if (!data || !data.foco) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Responda questões para gerar análise de prática deliberada.</p>'; return; }
    el.innerHTML = `
      <div style="padding:8px;background:var(--bg);border-radius:8px;margin-bottom:8px;">
        <div style="font-size:0.82rem;color:var(--yellow);font-weight:600;">🎯 Foco: ${data.foco}</div>
        <div style="font-size:0.75rem;color:var(--text-sub);margin-top:4px;">${data.motivo || 'Matéria com maior potencial de melhoria'}</div>
      </div>
      ${(data.exercicios || []).map(e => `<div style="padding:4px 0;font-size:0.8rem;border-bottom:1px solid var(--border);">• ${e}</div>`).join('')}
    `;
  } catch(e) {}
}

export async function loadFeynmanMaterias() {
  try {
    const mats = await fetch('/api/questoes/materias').then(r => r.json()).catch(() => []);
    const sel = document.getElementById('feynman-materia');
    if (sel) {
      sel.innerHTML = '<option value="">Escolha uma matéria...</option>' +
        mats.map(m => `<option value="${m}">${m}</option>`).join('');
    }
  } catch(e) {}
}

export async function sortearFeynman() {
  const materia = document.getElementById('feynman-materia').value;
  try {
    const url = materia ? `/api/edital?edital_nome=&cargo=&limit=100` : '/api/edital?limit=100';
    const data = await fetch(url).then(r => r.json());
    const items = (data.items || data).filter(t => t.status !== 'Concluído');
    const filtered = materia ? items.filter(t => t.materia === materia) : items;
    if (filtered.length === 0) { document.getElementById('feynman-topico').textContent = 'Nenhum tópico disponível'; return; }
    const sorteado = filtered[Math.floor(Math.random() * filtered.length)];
    document.getElementById('feynman-topico').textContent = `📌 ${sorteado.materia}: ${sorteado.topico}`;
    document.getElementById('feynman-topico').dataset.editalId = sorteado.id;
    document.getElementById('feynman-texto').value = '';
    document.getElementById('feynman-texto').focus();
  } catch(e) { console.error(e); }
}

export async function salvarFeynman() {
  const texto = document.getElementById('feynman-texto').value.trim();
  const editalId = document.getElementById('feynman-topico').dataset.editalId;
  if (!texto || !editalId) { alert('Sorteie um tópico e escreva sua explicação.'); return; }
  try {
    await fetch(`/api/edital/${editalId}/feynman`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ edital_id: parseInt(editalId), explicacao: texto })
    });
    alert('✅ Explicação Feynman salva com sucesso!');
    document.getElementById('feynman-texto').value = '';
  } catch(e) { alert('Erro ao salvar'); }
}

export async function sortearElaboracao() {
  try {
    const data = await fetch('/api/edital?limit=200').then(r => r.json());
    const items = (data.items || data).filter(t => t.status !== 'Concluído');
    if (items.length === 0) return;
    const sorteado = items[Math.floor(Math.random() * items.length)];
    document.getElementById('elab-topico-atual').textContent = `📌 ${sorteado.materia}: ${sorteado.topico}`;
    document.getElementById('elab-topico-atual').dataset.editalId = sorteado.id;
    document.getElementById('elab-frase1').value = '';
    document.getElementById('elab-frase2').value = '';
    document.getElementById('elab-frase3').value = '';
    document.getElementById('elab-frase1').focus();
  } catch(e) {}
}

export async function salvarElaboracao() {
  const f1 = document.getElementById('elab-frase1').value.trim();
  const f2 = document.getElementById('elab-frase2').value.trim();
  const f3 = document.getElementById('elab-frase3').value.trim();
  const editalId = document.getElementById('elab-topico-atual').dataset?.editalId;
  if (!f1 || !f2 || !f3) { alert('Preencha as 3 frases!'); return; }
  const resumo = `1) ${f1}\n2) ${f2}\n3) ${f3}`;
  try {
    if (editalId) {
      await fetch(`/api/edital/${editalId}/resumo`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ resumo, tipo: '3frases' })
      });
    }
    alert('✅ Elaboração salva!');
    document.getElementById('elab-frase1').value = '';
    document.getElementById('elab-frase2').value = '';
    document.getElementById('elab-frase3').value = '';
  } catch(e) { alert('Erro ao salvar'); }
}

let retrievalCard = null;
export async function gerarRetrieval() {
  try {
    const flashcards = await fetch('/api/flashcards/aleatorio?quantidade=1').then(r => r.json());
    if (flashcards.length === 0) { document.getElementById('retrieval-pergunta').textContent = 'Sem flashcards disponíveis.'; return; }
    retrievalCard = flashcards[0];
    document.getElementById('retrieval-pergunta').innerHTML = `<strong>${retrievalCard.materia || 'Geral'}</strong><br><br>${retrievalCard.pergunta}`;
    document.getElementById('retrieval-resposta').style.display = 'none';
    document.getElementById('retrieval-resposta').value = '';
    document.getElementById('retrieval-gabarito').style.display = 'none';
    document.getElementById('btn-retrieval-tentar').style.display = 'inline-block';
    document.getElementById('btn-retrieval-revelar').style.display = 'none';
  } catch(e) {}
}

export function tentarRetrieval() {
  document.getElementById('retrieval-resposta').style.display = 'block';
  document.getElementById('retrieval-resposta').focus();
  document.getElementById('btn-retrieval-tentar').style.display = 'none';
  document.getElementById('btn-retrieval-revelar').style.display = 'inline-block';
}

export function revelarRetrieval() {
  if (!retrievalCard) return;
  document.getElementById('retrieval-gabarito').style.display = 'block';
  document.getElementById('retrieval-gabarito').innerHTML = `<strong>Resposta correta:</strong><br>${retrievalCard.resposta}`;
  document.getElementById('btn-retrieval-revelar').style.display = 'none';
}

export async function loadPontosFragcos() {
  try {
    const el = document.getElementById('pontos-fracos-box');
    const tempo = await fetch('/api/questoes/tempo-medio').then(r => r.json()).catch(() => ({por_materia: []}));
    const porMateria = tempo.por_materia || [];

    if (porMateria.length === 0) {
      el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Responda questões para identificar pontos fracos.</p>';
      return;
    }

    porMateria.sort((a, b) => b.tempo_medio_seg - a.tempo_medio_seg);
    el.innerHTML = porMateria.slice(0, 5).map((m, i) => `
      <div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);font-size:0.8rem;">
        <span style="color:${i < 2 ? 'var(--red)' : 'var(--yellow)'};font-weight:700;">#${i+1}</span>
        <span style="flex:1;">${m.materia}</span>
        <span style="color:var(--peach);font-size:0.75rem;">${m.tempo_medio_seg}s/questão</span>
        <span style="color:var(--text-sub);font-size:0.72rem;">(${m.questoes} questões)</span>
      </div>
    `).join('');
  } catch(e) { console.error(e); }
}

export async function loadConexoes() {
  try {
    const el = document.getElementById('conexoes-box');
    const mats = await fetch('/api/questoes/materias').then(r => r.json()).catch(() => []);
    if (mats.length < 2) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Adicione mais matérias para ver conexões.</p>'; return; }

    const conexoes = [
      {a: 'Direito Constitucional', b: 'Direito Administrativo', desc: 'Princípios + Organização do Estado'},
      {a: 'Direito Penal', b: 'Direito Processual Penal', desc: 'Tipificação → Persecução'},
      {a: 'Direito Civil', b: 'Direito Processual Civil', desc: 'Direito Material → Instrumental'},
      {a: 'Direito Constitucional', b: 'Direitos Humanos', desc: 'Direitos Fundamentais + Tratados'},
      {a: 'Direito Tributário', b: 'Direito Financeiro', desc: 'Receitas + Orçamento Público'},
      {a: 'Direito Administrativo', b: 'Controle Externo', desc: 'Atos + Fiscalização'},
      {a: 'Raciocínio Lógico', b: 'Estatística', desc: 'Lógica + Análise de Dados'},
      {a: 'Engenharia De Software', b: 'Gestão E Governança De Ti', desc: 'Desenvolvimento + Gestão'},
      {a: 'Segurança Da Informação', b: 'Computação Em Nuvem', desc: 'Proteção + Infraestrutura'},
    ];

    const relevantes = conexoes.filter(c =>
      mats.some(m => m.toLowerCase().includes(c.a.toLowerCase().substring(0, 10))) ||
      mats.some(m => m.toLowerCase().includes(c.b.toLowerCase().substring(0, 10)))
    );

    el.innerHTML = (relevantes.length > 0 ? relevantes : conexoes).slice(0, 6).map(c => `
      <div style="display:flex;align-items:center;gap:6px;padding:5px 0;border-bottom:1px solid var(--border);font-size:0.78rem;">
        <span style="color:var(--blue);font-weight:600;">${c.a}</span>
        <span style="color:var(--accent);">↔</span>
        <span style="color:var(--green);font-weight:600;">${c.b}</span>
        <span style="color:var(--text-sub);margin-left:auto;font-size:0.7rem;">${c.desc}</span>
      </div>
    `).join('') + '<p style="font-size:0.7rem;color:var(--text-muted);margin-top:8px;">💡 Estude matérias conectadas na mesma semana para criar associações mentais mais fortes.</p>';
  } catch(e) {}
}

export async function loadTempoResultado() {
  try {
    const el = document.getElementById('tempo-resultado-box');
    const tempo = await fetch('/api/questoes/tempo-medio').then(r => r.json()).catch(() => ({por_materia: []}));
    const porMateria = tempo.por_materia || [];

    if (porMateria.length === 0) {
      el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Responda questões com timer para análise de eficiência.</p>';
      return;
    }

    porMateria.sort((a, b) => a.tempo_medio_seg - b.tempo_medio_seg);
    el.innerHTML = `<p style="font-size:0.72rem;color:var(--text-sub);margin-bottom:6px;">⚡ Matérias por velocidade de resolução (mais rápida = mais dominada):</p>` +
      porMateria.slice(0, 6).map((m, i) => {
        const barW = Math.min(100, Math.max(10, 100 - m.tempo_medio_seg));
        const cor = i < 2 ? 'var(--green)' : i < 4 ? 'var(--yellow)' : 'var(--red)';
        return `<div style="margin-bottom:4px;">
          <div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:2px;">
            <span>${m.materia}</span><span style="color:${cor};">${m.tempo_medio_seg}s · ${m.questoes}q</span>
          </div>
          <div style="height:5px;background:var(--bg-elevated);border-radius:3px;overflow:hidden;"><div style="width:${barW}%;height:100%;background:${cor};border-radius:3px;"></div></div>
        </div>`;
      }).join('');
  } catch(e) {}
}

export async function loadSpacing() {
  try {
    const data = await fetch('/api/spacing-indicator').then(r => r.json());
    const el = document.getElementById('spacing-box');
    if (!data.materias?.length) { el.innerHTML = '<p style="color:var(--text-sub);font-size:0.85rem;">Estude por alguns dias para visualizar o espaçamento ideal.</p>'; return; }
    el.innerHTML = data.materias.map(m => `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);font-size:0.8rem;">
        <span style="width:8px;height:8px;border-radius:50%;background:${m.cor};flex-shrink:0;"></span>
        <span style="flex:1;">${m.materia}</span>
        <span style="color:${m.cor};font-size:0.75rem;white-space:nowrap;">⌀ ${m.intervalo_medio_dias}d entre sessões</span>
        <span style="font-size:0.7rem;color:var(--text-sub);">(${m.sessoes_30d}x/mês)</span>
      </div>
      <div style="font-size:0.68rem;color:var(--text-muted);padding:0 0 4px 16px;">${m.sugestao}</div>
    `).join('');
  } catch(e) {}
}

// Micro-revisão
let microItems = [], microIdx = 0, microAcertos = 0;
export async function iniciarMicroRevisao() {
  try {
    const data = await fetch('/api/micro-revisao?quantidade=5').then(r => r.json());
    microItems = data.items; microIdx = 0; microAcertos = 0;
    if (!microItems.length) { alert('Sem conteúdo para revisão.'); return; }
    document.getElementById('micro-revisao-box').style.display = 'none';
    const area = document.getElementById('micro-revisao-area');
    area.style.display = 'block';
    showMicroItem();
  } catch(e) {}
}
function showMicroItem() {
  const area = document.getElementById('micro-revisao-area');
  if (microIdx >= microItems.length) {
    area.innerHTML = `<div style="text-align:center;padding:12px;background:var(--bg);border-radius:8px;"><div style="font-size:1.2rem;margin-bottom:6px;">🎉 Micro-revisão concluída!</div><div style="color:var(--green);font-size:0.9rem;">${microAcertos}/${microItems.length} acertos</div><button onclick="document.getElementById('micro-revisao-box').style.display='block';document.getElementById('micro-revisao-area').style.display='none';" style="margin-top:8px;background:var(--blue);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-weight:600;">OK</button></div>`;
    return;
  }
  const item = microItems[microIdx];
  area.innerHTML = `<div style="padding:12px;background:var(--bg);border-radius:8px;"><div style="font-size:0.7rem;color:var(--text-sub);margin-bottom:4px;">${microIdx+1}/${microItems.length} · ${item.materia}</div><div style="font-size:0.9rem;color:var(--text);margin-bottom:10px;font-weight:600;">${item.pergunta}</div><div id="micro-resp" style="display:none;padding:8px;background:var(--bg-surface);border-radius:6px;color:var(--green);font-size:0.82rem;margin-bottom:8px;">${item.resposta}</div><div style="display:flex;gap:6px;"><button onclick="document.getElementById('micro-resp').style.display='block';this.style.display='none';document.getElementById('micro-btns').style.display='flex';" style="background:var(--yellow);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;font-weight:600;cursor:pointer;">👁 Revelar</button><div id="micro-btns" style="display:none;gap:6px;"><button onclick="microAcertos++;microIdx++;showMicroItem();" style="background:var(--green);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;font-weight:600;cursor:pointer;">✓ Sabia</button><button onclick="microIdx++;showMicroItem();" style="background:var(--red);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;font-weight:600;cursor:pointer;">✗ Não sabia</button></div></div></div>`;
}

// Autoavaliação
let autoItems = [], autoIdx = 0, autoResultados = [];
export async function iniciarAutoavaliacao() {
  try {
    const data = await fetch('/api/autoavaliacao?quantidade=5').then(r => r.json());
    autoItems = data.items; autoIdx = 0; autoResultados = [];
    if (!autoItems.length) { alert('Sem flashcards para avaliação.'); return; }
    document.getElementById('autoavaliacao-box').style.display = 'none';
    const area = document.getElementById('autoavaliacao-area');
    area.style.display = 'block';
    showAutoItem();
  } catch(e) {}
}
function showAutoItem() {
  const area = document.getElementById('autoavaliacao-area');
  if (autoIdx >= autoItems.length) {
    fetch('/api/autoavaliacao/registrar', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resultados:autoResultados})}).then(r=>r.json()).then(res => {
      area.innerHTML = `<div style="text-align:center;padding:16px;background:var(--bg);border-radius:8px;"><div style="font-size:1.1rem;margin-bottom:8px;">📊 Resultado</div><div style="font-size:2rem;font-weight:700;color:var(--accent);">${res.calibracao_pct}%</div><div style="font-size:0.82rem;color:var(--text-sub);">calibração</div><div style="margin-top:8px;font-size:0.82rem;color:var(--text);">${res.feedback}</div><div style="margin-top:6px;font-size:0.75rem;color:var(--text-sub);">Superconfiante: ${res.superconfiante} | Subconfiante: ${res.subconfiante} | Calibrado: ${res.calibrados}</div><button onclick="document.getElementById('autoavaliacao-box').style.display='block';document.getElementById('autoavaliacao-area').style.display='none';" style="margin-top:10px;background:var(--blue);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-weight:600;">OK</button></div>`;
    });
    return;
  }
  const item = autoItems[autoIdx];
  area.innerHTML = `<div style="padding:12px;background:var(--bg);border-radius:8px;"><div style="font-size:0.7rem;color:var(--text-sub);margin-bottom:4px;">${autoIdx+1}/${autoItems.length} · ${item.materia}</div><div style="font-size:0.9rem;color:var(--text);margin-bottom:10px;">${item.pergunta}</div><div style="margin-bottom:8px;font-size:0.82rem;color:var(--yellow);">Antes de ver a resposta, qual sua confiança?</div><div style="display:flex;gap:6px;margin-bottom:10px;" id="auto-conf-btns"><button onclick="autoConfianca(1)" style="background:var(--red);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-weight:600;">😟 Não sei</button><button onclick="autoConfianca(2)" style="background:var(--yellow);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-weight:600;">🤔 Acho que sei</button><button onclick="autoConfianca(3)" style="background:var(--green);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-weight:600;">😎 Tenho certeza</button></div><div id="auto-reveal" style="display:none;"></div></div>`;
}
let autoConfAtual = 0;
export function autoConfianca(nivel) {
  autoConfAtual = nivel;
  document.getElementById('auto-conf-btns').style.display = 'none';
  const item = autoItems[autoIdx];
  document.getElementById('auto-reveal').style.display = 'block';
  document.getElementById('auto-reveal').innerHTML = `<div style="padding:8px;background:var(--bg-surface);border-radius:6px;color:var(--green);font-size:0.82rem;margin-bottom:8px;"><strong>Resposta:</strong> ${item.resposta}</div><div style="display:flex;gap:6px;"><button onclick="autoRegistrar(true)" style="background:var(--green);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-weight:600;">✓ Eu sabia</button><button onclick="autoRegistrar(false)" style="background:var(--red);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-weight:600;">✗ Errei</button></div>`;
}
export function autoRegistrar(acertou) {
  autoResultados.push({flashcard_id: autoItems[autoIdx].id, confianca_pre: autoConfAtual, acertou});
  autoIdx++;
  showAutoItem();
}

// Dissertativa
export async function loadDissertMaterias() {
  try {
    const mats = await fetch('/api/questoes/materias').then(r => r.json()).catch(() => []);
    const sel = document.getElementById('dissert-materia');
    if (sel) sel.innerHTML = '<option value="">Qualquer matéria</option>' + mats.map(m => `<option value="${m}">${m}</option>`).join('');
  } catch(e) {}
}
let dissertAtual = null;
export async function gerarDissertativa() {
  const materia = document.getElementById('dissert-materia').value;
  const url = materia ? `/api/questao-dissertativa?materia=${encodeURIComponent(materia)}` : '/api/questao-dissertativa';
  const data = await fetch(url).then(r => r.json());
  if (!data.pergunta) { alert(data.message || 'Sem tópicos disponíveis.'); return; }
  dissertAtual = data;
  const area = document.getElementById('dissertativa-area');
  area.style.display = 'block';
  area.innerHTML = `<div style="padding:10px;background:var(--bg);border-radius:8px;"><div style="font-size:0.75rem;color:var(--blue);margin-bottom:4px;">${data.materia} — ${data.topico}</div><div style="font-size:0.88rem;color:var(--text);margin-bottom:8px;font-weight:600;">${data.pergunta}</div><textarea id="dissert-resposta" placeholder="Escreva sua resposta completa aqui..." rows="5" style="width:100%;background:var(--bg-surface);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px;font-size:0.82rem;resize:vertical;"></textarea><div style="display:flex;gap:8px;margin-top:8px;align-items:center;"><span style="font-size:0.75rem;color:var(--text-sub);">Confiança:</span><select id="dissert-conf" style="background:var(--bg-surface);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:4px;font-size:0.78rem;"><option value="1">😟 Baixa</option><option value="2">🤔 Média</option><option value="3" selected>😎 Alta</option></select><button onclick="salvarDissertativa()" style="background:var(--green);color:var(--bg);border:none;border-radius:6px;padding:6px 12px;font-weight:600;cursor:pointer;">💾 Salvar</button></div></div>`;
}
export async function salvarDissertativa() {
  const resp = document.getElementById('dissert-resposta').value.trim();
  if (!resp) { alert('Escreva sua resposta!'); return; }
  await fetch('/api/questao-dissertativa/salvar', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({edital_id:dissertAtual.edital_id, resposta:resp, materia:dissertAtual.materia, confianca:parseInt(document.getElementById('dissert-conf').value)})});
  alert('✅ Resposta salva!');
  document.getElementById('dissertativa-area').style.display = 'none';
}

// Cornell Notes
let cornellEditalId = null;
export async function sortearCornell() {
  const data = await fetch('/api/edital?limit=200').then(r => r.json());
  const items = (data.items || data).filter(t => t.status !== 'Concluído');
  if (!items.length) return;
  const s = items[Math.floor(Math.random() * items.length)];
  cornellEditalId = s.id;
  document.getElementById('cornell-topico').textContent = `📌 ${s.materia}: ${s.topico}`;
  document.getElementById('cornell-dicas').value = '';
  document.getElementById('cornell-notas').value = '';
  document.getElementById('cornell-resumo').value = '';
}
export async function salvarCornell() {
  const dicas = document.getElementById('cornell-dicas').value.trim();
  const notas = document.getElementById('cornell-notas').value.trim();
  const resumo = document.getElementById('cornell-resumo').value.trim();
  if (!notas && !resumo) { alert('Preencha as notas e/ou o resumo.'); return; }
  const texto = `[CORNELL NOTES]\nDicas: ${dicas}\nNotas: ${notas}\nResumo: ${resumo}`;
  if (cornellEditalId) {
    await fetch(`/api/edital/${cornellEditalId}/resumo`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resumo:texto, tipo:'cornell'})});
  }
  alert('✅ Cornell Note salva!');
}

// Método Loci
export function testarLoci() {
  const valores = [];
  for (let i = 1; i <= 5; i++) {
    const v = document.getElementById(`loci-${i}`).value.trim();
    if (v) valores.push(v);
  }
  if (valores.length === 0) { alert('Preencha pelo menos um local com um conceito.'); return; }
  const locais = ['🚪 Entrada','🛋️ Sala','🍳 Cozinha','🛏️ Quarto','🚿 Banheiro'];
  const teste = document.getElementById('loci-teste');
  teste.style.display = 'block';
  teste.innerHTML = `<div style="padding:8px;background:var(--bg);border-radius:6px;font-size:0.8rem;"><div style="color:var(--yellow);font-weight:600;margin-bottom:6px;">🧠 Feche os olhos e percorra seu palácio mentalmente. Depois confira:</div>${valores.map((v, i) => `<div style="padding:3px 0;"><span style="color:var(--blue);">${locais[i]}:</span> <span class="loci-hidden" onclick="this.style.color='var(--green)'" style="color:#313244;background:var(--bg-surface);border-radius:3px;padding:0 4px;cursor:pointer;">${v}</span></div>`).join('')}<p style="font-size:0.7rem;color:var(--text-muted);margin-top:6px;">Clique em cada local para revelar o conceito.</p></div>`;
}
export function limparLoci() {
  for (let i = 1; i <= 5; i++) document.getElementById(`loci-${i}`).value = '';
  document.getElementById('loci-teste').style.display = 'none';
}

// Leitura em Voz Alta
let vozInterval = null, vozSeg = 300;
export async function sortearVozAlta() {
  const data = await fetch('/api/edital?limit=200').then(r => r.json());
  const items = (data.items || data).filter(t => t.status !== 'Concluído');
  if (!items.length) return;
  const s = items[Math.floor(Math.random() * items.length)];
  document.getElementById('voz-topico').textContent = `📌 ${s.materia}: ${s.topico}`;
}
export function startVozTimer() {
  vozSeg = 300;
  clearInterval(vozInterval);
  updateVozDisplay();
  vozInterval = setInterval(() => {
    vozSeg--;
    updateVozDisplay();
    if (vozSeg <= 0) {
      clearInterval(vozInterval);
      document.getElementById('voz-timer').textContent = '🎉 FIM!';
      document.getElementById('voz-timer').style.color = 'var(--green)';
      if (Notification.permission === 'granted') new Notification('🗣️ Leitura em voz alta concluída!');
    }
  }, 1000);
}
export function stopVozTimer() { clearInterval(vozInterval); }
function updateVozDisplay() {
  const m = Math.floor(vozSeg / 60), s = vozSeg % 60;
  document.getElementById('voz-timer').textContent = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  document.getElementById('voz-timer').style.color = vozSeg < 30 ? 'var(--red)' : '#cdd6f4';
}

// Window assignments for HTML onclick
window.responderDailyChallenge = responderDailyChallenge;
window.sortearFeynman = sortearFeynman;
window.salvarFeynman = salvarFeynman;
window.sortearElaboracao = sortearElaboracao;
window.salvarElaboracao = salvarElaboracao;
window.gerarRetrieval = gerarRetrieval;
window.tentarRetrieval = tentarRetrieval;
window.revelarRetrieval = revelarRetrieval;
window.sortearCornell = sortearCornell;
window.salvarCornell = salvarCornell;
window.testarLoci = testarLoci;
window.limparLoci = limparLoci;
window.sortearVozAlta = sortearVozAlta;
window.startVozTimer = startVozTimer;
window.stopVozTimer = stopVozTimer;
window.iniciarMicroRevisao = iniciarMicroRevisao;
window.iniciarAutoavaliacao = iniciarAutoavaliacao;
window.gerarDissertativa = gerarDissertativa;
window.salvarDissertativa = salvarDissertativa;
window.autoConfianca = autoConfianca;
window.autoRegistrar = autoRegistrar;

// ============================================================
// STUDY INTELLIGENCE PANEL
// ============================================================

export async function loadStudyIntelligence() {
  const el = document.getElementById('study-intelligence-box');
  if (!el) return;
  try {
    const data = await fetch('/api/study-intelligence?limit=10').then(r => r.json());
    const resumo = data.resumo;
    const topicos = data.topicos || [];

    const nivelColors = {
      dominando: 'var(--green)',
      progredindo: 'var(--blue)',
      consolidando: 'var(--yellow)',
      precisa_reforco: 'var(--red)'
    };
    const nivelLabels = {
      dominando: '🏆 Dominando',
      progredindo: '📈 Progredindo',
      consolidando: '🔄 Consolidando',
      precisa_reforco: '⚠️ Precisa reforço'
    };

    let html = `
      <div style="display:flex;gap:12px;margin-bottom:14px;flex-wrap:wrap;">
        <div style="flex:1;min-width:100px;background:var(--bg);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.4rem;font-weight:700;color:${nivelColors[resumo.nivel_geral] || 'var(--text)'};">${resumo.dificuldade_media}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Dificuldade média</div>
        </div>
        <div style="flex:1;min-width:100px;background:var(--bg);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.4rem;font-weight:700;color:var(--blue);">${resumo.retrieval_medio}%</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Força de memória</div>
        </div>
        <div style="flex:1;min-width:100px;background:var(--bg);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:1.4rem;font-weight:700;color:${resumo.topicos_em_risco > 0 ? 'var(--red)' : 'var(--green)'};">${resumo.topicos_em_risco}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Em risco</div>
        </div>
        <div style="flex:1;min-width:100px;background:var(--bg);border-radius:8px;padding:10px;text-align:center;">
          <div style="font-size:0.9rem;font-weight:700;color:${nivelColors[resumo.nivel_geral] || 'var(--text)'};">${nivelLabels[resumo.nivel_geral] || resumo.nivel_geral}</div>
          <div style="font-size:0.68rem;color:var(--text-sub);">Nível geral</div>
        </div>
      </div>`;

    // Mapa de dificuldade por tópico (barras)
    if (topicos.length > 0) {
      html += `<div style="font-size:0.78rem;color:var(--text-sub);margin-bottom:8px;font-weight:600;">📊 Mapa de Dificuldade (seus pontos fracos primeiro):</div>`;
      html += '<div style="display:grid;gap:6px;">';
      topicos.slice(0, 8).forEach(t => {
        const diffColor = t.difficulty_score >= 60 ? 'var(--red)' : t.difficulty_score >= 35 ? 'var(--peach)' : 'var(--green)';
        const retColor = t.retrieval_strength >= 70 ? 'var(--green)' : t.retrieval_strength >= 40 ? 'var(--yellow)' : 'var(--red)';
        const label = t.desirable_difficulty === 'reduzir' ? '📉 Simplificar' :
                      t.desirable_difficulty === 'aumentar' ? '📈 +Desafio' :
                      t.desirable_difficulty === 'reforçar' ? '🔄 Reforçar' : '✅ Ideal';
        html += `<div style="background:var(--bg);border-radius:6px;padding:8px 10px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <span style="font-size:0.78rem;font-weight:600;color:var(--text);">${t.materia}${t.topico !== '(geral)' ? ' · ' + t.topico : ''}</span>
            <span style="font-size:0.65rem;padding:2px 6px;border-radius:4px;background:${diffColor};color:var(--bg);font-weight:600;">${label}</span>
          </div>
          <div style="display:flex;gap:8px;align-items:center;">
            <div style="flex:1;height:6px;background:var(--bg-elevated);border-radius:3px;overflow:hidden;" title="Dificuldade: ${t.difficulty_score}%">
              <div style="width:${t.difficulty_score}%;height:100%;background:${diffColor};border-radius:3px;"></div>
            </div>
            <span style="font-size:0.65rem;color:${diffColor};min-width:25px;text-align:right;">${t.difficulty_score}</span>
            <span style="font-size:0.65rem;color:var(--text-sub);">|</span>
            <span style="font-size:0.65rem;color:${retColor};" title="Memória: ${t.retrieval_strength}%">🧠${t.retrieval_strength}%</span>
          </div>
        </div>`;
      });
      html += '</div>';
    }

    // Interleaving recommendation
    if (data.interleaving && data.interleaving.length > 3) {
      html += `<div style="margin-top:12px;font-size:0.75rem;color:var(--text-sub);"><strong>🔀 Ordem de estudo recomendada (interleaving):</strong> ${data.interleaving.slice(0, 5).map(i => i.materia).join(' → ')}...</div>`;
    }

    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = '<p style="color:var(--text-sub);font-size:0.82rem;">Responda mais questões para gerar análise de inteligência.</p>';
  }
}
