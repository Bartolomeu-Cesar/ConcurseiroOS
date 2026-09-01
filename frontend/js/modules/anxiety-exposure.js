/**
 * Anxiety Management — Exposição Gradual
 * Módulo para dessensibilização progressiva à pressão de prova.
 */

import { showToast } from './toast.js';

// ─── Constantes ────────────────────────────────────────────────────────────────

const API_BASE = '/api/study-intelligence/anxiety-exposure';
const NIVEL_CORES = { 1: '#a6e3a1', 2: '#f9e2af', 3: '#fab387', 4: '#f38ba8' };
const NIVEL_LABELS = { 1: 'Relaxado', 2: 'Moderado', 3: 'Intenso', 4: 'Extremo' };

// ─── Helpers ───────────────────────────────────────────────────────────────────

function authHeaders() {
    const token = localStorage.getItem('auth_token');
    return {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {})
    };
}

async function fetchNivel(nivel) {
    const res = await fetch(`${API_BASE}?nivel=${nivel}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(`Erro ao buscar nível: ${res.status}`);
    return res.json();
}

async function registrarSessao(payload) {
    const res = await fetch(`${API_BASE}/registrar`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(`Erro ao registrar sessão: ${res.status}`);
    return res.json();
}

function injectStyles() {
    if (document.getElementById('anxiety-exposure-styles')) return;
    const style = document.createElement('style');
    style.id = 'anxiety-exposure-styles';
    style.textContent = `
        /* ─── Anxiety Card ──────────────────────────────────────── */
        .anxiety-card {
            background: var(--surface0, #313244);
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid var(--surface1, #45475a);
        }
        .anxiety-card__header {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }
        .anxiety-card__header h3 {
            margin: 0;
            font-size: 1.1rem;
            color: var(--text, #cdd6f4);
        }
        .anxiety-card__progress {
            font-size: 0.85rem;
            color: var(--subtext0, #a6adc8);
            margin-bottom: 1rem;
        }
        .anxiety-card__levels {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            margin-bottom: 1rem;
        }
        .anxiety-card__level-btn {
            padding: 0.5rem 1rem;
            border: 2px solid transparent;
            border-radius: 8px;
            background: var(--surface1, #45475a);
            color: var(--text, #cdd6f4);
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            min-width: 0;
        }
        .anxiety-card__level-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .anxiety-card__level-btn--active {
            border-color: currentColor;
            background: color-mix(in srgb, currentColor 15%, var(--surface1, #45475a));
        }
        .anxiety-card__dicas {
            background: var(--mantle, #1e1e2e);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
            font-size: 0.85rem;
            color: var(--subtext1, #bac2de);
        }
        .anxiety-card__dicas ul {
            margin: 0.5rem 0 0 1.2rem;
            padding: 0;
        }
        .anxiety-card__dicas li {
            margin-bottom: 0.3rem;
        }
        .anxiety-card__start-btn {
            width: 100%;
            padding: 0.75rem;
            border: none;
            border-radius: 8px;
            background: var(--mauve, #cba6f7);
            color: var(--base, #1e1e2e);
            font-weight: 700;
            font-size: 1rem;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .anxiety-card__start-btn:hover {
            opacity: 0.85;
        }
        .anxiety-card__start-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* ─── Overlay Pré-Sessão ────────────────────────────────── */
        .anxiety-overlay {
            position: fixed;
            inset: 0;
            z-index: 9999;
            background: var(--base, #1e1e2e);
            color: var(--text, #cdd6f4);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 1.5rem;
            overflow-y: auto;
            animation: anxiety-fadein 0.3s ease;
        }
        @keyframes anxiety-fadein {
            from { opacity: 0; transform: scale(0.97); }
            to { opacity: 1; transform: scale(1); }
        }
        .anxiety-overlay__content {
            width: 100%;
            max-width: 480px;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }
        .anxiety-overlay__close {
            position: absolute;
            top: 1rem;
            right: 1rem;
            background: none;
            border: none;
            color: var(--subtext0, #a6adc8);
            font-size: 1.5rem;
            cursor: pointer;
        }
        .anxiety-overlay__nivel-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 1.3rem;
            font-weight: 700;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            align-self: center;
        }
        .anxiety-overlay__desc {
            text-align: center;
            font-size: 0.95rem;
            color: var(--subtext1, #bac2de);
        }
        .anxiety-overlay__pressao {
            text-align: center;
            font-weight: 600;
            font-size: 1rem;
            color: var(--peach, #fab387);
            font-style: italic;
        }

        /* Slider */
        .anxiety-slider {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.5rem;
        }
        .anxiety-slider__label {
            font-size: 0.9rem;
            color: var(--subtext0, #a6adc8);
        }
        .anxiety-slider__value {
            font-size: 2rem;
            font-weight: 700;
        }
        .anxiety-slider input[type="range"] {
            width: 100%;
            max-width: 320px;
            accent-color: var(--mauve, #cba6f7);
            height: 8px;
        }
        .anxiety-slider__scale {
            display: flex;
            justify-content: space-between;
            width: 100%;
            max-width: 320px;
            font-size: 0.75rem;
            color: var(--subtext0, #a6adc8);
        }

        .anxiety-overlay__dicas {
            background: var(--surface0, #313244);
            border-radius: 8px;
            padding: 1rem;
            font-size: 0.85rem;
        }
        .anxiety-overlay__dicas ul {
            margin: 0.5rem 0 0 1.2rem;
            padding: 0;
        }
        .anxiety-overlay__start-btn {
            padding: 1rem;
            border: none;
            border-radius: 10px;
            font-size: 1.1rem;
            font-weight: 700;
            cursor: pointer;
            color: var(--base, #1e1e2e);
            transition: transform 0.15s, opacity 0.2s;
        }
        .anxiety-overlay__start-btn:hover {
            transform: scale(1.02);
        }

        /* ─── Modal Pós-Sessão ──────────────────────────────────── */
        .anxiety-post-backdrop {
            position: fixed;
            inset: 0;
            z-index: 10000;
            background: rgba(0,0,0,0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
            animation: anxiety-fadein 0.3s ease;
        }
        .anxiety-post-modal {
            background: var(--surface0, #313244);
            border-radius: 16px;
            padding: 2rem;
            width: 100%;
            max-width: 440px;
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
            max-height: 90vh;
            overflow-y: auto;
        }
        .anxiety-post-modal__title {
            text-align: center;
            font-size: 1.2rem;
            font-weight: 700;
            color: var(--text, #cdd6f4);
        }
        .anxiety-post-modal__comparison {
            display: flex;
            justify-content: center;
            gap: 2rem;
            flex-wrap: wrap;
        }
        .anxiety-post-modal__comparison-item {
            text-align: center;
        }
        .anxiety-post-modal__comparison-item span {
            display: block;
            font-size: 0.8rem;
            color: var(--subtext0, #a6adc8);
            margin-bottom: 0.25rem;
        }
        .anxiety-post-modal__comparison-item strong {
            font-size: 1.8rem;
        }
        .anxiety-post-modal__feedback {
            text-align: center;
            font-size: 0.95rem;
            padding: 0.75rem;
            border-radius: 8px;
            background: var(--mantle, #1e1e2e);
            color: var(--text, #cdd6f4);
        }
        .anxiety-post-modal__save-btn {
            padding: 0.75rem;
            border: none;
            border-radius: 8px;
            background: var(--green, #a6e3a1);
            color: var(--base, #1e1e2e);
            font-weight: 700;
            font-size: 1rem;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .anxiety-post-modal__save-btn:hover {
            opacity: 0.85;
        }
        .anxiety-post-modal__save-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
    `;
    document.head.appendChild(style);
}

// ─── State ─────────────────────────────────────────────────────────────────────

let _selectedNivel = 1;
let _nivelData = null;
let _ansiedadeAntes = 5;

// ─── renderAnxietyCard ─────────────────────────────────────────────────────────

export async function renderAnxietyCard(container) {
    injectStyles();

    container.innerHTML = '<p style="color:var(--subtext0);text-align:center;">Carregando...</p>';

    try {
        _nivelData = await fetchNivel(_selectedNivel);
    } catch (err) {
        container.innerHTML = `<p style="color:var(--red,#f38ba8)">Erro ao carregar dados de ansiedade.</p>`;
        showToast('Erro ao carregar Exposição Gradual', 'error');
        return;
    }

    const { nivel_recomendado, config, dicas_anti_ansiedade, progresso_exposicao } = _nivelData;

    const dicasHtml = (dicas_anti_ansiedade || []).map(d => `<li>${d}</li>`).join('');

    container.innerHTML = `
        <div class="anxiety-card">
            <div class="anxiety-card__header">
                <span style="font-size:1.5rem">${config.emoji || '🧘'}</span>
                <h3>Exposição Gradual à Pressão</h3>
            </div>

            <div class="anxiety-card__progress">
                📊 ${progresso_exposicao.simulados_feitos} simulados feitos
                ${progresso_exposicao.proximo_nivel_em > 0 ? `· Próximo nível em ${progresso_exposicao.proximo_nivel_em} sessões` : ''}
                · Nível recomendado: <strong style="color:${NIVEL_CORES[nivel_recomendado]}">${nivel_recomendado}</strong>
            </div>

            <div class="anxiety-card__levels" role="group" aria-label="Seleção de nível">
                ${[1, 2, 3, 4].map(n => `
                    <button
                        class="anxiety-card__level-btn ${n === _selectedNivel ? 'anxiety-card__level-btn--active' : ''}"
                        style="color:${NIVEL_CORES[n]}"
                        onclick="window._anxietySelectNivel(${n})"
                        title="Nível ${n} — ${NIVEL_LABELS[n]}"
                    >
                        ${n}. ${NIVEL_LABELS[n]}
                    </button>
                `).join('')}
            </div>

            ${dicasHtml ? `
            <div class="anxiety-card__dicas">
                💡 <strong>Dicas anti-ansiedade:</strong>
                <ul>${dicasHtml}</ul>
            </div>` : ''}

            <button class="anxiety-card__start-btn" onclick="window.startAnxietySession(${_selectedNivel})" title="Iniciar sessão de exposição">
                🚀 Iniciar Sessão — Nível ${_selectedNivel}
            </button>
        </div>
    `;
}

// Seleção de nível no card (re-renderiza)
window._anxietySelectNivel = async function (nivel) {
    _selectedNivel = nivel;
    const container = document.querySelector('.anxiety-card')?.parentElement;
    if (container) await renderAnxietyCard(container);
};

// ─── startAnxietySession ───────────────────────────────────────────────────────

export async function startAnxietySession(nivel) {
    injectStyles();
    _selectedNivel = nivel;

    let data;
    try {
        data = await fetchNivel(nivel);
        _nivelData = data;
    } catch (err) {
        showToast('Erro ao carregar sessão', 'error');
        return;
    }

    const { config, dicas_anti_ansiedade, tempo_ajustado_min } = data;
    const cor = NIVEL_CORES[nivel];
    const dicasHtml = (dicas_anti_ansiedade || []).map(d => `<li>${d}</li>`).join('');

    const overlay = document.createElement('div');
    overlay.className = 'anxiety-overlay';
    overlay.id = 'anxiety-pre-overlay';
    overlay.innerHTML = `
        <button class="anxiety-overlay__close" onclick="window._anxietyCloseOverlay()" title="Fechar" aria-label="Fechar">✕</button>
        <div class="anxiety-overlay__content">
            <div class="anxiety-overlay__nivel-badge" style="background:color-mix(in srgb, ${cor} 20%, var(--surface0, #313244));color:${cor}">
                ${config.emoji || '🧘'} Nível ${nivel} — ${config.nome}
            </div>

            <p class="anxiety-overlay__desc">${config.descricao || ''}</p>

            ${config.mensagem_pressao ? `<p class="anxiety-overlay__pressao">"${config.mensagem_pressao}"</p>` : ''}

            <div class="anxiety-slider">
                <span class="anxiety-slider__label">Como você se sente <strong>AGORA</strong>?</span>
                <span class="anxiety-slider__value" id="anxiety-pre-value">5</span>
                <input type="range" min="1" max="10" value="5" id="anxiety-pre-slider" aria-label="Nível de ansiedade agora (1 calmo a 10 pânico)"
                    oninput="document.getElementById('anxiety-pre-value').textContent=this.value" />
                <div class="anxiety-slider__scale">
                    <span>1 — Calmo</span>
                    <span>10 — Pânico</span>
                </div>
            </div>

            <div style="font-size:0.85rem;color:var(--subtext0);">
                ⏱️ Tempo ajustado: <strong>${tempo_ajustado_min} min</strong>
                ${config.cronometro_visivel ? ' · Cronômetro visível' : ' · Cronômetro oculto'}
                ${config.ranking_visivel ? ' · Ranking ativo' : ''}
                ${config.penalizacao ? ' · Penalização ativa' : ''}
            </div>

            ${dicasHtml ? `
            <div class="anxiety-overlay__dicas">
                💡 <strong>Respire fundo. Lembre-se:</strong>
                <ul>${dicasHtml}</ul>
            </div>` : ''}

            <button class="anxiety-overlay__start-btn" style="background:${cor}" onclick="window._anxietyBeginSimulado()">
                ⚡ Começar Simulado
            </button>
        </div>
    `;

    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
}

window._anxietyCloseOverlay = function () {
    const el = document.getElementById('anxiety-pre-overlay');
    if (el) el.remove();
    document.body.style.overflow = '';
};

window._anxietyBeginSimulado = function () {
    const slider = document.getElementById('anxiety-pre-slider');
    _ansiedadeAntes = slider ? parseInt(slider.value, 10) : 5;

    // Salvar parâmetros de pressão no localStorage para questoes.html consumir
    const pressaoConfig = {
        anxiety_nivel: _selectedNivel,
        anxiety_ansiedade_antes: _ansiedadeAntes,
        tempo_ajustado_min: _nivelData.tempo_ajustado_min,
        cronometro_visivel: _nivelData.config.cronometro_visivel,
        ranking_visivel: _nivelData.config.ranking_visivel,
        penalizacao: _nivelData.config.penalizacao,
        nota_corte_visivel: _nivelData.config.nota_corte_visivel,
        nota_corte: _nivelData.nota_corte,
        distracoes: _nivelData.config.distracoes,
        mensagem_pressao: _nivelData.config.mensagem_pressao,
        tempo_fator: _nivelData.config.tempo_fator,
        started_at: Date.now()
    };
    localStorage.setItem('anxiety_session', JSON.stringify(pressaoConfig));

    window._anxietyCloseOverlay();
    window.location.href = '/questoes.html?mode=anxiety';
};

// ─── showAnxietyPostSession ────────────────────────────────────────────────────

export function showAnxietyPostSession(nivel, nota) {
    injectStyles();

    const session = JSON.parse(localStorage.getItem('anxiety_session') || '{}');
    const ansiedadeAntes = session.anxiety_ansiedade_antes || _ansiedadeAntes;
    const tempoSeg = session.started_at ? Math.round((Date.now() - session.started_at) / 1000) : 0;
    const cor = NIVEL_CORES[nivel] || NIVEL_CORES[1];

    const backdrop = document.createElement('div');
    backdrop.className = 'anxiety-post-backdrop';
    backdrop.id = 'anxiety-post-backdrop';
    backdrop.innerHTML = `
        <div class="anxiety-post-modal">
            <div class="anxiety-post-modal__title">
                🏁 Sessão Finalizada — Nível ${nivel}
            </div>

            <div class="anxiety-slider">
                <span class="anxiety-slider__label">Como você se sente <strong>AGORA</strong> (pós-sessão)?</span>
                <span class="anxiety-slider__value" id="anxiety-post-value">5</span>
                <input type="range" min="1" max="10" value="5" id="anxiety-post-slider" aria-label="Nível de ansiedade após a exposição (1 calmo a 10 pânico)"
                    oninput="document.getElementById('anxiety-post-value').textContent=this.value" />
                <div class="anxiety-slider__scale">
                    <span>1 — Calmo</span>
                    <span>10 — Pânico</span>
                </div>
            </div>

            <div class="anxiety-post-modal__comparison">
                <div class="anxiety-post-modal__comparison-item">
                    <span>Antes</span>
                    <strong style="color:${NIVEL_CORES[Math.min(4, Math.ceil(ansiedadeAntes / 3))]}">${ansiedadeAntes}</strong>
                </div>
                <div class="anxiety-post-modal__comparison-item">
                    <span>Depois</span>
                    <strong style="color:var(--subtext0)" id="anxiety-post-depois">5</strong>
                </div>
                <div class="anxiety-post-modal__comparison-item">
                    <span>Nota</span>
                    <strong style="color:${cor}">${nota != null ? nota + '%' : '—'}</strong>
                </div>
            </div>

            <div class="anxiety-post-modal__feedback" id="anxiety-post-feedback">
                Ajuste o slider acima para ver o feedback.
            </div>

            <button class="anxiety-post-modal__save-btn" id="anxiety-post-save" onclick="window._anxietySavePost(${nivel}, ${nota ?? 'null'}, ${tempoSeg})">
                💾 Salvar e Fechar
            </button>
        </div>
    `;

    document.body.appendChild(backdrop);
    document.body.style.overflow = 'hidden';

    // Atualizar feedback em tempo real
    const postSlider = document.getElementById('anxiety-post-slider');
    const depoisEl = document.getElementById('anxiety-post-depois');
    const feedbackEl = document.getElementById('anxiety-post-feedback');

    postSlider?.addEventListener('input', () => {
        const val = parseInt(postSlider.value, 10);
        depoisEl.textContent = val;
        feedbackEl.textContent = _getFeedback(ansiedadeAntes, val);
    });

    // Fechar ao clicar no backdrop
    backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) {
            backdrop.remove();
            document.body.style.overflow = '';
        }
    });
}

function _getFeedback(antes, depois) {
    const diff = antes - depois;
    if (diff >= 4) return '🎉 Incrível! Sua ansiedade caiu muito. A exposição está funcionando!';
    if (diff >= 2) return '💪 Ótimo progresso! Você está se habituando à pressão.';
    if (diff >= 0) return '👍 Manteve o controle. Continue praticando!';
    if (diff >= -2) return '🫂 A ansiedade subiu um pouco — é normal nos primeiros simulados. Persista!';
    return '❤️ Foi difícil, mas você enfrentou. Coragem é praticar mesmo com medo.';
}

window._anxietySavePost = async function (nivel, nota, tempoSeg) {
    const postSlider = document.getElementById('anxiety-post-slider');
    const ansiedadeDepois = postSlider ? parseInt(postSlider.value, 10) : 5;
    const session = JSON.parse(localStorage.getItem('anxiety_session') || '{}');
    const ansiedadeAntes = session.anxiety_ansiedade_antes || _ansiedadeAntes;

    const btn = document.getElementById('anxiety-post-save');
    if (btn) { btn.disabled = true; btn.textContent = 'Salvando...'; }

    try {
        await registrarSessao({
            nivel,
            nota,
            tempo_seg: tempoSeg,
            completou: true,
            ansiedade_antes: ansiedadeAntes,
            ansiedade_depois: ansiedadeDepois
        });

        showToast('Sessão registrada com sucesso! 🧠', 'success');
        localStorage.removeItem('anxiety_session');

        const backdrop = document.getElementById('anxiety-post-backdrop');
        if (backdrop) backdrop.remove();
        document.body.style.overflow = '';
    } catch (err) {
        showToast('Erro ao salvar sessão', 'error');
        if (btn) { btn.disabled = false; btn.textContent = '💾 Salvar e Fechar'; }
    }
};

// ─── Window exports (onclick inline) ──────────────────────────────────────────

window.startAnxietySession = startAnxietySession;
window.showAnxietyPostSession = showAnxietyPostSession;
