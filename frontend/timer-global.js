// Timer Global - Widget flutuante que funciona em todas as páginas
// Persiste via localStorage para manter contagem entre navegações
(function initGlobalTimer() {
    // ===== AUDIO ALARM SYSTEM =====
    let alarmAudioCtx = null;
    function playAlarmSound() {
        try {
            // Generate alarm sound using Web Audio API (no external file needed)
            if (!alarmAudioCtx) alarmAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const ctx = alarmAudioCtx;

            // Play a pleasant multi-tone chime (3 ascending notes)
            const notes = [523.25, 659.25, 783.99]; // C5, E5, G5
            notes.forEach((freq, i) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.type = 'sine';
                osc.frequency.value = freq;
                gain.gain.setValueAtTime(0.3, ctx.currentTime + i * 0.2);
                gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + i * 0.2 + 0.5);
                osc.start(ctx.currentTime + i * 0.2);
                osc.stop(ctx.currentTime + i * 0.2 + 0.5);
            });

            // Second chime after a pause (repeat pattern)
            setTimeout(() => {
                notes.forEach((freq, i) => {
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.type = 'sine';
                    osc.frequency.value = freq;
                    gain.gain.setValueAtTime(0.25, ctx.currentTime + i * 0.2);
                    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + i * 0.2 + 0.5);
                    osc.start(ctx.currentTime + i * 0.2);
                    osc.stop(ctx.currentTime + i * 0.2 + 0.5);
                });
            }, 800);
        } catch (e) {
            console.warn('Audio alarm failed:', e);
        }
    }

    // ===== VISUAL CELEBRATION =====
    function showTimerCelebration(materia, totalSeconds) {
        const overlay = document.createElement('div');
        overlay.id = 'timer-celebration-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(30,30,46,0.92);z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;animation:fadeInCelebration 0.3s ease;';
        const minutos = Math.round(totalSeconds / 60);
        overlay.innerHTML = `
            <style>
                @keyframes fadeInCelebration { from { opacity: 0; } to { opacity: 1; } }
                @keyframes bounceIn { 0% { transform: scale(0); } 50% { transform: scale(1.2); } 100% { transform: scale(1); } }
                @keyframes confettiDrop { 0% { transform: translateY(-100vh) rotate(0deg); opacity: 1; } 100% { transform: translateY(100vh) rotate(720deg); opacity: 0; } }
                .confetti-piece { position: absolute; width: 10px; height: 10px; animation: confettiDrop 3s ease-out forwards; }
            </style>
            <div id="confetti-container" style="position:absolute;inset:0;overflow:hidden;pointer-events:none;"></div>
            <div style="animation:bounceIn 0.5s ease;text-align:center;z-index:1;">
                <div style="font-size:4rem;margin-bottom:16px;">🎉</div>
                <h2 style="color:#a6e3a1;font-size:1.8rem;margin:0 0 8px;">Sessão Concluída!</h2>
                <p style="color:#cdd6f4;font-size:1.1rem;margin:0 0 4px;">📚 ${materia}</p>
                <p style="color:#cba6f7;font-size:1.3rem;font-weight:700;margin:0 0 20px;">⏱ ${minutos} minuto${minutos !== 1 ? 's' : ''} de foco</p>
                <button onclick="document.getElementById('timer-celebration-overlay').remove()" style="background:#cba6f7;color:#1e1e2e;border:none;border-radius:8px;padding:12px 32px;font-size:1rem;font-weight:600;cursor:pointer;">Continuar</button>
            </div>
        `;
        document.body.appendChild(overlay);

        // Spawn confetti
        const container = overlay.querySelector('#confetti-container');
        const colors = ['#f38ba8','#a6e3a1','#89b4fa','#f9e2af','#cba6f7','#fab387','#94e2d5'];
        for (let i = 0; i < 60; i++) {
            const piece = document.createElement('div');
            piece.className = 'confetti-piece';
            piece.style.left = Math.random() * 100 + '%';
            piece.style.background = colors[Math.floor(Math.random() * colors.length)];
            piece.style.borderRadius = Math.random() > 0.5 ? '50%' : '2px';
            piece.style.animationDelay = Math.random() * 1.5 + 's';
            piece.style.animationDuration = (2 + Math.random() * 2) + 's';
            container.appendChild(piece);
        }

        // Auto-dismiss after 6 seconds
        setTimeout(() => { if (overlay.parentNode) overlay.remove(); }, 6000);
    }

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
        div.setAttribute('role', 'timer');
        div.setAttribute('aria-live', 'polite');
        div.setAttribute('aria-label', 'Timer de estudo');
        div.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;">
                <span id="gtw-materia" style="font-size:0.75rem;color:#cba6f7;font-weight:600;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></span>
                <span id="gtw-time" style="font-size:1.1rem;font-weight:700;color:#cdd6f4;font-family:monospace;"></span>
                <button id="gtw-pause" onclick="globalTimerToggle()" style="background:#a6e3a1;color:#1e1e2e;border:none;border-radius:4px;padding:3px 8px;font-size:0.7rem;font-weight:600;cursor:pointer;">⏸</button>
                <button onclick="globalTimerStop()" style="background:#f38ba8;color:#1e1e2e;border:none;border-radius:4px;padding:3px 8px;font-size:0.7rem;font-weight:600;cursor:pointer;">⏹</button>
                <a href="/dashboard.html" style="font-size:0.65rem;color:#89b4fa;text-decoration:none;" title="Voltar ao calendário">📅</a>
            </div>
        `;
        div.style.cssText = 'position:fixed;bottom:16px;left:16px;background:#313244;border:2px solid #cba6f7;border-radius:12px;padding:10px 14px;z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,0.4);';
        document.body.appendChild(div);
    }

    function removeWidget() {
        const w = document.getElementById('global-timer-widget');
        if (w) w.remove();
    }

    let alarmPlayed = false;

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

                // Play alarm sound and show notification ONCE
                if (!alarmPlayed) {
                    alarmPlayed = true;
                    playAlarmSound();

                    // Browser notification
                    if (Notification.permission === 'granted') {
                        new Notification('⏰ Timer finalizado!', {
                            body: `Sessão de ${state.materia} concluída! (${Math.round(state.totalSeconds / 60)} min)`,
                            icon: '🎉',
                            tag: 'timer-complete',
                            requireInteraction: true
                        });
                    }

                    // Show celebration overlay
                    showTimerCelebration(state.materia, state.totalSeconds);
                }

                const horas = state.totalSeconds / 3600;
                fetch('/api/sessoes-estudo/registrar', {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ horas: Math.round(horas * 100) / 100, materia: state.materia, tipo: 'pomodoro' })
                }).catch(() => {});
                clearTimerState();
                setTimeout(() => {
                    removeWidget();
                    alarmPlayed = false;
                }, 5000);
                return;
            }

            timeEl.textContent = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
            timeEl.style.color = totalSec < 60 ? '#f38ba8' : '#cdd6f4';

            // Play a tick sound at 10 seconds remaining
            if (totalSec === 10 && !state._tickPlayed) {
                state._tickPlayed = true;
                try {
                    if (!alarmAudioCtx) alarmAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
                    const osc = alarmAudioCtx.createOscillator();
                    const gain = alarmAudioCtx.createGain();
                    osc.connect(gain); gain.connect(alarmAudioCtx.destination);
                    osc.type = 'sine'; osc.frequency.value = 440;
                    gain.gain.setValueAtTime(0.15, alarmAudioCtx.currentTime);
                    gain.gain.exponentialRampToValueAtTime(0.01, alarmAudioCtx.currentTime + 0.2);
                    osc.start(); osc.stop(alarmAudioCtx.currentTime + 0.2);
                } catch(e) {}
            }
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
        if (typeof confirmModal === 'function') {
            confirmModal('Parar Timer', 'Deseja parar o timer e voltar ao calendário?', { confirmText: 'Parar', type: 'warning', icon: '⏹' }).then(ok => {
                if (ok) { clearTimerState(); removeWidget(); stopTimerLoop(); alarmPlayed = false; window.location.href = '/dashboard.html'; }
            });
        } else if (confirm('Parar o timer e voltar ao calendário?')) {
            clearTimerState();
            removeWidget();
            stopTimerLoop();
            alarmPlayed = false;
            window.location.href = '/dashboard.html';
        }
    };

    window.startGlobalTimer = function(materia, tempoMin, tipo) {
        alarmPlayed = false;
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
        startTimerLoop();
    };

    // Loop: otimizado — só roda setInterval quando há timer ativo
    let timerIntervalId = null;

    function startTimerLoop() {
        if (timerIntervalId) return; // já rodando
        timerIntervalId = setInterval(() => {
            const state = getTimerState();
            if (state) {
                if (!document.getElementById('global-timer-widget')) createWidget();
                updateWidget(state);
            } else {
                removeWidget();
                stopTimerLoop();
            }
        }, 1000);
    }

    function stopTimerLoop() {
        if (timerIntervalId) {
            clearInterval(timerIntervalId);
            timerIntervalId = null;
        }
    }

    // Pausar/retomar com visibilidade da aba
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopTimerLoop();
        } else {
            // Ao voltar, verificar se ainda há timer e reiniciar loop
            const state = getTimerState();
            if (state) {
                if (!document.getElementById('global-timer-widget')) createWidget();
                updateWidget(state);
                startTimerLoop();
            }
        }
    });

    // Check inicial — só inicia loop se há timer
    const initialState = getTimerState();
    if (initialState) {
        createWidget();
        updateWidget(initialState);
        startTimerLoop();
    }

    // Pedir permissão de notificação
    if (Notification.permission === 'default') Notification.requestPermission();

    // ===== ADAPTIVE POMODORO — Fatigue Detection =====
    // Monitors accuracy/speed during sessions and suggests breaks
    window._adaptivePomo = {
        sessionAnswers: [],  // {timestamp, correct, tempo_s}
        lastCheckTimestamp: Date.now(),
        breakSuggested: false,

        // Called by flashcard/question review to feed accuracy data
        recordAnswer(correct, tempoSeconds) {
            this.sessionAnswers.push({
                timestamp: Date.now(),
                correct: !!correct,
                tempo_s: tempoSeconds || 0
            });
            this._checkFatigue();
        },

        _checkFatigue() {
            // Need at least 6 answers to detect pattern
            if (this.sessionAnswers.length < 6) return;
            if (this.breakSuggested) return; // Already suggested this cycle

            const recent = this.sessionAnswers.slice(-6);
            const older = this.sessionAnswers.slice(-12, -6);

            // Check 1: Recent accuracy dropped significantly
            const recentAcc = recent.filter(a => a.correct).length / recent.length;
            const olderAcc = older.length >= 3
                ? older.filter(a => a.correct).length / older.length
                : 0.7; // assume 70% baseline

            // Check 2: Response time increasing (fatigue sign)
            const recentAvgTime = recent.reduce((s, a) => s + a.tempo_s, 0) / recent.length;
            const olderAvgTime = older.length >= 3
                ? older.reduce((s, a) => s + a.tempo_s, 0) / older.length
                : recentAvgTime;

            const accuracyDrop = olderAcc - recentAcc;
            const timeIncrease = recentAvgTime / (olderAvgTime || 1);

            // Fatigue detected: accuracy dropped >20% OR response time increased >50%
            if (accuracyDrop > 0.20 || timeIncrease > 1.5) {
                this.breakSuggested = true;
                this._suggestBreak(recentAcc, accuracyDrop, timeIncrease);
            }
        },

        _suggestBreak(currentAcc, drop, timeRatio) {
            const pct = Math.round(currentAcc * 100);
            const dropPct = Math.round(drop * 100);
            let reason = '';
            if (drop > 0.20) reason = `Acerto caiu ${dropPct}% (agora ${pct}%)`;
            else reason = `Tempo de resposta aumentou ${Math.round((timeRatio - 1) * 100)}%`;

            // Create a non-intrusive notification banner
            const banner = document.createElement('div');
            banner.id = 'fatigue-banner';
            banner.style.cssText = 'position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:99998;background:linear-gradient(135deg,var(--peach),var(--yellow));color:var(--bg);padding:12px 20px;border-radius:12px;font-size:0.85rem;font-weight:600;box-shadow:0 4px 20px rgba(0,0,0,0.3);display:flex;align-items:center;gap:12px;max-width:90vw;animation:slideDown 0.3s ease;';
            banner.innerHTML = `
                <span style="font-size:1.4rem;">😴</span>
                <div>
                    <div>Cansaço detectado — ${reason}</div>
                    <div style="font-size:0.72rem;opacity:0.8;margin-top:2px;">Fazer uma pausa de 5-10min melhora a retenção em até 20%</div>
                </div>
                <button onclick="this.parentElement.remove();window._adaptivePomo.breakSuggested=false;" style="background:rgba(0,0,0,0.2);border:none;color:var(--bg);border-radius:6px;padding:6px 12px;cursor:pointer;font-weight:600;font-size:0.78rem;white-space:nowrap;">Entendi ✓</button>
            `;
            document.body.appendChild(banner);

            // Auto-dismiss after 15 seconds
            setTimeout(() => {
                if (banner.parentNode) banner.remove();
            }, 15000);
        },

        // Reset on new session
        reset() {
            this.sessionAnswers = [];
            this.breakSuggested = false;
            this.lastCheckTimestamp = Date.now();
        }
    };
})();
