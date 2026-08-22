/**
 * <timer-widget> — Countdown / Stopwatch timer with progress bar.
 * ConcurseiroOS Web Component
 */
class TimerWidget extends HTMLElement {
  static get observedAttributes() {
    return ['seconds', 'direction', 'auto-start', 'show-bar'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._intervalId = null;
    this._elapsed = 0;
    this._running = false;
    this._totalSeconds = 0;
  }

  connectedCallback() {
    this._totalSeconds = parseInt(this.getAttribute('seconds'), 10) || 0;
    this._elapsed = 0;
    this.render();

    if (this.hasAttribute('auto-start')) {
      this.start();
    }
  }

  disconnectedCallback() {
    this._stop();
  }

  attributeChangedCallback(name) {
    if (name === 'seconds') {
      this._totalSeconds = parseInt(this.getAttribute('seconds'), 10) || 0;
      this._elapsed = 0;
      this._stop();
      this.render();
      if (this.hasAttribute('auto-start')) {
        this.start();
      }
    } else {
      this.render();
    }
  }

  get direction() { return this.getAttribute('direction') || 'down'; }
  get showBar() { return this.hasAttribute('show-bar'); }

  /** Start the timer */
  start() {
    if (this._running) return;
    this._running = true;
    this._intervalId = setInterval(() => this._tick(), 1000);
    this.render();
  }

  /** Pause the timer */
  pause() {
    this._stop();
    this.render();
  }

  /** Reset the timer */
  reset() {
    this._stop();
    this._elapsed = 0;
    this.render();
  }

  /** Get current time in seconds */
  getTime() {
    if (this.direction === 'down') {
      return Math.max(0, this._totalSeconds - this._elapsed);
    }
    return this._elapsed;
  }

  _stop() {
    if (this._intervalId) {
      clearInterval(this._intervalId);
      this._intervalId = null;
    }
    this._running = false;
  }

  _tick() {
    this._elapsed++;

    this.dispatchEvent(new CustomEvent('timer-tick', {
      bubbles: true,
      composed: true,
      detail: { time: this.getTime(), elapsed: this._elapsed }
    }));

    if (this.direction === 'down' && this._elapsed >= this._totalSeconds) {
      this._stop();
      this.dispatchEvent(new CustomEvent('timer-complete', {
        bubbles: true,
        composed: true,
        detail: { elapsed: this._elapsed }
      }));
    }

    this.render();
  }

  _formatTime(totalSec) {
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    const pad = (n) => String(n).padStart(2, '0');
    if (h > 0) return `${pad(h)}:${pad(m)}:${pad(s)}`;
    return `${pad(m)}:${pad(s)}`;
  }

  render() {
    const currentTime = this.getTime();
    const progress = this.direction === 'down' && this._totalSeconds > 0
      ? ((this._totalSeconds - this._elapsed) / this._totalSeconds) * 100
      : this._totalSeconds > 0
        ? (this._elapsed / this._totalSeconds) * 100
        : 0;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: inline-block;
          font-family: var(--font-family, system-ui, sans-serif);
          color: var(--text-color, #222);
        }

        .timer-container {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0.5rem;
          padding: 0.75rem 1.25rem;
          border: 1px solid var(--border-color, #ddd);
          border-radius: var(--border-radius, 8px);
          background: var(--card-bg, #fff);
          min-width: 120px;
        }

        .time-display {
          font-size: 1.75rem;
          font-weight: 700;
          font-variant-numeric: tabular-nums;
          letter-spacing: 0.05em;
          color: var(--timer-color, var(--text-color, #222));
        }

        .time-display.warning {
          color: var(--timer-warning-color, #e65100);
        }

        .time-display.danger {
          color: var(--timer-danger-color, #c62828);
          animation: pulse 1s infinite;
        }

        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }

        .progress-bar-container {
          width: 100%;
          height: 6px;
          background: var(--progress-track-bg, #e0e0e0);
          border-radius: 3px;
          overflow: hidden;
        }

        .progress-bar-fill {
          height: 100%;
          background: var(--timer-bar-color, #1976d2);
          border-radius: 3px;
          transition: width 1s linear;
          width: ${Math.max(0, Math.min(100, progress))}%;
        }

        .status {
          font-size: 0.7rem;
          text-transform: uppercase;
          letter-spacing: 0.1em;
          color: var(--text-muted, #888);
        }
      </style>

      <div class="timer-container">
        <div class="time-display ${this.direction === 'down' && currentTime <= 10 ? 'danger' : this.direction === 'down' && currentTime <= 30 ? 'warning' : ''}">
          ${this._formatTime(currentTime)}
        </div>
        ${this.showBar ? `
          <div class="progress-bar-container">
            <div class="progress-bar-fill"></div>
          </div>
        ` : ''}
        <div class="status">${this._running ? '▶ running' : '⏸ paused'}</div>
      </div>
    `;
  }
}

customElements.define('timer-widget', TimerWidget);
