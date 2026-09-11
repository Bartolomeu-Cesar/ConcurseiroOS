"""Scheduler de background para os triggers de notificação push.

Os gatilhos de notificação (streak em risco, flashcards/edital/caderno de erros
vencidos, meta diária, sleep consolidation, etc.) já existem em
`routers.notifications.run_trigger_checks`, mas precisam ser DISPARADOS
periodicamente — senão ficam dormentes. Este módulo agenda essa verificação em
uma thread daemon, seguindo o mesmo padrão de `backup.schedule_daily_backup`.

Por que threading.Timer (e não APScheduler/Celery): o projeto é um monolito
SQLite single-node; adicionar um broker/serviço externo seria overkill. O Timer
daemon roda em background sem impedir o shutdown do processo e se re-agenda.

Segurança de concorrência: cada execução abre a PRÓPRIA conexão SQLite (WAL +
busy_timeout), como o resto do app, evitando compartilhar conexão entre threads.
Os próprios triggers têm rate-limit por dia/tag e respeitam quiet hours, então
rodar a cada N minutos apenas garante que a janela horária correta seja pega —
não gera spam.
"""
import sqlite3
import threading

from logger import log
from settings import settings

_scheduler_timer: threading.Timer | None = None


def _open_conn(db_path: str) -> sqlite3.Connection:
    """Abre uma conexão SQLite no mesmo modo usado pelo app (WAL, row factory)."""
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return conn


def run_once(db_path: str | None = None) -> dict:
    """Executa uma verificação de gatilhos agora, com conexão própria.

    Retorna o resultado de `run_trigger_checks` (ou dict de erro). Não levanta
    exceção — o scheduler não pode morrer por causa de uma falha pontual.
    """
    if db_path is None:
        db_path = settings.DB_PATH

    conn = None
    try:
        # Import tardio para evitar ciclo de import no startup do main.
        from routers.notifications import run_trigger_checks

        conn = _open_conn(db_path)
        result = run_trigger_checks(conn)
        return result
    except Exception as e:
        log.error(f"push_scheduler: erro ao verificar triggers: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def schedule_trigger_checks(db_path: str | None = None):
    """Agenda a verificação periódica de triggers de push.

    Roda a cada `PUSH_SCHEDULER_INTERVAL_MINUTES` numa thread daemon que se
    re-agenda. Respeita a flag `PUSH_SCHEDULER_ENABLED`. Idempotente: cancela um
    timer anterior antes de criar outro.
    """
    global _scheduler_timer

    if not getattr(settings, "PUSH_SCHEDULER_ENABLED", True):
        log.info("push_scheduler: desabilitado (PUSH_SCHEDULER_ENABLED=false)")
        return

    if db_path is None:
        db_path = settings.DB_PATH

    # Cancela timer anterior (evita múltiplos agendamentos em reload).
    if _scheduler_timer is not None:
        try:
            _scheduler_timer.cancel()
        except Exception:
            pass

    interval_minutes = max(1, getattr(settings, "PUSH_SCHEDULER_INTERVAL_MINUTES", 30))
    interval_seconds = interval_minutes * 60

    def _tick():
        try:
            result = run_once(db_path)
            enviados = result.get("notifications_sent") if isinstance(result, dict) else None
            if enviados:
                total = sum(v for v in enviados.values() if isinstance(v, int))
                if total > 0:
                    log.info(f"push_scheduler: {total} notificação(ões) enviada(s)")
        finally:
            # Re-agenda o próximo tick.
            schedule_trigger_checks(db_path)

    _scheduler_timer = threading.Timer(interval_seconds, _tick)
    _scheduler_timer.daemon = True
    _scheduler_timer.start()
    log.info(f"push_scheduler: agendado a cada {interval_minutes} min")


def stop_scheduler():
    """Cancela o scheduler (usado em testes/shutdown)."""
    global _scheduler_timer
    if _scheduler_timer is not None:
        try:
            _scheduler_timer.cancel()
        except Exception:
            pass
        _scheduler_timer = None
