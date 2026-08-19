// Timer Global - Widget flutuante que funciona em todas as páginas
// Persiste via localStorage para manter contagem entre navegações
(function initGlobalTimer() {
    function getTimerState() {
        const raw = localStorage.getItem('pomo_timer');
        if (!raw) return null;
        try { return JSON.parse(raw); } catch(e) { return null; }
    }
    function setTimerState(state) { localStorage.setItem('pomo_timer', JSON.stringify(state)); }
    function clearTimerState() { localStorage.removeItem('pomo_timer'); }

    function createWidget() {
        if (document.getElementById('global-timer-widget')) return;
        const div = document.createElement('div');
        div.id = 'global-timer-widget';
        div.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;">
                <span id="gtw-materia" style="font-size:0.75rem;color:#cba6f7;font-weight:600;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></span>
                <span id="gtw-time" style="font-size:1.1rem;font-weight:700;color:#cdd6f4;font-family:monospace;"></span>
                <button id="gtw-pause" onclick="globalTimerToggle()" style="background:#a6e3a1;color:#1e1e2e;border:none;border-radius:4px;padding:3px 8px;font-size:0.7rem;font-weight:600;cursor:pointer;">⏸</button>
                <button onclick="globalTimerStop()" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:4px;padding:3px 8px;font-size:0.7rem;font-weight:600;cursor:pointer;">⏹</button>
                <a href="/dashboard.html" style="font-size:0.65rem;color:#89b4fa;text-decoration:none;" title="Voltar ao calendário">📅</a>
            </div>
        `;
        div.style.cssText = 'position:fixed;bottom:16px;right:16px;background:#313244;border:2px solid #cba6f7;border-radius:12px;padding:10px 14px;z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,0.4);';
        document.body.appendChild(div);
    }

    function removeWidget() {
        const w = document.getElementById('global-timer-widget');
        if (w) w.remove();
    }

    function updateWidget(state) {
        const timeEl = document.getElementById('gtw-time');
        const matEl = document.getElementById('gtw-materia');
        const pauseBtn = document.getElementById('gtw-pause');
        if (!timeEl) return;

        if (state.paused) {
            const pausedSec = Math.max(0, Math.floor(state.remainingWhenPaused / 1000));
            const pm = Math.floor(pausedSec / 60);
            const ps = pausedSec % 60;
            timeEl.textContent = `${String(pm).padStart(2,'0')}:${String(ps).padStart(2,'0')}`;
            timeEl.style.color = '#f9e2af';
        } else {
            const remaining = Math.max(0, state.endTime - Date.now());
            const totalSec = Math.floor(remaining / 1000);
            const m = Math.floor(totalSec / 60);
            const s = totalSec % 60;

            if (totalSec <= 0) {
                timeEl.textContent = '🎉 FIM!';
                timeEl.style.color = '#a6e3a1';
                if (Notification.permission === 'granted') {
                    new Notification('⏰ Timer finalizado!', {body: `Sessão de ${state.materia} concluída!`});
                }
                const horas = state.totalSeconds / 3600;
                fetch('/api/sessoes-estudo/registrar', {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ horas: Math.round(horas * 100) / 100, materia: state.materia, tipo: 'pomodoro' })
                }).catch(() => {});
                clearTimerState();
                setTimeout(() => {
                    removeWidget();
                    window.location.href = '/dashboard.html';
                }, 3000);
                return;
            }

            timeEl.textContent = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
            timeEl.style.color = totalSec < 60 ? '#f38ba8' : '#cdd6f4';
        }

        matEl.textContent = state.materia;
        if (pauseBtn) pauseBtn.textContent = state.paused ? '▶' : '⏸';
    }

    window.globalTimerToggle = function() {
        const state = getTimerState();
        if (!state) return;
        if (state.paused) {
            state.endTime = Date.now() + state.remainingWhenPaused;
            state.paused = false;
        } else {
            state.remainingWhenPaused = state.endTime - Date.now();
            state.paused = true;
        }
        setTimerState(state);
    };

    window.globalTimerStop = function() {
        if (confirm('Parar o timer e voltar ao calendário?')) {
            clearTimerState();
            removeWidget();
            window.location.href = '/dashboard.html';
        }
    };

    window.startGlobalTimer = function(materia, tempoMin, tipo) {
        const state = {
            materia: materia,
            tipo: tipo || 'estudo',
            totalSeconds: tempoMin * 60,
            endTime: Date.now() + tempoMin * 60 * 1000,
            paused: false,
            remainingWhenPaused: 0
        };
        setTimerState(state);
        createWidget();
        updateWidget(state);
    };

    // Loop: verifica timer a cada segundo
    setInterval(() => {
        const state = getTimerState();
        if (state) {
            if (!document.getElementById('global-timer-widget')) createWidget();
            updateWidget(state);
        } else {
            removeWidget();
        }
    }, 1000);

    // Check inicial
    const initialState = getTimerState();
    if (initialState) {
        createWidget();
        updateWidget(initialState);
    }

    // Pedir permissão de notificação
    if (Notification.permission === 'default') Notification.requestPermission();
})();
