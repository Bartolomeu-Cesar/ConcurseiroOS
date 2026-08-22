/**
 * <progress-bar> — Animated progress bar with auto-coloring.
 * ConcurseiroOS Web Component
 *
 * @usage
 * <!-- Basic with label and percentage -->
 * <progress-bar value="72" label="Direito Constitucional" show-pct></progress-bar>
 *
 * <!-- Custom color (overrides auto-coloring) -->
 * <progress-bar value="45" label="Administrativo" color="#89b4fa" show-pct></progress-bar>
 *
 * <!-- Auto-coloring: red <30%, yellow 30-70%, green >70% -->
 * <progress-bar value="20" label="Penal" show-pct></progress-bar>
 *
 * <!-- Minimal (no label, no percentage) -->
 * <progress-bar value="60"></progress-bar>
 *
 * @attributes
 *   value    — Percentage value 0–100 (required)
 *   label    — Text label shown above the bar (optional)
 *   color    — Custom bar color, overrides auto-coloring (optional)
 *   show-pct — If present, shows percentage number
 *
 * @css-custom-properties
 *   --progress-height       — Bar height (default: 10px)
 *   --progress-track-bg     — Track background color
 *   --progress-color-low    — Color when <30% (default: red)
 *   --progress-color-mid    — Color when 30-70% (default: yellow)
 *   --progress-color-high   — Color when >70% (default: green)
 */
class ProgressBar extends HTMLElement {
  static get observedAttributes() {
    return ['value', 'label', 'color', 'show-pct'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  connectedCallback() {
    this.render();
  }

  attributeChangedCallback() {
    this.render();
  }

  get value() {
    const v = parseFloat(this.getAttribute('value'));
    return isNaN(v) ? 0 : Math.max(0, Math.min(100, v));
  }

  get label() { return this.getAttribute('label') || ''; }
  get showPct() { return this.hasAttribute('show-pct'); }

  get barColor() {
    const explicit = this.getAttribute('color');
    if (explicit) return explicit;
    const v = this.value;
    if (v < 30) return 'var(--progress-color-low, #d32f2f)';
    if (v < 70) return 'var(--progress-color-mid, #fbc02d)';
    return 'var(--progress-color-high, #388e3c)';
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: var(--font-family, system-ui, sans-serif);
          color: var(--text-color, #222);
        }

        .wrapper {
          display: flex;
          flex-direction: column;
          gap: 0.35rem;
        }

        .header {
          display: flex;
          justify-content: space-between;
          align-items: baseline;
          font-size: 0.85rem;
        }

        .label {
          font-weight: 600;
          color: var(--text-color, #222);
        }

        .pct {
          font-weight: 700;
          font-variant-numeric: tabular-nums;
          color: var(--text-muted, #666);
        }

        .track {
          width: 100%;
          height: var(--progress-height, 10px);
          background: var(--progress-track-bg, #e0e0e0);
          border-radius: 999px;
          overflow: hidden;
        }

        .fill {
          height: 100%;
          border-radius: 999px;
          transition: width 0.5s ease, background-color 0.4s ease;
          width: ${this.value}%;
          background-color: ${this.barColor};
        }
      </style>

      <div class="wrapper">
        ${(this.label || this.showPct) ? `
          <div class="header">
            <span class="label">${this._esc(this.label)}</span>
            ${this.showPct ? `<span class="pct">${Math.round(this.value)}%</span>` : ''}
          </div>
        ` : ''}
        <div class="track">
          <div class="fill"></div>
        </div>
      </div>
    `;
  }

  _esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
}

customElements.define('progress-bar', ProgressBar);
