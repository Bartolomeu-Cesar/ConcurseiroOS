/**
 * <question-card> — Renders a question with clickable alternatives.
 * ConcurseiroOS Web Component
 *
 * @usage
 * <!-- Answer mode (default): user can select alternatives -->
 * <question-card
 *   enunciado="Qual é a capital do Brasil?"
 *   materia="Geografia"
 *   dificuldade="Fácil"
 *   alternativas='{"a":"São Paulo","b":"Brasília","c":"Rio de Janeiro","d":"Salvador"}'
 *   resposta-correta="b"
 *   mode="answer">
 * </question-card>
 *
 * <!-- Review mode: shows correct/wrong answers -->
 * <question-card
 *   enunciado="Qual é a capital do Brasil?"
 *   materia="Geografia"
 *   dificuldade="Fácil"
 *   alternativas='{"a":"São Paulo","b":"Brasília","c":"Rio de Janeiro","d":"Salvador"}'
 *   resposta-correta="b"
 *   mode="review">
 * </question-card>
 *
 * @attributes
 *   enunciado        — The question text
 *   materia          — Subject badge (optional)
 *   dificuldade      — Difficulty badge (optional)
 *   alternativas     — JSON object of letter->text pairs
 *   resposta-correta — Correct answer letter
 *   mode             — "answer" (interactive) or "review" (shows results)
 *
 * @events
 *   answer-selected  — Fired when user picks an alternative
 *                      detail: { letter, correct }
 */
class QuestionCard extends HTMLElement {
  static get observedAttributes() {
    return ['enunciado', 'materia', 'dificuldade', 'alternativas', 'resposta-correta', 'mode'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._selected = null;
  }

  connectedCallback() {
    this.render();
  }

  attributeChangedCallback() {
    this.render();
  }

  get enunciado() { return this.getAttribute('enunciado') || ''; }
  get materia() { return this.getAttribute('materia') || ''; }
  get dificuldade() { return this.getAttribute('dificuldade') || ''; }
  get respostaCorreta() { return this.getAttribute('resposta-correta') || ''; }
  get mode() { return this.getAttribute('mode') || 'answer'; }

  get alternativas() {
    const raw = this.getAttribute('alternativas');
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }

  render() {
    const alts = this.alternativas;
    const letters = Object.keys(alts);
    const isReview = this.mode === 'review';

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: var(--font-family, system-ui, sans-serif);
          border: 1px solid var(--border-color, #ddd);
          border-radius: var(--border-radius, 8px);
          padding: 1.25rem;
          background: var(--card-bg, #fff);
          color: var(--text-color, #222);
          box-shadow: var(--card-shadow, 0 2px 6px rgba(0,0,0,0.08));
        }

        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.75rem;
          gap: 0.5rem;
          flex-wrap: wrap;
        }

        .badge {
          font-size: 0.75rem;
          padding: 0.2em 0.6em;
          border-radius: 4px;
          background: var(--badge-bg, #e8e8e8);
          color: var(--badge-color, #555);
          font-weight: 600;
        }

        .badge.dificuldade {
          background: var(--badge-dificuldade-bg, #ffeeba);
          color: var(--badge-dificuldade-color, #856404);
        }

        .enunciado {
          font-size: 1rem;
          line-height: 1.5;
          margin-bottom: 1rem;
        }

        .alternativas {
          list-style: none;
          padding: 0;
          margin: 0;
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }

        .alternativa {
          display: flex;
          align-items: flex-start;
          gap: 0.75rem;
          padding: 0.75rem 1rem;
          border: 2px solid var(--alt-border, #e0e0e0);
          border-radius: var(--border-radius, 6px);
          cursor: pointer;
          transition: background 0.2s, border-color 0.2s;
          user-select: none;
        }

        .alternativa:hover:not(.disabled) {
          background: var(--alt-hover-bg, #f5f5f5);
          border-color: var(--alt-hover-border, #aaa);
        }

        .alternativa.selected {
          background: var(--alt-selected-bg, #e3f2fd);
          border-color: var(--alt-selected-border, #1976d2);
        }

        .alternativa.correct {
          background: var(--alt-correct-bg, #e8f5e9);
          border-color: var(--alt-correct-border, #388e3c);
        }

        .alternativa.wrong {
          background: var(--alt-wrong-bg, #ffebee);
          border-color: var(--alt-wrong-border, #d32f2f);
        }

        .alternativa.disabled {
          cursor: default;
        }

        .letter {
          font-weight: 700;
          min-width: 1.5em;
          text-transform: uppercase;
        }

        .text {
          flex: 1;
        }

        .feedback-icon {
          margin-left: auto;
          font-size: 1.1rem;
        }
      </style>

      <div class="header">
        ${this.materia ? `<span class="badge materia">${this._esc(this.materia)}</span>` : ''}
        ${this.dificuldade ? `<span class="badge dificuldade">${this._esc(this.dificuldade)}</span>` : ''}
      </div>

      <div class="enunciado">${this._esc(this.enunciado)}</div>

      <ul class="alternativas">
        ${letters.map(letter => {
          let classes = 'alternativa';
          let icon = '';

          if (isReview) {
            classes += ' disabled';
            if (letter === this.respostaCorreta) {
              classes += ' correct';
              icon = '<span class="feedback-icon">✓</span>';
            } else if (letter === this._selected && letter !== this.respostaCorreta) {
              classes += ' wrong';
              icon = '<span class="feedback-icon">✗</span>';
            }
          } else {
            if (letter === this._selected) {
              classes += ' selected';
            }
          }

          return `
            <li class="${classes}" data-letter="${letter}">
              <span class="letter">${this._esc(letter)})</span>
              <span class="text">${this._esc(alts[letter])}</span>
              ${icon}
            </li>
          `;
        }).join('')}
      </ul>
    `;

    if (!isReview) {
      this.shadowRoot.querySelectorAll('.alternativa').forEach(el => {
        el.addEventListener('click', () => {
          const letter = el.dataset.letter;
          this._selected = letter;
          this.dispatchEvent(new CustomEvent('answer-selected', {
            bubbles: true,
            composed: true,
            detail: {
              letter,
              correct: letter === this.respostaCorreta
            }
          }));
          this.render();
        });
      });
    }
  }

  _esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
}

customElements.define('question-card', QuestionCard);
