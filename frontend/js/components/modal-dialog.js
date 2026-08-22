/**
 * <modal-dialog> — Accessible modal with slot-based content.
 * ConcurseiroOS Web Component
 */
class ModalDialog extends HTMLElement {
  static get observedAttributes() {
    return ['title', 'open', 'closable'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._onKeyDown = this._onKeyDown.bind(this);
  }

  connectedCallback() {
    this.render();
    document.addEventListener('keydown', this._onKeyDown);
  }

  disconnectedCallback() {
    document.removeEventListener('keydown', this._onKeyDown);
  }

  attributeChangedCallback() {
    this.render();
  }

  get isOpen() { return this.hasAttribute('open'); }
  get isClosable() { return !this.hasAttribute('closable') || this.getAttribute('closable') !== 'false'; }
  get titleText() { return this.getAttribute('title') || ''; }

  /** Open the modal */
  open() {
    this.setAttribute('open', '');
  }

  /** Close the modal */
  close() {
    this.removeAttribute('open');
    this.dispatchEvent(new CustomEvent('modal-close', {
      bubbles: true,
      composed: true
    }));
  }

  _onKeyDown(e) {
    if (e.key === 'Escape' && this.isOpen && this.isClosable) {
      this.close();
    }
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          font-family: var(--font-family, system-ui, sans-serif);
          color: var(--text-color, #222);
        }

        .backdrop {
          display: ${this.isOpen ? 'flex' : 'none'};
          position: fixed;
          inset: 0;
          z-index: var(--modal-z-index, 9999);
          background: var(--modal-backdrop, rgba(0, 0, 0, 0.5));
          align-items: center;
          justify-content: center;
          padding: 1rem;
          animation: fadeIn 0.2s ease;
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        @keyframes slideIn {
          from { transform: translateY(-20px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }

        .modal {
          background: var(--modal-bg, #fff);
          border-radius: var(--border-radius, 10px);
          box-shadow: var(--modal-shadow, 0 8px 32px rgba(0,0,0,0.2));
          max-width: var(--modal-max-width, 560px);
          width: 100%;
          max-height: 90vh;
          display: flex;
          flex-direction: column;
          animation: slideIn 0.25s ease;
          overflow: hidden;
        }

        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1rem 1.25rem;
          border-bottom: 1px solid var(--border-color, #eee);
        }

        .modal-title {
          font-size: 1.15rem;
          font-weight: 700;
          margin: 0;
        }

        .close-btn {
          background: none;
          border: none;
          font-size: 1.5rem;
          cursor: pointer;
          color: var(--text-muted, #888);
          line-height: 1;
          padding: 0.25rem;
          border-radius: 4px;
          transition: background 0.15s;
        }

        .close-btn:hover {
          background: var(--close-btn-hover-bg, #f0f0f0);
          color: var(--text-color, #222);
        }

        .modal-body {
          padding: 1.25rem;
          overflow-y: auto;
          flex: 1;
        }

        .modal-footer {
          padding: 0.75rem 1.25rem;
          border-top: 1px solid var(--border-color, #eee);
        }
      </style>

      <div class="backdrop" part="backdrop">
        <div class="modal" part="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div class="modal-header">
            <h2 class="modal-title" id="modal-title">${this._esc(this.titleText)}</h2>
            ${this.isClosable ? `<button class="close-btn" aria-label="Fechar">&times;</button>` : ''}
          </div>
          <div class="modal-body">
            <slot name="body"></slot>
            <slot></slot>
          </div>
          <div class="modal-footer">
            <slot name="footer"></slot>
          </div>
        </div>
      </div>
    `;

    if (this.isOpen) {
      // Close on backdrop click
      const backdrop = this.shadowRoot.querySelector('.backdrop');
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop && this.isClosable) {
          this.close();
        }
      });

      // Close button
      const closeBtn = this.shadowRoot.querySelector('.close-btn');
      if (closeBtn) {
        closeBtn.addEventListener('click', () => this.close());
      }
    }
  }

  _esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
}

customElements.define('modal-dialog', ModalDialog);
